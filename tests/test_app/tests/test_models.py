# -*- coding: utf-8 -*-

"""Tests for form-related models."""

import warnings
from datetime import timedelta
from typing import Sequence, cast

import pytest
from django import forms
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.base import File
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import models
from django.forms.widgets import HiddenInput, Select, Textarea, TextInput
from django.utils.datastructures import MultiValueDict
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.extra.django import from_form
from test_app.models import AppField, AppRecord
from test_app.tests.factories import FieldFactory, FormFactory

from flexible_forms.fields import (
    FIELD_TYPES,
    FileUploadField,
    IntegerField,
    MultiLineTextField,
    SingleChoiceSelectField,
    SingleLineTextField,
    YesNoRadioField,
)
from flexible_forms.models import (
    BaseField,
    BaseFieldModifier,
    BaseForm,
    BaseRecord,
    BaseRecordAttribute,
    FlexibleForms,
)
from flexible_forms.utils import FormEvaluator
from tests.conftest import ContextManagerFixture


@pytest.mark.django_db
def test_form() -> None:
    """Ensure that forms can be created with minimal specification."""
    form = FormFactory.build(label=None)

    # Ensure that the form has no machine name until it gets saved to the
    # database.
    assert form.name == ""

    # Ensure the form has a friendly string representation
    assert str(form) == "New Form"

    # Ensure that a name is generated for the form upon save.
    form.label = "Test Form"
    form.save()
    assert form.name == "test_form"

    # Ensure that updating the form label does not change the name, which
    # should remain stable.
    form.label = "Updated Test Form"
    form.save()
    assert form.name == "test_form"

    # Ensure the form's friendly string representation reflects the label
    assert str(form) == form.label


@pytest.mark.django_db
def test_field() -> None:
    """Ensure that fields can be created within a form."""
    field = FieldFactory.build(
        form=FormFactory(),
        label=None,
        field_type=SingleLineTextField.name(),
    )

    # Ensure that the field has no machine name until it gets saved to the
    # database.
    assert field.name == ""

    # Ensure the field has a friendly string representation
    assert str(field) == "New Field"

    # Ensure that a machine name is generated for the field on save.
    field.label = "Test Field"
    field.save()
    assert field.name == "test_field"

    # Ensure that updating the field label does not change the name,
    # which should remain stable.
    field.label = "Updated Test Field"
    field.save()
    assert field.name == "test_field"

    # Ensure the field's friendly string representation reflects the label
    assert str(field) == "Updated Test Field"

    # Ensure that a Django form field instance can be produced from the field.
    assert isinstance(field.as_form_field(), forms.Field)

    # Ensure that a Django model field instance can be produced from the field.
    assert isinstance(field.as_model_field(), models.Field)


@pytest.mark.django_db
def test_field_modifier() -> None:
    """Ensure that field modifiers can be created for a field.

    Tests validation logic for expression validity.
    """
    form = FormFactory()

    field_1 = FieldFactory(
        form=form,
        name="field_1",
        label="Test Field 1",
        field_type=SingleLineTextField.name(),
    )

    field_2 = FieldFactory(
        form=form,
        name="field_2",
        label="Test Field 2",
        field_type=SingleLineTextField.name(),
    )

    modifier = field_2.modifiers.create(attribute="required", expression="True")

    # If the modifier has no field, defer validation until save
    modifier.field = None
    modifier.clean()
    assert not modifier._validated
    modifier.field = field_2
    modifier.save()
    assert modifier._validated
    # Saving after validating should not result in a call to clean()
    modifier.save()
    assert modifier._validated

    # Ensure the field modifier has a friendly string representation
    assert str(modifier) == "required = True"

    # Field modifiers that reference fields that don't exist should raise a
    # ValidationError.
    with pytest.raises(ValidationError) as ex:
        modifier.expression = "does_not_exist == 1"
        modifier.clean()

    # The validation message should tell the user what's wrong, and include the
    # name of the invalid variable as well as a list of valid ones.
    assert "no field with that name exists" in str(ex)
    assert "does_not_exist" in str(ex)
    assert ", ".join([field_1.name, field_2.name]) in str(ex)

    # Field modifiers that reference functions that don't exist should raise a
    # ValidationError.
    with pytest.raises(ValidationError) as ex:
        modifier.expression = "does_not_exist()"
        modifier.clean()

    # The validation message should tell the user what's wrong, and include the
    # name of the invalid function as well as a list of valid ones.
    assert "that function does not exist" in str(ex)
    assert "does_not_exist" in str(ex)
    assert ", ".join(FormEvaluator.FUNCTIONS.keys()) in str(ex)

    # Field modifiers that encounter other errors (like TypeErrors for
    # comparisons) should raise a ValidationError.
    with pytest.raises(ValidationError) as ex:
        modifier.expression = "'string' > 1"
        modifier.clean()

    # The validation message should tell the user what's wrong, and include the
    # exception message.
    assert "'>' not supported between instances of 'str' and 'int'" in str(ex)
    assert "expression is invalid" in str(ex)


