# -*- coding: utf-8 -*-
import json

import pytest
from django.http import JsonResponse
from django.test import RequestFactory
from django.urls import reverse

from flexible_forms import fields, views
from flexible_forms.fields import AutocompleteSelectField, SingleLineTextField
from tests.quiz_builder.tests.factories import QuizFactory, QuizQuestionFactory

BASE_URL = "https://api.instantwebtools.net/v1/passenger"
PAGINATED_URL = BASE_URL + "?page={{page}}&size={{per_page}}"
MOCK_RESPONSE = {
    "totalPassengers": 1897,
    "totalPages": 380,
    "data": [
        {
            "_id": "5f1c59c3fa523c3aa793bcfa",
            "name": " MIRKO TOMIC Mladji",
            "airline": {
                "name": "Delta",
            },
        },
        {
            "_id": "5f1c59c3fa523c3aa793bd26",
            "name": "Phyllis Jessen",
            "airline": {
                "name": "Delta",
            },
        },
        {
            "_id": "5f1c59c3fa523c3aa793bd30",
            "name": "Darcie Coleville",
            "airline": {
                "name": "Delta",
            },
        },
        {
            "_id": "5f1c59c3fa523c3aa793bd2d",
            "name": "Tandy Aphra",
            "airline": {
                "name": "Delta",
            },
        },
        # Results without an ID will use the name as the ID by default.
        {
            "name": "Same as ID",
        },
    ],
}
EXPECTED_RESULTS_EMPTY = {"results": [], "pagination": {"more": False}}
EXPECTED_RESULTS = {
    "results": [
        {
            "extra": {"Airline": "Delta"},
            "id": '{"extra":{"Airline":"Delta"},"text":" MIRKO TOMIC Mladji","value":"5f1c59c3fa523c3aa793bcfa"}',
            "text": " MIRKO TOMIC Mladji",
            "value": "5f1c59c3fa523c3aa793bcfa",
        },
        {
            "extra": {"Airline": "Delta"},
            "id": '{"extra":{"Airline":"Delta"},"text":"Phyllis Jessen","value":"5f1c59c3fa523c3aa793bd26"}',
            "text": "Phyllis Jessen",
            "value": "5f1c59c3fa523c3aa793bd26",
        },
        {
            "extra": {"Airline": "Delta"},
            "id": '{"extra":{"Airline":"Delta"},"text":"Darcie Coleville","value":"5f1c59c3fa523c3aa793bd30"}',
            "text": "Darcie Coleville",
            "value": "5f1c59c3fa523c3aa793bd30",
        },
        {
            "extra": {"Airline": "Delta"},
            "id": '{"extra":{"Airline":"Delta"},"text":"Tandy Aphra","value":"5f1c59c3fa523c3aa793bd2d"}',
            "text": "Tandy Aphra",
            "value": "5f1c59c3fa523c3aa793bd2d",
        },
        {
            "extra": {"Airline": None},
            "id": '{"extra":{"Airline":null},"text":"Same as ID","value":"Same as ID"}',
            "text": "Same as ID",
            "value": "Same as ID",
        },
    ],
    "pagination": {"more": True},
}


@pytest.mark.django_db
def test_autocomplete_no_record(rf: RequestFactory, requests_mock) -> None:
    """Ensure that the autocomplete view defers to the field implementation.

    This is simulating the scenario where an autocomplete field on an
    unbound form (i.e., no record instance has been created) makes a
    request to the autocomplete view.
    """
    requests_mock.get(BASE_URL, text=json.dumps(MOCK_RESPONSE))

    question_field = QuizQuestionFactory(
        field_type=AutocompleteSelectField.name,
        form_widget_options={
            "url": PAGINATED_URL,
            "mapping": {
                "root": "data",
                "value": "_id",
                "text": "name",
                "extra": {"Airline": "airline.name"},
            },
        },
    )

    results = _get_autocomplete_results(rf, question_field, page=1, per_page=5)

    assert results == EXPECTED_RESULTS


