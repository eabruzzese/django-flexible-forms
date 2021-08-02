# -*- coding: utf-8 -*-
"""Forms that power the flexible_forms module."""

import datetime
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, cast

import django
from django import forms
from django.core.exceptions import ValidationError
from django.core.files.base import File
from django.forms.models import ALL_FIELDS
from django.forms.widgets import HiddenInput
from django.utils.datastructures import MultiValueDict

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

if django.VERSION >= (3, 1):  # pragma: no-cover
    from django.forms.models import ModelChoiceIteratorValue  # type: ignore


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
        prefix: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        opts = self._meta  # type: ignore

        # Set the prefix if we were given one (we'll need it for a modifier).
        self.prefix = prefix

        # Ensure that data and files are both mutable so that signal handlers
        # can act before the form is initialized.
        data = data.copy() if data is not None else None
        files = files.copy() if files is not None else None

        # If we don't have an instance (e.g., we're adding a new record), we try
        # to derive the BaseForm from the given parameters.
        #
        # If we can't derive a BaseForm (e.g. we're totally unbound and there's
        # no BaseForm identifier in the initial data) then we behave as a
        # totally normal ModelForm, only presenting the BaseForm's concrete
        # attributes.
        RecordModel = opts.model
        FormModel = RecordModel._flexible_model_for(BaseForm)
        form_field_name = RecordModel.FlexibleMeta.form_field_name

        # Try to get some kind of specifier for the BaseForm we should use.
        #
        #   1. Look in the data parameter to see if one was sumbitted with the
        #      form data.
        #   2. If it wasn't in the form data, see if the instance is related to
        #      a BaseForm.
        #   3. Look in the initial parameter to see if we were given a BaseForm
        #      either manually or by the as_django_form() method on the BaseForm
        #      model.
        #
        # If all of these fail, we'll fall back to behaving as a normal
        # ModelForm: the form will only have fields for the direct model
        # attributes of a BaseRecord until it has a relationship to a BaseForm.
        #
        form = (data or {}).get(form_field_name)
        form = form or getattr(instance, form_field_name, None)
        form = form or (initial or {}).get(form_field_name)

        # Depending on how the RecordForm is being created, the form might be:
        #
        #   3. A ModelChoiceIteratorValue (Django 3.1+), which has an "instance"
        #      property containing the form instance that we unpack.
        #   4. A primary key value (an int or a string) that we use to query
        #      for the BaseForm.
        #   1. None or a BaseForm instance, in which case we do nothing.
        if django.VERSION >= (3, 1) and isinstance(form, ModelChoiceIteratorValue):
            form = form.instance
        if isinstance(form, int) or (isinstance(form, str) and form.isdigit()):
            form = FormModel.objects.get(pk=form)

        # If the form is bound, make sure that data holds a reference to the
        # form object, and disable the form field.
        is_bound = data is not None or files is not None
        if is_bound:
            data = cast(Dict[str, Any], data or MultiValueDict())
            data[form_field_name] = form

        # Inject the instance's _data (form field values) into the initial dict.
        # If we weren't given an instance, we make a new one (but don't persist
        # it) for consistency.
        instance = instance or opts.model(**{form_field_name: form})
        initial = {
            **instance._data,
            **(initial or {}),
            form_field_name: form,
        }

        # If any of the form fields have a "_value" attribute, use it in either
        # the data (if the form is bound) and/or the initial (if the form is
        # unbound).
        modified_fields = {
            k: v for k, v in self.base_fields.items() if hasattr(v, "_value")
        }
        for field_name, field in modified_fields.items():
            field_name = self.add_prefix(field_name)

            try:
                field_value = field._value  # type: ignore
            except AttributeError:
                continue

            # Set the initial value.
            initial[field_name] = field_value

            # For unbound forms, data and files are both None, so we can't set
            # values in them and we continue on.
            if not is_bound:
                continue

            files = cast(Dict[str, File], files or MultiValueDict())
            data = cast(Dict[str, Any], data or MultiValueDict())
            value = data.get(field_name, files.get(field_name))

            # If the field was already assigned a non-empty value, don't try to
            # overwrite it.
            if value not in field.empty_values:
                continue

            # Set the appropriate data element (files for FileFields, data for
            # everything else) to the field's new value.
            if isinstance(field, forms.FileField):
                files[field_name] = field_value
            else:
                data[field_name] = field_value

            # Unset the initial value so that the automatically-set value is
            # detected as a change when the form is saved.
            initial.pop(field_name, None)

        # Emit a signal before initializing the form.
        pre_form_init.send(
            sender=self.__class__,
            form=self,
            data=data,
            files=files,
            instance=instance,
            initial=initial,
        )

        # Initialize the form as usual.
        super().__init__(
            data=data, files=files, instance=instance, initial=initial, **kwargs
        )

        # Hide and disable the form input if the BaseRecord is already persisted
        # with a relationship to its BaseForm.
        if form is not None and form_field_name in self.fields:
            form_field = self.fields[form_field_name]
            form_field.widget = HiddenInput()
            form_field.disabled = instance.pk and getattr(
                instance, f"{form_field_name}_id", None
            )

        # Emit a signal after initializing the form.
        post_form_init.send(
            sender=self.__class__,
            form=self,
        )

    def full_clean(self) -> None:
        """Perform a full clean of the form.

        Emits signals before and after, and excludes the form relation
        from validation if it's already set (to eliminate database
        queries related to the schema lookup).
        """
        pre_form_clean.send(sender=self.__class__, form=self)

        super().full_clean()

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

        clean_responses = post_form_clean.send_robust(
            sender=self.__class__, form=self, field_values=field_values
        )

        for _, response in clean_responses:
            if not isinstance(response, BaseException):
                continue
            if isinstance(response, ValidationError):
                self.add_error(None, response)
            raise response

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
