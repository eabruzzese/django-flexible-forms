# -*- coding: utf-8 -*-
"""Forms that power the flexible_forms module."""

import datetime
from typing import Any, Dict, Mapping, Optional, cast

from django import forms
from django.core.files.base import File
from django.forms.models import ALL_FIELDS
from django.forms.widgets import HiddenInput

from flexible_forms.cache import cache
from flexible_forms.models import BaseForm, BaseRecord
from flexible_forms.signals import (
    post_form_clean,
    post_form_init,
    post_form_save,
    pre_form_clean,
    pre_form_init,
    pre_form_save,
)


class BaseRecordForm(forms.ModelForm):
    """A Django form for serializing Form submissions into Record objects.

    It is used as the base class when generating a Django Form from a
    Form object.
    """

    class Meta:
        fields = ALL_FIELDS
        model: "BaseRecord"

    def __init__(
        self,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, File]] = None,
        instance: Optional["BaseRecord"] = None,
        initial: Optional[Mapping[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        opts = self._meta  # type: ignore

        # Ensure that data and files are both mutable so that signal handlers
        # can act before the form is initialized.
        data = data.copy() if data is not None else None
        files = files.copy() if files is not None else None

        # Extract the form definition from the given data, the instance, or the
        # initial values.
        self.form = (
            (data or {}).get("form")
            or getattr(instance, "form", None)
            or (initial or {}).get("form")
        )

        if data is not None:
            data["form"] = self.form

        if instance is not None and data is not None:
            data[instance.FlexibleMeta.form_field_name] = self.form

        # In some situations, the form might be a ModelChoiceIteratorValue
        # that needs to be unpacked.
        form_instance = getattr(self.form, "instance", None)
        if isinstance(form_instance, BaseForm):
            self.form = form_instance

        # If no record instance was given, create a new (empty) one and use its
        # data for the initial form values.
        instance = instance or opts.model(form=self.form)
        initial = {**instance._data, **(initial or {}), "form": self.form, instance.FlexibleMeta.form_field_name: self.form}

        # If any of the form fields have a "_value" attribute, use it in either
        # the data (if the form is bound) or the initial (if the form is
        # unbound).
        for field_name, field in self.base_fields.items():
            if not hasattr(field, "_value"):
                continue
            try:
                initial[field_name] = field._value  # type: ignore
                if data is not None and data.get(field_name) is None:
                    data[field_name] = field._value  # type: ignore
                    # Unset the initial value so that the automatic value is detected as a change.
                    initial.pop(field_name, None)
            except (AttributeError, KeyError):
                continue

        # Emit a signal before initializing the form.
        pre_form_init.send(
            sender=self.__class__,
            form=self,
            data=data,
            files=files,
            instance=instance,
            initial=initial,
        )

        super().__init__(
            data=data, files=files, instance=instance, initial=initial, **kwargs
        )

        # If the record has a form associated already, don't allow it to be changed.
        if self.form:
            form_field_name = instance.FlexibleMeta.form_field_name
            if form_field_name in self.fields:
                self.fields[form_field_name].disabled = True
                self.fields[form_field_name].widget = HiddenInput()
            if "form" in self.fields:
                self.fields["form"].disabled = True
                self.fields["form"].widget = HiddenInput()

        # Emit a signal after initializing the form.
        post_form_init.send(
            sender=self.__class__,
            form=self,
        )

    def get_value(self, field_name: str, raw: bool = False) -> Any:
        """Return the value of the field with the given name.

        If raw is specified, returns the value as-is with no cleaning performed.

        Args:
            field_name: The name of the field for which to return the value.
            raw: Return the raw value from the data dict.

        Returns:
            Any: The value of the field.
        """
        field: forms.Field = self.fields[field_name]
        field.widget = cast(forms.Widget, field.widget)

        value = (
            self.get_initial_for_field(field, field_name)
            if field.disabled
            else field.widget.value_from_datadict(
                self.data, self.files, self.add_prefix(field_name)
            )
        )

        # If raw was specified, return the value as-is.
        if raw:
            return value

        # Attempt to clean the field value. This may throw a validation error.
        if isinstance(field, forms.FileField):
            initial = self.get_initial_for_field(field, field_name)
            value = field.clean(value, initial)
        else:
            value = field.clean(value)

        if hasattr(self, f"clean_{field_name}"):
            value = getattr(self, f"clean_{field_name}")()

        return value

    def set_value(self, field_name: str, value: Any) -> None:
        """Set the value of the field with the given name.

        Args:
            field_name: The name of the field for which to set the value.
            value: The new value for the field.
        """
        field: forms.Field = self.fields[field_name]

        if isinstance(field, forms.FileField):
            self.files[field_name] = value
        else:
            self.data[field_name] = value

        # Clear the changed_data cached_property.
        try:
            del self.changed_data
        except AttributeError:
            pass

    def full_clean(self) -> None:
        """Perform a full clean of the form.

        Emits signals before and after, and excludes the form relation
        from validation if it's already set (to eliminate database
        queries related to the schema lookup).
        """
        pre_form_clean.send(sender=self.__class__, form=self)

        # Exclude form relationships that never change to avoid additional
        # database calls during validation.
        excluded_fields = {
            name: self.fields.pop(name)
            for name in frozenset.intersection(
                frozenset(("form", self.instance.FlexibleMeta.form_field_name)),
                frozenset(self.fields.keys())
            )
            if self.form
        }

        super().full_clean()

        # Restore excluded fields and assume that their values are clean.
        for name, field in excluded_fields.items():
            # Restore the field.
            self.fields[name] = field

            if name not in self.data:
                continue

            # Manually "clean" the field value by assuming it's valid.
            value = self.data[name]
            self.cleaned_data[name] = (
                value.instance
                if hasattr(value, "instance")
                else value
            )

        record_pk = self.instance.pk
        record_opts = self.instance._meta
        app_label, model_name = record_opts.app_label, record_opts.model_name

        field_values = {
            **{
                name: field.widget.value_from_datadict(
                    self.data, self.files, self.add_prefix(name)
                )
                for name, field in self.fields.items()
            },
            **getattr(self, "cleaned_data", {}),
        }

        for key, value in field_values.items():
            if isinstance(value, File):
                field_values[key] = value.name

        cache.set(
            f"flexible_forms:field_values:{app_label}:{model_name}:{record_pk}",
            field_values,
            timeout=None,
        )

        post_form_clean.send(
            sender=self.__class__, form=self, field_values=field_values
        )

    def clean(self) -> Dict[str, Any]:
        """Clean the form data before saving."""
        # Emit a signal before initializing the form.

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

    def save(self, commit: bool = True) -> "BaseRecord":
        """Save the form data to a Record.

        Maps the cleaned form data into the Record's _data field.

        Args:
            commit: If True, persists the data to the database.

        Returns:
            instance: The Record model instance.
        """
        pre_form_save.send(sender=self.__class__, form=self)

        # Update any changed attributes.
        for field_name in self.changed_data:
            if field_name not in self.cleaned_data:
                continue
            setattr(self.instance, field_name, self.cleaned_data[field_name])

        super().save(commit=commit)

        post_form_save.send(sender=self.__class__, form=self)

        return cast("BaseRecord", self.instance)
