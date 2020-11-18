# -*- coding: utf-8 -*-

"""Tests for form-related models."""

import hashlib
from datetime import timedelta
from typing import Sequence, cast

import pytest
from django import forms
from django.core import management
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.base import File
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, models
from django.forms.widgets import HiddenInput, Select, Textarea, TextInput
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.extra.django import from_form
from test_app.models import AppField, AppForm, AppRecord, AppRecordAttribute
from test_app.tests.factories import FieldFactory, FormFactory

from flexible_forms.fields import (
    FIELD_TYPES,
    DateTimeField,
    FileUploadField,
    IntegerField,
    MultiLineTextField,
    SingleChoiceSelectField,
    SingleLineTextField,
    YesNoRadioField,
)
from flexible_forms.models import (
    AliasField,
    BaseForm,
    FlexibleBaseModel,
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
    assert str(form) == "Untitled AppForm"

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
        field_type=SingleLineTextField.name,
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
        field_type=SingleLineTextField.name,
    )

    field_2 = FieldFactory(
        form=form,
        name="field_2",
        label="Test Field 2",
        field_type=SingleLineTextField.name,
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


@pytest.mark.django_db(transaction=True)
def test_fieldset() -> None:
    """Ensure that Django fieldsets can be produced for a Form."""
    form = FormFactory(label="Fieldsets Test")

    first_name_field = FieldFactory(
        form=form,
        label="First name",
        name="first_name",
        field_type=SingleLineTextField.name,
    )
    last_name_field = FieldFactory(
        form=form,
        label="Last name",
        name="last_name",
        field_type=SingleLineTextField.name,
    )

    birth_date_field = FieldFactory(
        form=form,
        label="Birth date",
        name="birth_date",
        field_type=DateTimeField.name,
    )

    avatar_field = FieldFactory(
        form=form, label="Avatar", name="avatar", field_type=FileUploadField.name
    )

    bio_field = FieldFactory(
        form=form, label="Bio", name="bio", field_type=MultiLineTextField.name
    )

    # A form with no fieldsets should return an empty list for as_django_fieldsets().
    assert form.as_django_fieldsets() == []

    # Create a fieldset for collecting basic info. It should have no header or description.
    basic_fieldset = form.fieldsets.create()

    # The fieldset should have a friendly name that includes its ID in __str__.
    assert str(basic_fieldset.pk) in str(basic_fieldset)

    # First and last name should appear on the same line within the fieldset.
    basic_fieldset.items.create(
        field=first_name_field, vertical_order=0, horizontal_order=0
    )
    basic_fieldset.items.create(
        field=last_name_field, vertical_order=0, horizontal_order=1
    )
    # Birth date should appear on its own line. Horizontal and vertical order
    # should act as a (weight as opposed to an index), so higher numbers in
    # either field should not result in gaps or empty elements in the rendered
    # fieldsets.
    basic_fieldset.items.create(
        field=birth_date_field, vertical_order=10, horizontal_order=10
    )

    # Create a fieldset for collecting profile info. It should have a header,
    # description, and CSS class names that will be split on spaces.
    profile_fieldset = form.fieldsets.create(
        name="Profile", description="Profile info", classes="profile collapse"
    )

    profile_fieldset.items.create(
        field=avatar_field, vertical_order=0, horizontal_order=0
    )

    # Trying to put a field in the same slot as another field should raise an error.
    with pytest.raises(IntegrityError):
        profile_fieldset.items.create(
            field=bio_field, vertical_order=0, horizontal_order=0
        )

    fieldset_item = profile_fieldset.items.create(
        field=bio_field, vertical_order=1, horizontal_order=1
    )

    # The fieldset should have a friendly name that includes its ID in __str__.
    assert str(fieldset_item.pk) in str(fieldset_item)

    assert form.as_django_fieldsets() == [
        # The basic fieldset should come first and have no heading, classes, or description.
        (
            None,
            {
                "classes": (),
                "description": None,
                "fields": (
                    # The first and last name fields should be grouped together.
                    ("first_name", "last_name"),
                    # The birth date field should be on its own line,
                    # unwrapped, with no gaps or empty elements from the higher
                    # vertical and horizontal order numbers.
                    "birth_date",
                ),
            },
        ),
        # The profile fieldset should come last and have appropriate metadata values.
        (
            "Profile",
            {
                "classes": ("profile", "collapse"),
                "description": "Profile info",
                "fields": ("avatar", "bio"),
            },
        ),
    ]


@pytest.mark.django_db
def test_form_lifecycle() -> None:
    """Ensure that changing form values can change the form structure."""
    form = FormFactory(label="Bridgekeeper")

    name_field = FieldFactory(
        form=form,
        label="What... is your name?",
        name="name",
        field_type=SingleLineTextField.name,
        required=True,
    )

    # Define a field that is only visible and required if the name field is not
    # empty.
    quest_field = FieldFactory(
        form=form,
        label="What... is your quest?",
        name="quest",
        field_type=MultiLineTextField.name,
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
        field_type=SingleChoiceSelectField.name,
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
    assert unpersisted_record._data == cleaned_record_data
    assert AppRecord.objects.count() == record_count

    # Saving the form with commit=True should produce the same result as
    # commit=False, but actually persist the changes to the database.
    persisted_record = django_form.save(commit=True)
    assert persisted_record._data == cleaned_record_data
    assert AppRecord.objects.count() == record_count + 1

    # Recreating the form from the persisted record should produce a valid,
    # unchanged form. Calling save() on the form should noop.
    same_form = persisted_record.as_django_form(field_values)
    assert same_form.initial == {**persisted_record._data, "form": form}
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
        field_type=FileUploadField.name,
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
    assert isinstance(record.file, File)

    # Setting the field to False should result in a null value when cleaned.
    django_form = form.as_django_form(files={file_field.name: False}, instance=record)
    assert django_form.is_valid(), django_form.errors
    record = django_form.save()
    assert record.file._file is None


@pytest.mark.django_db
def test_initial_values() -> None:
    """Ensure initial values are respected for django forms."""
    form = FormFactory(label="Initial Value Form")

    # Define a field that has a modifier that tries to change a nonexistent attribute.
    field = FieldFactory(
        form=form,
        label="How many?",
        name="test_field",
        field_type=IntegerField.name,
        required=True,
        initial=0,
    )
    django_form = form.as_django_form()
    assert not django_form.is_bound
    assert django_form.initial.get(field.name) == field.initial

    django_form = form.as_django_form(data={})
    assert django_form.is_bound
    assert django_form.initial.get(field.name) == field.initial

    django_form = form.as_django_form(initial={field.name: 123})
    assert not django_form.is_bound
    assert django_form.initial.get(field.name) == 123

    django_form = form.as_django_form(data={}, initial={field.name: 123})
    assert django_form.is_bound
    assert django_form.initial.get(field.name) == 123


@pytest.mark.django_db
def test_noop_modifier_attribute() -> None:
    """Ensure that a nonexistent attribute in a modifier is a noop.

    If a FieldModifier modifies an attribute that does not exist on the
    field and has no explicit handler on the field type, its only effect
    should be that it appears in the "_modifiers" dict on the rendered
    form field.
    """
    form = FormFactory(label="Orphan Field Modifier")

    # Define a field that has a modifier that tries to change a nonexistent attribute.
    field = FieldFactory(
        form=form,
        label="Are we testing?",
        name="test_field",
        field_type=YesNoRadioField.name,
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
            django_form = cast(
                forms.ModelForm,
                data.draw(from_form(type(form.as_django_form()))),
            )

        django_form.data["form"] = form

        # Set the files attribute (file fields are read from here).
        django_form.files = {
            field: value
            for field, value in django_form.data.items()
            if isinstance(value, File)
        }

        # Assert that it's valid when filled out (and output the errors if it's
        # not).
        assert django_form.is_valid(), f"The form was not valid: {django_form.errors}"

        # Assert that saving the Django form results in a Record instance.
        record = django_form.save()
        assert isinstance(record, AppRecord)

        # Ensure form records and their attributes have a friendly string representation.
        assert str(record) == f"{form.label} {record.pk}"
        assert str(AppRecord()) == f"New Record"

        sample_attribute = record.attributes.first()
        assert (
            str(sample_attribute)
            == f"RecordAttribute {sample_attribute.pk} (record_id={sample_attribute.record_id}, field_id={sample_attribute.field_id})"
        )

        # Assert that each field value can be retrieved from the database and
        # that it matches the value in the form's cleaned_data construct.
        for field_name, cleaned_value in django_form.cleaned_data.items():
            record_value = getattr(record, field_name)

            # File comparisons
            if isinstance(record_value, File):
                assert record_value.size == cleaned_value.size
                assert (
                    hashlib.sha1(record_value.read()).hexdigest()
                    == hashlib.sha1(cleaned_value.read()).hexdigest()
                ), (
                    f"The file cleaned by the RecordForm is different from "
                    f"the file stored on the Record's '{field_name}' field."
                )
            else:
                assert (
                    record_value == cleaned_value
                ), f"Expected the record {field_name} to have value {repr(cleaned_value)} but got {repr(record_value)}"


@pytest.mark.django_db
def test_disabled_validation() -> None:
    """Ensure that validation can be skipped when saving a record form.

    In some scenarios it's useful to be able to save a record in an
    invalid state (e.g., storing form inputs to be modified later).
    Passing validate=False to form.save() will trigger this behavior.
    """
    form = FormFactory()

    # Generate a field of every type and make them required.
    AppField.objects.bulk_create(
        FieldFactory.build(
            form=form,
            name=f"{field_type}_field",
            field_type=field_type,
            required=True,
            _order=0,
        )
        for field_type in FIELD_TYPES.keys()
    )

    # Create a Django form from our form definition.
    django_form = form.as_django_form(data={})

    # The form should not be valid because we haven't entered any data yet.
    assert not django_form.is_valid()

    # Attempting to save the form normally will raise a ValidationError.
    with pytest.raises(ValueError):
        django_form.save()

    # Passing validate=False should allow the record to be saved.
    record = django_form.save(validate=False)

    # Trying to save a record containing completely invalid data for a field
    # should make a best effort to save as many attributes as possible.
    record.SingleLineTextField_field = "some different text"
    record.DateTimeField_field = "not a datetime"
    with pytest.raises(ValidationError):
        record.save()


@pytest.mark.django_db
def test_record_queries(django_assert_num_queries) -> None:
    """Ensure that a minimal number of queries is required to fetch records."""
    forms_count = 3
    fields_per_form_count = len(FIELD_TYPES)
    records_per_form_count = 1

    forms = FormFactory.create_batch(forms_count)

    for form in forms:
        AppField.objects.bulk_create(
            FieldFactory.build(
                form=form, name=f"{field_type}_field", field_type=field_type, _order=0
            )
            for field_type in FIELD_TYPES.keys()
        )

        record = AppRecord.objects.create(form=form)
        for field in form.fields.all():
            setattr(record, field.name, None)
        record.save()

    # There should be `forms_count` forms in the database.
    assert AppForm.objects.count() == forms_count

    # There should be `forms_count * fields_per_form_count` fields in the database (one field per type in FIELD_TYPES).
    assert AppField.objects.count() == forms_count * fields_per_form_count

    # There should be `forms_count * records_per_form_count` records in the database.
    assert AppRecord.objects.count() == forms_count * records_per_form_count

    # There should be `forms_count * fields_per_form_count` records in the database (one record per form, one field per type in FIELD_TYPES).
    assert AppRecordAttribute.objects.count() == forms_count * fields_per_form_count

    # By default, the records QuerySet should only require these queries do
    # perform all of the core responsibilities of the library from the
    # perspective of Record instances (which is what most implementations will
    # be interacting with most of the time in e.g. views):
    #
    #   1. One to fetch the list of records; this should include a prefetch of its form.
    #   2. One to fetch the list of the fields on the record's form.
    #   3. One to fetch the list of field modifiers fields on the record's form.
    #   4. One to fetch the list of fieldsets for each record's form.
    #   5. One to fetch the list of attributes for all of the records.
    #
    with django_assert_num_queries(5):
        records = list(AppRecord.objects.all())

    # Fetching the data from any of the records should not require any
    # additional queries.
    with django_assert_num_queries(0):
        for record in records:
            assert record._data != {}

    # Validating an existing record against its Django form with no changes
    # should require only the queries needed to validate that the form is
    # still a valid Form instance.
    with django_assert_num_queries(2):
        record = records[0]
        django_form = record.form.as_django_form(data={}, instance=record)
        assert django_form.is_valid(), django_form.errors

    # Updating a record using a Django form should require these queries:
    #
    #   * Two SELECTs as part of form validation, both used to check that the
    #     value of the form field is valid.
    #   * A SAVEPOINT query before saving the model.
    #   * A single query to update the Record itself.
    #   * A single bulk_update query to update the attributes that have changed.
    #   * A RELEASE SAVEPOINT query after all of the queries have been executed.
    #
    with django_assert_num_queries(6):
        record = records[1]
        new_record_values = {
            f"{SingleLineTextField.name}_field": "new_value",
            f"{MultiLineTextField.name}_field": "another\nnew\nvalue",
        }
        django_form = record.form.as_django_form(
            instance=record, data=new_record_values
        )
        assert django_form.is_valid(), django_form.errors

        updated_record = django_form.save()

        for attr, value in new_record_values.items():
            assert getattr(updated_record, attr) == value


def test_flexible_forms(mocker) -> None:
    """Ensure that the FlexibleForms construct behaves as expected."""
    test_ff = FlexibleForms(model_prefix="Test")

    # Attempting to look up an unregistered model before make_flexible is
    # called should generate a LookupError.
    with pytest.raises(LookupError):
        test_ff.get_model("flexible_forms.baseform")

    # Calling make_flexible on a FlexibleForms object should generate a set of
    # models: one for every direct subclass of FlexibleBaseModel.
    #
    # These models should be able to be accessed using the get_model utility
    # provided by the FlexibleForms object.
    test_ff.make_flexible()
    for base_model in FlexibleBaseModel.__subclasses__():
        concrete_model = test_ff.get_model(base_model)

        # Every concrete model should hold a reference to the FlexibleForms
        # object.
        assert concrete_model.flexible_forms is test_ff

        # The concrete model generated by make_flexible should be a subclass of
        # a flexible base model, and _get_flexible_base_model should be able to
        # resolve it.
        assert test_ff._get_flexible_base_model(concrete_model) is base_model

    # Trying to resolve the flexible base model for a class that does not
    # inherit from it should generate a ValueError.
    with pytest.raises(ValueError):

        class IrrelevantClass(object):
            pass

        test_ff._get_flexible_base_model(IrrelevantClass)

    # A finalizer should be registered and called when the FlexibleForms object
    # is garbage collected and raise an ImproperlyConfigured error if the user
    # has not called make_flexible().
    #
    # The error message should include the model's module and a mention of the
    # make_flexible call that's missing.
    with pytest.raises(ImproperlyConfigured) as ex:
        test_ff.finalized = False
        test_ff._check_finalized(test_ff)
    assert test_ff.module.__name__ in str(ex)
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


@pytest.mark.django_db(transaction=True)
def test_flexible_forms_partial_groups() -> None:
    """Ensure that model groups can be defined with only a subset of custom
    implementations."""
    test_ff = FlexibleForms(model_prefix="Partial")

    class PartialForm(test_ff.BaseForm, models.Model):
        pass

    class PartialRecord(test_ff.BaseRecord):
        class Meta:
            indexes = [models.Index(fields=("form",))]
            constraints = [
                models.UniqueConstraint(fields=("form", "id"), name="test_constraint")
            ]

        class FlexibleMeta(test_ff.BaseRecord.FlexibleMeta):
            form_field_name = "form_alias"

    # Calling make_flexible on a partial group should "fill in the gaps" and
    # generate models for any of the missing flexible form components.
    test_ff.make_flexible()
    for base_model in FlexibleBaseModel.__subclasses__():
        try:
            concrete_model = test_ff.get_model(base_model)
        except LookupError:
            pytest.fail(
                f"No concrete model was registered for the {base_model.__name__} model."
            )
            raise

        # The registered model's name should begin with the configured model
        # prefix.
        assert concrete_model.__name__.startswith(test_ff.model_prefix)

    management.call_command("migrate", run_syncdb=True)


@pytest.mark.django_db(transaction=True)
def test_alias_field() -> None:
    """Ensure that the AliasField behaves transparently."""
    test_ff = FlexibleForms(model_prefix="Alias")

    class AliasedField(test_ff.BaseField):

        # An aliased mundane (non-relation) attribute.
        name_alias = AliasField(test_ff.BaseField._meta.get_field("name"))

        class FlexibleMeta(test_ff.BaseField.FlexibleMeta):
            # Replace the "form" relation attribute with "form_relation", and
            # create an AliasField pointing "form" to "form_relation".
            form_field_name = "form_relation"

    test_ff.make_flexible()

    # Migrate the database.
    management.call_command("migrate", run_syncdb=True)

    AliasedForm = test_ff.get_model(BaseForm)

    # The aliased_form attribute should be a ForeignKey, and there should be an AliasField named "form" pointing to it.
    assert isinstance(AliasedField._meta.get_field("form_relation"), models.ForeignKey)
    assert isinstance(AliasedField._meta.get_field("form"), AliasField)

    # The name_alias should be an AliasField pointing to "name", which should
    # be a concrete text field.
    assert isinstance(AliasedField._meta.get_field("name_alias"), AliasField)
    assert isinstance(AliasedField._meta.get_field("name"), models.TextField)

    test_form = AliasedForm.objects.create(label="Test Aliased Field")
    test_field = AliasedField(
        form=test_form, form_id=test_form.id, label="Alias", name_alias="original-name"
    )

    # The original field value and the alias values should remain synchronized.
    assert test_field.name == "original-name"
    assert test_field.name_alias == "original-name"

    test_field.save()

    test_field.name_alias = "aliased-name"
    assert test_field.name == "aliased-name"
    assert test_field.name_alias == "aliased-name"

    test_field.name = "original-name-again"
    assert test_field.name == "original-name-again"
    assert test_field.name_alias == "original-name-again"

    # The original field and its alias should both revert to the database value
    # when refresh_from_db is called.
    test_field.refresh_from_db()
    assert test_field.name == "original-name"
    assert test_field.name_alias == "original-name"

    # Changing the alias, saving, and refreshing should result in both the
    # original field and its alias being updated.
    test_field.name_alias = "original-name-again"
    test_field.save()
    test_field.refresh_from_db()

    assert test_field.name == "original-name-again"
    assert test_field.name_alias == "original-name-again"

    # The __delete__ operation should noop (the Django descriptor default).
    del test_field.name_alias

    assert test_field.name == "original-name-again"
    assert test_field.name_alias == "original-name-again"

    # Creating an object using the concrete attributes should also work identically.
    test_field_concrete = AliasedField.objects.create(
        form_relation=test_form,
        form_relation_id=test_form.id,
        label="Concrete",
        name="concrete",
    )
    assert test_field_concrete.name == "concrete"
    assert test_field_concrete.name_alias == "concrete"
    assert test_field_concrete.form_id == test_form.id
    assert test_field_concrete.form_relation_id == test_form.id
