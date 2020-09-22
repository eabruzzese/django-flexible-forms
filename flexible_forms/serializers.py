"""Serializers for Django forms."""

import json
from types import GeneratorType
from typing import Any, Mapping
from django import forms
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models.fields.files import FieldFile


class FormJSONEncoder(DjangoJSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, FieldFile):
            return o.url
        return super().default(o)


def _to_json(data: Mapping[str, Any], **kwargs: Any) -> Mapping[str, Any]:
    return json.loads(json.dumps(data, cls=FormJSONEncoder, **kwargs))


def form_to_json(form: forms.Form) -> Mapping[str, Any]:
    """Convert the given Django form to JSON."""
    return _to_json(
        {
            "_type": form.__class__.__name__,
            "non_field_errors": form.non_field_errors(),
            "label_suffix": form.label_suffix,
            "is_bound": form.is_bound,
            "prefix": form.prefix,
            "fields": {
                field_name: field_to_json(field, field_name, form)
                for field_name, field in form.fields.items()
            },
            "fieldsets": getattr(form, "fieldsets", []),
            "data": form.data or form.initial,
            "files": form.files,
        }
    )


def field_to_json(
    field: forms.Field, field_name: str, form: forms.Form
) -> Mapping[str, Any]:
    """Convert the given Django form field to JSON."""
    return _to_json(
        {
            "_field_type": field.__class__.__name__,
            "_flexible_field_type": (
                field._flexible_field_type.__name__
                if hasattr(field, "_flexible_field_type")
                else None
            ),
            "_flexible_field_modifiers": getattr(
                field, "_flexible_field_modifiers", None
            ),
            "required": field.required,
            "label": field.label,
            "initial": form.initial.get(field_name),
            "help_text": field.help_text,
            "error_messages": field.error_messages,
            "widget": widget_to_json(field.widget),
            "choices": list(
                {"value": str(value), "text": label}
                for value, label in getattr(field, "choices", [])
            ),
        }
    )


def widget_to_json(widget: forms.widgets.Widget) -> Mapping[str, Any]:
    return _to_json(
        {
            "_type": widget.__class__.__name__,
            "input_type": getattr(widget, "input_type", None),
            "is_hidden": widget.is_hidden,
            "needs_multipart_form": widget.needs_multipart_form,
            "is_localized": widget.is_localized,
            "is_required": widget.is_required,
            "attrs": widget.attrs,
        }
    )