@pytest.mark.django_db
def test_form_lifecycle() -> None:
    """Ensure that changing form values can change the form structure."""
    form = FormFactory(label="Bridgekeeper")

    name_field = FieldFactory(
        form=form,
        label="What... is your name?",
        name="name",
        field_type=SingleLineTextField.name(),
        required=True,
    )

    # Define a field that is only visible and required if the name field is not
    # empty.
    quest_field = FieldFactory(
        form=form,
        label="What... is your quest?",
        name="quest",
        field_type=MultiLineTextField.name(),
        required=True,
    )
    quest_field.modifiers.create(
        attribute="hidden",
        expression=f"empty({name_field.name})",
    )

    # Define a field that is only visible and required if the name field is not
    # empty.
    favorite_color_field = FieldFactory(
        form=form,
        label="What... is your favorite color?",
        name="favorite_color",
        field_type=SingleChoiceSelectField.name(),
        form_field_options={
            "choices": (
                ("blue", "Blue"),
                ("yellow", "Yellow"),
            ),
        },
        required=True,
    )
    favorite_color_field.modifiers.create(
        attribute="hidden",
        expression="empty(quest)",
    )
    favorite_color_field.modifiers.create(
        attribute="help_text",
        expression="'Auuugh!' if favorite_color == 'yellow' else ''",
    )

    # Initially, the form should have three fields. Only the first field should
    # be visible and required.
    #
    # Since the first field is required, the form should not be valid since we
    # haven't provided a value for it.
    field_values = {}
    django_form = form.as_django_form(data=field_values)

    form_fields = django_form.fields
    assert form_fields["name"].required
    assert isinstance(form_fields["name"].widget, TextInput)
    assert not form_fields["quest"].required
    assert isinstance(form_fields["quest"].widget, HiddenInput)
    assert not form_fields["favorite_color"].required
    assert isinstance(form_fields["favorite_color"].widget, HiddenInput)

    assert not django_form.is_valid()
    assert "name" in django_form.errors

    # Filling out the first field should cause the second field to become
    # visible and required.
    field_values = {
        **field_values,
        "name": "Sir Lancelot of Camelot",
    }
    django_form = form.as_django_form(field_values)

    form_fields = django_form.fields
    assert form_fields["name"].required
    assert isinstance(form_fields["name"].widget, TextInput)
    assert form_fields["quest"].required
    assert isinstance(form_fields["quest"].widget, Textarea)
    assert not form_fields["favorite_color"].required
    assert isinstance(form_fields["favorite_color"].widget, HiddenInput)

    assert not django_form.is_valid()
    assert "quest" in django_form.errors

    # Filling out the second field should expose the last field.
    field_values = {
        **field_values,
        "quest": "To seek the Holy Grail.",
    }
    django_form = form.as_django_form(field_values)

    form_fields = django_form.fields
    assert form_fields["name"].required
    assert isinstance(form_fields["name"].widget, TextInput)
    assert form_fields["quest"].required
    assert isinstance(form_fields["quest"].widget, Textarea)
    assert form_fields["favorite_color"].required
    assert isinstance(form_fields["favorite_color"].widget, Select)

    assert not django_form.is_valid()
    assert "favorite_color" in django_form.errors

    # Filling out the last field with the "wrong" answer should change its help text.
    field_values = {
        **field_values,
        "favorite_color": "yellow",
    }
    django_form = form.as_django_form(field_values)

    form_fields = django_form.fields
    assert form_fields["name"].required
    assert isinstance(form_fields["name"].widget, TextInput)
    assert form_fields["quest"].required
    assert isinstance(form_fields["quest"].widget, Textarea)
    assert form_fields["favorite_color"].required
    assert form_fields["favorite_color"].help_text == "Auuugh!"
    assert isinstance(form_fields["favorite_color"].widget, Select)

    # A completely filled-out form should be valid.
    assert django_form.is_valid(), (
        django_form.errors,
        django_form.data,
        django_form.instance,
    )

    # "Saving" the form with commit=False should produce a record instance with
    # a data property that matches the cleaned form submission, but not
    # actually persist anything to the database.
    record_count = AppRecord.objects.count()
    unpersisted_record = django_form.save(commit=False)
    cleaned_record_data = django_form.cleaned_data
    del cleaned_record_data["form"]
    assert unpersisted_record.data == cleaned_record_data
    assert AppRecord.objects.count() == record_count

    # Saving the form with commit=True should produce the same result as
    # commit=False, but actually persist the changes to the database.
    persisted_record = django_form.save(commit=True)
    assert persisted_record.data == cleaned_record_data
    assert AppRecord.objects.count() == record_count + 1

    # Recreating the form should produce a valid, unchanged form. Calling
    # save() on the form should noop.
    same_form = form.as_django_form(instance=persisted_record)
    assert same_form.initial == same_form.data
    assert same_form.is_valid(), same_form.errors
    assert not same_form.has_changed(), same_form.changed_data
    same_record = same_form.save()
    assert persisted_record is same_record


