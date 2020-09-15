# -*- coding: utf-8 -*-
"""Model definitions for the test app."""

import uuid

from django.db import models

from flexible_forms.models import Field as BaseField
from flexible_forms.models import FieldModifier as BaseFieldModifier
from flexible_forms.models import Form as BaseForm
from flexible_forms.models import Record as BaseRecord
from flexible_forms.models import RecordAttribute as BaseRecordAttribute


class BaseModel(models.Model):
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


class Form(BaseForm, BaseModel):
    """A customized and swapped-out version of the Form provided by
    flexible_forms."""


class Field(BaseField, BaseModel):
    """A customized and swapped-out version of the Field provided by
    flexible_forms."""


class FieldModifier(BaseFieldModifier, BaseModel):
    """A customized and swapped-out version of the RecordAttribute provided by
    flexible_forms."""


class Record(BaseRecord, BaseModel):
    """A customized and swapped-out version of the Record provided by
    flexible_forms."""


class RecordAttribute(BaseRecordAttribute, BaseModel):
    """A customized and swapped-out version of the RecordAttribute provided by
    flexible_forms."""
