# -*- coding: utf-8 -*-
from flexible_forms.utils import empty, replace_element


def test_empty() -> None:
    """Ensure that the empty() function behaves as expected.

    `empty()` is a helper function used with the expression evaluator
    that can be used in expressions to determine if a value is empty
    (while handling booleans properly).
    """
    assert empty("")
    assert not empty("not empty")
    assert empty([])
    assert not empty(["not empty"])
    assert empty(set())
    assert not empty(set(["not empty"]))
    assert empty({})
    assert not empty({"not": "empty"})
    assert empty(None)
    assert not empty(True)
    assert not empty(False)


def test_replace_element() -> None:
    """Ensure that replace_element recursively replaces elements in a data
    structure."""
    needle = "needle"
    replacement = "replacement"
    haystack = (
        ["needle", "not-needle", ("needle",)],
        "needle",
        "not-needle",
        set(["needle", "not-needle"]),
    )
    expected_result = (
        ["replacement", "not-needle", ("replacement",)],
        "replacement",
        "not-needle",
        set(["replacement", "not-needle"]),
    )

    assert replace_element(needle, replacement, haystack) == expected_result
