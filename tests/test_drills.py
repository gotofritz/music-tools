"""Characterisation tests for drill expansion.

Textual only: `expand_drill` needs no score and no audio, which is what
makes `--expand` work on a config whose snippet is not to hand.
"""

import click
import pytest

from music_tools.loop import expand_drill

ABCD = "[A][B][C][D]"


def markers(**section) -> list[str]:
    """The patterns a drill stands for, without the reference sections."""
    section = {"drill": ABCD, "keep": 1, "reference": 0, **section}
    return [expanded["markers"] for expanded in expand_drill(section, "test")]


def names(**section) -> list[str]:
    section = {"drill": ABCD, "keep": 1, "reference": 0, **section}
    return [expanded["name"] for expanded in expand_drill(section, "test")]


# --- the steps, one at a time ----------------------------------------------


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        (
            "each",
            ["[A][Bx][C][D]", "[A][B][Cx][D]", "[A][B][C][Dx]"],
        ),
        (
            "head",
            ["[A][Bx][C][D]", "[A][Bx][Cx][D]", "[A][Bx][Cx][Dx]"],
        ),
        (
            "tail",
            ["[A][B][C][Dx]", "[A][B][Cx][Dx]", "[A][Bx][Cx][Dx]"],
        ),
        (
            "build",
            ["[A][Bx][Cx][Dx]", "[A][B][Cx][Dx]", "[A][B][C][Dx]"],
        ),
        (
            "widen",
            [
                "[A][Bx][C][D]",
                "[A][B][Cx][D]",
                "[A][B][C][Dx]",
                "[A][Bx][Cx][D]",
                "[A][B][Cx][Dx]",
                "[A][Bx][Cx][Dx]",
            ],
        ),
        (
            "solo",
            [
                "[A][Bx][Cx][Dx]",
                "[Ax][B][Cx][Dx]",
                "[Ax][Bx][C][Dx]",
                "[Ax][Bx][Cx][D]",
            ],
        ),
    ],
)
def test_each_step_over_four_regions_keeping_one(step, expected):
    assert markers(steps=[step]) == expected


def test_a_single_step_may_be_written_without_a_list():
    assert markers(steps="each") == markers(steps=["each"])


# --- composing steps -------------------------------------------------------


def test_steps_run_in_the_order_given():
    assert markers(steps=["tail", "head"])[:3] == markers(steps=["tail"])


def test_a_silencing_already_reached_is_not_repeated():
    """widen ends on the set solo begins with, and the default is both."""
    default = markers()

    assert default == markers(steps=["widen", "solo"])
    assert len(default) == len(set(default))
    assert default[5] == "[A][Bx][Cx][Dx]"  # widen's last
    assert default[6] == "[Ax][B][Cx][Dx]"  # solo's second, its first being a dup


def test_each_is_the_first_pass_of_widen():
    assert markers(steps=["widen"])[:3] == markers(steps=["each"])


# --- keep ------------------------------------------------------------------


def test_keep_zero_lets_a_window_reach_every_region():
    assert markers(steps=["tail"], keep=0)[-1] == "[Ax][Bx][Cx][Dx]"


def test_solo_ignores_keep():
    assert markers(steps=["solo"], keep=0) == markers(steps=["solo"], keep=1)


# --- cycle -----------------------------------------------------------------


def test_a_cycle_lays_the_regions_down_twice_and_drills_the_whole_run():
    cycled = markers(steps=["each"], cycle=2)

    assert len(cycled) == 7  # eight regions, the first held by keep
    assert cycled[0] == "[A-B][B-Cx][C-D][D-END][A-B][B-C][C-D][D-END]"
    assert cycled[-1] == "[A-B][B-C][C-D][D-END][A-B][B-C][C-D][D-ENDx]"


def test_cycling_gives_every_region_an_end_of_its_own():
    """Otherwise the last region would be closed by the first, and run back."""
    for pattern in markers(steps=["each"], cycle=2):
        assert "-" in pattern.split("][")[0]


def test_a_cycled_step_is_named_by_its_place_in_the_cycle():
    assert names(steps=["each"], cycle=2)[0] == "test 1/7: without B-C#2"


# --- reference -------------------------------------------------------------


def test_reference_inserts_the_plain_pattern_before_each_step():
    expanded = expand_drill(
        {"drill": ABCD, "keep": 1, "steps": ["each"], "reference": 1}, "test"
    )

    assert [section["markers"] for section in expanded] == [
        ABCD,
        "[A][Bx][C][D]",
        ABCD,
        "[A][B][Cx][D]",
        ABCD,
        "[A][B][C][Dx]",
    ]
    assert expanded[0]["name"] == "test 1/3: all"
    assert expanded[0]["repeat"] == 1


def test_repeat_applies_to_the_silenced_patterns():
    expanded = expand_drill(
        {"drill": ABCD, "steps": ["each"], "reference": 0, "repeat": 3}, "test"
    )

    assert {section["repeat"] for section in expanded} == {3}


# --- errors ----------------------------------------------------------------


def test_an_unknown_step_names_the_valid_ones():
    with pytest.raises(click.ClickException) as error:
        markers(steps=["nope"])

    assert "no such drill step 'nope'" in error.value.message
    assert "build, each, head, solo, tail, widen" in error.value.message


def test_a_drill_needs_at_least_two_regions():
    with pytest.raises(click.ClickException) as error:
        markers(drill="[A]")

    assert "at least two regions" in error.value.message


def test_keep_may_not_hold_back_every_region():
    with pytest.raises(click.ClickException) as error:
        markers(keep=4)

    assert "only 4 regions" in error.value.message


def test_a_cycle_below_one_is_rejected():
    with pytest.raises(click.ClickException) as error:
        markers(cycle=0)

    assert "at least one pass" in error.value.message
