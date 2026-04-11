"""QA / Reviewer agent: validates Engineer HTML and Marketing copy using LLM, posts GitHub PR comments."""

import json
import os
import re
from typing import Any, Dict, List

import requests

from utils.llm import call_llm


AGENT_NAME = "qa"


def _review_html(html: str, product_spec: Dict[str, Any]) -> Dict[str, Any]:
    """Use LLM to review the HTML landing page against the product spec."""
    system_prompt = (
        "You are a senior QA engineer reviewing an HTML landing page. "
        "Check whether it matches the product specification. "
        "Return strict JSON only."
    )
    user_prompt = (
        f"Product spec:\n{json.dumps(product_spec, ensure_ascii=True)}\n\n"
        f"HTML landing page:\n{html[:4000]}\n\n"
        "Review the HTML and return JSON with these keys:\n"
        "- headline_matches: boolean, does the headline match the value proposition?\n"
        "- features_present: boolean, are the product features mentioned?\n"
        "- cta_present: boolean, is there a call-to-action button?\n"
        "- issues: array of strings describing specific problems found\n"
        "- suggestions: array of strings with improvement suggestions\n"
        "- html_verdict: 'pass' or 'fail'\n"
    )
    raw = call_llm(system_prompt, user_prompt, response_format="json")
    return json.loads(raw)


def _review_marketing(marketing_artifacts: Dict[str, Any], product_spec: Dict[str, Any]) -> Dict[str, Any]:
    """Use LLM to review the marketing copy against the product spec."""
    system_prompt = (
        "You are a senior marketing reviewer. Check whether the marketing materials "
        "are compelling, consistent with the product, and professional. "
        "Return strict JSON only."
    )
    user_prompt = (
        f"Product spec:\n{json.dumps(product_spec, ensure_ascii=True)}\n\n"
        f"Marketing materials:\n{json.dumps(marketing_artifacts, ensure_ascii=True)}\n\n"
        "Review and return JSON with these keys:\n"
        "- tagline_compelling: boolean, is the tagline compelling and under 10 words?\n"
        "- email_has_cta: boolean, does the cold email have a clear call to action?\n"
        "- tone_appropriate: boolean, is the tone professional and appropriate?\n"
        "- issues: array of strings describing specific problems\n"
        "- suggestions: array of strings with improvements\n"
        "- marketing_verdict: 'pass' or 'fail'\n"
    )
    raw = call_llm(system_prompt, user_prompt, response_format="json")
    return json.loads(raw)


def _post_pr_review_comments(pr_url: str, html: str, issues: List[str]) -> bool:
    """Post review comments on the GitHub pull request."""
    github_token = os.environ.get("GITHUB_TOKEN", "")
    github_repo = os.environ.get("GITHUB_REPO", "")

    if not pr_url or not github_token or not github_repo:
        print("[QA] Skipping PR comments: missing PR URL or GitHub credentials")
        return False

    pr_number_match = re.search(r"/pull/(\d+)", pr_url)
    if not pr_number_match:
        print(f"[QA] Could not extract PR number from URL: {pr_url}")
        return False

    pr_number = pr_number_match.group(1)
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github+json",
    }
    base = f"https://api.github.com/repos/{github_repo}"

    # Post a general review comment with all findings
    review_body = "## QA Agent Review\n\n"
    if issues:
        review_body += "### Issues Found:\n"
        for issue in issues:
            review_body += f"- {issue}\n"
    else:
        review_body += "No critical issues found. Landing page looks good!\n"

    # Get the PR diff to find commit SHA for inline comments
    try:
        pr_data = requests.get(f"{base}/pulls/{pr_number}", headers=headers, timeout=30).json()
        head_sha = pr_data.get("head", {}).get("sha", "")

        # Post a PR review with inline comments on index.html
        comments = []
        if len(issues) >= 1:
            comments.append({
                "path": "index.html",
                "position": 1,
                "body": f"**QA Review:** {issues[0]}",
            })
        if len(issues) >= 2:
            comments.append({
                "path": "index.html",
                "position": 5,
                "body": f"**QA Review:** {issues[1]}",
            })

        review_payload: Dict[str, Any] = {
            "body": review_body,
            "event": "COMMENT",
        }
        if comments:
            review_payload["comments"] = comments
            review_payload["commit_id"] = head_sha

        response = requests.post(
            f"{base}/pulls/{pr_number}/reviews",
            headers=headers,
            json=review_payload,
            timeout=30,
        )

        if response.status_code < 300:
            print(f"[QA] Posted review on PR #{pr_number}")
            return True
        else:
            # Fallback: post as a simple issue comment if review API fails
            print(f"[QA] Review API returned {response.status_code}, falling back to issue comment")
            fallback = requests.post(
                f"{base}/issues/{pr_number}/comments",
                headers=headers,
                json={"body": review_body},
                timeout=30,
            )
            if fallback.status_code < 300:
                print(f"[QA] Posted fallback comment on PR #{pr_number}")
                return True
            print(f"[QA] Fallback comment also failed: {fallback.status_code}")
            return False

    except Exception as exc:
        print(f"[QA] Failed to post PR comments: {exc}")
        return False


