# -*- coding: utf-8 -*-
from flexible_forms.utils import (
    empty,
    get_expression_fields,
    interpolate,
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

    # Replace "needle" with "replacement" in a nested complex haystack.
    needle = "needle"
    haystack = (
        ["needle", "not-needle", ("needle",)],
        "needle",
        "not-needle",
        set(["needle", "not-needle"]),
    )
    replacement = "replaced"

    expected_result = (
        ["replaced", "not-needle", ("replaced",)],
        "replaced",
        "not-needle",
        set(["replaced", "not-needle"]),
    )

    assert replace_element(needle, replacement, haystack) == expected_result


def test_get_expression_fields() -> None:
    """Ensure field names can be extracted from a JMESPath expression.

    Ignores the special "null" field, and only returns first-level field
    names.
    """
    expression = "join(', ', [field_1, field_2, field_2.field_2a, null])"
    expected_fields = ("field_1", "field_2")

    assert get_expression_fields(expression) == expected_fields


def test_template_renderers() -> None:
    """Ensure that the interpolate util can render complex types."""
    test_structure = {
        "test": "'{{first}}'",
        "this": 1,
        "dict": {
            "with": {
                "a": ["list", ["of"], 5, "{{variable}}", {"key": "and a {{variable}}"}]
            }
        },
    }

    expected_results = {
        "test": "'the key is test'",
        "this": 1,
        "dict": {
            "with": {
                "a": [
                    "list",
                    ["of"],
                    5,
                    "string variable",
                    {"key": "and a string variable"},
                ]
            }
        },
    }

    assert (
        interpolate(
            test_structure,
            context={"first": "the key is test", "variable": "string variable"},
        )
        == expected_results
    )
