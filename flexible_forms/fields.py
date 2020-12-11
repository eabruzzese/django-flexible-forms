# -*- coding: utf-8 -*-

"""Field definitions for the flexible_forms module."""

import json
import logging
import urllib.parse as urlparse
from typing import (
    TYPE_CHECKING,
    Any,
    Collection,
    Dict,
    Iterable,
    Optional,
    Sequence,
    Sized,
    Tuple,
    Type,
    TypedDict,
    cast,
)

import requests
import simpleeval
from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from django.core.paginator import Paginator
from django.db.models import FileField, ImageField
from django.db.models import Model as DjangoModel
from django.db.models import fields as model_fields
from django.forms import fields as form_fields
from django.forms import widgets as form_widgets
from django.http import HttpRequest, QueryDict
from django.shortcuts import get_object_or_404
from django.template import Context, Template
from django.template.base import VariableNode
from django.urls import Resolver404, resolve, reverse
from django.utils.functional import cached_property

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

from flexible_forms.utils import (
    evaluate_expression,
    get_expression_fields,
    jp,
    stable_json,
)

logger = logging.getLogger(__name__)

##
# _EMPTY_CHOICES
_EMPTY_CHOICES = (("EMPTY", "Select a value."),)

if TYPE_CHECKING:  # pragma: no cover
    from flexible_forms.models import BaseField, BaseRecord


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
        field_values: Dict[str, Optional[Any]],
        record: Optional["BaseRecord"] = None,
        modifiers: Sequence[Tuple[str, str]] = (),
        **form_field_options: Any,
    ) -> form_fields.Field:
        """Return an instance of the field for use in a Django form.

        Passes additional kwargs to the form field constructor.

        Args:
            field: The Field model instance.
            record: The record instance to which the form is bound, if
                available.
            modifiers: A sequence of modifiers to be applied to the field.
            field_values: A mapping of the current form values.
            form_field_options: Passed to the form field constructor.

        Returns:
            form_fields.Field: An instance of the form field.
        """
        # If no widget was given explicitly, build a default one.
        form_field_options["widget"] = form_field_options.get(
            "widget", cls.as_form_widget(field=field, record=record)
        )

        # Generate the form field with its appropriate class and widget.
        form_field = cls.form_field_class(
            **{
                **cls.form_field_options,
                **form_field_options,
            },
        )

        # Apply any modifiers to the field.
        form_field = cls.apply_modifiers(
            form_field,
            field=field,
            record=record,
            modifiers=modifiers,
            field_values=field_values,
        )

        return form_field

    @classmethod
    def as_form_widget(
        cls,
        *,
        field: "BaseField",
        record: Optional["BaseRecord"] = None,
        **form_widget_options: Any,
    ) -> form_widgets.Widget:
        """Return an instance of the form widget for rendering.

        Passes additional kwargs to the form widget constructor.

        Args:
            field: The Field model instance.
            record: The record instance to which the form is bound, if
                available.
            form_widget_options: Passed through to the form widget constructor.

        Returns:
            form_widgets.Widget: The configured form widget for the field.
        """
        widget_cls = cls.form_widget_class or cls.form_field_class.widget

        return widget_cls(
            **{
                **cls.form_widget_options,
                **form_widget_options,
            }
        )

    @classmethod
    def as_model_field(cls, **model_field_options: Any) -> model_fields.Field:
        """Return an instance of the field for use in a Django model.

        Receives a dict of kwargs to pass through to the model field constructor.

        Args:
            model_field_options: A dict of kwargs to be passed to the
                constructor of the `model_field_class`.

        Returns:
            model_fields.Field: An instance of the model field.
        """
        return cls.model_field_class(
            **{
                **cls.model_field_options,
                **model_field_options,
            }
        )

    @classmethod
    def apply_modifiers(
        cls,
        form_field: form_fields.Field,
        *,
        field: "BaseField",
        field_values: Dict[str, Any],
        record: Optional["BaseRecord"] = None,
        modifiers: Sequence[Tuple[str, str]] = (),
    ) -> form_fields.Field:
        """Apply the given modifiers to the given Django form field.

        Args:
            form_field: The form field to be modified.
            field: The BaseField instance.
            field_values: The current values of all fields on the form.
            record: The BaseRecord instance, if available.
            modifiers: A sequence of tuples
                in the form of (attribute, expression) tuples to apply to the
                field.

        Returns:
            form_fields.Field: The given form field, modified using the modifiers.
        """
        for attribute, expression in modifiers:
            expression_context = field_values

            if record:
                record_variable = (
                    (record._meta.verbose_name or "record").lower().replace(" ", "_")
                )
                expression_context = {record_variable: record, **field_values}

            # Evaluate the expression and set the attribute specified by
            # `self.attribute` to the value it returns.
            try:
                expression_value = evaluate_expression(
                    expression, names=expression_context
                )
            except simpleeval.NameNotDefined:
                continue

            # If the caller has implemented a custom apply_ATTRIBUTENAME method
            # to handle application of the attribute, use it.
            custom_applicator = getattr(cls, f"apply_{attribute}", None)
            if custom_applicator:
                form_field = custom_applicator(
                    form_field,
                    field=field,
                    record=record,
                    field_values=field_values,
                    **{attribute: expression_value},
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
        cls,
        form_field: form_fields.Field,
        *,
        hidden: bool = False,
        **kwargs: Any,
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


AutocompleteResultMapping = TypedDict(
    "AutocompleteResultMapping",
    {"root": str, "value": str, "text": str, "extra": Dict[str, str]},
    total=False,
)


class AutocompleteSelectField(FieldType):
    """A field for autocompleting selections from an HTTP endpoint."""

    label = "Autocomplete"

    form_field_class = JSONFormField
    form_widget_class = AutocompleteSelect
    model_field_class = JSONField

    DEFAULT_RESULT_MAPPING: AutocompleteResultMapping = {
        "root": "@",
        "value": "id",
        "text": "text",
        "extra": {},
    }

    @classmethod
    def as_form_widget(
        cls,
        field: "BaseField",
        record: Optional["BaseRecord"] = None,
        **form_widget_options: Any,
    ) -> form_widgets.Widget:
        """Build the autocomplete form widget.

        Replaces the url parameter with a proxy URL to a custom view to allow
        developers to implement fine-grained search behavior.

        Args:
            field: The Field record.
            record: The record instance to which the form is bound, if
                available.
            form_widget_options: Parameters passed to the form widget
                constructor.

        Returns:
            form_widgets.Widget: A configured widget for rendering the
                autocomplete input.
        """
        proxy_url = reverse(
            "flexible_forms:autocomplete",
            kwargs={
                "app_label": field._meta.app_label,
                "model_name": field._meta.model_name,
                "field_pk": field.pk,
            },
        )

        # If a specific record instance was supplied, append its ID to the URL
        # so that autocomplete suggestions can be tailored to a particular
        # record's field values.
        proxy_url = f"{proxy_url}?record_pk={record.pk}" if record else proxy_url

        return super().as_form_widget(
            field=field,
            record=record,
            **{
                **form_widget_options,
                "url": proxy_url,
            },
        )

    @classmethod
    def autocomplete(
        cls,
        request: HttpRequest,
        field: "BaseField",
        **form_widget_options: Any,
    ) -> Tuple[Collection[AutocompleteResult], bool]:
        """Perform a search against the configured URL.

        Returns a sequence of dicts, each with "id" and "text" values to use
        within a select form element.

        Args:
            request: The HTTP request.
            field: The Field record instance that uses this autocomplete.
            form_widget_options: A dict of form widget options that can be
                used to customize autocomplete behavior.

        Returns:
            Tuple[Sequence[AutocompleteResult], bool]: A two-tuple containing
                a sequence of zero or more select2-compatible search results, and
                a boolean indicating whether or not there are more results to
                fetch.
        """
        # Extract GET parameters common to all autocomplete fields.
        search_term = request.GET.get("term", "")
        record_pk = request.GET.get("record_pk")
        page = int(request.GET.get("page", "1"))
        per_page = int(request.GET.get("per_page", "50"))

        raw_results, has_more, filtered, paginated = cls.get_raw_results(
            request,
            field,
            search_term=search_term,
            record_pk=int(record_pk) if record_pk else None,
            page=page,
            per_page=per_page,
            **form_widget_options,
        )

        if not filtered:
            raw_results = cls.filter_raw_results(
                request,
                field,
                raw_results=raw_results,
                search_term=search_term,
                **form_widget_options,
            )

        if not paginated:
            raw_results, has_more = cls.paginate_raw_results(
                request,
                field,
                raw_results=raw_results,
                page=page,
                per_page=per_page,
                **form_widget_options,
            )

        mapped_results = cls.map_raw_results(
            request, field, raw_results=raw_results, **form_widget_options
        )

        return mapped_results, has_more

    @classmethod
    def get_raw_results(
        cls,
        request: HttpRequest,
        field: "BaseField",
        search_term: str,
        record_pk: Optional[int],
        page: int,
        per_page: int,
        **form_widget_options: Any,
    ) -> Tuple[Collection[Any], bool, bool, bool]:
        """Retrieve the "raw" results for the search.

        Performs the initial fetch of results, as well as optionally
        filtering them with the search term and/or paginating them with the
        given page and per_page parameters.

        It should *not* perform any mapping.

        Args:
            request: The current HttpRequest.
            field: The BaseField instance.
            search_term: The given search term.
            record_pk: The primary key for the record being filled out.
            page: The pagination page number.
            per_page: The pagination page size.
            form_widget_options: Options for the form widget.

        Returns:
            Tuple[Collection[Any], bool, bool, bool]: A collection of
                unmapped results and three flags: has_more (indicating that
                there are more results to be fetched with pagination),
                filtered (whether the search_term has already been used to
                filter the results), and paginated (whether the pagination
                parameters have already been applied to the results).
        """
        url_template = form_widget_options.get("url", "")
        raw_results, has_more, filtered, paginated = (
            cast(Collection[Any], []),
            False,
            True,
            True,
        )

        if not url_template:
            return raw_results, has_more, filtered, paginated

        rendered_url, template_variables = cls._render_url(
            request,
            field,
            url_template=url_template,
            record_pk=record_pk,
            search_term=search_term,
            page=page,
            per_page=per_page,
            **form_widget_options,
        )

        raw_results = cls._request_url(
            request,
            field,
            **{
                **form_widget_options,
                "url": rendered_url,
            },
        )

        mapping = cast(
            AutocompleteResultMapping,
            {
                **cls.DEFAULT_RESULT_MAPPING,
                **form_widget_options.get("mapping", {}),
            },
        )

        raw_results = jp(mapping["root"], raw_results) or []

        # Determine whether the URL was rendered with the search term and
        # pagination info. These flags are used to determine if the
        # autocomplete should attempt to manually search or paginate the
        # results.
        filtered = "term" in template_variables
        paginated = "page" in template_variables

        return raw_results, has_more, filtered, paginated

    @classmethod
    def _render_url(
        cls,
        request: HttpRequest,
        field: "BaseField",
        url_template: str,
        search_term: str,
        record_pk: Optional[int],
        page: int,
        per_page: int,
        **form_widget_options: Any,
    ) -> Tuple[str, Dict[str, Any]]:
        """Render the URL using DTL.

        Uses the record (if available) and the request's GET parameters as
        context when rendering.

        Args:
            request: The current HttpRequest.
            field: The BaseField instance.
            url_template: The url template string configured in the form_widget_options.
            search_term: The search_term for filtering the results.
            record_pk: The primary key of the record currently being filled.
            page: The pagination page number.
            per_page: The pagination page size.
            form_widget_options: Options passed to the form widget.

        Returns:
            Tuple[str, Dict[str, Any]]: The rendered URL and a dict
                containing the names and values of the variables used to
                render it.
        """
        # Prevent a circular import.
        from flexible_forms.models import BaseRecord

        # If autocompletion was requested for a specific record, fetch it using
        # the given primary key. Otherwise, make a blank record.
        record_model = field.flexible_forms.get_model(BaseRecord)
        record = (
            get_object_or_404(record_model, pk=record_pk)
            if record_pk is not None
            else record_model(form=field.form)
        )

        # Render the URL as a Django Template, feeding it the current field
        # values, the record instance ("meta"), and the GET parameters.
        template = Template(url_template)
        record_variable = (
            (record._meta.verbose_name or "record").lower().replace(" ", "_")
        )
        url_template_context = Context(
            {
                record_variable: record,
                **request.GET.dict(),
                "search_term": search_term,
                "page": page,
                "per_page": per_page,
            }
        )

        # Extract a list of variables used in rendering and create a dict of
        # them and their values to return along with the rendered URL.
        rendered_context = {
            var: url_template_context[var]
            for var in frozenset(
                v.filter_expression.var.lookups[0]
                for v in template.nodelist
                if isinstance(v, VariableNode)
            )
        }

        return cast(str, template.render(url_template_context)), rendered_context

    @classmethod
    def _request_url(
        cls,
        request: HttpRequest,
        field: "BaseField",
        url: str,
        **form_widget_options: Any,
    ) -> Any:
        """Make a request to the configured URL and return the JSON response.

        Args:
            request: The current HttRequest.
            field: The BaseField instance.
            url: The URL from which to fetch results.
            form_widget_options: Options passed to the form widget.

        Returns:
            The response from the endpoint, as JSON.
        """
        parsed_url = urlparse.urlparse(url)
        response_json = None

        # If the configured URL is just a path, we might be able to simply
        # proxy the request to an internal view function instead of making an
        # entirely new HTTP request. This is less expensive and side-steps
        # issues with auth when calling local views.
        if not parsed_url.netloc:
            try:
                resolver_match = resolve(parsed_url.path)
            except Resolver404:  # pragma: no cover
                pass
            else:
                view_func, args, kwargs = resolver_match

                # Invalidate cached properties affected by the request update.
                for attr, value in type(request).__dict__.items():
                    if not isinstance(value, cached_property):
                        continue
                    try:
                        delattr(request, attr)
                    except AttributeError:
                        pass

                # Update the request to point to the configured URL.
                request.META["QUERY_STRING"] = parsed_url.query
                request.GET = QueryDict(parsed_url.query)
                request.path = parsed_url.path
                request.path_info = parsed_url.path
                request.resolver_match = resolver_match

                # Call the view function with the updated request object.
                response = view_func(request, *args, **kwargs)
                response_json = json.loads(
                    getattr(response, "rendered_content", response.content)
                )

        # If we weren't able to call a local view to get our results, we'll
        # make a regular GET request to the URL instead.
        if response_json is None:
            response = requests.get(request.build_absolute_uri(url))
            response.raise_for_status()
            response_json = response.json()

        return response_json

    @classmethod
    def filter_raw_results(
        cls,
        request: HttpRequest,
        field: "BaseField",
        raw_results: Collection[Any],
        search_term: str,
        **form_widget_options: Any,
    ) -> Collection[Any]:
        """Filter a collection of raw results with the given search_term.

        If searching was not handled when fetching the raw results, it can be
        performed manually here.

        Args:
            request: The current HttpRequest.
            field: The BaseField instance.
            raw_results: The collection of raw results.
            search_term: The term to filter results with.
            form_widget_options: The options passed to the form widget.

        Returns:
            Collection[Any]: A filtered collection of raw results.
        """
        if not search_term:
            return raw_results

        mapping = cast(
            AutocompleteResultMapping,
            {**cls.DEFAULT_RESULT_MAPPING, **form_widget_options.get("mapping", {})},
        )
        search_field = form_widget_options.get("search_field", mapping["text"])

        filtered_results = []
        for raw_result in raw_results or []:
            search_text = jp(search_field, dict(raw_result))

            # If the search term doesn't exist in the result, skip it.
            if search_term.casefold() not in str(search_text).casefold():
                continue

            filtered_results.append(raw_result)

        return filtered_results

    @classmethod
    def paginate_raw_results(
        cls,
        request: HttpRequest,
        field: "BaseField",
        raw_results: Sized,
        page: int,
        per_page: int,
        **form_widget_options: Any,
    ) -> Tuple[Collection[Any], bool]:
        """Paginate a collection of raw results.

        Args:
            request: The current HttpRequest.
            field: The BaseField instance.
            raw_results: The unpaginated collection of raw results.
            page: The pagination page number.
            per_page: The pagination page size.
            form_widget_options: The options passed to the form widget.

        Returns:
            Tuple[Collection[Any], bool]: The list of objects in the current
                pagination page, and a flag indicating whether there are more
                results to fetch.
        """
        paginator = Paginator(raw_results, per_page)
        paginated_page = paginator.page(page)

        return paginated_page.object_list, paginated_page.has_next()

    @classmethod
    def map_raw_results(
        cls,
        request: HttpRequest,
        field: "BaseField",
        raw_results: Iterable[Any],
        **form_widget_options: Any,
    ) -> Collection[AutocompleteResult]:
        """Extract a list of autocomplete results from the given response JSON.

        Args:
            request: The current HttpRequest.
            field: The BaseField instance.
            raw_results: The raw JSON received from requesting the configured URL.
            form_widget_options: The form_widget_options configured for the field.

        Returns:
            Collection[AutocompleteResults]: A list of Select2-compatible autocomplete results.
        """
        results = []

        # Define a default result mapping and merge the configured mapping into
        # it, if given.
        mapping = cast(
            AutocompleteResultMapping,
            {
                **cls.DEFAULT_RESULT_MAPPING,
                **form_widget_options.get("mapping", {}),
            },
        )

        # Parse the search response and map each result to a Select2-compatible
        # dict with an "id" and a "text" property.
        for result in raw_results:
            # print(repr(mapping))
            # print(repr(result))
            result_text = jp(mapping["text"], result)
            result_value = jp(mapping["value"], result, default=result_text)
            result_extra = {k: jp(v, result) for k, v in mapping["extra"].items()}

            result = {
                "value": result_value,
                "text": result_text,
                "extra": result_extra,
            }

            # The "id" is the value eventually stored in the database. In this
            # case, it is a stringified version of the result JSON so that it can
            # be deserialized when rendering the initial value for the widget.
            #
            # The use of "id" as opposed to "value" or something that makes
            # more semantic sense is to support the use of the select2
            # implementation that ships with the Django admin.
            result["id"] = stable_json(result)

            results.append(result)

        return results


class AutocompleteSelectMultipleField(AutocompleteSelectField):
    """An autocomplete field that supports multiple selections."""

    form_field_class = JSONFormField
    form_widget_class = AutocompleteSelectMultiple


class QuerysetAutocompleteSelectField(AutocompleteSelectField):
    """An autocomplete field that sources options from a queryset."""

    @classmethod
    def get_raw_results(
        cls,
        request: HttpRequest,
        field: "BaseField",
        search_term: str,
        record_pk: Optional[int],
        page: int,
        per_page: int,
        **form_widget_options: Any,
    ) -> Tuple[Collection[Any], bool, bool, bool]:
        """Retrieve the "raw" results for the search.

        Performs the initial fetch of results, as well as optionally
        filtering them with the search term and/or paginating them with the
        given page and per_page parameters.

        It should *not* perform any mapping.

        Args:
            request: The current HttpRequest.
            field: The BaseField instance.
            search_term: The given search term.
            record_pk: The primary key for the record being filled out.
            page: The pagination page number.
            per_page: The pagination page size.
            form_widget_options: The options passed to the form widget.

        Returns:
            Tuple[Collection[Any], bool, bool, bool]: A collection of
                unmapped results and three flags: has_more (indicating that
                there are more results to be fetched with pagination),
                filtered (whether the search_term has already been used to
                filter the results), and paginated (whether the pagination
                parameters have already been applied to the results).

        Raises:
            ImproperlyConfigured: if the search_field is not a concrete field
                on the configured model.
        """
        # Extract the relevant configuration from the form widget options.
        model = form_widget_options["model"]
        filter = form_widget_options.get("filter", {})
        exclude = form_widget_options.get("exclude", {})
        mapping = form_widget_options.get("mapping", {})
        search_field = form_widget_options.get("search_field")

        # Build the queryset from the configured parameters.
        model_cls = cast(DjangoModel, apps.get_model(model))
        qs = (
            model_cls._default_manager.filter(**(filter or {}))
            .exclude(**(exclude or {}))
            .order_by("pk")
        )

        # If the field is configured with a search_field, and that search field
        # is able to be filtered at the database level, use it to filter
        # results instead of doing it manually later.
        if search_term and search_field:
            # If the search_field is not a concrete model field, it can't be used to filter results.
            if not search_field in set(f.name for f in model_cls._meta.concrete_fields):
                raise ImproperlyConfigured(
                    f"The search_field option for {cls.__name__} fields must be a concrete model field."
                )
            qs = qs.filter(**{f"{search_field}__icontains": search_term})

        paginator = Paginator(qs, per_page)
        paginated_page = paginator.page(page)

        raw_results, has_more = (paginated_page.object_list, paginated_page.has_next())

        return raw_results, has_more, True, True

    @classmethod
    def map_raw_results(
        cls,
        request: HttpRequest,
        field: "BaseField",
        raw_results: Iterable[Any],
        **form_widget_options: Any,
    ) -> Collection[AutocompleteResult]:
        """Extract a list of autocomplete results from the given iterable.

        Args:
            request: The current HttpRequest.
            field: The BaseField instance.
            raw_results: The raw JSON received from requesting the configured URL.
            form_widget_options: The form_widget_options configured for the field.

        Returns:
            Collection[AutocompleteResults]: A list of Select2-compatible autocomplete results.
        """
        mapping = cast(
            AutocompleteResultMapping,
            {
                **cls.DEFAULT_RESULT_MAPPING,
                **form_widget_options.get("mapping", {}),
                "root": "@",
            },
        )

        # Build a list of model fields referenced in the mapping expressions.
        expression_fields = set()
        for expr in (*mapping.values(), *mapping["extra"].values()):
            if not isinstance(expr, str):
                continue
            expression_fields.update(get_expression_fields(expr))

        return super().map_raw_results(
            request,
            field,
            raw_results=(
                {f: getattr(instance, f, None) for f in expression_fields}
                for instance in raw_results
            ),
            **{
                **form_widget_options,
                "mapping": mapping,
            },
        )


class QuerysetAutocompleteSelectMultipleField(QuerysetAutocompleteSelectField):
    """A queryset autocomplete field that supports multiple selections."""

    form_field_class = JSONFormField
    form_widget_class = AutocompleteSelectMultiple
