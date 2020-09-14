# -*- coding: utf-8 -*-
"""Forms that power the flexible_forms module."""

import datetime
from typing import TYPE_CHECKING, Any, Dict, Mapping, Optional, cast

from django import forms
from django.core.files.base import File
from django.db import transaction
from django.forms.fields import FileField

from flexible_forms.utils import get_record_model

Record = get_record_model()

if TYPE_CHECKING:  # pragma: no cover
    from flexible_forms.models import BaseRecord


class RecordForm(forms.ModelForm):
    """A Django form for serializing Form submissions into Record objects.

    It is used as the base class when generating a Django Form from a
    Form object.
    """

    class Meta:
        model = Record
        fields = ("form",)

    def __init__(
        self,
        data: Optional[Mapping[str, Any]] = None,
        files: Optional[Mapping[str, File]] = None,
        instance: Optional["BaseRecord"] = None,
        initial: Optional[Mapping[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        initial_data = {
            **(instance.data if instance else {}),
            **(initial or {}),
        }

        super().__init__(
            data=data, files=files, instance=instance, initial=initial_data, **kwargs
        )

    def clean(self) -> Dict[str, Any]:
        """Clean the form data before saving."""
        cleaned_data = super().clean()

        for key, value in cleaned_data.items():
            field = {**self.base_fields, **self.fields}.get(key)

            # Time-only values cannot be timezone aware, so we remove the
            # timezone if one is given.
            if isinstance(value, datetime.time):
                value = value.replace(tzinfo=None)

            # If a False value is given for a FileField, it means that the file
            # should be cleared, and its value set to None.
            if isinstance(field, FileField) and value is False:
                value = None

            # Replace the value in cleaned_data with the updated value.
            cleaned_data[key] = value

        return cleaned_data

    @transaction.atomic
    def save(self, commit: bool = True) -> "BaseRecord":
        """Save the form data to a Record.

        Maps the cleaned form data into the Record's _data field.

        Args:
            commit: If True, persists the data to the database.

        Returns:
            instance: The Record model instance.
        """
        record = cast("BaseRecord", super().save(commit=False))

        # If nothing has changed, noop and return the record as-is.
        if not self.has_changed():
            return record

        # Update any changed attributes.
        if commit:
            for field_name in self.changed_data:
                cleaned_value = self.cleaned_data[field_name]

                if field_name in self.Meta.fields:
                    setattr(record, field_name, cleaned_value)
                else:
                    record.set_attribute(field_name, cleaned_value)

                record.save()
        else:
            record_data = self.cleaned_data.copy()
            del record_data["form"]
            record._invalidate_cache()
            record.data = self.cleaned_data

        return record