@pytest.mark.django_db
def test_autocomplete_with_record(rf: RequestFactory, requests_mock) -> None:
    """Ensure that an autocomplete URL can use Django Templating.

    The URL template should have access to pagination tokens (page,
    per_page) and the record, if available.
    """
    dynamic_url = PAGINATED_URL + (
        "&record_pk={{quiz_submission.pk}}&field_value={{quiz_submission.test_field}}"
    )

    mock_request = requests_mock.get(BASE_URL, text=json.dumps(MOCK_RESPONSE))

    # Generate a Quiz with an autocomplete field and a test field.
    quiz = QuizFactory()
    test_question = QuizQuestionFactory(
        quiz=quiz,
        name="test_field",
        field_type=SingleLineTextField.name,
    )
    autocomplete_question = QuizQuestionFactory(
        quiz=quiz,
        field_type=AutocompleteSelectField.name,
        form_widget_options={
            "url": dynamic_url,
            "mapping": {
                "root": "data",
                "value": "_id",
                "text": "name",
                "extra": {"Airline": "airline.name"},
            },
        },
    )

    # Submit the quiz to generate a submission to work with.
    test_question_value = "testing"
    quiz_form = quiz.as_django_form(
        {autocomplete_question.name: "", test_question.name: test_question_value}
    )
    assert quiz_form.is_valid(), quiz_form.errors
    submission = quiz_form.save()

    results = _get_autocomplete_results(
        rf, autocomplete_question, page=1, per_page=5, record_pk=submission.pk
    )

    # Ensure that the request URL and the response were expected.
    assert mock_request.request_history[0].query == (
        f"page=1"
        f"&size=5"
        f"&record_pk={submission.pk}"
        f"&field_value={test_question_value}"
    )
    assert results == EXPECTED_RESULTS


@pytest.mark.django_db
def test_autocomplete_no_url(rf: RequestFactory) -> None:
    """Ensure that an autocomplete field can be configured with no URL.

    Simulates a scenario where autocomplete is powered by something
    other than an HTTP endpoint.
    """
    question_field = QuizQuestionFactory(
        field_type=AutocompleteSelectField.name,
        form_widget_options={
            "url": "",
            "mapping": {
                "root": "data",
                "value": "_id",
                "text": "name",
                "extra": {"Airline": "airline.name"},
            },
        },
    )

    results = _get_autocomplete_results(rf, question_field)

    assert results == EXPECTED_RESULTS_EMPTY


@pytest.mark.django_db
def test_autocomplete_internal_url(rf: RequestFactory, mocker) -> None:
    """Ensure that autocomplete fields route app-internal paths directly to
    view functions."""
    mocker.patch.object(
        fields,
        "resolve",
        return_value=(lambda *a, **kw: JsonResponse(MOCK_RESPONSE), (), {}),
    )

    question_field = QuizQuestionFactory(
        field_type=AutocompleteSelectField.name,
        form_widget_options={
            "url": "/dummy/endpoint?page={{page}}&per_page={{per_page}}",
            "mapping": {
                "root": "data",
                "value": "_id",
                "text": "name",
                "extra": {"Airline": "airline.name"},
            },
        },
    )

    results = _get_autocomplete_results(rf, question_field, page=1, per_page=5)

    assert results == EXPECTED_RESULTS


@pytest.mark.django_db
def test_autocomplete_manual_pagination(rf: RequestFactory, requests_mock) -> None:
    """Ensure that autocomplete URLs without pagination tokens are manually
    paginated.

    If no page or per_page tokens are referenced in the URL, the default
    autocomplete implementation will assume that the response should be
    manually paginated.
    """
    requests_mock.get(BASE_URL, text=json.dumps(MOCK_RESPONSE))

    expected_results = {
        "results": [
            {
                "extra": {"Airline": "Delta"},
                "id": '{"extra":{"Airline":"Delta"},"text":" MIRKO TOMIC Mladji","value":"5f1c59c3fa523c3aa793bcfa"}',
                "text": " MIRKO TOMIC Mladji",
                "value": "5f1c59c3fa523c3aa793bcfa",
            },
        ],
        "pagination": {"more": True},
    }

    question_field = QuizQuestionFactory(
        field_type=AutocompleteSelectField.name,
        form_widget_options={
            "url": BASE_URL,
            "mapping": {
                "root": "data",
                "value": "_id",
                "text": "name",
                "extra": {"Airline": "airline.name"},
            },
        },
    )

    results = _get_autocomplete_results(rf, question_field, page=1, per_page=1)

    assert results == expected_results


def _get_autocomplete_results(rf, field, **query_params):
    route_params = {
        "app_label": field._meta.app_label,
        "model_name": field._meta.model_name,
        "field_pk": field.pk,
    }
    autocomplete_url = reverse("flexible_forms:autocomplete", kwargs=route_params)

    request = rf.get(autocomplete_url, query_params)
    response = views.autocomplete(request=request, **route_params)

    return json.loads(response.getvalue())
