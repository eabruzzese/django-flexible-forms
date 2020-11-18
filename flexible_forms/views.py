# -*- coding: utf-8 -*-
from typing import Type, cast

from django.apps import apps
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404

from flexible_forms.fields import AutocompleteSelectField
from flexible_forms.models import BaseField


def autocomplete(
    request: HttpRequest, field_app_label: str, field_model_name: str, field_pk: str
) -> JsonResponse:
    """Perform a search and return autocomplete results.

    Args:
        request: The current HTTP request.
        field_app_label: The app_label of the appropriate BaseField implementation.
        field_model_name: The app_label of the appropriate BaseField implementation.
        field_pk: The primary key of the Field record.

    Returns:
        JsonResponse: A select2-compatible JSON response of autocomplete suggestions.
    """
    # Retrieve the Field.
    field_model = cast(
        Type[BaseField], apps.get_model(field_app_label, field_model_name)
    )
    field = get_object_or_404(field_model, pk=field_pk)
    field_type = cast(AutocompleteSelectField, field.as_field_type())

    search_term = request.GET.get("term")
    page = int(request.GET.get("page", 1))
    per_page = int(
        request.GET.get("per_page", field.form_widget_options.get("per_page", 100))
    )

    search_results, has_more = field_type.autocomplete(
        term=search_term,
        page=page,
        **{
            **field.form_widget_options,
            "per_page": per_page,
        }
    )

    # Perform the search and return a Select2-compatible response.
    return JsonResponse(
        {
            "results": search_results,
            "pagination": {"more": has_more},
        }
    )
