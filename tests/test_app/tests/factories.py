# -*- coding: utf-8 -*-

"""Model factories for use in testing."""

import random

import factory

from flexible_forms.fields import FIELD_TYPES


class FieldFactory(factory.django.DjangoModelFactory):
    """A factory for generating form Field records."""

    class Meta:
        model = "test_app.AppField"

    form = factory.SubFactory("test_app.tests.factories.FormFactory")
    field_type = factory.LazyAttribute(
        lambda _: random.choice([*FIELD_TYPES.keys()]),
    )
    required = False
    label = factory.Faker("sentence")


class FormFactory(factory.django.DjangoModelFactory):
    """A factory for generating Form records."""

    class Meta:
        model = "test_app.AppForm"

    label = factory.Faker("sentence")
