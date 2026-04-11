"""Marketing agent: generates marketing copy, sends email via Brevo, posts to Slack."""

import json
import os
from typing import Any, Dict, List

import requests

from utils.llm import call_llm


AGENT_NAME = "marketing"


def _extract_marketing_inputs(bus: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    """Merge product spec context with queued messages for the marketing agent."""
    incoming: List[Any] = bus.receive_messages("marketing")
    merged: Dict[str, Any] = {
        "startup_idea": context.get("startup_idea", ""),
        "product_spec": context if "value_proposition" in context else context.get("product_spec", {}),
        "pr_url": context.get("pr_url", ""),
        "marketing_task": "Generate marketing materials and launch the product.",
    }

    for msg in incoming:
        payload = getattr(msg, "payload", {})
        if msg.message_type == "task" and payload.get("task"):
            merged["marketing_task"] = str(payload["task"])
            merged["startup_idea"] = str(payload.get("startup_idea", merged["startup_idea"]))
        if msg.message_type == "result" and payload.get("product_spec"):
            merged["product_spec"] = payload["product_spec"]
        if msg.message_type == "revision_request":
            merged["revision_instruction"] = str(payload.get("instruction", ""))
    return merged


def _generate_marketing_copy(product_spec: Dict[str, Any], startup_idea: str, task: str) -> Dict[str, Any]:
    """Use LLM to generate all marketing materials."""
    value_proposition = product_spec.get("value_proposition", startup_idea)
    features = product_spec.get("features", [])
    personas = product_spec.get("personas", [])

    system_prompt = (
        "You are a senior growth marketer. Generate compelling marketing materials for a startup launch. "
        "Return strict JSON only."
    )
    user_prompt = (
        f"Startup idea: {startup_idea}\n"
        f"Marketing task: {task}\n"
        f"Value proposition: {value_proposition}\n"
        f"Features: {json.dumps(features, ensure_ascii=True)}\n"
        f"Target personas: {json.dumps(personas, ensure_ascii=True)}\n\n"
        "Generate the following and return as strict JSON with these exact keys:\n"
        "- tagline: a product tagline (under 10 words)\n"
        "- product_description: short product description for a landing page (2-3 sentences)\n"
        "- email_subject: compelling email subject line for cold outreach\n"
        "- email_body: cold outreach email body addressed to a potential early user or investor "
        "(professional tone, include a clear call to action, 3-4 paragraphs)\n"
        "- social_posts: an object with keys twitter, linkedin, instagram each containing a post draft\n"
    )
    raw = call_llm(system_prompt, user_prompt, response_format="json")
    parsed = json.loads(raw)

    required = ["tagline", "product_description", "email_subject", "email_body", "social_posts"]
    missing = [k for k in required if k not in parsed]
    if missing:
        raise ValueError(f"Marketing LLM output missing keys: {', '.join(missing)}")

    return parsed


def _send_email_brevo(subject: str, html_body: str, to_email: str, from_email: str) -> Dict[str, Any]:
    """Send a transactional email using the Brevo (formerly Sendinblue) HTTP API."""
    api_key = os.environ["BREVO_API_KEY"]

    payload = {
        "sender": {"email": from_email, "name": "ShiftSwap by LaunchMind"},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #2563eb;">{subject}</h2>
                {html_body}
                <hr style="margin-top: 30px; border: none; border-top: 1px solid #eee;">
                <p style="font-size: 12px; color: #999;">
                    Sent by ShiftSwap LaunchMind AI Agent System
                </p>
            </div>
        </body>
        </html>
        """,
    }

    response = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={
            "api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json=payload,
        timeout=30,
    )

    if response.status_code >= 400:
        error_detail = response.text
        raise RuntimeError(f"Brevo email failed (HTTP {response.status_code}): {error_detail}")

    result = response.json() if response.text.strip() else {}
    print(f"[Marketing] Email sent successfully to {to_email} (messageId: {result.get('messageId', 'N/A')})")
    return result


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
    # If not found, try joining by name (the bot may not be in the channel yet)
    join_resp = requests.post(
        "https://slack.com/api/conversations.join",
        headers={
            "Authorization": f"Bearer {slack_token}",
            "Content-Type": "application/json",
        },
        json={"channel": clean_name},
        timeout=30,
    )
    join_data = join_resp.json()
    if join_data.get("ok"):
        return join_data["channel"]["id"]
    return clean_name  # Fallback: return the name as-is


def _post_to_slack(tagline: str, description: str, pr_url: str) -> Dict[str, Any]:
    """Post a Block Kit formatted message to the Slack #launches channel."""
    slack_token = os.environ["SLACK_BOT_TOKEN"]
    channel_name = os.environ.get("SLACK_CHANNEL", "launches")
    channel_id = _find_slack_channel_id(slack_token, channel_name)

    # Auto-join the channel if the bot isn't already a member
    requests.post(
        "https://slack.com/api/conversations.join",
        headers={"Authorization": f"Bearer {slack_token}", "Content-Type": "application/json"},
        json={"channel": channel_id},
        timeout=30,
    )

    pr_field = f"<{pr_url}|View PR>" if pr_url else "PR pending"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"New Launch: {tagline}", "emoji": True},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": description},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*GitHub PR:* {pr_field}"},
                {"type": "mrkdwn", "text": "*Status:* Ready for review"},
            ],
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "Posted by LaunchMind Marketing Agent"},
            ],
        },
    ]

    response = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={
            "Authorization": f"Bearer {slack_token}",
            "Content-Type": "application/json",
        },
        json={"channel": channel_id, "blocks": blocks, "text": f"New Launch: {tagline}"},
        timeout=30,
    )

    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Slack post failed: {result.get('error', 'unknown error')}")

    print(f"[Marketing] Slack message posted to #{channel_name}")
    return result


