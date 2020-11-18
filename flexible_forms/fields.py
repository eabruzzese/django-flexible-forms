# -*- coding: utf-8 -*-

"""Field definitions for the flexible_forms module."""

import logging
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Type,
    cast,
)

import jmespath
import requests
import simpleeval
from django.core.paginator import Paginator
from django.db.models import FileField, ImageField
from django.db.models import fields as model_fields
from django.forms import fields as form_fields
from django.forms import widgets as form_widgets
from django.urls import reverse

from flexible_forms.widgets import (
    AutocompleteResult,
    AutocompleteSelect,
    AutocompleteSelectMultiple,
)

try:
    from django.db.models import JSONField  # type: ignore
    from django.forms import JSONField as JSONFormField  # type: ignore
except ImportError:  # pragma: no cover
    from django.contrib.postgres.fields import JSONField
    from django.contrib.postgres.forms import JSONField as JSONFormField

from flexible_forms.utils import evaluate_expression, stable_json

logger = logging.getLogger(__name__)

##
# _EMPTY_CHOICES
_EMPTY_CHOICES = (("EMPTY", "Select a value."),)

if TYPE_CHECKING:  # pragma: no cover
    from flexible_forms.models import BaseField


##
# FIELD_TYPES
#
# A dict mapping of field types, where the key is the string representation of
# the field type (usually its class name), and the value is the `FlexibleField`
# class itself.
#
# Built dynamically to include all descendants of `FieldType`.
#
FIELD_TYPES: Dict[str, Type["FieldType"]] = {}


class FieldTypeOptions:
    """A base class for the Meta inner class for FieldType."""

    abstract = False
    force_replacement = False


class FieldTypeMetaclass(type):
    """A metaclass for handling FieldType configuration and registration."""

    def __new__(
        cls,
        name: str,
        bases: Tuple[type, ...],
        attrs: Dict[str, Any],
        **kwargs: Any,
    ) -> "FieldTypeMetaclass":
        """Create a new FieldType and register it.

        Args:
            cls: This metaclass.
            name: The name of the new FieldType class.
            bases: The base classes of the new FieldType class.
            attrs: The attributes of the new FieldType class.
            kwargs: Passed to super.

        Returns:
            Type[FieldType]: The new FieldType class, configured and registered.

        Raises:
            ValueError: If a FieldType with the same class name was already
                registered, and the force_replacement meta option is False.
        """
        attrs_meta = attrs.pop("Meta", None)
        attrs["_meta"] = type(
            "Meta", tuple(filter(bool, (attrs_meta, FieldTypeOptions))), {}
        )

        # Set the name from the class name if a name was not provided.
        attrs["name"] = attrs.get("name", name)

        clsobj = super().__new__(cls, name, bases, attrs, **kwargs)  # type: ignore

        # Throw an error if a FieldType with the given name was already registered.
        if clsobj.name in FIELD_TYPES and not clsobj._meta.force_replacement:
            raise ValueError(
                f"A FieldType named {name} was already registered ({FIELD_TYPES[name]})."
            )

        # Register the new field type with its class name (if it's not abstract).
        if not clsobj._meta.abstract:
            FIELD_TYPES[name] = clsobj

        return cast("FieldTypeMetaclass", clsobj)