@pytest.mark.django_db
def test_file_upload() -> None:
    """Ensure that file uploads are handled correctly."""
    form = FormFactory(label="File Upload Form")

    # Define a field that has a modifier that tries to change a nonexistent attribute.
    file_field = FieldFactory(
        form=form,
        label="Upload a file",
        name="file",
        field_type=FileUploadField.name(),
        required=False,
    )

    # Upload a file.
    uploaded_file = SimpleUploadedFile(
        "random-file.txt",
        b"Hello, world!",
        content_type="text/plain",
    )

    # Generate a Django form.
    django_form = form.as_django_form(files={file_field.name: uploaded_file})

    # The form should be valid, and saving it should produce a record.
    assert django_form.is_valid(), django_form.errors
    record = django_form.save()
    assert isinstance(record.data[file_field.name], File)

    # Setting the field to False should result in a null value when cleaned.
    django_form = form.as_django_form(files={file_field.name: False}, instance=record)
    assert django_form.is_valid(), django_form.errors
    record = django_form.save()
    assert record.data[file_field.name]._file is None


@pytest.mark.django_db
def test_initial_values() -> None:
    """Ensure initial values are respected for django forms."""
    form = FormFactory(label="Initial Value Form")

    # Define a field that has a modifier that tries to change a nonexistent attribute.
    field = FieldFactory(
        form=form,
        label="How many?",
        name="test_field",
        field_type=IntegerField.name(),
        required=True,
        initial=0,
    )
    django_form = form.as_django_form()
    assert django_form.initial["test_field"] == "0"

    django_form = form.as_django_form(initial=MultiValueDict({field.name: [123]}))
    assert django_form.initial["test_field"] == 123


@pytest.mark.django_db
def test_noop_modifier_attribute() -> None:
    """Ensure that a nonexistent attribute in a modifier is a noop.

    Field modifiers can be
    """
    form = FormFactory(label="Orphan Field Modifier")

    # Define a field that has a modifier that tries to change a nonexistent attribute.
    field = FieldFactory(
        form=form,
        label="Are we testing?",
        name="test_field",
        field_type=YesNoRadioField.name(),
        required=True,
    )
    modifier = field.modifiers.create(
        attribute="noop_modifier",
        expression=f"empty({field.name})",
    )

    django_form = form.as_django_form()

    # The only effect an unhandled modifier should have is to be present in the
    # modifiers dict.
    assert modifier.attribute in django_form.fields[field.name]._modifiers


