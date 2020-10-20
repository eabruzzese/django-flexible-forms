# -*- coding: utf-8 -*-

"""Model factories for use in testing."""

import random

import factory

from flexible_forms.fields import FIELD_TYPES


class QuizFactory(factory.django.DjangoModelFactory):
    """A factory for generating Quiz records."""

    class Meta:
        model = "quiz_builder.Quiz"

    label = factory.Faker("sentence")


class QuizQuestionFactory(factory.django.DjangoModelFactory):
    """A factory for generating quiz question records."""

    class Meta:
        model = "quiz_builder.QuizQuestion"

    quiz = factory.SubFactory(QuizFactory)
    field_type = factory.LazyAttribute(
        lambda _: random.choice([*FIELD_TYPES.keys()]),
    )
    label_suffix = "?"
    required = False
    label = factory.Faker("sentence")
    _order = factory.Sequence(lambda n: n)


class QuizSectionFactory(factory.django.DjangoModelFactory):
    """A factory for generating quiz section records."""

    class Meta:
        model = "quiz_builder.QuizSection"

    quiz = factory.SubFactory(QuizFactory)


class QuizSectionItemFactory(factory.django.DjangoModelFactory):
    """A factory for generating quiz section items."""

    class Meta:
        model = "quiz_builder.QuizSectionItem"

    section = factory.SubFactory(QuizSectionFactory)
    question = factory.SubFactory(QuizQuestionFactory)
    vertical_order = factory.Sequence(lambda n: n)
    horizontal_order = factory.Sequence(lambda n: n)


class QuizSubmissionFactory(factory.django.DjangoModelFactory):
    """A factory for generating quiz submissions."""

    class Meta:
        model = "quiz_builder.QuizSubmission"

    quiz = factory.SubFactory(QuizFactory)
