"""QA agent: validates readiness and test strategy."""

from typing import Any, Dict


AGENT_NAME = "qa_agent"


def run(message_bus: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    """Return a practical QA checklist for launch readiness."""
    output = {
        "test_plan": [
            "unit tests for swap eligibility rules",
            "integration tests for approval workflow",
            "API failure and retry behavior tests",
            "smoke tests for critical user journeys",
        ],
        "release_gate": "No blocker defects and >= 95% pass rate on critical test suite",
    }
    message_bus.publish("agent_events", {"agent": AGENT_NAME, "input": context, "output": output})
    return output
