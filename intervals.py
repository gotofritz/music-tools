#!/usr/bin/env python3
"""
Jazz Practice Generator
Cycles through notes, scales, and fingerings for practice sessions.

Usage: uv run generate_exercise.py
"""

import json
import random
from pathlib import Path

# intervals
INTERVALS = [
    "2-",
    "2",
    "3-",
    "3",
    "4",
    "4+",
    "5",
    "6-",
    "6",
    "7-",
    "7",
    "8",
    "9-",
    "9",
    "10-",
    "10",
]

STATE_FILE = Path(__file__).parent / ".intervals_state.json"


def load_state():
    """Load the cycle state from file."""
    if STATE_FILE.exists():
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {
        "intervals": INTERVALS.copy(),
    }


def save_state(state):
    """Save the cycle state to file."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def get_random_item(items):
    """Get a random item from a list and remove it. Reset if empty."""
    if not items:
        return None

    item = random.choice(items)
    items.remove(item)
    return item


def main():
    state = load_state()

    # Get random items from each cycle
    interval = get_random_item(state["intervals"])
    if interval is None:
        state["intervals"] = INTERVALS.copy()
        interval = get_random_item(state["intervals"])

    # Save updated state
    save_state(state)

    # Print the result
    print(f"{interval}")


if __name__ == "__main__":
    main()
