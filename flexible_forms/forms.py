# -*- coding: utf-8 -*-
"""Forms that power the flexible_forms module."""

import datetime
from typing import Any, Dict, Mapping, Optional, cast

from django import forms
from django.core.files.base import File
from django.forms.fields import FileField
from django.forms.models import ModelChoiceIteratorValue  # type: ignore

from flexible_forms.models import BaseRecord


class BaseRecordForm(forms.ModelForm):
    """A Django form for serializing Form submissions into Record objects.

    It is used as the base class when generating a Django Form from a
    Form object.
    """

    class Meta:
        fields = ("_form",)
        model: "BaseRecord"

    def __init__(
        self,
        data: Optional[Mapping[str, Any]] = None,
        files: Optional[Mapping[str, File]] = None,
        instance: Optional["BaseRecord"] = None,
        initial: Optional[Mapping[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        opts = self._meta  # type: ignore

        # Extract the form definition from the given data, the instance, or the
        # initial values.
        self._form = (
            (data or {}).get("_form")
            or getattr(instance, "_form", None)
            or (initial or {}).get("_form")
        )

        if isinstance(self._form, ModelChoiceIteratorValue):
            self._form = self._form.instance

        # If no record instance was given, create a new (empty) one and use its
        # data for the initial form values.
        instance = instance or opts.model(_form=self._form)
        initial = {**instance._data, **(initial or {}), "_form": self._form}

        super().__init__(
            data=data, files=files, instance=instance, initial=initial, **kwargs
        )

        if self._form:
            self.fields["_form"].disabled = True

    def clean(self) -> Dict[str, Any]:
        """Clean the form data before saving."""
        cleaned_data = super().clean()

        for key, value in cleaned_data.items():
            field = self.fields.get(key)

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

    def save(self, commit: bool = True) -> "BaseRecord":
        """Save the form data to a Record.

        Maps the cleaned form data into the Record's _data field.

        Args:
            commit: If True, persists the data to the database.

        Returns:
            instance: The Record model instance.
        """
        # Update any changed attributes.
        for field_name in self.changed_data:
            setattr(self.instance, field_name, self.cleaned_data[field_name])

        return cast("BaseRecord", super().save(commit=commit))
