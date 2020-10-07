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

    class FlexibleMeta:
        fields_relation_name = "app_fields"
        fieldsets_relation_name = "app_fieldsets"
        records_relation_name = "app_records"


class AppField(app_forms.BaseField, CustomBaseModel):
    """A customized version of the Field provided by flexible_forms."""

    class FlexibleMeta:
        form_relation_name = "app_form"
        fieldset_item_relation_name = "app_fieldset_item"
        modifiers_relation_name = "app_modifiers"
        attributes_relation_name = "app_record_attributes"


class AppFieldset(app_forms.BaseFieldset, CustomBaseModel):
    """A customized version of the Fieldset provided by flexible_forms."""

    class FlexibleMeta:
        form_relation_name = "app_form"
        items_relation_name = "app_fieldset_items"


class AppFieldsetItem(app_forms.BaseFieldsetItem, CustomBaseModel):
    """A customized version of the FieldsetItem provided by flexible_forms."""

    class FlexibleMeta:
        field_relation_name = "app_field"
        fieldset_relation_name = "app_fieldset"


class AppFieldModifier(app_forms.BaseFieldModifier, CustomBaseModel):
    """A customized version of the FieldModifier provided by flexible_forms."""

    class FlexibleMeta:
        field_relation_name = "app_field"


class AppRecord(app_forms.BaseRecord, CustomBaseModel):
    """A customized version of the Record provided by flexible_forms."""

    class FlexibleMeta:
        _form_relation_name = "app_form"
        _attributes_relation_name = "app_record_attributes"


class AppRecordAttribute(app_forms.BaseRecordAttribute, CustomBaseModel):
    """A customized version of the RecordAttribute provided by
    flexible_forms."""

    class FlexibleMeta:
        field_relation_name = "app_field"
        record_relation_name = "app_record"