class FieldType(metaclass=FieldTypeMetaclass):
    """A prefabricated field to use with flexible forms.

    Provides an interface to emit a model field, form field, or widget.
    """

    class Meta:
        abstract = True

    ##
    # label
    #
    # The human-friendly key of the field type, e.g. "Single-line Text".
    #
    label: str = ""

    ##
    # form_field_class
    #
    # The class to use when creating a new instance of the field for use in a Django
    # form.
    #
    # Default: django.forms.fields.CharField
    #
    form_field_class: Type[form_fields.Field] = form_fields.CharField

    ##
    # form_field_options
    #
    # Keyword arguments to be passed to the form_field_class constructor.
    #
    # Default: {}
    #
    form_field_options: Dict[str, Any] = {}

    ##
    # form_widget_class
    #
    # The class to use to render the form widget to a form template. If unspecified, use
    # the default for the form_field_class.
    #
    # Default: None
    #
    form_widget_class: Optional[Type[form_widgets.Widget]] = None

    ##
    # form_widget_options
    #
    # Keyword arguments to be passed to the form_widget_class constructor.
    #
    # Default: {}
    #
    form_widget_options: Dict[str, Any] = {}

    ##
    # model_field_class
    #
    # The class to use for when using the field to define a Django model.
    #
    # Default: JSONField
    #
    model_field_class: Type[model_fields.Field] = JSONField

    ##
    # model_field_options
    #
    # Keyword arguments to be passed to the model_field_class constructor.
    #
    # Default: {}
    #
    model_field_options: Dict[str, Any] = {}

    @classmethod
    def as_form_field(
        cls,
        *,
        field: "BaseField",
        modifiers: Sequence[Tuple[str, str]] = (),
        field_values: Optional[Mapping[str, Optional[Any]]] = None,
        **kwargs: Any,
    ) -> form_fields.Field:
        """Return an instance of the field for use in a Django form.

        Passes additional kwargs to the form field constructor.

        Args:
            field: The Field model instance.
            modifiers: A sequence of modifiers to be applied to the field.
            field_values: A mapping of the current form values.
            kwargs: Passed to the form field constructor.

        Returns:
            form_fields.Field: An instance of the form field.
        """
        # If no widget was given explicitly, build a default one.
        kwargs["widget"] = kwargs.get("widget", cls.as_form_widget(field=field))

        # Generate the form field with its appropriate class and widget.
        form_field = cls.form_field_class(
            **{
                **cls.form_field_options,
                **kwargs,
            },
        )

        # Apply any modifiers to the field.
        form_field = cls.apply_modifiers(
            form_field=form_field,
            modifiers=modifiers,
            field_values=field_values,
        )

        return form_field

    @classmethod
    def as_form_widget(cls, field: "BaseField", **kwargs: Any) -> form_widgets.Widget:
        """Return an instance of the form widget for rendering.

        Passes additional kwargs to the form widget constructor.

        Args:
            field: The Field model instance.
            kwargs: Passed through to the form widget constructor.

        Returns:
            form_widgets.Widget: The configured form widget for the field.
        """
        widget_cls = cls.form_widget_class or cls.form_field_class.widget

        return widget_cls(
            **{
                **cls.form_widget_options,
                **kwargs,
            }
        )

    @classmethod
    def as_model_field(cls, **kwargs: Any) -> model_fields.Field:
        """Return an instance of the field for use in a Django model.

        Receives a dict of kwargs to pass through to the model field constructor.

        Args:
            kwargs: A dict of kwargs to be passed to the constructor of the
                `model_field_class`.

        Returns:
            model_fields.Field: An instance of the model field.
        """
        return cls.model_field_class(
            **{
                **cls.model_field_options,
                **kwargs,
            }
        )

    @classmethod
    def apply_modifiers(
        cls,
        form_field: form_fields.Field,
        modifiers: Sequence[Tuple[str, str]] = (),
        field_values: Optional[Mapping[str, Any]] = None,
    ) -> form_fields.Field:
        """Apply the given modifiers to the given Django form field.

        Args:
            form_field: The form field to be modified.
            modifiers: A sequence of tuples
                in the form of (attribute, expression) tuples to apply to the
                field.
            field_values: The current values of
                all fields on the form.

        Returns:
            form_fields.Field: The given form field, modified using the modifiers.
        """
        for attribute, expression in modifiers:
            # Evaluate the expression and set the attribute specified by
            # `self.attribute` to the value it returns.
            try:
                expression_value = evaluate_expression(expression, names=field_values)
            except simpleeval.NameNotDefined:
                continue

            # If the caller has implemented a custom apply_ATTRIBUTENAME method
            # to handle application of the attribute, use it.
            custom_applicator = getattr(cls, f"apply_{attribute}", None)
            if custom_applicator:
                form_field = custom_applicator(
                    **{
                        "form_field": form_field,
                        attribute: expression_value,
                        "field_values": field_values,
                    }
                )

            # If no custom applicator method is implemented, but the form field
            # has an attribute with the specified name, set its value to the
            # result of the expression.
            elif hasattr(form_field, attribute):
                setattr(form_field, attribute, expression_value)

            # Finally, add the modifier and its value to the applied modifiers
            # dict on the field.
            setattr(
                form_field,
                "_modifiers",
                {
                    **getattr(form_field, "_modifiers", {}),
                    attribute: expression_value,
                },
            )

        return form_field

    @classmethod
    def apply_hidden(
        cls, form_field: form_fields.Field, hidden: bool = False, **kwargs: Any
    ) -> form_fields.Field:
        """Apply the "hidden" attribute.

        If a field modifier specifies that the field should be "hidden", its
        widget is changed to a HiddenInput, and its "required" attribute is
        set to False.

        Args:
            form_field: The form field that should be hidden.
            hidden: The new value of "hidden".
            kwargs: Unused.

        Returns:
            form_fields.Field: The given form_field, modified to use the
                given "hidden" value.
        """
        if hidden:
            form_field.widget = form_widgets.HiddenInput()  # type: ignore
            form_field.required = False

        return form_field


