# -*- coding: utf-8 -*-
from typing import Type, cast

from django.apps import apps
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404

from flexible_forms.fields import URLAutocompleteSelectField
from flexible_forms.models import BaseField


def autocomplete(
    request: HttpRequest, app_label: str, model_name: str, field_pk: str
) -> JsonResponse:
    """Perform a search and return autocomplete results.

    Args:
        request: The current HTTP request.
        app_label: The app_label of the appropriate BaseField implementation.
        model_name: The app_label of the appropriate BaseField implementation.
        field_pk: The primary key of the Field record.

    Returns:
        JsonResponse: A select2-compatible JSON response of autocomplete suggestions.
    """
    # Retrieve the Field.
    field_model = cast(Type[BaseField], apps.get_model(app_label, model_name))
    field = get_object_or_404(field_model, pk=field_pk)
    field_type = cast(URLAutocompleteSelectField, field.as_field_type())

    search_results, has_more = field_type.autocomplete(request=request, field=field)

    # Perform the search and return a Select2-compatible response.
    return JsonResponse(
        {
            "results": search_results,
            "pagination": {"more": has_more},
        }
    )
