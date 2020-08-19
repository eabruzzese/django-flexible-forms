# -*- coding: utf-8 -*-

"""Model factories for use in testing."""

import random

import factory

from flexible_forms.fields import FIELDS_BY_KEY


class FieldFactory(factory.django.DjangoModelFactory):
    """A factory for generating form Field records."""

    class Meta:
        model = 'test_app.CustomField'

    form = factory.SubFactory('test_app.tests.factories.FormFactory')
    field_type = factory.LazyAttribute(
        lambda _: random.choice([*FIELDS_BY_KEY.keys()]),
    )
    required = False
    label = factory.Faker('sentence')


class FormFactory(factory.django.DjangoModelFactory):
    """A factory for generating Form records."""

    class Meta:
        model = 'test_app.CustomForm'

    label = factory.Faker('sentence')
