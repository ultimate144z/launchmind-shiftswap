"""LangGraph workflow definition for the LaunchMind ShiftSwap pipeline."""

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from agents import ceo_agent, engineer_agent, marketing_agent, product_agent, qa_agent
from message_bus import MessageBus


class PipelineState(TypedDict):
    startup_idea: str
    tasks_by_agent: dict
    product_spec: dict
    engineer_artifacts: dict
    marketing_artifacts: dict
    qa_report: dict
    revision_count: int
    message_log: Annotated[list, operator.add]


def _collect_new_messages(state: PipelineState, bus: MessageBus) -> list:
    """Collect only new messages from bus.full_history() since last node ran."""
    existing_count = len(state.get("message_log", []))
    all_messages = bus.full_history()
    return [m.model_dump() for m in all_messages[existing_count:]]


def ceo_decompose_node(state: PipelineState, bus: MessageBus) -> dict:
    if hasattr(ceo_agent, "decompose"):
        result = ceo_agent.decompose(state, bus)
    else:
        result = ceo_agent.run(bus, {"idea": state.get("startup_idea", "")})

    # decompose() returns {"tasks_by_agent": tasks} — unwrap one level
    if isinstance(result, dict):
        tasks = result.get("tasks_by_agent", result)
    else:
        tasks = {}

    return {
        "tasks_by_agent": tasks,
        "message_log": _collect_new_messages(state, bus),
    }


def product_node(state: PipelineState, bus: MessageBus) -> dict:
    result = product_agent.run(state, bus)

    # run() returns {"product_spec": spec} — unwrap one level
    if isinstance(result, dict):
        spec = result.get("product_spec", result)
    else:
        spec = {}

    return {
        "product_spec": spec,
        "message_log": _collect_new_messages(state, bus),
    }


def engineer_node(state: PipelineState, bus: MessageBus) -> dict:
    result = engineer_agent.run(bus, state.get("product_spec", {}))

    if isinstance(result, dict):
        artifacts = result.get("engineer_artifacts", result)
    else:
        artifacts = {}

    return {
        "engineer_artifacts": artifacts,
        "message_log": _collect_new_messages(state, bus),
    }


def marketing_node(state: PipelineState, bus: MessageBus) -> dict:
    # Pass product_spec and PR URL so marketing can include it in Slack post
    context = dict(state.get("product_spec", {}))
    context["pr_url"] = state.get("engineer_artifacts", {}).get("pr_url", "")
    context["startup_idea"] = state.get("startup_idea", "")
    result = marketing_agent.run(bus, context)
    return {
        "marketing_artifacts": result if isinstance(result, dict) else {},
        "message_log": _collect_new_messages(state, bus),
    }


def qa_node(state: PipelineState, bus: MessageBus) -> dict:
    qa_input = {
        "engineer_artifacts": state.get("engineer_artifacts", {}),
        "marketing_artifacts": state.get("marketing_artifacts", {}),
        "product_spec": state.get("product_spec", {}),
    }
    result = qa_agent.run(bus, qa_input)

    qa_report = result if isinstance(result, dict) else {}
    if "verdict" not in qa_report:
        qa_report["verdict"] = "pass"

    return {
        "qa_report": qa_report,
        "message_log": _collect_new_messages(state, bus),
    }


def ceo_review_node(state: PipelineState, bus: MessageBus) -> dict:
    if hasattr(ceo_agent, "review"):
        result = ceo_agent.review(state, bus)
    else:
        result = state.get("qa_report", {})

    qa_report = result if isinstance(result, dict) else state.get("qa_report", {})
    verdict = str(qa_report.get("verdict", "pass")).lower()
    revision_count = state.get("revision_count", 0)
    if verdict == "fail":
        revision_count += 1

    return {
        "qa_report": qa_report,
        "revision_count": revision_count,
        "message_log": _collect_new_messages(state, bus),
    }




def ceo_final_summary_node(state: PipelineState, bus: MessageBus) -> dict:
    result = ceo_agent.post_final_summary(state, bus)
    return {
        "message_log": _collect_new_messages(state, bus),
    }


def _next_step_after_ceo_review(state: PipelineState) -> str:
    qa_report = state.get("qa_report", {})
    verdict = str(qa_report.get("verdict", "pass")).lower()

    if verdict == "pass" or state.get("revision_count", 0) >= 3:
        return "ceo_final_summary"

    responsible = str(qa_report.get("agent_responsible", "")).lower()
    if responsible == "engineer":
        return "engineer_node"
    if responsible == "marketing":
        return "marketing_node"

    return "ceo_final_summary"


def build_graph() -> tuple:
    """Create and compile the LangGraph workflow. Returns (compiled_graph, bus)."""
    bus = MessageBus()
    workflow = StateGraph(PipelineState)

    workflow.add_node("ceo_decompose", lambda state: ceo_decompose_node(state, bus))
    workflow.add_node("product_node", lambda state: product_node(state, bus))
    workflow.add_node("engineer_node", lambda state: engineer_node(state, bus))
    workflow.add_node("marketing_node", lambda state: marketing_node(state, bus))
    workflow.add_node("qa_node", lambda state: qa_node(state, bus))
    workflow.add_node("ceo_review_node", lambda state: ceo_review_node(state, bus))
    workflow.add_node("ceo_final_summary", lambda state: ceo_final_summary_node(state, bus))

    workflow.add_edge(START, "ceo_decompose")
    workflow.add_edge("ceo_decompose", "product_node")

    workflow.add_edge("product_node", "engineer_node")

    workflow.add_edge("engineer_node", "marketing_node")
    workflow.add_edge("marketing_node", "qa_node")
    workflow.add_edge("qa_node", "ceo_review_node")

    workflow.add_conditional_edges(
        "ceo_review_node",
        _next_step_after_ceo_review,
        {
            "ceo_final_summary": "ceo_final_summary",
            "engineer_node": "engineer_node",
            "marketing_node": "marketing_node",
        },
    )
    workflow.add_edge("ceo_final_summary", END)

    return workflow.compile(), bus
