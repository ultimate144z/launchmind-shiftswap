"""Engineer agent: proposes technical implementation details."""

from typing import Any, Dict


AGENT_NAME = "engineer_agent"


def run(message_bus: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    """Produce an engineering plan for the MVP."""
    output = {
        "stack": {
            "backend": "Python",
            "workflow": "LangGraph",
            "llm": "OpenAI GPT",
            "http": "Requests",
        },
        "services": ["auth", "swap-requests", "approval-engine", "notifications"],
        "non_functional": ["idempotent operations", "structured logs", "retry-safe API calls"],
    }
    message_bus.publish("agent_events", {"agent": AGENT_NAME, "input": context, "output": output})
    return output
