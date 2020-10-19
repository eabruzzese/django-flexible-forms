# -*- coding: utf-8 -*-
from typing import Any

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.http import HttpRequest
from django.http.response import HttpResponseRedirect
from django.template.response import TemplateResponse
from test_app.admin import AppFormsAdmin, AppRecordsAdmin
from test_app.models import AppForm, AppRecord

from flexible_forms.admin import (
    FieldModifiersInline,
    FieldsetItemsInline,
    FieldsetsInline,
    FieldsInline,
)

from .factories import FieldFactory, FormFactory


@pytest.mark.django_db
def test_form_admin(django_assert_num_queries: Any, mocker: Any) -> None:
    """Ensure that the ModelAdmin for forms renders as expected."""

    forms_admin = AppFormsAdmin(model=AppForm, admin_site=AdminSite())
    super_user = get_user_model().objects.create_superuser(
        username="admin", email="admin@example.com", password="admin"
    )
    request = HttpRequest()
    request.user = super_user

    # Generate a form.
    test_form = FormFactory(label="Test Form")
    test_field = FieldFactory(form=test_form)
    test_fieldset = test_form.fieldsets.create(name="Test Fieldset")
    test_fieldset_item = test_fieldset.items.create(
        field=test_field, vertical_order=0, horizontal_order=0
    )

    with django_assert_num_queries(1):
        queryset = forms_admin.get_queryset(request=request)
        form = queryset.first()

        # There should be one form (the one we created).
        assert form == test_form

        assert forms_admin._fields_count(form) == 1
        assert ">0<" in forms_admin._records_count(form)
        assert f"?_form_id={form.pk}" in forms_admin._add_record(form)

    # The forms admin should have an inline for fields.
    fields_inline = next(
        (i for i in forms_admin.inlines if issubclass(i, FieldsInline)), None
    )
    assert fields_inline is not None

    fields_inline = fields_inline(forms_admin.model, forms_admin.admin_site)

    # The inline instance should use the configured attribute name instead of
    # the alias as its fk_name, and exclude aliased fields from its form.
    assert fields_inline.fk_name == "app_form"
    assert fields_inline.exclude == ("form",)

    # The fields inline should have an inline for field modifiers. The
    # fields_inline needs to be instantiated before we can access its `inlines`
    # property.
    field_modifiers_inline = next(
        (i for i in fields_inline.inlines if issubclass(i, FieldModifiersInline)),
        None,
    )
    assert field_modifiers_inline is not None

    field_modifiers_inline = field_modifiers_inline(
        forms_admin.model, forms_admin.admin_site
    )

    # The inline should use the configured attribute name instead of the alias as its fk_name.
    assert field_modifiers_inline.fk_name == "app_field"
    assert field_modifiers_inline.exclude == ("field",)

    # The forms admin should also have an inline for fieldsets.
    fieldsets_inline = next(
        (i for i in forms_admin.inlines if issubclass(i, FieldsetsInline)), None
    )
    assert fieldsets_inline is not None

    fieldsets_inline = fieldsets_inline(forms_admin.model, forms_admin.admin_site)

    # The inline should use the configured attribute name instead of the alias as its fk_name.
    assert fieldsets_inline.fk_name == "app_form"
    assert fieldsets_inline.exclude == ("form",)

    # The formsets inline should also have an inline for fieldset items.
    fieldset_items_inline = next(
        (i for i in fieldsets_inline.inlines if issubclass(i, FieldsetItemsInline)),
        None,
    )
    assert fieldset_items_inline is not None

    fieldset_items_inline = fieldset_items_inline(
        forms_admin.model, forms_admin.admin_site
    )

    # The inline should use the configured attribute name instead of the alias as its fk_name.
    assert fieldset_items_inline.fk_name == "app_fieldset"
    assert fieldset_items_inline.exclude == ("fieldset", "field")

    # Fieldset items should have their "field" choices restricted to fields in the current form.
    #
    # In order to restrict the queryset, the formfield_for_foreignkey method
    # needs access to the request's resolver_match property so that it can get
    # the object_id out of the matched path for the application route.
    mock_request = mocker.Mock()
    mock_request.resolver_match.kwargs = {"object_id": test_form.pk}
    formfield_for_field_fk = fieldset_items_inline.formfield_for_foreignkey(
        db_field=test_fieldset_item._meta.get_field("field"), request=mock_request
    )
    assert set(formfield_for_field_fk.queryset.all()) == set(test_form.fields.all())

    # The fieldset foreign key should remain untouched.
    fieldset_fk = test_fieldset_item._meta.get_field("fieldset")
    formfield_for_fieldset_fk = fieldset_items_inline.formfield_for_foreignkey(
        db_field=fieldset_fk, request=mock_request
    )
    assert str(formfield_for_fieldset_fk.queryset.query) == str(
        fieldset_fk.formfield().queryset.query
    )