def run(message_bus: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    """Review engineer HTML and marketing copy, post PR comments, return verdict."""
    engineer_artifacts = context.get("engineer_artifacts", {})
    marketing_artifacts = context.get("marketing_artifacts", {})
    product_spec = context.get("product_spec", {})

    html = engineer_artifacts.get("html", "")
    pr_url = engineer_artifacts.get("pr_url", "")

    all_issues: List[str] = []
    overall_verdict = "pass"
    agent_responsible = ""

    try:
        # Step 1: Review HTML landing page
        html_review = {}
        if html:
            html_review = _review_html(html, product_spec)
            html_issues = html_review.get("issues", [])
            all_issues.extend(html_issues)
            if html_review.get("html_verdict", "pass").lower() == "fail":
                overall_verdict = "fail"
                agent_responsible = "engineer"
            print(f"[QA] HTML review: {html_review.get('html_verdict', 'pass')} "
                  f"({len(html_issues)} issues)")
        else:
            all_issues.append("No HTML content received from Engineer agent")
            overall_verdict = "fail"
            agent_responsible = "engineer"

        # Step 2: Review marketing copy
        marketing_review = {}
        if marketing_artifacts.get("tagline") or marketing_artifacts.get("email_body"):
            marketing_review = _review_marketing(marketing_artifacts, product_spec)
            mkt_issues = marketing_review.get("issues", [])
            all_issues.extend(mkt_issues)
            if marketing_review.get("marketing_verdict", "pass").lower() == "fail":
                overall_verdict = "fail"
                if not agent_responsible:
                    agent_responsible = "marketing"
            print(f"[QA] Marketing review: {marketing_review.get('marketing_verdict', 'pass')} "
                  f"({len(mkt_issues)} issues)")
        else:
            if marketing_artifacts.get("error"):
                all_issues.append(f"Marketing agent reported error: {marketing_artifacts['error']}")
                overall_verdict = "fail"
                agent_responsible = "marketing"

        # Step 3: Post review comments on the GitHub PR
        pr_commented = _post_pr_review_comments(pr_url, html, all_issues)

        # Step 4: Build and send structured review report to CEO
        report = {
            "verdict": overall_verdict,
            "agent_responsible": agent_responsible,
            "issues": all_issues,
            "html_review": html_review,
            "marketing_review": marketing_review,
            "pr_comments_posted": pr_commented,
        }

        message_bus.send_message(
            to_agent="ceo",
            from_agent=AGENT_NAME,
            message_type="result",
            payload=report,
        )

        print(f"[QA] Overall verdict: {overall_verdict.upper()}")
        return report

    except Exception as exc:
        failure_report = {
            "verdict": "pass",
            "agent_responsible": "",
            "issues": [f"QA agent error: {str(exc)}"],
            "pr_comments_posted": False,
            "error": str(exc),
        }
        message_bus.send_message(
            to_agent="ceo",
            from_agent=AGENT_NAME,
            message_type="result",
            payload=failure_report,
        )
        print(f"[QA] ERROR: {exc}")
        return failure_report
