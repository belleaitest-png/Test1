"""Entry point for running the grocery agent: python -m grocery_agent"""

import asyncio
import logging
import sys

from grocery_agent.agent import GroceryAgent


def main() -> None:
    """Launch the interactive grocery shopping agent."""
    # Set up logging
    log_level = logging.DEBUG if "--debug" in sys.argv else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    agent = GroceryAgent()

    try:
        asyncio.run(agent.run_interactive())
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        asyncio.run(agent.shutdown())


if __name__ == "__main__":
    main()
