# -*- coding: utf-8 -*-
import json

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.http import JsonResponse
from django.test import RequestFactory
from django.urls import reverse

from flexible_forms import fields, views
from flexible_forms.fields import (
    QuerysetAutocompleteSelectField,
    SingleLineTextField,
    URLAutocompleteSelectField,
)
from tests.quiz_builder.tests.factories import QuizFactory, QuizQuestionFactory

User = get_user_model()

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
    "pagination": {"more": False},
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
        field_type=URLAutocompleteSelectField.name,
        field_type_options={
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
        field_type=URLAutocompleteSelectField.name,
        field_type_options={
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
        field_type=URLAutocompleteSelectField.name,
        field_type_options={
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
        field_type=URLAutocompleteSelectField.name,
        field_type_options={
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
        field_type=URLAutocompleteSelectField.name,
        field_type_options={
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


@pytest.mark.django_db
def test_autocomplete_search(rf: RequestFactory, requests_mock) -> None:
    """Ensure that autocomplete fields filter their results with a search
    term."""
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
        # Pagination should be False since this is the only entry with the
        # search term.
        "pagination": {"more": False},
    }

    question_field = QuizQuestionFactory(
        field_type=URLAutocompleteSelectField.name,
        field_type_options={
            "url": BASE_URL,
            "search_fields": ["name"],
            "mapping": {
                "root": "data",
                "value": "_id",
                "text": "name",
                "extra": {"Airline": "airline.name"},
            },
        },
    )

    results = _get_autocomplete_results(
        rf, question_field, page=1, per_page=5, term="mladji"
    )

    assert results == expected_results


@pytest.mark.django_db
def test_autocomplete_search_specific_field(rf: RequestFactory, requests_mock) -> None:
    """Ensure that autocomplete fields filter their results with a search
    term."""
    requests_mock.get(BASE_URL, text=json.dumps(MOCK_RESPONSE))

    expected_results = {
        "results": [
            {
                "extra": {"Airline": "Delta"},
                "id": '{"extra":{"Airline":"Delta"},"text":"Phyllis Jessen","value":"5f1c59c3fa523c3aa793bd26"}',
                "text": "Phyllis Jessen",
                "value": "5f1c59c3fa523c3aa793bd26",
            },
            {
                "extra": {"Airline": "Delta"},
                "id": '{"extra":{"Airline":"Delta"},"text":"Tandy Aphra","value":"5f1c59c3fa523c3aa793bd2d"}',
                "text": "Tandy Aphra",
                "value": "5f1c59c3fa523c3aa793bd2d",
            },
        ],
        # Pagination should be False since these are the only entries with the
        # search term ("p") in the name.
        "pagination": {"more": False},
    }

    question_field = QuizQuestionFactory(
        field_type=URLAutocompleteSelectField.name,
        field_type_options={
            "url": BASE_URL,
            "mapping": {
                "root": "data",
                "value": "_id",
                "text": "name",
                "extra": {"Airline": "airline.name"},
            },
        },
    )

    results = _get_autocomplete_results(
        rf, question_field, page=1, per_page=5, term="p"
    )

    assert results == expected_results


@pytest.mark.django_db
def test_autocomplete_queryset(rf: RequestFactory, mocker) -> None:
    """Ensure that autocomplete fields can be backed by querysets."""
    # Create a few test users.
    User.objects.bulk_create(User(username=f"User {n}") for n in range(1, 4))

    expected_results = {
        "pagination": {"more": False},
        "results": [
            {
                "extra": {},
                "id": '{"extra":{},"text":"User 1","value":1}',
                "text": "User 1",
                "value": 1,
            },
            {
                "extra": {},
                "id": '{"extra":{},"text":"User 2","value":2}',
                "text": "User 2",
                "value": 2,
            },
            {
                "extra": {},
                "id": '{"extra":{},"text":"User 3","value":3}',
                "text": "User 3",
                "value": 3,
            },
        ],
    }

    mocker.patch.object(
        fields,
        "resolve",
        return_value=(lambda *a, **kw: JsonResponse(MOCK_RESPONSE), (), {}),
    )

    question_field = QuizQuestionFactory(
        field_type=QuerysetAutocompleteSelectField.name,
        field_type_options={
            "model": "auth.User",
            "mapping": {
                "value": "pk",
                "text": "username",
            },
        },
    )

    results = _get_autocomplete_results(rf, question_field, page=1, per_page=5)

    assert results == expected_results


@pytest.mark.django_db
def test_autocomplete_queryset_filter(rf: RequestFactory, mocker) -> None:
    """Ensure that queryset autocomplete fields can be configured with
    filters."""
    # Create a few test users.
    User.objects.bulk_create(User(username=f"User {n}") for n in range(1, 4))

    expected_results = {
        "pagination": {"more": False},
        "results": [
            # The filter should exclude this record.
            # {
            #     "extra": {},
            #     "id": '{"extra":{},"text":"User 1","value":1}',
            #     "text": "User 1",
            #     "value": 1,
            # },
            {
                "extra": {},
                "id": '{"extra":{},"text":"User 2","value":2}',
                "text": "User 2",
                "value": 2,
            },
            {
                "extra": {},
                "id": '{"extra":{},"text":"User 3","value":3}',
                "text": "User 3",
                "value": 3,
            },
        ],
    }

    mocker.patch.object(
        fields,
        "resolve",
        return_value=(lambda *a, **kw: JsonResponse(MOCK_RESPONSE), (), {}),
    )

    question_field = QuizQuestionFactory(
        field_type=QuerysetAutocompleteSelectField.name,
        field_type_options={
            "model": "auth.User",
            "filter": {"pk__gt": 1},
            "mapping": {
                "value": "pk",
                "text": "username",
            },
        },
    )

    results = _get_autocomplete_results(rf, question_field, page=1, per_page=5)

    assert results == expected_results


@pytest.mark.django_db
def test_autocomplete_queryset_exclude(rf: RequestFactory, mocker) -> None:
    """Ensure that queryset autocomplete fields can be configured with
    excludes."""
    # Create a few test users.
    User.objects.bulk_create(User(username=f"User {n}") for n in range(1, 4))

    expected_results = {
        "pagination": {"more": False},
        "results": [
            # The filter should exclude this record.
            # {
            #     "extra": {},
            #     "id": '{"extra":{},"text":"User 1","value":1}',
            #     "text": "User 1",
            #     "value": 1,
            # },
            {
                "extra": {},
                "id": '{"extra":{},"text":"User 2","value":2}',
                "text": "User 2",
                "value": 2,
            },
            {
                "extra": {},
                "id": '{"extra":{},"text":"User 3","value":3}',
                "text": "User 3",
                "value": 3,
            },
        ],
    }

    mocker.patch.object(
        fields,
        "resolve",
        return_value=(lambda *a, **kw: JsonResponse(MOCK_RESPONSE), (), {}),
    )

    question_field = QuizQuestionFactory(
        field_type=QuerysetAutocompleteSelectField.name,
        field_type_options={
            "model": "auth.User",
            "exclude": {"pk__lt": 2},
            "mapping": {
                "value": "pk",
                "text": "username",
            },
        },
    )

    results = _get_autocomplete_results(rf, question_field, page=1, per_page=5)

    assert results == expected_results


@pytest.mark.django_db
def test_autocomplete_queryset_pagination(rf: RequestFactory, mocker) -> None:
    """Ensure that queryset autocomplete fields are paginated correctly."""
    # Create a few test users.
    User.objects.bulk_create(User(username=f"User {n}") for n in range(1, 4))

    expected_results = {
        "results": [
            {
                "extra": {},
                "id": '{"extra":{},"text":"User 1","value":1}',
                "text": "User 1",
                "value": 1,
            },
            {
                "extra": {},
                "id": '{"extra":{},"text":"User 2","value":2}',
                "text": "User 2",
                "value": 2,
            },
            # The paginator should exclude this record.
            # {
            #     "extra": {},
            #     "id": '{"extra":{},"text":"User 3","value":3}',
            #     "text": "User 3",
            #     "value": 3,
            # },
        ],
        "pagination": {"more": True},
    }

    mocker.patch.object(
        fields,
        "resolve",
        return_value=(lambda *a, **kw: JsonResponse(MOCK_RESPONSE), (), {}),
    )

    question_field = QuizQuestionFactory(
        field_type=QuerysetAutocompleteSelectField.name,
        field_type_options={
            "model": "auth.User",
            "search_fields": ["username"],
            "mapping": {
                "value": "pk",
                "text": "username",
            },
        },
    )

    results = _get_autocomplete_results(rf, question_field, page=1, per_page=2)

    assert results == expected_results


@pytest.mark.django_db
def test_autocomplete_queryset_search(rf: RequestFactory, mocker) -> None:
    """Ensure that queryset autocomplete fields are searchable."""
    # Create a few test users.
    User.objects.bulk_create(User(username=f"User {n}") for n in range(1, 4))

    expected_results = {
        "pagination": {"more": False},
        "results": [
            # {
            #     "extra": {},
            #     "id": '{"extra":{},"text":"User 1","value":1}',
            #     "text": "User 1",
            #     "value": 1,
            # },
            # The search term should filter the queryset so that only this
            # record is returned.
            {
                "extra": {},
                "id": '{"extra":{},"text":"User 2","value":2}',
                "text": "User 2",
                "value": 2,
            },
            # {
            #     "extra": {},
            #     "id": '{"extra":{},"text":"User 3","value":3}',
            #     "text": "User 3",
            #     "value": 3,
            # },
        ],
    }

    mocker.patch.object(
        fields,
        "resolve",
        return_value=(lambda *a, **kw: JsonResponse(MOCK_RESPONSE), (), {}),
    )

    question_field = QuizQuestionFactory(
        field_type=QuerysetAutocompleteSelectField.name,
        field_type_options={
            "model": "auth.User",
            "search_fields": ["username"],
            "mapping": {
                "value": "pk",
                "text": "username",
            },
        },
    )

    results = _get_autocomplete_results(
        rf, question_field, page=1, per_page=5, term="user 2"
    )

    assert results == expected_results


@pytest.mark.django_db
def test_autocomplete_queryset_search_fallback(rf: RequestFactory, mocker) -> None:
    """Ensure that queryset autocomplete fields fall back to searching fields
    referenced in the mapping JMESPath expressions."""
    # Create a few test users.
    User.objects.bulk_create(
        User(username=f"User {n}", email=f"user{n}@example.com") for n in range(1, 4)
    )

    expected_results = {
        "pagination": {"more": False},
        "results": [
            # {
            #     "extra": {},
            #     "id": '{"extra":{},"text":"User 1","value":1}',
            #     "text": "User 1, 1, user1@example.com",
            #     "value": 1,
            # },
            # The search term should filter the queryset so that only this
            # record is returned.
            {
                "extra": {},
                "id": '{"extra":{},"text":"User 2, 2, user2@example.com","value":2}',
                "text": "User 2, 2, user2@example.com",
                "value": 2,
            },
            # {
            #     "extra": {},
            #     "id": '{"extra":{},"text":"User 3","value":3}',
            #     "text": "User 3, 3, user3@example.com",
            #     "value": 3,
            # },
        ],
    }

    mocker.patch.object(
        fields,
        "resolve",
        return_value=(lambda *a, **kw: JsonResponse(MOCK_RESPONSE), (), {}),
    )

    question_field = QuizQuestionFactory(
        field_type=QuerysetAutocompleteSelectField.name,
        field_type_options={
            "model": "auth.User",
            "mapping": {
                "value": "pk",
                # Since no search_fields option was explicitly defined, the
                # search mechanism will fall back to parsing the text mapping
                # expression and automatically search each field referenced
                # within it (if the field is a concrete model field).
                "text": "join(', ', [username, to_string(pk), email])",
            },
        },
    )

    results = _get_autocomplete_results(
        rf, question_field, page=1, per_page=5, term="user 2 2 user2@example.com"
    )

    assert results == expected_results


@pytest.mark.django_db
def test_autocomplete_queryset_search_misconfigured(rf: RequestFactory, mocker) -> None:
    """Ensure that queryset autocomplete fields raise an error if search fields
    are misconfigured."""
    question_field = QuizQuestionFactory(
        field_type=QuerysetAutocompleteSelectField.name,
        field_type_options={
            "model": "auth.User",
            "search_fields": ["not_a_field"],
            "mapping": {
                "value": "pk",
                "text": "username",
            },
        },
    )

    # An error should be raised because not_a_field is not a searchable model field.
    with pytest.raises(ImproperlyConfigured):
        _get_autocomplete_results(rf, question_field, page=1, per_page=5, term="user 2")


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
