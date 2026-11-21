"""ISO 26262 SG/FSR/TSR structural traceability review Agent (Assignment 2 MVP).

Architecture: LLM Tool Calling -> Python Tool -> Observation -> state-based
Decision -> deterministic final result or error. The Tool checks project-defined
Excel IDs, not ISO 26262 compliance.

Compatible with the existing Containerfile, requirements.txt and
`tools/traceability_check.py`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, MessagesState, StateGraph

from tools.traceability_check import traceability_check as run_check


# The container mounts/copies its project into /app; resolve relative to this
# program to support ordinary local Python execution as well.
DATA_DIR = Path(__file__).resolve().parent / "test_data"
MODEL_NAME = os.getenv("OLLAMA_MODEL", "qwen3:4b-instruct")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
MAX_LLM_ATTEMPTS = 2  # One initial request + at most one bounded retry.


class ReviewState(MessagesState):
    """LangGraph state; `messages` uses the built-in append reducer."""

    requested_file: str
    llm_attempts: int
    llm_error: str
    tool_decision: dict[str, Any]
    verified_result: dict[str, Any]


@tool("traceability_check")
def check_excel(file_path: str) -> str:
    """Review SG/FSR/TSR references in one Excel file under test_data.

    Args:
        file_path: A single .xlsx filename, not a directory or absolute path.
    """
    if (
        not isinstance(file_path, str)
        or not file_path
        or file_path.strip() != file_path
        or file_path in (".", "..")
        or "/" in file_path
        or "\\" in file_path
        or "\x00" in file_path
        or not file_path.lower().endswith(".xlsx")
    ):
        result = {
            "status": "error",
            "message": "Only .xlsx filenames in test_data are allowed",
        }
    else:
        try:
            result = run_check(str(DATA_DIR / file_path))
        except Exception as exc:
            result = {"status": "error", "message": f"Tool execution failed: {exc}"}
    return json.dumps(result, ensure_ascii=False)


SYSTEM_PROMPT = """You are an ISO 26262 functional safety document review assistant.
This project currently checks ONLY structural SG -> FSR -> TSR references in
project-defined Excel sheets. It does NOT verify ISO 26262 clauses or compliance.
When asked to review an Excel file:
- Use the traceability_check tool with exactly the supplied .xlsx filename.
- Do not claim to have inspected the file without the tool observation.
- Do not invent standards, requirement IDs, row numbers, findings, or evidence.
- Tool names, sheet headers (SG / FSR / TSR), and file names are project-specific.
The program uses deterministic routing and final reporting based on the tool output.
"""


# The LLM selects the Tool; it does NOT execute Python or read Excel itself.
model = ChatOllama(
    model=MODEL_NAME,
    base_url=OLLAMA_BASE_URL,
    temperature=0,
)
model_with_tools = model.bind_tools([check_excel])


def agent_node(state: ReviewState) -> dict[str, Any]:
    """Ask the LLM to choose a tool; return errors as state, not exceptions."""
    attempts = state.get("llm_attempts", 0) + 1
    try:
        response = model_with_tools.invoke(
            [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
        )
        if not isinstance(response, AIMessage):
            raise TypeError("LLM returned a non-AIMessage response")
        return {"messages": [response], "llm_attempts": attempts, "llm_error": ""}
    except Exception as exc:
        return {
            "llm_attempts": attempts,
            "llm_error": f"LLM service error ({type(exc).__name__}): {exc}",
        }


def route_after_agent(state: ReviewState) -> str:
    """An Excel review cannot end successfully without a real Tool Call."""
    if state.get("llm_error"):
        return "error"
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    if state.get("llm_attempts", 0) < MAX_LLM_ATTEMPTS:
        return "retry"
    return "no_tool"


def retry_node(state: ReviewState) -> dict[str, Any]:
    """Give the LLM one more opportunity without an infinite loop."""
    return {
        "messages": [HumanMessage(content=(
            "你尚未呼叫 traceability_check。這是實際 Excel 審查工作，"
            f"請現在使用工具檢查 {state['requested_file']}，不要先提供結果。"
        ))]
    }


def _tool_error(message: str) -> str:
    return json.dumps({"status": "error", "message": message}, ensure_ascii=False)


def tool_node(state: ReviewState) -> dict[str, Any]:
    """Execute only the requested Tool, and never silently change its filename."""
    calls = getattr(state["messages"][-1], "tool_calls", None) or []
    replies: list[ToolMessage] = []
    multiple = len(calls) != 1
    if not calls:
        return {"messages": [ToolMessage(
            content=_tool_error("No tool call was supplied"),
            tool_call_id="missing-tool-call-id",
        )]}

    for call in calls:
        call_id = call.get("id") or "missing-tool-call-id"
        name = call.get("name")
        args = call.get("args")
        try:
            if multiple:
                result = _tool_error("Exactly one traceability_check Tool Call is required")
            elif name != "traceability_check":
                result = _tool_error(f"Unknown tool: {name}")
            elif not isinstance(args, dict) or not isinstance(args.get("file_path"), str):
                result = _tool_error("Tool argument file_path must be a string")
            elif args["file_path"] != state["requested_file"]:
                result = _tool_error(
                    "Tool filename does not match the requested REVIEW_FILE"
                )
            else:
                # LangChain @tool accepts a dictionary of validated inputs.
                result = check_excel.invoke({"file_path": args["file_path"]})
        except Exception as exc:
            result = _tool_error(f"Tool invocation error ({type(exc).__name__}): {exc}")
        replies.append(ToolMessage(content=result, tool_call_id=call_id))
    return {"messages": replies}


def latest_tool_observations(state: ReviewState) -> list[dict[str, Any]]:
    """Read the most recent contiguous ToolMessage batch."""
    observations: list[dict[str, Any]] = []
    for message in reversed(state["messages"]):
        if not isinstance(message, ToolMessage):
            break
        try:
            decoded = json.loads(message.content)
            if not isinstance(decoded, dict):
                raise ValueError("Tool response must be a JSON object")
        except (ValueError, TypeError):
            decoded = {"status": "error", "message": "Invalid tool response JSON"}
        observations.append(decoded)
    return list(reversed(observations))


def _valid_success(value: dict[str, Any]) -> bool:
    """Fail closed on malformed or inconsistent success observations."""
    summary, issues = value.get("summary"), value.get("issues")
    if not isinstance(summary, dict) or not isinstance(issues, list):
        return False
    try:
        if summary.get("issue_count") != len(issues):
            return False
        if any(type(summary.get(key)) is not int or summary[key] < 0
               for key in ("SG_count", "FSR_count", "TSR_count", "issue_count")):
            return False
        for issue in issues:
            if not isinstance(issue, dict):
                return False
            if not isinstance(issue.get("type"), str) or not issue["type"]:
                return False
            if not isinstance(issue.get("requirement"), str):
                return False
            if type(issue.get("row")) is not int or issue["row"] < 2:
                return False
        return True
    except (TypeError, KeyError, ValueError):
        return False


def decision_node(state: ReviewState) -> dict[str, Any]:
    """Second Agent Decision: inspect actual Observation, not model guesses."""
    observations = latest_tool_observations(state)
    if len(observations) == 1 and observations[0].get("status") == "success" \
            and _valid_success(observations[0]):
        return {
            "verified_result": observations[0],
            "tool_decision": {
                "status": "success",
                "next_node": "finalize",
                "reason": "Valid Tool Observation; produce an evidence-based final result.",
            },
        }

    if not observations:
        reason = "No Tool Observation was returned"
    elif any(o.get("status") == "error" for o in observations):
        reason = "；".join(
            str(o.get("message") or "Unknown tool error")
            for o in observations if o.get("status") == "error"
        )
    else:
        reason = "Invalid or inconsistent Tool Observation"

    return {
        "tool_decision": {
            "status": "error",
            "next_node": "error",
            "reason": reason,
        },
    }


def route_after_decision(state: ReviewState) -> str:
    return str(state["tool_decision"]["next_node"])


def finalize_node(state: ReviewState) -> dict[str, Any]:
    """Only report facts actually returned by a successful Python Tool."""
    result = state["verified_result"]
    summary = result["summary"]
    issues = result["issues"]
    lines = [
        "SG／FSR／TSR 結構化追溯性檢查已完成（工具執行成功）。",
        f"SG：{summary['SG_count']} 筆；FSR：{summary['FSR_count']} 筆；"
        f"TSR：{summary['TSR_count']} 筆。",
    ]
    if issues:
        lines.append(f"發現 {len(issues)} 項追溯性問題：")
        for issue in issues:
            lines.append(
                f"- {issue['type']}：{issue['requirement']}（Excel 第 {issue['row']} 列）。"
            )
    else:
        lines.append("未發現本工具可檢查的結構化 ID 追溯性問題。")
    lines.append(
        "注意：這是模擬 Excel 的結構檢查，並非 ISO 26262 條款或符合性判定。"
    )
    return {"messages": [AIMessage(content="\n".join(lines))]}


def no_tool_node(state: ReviewState) -> dict[str, Any]:
    return {"messages": [AIMessage(content=(
        "本次追溯性檢查無法完成：LLM 經有限次嘗試後仍未呼叫 "
        "traceability_check 工具，沒有取得任何 Excel 檢查結果。\n"
        "無法判定追溯性或 ISO 26262 符合性。"
    ))]}


def error_node(state: ReviewState) -> dict[str, Any]:
    """Program-generated error answer, not another LLM hallucination."""
    reason = state.get("llm_error") or state.get("tool_decision", {}).get(
        "reason", "Unknown Agent error"
    )
    return {"messages": [AIMessage(content=(
        "本次追溯性檢查無法完成。\n"
        f"錯誤原因：{reason}\n"
        "請確認檔案、模型服務或工具輸入後重新執行。\n"
        "沒有可靠的檢查結果，不能判定追溯性或 ISO 26262 符合性。"
    ))]}


# StateGraph defines the workflow explicitly; no open-ended ReAct loop.
builder = StateGraph(ReviewState)
builder.add_node("agent", agent_node)
builder.add_node("retry", retry_node)
builder.add_node("tools", tool_node)
builder.add_node("decision", decision_node)
builder.add_node("finalize", finalize_node)
builder.add_node("no_tool", no_tool_node)
builder.add_node("error", error_node)

builder.add_edge(START, "agent")
builder.add_conditional_edges(
    "agent",
    route_after_agent,
    {"tools": "tools", "retry": "retry", "no_tool": "no_tool", "error": "error"},
)
builder.add_edge("retry", "agent")
builder.add_edge("tools", "decision")
builder.add_conditional_edges(
    "decision", route_after_decision,
    {"finalize": "finalize", "error": "error"},
)
for terminal_node in ("finalize", "no_tool", "error"):
    builder.add_edge(terminal_node, END)

graph = builder.compile()


def main() -> None:
    file_name = os.getenv("REVIEW_FILE", "safety_requirements.xlsx")
    question = (
        f"請使用工具檢查 {file_name} 的 SG、FSR、TSR 追溯關係，"
        "列出問題與 Excel 列號；如果檢查無法完成，請回報錯誤。"
    )
    print("=== User Input ===", flush=True)
    print(question, flush=True)

    initial_state = {
        "messages": [HumanMessage(content=question)],
        "requested_file": file_name,
        "llm_attempts": 0,
        "llm_error": "",
    }
    # CLI contract: only a completed, validated Tool review exits with 0.
    # All errors (including intentionally handled Failure Cases) exit nonzero.
    terminal_node_seen = None
    try:
        for event in graph.stream(
            initial_state,
            config={"recursion_limit": 12},
            stream_mode="updates",
        ):
            for node, update in event.items():
                if node == "retry":
                    print("\n=== Agent Decision (no Tool Call) ===")
                    print("Decision: retry Tool Calling once", flush=True)
                elif node == "agent":
                    for message in update.get("messages", []):
                        if getattr(message, "tool_calls", None):
                            print("\n=== Agent Decision (before Tool Call) ===")
                            print("Decision: call the tool(s) listed below")
                            print("\n=== Tool Call ===")
                            for call in message.tool_calls:
                                print("Tool:", call.get("name"))
                                print("Arguments:", call.get("args"), flush=True)
                    if update.get("llm_error"):
                        print("\n=== Agent Decision (LLM Service Failure) ===")
                        print("Decision: error", flush=True)
                elif node == "tools":
                    for message in update.get("messages", []):
                        print("\n=== Observation ===")
                        print(message.content, flush=True)
                elif node == "decision":
                    decision = update["tool_decision"]
                    print("\n=== Agent Decision (after Observation) ===")
                    print("Observation Status:", decision["status"])
                    print("Next Node:", decision["next_node"])
                    print("Reason:", decision["reason"], flush=True)
                elif node in ("finalize", "error", "no_tool"):
                    terminal_node_seen = node
                    for message in update.get("messages", []):
                        print("\n=== Final Answer ===")
                        print(message.content, flush=True)
    except Exception as exc:
        # A clear CLI-level fallback for graph/runtime failures.
        print("\n=== Final Answer ===")
        print(f"Agent workflow error ({type(exc).__name__}): {exc}")
        print("沒有可靠的審查結果，不能判定 ISO 26262 符合性。", flush=True)
        raise SystemExit(1) from None

    if terminal_node_seen != "finalize":
        if terminal_node_seen is None:
            print("\n=== Final Answer ===")
            print("Agent workflow ended without a verified final result.", flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
