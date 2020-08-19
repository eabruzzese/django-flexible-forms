"""Forms that power the flexible_forms module."""

import datetime
from typing import Any, Dict, Mapping, Optional, cast

import swapper
from django import forms
from django.core.files.base import File
from django.db import transaction

from flexible_forms.models import RecordAttribute

Record = swapper.load_model('flexible_forms', 'Record')
RecordAttribute = swapper.load_model('flexible_forms', 'RecordAttribute')


class RecordForm(forms.ModelForm):
    """A Django form for serializing Form submissions into Record objects.

    It is used as the base class when generating a Django Form from a Form object.
    """

    class Meta:
        model = Record
        fields = ('form',)

    def __init__(
        self,
        data: Optional[Mapping[str, Any]] = None,
        files: Optional[Mapping[str, File]] = None,
        *args: Any,
        **kwargs: Any
    ) -> None:
        instance = kwargs.get('instance', None)
        data = data or kwargs.get('data', {})
        files = files or kwargs.get('files', {})

        # If an instance was supplied, merge its data/files with any data/files
        # given to the form constructor.
        if instance:
            # Merge any submitted data into the existing instance data.
            data = {
                **instance.data,
                'form': instance.form,
                **{
                    k: data.get(k)
                    for k in data.keys()
                    if k in self.declared_fields.keys()
                }
            }

            # Merge any submitted files into the existing file-type values from
            # the instance data.
            files = {
                **{
                    k: v
                    for k, v in instance.data.items()
                    if isinstance(v, File)
                },
                **files
            }

        super().__init__(data, files, *args, **kwargs)

    def clean(self) -> Dict[str, Any]:
        """Clean the form data before saving."""
        cleaned_data = super().clean()

        for key, value in cleaned_data.items():
            # Time-only values cannot be timezone aware, so we remove the
            # timezone if one is given.
            if isinstance(value, datetime.time):
                value = value.replace(tzinfo=None)

            # Replace the value in cleaned_data with the updated value.
            cleaned_data[key] = value

        return cleaned_data

    @transaction.atomic
    def save(self, commit: bool = True) -> Record:
        """Save the form data to a Record.

        Maps the cleaned form data into the Record's _data field.

        Args:
            commit (bool): If True, persists the data to the database.

        Returns:
            instance (Record): The Record model instance.
        """
        record = cast(Record, super().save(commit=False))

        if commit:
            record.save()

        form = self.cleaned_data['form']

        # Regenerate the record's attributes.
        record.attributes.all().delete()

        attributes = []
        for field in form.fields.all():
            attribute = RecordAttribute(
                record=record,
                field=field,
            )
            attribute.value_type = field.as_model_field()
            attribute.value = self.cleaned_data.get(field.machine_name)
            attributes.append(attribute)

        RecordAttribute.objects.bulk_create(attributes)

        # Re-fetch the Record instance.
        return Record.objects.get(pk=record.pk)