class SingleLineTextField(FieldType):
    """A field for collecting single-line text values."""

    label = "Single-line Text"

    form_field_class = form_fields.CharField
    model_field_class = model_fields.TextField


class MultiLineTextField(FieldType):
    """A field for collecting multiline text values."""

    label = "Multi-line Text"

    form_field_class = form_fields.CharField
    form_widget_class = form_widgets.Textarea
    model_field_class = model_fields.TextField


class EmailField(FieldType):
    """A field for collecting email addresses."""

    label = "Email Address"

    form_field_class = form_fields.EmailField
    model_field_class = model_fields.EmailField


class URLField(FieldType):
    """A field for collecting URL values."""

    label = "URL"

    form_field_class = form_fields.URLField
    model_field_class = model_fields.URLField
    model_field_options = {"max_length": 2083}


class SensitiveTextField(FieldType):
    """A field for collecting sensitive text values.

    Primarily useful for obfuscating the input when on-screen.
    """

    label = "Sensitive text"

    form_field_class = form_fields.CharField
    form_widget_class = form_widgets.PasswordInput
    model_field_class = model_fields.TextField


class IntegerField(FieldType):
    """A field for collecting integer values."""

    label = "Integer"

    form_field_class = form_fields.IntegerField
    form_field_options = {"min_value": -2147483648, "max_value": 2147483647}
    model_field_class = model_fields.IntegerField


class PositiveIntegerField(FieldType):
    """A field for collecting positive integer values."""

    label = "Positive Integer"

    form_field_class = form_fields.IntegerField
    form_field_options = {"min_value": 0, "max_value": 2147483647}
    model_field_class = model_fields.PositiveIntegerField


class DecimalField(FieldType):
    """A field for collecting decimal number values."""

    label = "Decimal Number"

    form_field_class = form_fields.DecimalField
    form_field_options = {"max_digits": 15, "decimal_places": 6}
    model_field_class = model_fields.DecimalField
    model_field_options = {"max_digits": 15, "decimal_places": 6}


class DateField(FieldType):
    """A field for collecting date data."""

    label = "Date"

    form_field_class = form_fields.DateField
    model_field_class = model_fields.DateField


class TimeField(FieldType):
    """A field for collecting time data."""

    label = "Time"

    form_field_class = form_fields.TimeField
    model_field_class = model_fields.TimeField


class DateTimeField(FieldType):
    """A field for collecting datetime data."""

    label = "Date & Time"

    form_field_class = form_fields.DateTimeField
    model_field_class = model_fields.DateTimeField


class DurationField(FieldType):
    """A field for collecting duration data."""

    label = "Duration"

    form_field_class = form_fields.DurationField
    model_field_class = model_fields.DurationField


class CheckboxField(FieldType):
    """A field for collecting a boolean value with a checkbox."""

    label = "Checkbox"

    form_field_class = form_fields.BooleanField
    form_widget_class = form_widgets.CheckboxInput
    model_field_class = model_fields.BooleanField


