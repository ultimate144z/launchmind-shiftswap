"""Product agent implementation for generating structured product specs."""

import json
from typing import Any, Dict, List

from utils.llm import call_llm


AGENT_NAME = "product"


def _parse_json_or_raise(content: str) -> Dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Product agent received non-JSON LLM output: {content}") from exc


def _validate_product_spec(spec: Dict[str, Any]) -> None:
    required_fields = ["value_proposition", "personas", "features", "user_stories"]
    missing_fields = [field for field in required_fields if field not in spec]
    if missing_fields:
        raise ValueError(f"Product spec missing required fields: {', '.join(missing_fields)}")

    if not isinstance(spec["personas"], list) or not spec["personas"]:
        raise ValueError("Product spec field 'personas' must be a non-empty list")
    if not isinstance(spec["features"], list) or not spec["features"]:
        raise ValueError("Product spec field 'features' must be a non-empty list")
    if not isinstance(spec["user_stories"], list) or not spec["user_stories"]:
        raise ValueError("Product spec field 'user_stories' must be a non-empty list")

    for idx, persona in enumerate(spec["personas"]):
        if not all(key in persona for key in ["name", "role", "pain_point"]):
            raise ValueError(f"Persona at index {idx} is missing name/role/pain_point")

    for idx, feature in enumerate(spec["features"]):
        if not all(key in feature for key in ["name", "description", "priority"]):
            raise ValueError(f"Feature at index {idx} is missing name/description/priority")

    for idx, story in enumerate(spec["user_stories"]):
        if not all(key in story for key in ["as_a", "i_want", "so_that"]):
            raise ValueError(f"User story at index {idx} is missing as_a/i_want/so_that")


def _find_product_task(messages: List[Any], fallback_task: str) -> str:
    for message in reversed(messages):
        payload = getattr(message, "payload", {})
        if message.message_type == "task" and payload.get("task"):
            return str(payload["task"])
    return fallback_task


def run(state: Dict[str, Any], bus: Any) -> Dict[str, Any]:
    """Generate a structured product specification from CEO instructions."""
    incoming = bus.receive_messages("product")
    startup_idea = state.get("startup_idea", "")

    fallback = state.get("tasks_by_agent", {}).get("product_task", "Define core product specification.")
    product_task = _find_product_task(incoming, fallback)

    system_prompt = "You are a product manager. Generate a detailed product specification."
    user_prompt = (
        f"Startup idea: {startup_idea}\n"
        f"CEO task: {product_task}\n"
        "Return strict JSON with exactly these fields: "
        "value_proposition (string), personas (array of {name, role, pain_point}), "
        "features (array of {name, description, priority}), user_stories "
        "(array of {as_a, i_want, so_that})."
    )

    raw = call_llm(system_prompt, user_prompt, response_format="json")
    product_spec = _parse_json_or_raise(raw)
    _validate_product_spec(product_spec)

    bus.send_message(
        to_agent="engineer",
        from_agent=AGENT_NAME,
        message_type="result",
        payload={"product_spec": product_spec},
    )
    bus.send_message(
        to_agent="marketing",
        from_agent=AGENT_NAME,
        message_type="result",
        payload={"product_spec": product_spec},
    )
    bus.send_message(
        to_agent="ceo",
        from_agent=AGENT_NAME,
        message_type="confirmation",
        payload={"status": "spec_ready"},
    )

    print(f"[Product] Spec generated: {product_spec.get('value_proposition', '')}")
    return {"product_spec": product_spec}
