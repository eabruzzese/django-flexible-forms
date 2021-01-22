# -*- coding: utf-8 -*-
import json
from decimal import Decimal
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
    cast,
)

from django.contrib.admin.widgets import AutocompleteMixin
from django.forms.widgets import Select

from flexible_forms.utils import stable_json


class AutocompleteSelect(Select):
    """A select widget where options are sourced from a remote URL."""

    url: Optional[str]
    allow_freetext: bool
    placeholder: str

    EMPTY_VALUES = (None, "", "null")

    def __init__(
        self,
        url: Optional[str] = None,
        allow_freetext: bool = False,
        placeholder: Optional[str] = None,
        attrs: Optional[Dict[str, Any]] = None,
        choices: Sequence[Tuple[Any, Any]] = (),
        **kwargs: Any,
    ) -> None:
        super().__init__(attrs=attrs, choices=choices)
        self.url = url
        self.allow_freetext = allow_freetext
        self.placeholder = placeholder or ""

    def optgroups(  # type: ignore
        self, name: str, value: str, attrs: Optional[Dict[Any, Any]] = None
    ) -> List[Tuple[None, List[Dict[str, Any]], int]]:
        """Build a list of optgroups for populating the select.

        Autocompletes are powered by external endpoints, and so the selected
        options must be derived from the selected value to avoid making an
        HTTP call just to render the field.

        The AutocompleteWidget assumes that the stored value is the JSON
        representation of the originally-selected result from the
        autocomplete API call.

        Args:
            name: The name of the widget in the form.
            value: The value of the field.
            attrs: Unused.

        Returns:
            List[Tuple[Optional[str], List[Tuple[Any, Any]], int]]: Optgroups
                for the widget.
        """
        default: Tuple[None, List[Dict[str, Any]], int] = (None, [], 0)
        groups = [default]
        has_selected = False

        # Parse the given value as a JSON string, and make it a list if it
        # isn't already so that we can iterate over it when we enumerate
        # selected options.
        parsed_value = json.loads(value)
        parsed_value = (
            parsed_value if isinstance(parsed_value, list) else [parsed_value]
        )

        selected_choices = {
            stable_json(v)
            for v in parsed_value
            if not self._choice_has_empty_value((stable_json(v), ""))
        }

        if not self.is_required and not self.allow_multiple_selected:
            default[1].append(self.create_option(name, "", "", False, 0))

        choices = [
            (stable_json(v), v["text"])
            for v in parsed_value
            if v not in (None, "", "null")
        ]

        for option_value, option_label in choices:
            selected = str(option_value) in parsed_value and (
                has_selected is False or self.allow_multiple_selected
            )
            has_selected |= selected
            index = len(default[1])
            subgroup = default[1]
            subgroup.append(
                self.create_option(
                    name, option_value, option_label, selected_choices, index
                )
            )

        return groups

    def build_attrs(
        self, base_attrs: Dict[str, Any], extra_attrs: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Union[Decimal, float, str]]:
        """Set select2's AJAX attributes.

        Attributes can be set using the html5 data attribute.
        Nested attributes require a double dash as per
        https://select2.org/configuration/data-attributes#nested-subkey-options
        """
        attrs = super().build_attrs(base_attrs, extra_attrs=extra_attrs)
        return {
            **attrs,
            "data-ajax--cache": "true",
            "data-ajax--delay": 250,
            "data-ajax--type": "GET",
            "data-ajax--url": self.url or "",
            "data-theme": "admin-autocomplete",
            "data-allow-clear": json.dumps(not self.is_required),
            "data-placeholder": self.placeholder,
            "data-close-on-select": "false" if self.allow_multiple_selected else "true",
            "data-tags": json.dumps(self.allow_freetext),
            "data-disabled": json.dumps(
                "true"
                in (
                    str(attrs.get("disabled", "false")).lower(),
                    str(attrs.get("readonly", "false")).lower(),
                )
            ),
            "class": " ".join(
                [str(attrs.get("class", "")), "admin-autocomplete"]
            ).strip(),
        }

    def value_from_datadict(
        self, data: Dict[str, Any], files: Mapping[str, Iterable[Any]], name: str
    ) -> str:
        """Extract the widget's value from the given data.

        Handles the case where multiple values are selected.

        Args:
            data: The form data.
            files: File uploads submitted with the form data.
            name: The name of the widget.

        Returns:
            str: The JSON value produced by the widget.
        """
        value = super().value_from_datadict(data, files, name)

        if value is None:
            value = []

        if not isinstance(value, list):
            value = [value]

        parsed_value: List[dict] = []
        for v in value:
            # Skip empty values.
            if v in self.EMPTY_VALUES:
                continue

            parsed_v = None

            # If the value is already a dict, we'll just consider it to be
            # already parsed.
            if isinstance(v, dict):
                parsed_v = v

            # If the value is a string and it looks like a JSON object, parse
            # it as one.
            elif isinstance(v, str):
                if v.startswith("{") and v.endswith("}"):
                    parsed_v = json.loads(v)
                else:
                    parsed_v = json.loads(stable_json({"id": v, "text": v, "value": v}))

            if parsed_v is not None:
                parsed_value.append(parsed_v)

        # If only one value is expected, unwrap it from the parsed list.
        final_value = (
            next(iter(cast(Iterable, parsed_value)), None)
            if not self.allow_multiple_selected
            else parsed_value
        )

        return json.dumps(final_value)

    def format_value(self, value: Any) -> Any:
        """Format a value for rendering in a widget template.

        Args:
            value: The value to format.

        Returns:
            Any: The formatted value, if formatting was successful. Otherwise
                returns the value unmodified.
        """
        return str([] if value in self.EMPTY_VALUES else value)

    @staticmethod
    def _choice_has_empty_value(choice: Tuple[Any, str]) -> bool:
        """Return True if the value of the given choice is empty.

        Args:
            choice: The choice two-tuple to check for an empty value.

        Returns:
            bool: True if the value of the given choice is empty, Flase
                otherwise.
        """
        value, _ = choice
        return value in AutocompleteSelect.EMPTY_VALUES

    # Use the media property from Django Admin's AutocompleteMixin (which this
    # widget is based on). This ensures that the Django admin appropriately
    # loads the required Select2 frontend assets.
    media = AutocompleteMixin.media


class AutocompleteSelectMultiple(AutocompleteSelect):
    """An AutocompleteSelect that supports multiple selections."""

    allow_multiple_selected = True
