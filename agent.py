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


# 1. 實際執行 Excel 追溯性檢查的 Tool
@tool("traceability_check")
def check_excel(file_path: str) -> str:
    """Check SG, FSR, and TSR traceability in an Excel file.

    Args:
        file_path: Excel filename inside the test_data directory.
    """
    # 只允許讀取 /app/test_data 裡的 .xlsx 檔案，避免任意檔案存取。
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


# 2. 連接 Podman 網路中的 Ollama
model = ChatOllama(
    model="qwen3:4b-instruct",
    base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
    temperature=0,
)
tools = [check_excel]
model_with_tools = model.bind_tools(tools)

SYSTEM_PROMPT = """
You are an ISO 26262 functional safety document review agent.

Definitions:
- SG = Safety Goal
- FSR = Functional Safety Requirement
- TSR = Technical Safety Requirement

When the user requests an Excel traceability review:
1. Call the traceability_check tool with the specified filename.
2. Read the real tool observation before reporting any findings.
3. Answer in Traditional Chinese, citing requirement IDs and Excel row numbers
   only if the observation provides them.
4. Treat missing traceability as a potential documentation gap, not proof of
   non-compliance with ISO 26262.
5. Do not invent ISO clauses, affected rows, requirement IDs, or test results.
6. Do not recommend deleting safety requirements based only on missing links.
7. Distinguish input-format errors from actual traceability findings.
8. This tool checks structural relationships only; it does not confirm semantic
   consistency or formal ISO 26262 compliance.

Project Excel schema (not mandated column names by ISO 26262):
- SG sheet: ID, Description
- FSR sheet: ID, SG_ID, Description
- TSR sheet: ID, FSR_ID, Description

If the tool reports an error, do not invent results. The graph will handle the
error deterministically.
"""


# 3. Agent 節點：讓 LLM 決定是否呼叫 Tool
def agent_node(state: MessagesState):
    response = model_with_tools.invoke(
        [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    )
    return {"messages": [response]}


# 4. Tool 節點：實際執行 Python 函式，並回傳 Observation
def tool_node(state: MessagesState):
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


# 5. 判斷 LLM 是否要求呼叫 Tool
def route_after_agent(state: MessagesState):
    last_message = state["messages"][-1]
    if getattr(last_message, "tool_calls", None):
        return "tools"
    return END


# 6. 取得最近一次工具呼叫的所有 Observation
def latest_tool_observations(state: MessagesState):
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


# 7. 根據 Observation 分流：成功交給 LLM，失敗直接輸出錯誤
def route_after_tools(state: MessagesState):
    observations = latest_tool_observations(state)
    if observations and all(item.get("status") == "success" for item in observations):
        return "agent"
    return "error"


# 8. 錯誤節點：由程式組裝訊息，避免 LLM 編造欄位或行號
def error_node(state: MessagesState):
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


# 9. 建立 LangGraph
builder = StateGraph(MessagesState)
builder.add_node("agent", agent_node)
builder.add_node("tools", tool_node)
builder.add_node("error", error_node)

builder.add_edge(START, "agent")
builder.add_conditional_edges(
    "agent",
    route_after_agent,
    {"tools": "tools", END: END},
)
builder.add_conditional_edges(
    "tools",
    route_after_tools,
    {"agent": "agent", "error": "error"},
)
builder.add_edge("error", END)

graph = builder.compile()


# 10. 由環境變數指定測試檔案，並顯示 Agent Trace
if __name__ == "__main__":
    file_name = os.getenv("REVIEW_FILE", "safety_requirements.xlsx")

    question = (
        f"請使用工具檢查 {file_name} 的 SG、FSR、TSR 追溯關係，"
        "列出問題與 Excel 列號。如果檔案不存在，請明確回報錯誤，"
        "不要自行推測審查結果。"
    )

    print("=== User Input ===")
    print(question)

    events = graph.stream(
        {"messages": [HumanMessage(content=question)]},
        config={"recursion_limit": 8},
        stream_mode="updates",
    )

    for event in events:
        for node, update in event.items():
            for message in update.get("messages", []):
                if node == "tools":
                    print("\n=== Observation ===")
                    print(message.content)
                elif getattr(message, "tool_calls", None):
                    print("\n=== Agent Action ===")
                    for call in message.tool_calls:
                        print("Tool:", call["name"])
                        print("Arguments:", call["args"])
                elif node in ("agent", "error"):
                    print("\n=== Final Answer ===")
                    print(message.content)
