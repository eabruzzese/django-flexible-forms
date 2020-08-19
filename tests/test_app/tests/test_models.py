# -*- coding: utf-8 -*-

"""Tests for form-related models."""

from datetime import timedelta
from typing import Sequence, cast

import pytest
from django import forms
from django.core.files.base import File
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.extra.django import from_form
from test_app.models import CustomField, CustomRecord

from flexible_forms.fields import FIELDS_BY_KEY
from tests.conftest import ContextManagerFixture
from tests.test_app.tests.factories import FieldFactory, FormFactory


@pytest.mark.django_db
def test_form() -> None:
    """Ensure that forms can be created with minimal specification."""
    form = FormFactory.build(label='Test Form')

    # Ensure that the form has no machine name until it gets saved to the database.
    assert form.machine_name == ''

    # Ensure that a machine_name is generated for the form upon save.
    form.save()
    assert form.machine_name == 'test_form'

    # Ensure that updating the form label does not change the machine_name, which
    # should remain stable.
    form.label = 'Updated Test Form'
    form.save()
    assert form.machine_name == 'test_form'


@pytest.mark.django_db
def test_field() -> None:
    """Ensure that fields can be created within a form."""
    field = FieldFactory.build(
        form=FormFactory(),
        label='Test Field',
        field_type='SINGLE_LINE_TEXT',
    )

    # Ensure that the field has no machine name until it gets saved to the database.
    assert field.machine_name == ''

    # Ensure that a machine name is generated for the field on save.
    field.save()
    assert field.machine_name == 'test_field'

    # Ensure that updating the field label does not change the machine_name,
    # which should remain stable.
    field.label = 'Updated Test Field'
    field.save()
    assert field.machine_name == 'test_field'

    # Ensure that a Django form field instance can be produced from the field.
    assert isinstance(field.as_form_field(), forms.Field)


@settings(deadline=None, suppress_health_check=(HealthCheck.too_slow,))
@given(st.data())
@pytest.mark.django_db
def test_record(
    patch_field_strategies: ContextManagerFixture,
    duration_strategy: st.SearchStrategy[timedelta],
    rollback: ContextManagerFixture,
    data: st.DataObject
) -> None:
    """Ensure that Records can be produced from Forms.

    Uses Hypothesis to fuzz-test the fields and find edge cases.
    """
    # Generate a form using one of each field type.
    form = FormFactory(label='Kitchen Sink')

    # Bulk create fields (one per supported field type).
    CustomField.objects.bulk_create(
        FieldFactory.build(
            form=form,
            machine_name=f'{field_type}_field',
            field_type=field_type,
            required=True,
            _order=1
        )
        for field_type in FIELDS_BY_KEY.keys()
    )

    fields: Sequence[CustomField] = ()
    for field_type in FIELDS_BY_KEY.keys():
        field = FieldFactory.build(
            form=form,
            field_type=field_type,
            required=True
        )

        fields = (*fields, field)

    django_form_class = form.as_form_class()

    with rollback():
        # Fill out the form (and use the same strategy for the form field as
        # the model field when handling durations)
        with patch_field_strategies({forms.DurationField: duration_strategy}):
            django_form_instance = cast(
                forms.ModelForm,
                data.draw(from_form(django_form_class))
            )

        django_form_instance.data['form'] = form

        # Set the files attribute (file fields are read from here).
        django_form_instance.files = {
            field: value
            for field, value in django_form_instance.data.items()
            if isinstance(value, File)
        }

        # Assert that it's valid when filled out (and output the errors if it's not).
        assert django_form_instance.is_valid(), (
            f'The form was not valid: {django_form_instance.errors}'
        )

        # Assert that saving the Django form results in a Record instance.
        record = django_form_instance.save()
        assert isinstance(record, CustomRecord)

        # Re-fetch the record so that we can test prefetching.
        record = CustomRecord.objects.get(pk=record.pk)

        # Assert that the Record has one attribute per field type.
        assert record.attributes.count() == len(FIELDS_BY_KEY)

        # Assert that each field value can be retrieved from the database and
        # that it matches the value in the form's cleaned_data construct.
        for field_name, cleaned_value in django_form_instance.cleaned_data.items():
            if field_name == 'form':
                continue

            record_value = record.data[field_name]

            if isinstance(record_value, File):
                assert record_value.size == cleaned_value.size
            else:
                assert record_value == cleaned_value
