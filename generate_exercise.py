#!/usr/bin/env python3
"""
Jazz Practice Generator
Cycles through notes, scales, and fingerings for practice sessions.

Usage: uv run generate_exercise.py
"""

import json
import random
from pathlib import Path

# Define the musical elements
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Enharmonic equivalents for proper scale spelling
ENHARMONIC = {"C#": "Db", "D#": "Eb", "F#": "Gb", "G#": "Ab", "A#": "Bb"}

# Note circle for determining scale spelling
NOTE_CIRCLE = ["C", "D", "E", "F", "G", "A", "B"]

# Chromatic notes with both spellings
CHROMATIC = {
    0: ["C", "B#"],
    1: ["C#", "Db"],
    2: ["D"],
    3: ["D#", "Eb"],
    4: ["E", "Fb"],
    5: ["F", "E#"],
    6: ["F#", "Gb"],
    7: ["G"],
    8: ["G#", "Ab"],
    9: ["A"],
    10: ["A#", "Bb"],
    11: ["B", "Cb"],
}

SCALES = [
    "major",
    "minor",
    "dorian",
    "phrygian",
    "lydian",
    "mixolydian",
    "aeolian",
    "locrian",
    "major pentatonic",
    "minor pentatonic",
    "blues",
    "harmonic minor",
    "melodic minor",
    "altered",
    "diminished",
    "whole tone",
    "lydian dominant",
    "half-diminished",
    "phrygian dominant",
    "bebop major",
    "bebop dominant",
    "whole-half diminished",
]

FINGERINGS = [
    (1, 1),
    (1, 2),
    (1, 3),
    (1, 4),
    (2, 2),
    (2, 3),
    (2, 4),
    (3, 3),
    (3, 4),
    (4, 4),
]

# Scale intervals (in semitones from root)
SCALE_INTERVALS = {
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "phrygian": [0, 1, 3, 5, 7, 8, 10],
    "lydian": [0, 2, 4, 6, 7, 9, 11],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "aeolian": [0, 2, 3, 5, 7, 8, 10],
    "locrian": [0, 1, 3, 5, 6, 8, 10],
    "major pentatonic": [0, 2, 4, 7, 9],
    "minor pentatonic": [0, 3, 5, 7, 10],
    "blues": [0, 3, 5, 6, 7, 10],
    "harmonic minor": [0, 2, 3, 5, 7, 8, 11],
    "melodic minor": [0, 2, 3, 5, 7, 9, 11],
    "altered": [0, 1, 3, 4, 6, 8, 10],
    "diminished": [0, 2, 3, 5, 6, 8, 9, 11],  # half-whole
    "whole tone": [0, 2, 4, 6, 8, 10],
    "lydian dominant": [0, 2, 4, 6, 7, 9, 10],
    "half-diminished": [0, 2, 3, 5, 6, 9, 10],  # locrian #2
    "phrygian dominant": [0, 1, 4, 5, 7, 8, 10],
    "bebop major": [0, 2, 4, 5, 7, 8, 9, 11],
    "bebop dominant": [0, 2, 4, 5, 7, 9, 10, 11],
    "whole-half diminished": [0, 2, 3, 5, 6, 8, 9, 11],
}

STATE_FILE = Path(__file__).parent / ".generate_exercise_state.json"


def load_state():
    """Load the cycle state from file."""
    if STATE_FILE.exists():
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {
        "notes": NOTES.copy(),
        "scales": SCALES.copy(),
        "fingerings": [list(f) for f in FINGERINGS],
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


def get_scale_notes(root, scale):
    """Generate the notes of a scale given the root note and scale type."""
    # Convert root to sharp spelling for indexing
    root_sharp = root
    if root in ENHARMONIC.values():
        # Convert flat to sharp for indexing
        for sharp, flat in ENHARMONIC.items():
            if flat == root:
                root_sharp = sharp
                break

    root_index = NOTES.index(root_sharp)
    intervals = SCALE_INTERVALS[scale]

    # Determine the base note letter (C, D, E, F, G, A, or B)
    root_letter = root[0]
    root_letter_index = NOTE_CIRCLE.index(root_letter)

    scale_notes = []
    used_letters = set()

    for i, interval in enumerate(intervals):
        note_index = (root_index + interval) % 12

        # Determine expected letter for this scale degree
        expected_letter_index = (root_letter_index + i) % 7
        expected_letter = NOTE_CIRCLE[expected_letter_index]

        # Get possible note names for this chromatic pitch
        possible_notes = CHROMATIC[note_index]

        # Choose the note that matches the expected letter
        chosen_note = None
        for note in possible_notes:
            if note[0] == expected_letter:
                chosen_note = note
                break

        # Fallback to first option if no match (shouldn't happen in well-formed scales)
        if chosen_note is None:
            chosen_note = possible_notes[0]

        scale_notes.append(chosen_note)
        used_letters.add(chosen_note[0])

    return scale_notes


def main():
    state = load_state()

    # Get random items from each cycle
    note = get_random_item(state["notes"])
    if note is None:
        state["notes"] = NOTES.copy()
        note = get_random_item(state["notes"])

    scale = get_random_item(state["scales"])
    if scale is None:
        state["scales"] = SCALES.copy()
        scale = get_random_item(state["scales"])

    fingering = get_random_item(state["fingerings"])
    if fingering is None:
        state["fingerings"] = [list(f) for f in FINGERINGS]
        fingering = get_random_item(state["fingerings"])

    # Save updated state
    save_state(state)

    # Print the result
    fingering_str = f"{fingering[0]}-{fingering[1]}"
    direction = random.choice(["ascending", "descending"])
    print(f"{note} {scale} {fingering_str} ({direction})")

    # Print the scale notes
    scale_notes = get_scale_notes(note, scale)
    # Add the octave (root note again)
    scale_notes.append(scale_notes[0])
    if direction == "descending":
        scale_notes = scale_notes[::-1]
    print(" ".join(scale_notes))


if __name__ == "__main__":
    main()