@pytest.mark.django_db
def test_record_admin(django_assert_num_queries: Any) -> None:
    """Ensure that the ModelAdmin for records renders as expected."""

    records_admin = AppRecordsAdmin(model=AppRecord, admin_site=AdminSite())
    super_user = get_user_model().objects.create_superuser(
        username="admin", email="admin@example.com", password="admin"
    )
    request = HttpRequest()
    request.user = super_user

    # Generate a form so we can create records.
    test_form = FormFactory(label="Test Form")
    test_field = FieldFactory(form=test_form, required=False)
    test_fieldset = test_form.fieldsets.create(name="Test Fieldset")
    test_fieldset.items.create(field=test_field, vertical_order=0, horizontal_order=0)

    # The admin list view should only run a minimal number of queries to fetch
    # its listing.
    with django_assert_num_queries(1):
        records_admin.get_queryset(request=request).first()

    # Call the add_view() view method with no form ID to present the user with
    # a blank form with essentially only the form select input. No new records
    # should be created.
    add_request = HttpRequest()
    add_request.user = super_user
    add_request._dont_enforce_csrf_checks = True
    add_request.META["SCRIPT_NAME"] = None
    add_response = records_admin.add_view(add_request)
    assert not AppRecord.objects.exists()
    assert isinstance(add_response, TemplateResponse)

    # Calling get_form() with no instance (i.e., adding a new record from the
    # admin page) should return a form with only the base fields since the
    # record doesn't know what form it should be using yet.
    record_form = records_admin.get_form(request=request, obj=None)
    assert set(record_form().fields.keys()) == set(
        f.name
        for f in AppRecord._meta.get_fields()
        if f.concrete and f.name not in ("id",)
    )

    # Call the add_view() view method with our form's ID in the querystring to
    # create a new record. The response should redirect us to the change view.
    add_request = HttpRequest()
    add_request.user = super_user
    add_request.GET["_form_id"] = test_form.pk
    add_response = records_admin.add_view(add_request)
    added_record = AppRecord.objects.last()
    assert isinstance(add_response, HttpResponseRedirect)
    assert (
        f"{added_record.__class__.__name__.lower()}/{added_record.id}/change"
        in add_response.url
    )
    assert f">{test_form.label}<" in records_admin._form_label(added_record)

    # The change form returned by the admin should have the same field
    # structure as the one generated by the record's form.as_django_form().
    record_form = records_admin.get_form(request=request, obj=added_record)
    admin_form_fields = record_form().fields
    record_form_fields = added_record._form.as_django_form(instance=added_record).fields
    assert set(admin_form_fields.keys()) == set(record_form_fields.keys())

    # If the form has defined fieldsets, they should be rendered instead of the defaults.
    fieldsets = records_admin.get_fieldsets(request=request, obj=added_record)
    assert len(fieldsets) == 1
    assert fieldsets[0][0] == test_fieldset.name