def run(message_bus: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    """Generate marketing copy, send email via Brevo, post to Slack, report to CEO."""
    merged = _extract_marketing_inputs(message_bus, context)
    startup_idea = merged["startup_idea"]
    product_spec = merged["product_spec"]
    marketing_task = merged["marketing_task"]
    pr_url = merged.get("pr_url", "")

    try:
        # Step 1: Generate all marketing copy via LLM
        copy = _generate_marketing_copy(product_spec, startup_idea, marketing_task)
        print(f"[Marketing] Generated tagline: {copy['tagline']}")

        # Step 2: Send cold outreach email via Brevo
        test_email = os.environ.get("TEST_EMAIL", "")
        from_email = os.environ.get("VERIFIED_SENDER_EMAIL", "")
        email_html = copy["email_body"].replace("\n", "<br>")
        email_result = _send_email_brevo(
            subject=copy["email_subject"],
            html_body=f"<p>{email_html}</p>",
            to_email=test_email,
            from_email=from_email,
        )

        # Step 3: Post to Slack
        slack_result = _post_to_slack(
            tagline=copy["tagline"],
            description=copy["product_description"],
            pr_url=pr_url,
        )

        # Step 4: Send results back to CEO via message bus
        payload = {
            "tagline": copy["tagline"],
            "product_description": copy["product_description"],
            "email_subject": copy["email_subject"],
            "email_body": copy["email_body"],
            "social_posts": copy["social_posts"],
            "email_sent": True,
            "email_recipient": test_email,
            "slack_posted": True,
        }

        message_bus.send_message(
            to_agent="ceo",
            from_agent=AGENT_NAME,
            message_type="result",
            payload=payload,
        )

        return payload

    except Exception as exc:
        failure_payload = {
            "tagline": "",
            "product_description": "",
            "email_sent": False,
            "slack_posted": False,
            "error": str(exc),
        }
        message_bus.send_message(
            to_agent="ceo",
            from_agent=AGENT_NAME,
            message_type="result",
            payload=failure_payload,
        )
        print(f"[Marketing] ERROR: {exc}")
        return failure_payload
