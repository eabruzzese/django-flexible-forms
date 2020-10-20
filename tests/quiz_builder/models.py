# -*- coding: utf-8 -*-
"""Model definitions for the test app."""

import uuid

from django.db import models

from flexible_forms.models import FlexibleForms


class CustomBaseModel(models.Model):
    """A custom base model to simulate a common customization scenario."""

    uuid = models.UUIDField(blank=True, default=uuid.uuid4)

    class Meta:
        abstract = True


quiz_forms = FlexibleForms(model_prefix="Quiz")


class Quiz(quiz_forms.BaseForm, CustomBaseModel):
    """A quiz to be defined by a teacher and completed by a student."""


class QuizQuestion(quiz_forms.BaseField, CustomBaseModel):
    """A single question on a quiz."""

    class FlexibleMeta:
        # Different field name and related_name.
        form_field_name = "quiz"
        form_field_related_name = "questions"


class QuizSection(quiz_forms.BaseFieldset, CustomBaseModel):
    """A section on a quiz containing questions."""

    class FlexibleMeta:
        # Different field name and related_name.
        form_field_name = "quiz"
        form_field_related_name = "sections"


class QuizSectionItem(quiz_forms.BaseFieldsetItem, CustomBaseModel):
    """A single item within a quiz section to define additional groupings."""

    class FlexibleMeta:
        # Different field name, original related_name.
        fieldset_field_name = "section"
        fieldset_field_related_name = "items"

        # Different field name and related_name.
        field_field_name = "question"
        field_field_related_name = "section_item"


class QuizQuestionModifier(quiz_forms.BaseFieldModifier, CustomBaseModel):
    """A dynamic question modifier for a quiz (e.g., show/hide a question based on the answer to another question)."""

    class FlexibleMeta:
        # Different field name, original related_name.
        field_field_name = "question"
        field_field_related_name = "modifiers"


class QuizSubmission(quiz_forms.BaseRecord, CustomBaseModel):
    """An instance of a quiz submitted for grading."""

    class FlexibleMeta:
        # Different field name and related_name.
        _form_field_name = "quiz"
        _form_field_related_name = "submissions"


class Answer(quiz_forms.BaseRecordAttribute, CustomBaseModel):
    """A single answer on a submitted quiz."""

    class FlexibleMeta:
        # Different field name and related_name.
        field_field_name = "question"
        field_field_related_name = "answers"

        # Different field name and related_name.
        record_field_name = "submission"
        record_field_related_name = "answers"


quiz_forms.make_flexible()
