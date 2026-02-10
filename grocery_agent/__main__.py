"""Entry point for running the grocery agent: python -m grocery_agent"""

import asyncio
import logging
import os
import signal
import sys

from grocery_agent.agent import GroceryAgent


def _detect_headless() -> bool:
    """Return True if we should run the browser in headless mode."""
    if "--headed" in sys.argv:
        return False
    if "--headless" in sys.argv:
        return True
    # Auto-detect: headless when no DISPLAY is available
    return not bool(os.environ.get("DISPLAY"))


def main() -> None:
    """Launch the interactive grocery shopping agent."""
    # Set up logging
    log_level = logging.DEBUG if "--debug" in sys.argv else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    headless = _detect_headless()

    # Schedule a forced exit to avoid playwright subprocess hangs
    def _force_exit(*_args: object) -> None:
        os._exit(0)

    signal.signal(signal.SIGALRM, _force_exit)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    agent = GroceryAgent(headless=headless)

    try:
        loop.run_until_complete(agent.run_interactive())
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        # Give shutdown 3 seconds before force exit
        signal.alarm(3)
        try:
            loop.run_until_complete(agent.shutdown())
        except Exception:
            pass
        os._exit(0)


if __name__ == "__main__":
    main()
