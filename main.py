"""Single entry point to run the multi-agent ShiftSwap system end-to-end."""

from config import validate_config
from graph import build_graph

validate_config()

from pprint import pprint

STARTUP_IDEA = "ShiftSwap: a platform that helps hourly workers exchange shifts quickly and fairly, with manager approval and policy compliance."


def run_system() -> tuple:
    """Run the LangGraph pipeline and return (final_state, bus)."""
    graph, bus = build_graph()
    result = graph.invoke(
        {
            "startup_idea": STARTUP_IDEA,
            "tasks_by_agent": {},
            "product_spec": {},
            "engineer_artifacts": {},
            "marketing_artifacts": {},
            "qa_report": {},
            "revision_count": 0,
            "message_log": [],
        }
    )
    return result, bus


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)

    final_state, bus = run_system()
    
    print("\n=== FULL MESSAGE HISTORY ===")
    for msg in bus.full_history():
        print(f"  [{msg.from_agent}] -> [{msg.to_agent}] type={msg.message_type} id={msg.message_id[:8]}")