@settings(deadline=None, suppress_health_check=(HealthCheck.too_slow,))
@given(st.data())
@pytest.mark.timeout(360)
@pytest.mark.django_db
def test_record(
    patch_field_strategies: ContextManagerFixture,
    duration_strategy: st.SearchStrategy[timedelta],
    rollback: ContextManagerFixture,
    data: st.DataObject,
) -> None:
    """Ensure that Records can be produced from Forms.

    Uses Hypothesis to fuzz-test the fields and find edge cases.
    """
    # Generate a form using one of each field type.
    form = FormFactory(label="Kitchen Sink")

    # Bulk create fields (one per supported field type).
    AppField.objects.bulk_create(
        FieldFactory.build(
            form=form,
            name=f"{field_type}_field",
            field_type=field_type,
            required=True,
            _order=1,
        )
        for field_type in FIELD_TYPES.keys()
    )

    fields: Sequence[AppField] = ()
    for field_type in FIELD_TYPES.keys():
        field = FieldFactory.build(
            form=form,
            field_type=field_type,
            required=True,
        )

        fields = (*fields, field)

    with rollback():
        # Fill out the form (and use the same strategy for the form field as
        # the model field when handling durations)
        with patch_field_strategies({forms.DurationField: duration_strategy}):
            django_form_class = form.as_django_form().__class__
            django_form_instance = cast(
                forms.ModelForm,
                data.draw(from_form(django_form_class)),
            )

        django_form_instance.data["form"] = form

        # Set the files attribute (file fields are read from here).
        django_form_instance.files = {
            field: value
            for field, value in django_form_instance.data.items()
            if isinstance(value, File)
        }

        # Assert that it's valid when filled out (and output the errors if it's
        # not).
        assert (
            django_form_instance.is_valid()
        ), f"The form was not valid: {django_form_instance.errors}"

        # Assert that saving the Django form results in a Record instance.
        record = django_form_instance.save()
        assert isinstance(record, AppRecord)

        # Ensure form records and their attributes have a friendly string representation.
        assert str(record) == f"Record {record.pk} (form_id={record.form_id})"

        sample_attribute = record.attributes.first()
        assert (
            str(sample_attribute)
            == f"RecordAttribute {sample_attribute.pk} (record_id={sample_attribute.record_id}, field_id={sample_attribute.field_id})"
        )

        # Assert that each field value can be retrieved from the database and
        # that it matches the value in the form's cleaned_data construct.
        for field_name, cleaned_value in django_form_instance.cleaned_data.items():
            if field_name == "form":
                continue

            record_value = record.data[field_name]

            if isinstance(record_value, File):
                assert record_value.size == cleaned_value.size
            else:
                assert record_value == cleaned_value


def test_flexible_forms(mocker) -> None:
    """Ensure that the FlexibleForms construct behaves as expected."""
    test_ff = FlexibleForms(model_prefix="Test")

    # All of the model slots should start out empty.
    assert test_ff.form_model is None
    assert test_ff.field_model is None
    assert test_ff.field_modifier_model is None
    assert test_ff.record_model is None
    assert test_ff.record_attribute_model is None

    # Models should be able to be decorated to have them assigned to an
    # appropriate slot based on the flexible_forms base model they inherit
    # from.
    @test_ff
    class TestForm(BaseForm):
        pass

    assert test_ff.form_model is TestForm

    @test_ff
    class TestField(BaseField):
        pass

    assert test_ff.field_model is TestField

    @test_ff
    class TestFieldModifier(BaseFieldModifier):
        pass

    assert test_ff.field_modifier_model is TestFieldModifier

    @test_ff
    class TestRecord(BaseRecord):
        pass

    assert test_ff.record_model is TestRecord

    @test_ff
    class TestRecordAttribute(BaseRecordAttribute):
        pass

    assert test_ff.record_attribute_model is TestRecordAttribute

    # An error should be raised if the decorator is used on a class that
    # doesn't inherit from a flexible_forms base model.
    with pytest.raises(ValueError) as ex:

        @test_ff
        class BrokenModel:
            pass

    assert "BrokenModel" in str(ex)
    assert "must implement one of" in str(ex)
    assert "flexible_forms.models.Base" in str(ex)

    # Leaving a slot empty should result in a model being automatically
    # generated from the appropriate base class.
    test_ff.finalized = False
    test_ff.form_model = None
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message=r"Model [^\s]+ was already registered"
        )
        test_ff.make_flexible()
    assert test_ff.form_model is not None

    # A finalizer should be registered and called when the FlexibleForms object
    # is garbage collected and raise an ImproperlyConfigured error if the user
    # has not called make_flexible().
    #
    # The error message should include the model's module and a mention of the
    # make_flexible call that's missing.
    with pytest.raises(ImproperlyConfigured) as ex:
        test_ff.finalized = False
        test_ff._check_finalized(test_ff)
    assert test_ff.module in str(ex)
    assert "make_flexible" in str(ex)

    # The finalizer should not be called if the user has called make_flexible
    # on their FlexibleForms object.
    test_ff.make_flexible()
    test_ff._check_finalized(test_ff)

    # The finalizer should be called whenever the FlexibleForms object gets
    # garbage collected or destroyed.
    finalizer = mocker.patch.object(test_ff, "_check_finalized")
    del test_ff
    assert finalizer.called_once()
