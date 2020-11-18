# -*- coding: utf-8 -*-
import pytest

from flexible_forms.fields import FIELD_TYPES, FieldType


def test_duplicate_field_registration() -> None:
    """Ensure that a user cannot overwrite a field type unless is forces
    replacement."""

    original_field = FIELD_TYPES["SingleLineTextField"]

    with pytest.raises(ValueError):

        class SingleLineTextField(FieldType):
            pass

    # Specifying force_replacement in the Meta options allows a field type to
    # overwrite an existing one.
    class SingleLineTextField(FieldType):
        class Meta:
            force_replacement = True

    FIELD_TYPES["SingleLineTextField"] = original_field


def test_abstract_field_type() -> None:
    """Ensure that abstract field types do not appear in the FIELD_TYPES
    mapping."""

    class CustomFieldType(FieldType):
        class Meta:
            abstract = True

    class ChildFieldType(CustomFieldType):
        pass

    assert CustomFieldType.name not in FIELD_TYPES
    assert ChildFieldType.name in FIELD_TYPES

    del FIELD_TYPES[ChildFieldType.name]
