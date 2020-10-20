# -*- coding: utf-8 -*-
"""Forms that power the flexible_forms module."""

import datetime
from typing import Any, Dict, Mapping, Optional, cast

from django import forms
from django.core.files.base import File
from django.forms.widgets import HiddenInput

from flexible_forms.models import BaseForm, BaseRecord


class BaseRecordForm(forms.ModelForm):
    """A Django form for serializing Form submissions into Record objects.

    It is used as the base class when generating a Django Form from a
    Form object.
    """

    class Meta:
        fields = ("form",)
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
        self.form = (
            (data or {}).get("form")
            or getattr(instance, "form", None)
            or (initial or {}).get("form")
        )

        # In some situations, the form might be a ModelChoiceIteratorValue
        # that needs to be unpacked.
        form_instance = getattr(self.form, "instance", None)
        if isinstance(form_instance, BaseForm):
            self.form = form_instance

        # If no record instance was given, create a new (empty) one and use its
        # data for the initial form values.
        instance = instance or opts.model(form=self.form)
        initial = {**instance._data, **(initial or {}), "form": self.form}

        super().__init__(
            data=data, files=files, instance=instance, initial=initial, **kwargs
        )

        if self.form:
            self.fields["form"].disabled = True
            self.fields["form"].widget = HiddenInput()

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
            if isinstance(field, forms.FileField) and value is False:
                value = None

            # Replace the value in cleaned_data with the updated value.
            cleaned_data[key] = value

        return cleaned_data

    def save(self, commit: bool = True, validate: bool = True) -> "BaseRecord":
        """Save the form data to a Record.

        Maps the cleaned form data into the Record's _data field.

        Args:
            commit: If True, persists the data to the database.
            validate: If False, attempts to persist the record even if
                validation is failing.

        Returns:
            instance: The Record model instance.
        """
        # Update any changed attributes.
        for field_name in self.changed_data:
            setattr(self.instance, field_name, self.cleaned_data[field_name])

        if commit and not validate:
            self.instance.save()
        else:
            super().save(commit=commit)

        return cast("BaseRecord", self.instance)
