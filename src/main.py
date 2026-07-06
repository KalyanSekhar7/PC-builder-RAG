"""CLI entry point for the PC Configuration Agent."""

import json
import sys
from datetime import datetime
from pathlib import Path

import anthropic

from .config import (
    ANTHROPIC_API_KEY, MODEL_NAME, MAX_AGENT_TURNS, MAX_RETRIES,
    DATA_DIR, LOG_LEVEL, LOG_FILE,
)
from .utils.logging_config import setup_logging
from .data.loader import ComponentStore
from .engine.compatibility import CompatibilityChecker
from .engine.optimizer import UseCaseOptimizer
from .engine.validator import RequirementValidator
from .agent.tools import ToolDispatcher
from .agent.loop import AgentLoop


def main():
    """Run the PC Configuration Agent in interactive CLI mode."""
    setup_logging(level=LOG_LEVEL, log_file=LOG_FILE)

    # Check API key
    if not ANTHROPIC_API_KEY:
        print("Error: ANTHROPIC_API_KEY not set.")
        print("Create a .env file with: ANTHROPIC_API_KEY=your-key-here")
        print("Or set the environment variable: export ANTHROPIC_API_KEY=your-key-here")
        sys.exit(1)

    # Initialize components
    print("Loading component database...")
    store = ComponentStore(DATA_DIR)
    stats = store.get_summary_stats()
    print(f"Loaded {stats['total_components']} components across {stats['category_count']} categories.\n")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    checker = CompatibilityChecker(store)
    optimizer = UseCaseOptimizer(store)
    validator = RequirementValidator(client, model=MODEL_NAME)
    dispatcher = ToolDispatcher(store, optimizer, checker)
    agent = AgentLoop(
        client=client,
        dispatcher=dispatcher,
        store_stats=stats,
        validator=validator,
        model=MODEL_NAME,
        max_turns=MAX_AGENT_TURNS,
        max_retries=MAX_RETRIES,
    )

    # Welcome message
    print("=" * 60)
    print("  PC Configuration Agent")
    print("  Powered by Claude")
    print("=" * 60)
    print()
    print("Tell me what kind of PC you need and your budget,")
    print("and I'll configure the perfect build for you.")
    print()
    print("Type 'quit' to exit, 'reset' to start over,")
    print("or 'trace' to see the agent's reasoning trace.")
    print("-" * 60)

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "q"):
            _save_trace(agent)
            print("Goodbye!")
            break

        if user_input.lower() == "reset":
            agent.reset()
            print("Conversation reset. What kind of PC do you need?")
            continue

        if user_input.lower() == "trace":
            trace = agent.get_trace()
            print(f"\n--- Agent Trace ({len(trace)} events) ---")
            for event in trace:
                print(f"  [{event['timestamp'][:19]}] {event['event']}: "
                      f"{json.dumps(event['data'], default=str)[:120]}")
            print("--- End Trace ---")
            continue

        # Get agent response
        response = agent.chat(user_input)
        print(f"\nAssistant: {response}")


def _save_trace(agent: AgentLoop) -> None:
    """Save the agent trace to a JSON file."""
    trace = agent.get_trace()
    if not trace:
        return

    reports_dir = Path(__file__).parent.parent / "evaluation" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    trace_file = reports_dir / f"trace_{timestamp}.json"

    with open(trace_file, "w") as f:
        json.dump(trace, f, indent=2, default=str)
    print(f"\nAgent trace saved to: {trace_file}")


if __name__ == "__main__":
    main()
