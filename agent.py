import json
import os
from pathlib import Path

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, MessagesState, StateGraph

from tools.traceability_check import traceability_check as run_check


# Extend LangGraph's message state to record the post-tool routing decision.
# This value is for execution tracing, not a message sent to the LLM.
class ReviewState(MessagesState):
    tool_decision: dict[str, str]


# 1. Python tool: perform a real Excel traceability check.
@tool("traceability_check")
def check_excel(file_path: str) -> str:
    """Check SG, FSR, and TSR traceability in an Excel file.

    Args:
        file_path: Excel filename inside the test_data directory.
    """
    if (
        not file_path
        or file_path in (".", "..")
        or "/" in file_path
        or "\\" in file_path
        or not file_path.lower().endswith(".xlsx")
    ):
        return json.dumps(
            {
                "status": "error",
                "message": "Only .xlsx filenames in test_data are allowed",
            },
            ensure_ascii=False,
        )

    path = Path("/app/test_data") / file_path
    result = run_check(str(path))
    return json.dumps(result, ensure_ascii=False)


# 2. LLM: call Ollama through the Podman network.
model = ChatOllama(
    model="qwen3:4b-instruct",
    base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
    temperature=0,
)
model_with_tools = model.bind_tools([check_excel])

SYSTEM_PROMPT = """
You are an ISO 26262 functional safety document review agent.

Definitions:
- SG = Safety Goal
- FSR = Functional Safety Requirement
- TSR = Technical Safety Requirement

When the user requests an Excel traceability review:
1. Call the traceability_check tool with the specified filename.
2. Read the real tool observation before reporting any findings.
3. Answer in Traditional Chinese. Cite requirement IDs and Excel row numbers only
   if they are present in the tool observation.
4. Treat missing traceability as a potential documentation gap, not as proof of
   ISO 26262 non-compliance.
5. Never invent ISO clauses, rows, IDs, missing columns, or test results.
6. Never recommend deleting a safety requirement based only on missing links.
7. Distinguish input-format errors from actual traceability findings.
8. The tool performs structural checks only. Neither compliance nor
   non-compliance with ISO 26262 has been established by this check.
9. Never say that an item 'does not violate ISO 26262' without verifying the
   applicable standards. State that compliance has not been assessed instead.

Project-defined Excel schema (not mandated column names by ISO 26262):
- SG sheet: ID, Description
- FSR sheet: ID, SG_ID, Description
- TSR sheet: ID, FSR_ID, Description

If the tool reports an error, do not invent results. The graph handles errors
through a deterministic error node.
"""


# 3. Agent node: ask the model to decide whether to call a tool.
def agent_node(state: ReviewState):
    response = model_with_tools.invoke(
        [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    )
    return {"messages": [response]}


# 4. Tool node: actually execute the Python tool(s).
def tool_node(state: ReviewState):
    observations = []

    for call in state["messages"][-1].tool_calls:
        try:
            if call["name"] != "traceability_check":
                raise ValueError(f"Unknown tool: {call['name']}")
            result = check_excel.invoke(call["args"])
        except Exception as exc:
            result = json.dumps(
                {"status": "error", "message": str(exc)},
                ensure_ascii=False,
            )

        observations.append(
            ToolMessage(content=result, tool_call_id=call["id"])
        )

    return {"messages": observations}


# 5. Decision after an LLM response: call tools or finish.
def route_after_agent(state: ReviewState):
    if getattr(state["messages"][-1], "tool_calls", None):
        return "tools"
    return END


# 6. Collect observations from the most recent tool batch.
def latest_tool_observations(state: ReviewState):
    observations = []

    for message in reversed(state["messages"]):
        if isinstance(message, ToolMessage):
            try:
                data = json.loads(message.content)
                if not isinstance(data, dict):
                    raise ValueError("Tool result must be a JSON object")
            except (ValueError, TypeError):
                data = {"status": "error", "message": "Invalid tool response"}
            observations.append(data)
        elif isinstance(message, AIMessage):
            break

    return list(reversed(observations))


# 7. New decision node: make the post-observation decision visible in Trace.
# Returning a separate state field avoids inserting an artificial message
# between the assistant's tool calls and the corresponding ToolMessages.
def decision_node(state: ReviewState):
    observations = latest_tool_observations(state)
    all_success = bool(observations) and all(
        item.get("status") == "success" for item in observations
    )

    if all_success:
        decision = {
            "status": "success",
            "next_node": "agent",
            "reason": "Tool check succeeded; return results to the LLM for analysis.",
        }
    else:
        decision = {
            "status": "error",
            "next_node": "error",
            "reason": "Tool check failed or response was invalid; use fixed error handling.",
        }

    return {"tool_decision": decision}


def route_after_decision(state: ReviewState):
    return state["tool_decision"]["next_node"]


# 8. Error node: build a deterministic answer from observed errors.
def error_node(state: ReviewState):
    observations = latest_tool_observations(state)
    errors = [
        str(item.get("message", "Unknown tool error"))
        for item in observations
        if item.get("status") != "success"
    ]
    if not errors:
        errors = ["No valid tool observations"]

    final_message = (
        "本次追溯性檢查無法完成。\n"
        f"工具回報：{'；'.join(errors)}\n"
        "請確認並修正輸入檔案後重新執行。\n"
        "由於檢查未完成，無法判定需求追溯關係是否完整，"
        "也無法據此判定 ISO 26262 符合性。"
    )
    return {"messages": [AIMessage(content=final_message)]}


# 9. Graph: agent -> tools -> decision -> agent/error.
builder = StateGraph(ReviewState)
builder.add_node("agent", agent_node)
builder.add_node("tools", tool_node)
builder.add_node("decision", decision_node)
builder.add_node("error", error_node)

builder.add_edge(START, "agent")
builder.add_conditional_edges(
    "agent",
    route_after_agent,
    {"tools": "tools", END: END},
)
builder.add_edge("tools", "decision")
builder.add_conditional_edges(
    "decision",
    route_after_decision,
    {"agent": "agent", "error": "error"},
)
builder.add_edge("error", END)

graph = builder.compile()


# 10. Command-line entry point: emit a fully inspectable Agent Trace.
if __name__ == "__main__":
    file_name = os.getenv("REVIEW_FILE", "safety_requirements.xlsx")
    question = (
        f"請使用工具檢查 {file_name} 的 SG、FSR、TSR 追溯關係，"
        "列出問題與 Excel 列號。如果檔案不存在，請明確回報錯誤，"
        "不要自行推測審查結果。"
    )

    print("=== User Input ===", flush=True)
    print(question, flush=True)

    events = graph.stream(
        {"messages": [HumanMessage(content=question)]},
        config={"recursion_limit": 8},
        stream_mode="updates",
    )

    for event in events:
        for node, update in event.items():
            if node == "decision":
                decision = update["tool_decision"]
                print("\n=== Agent Decision (after Observation) ===")
                print("Observation Status:", decision["status"])
                print("Next Node:", decision["next_node"])
                print("Reason:", decision["reason"], flush=True)
                continue

            for message in update.get("messages", []):
                if node == "tools":
                    print("\n=== Observation ===")
                    print(message.content, flush=True)
                elif getattr(message, "tool_calls", None):
                    print("\n=== Agent Decision (before Tool Call) ===")
                    print("Decision: call the tool(s) listed below")
                    print("\n=== Tool Call ===")
                    for call in message.tool_calls:
                        print("Tool:", call["name"])
                        print("Arguments:", call["args"], flush=True)
                elif node in ("agent", "error"):
                    print("\n=== Final Answer ===")
                    print(message.content, flush=True)
