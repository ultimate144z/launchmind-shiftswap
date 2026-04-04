"""Marketing agent: frames positioning and launch messaging."""

from typing import Any, Dict


AGENT_NAME = "marketing_agent"


def run(message_bus: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    """Create concise go-to-market messaging."""
    output = {
        "positioning": "The fastest way to swap shifts without policy headaches.",
        "channels": ["email campaign", "manager onboarding", "internal chat announcements"],
        "launch_message": "ShiftSwap helps teams fill shifts faster with transparent approvals.",
    }
    message_bus.publish("agent_events", {"agent": AGENT_NAME, "input": context, "output": output})
    return output
