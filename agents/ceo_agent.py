"""CEO agent orchestration logic for task decomposition and quality review."""

import json
from typing import Any, Dict

from utils.llm import call_llm


AGENT_NAME = "ceo"


def _parse_json_or_raise(content: str) -> Dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"CEO received non-JSON LLM output: {content}") from exc


def decompose(state: Dict[str, Any], bus: Any) -> Dict[str, Any]:
    """Use the LLM to decompose startup idea into tasks for product, engineer, marketing."""
    startup_idea = state.get("startup_idea", "")
    system_prompt = (
        "You are the CEO of a startup. Decompose the given startup idea into specific tasks "
        "for three agents: product manager, engineer, and marketing. "
        "Return strict JSON with keys: product_task, engineer_task, marketing_task."
    )
    user_prompt = f"Startup idea: {startup_idea}"

    raw = call_llm(system_prompt, user_prompt, response_format="json")
    tasks = _parse_json_or_raise(raw)

    required = ["product_task", "engineer_task", "marketing_task"]
    missing = [key for key in required if not tasks.get(key)]
    if missing:
        raise ValueError(f"CEO task decomposition missing keys: {', '.join(missing)}")

    bus.send_message(
        to_agent="product",
        from_agent=AGENT_NAME,
        message_type="task",
        payload={"startup_idea": startup_idea, "task": tasks["product_task"]},
    )
    bus.send_message(
        to_agent="engineer",
        from_agent=AGENT_NAME,
        message_type="task",
        payload={"startup_idea": startup_idea, "task": tasks["engineer_task"]},
    )
    bus.send_message(
        to_agent="marketing",
        from_agent=AGENT_NAME,
        message_type="task",
        payload={"startup_idea": startup_idea, "task": tasks["marketing_task"]},
    )

    return {"tasks_by_agent": tasks}


def review(state: Dict[str, Any], bus: Any) -> Dict[str, Any]:
    """Review QA findings and decide pass/fail with revision instruction when needed."""
    qa_report = state.get("qa_report", {})
    system_prompt = (
        "You are the CEO reviewing work quality. Given a QA report, decide whether the output "
        "is acceptable or needs revision. Return strict JSON with keys: verdict, reasoning, "
        "revision_instruction (empty string allowed when verdict is pass)."
    )
    user_prompt = (
        "QA report:\n"
        f"{json.dumps(qa_report, ensure_ascii=True)}\n\n"
        "Full pipeline state:\n"
        f"{json.dumps(state, ensure_ascii=True)}"
    )

    raw = call_llm(system_prompt, user_prompt, response_format="json")
    decision = _parse_json_or_raise(raw)

    verdict = str(decision.get("verdict", "fail")).lower().strip()
    reasoning = str(decision.get("reasoning", "No reasoning provided")).strip()
    revision_instruction = str(decision.get("revision_instruction", "")).strip()

    if verdict not in {"pass", "fail"}:
        raise ValueError(f"CEO review returned invalid verdict: {verdict}")

    if verdict == "fail":
        target_agent = str(qa_report.get("agent_responsible", "")).strip() or "engineer"
        bus.send_message(
            to_agent=target_agent,
            from_agent=AGENT_NAME,
            message_type="revision_request",
            payload={"instruction": revision_instruction, "qa_report": qa_report},
        )

    print(f"[CEO] Decision: {verdict.upper()} - {reasoning}")

    updated_report = dict(qa_report)
    updated_report.update(
        {
            "verdict": verdict,
            "reasoning": reasoning,
            "revision_instruction": revision_instruction,
        }
    )
    return updated_report


def run(message_bus: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    """Backward compatible CEO run wrapper for older orchestration paths."""
    return decompose({"startup_idea": context.get("idea", "")}, message_bus)
