# -*- coding: utf-8 -*-
import json

import pytest
from django.test import RequestFactory
from django.urls import reverse

from flexible_forms import views
from flexible_forms.fields import AutocompleteSelectField
from tests.quiz_builder.tests.factories import QuizQuestionFactory


@pytest.mark.django_db
def test_autocomplete(rf: RequestFactory, requests_mock) -> None:
    """Ensure that the autocomplete view appropriately defers to an underlying
    field."""

    base_url = "https://api.instantwebtools.net/v1/passenger"
    url = base_url + "?page={page}&size={per_page}"

    mock_response = {
        "totalPassengers": 1897,
        "totalPages": 380,
        "data": [
            {
                "_id": "5f1c59c3fa523c3aa793bcfa",
                "name": " MIRKO TOMIC Mladji",
            },
            {
                "_id": "5f1c59c3fa523c3aa793bd26",
                "name": "Phyllis Jessen",
            },
            {
                "_id": "5f1c59c3fa523c3aa793bd30",
                "name": "Darcie Coleville",
            },
            {
                "_id": "5f1c59c3fa523c3aa793bd2d",
                "name": "Tandy Aphra",
            },
            # Malformed results should be skipped.
            {
                "malformed": "result",
            },
            # Results without an ID will use the name as the ID by default.
            {
                "name": "Same as ID",
            },
            {
                "_id": "5f1c59c4fa523c3aa793bd32",
                "name": "Kristine Ian",
            },
        ],
    }

    requests_mock.get(base_url, text=json.dumps(mock_response))

    expected_results = {
        "results": [
            {
                "id": '{"extra":{},"id":"5f1c59c3fa523c3aa793bcfa","text":" MIRKO TOMIC Mladji"}',
                "text": " MIRKO TOMIC Mladji",
            },
            {
                "id": '{"extra":{},"id":"5f1c59c3fa523c3aa793bd26","text":"Phyllis Jessen"}',
                "text": "Phyllis Jessen",
            },
            {
                "id": '{"extra":{},"id":"5f1c59c3fa523c3aa793bd30","text":"Darcie Coleville"}',
                "text": "Darcie Coleville",
            },
            {
                "id": '{"extra":{},"id":"5f1c59c3fa523c3aa793bd2d","text":"Tandy Aphra"}',
                "text": "Tandy Aphra",
            },
            {
                "id": '{"extra":{},"id":"Same as ID","text":"Same as ID"}',
                "text": "Same as ID",
            },
            {
                "id": '{"extra":{},"id":"5f1c59c4fa523c3aa793bd32","text":"Kristine Ian"}',
                "text": "Kristine Ian",
            },
        ],
        "pagination": {"more": True},
    }

    question_field = QuizQuestionFactory(
        field_type=AutocompleteSelectField.name,
        form_widget_options={
            "url": url,
            "results_path": "data",
            "id_path": "_id",
            "text_path": "name",
        },
    )

    route_params = {
        "field_app_label": question_field._meta.app_label,
        "field_model_name": question_field._meta.model_name,
        "field_pk": question_field.pk,
    }
    autocomplete_url = reverse("flexible_forms:autocomplete", kwargs=route_params)

    request = rf.get(autocomplete_url, {"page": "1", "per_page": "5"})
    response = views.autocomplete(request=request, **route_params)
    results = json.loads(response.getvalue())

    assert results == expected_results


@pytest.mark.django_db
def test_autocomplete_no_url(rf: RequestFactory) -> None:
    expected_results = {"results": [], "pagination": {"more": False}}

    question_field = QuizQuestionFactory(
        field_type=AutocompleteSelectField.name,
        form_widget_options={
            "url": None,
            "results_path": "data",
            "id_path": "_id",
            "text_path": "name",
        },
    )

    route_params = {
        "field_app_label": question_field._meta.app_label,
        "field_model_name": question_field._meta.model_name,
        "field_pk": question_field.pk,
    }
    autocomplete_url = reverse("flexible_forms:autocomplete", kwargs=route_params)

    request = rf.get(autocomplete_url)
    response = views.autocomplete(request=request, **route_params)
    results = json.loads(response.getvalue())

    assert results == expected_results


@pytest.mark.django_db
def test_autocomplete_manual_pagination(rf: RequestFactory, requests_mock) -> None:
    url = "https://api.instantwebtools.net/v1/passenger"

    mock_response = {
        "totalPassengers": 1897,
        "totalPages": 380,
        "data": [
            {
                "_id": "5f1c59c3fa523c3aa793bcfa",
                "name": " MIRKO TOMIC Mladji",
            },
            {
                "_id": "5f1c59c3fa523c3aa793bd26",
                "name": "Phyllis Jessen",
            },
            {
                "_id": "5f1c59c3fa523c3aa793bd30",
                "name": "Darcie Coleville",
            },
            {
                "_id": "5f1c59c3fa523c3aa793bd2d",
                "name": "Tandy Aphra",
            },
            # Malformed results should be skipped.
            {
                "malformed": "result",
            },
            # Results without an ID will use the name as the ID by default.
            {
                "name": "Same as ID",
            },
            {
                "_id": "5f1c59c4fa523c3aa793bd32",
                "name": "Kristine Ian",
            },
        ],
    }

    requests_mock.get(url, text=json.dumps(mock_response))

    expected_results = {
        "results": [
            {
                "id": '{"extra":{},"id":"5f1c59c3fa523c3aa793bcfa","text":" MIRKO TOMIC Mladji"}',
                "text": " MIRKO TOMIC Mladji",
            },
        ],
        "pagination": {"more": True},
    }

    question_field = QuizQuestionFactory(
        field_type=AutocompleteSelectField.name,
        form_widget_options={
            "url": url,
            "results_path": "data",
            "id_path": "_id",
            "text_path": "name",
        },
    )

    route_params = {
        "field_app_label": question_field._meta.app_label,
        "field_model_name": question_field._meta.model_name,
        "field_pk": question_field.pk,
    }
    autocomplete_url = reverse("flexible_forms:autocomplete", kwargs=route_params)

    request = rf.get(autocomplete_url, {"page": "1", "per_page": "1"})
    response = views.autocomplete(request=request, **route_params)
    results = json.loads(response.getvalue())

    assert results == expected_results
