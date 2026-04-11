"""Engineer agent implementation for HTML generation and GitHub automation."""

import base64
import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from utils.llm import call_llm


AGENT_NAME = "engineer"


def _retry_request(method: str, url: str, headers: Dict[str, str], json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Send HTTP request with retries for transient failures only."""
    backoffs = [1, 2, 4]

    last_error: Optional[Exception] = None
    for idx, delay in enumerate(backoffs, start=1):
        try:
            response = requests.request(method=method, url=url, headers=headers, json=json_body, timeout=30)
            if 400 <= response.status_code < 500:
                response.raise_for_status()
            if response.status_code >= 500:
                raise requests.HTTPError(f"Server error {response.status_code}: {response.text}")

            if not response.text.strip():
                return {}
            return response.json()
        except requests.HTTPError as exc:
            last_error = exc
            if "Server error" not in str(exc):
                raise
            if idx == len(backoffs):
                raise
            time.sleep(delay)
        except requests.RequestException as exc:
            last_error = exc
            if idx == len(backoffs):
                break
            time.sleep(delay)

    raise RuntimeError(f"GitHub request failed after retries: {last_error}")


def _extract_engineer_inputs(bus: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    """Merge startup context with queued messages for the engineer."""
    incoming: List[Any] = bus.receive_messages("engineer")
    merged: Dict[str, Any] = {
        "startup_idea": context.get("startup_idea", ""),
        "product_spec": context if "value_proposition" in context else context.get("product_spec", {}),
        "engineer_task": "Build the initial landing page and open a PR.",
    }

    for msg in incoming:
        payload = getattr(msg, "payload", {})
        if msg.message_type == "task" and payload.get("task"):
            merged["engineer_task"] = str(payload["task"])
            merged["startup_idea"] = str(payload.get("startup_idea", merged["startup_idea"]))
        if msg.message_type == "result" and payload.get("product_spec"):
            merged["product_spec"] = payload["product_spec"]
    return merged


def _generate_html(product_spec: Dict[str, Any], startup_idea: str, engineer_task: str) -> str:
    """Generate semantic HTML landing page with inline styling."""
    value_proposition = product_spec.get("value_proposition", startup_idea)
    features = product_spec.get("features", [])
    tagline = product_spec.get("tagline", "Shift swaps done fairly.")

    system_prompt = "You are a senior frontend engineer. Return only runnable HTML." 
    user_prompt = (
        "Create a complete HTML5 landing page with inline CSS only.\n"
        f"Startup idea: {startup_idea}\n"
        f"Engineer task: {engineer_task}\n"
        f"Value proposition: {value_proposition}\n"
        f"Tagline: {tagline}\n"
        f"Features JSON: {json.dumps(features, ensure_ascii=True)}\n"
        "Requirements: semantic HTML5, headline must match value proposition, include all features, "
        "include a CTA button with exact text 'Get Early Access', and no external assets."
    )
    return call_llm(system_prompt, user_prompt, response_format="text").strip()


def _generate_github_copy(startup_idea: str, product_spec: Dict[str, Any]) -> Dict[str, str]:
    """Generate issue/PR body text for GitHub artifacts."""
    system_prompt = "You write concise GitHub issue and pull request copy. Return strict JSON only."
    user_prompt = (
        f"Startup idea: {startup_idea}\n"
        f"Product spec: {json.dumps(product_spec, ensure_ascii=True)}\n"
        "Return JSON with keys: issue_body, pr_title, pr_body. "
        "issue_body must be 2-3 sentences and describe what was built."
    )
    raw = call_llm(system_prompt, user_prompt, response_format="json")
    parsed = json.loads(raw)
    return {
        "issue_body": str(parsed.get("issue_body", "Initial landing page scaffolding.")),
        "pr_title": str(parsed.get("pr_title", "Initial landing page")),
        "pr_body": str(parsed.get("pr_body", "Adds AI-generated landing page and basic styling.")),
    }


def run(message_bus: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    """Generate landing page, push to GitHub, open issue/PR, and report to CEO."""
    merged = _extract_engineer_inputs(message_bus, context)
    startup_idea = merged["startup_idea"]
    product_spec = merged["product_spec"]
    engineer_task = merged["engineer_task"]

    try:
        html_str = _generate_html(product_spec, startup_idea, engineer_task)
        copy = _generate_github_copy(startup_idea, product_spec)

        github_token = os.environ["GITHUB_TOKEN"]
        github_repo = os.environ["GITHUB_REPO"]

        headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github+json",
        }
        base = f"https://api.github.com/repos/{github_repo}"

        ref_data = _retry_request("GET", f"{base}/git/ref/heads/main", headers)
        base_sha = ref_data["object"]["sha"]

        branch_name = f"agent-landing-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
        print(f"[Engineer] Creating branch: {branch_name}")
        _retry_request(
            "POST",
            f"{base}/git/refs",
            headers,
            json_body={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
        )

        encoded_html = base64.b64encode(html_str.encode("utf-8")).decode("utf-8")
        _retry_request(
            "PUT",
            f"{base}/contents/index.html",
            headers,
            json_body={
                "message": "feat: add AI-generated landing page",
                "content": encoded_html,
                "branch": branch_name,
                "author": {"name": "EngineerAgent", "email": "agent@launchmind.ai"},
                "committer": {"name": "EngineerAgent", "email": "agent@launchmind.ai"},
            },
        )

        issue_data = _retry_request(
            "POST",
            f"{base}/issues",
            headers,
            json_body={"title": "Initial landing page", "body": copy["issue_body"]},
        )
        issue_url = issue_data.get("html_url", "")

        pr_data = _retry_request(
            "POST",
            f"{base}/pulls",
            headers,
            json_body={
                "title": copy["pr_title"],
                "body": copy["pr_body"],
                "head": branch_name,
                "base": "main",
            },
        )
        pr_url = pr_data.get("html_url", "")

        payload = {"pr_url": pr_url, "issue_url": issue_url, "html": html_str}
        message_bus.send_message(
            to_agent="ceo",
            from_agent=AGENT_NAME,
            message_type="result",
            payload=payload,
        )

        print(f"[Engineer] PR opened: {pr_url}")
        return {"engineer_artifacts": payload}
    except Exception as exc:
        failure_payload = {
            "pr_url": "",
            "issue_url": "",
            "html": "",
            "error": str(exc),
        }
        message_bus.send_message(
            to_agent="ceo",
            from_agent=AGENT_NAME,
            message_type="result",
            payload=failure_payload,
        )
        print(f"[Engineer] ERROR: {exc}")
        return {"engineer_artifacts": failure_payload}