class YesNoRadioField(FieldType):
    """A field for collecting a yes/no value with radio buttons."""

    label = "Yes/No Radio Buttons"

    form_field_class = form_fields.TypedChoiceField
    form_field_options = {
        "choices": (
            ("True", "Yes"),
            ("False", "No"),
        ),
        "coerce": lambda v: True if v in ("True", True) else False,
    }
    form_widget_class = form_widgets.RadioSelect
    model_field_class = model_fields.BooleanField


class YesNoUnknownRadioField(FieldType):
    """A field for collecting a yes/no/unknown value with radio buttons."""

    label = "Yes/No/Unknown Radio Buttons"

    form_field_class = form_fields.TypedChoiceField
    form_field_options = {
        "choices": (
            ("True", "Yes"),
            ("False", "No"),
            ("None", "Unknown"),
        ),
        "coerce": lambda v: (
            True if v in ("True", True) else False if v in ("False", False) else None
        ),
    }
    form_widget_class = form_widgets.RadioSelect
    model_field_class = model_fields.BooleanField
    model_field_options = {"null": True}


class YesNoSelectField(FieldType):
    """A field for collecting a boolean value with a yes/no select field."""

    label = "Yes/No Dropdown"

    form_field_class = form_fields.TypedChoiceField
    form_field_options = {
        "choices": (
            ("True", "Yes"),
            ("False", "No"),
        ),
        "coerce": lambda v: True if v in ("True", True) else False,
    }
    form_widget_class = form_widgets.Select
    model_field_class = model_fields.BooleanField


class YesNoUnknownSelectField(FieldType):
    """A field for collecting a boolean value with a yes/no select field."""

    label = "Yes/No/Unknown Dropdown"

    form_field_class = form_fields.TypedChoiceField
    form_field_options = {
        "choices": (
            ("True", "Yes"),
            ("False", "No"),
            ("None", "Unknown"),
        ),
        "coerce": lambda v: (
            True if v in ("True", True) else False if v in ("False", False) else None
        ),
    }
    model_field_class = model_fields.BooleanField
    model_field_options = {"null": True}


class SingleChoiceSelectField(FieldType):
    """A field for collecting a single text value from a select list."""

    label = "Single-choice Dropdown"

    form_field_class = form_fields.ChoiceField
    form_field_options = {"choices": _EMPTY_CHOICES}
    model_field_class = model_fields.TextField


class SingleChoiceRadioSelectField(FieldType):
    """A field for collecting a text value from a set of radio buttons."""

    label = "Radio Buttons"

    form_field_class = form_fields.ChoiceField
    form_field_options = {"choices": _EMPTY_CHOICES}
    form_widget_class = form_widgets.RadioSelect
    model_field_class = model_fields.TextField


class MultipleChoiceSelectField(FieldType):
    """A field for collecting multiple text values from a select list."""

    label = "Multiple-choice Dropdown"

    form_field_class = form_fields.MultipleChoiceField
    form_field_options = {"choices": _EMPTY_CHOICES}
    model_field_class = JSONField


class MultipleChoiceCheckboxField(FieldType):
    """A field for collecting multiple text values from a checkbox list."""

    label = "Multiple-choice Checkboxes"

    form_field_class = form_fields.MultipleChoiceField
    form_field_options = {"choices": _EMPTY_CHOICES}
    form_widget_class = form_widgets.CheckboxSelectMultiple
    model_field_class = JSONField


class FileUploadField(FieldType):
    """A field for collecting file uploads."""

    label = "File Upload"

    form_field_class = form_fields.FileField
    model_field_class = FileField


class ImageUploadField(FieldType):
    """A field for collecting image uploads."""

    label = "Image Upload"

    form_field_class = form_fields.ImageField
    model_field_class = ImageField


