# -*- coding: utf-8 -*-
from typing import Type, cast

from django.apps import apps
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404

from flexible_forms.cache import cache
from flexible_forms.fields import BaseAutocompleteSelectField
from flexible_forms.models import BaseField, BaseRecord


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

    # If autocompletion was requested for a specific record, fetch it using
    # the given primary key. If not, use a blank record.
    record_pk = request.GET.get("record_pk")
    record_model = field.flexible_forms.get_model(BaseRecord)
    record = (
        get_object_or_404(record_model, pk=record_pk)
        if record_pk is not None
        else record_model(form=field.form)
    )

    # Fetch the current set of field values from the cache so that the
    # underlying field type can use them to make decisions.
    field_values = cache.get(
        f"flexible_forms:field_values:{record._meta.app_label}:{record._meta.model_name}:{record_pk}",
        default={},
    )

    field_type = cast(
        BaseAutocompleteSelectField,
        field.as_field_type(record=record, field_values=field_values),
    )

    search_results, has_more = field_type.autocomplete(request)

    # Perform the search and return a Select2-compatible response.
    return JsonResponse(
        {
            "results": search_results,
            "pagination": {"more": has_more},
        }
    )
