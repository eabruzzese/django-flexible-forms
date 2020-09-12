# -*- coding: utf-8 -*-
import uuid

from django.db import models

from flexible_forms.models import (
    BaseField,
    BaseFieldModifier,
    BaseForm,
    BaseRecord,
    BaseRecordAttribute,
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


class CustomForm(BaseForm, CustomBaseModel):
    """A customized and swapped-out version of the Form provided by
    flexible_forms."""


class CustomField(BaseField, CustomBaseModel):
    """A customized and swapped-out version of the Field provided by
    flexible_forms."""


class CustomRecord(BaseRecord, CustomBaseModel):
    """A customized and swapped-out version of the Record provided by
    flexible_forms."""


class CustomRecordAttribute(BaseRecordAttribute, CustomBaseModel):
    """A customized and swapped-out version of the RecordAttribute provided by
    flexible_forms."""


class CustomFieldModifier(BaseFieldModifier, CustomBaseModel):
    """A customized and swapped-out version of the RecordAttribute provided by
    flexible_forms."""
