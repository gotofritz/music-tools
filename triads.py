#!/usr/bin/env python

# This script generates random triad exercises for music practice.
# Every interval, it prints a random root note, triad type (major, minor,
# diminished, or augmented), direction (↑ or ↓), and inversion (root, 1st, or 2nd).
# Root notes are shuffled so that each of the 12 notes appears once before
# the sequence starts over with a new random order.


import random
import time

INTERVAL_SECONDS = 10

NOTES = [
    "C",
    "Db",
    "D",
    "Eb",
    "E",
    "F",
    "F♯",
    "G",
    "Ab",
    "A",
    "Bb",
    "B",
]

TRIAD_TYPES = [
    "maj",
    "min",
    "diminished",
    "augmented",
]

DIRECTIONS = [
    "↑",
    "↓",
]

INVERSIONS = [
    "root",
    "1st",
    "2nd",
]


def new_note_sequence():
    """Return a shuffled sequence containing all 12 notes exactly once."""
    notes = NOTES.copy()
    random.shuffle(notes)
    return notes


def main():
    note_sequence = new_note_sequence()
    print("↑ Play lowest possible triad up to highest")
    print("↓ Play highest possible triad down to lowest", end="\n\n")

    while True:
        # Start a new cycle when we run out of roots
        if not note_sequence:
            note_sequence = new_note_sequence()

        root = note_sequence.pop()

        triad_type = random.choice(TRIAD_TYPES)
        direction = random.choice(DIRECTIONS)
        inversion = random.choice(INVERSIONS)

        print(
            f"{root} {triad_type:12} {direction} {inversion}",
            flush=True,
        )

        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
