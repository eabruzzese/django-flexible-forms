# -*- coding: utf-8 -*-
"""Model definitions for the test app."""

import uuid

from django.db import models

from flexible_forms.models import FlexibleForms


class CustomBaseModel(models.Model):
    """A custom base model to simulate a common swapping scenario.

    Often, users of the package will have a common base model that they want
    all of their models to inherit from. The flexible_forms package allows
    all of its models to be swapped out with custom implementations, so this
    base model is simulating that use case and exercising the swapping
    feature.

    The swapping configuration is handled in settings.py.
    """

    uuid = models.UUIDField(blank=True, default=uuid.uuid4)

    class Meta:
        abstract = True


app_forms = FlexibleForms(model_prefix="App")


class AppForm(app_forms.BaseForm, CustomBaseModel):
    """A customized version of the Form provided by flexible_forms."""


class AppField(app_forms.BaseField, CustomBaseModel):
    """A customized version of the Field provided by flexible_forms."""

    class FlexibleMeta:
        form_field_name = "app_form"
        form_field_related_name = "app_fields"


class AppFieldset(app_forms.BaseFieldset, CustomBaseModel):
    """A customized version of the Fieldset provided by flexible_forms."""

    class FlexibleMeta:
        form_field_name = "app_form"
        form_field_related_name = "app_fieldsets"


class AppFieldsetItem(app_forms.BaseFieldsetItem, CustomBaseModel):
    """A customized version of the FieldsetItem provided by flexible_forms."""

    class FlexibleMeta:
        field_field_name = "app_field"
        field_field_related_name = "app_fieldsets"
        fieldset_field_name = "app_fieldset"
        fieldset_field_related_name = "app_fieldset_items"


class AppFieldModifier(app_forms.BaseFieldModifier, CustomBaseModel):
    """A customized version of the FieldModifier provided by flexible_forms."""

    class FlexibleMeta:
        field_field_name = "app_field"
        field_field_related_name = "app_field_modifiers"


class AppRecord(app_forms.BaseRecord, CustomBaseModel):
    """A customized version of the Record provided by flexible_forms."""

    class FlexibleMeta:
        form_field_name = "app_form"
        form_field_related_name = "app_records"


class AppRecordAttribute(app_forms.BaseRecordAttribute, CustomBaseModel):
    """A customized version of the RecordAttribute provided by
    flexible_forms."""

    class FlexibleMeta:
        field_field_name = "app_field"
        field_field_related_name = "app_attributes"
        record_field_name = "app_record"
        record_field_related_name = "app_attributes"


app_forms.make_flexible()
