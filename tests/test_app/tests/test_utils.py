# -*- coding: utf-8 -*-
from flexible_forms.utils import empty


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
