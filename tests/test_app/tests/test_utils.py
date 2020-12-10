# -*- coding: utf-8 -*-
from flexible_forms.utils import (
    LenientFormatter,
    empty,
    get_expression_fields,
    replace_element,
)


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


def test_lenient_formatter() -> None:
    """Ensure that the LenientFormatter behaves as expected."""
    formatter = LenientFormatter()

    assert (
        formatter.format("Missing indexes are blank: {0}")
        == "Missing indexes are blank: "
    )
    assert (
        formatter.format("Supplied indexes are interpolated: {0}", "zero")
        == "Supplied indexes are interpolated: zero"
    )
    assert (
        formatter.format("Missing keywords are blank: {keyword}")
        == "Missing keywords are blank: "
    )
    assert (
        formatter.format(
            "Supplied keywords are interpolated: {keyword}", keyword="keyword"
        )
        == "Supplied keywords are interpolated: keyword"
    )


def test_get_expression_fields() -> None:
    """Ensure that a set of field names can be extracted from a JMESPath expression."""
    assert get_expression_fields(
        "join(', ', [field_1, field_2, field_2.field_2a, null])"
    ) == set(["field_1", "field_2"])
