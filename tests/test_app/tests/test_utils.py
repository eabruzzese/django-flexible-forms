# -*- coding: utf-8 -*-
from test_app.models import (
    CustomField,
    CustomFieldModifier,
    CustomForm,
    CustomRecord,
    CustomRecordAttribute,
)

from flexible_forms.utils import (
    empty,
    get_field_model,
    get_field_modifier_model,
    get_form_model,
    get_record_attribute_model,
    get_record_model,
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


def test_swappable_models() -> None:
    """Ensure that get_modelname_model() returns the model."""
    assert get_form_model() is CustomForm
    assert get_field_model() is CustomField
    assert get_field_modifier_model() is CustomFieldModifier
    assert get_record_model() is CustomRecord
    assert get_record_attribute_model() is CustomRecordAttribute
