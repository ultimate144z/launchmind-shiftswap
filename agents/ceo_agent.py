"""CEO agent orchestration logic for task decomposition and quality review."""

import json
import os
from typing import Any, Dict

import requests

from utils.llm import call_llm


AGENT_NAME = "ceo"


def _find_slack_channel_id(slack_token: str, channel_name: str) -> str:
    """Look up the Slack channel ID by name."""
    clean_name = channel_name.lstrip("#")
    response = requests.get(
        "https://slack.com/api/conversations.list",
        headers={"Authorization": f"Bearer {slack_token}"},
        params={"types": "public_channel", "limit": 200},
        timeout=30,
    )
    data = response.json()
    if data.get("ok"):
        for ch in data.get("channels", []):
            if ch.get("name") == clean_name:
                return ch["id"]
    return clean_name


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


def post_final_summary(state: Dict[str, Any], bus: Any) -> Dict[str, Any]:
    """Compile a final summary from all agent outputs and post it to Slack."""
    product_spec = state.get("product_spec", {})
    engineer_artifacts = state.get("engineer_artifacts", {})
    marketing_artifacts = state.get("marketing_artifacts", {})
    qa_report = state.get("qa_report", {})
    startup_idea = state.get("startup_idea", "")

    # Use LLM to generate the final summary
    system_prompt = (
        "You are the CEO writing a final launch summary for your team's Slack channel. "
        "Summarize what was accomplished. Keep it concise but informative (3-5 bullet points). "
        "Do not use emoji or special Unicode characters. Use plain ASCII text only. "
        "Return strict JSON with keys: summary_title (short, under 80 chars), summary_body (plain text)."
    )
    user_prompt = (
        f"Startup idea: {startup_idea}\n"
        f"Product spec value proposition: {product_spec.get('value_proposition', 'N/A')}\n"
        f"PR URL: {engineer_artifacts.get('pr_url', 'N/A')}\n"
        f"Issue URL: {engineer_artifacts.get('issue_url', 'N/A')}\n"
        f"Marketing tagline: {marketing_artifacts.get('tagline', 'N/A')}\n"
        f"Email sent: {marketing_artifacts.get('email_sent', False)}\n"
        f"Slack posted: {marketing_artifacts.get('slack_posted', False)}\n"
        f"QA verdict: {qa_report.get('verdict', 'N/A')}\n"
    )

    try:
        raw = call_llm(system_prompt, user_prompt, response_format="json")
        summary = json.loads(raw)
    except Exception:
        summary = {
            "summary_title": "ShiftSwap Launch Complete",
            "summary_body": f"All agents have finished. PR: {engineer_artifacts.get('pr_url', 'N/A')}",
        }

    title = summary.get("summary_title", "Launch Summary")[:100]
    body = summary.get("summary_body", "Pipeline complete.")
    # Ensure body isn't too long for Slack (max 3000 chars per section)
    if len(body) > 2900:
        body = body[:2900] + "..."

    pr_url = engineer_artifacts.get("pr_url", "")
    pr_field = f"<{pr_url}|View PR>" if pr_url else "N/A"

    header_text = f"CEO Summary: {title}"[:150]

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header_text, "emoji": True},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": body},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*GitHub PR:* {pr_field}"},
                {"type": "mrkdwn", "text": f"*QA Verdict:* {qa_report.get('verdict', 'N/A').upper()}"},
                {"type": "mrkdwn", "text": f"*Email Sent:* {'Yes' if marketing_artifacts.get('email_sent') else 'No'}"},
                {"type": "mrkdwn", "text": f"*Slack Posted:* {'Yes' if marketing_artifacts.get('slack_posted') else 'No'}"},
            ],
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "Posted by LaunchMind CEO Agent - Final Summary"},
            ],
        },
    ]

    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    channel_name = os.environ.get("SLACK_CHANNEL", "launches")
    channel_id = _find_slack_channel_id(slack_token, channel_name)

    # Auto-join the channel if the bot isn't already a member
    requests.post(
        "https://slack.com/api/conversations.join",
        headers={"Authorization": f"Bearer {slack_token}", "Content-Type": "application/json"},
        json={"channel": channel_id},
        timeout=30,
    )

    try:
        response = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={
                "Authorization": f"Bearer {slack_token}",
                "Content-Type": "application/json",
            },
            json={"channel": channel_id, "blocks": blocks, "text": f"CEO Summary: {title}"},
            timeout=30,
        )
        result = response.json()
        if result.get("ok"):
            print(f"[CEO] Final summary posted to #{channel_name}")
        else:
            print(f"[CEO] Slack post failed: {result.get('error', 'unknown')}")
    except Exception as exc:
        print(f"[CEO] Failed to post final summary to Slack: {exc}")

    bus.send_message(
        to_agent="ceo",
        from_agent=AGENT_NAME,
        message_type="confirmation",
        payload={"status": "pipeline_complete", "summary": summary},
    )

    return {"summary": summary}


def run(message_bus: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    """Backward compatible CEO run wrapper for older orchestration paths."""
    return decompose({"startup_idea": context.get("idea", "")}, message_bus)
