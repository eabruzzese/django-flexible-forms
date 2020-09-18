# -*- coding: utf-8 -*-
"""Model definitions for the test app."""

import uuid

from django.db import models

from flexible_forms.models import (
    BaseField,
    BaseFieldModifier,
    BaseForm,
    BaseRecord,
    BaseRecordAttribute,
    FlexibleForms,
)


class CustomBaseModel(models.Model):
    """A custom base model to simulate a common swapping scenario.

    Often, users of the package will have a common base model that they want
    all of their models to inherit from. The flexible_forms package allows
    all of its models to be swapped out with custom implementations, so this
    base model is simulating that use case and exercising the swapping
    feature.

    The swapping configuration is handled in settings.py.
    """

    uuid = models.UUIDField(default=uuid.uuid4)

    class Meta:
        abstract = True


app_forms = FlexibleForms(model_prefix="App")


@app_forms
class AppForm(BaseForm, CustomBaseModel):
    """A customized version of the Form provided by flexible_forms."""


@app_forms
class AppField(BaseField, CustomBaseModel):
    """A customized version of the Field provided by flexible_forms."""

    class Meta(BaseField.Meta):
        unique_together = ("form", "name", "label")


@app_forms
class AppFieldModifier(BaseFieldModifier, CustomBaseModel):
    """A customized version of the FieldModifier provided by flexible_forms."""


@app_forms
class AppRecord(BaseRecord, CustomBaseModel):
    """A customized version of the Record provided by flexible_forms."""


@app_forms
class AppRecordAttribute(BaseRecordAttribute, CustomBaseModel):
    """A customized version of the RecordAttribute provided by
    flexible_forms."""


app_forms.make_flexible()
