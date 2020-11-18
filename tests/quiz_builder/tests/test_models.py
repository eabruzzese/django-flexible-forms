# -*- coding: utf-8 -*-

"""Tests for form-related models."""

import pytest
from django.db.utils import IntegrityError
from django.utils.datastructures import MultiValueDict
from quiz_builder.models import QuizSection

from flexible_forms.fields import (
    MultipleChoiceCheckboxField,
    PositiveIntegerField,
    SingleLineTextField,
)

from .factories import (
    QuizFactory,
    QuizQuestionFactory,
    QuizSectionFactory,
    QuizSectionItemFactory,
    QuizSubmissionFactory,
)


@pytest.mark.django_db
def test_quiz_save() -> None:
    quiz = QuizFactory.build(label="")

    # If no label is specified, the quiz name should be empty before and after
    # saving.
    assert quiz.label == ""
    assert quiz.name == ""
    quiz.save()
    assert quiz.label == ""
    assert quiz.name == ""

    # If a label is specified, the name should be computed by slugifying it.
    quiz.label = "Test Quiz"
    quiz.save()
    assert quiz.name == "test_quiz"

    # Updating a quiz label should not change its name.
    quiz.label = "New Test Quiz"
    quiz.save()
    assert quiz.name == "test_quiz"


def test_quiz___str__() -> None:
    quiz = QuizFactory.build(label=None)

    # No label configured.
    assert str(quiz) == "Untitled Quiz"

    # Label configured.
    quiz.label = "Test Quiz"
    assert str(quiz) == "Test Quiz"


@pytest.mark.django_db
def test_quiz_relations() -> None:
    quiz = QuizFactory()

    # A quiz should have a "questions" field and a "fields" field that behave
    # in exactly the same way. The "fields" field is used internally.
    quiz.questions.add(QuizQuestionFactory.build(), bulk=False)
    quiz.fields.add(QuizQuestionFactory.build(), bulk=False)
    assert quiz.questions.count() == 2
    assert set(quiz.questions.all()) == set(quiz.fields.all())

    # Similarly, a quiz should have a "sections" field and a "fieldsets" field.
    quiz.sections.add(QuizSectionFactory.build(), bulk=False)
    quiz.fieldsets.add(QuizSectionFactory.build(), bulk=False)
    assert quiz.sections.count() == 2
    assert set(quiz.sections.all()) == set(quiz.fieldsets.all())

    # A quiz should also have a "submissions" field and a "records" field.
    quiz.submissions.add(QuizSubmissionFactory.build(), bulk=False)
    quiz.records.add(QuizSubmissionFactory.build(), bulk=False)
    assert quiz.submissions.count() == 2
    assert set(quiz.submissions.all()) == set(quiz.records.all())


@pytest.mark.django_db
def test_quiz_initial_values() -> None:
    quiz = QuizFactory()
    question_1 = QuizQuestionFactory(
        quiz=quiz, field_type=SingleLineTextField.name, initial="Testing"
    )
    question_2 = QuizQuestionFactory(
        quiz=quiz, field_type=PositiveIntegerField.name, initial=123
    )
    question_3 = QuizQuestionFactory(
        quiz=quiz,
        field_type=MultipleChoiceCheckboxField.name,
        initial=["first", "second"],
    )

    # The initial values for a quiz should be represented as a MultiValueDict
    # with field names as keys and their initial properties as values.
    #
    # The initial values will be converted to lists if they aren't already, and
    # a reference to the quiz ("form") will be included as well.
    assert quiz.initial_values == MultiValueDict(
        {
            "form": [quiz],
            question_1.name: [question_1.initial],
            question_2.name: [question_2.initial],
            question_3.name: question_3.initial,
        }
    )


@pytest.mark.django_db(transaction=True)
def test_quiz_as_django_fieldsets() -> None:
    quiz = QuizFactory()

    question_1 = QuizQuestionFactory(
        quiz=quiz, field_type=SingleLineTextField.name, initial="Testing"
    )
    question_2 = QuizQuestionFactory(
        quiz=quiz, field_type=PositiveIntegerField.name, initial=123
    )
    question_3 = QuizQuestionFactory(
        quiz=quiz,
        field_type=MultipleChoiceCheckboxField.name,
        initial=["first", "second"],
    )

    # A quiz with no fieldsets (sections) should expect an empty list when
    # calling as_django_fieldsets().
    assert quiz.as_django_fieldsets() == []

    # A "default" section can be created with empty values for attributes.
    section = QuizSectionFactory(quiz=quiz, name="", description="", classes="")

    # The default section will have questions 1 and 2 on the same line, and
    # section 3 by itself on the next line.
    section.items.create(question=question_1, vertical_order=1, horizontal_order=1)
    section.items.create(question=question_2, vertical_order=1, horizontal_order=2)
    # Orders are relative weights, not indexes. They do not need to be in sequence.
    section.items.create(question=question_3, vertical_order=10, horizontal_order=10)

    assert quiz.as_django_fieldsets() == [
        (
            None,
            {
                "classes": (),
                "description": None,
                "fields": ((question_1.name, question_2.name), question_3.name),
            },
        )
    ]

    # The section can include details to make its representation richer.
    section.name = "First Section"
    section.description = "The first section of the quiz."
    section.classes = "section first default"
    section.save()

    assert quiz.as_django_fieldsets() == [
        (
            "First Section",
            {
                "classes": ("section", "first", "default"),
                "description": "The first section of the quiz.",
                "fields": ((question_1.name, question_2.name), question_3.name),
            },
        )
    ]

    # Section items can share a vertical order, but not a horizontal one.
    with pytest.raises(IntegrityError):
        section_item_2 = question_2.section_item
        section_item_2.horizontal_order = 1
        section_item_2.save()

    # Section items cannot be specified more than once in a fieldset.
    with pytest.raises(IntegrityError):
        section.items.create(question=question_3, vertical_order=10, horizontal_order=1)


@pytest.mark.django_db
def test_quiz_as_django_form_unbound() -> None:
    pytest.skip("TODO")


@pytest.mark.django_db
def test_quiz_as_django_form_bound() -> None:
    pytest.skip("TODO")


@pytest.mark.django_db
def test_quiz_question() -> None:
    pytest.skip("TODO")


@pytest.mark.django_db
def test_quiz_section() -> None:
    pytest.skip("TODO")


@pytest.mark.django_db
def test_quiz_section_item() -> None:
    item = QuizSectionItemFactory()

    # An item refers to its form as a "section" (different from the default of
    # "form"), but keeps the original related_name of "items".
    assert isinstance(item.section, QuizSection)
    assert item in item.section.items.all()
    assert set(item.section.items.all()) == set(item.fieldset.items.all())


@pytest.mark.django_db
def test_quiz_question_modifier() -> None:
    pytest.skip("TODO")


@pytest.mark.django_db
def test_quiz_question_modifier() -> None:
    pytest.skip("TODO")


@pytest.mark.django_db
def test_quiz_submission() -> None:
    pytest.skip("TODO")


@pytest.mark.django_db
def test_quiz_answer() -> None:
    pytest.skip("TODO")
