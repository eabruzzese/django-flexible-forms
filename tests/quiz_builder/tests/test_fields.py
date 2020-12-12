# -*- coding: utf-8 -*-
import hashlib
from datetime import timedelta
from typing import cast

import pytest
from django import forms
from django.core.files import File
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.extra.django import from_form
from quiz_builder.models import QuizSubmission

from flexible_forms.fields import FIELD_TYPES, FieldType

from .factories import QuizFactory, QuizQuestionFactory


def test_duplicate_field_registration() -> None:
    """Ensure that a user cannot overwrite a field type unless is forces
    replacement."""

    original_field = FIELD_TYPES["SingleLineTextField"]

    with pytest.raises(ValueError):

        class SingleLineTextField(FieldType):
            pass

    # Specifying force_replacement in the Meta options allows a field type to
    # overwrite an existing one.
    class SingleLineTextField(FieldType):
        class Meta:
            force_replacement = True

    FIELD_TYPES["SingleLineTextField"] = original_field


def test_abstract_field_type() -> None:
    """Ensure that abstract field types do not appear in the FIELD_TYPES
    mapping."""

    class CustomFieldType(FieldType):
        class Meta:
            abstract = True

    class ChildFieldType(CustomFieldType):
        pass

    assert CustomFieldType.name not in FIELD_TYPES
    assert ChildFieldType.name in FIELD_TYPES

    del FIELD_TYPES[ChildFieldType.name]


@pytest.mark.django_db
@pytest.mark.parametrize("field_type", FIELD_TYPES.keys())
@pytest.mark.timeout(360)
@settings(
    deadline=None,
    suppress_health_check=(HealthCheck.too_slow, HealthCheck.data_too_large),
)
@given(data=st.data())
def test_field_types(
    patch_field_strategies,
    duration_strategy: st.SearchStrategy[timedelta],
    rollback,
    field_type: FieldType,
    data: st.DataObject,
) -> None:
    """Ensure that each field type behaves appropriately."""
    with rollback():
        quiz = QuizFactory()
        question = QuizQuestionFactory(
            quiz=quiz,
            name=f"{field_type}_question".lower(),
            field_type=field_type,
            required=True,
        )

        with patch_field_strategies({forms.DurationField: duration_strategy}):
            django_form = cast(
                forms.ModelForm, data.draw(from_form(type(quiz.as_django_form())))
            )

        django_form.files = {
            k: v for k, v in django_form.data.items() if isinstance(v, File)
        }

        # The form should be valid.
        assert django_form.is_valid(), f"The form was not valid: {django_form.errors}"

        # Saving the form should result in a QuizSubmission instance.
        quiz_submission = django_form.save()
        assert isinstance(quiz_submission, QuizSubmission)
        assert (
            str(quiz_submission) == f"{quiz_submission.quiz.label} {quiz_submission.pk}"
        )
        assert (
            str(type(quiz_submission)(form=quiz)) == f"New {quiz_submission.quiz.label}"
        )
        assert str(type(quiz_submission)()) == f"New Quiz Submission"

        # The QuizSubmission should have one answer.
        assert quiz_submission.answers.count() == 1
        answer = quiz_submission.answers.first()
        assert str(answer) == f"Quiz Answer {answer.pk}"

        # The field value on the model should be identical to the one in the form's cleaned_data dict.
        record_value = getattr(quiz_submission, question.name)
        form_value = django_form.cleaned_data[question.name]

        # Files can't be reliably compared directly, so we compare their SHA1
        # digests instead of their direct values.
        if isinstance(record_value, File):
            record_value = hashlib.sha1(record_value.read()).hexdigest()
            form_value = hashlib.sha1(form_value.read()).hexdigest()

        assert (
            record_value == form_value
        ), f"Expected the record {question.name} ({field_type}) to have value {repr(form_value)} but got {repr(record_value)}"