class AutocompleteSelectField(FieldType):
    """A field for autocompleting selections from an HTTP endpoint."""

    label = "Autocomplete"

    form_field_class = JSONFormField
    form_widget_class = AutocompleteSelect
    model_field_class = JSONField

    @classmethod
    def as_form_widget(
        cls, field: "BaseField", **form_widget_options: Any
    ) -> form_widgets.Widget:
        """Build the autocomplete form widget.

        Replaces the url parameter with a proxy URL to a custom view to allow
        developers to implement fine-grained search behavior.

        Args:
            field: The Field record.
            form_widget_options: Parameters passed to the form widget
                constructor.

        Returns:
            form_widgets.Widget: A configured widget for rendering the
                autocomplete input.
        """
        return super().as_form_widget(
            field=field,
            **{
                **form_widget_options,
                "url": reverse(
                    "flexible_forms:autocomplete",
                    kwargs={
                        "field_app_label": field._meta.app_label,
                        "field_model_name": field._meta.model_name,
                        "field_pk": field.pk,
                    },
                ),
            },
        )

    @classmethod
    def autocomplete(
        cls,
        term: Optional[str] = None,
        per_page: Optional[int] = None,
        page: Optional[int] = None,
        **form_widget_options: Any,
    ) -> Tuple[List[AutocompleteResult], bool]:
        """Perform a search against the configured URL.

        Returns a sequence of dicts, each with "id" and "text" values to use
        within a select form element.

        Args:
            term: The search term.
            per_page: The number of search results per page.
            page: The 1-based page number for pagination.
            form_widget_options: A dict of form widget options that can be
                used to customize autocomplete behavior.

        Returns:
            Tuple[Sequence[AutocompleteResult], bool]: A two-tuple containing
                a sequence of zero or more select2-compatible search results, and
                a boolean indicating whether or not there are more results to
                fetch.
        """
        term = term or ""
        per_page = per_page or 100
        page = page or 1

        url = form_widget_options.get("url") or ""
        results_path = form_widget_options.get("results_path") or "@"
        text_path = form_widget_options.get("text_path") or "(text || label || name)"
        id_path = form_widget_options.get("id_path") or "id"

        # Initialize results with an empty list.
        results: List[AutocompleteResult] = []
        has_more = False

        # If no URL has been configured, return results as-is.
        if not url:
            return results, has_more

        # Search the endpoint and raise an exception if we get any non-success
        # status in the response.
        response = requests.get(url.format(term=term, page=page, per_page=per_page))
        response.raise_for_status()

        # Decode the JSON response.
        response_json = response.json()

        # Parse the search response and map each result to a Select2-compatible
        # dict with an "id" and a "text" property.
        results_expr = jmespath.compile(results_path)
        text_expr = jmespath.compile(text_path)
        id_expr = jmespath.compile(id_path)

        raw_results = results_expr.search(response_json)
        for result in raw_results:
            result_text = text_expr.search(result)
            result_value = id_expr.search(result)

            if result_value is None:
                result_value = result_text

            # If the result text and value are both None, skip the entry.
            if result_text is None and result_value is None:
                continue

            # The "id" is the value eventually stored in the database. In this
            # case, it is a stringified version of the result JSON so that it can
            # be deserialized when rendering the initial value for the widget.
            result_id = stable_json(
                {"id": str(result_value), "text": str(result_text), "extra": {}}
            )

            # The use of "id" as opposed to "value" or something that makes
            # more semantic sense is to support the use of the select2
            # implementation that ships with the Django admin.
            results.append({"id": result_id, "text": result_text})

        # If the remote endpoint isn't handling pagination, do it manually.
        if not "{page}" in url:
            paginated_page = Paginator(results, per_page).page(page)
            results, has_more = (
                cast(List[AutocompleteResult], paginated_page.object_list),
                paginated_page.has_next(),
            )

        # If the remote endpoint is handling pagination for us, we can assume
        # that there are more results if the number of results received is
        # greater than or equal to our per_page value (i.e., we received a full
        # page of results).
        else:
            has_more = len(results) >= per_page

        return results, has_more


class AutocompleteSelectMultipleField(AutocompleteSelectField):
    """An autocomplete field that supports multiple selections."""

    form_field_class = JSONFormField
    form_widget_class = AutocompleteSelectMultiple
