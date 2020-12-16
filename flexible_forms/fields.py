# -*- coding: utf-8 -*-

"""Field definitions for the flexible_forms module."""

import json
import logging
import urllib.parse as urlparse
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    Type,
    Union,
    cast,
)

import requests
import simpleeval
from django.apps import apps
from django.contrib.postgres.search import SearchQuery, SearchVector
from django.core.exceptions import ImproperlyConfigured
from django.core.paginator import Paginator
from django.db import connections
from django.db.models import FileField, ImageField
from django.db.models import Model as DjangoModel
from django.db.models import Value
from django.db.models import fields as model_fields
from django.db.models.functions import Cast, Concat
from django.db.models.query import QuerySet
from django.forms import fields as form_fields
from django.forms import widgets as form_widgets
from django.http import HttpRequest, QueryDict
from django.shortcuts import get_object_or_404
from django.urls import Resolver404, resolve, reverse
from django.utils.functional import cached_property
from typing_extensions import TypedDict

from flexible_forms.widgets import (
    AutocompleteSelect,
    AutocompleteSelectMultiple,
)

try:
    from django.db.models import JSONField  # type: ignore
    from django.forms import JSONField as JSONFormField
except ImportError:  # pragma: no cover
    from django.contrib.postgres.fields import JSONField
    from django.contrib.postgres.forms import JSONField as JSONFormField  # type: ignore

from flexible_forms.utils import (
    RenderedString,
    evaluate_expression,
    get_expression_fields,
    interpolate,
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

    # The name is set by the Metaclass when the class is initialized.
    name: str

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
        widget_cls = cls.form_widget_class or cast(
            Type[form_widgets.Widget], cls.form_field_class.widget
        )

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
            form_field.widget = form_widgets.HiddenInput()
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


AutocompleteResult = TypedDict("AutocompleteResult", {"id": str, "text": str})
AutocompleteResultMapping = TypedDict(
    "AutocompleteResultMapping",
    {"root": str, "value": str, "text": str, "extra": Dict[str, str]},
    total=False,
)


class BaseAutocompleteSelectField(FieldType):
    """An interface for implementing autocomplete select fields."""

    class Meta:
        abstract = True

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
    ) -> Tuple[Iterable[AutocompleteResult], bool]:
        """Return paginated search results for the given search_term.

        Returns an iterable of AutocompleteSearchResult objects and a boolean
        indicating whether there are more to be fetched via pagination.

        This method is responsible for extracting GET parameters from the
        request, fetching the appropriate record instance (if needed),
        interpolating any templated values in the field's form_field_options
        dict, and finally passing the results of those operations to the
        field type's get_results() method to perform the actual search.

        Args:
            request: The HTTP request.
            field: The Field record instance that uses this autocomplete.

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

        # Build the context for rendering the data.
        from flexible_forms.models import BaseRecord

        # If autocompletion was requested for a specific record, fetch it using
        # the given primary key. If not, use a blank record.
        record_model = field.flexible_forms.get_model(BaseRecord)
        record_alias = (
            (record_model._meta.verbose_name or "record").lower().replace(" ", "_")
        )
        record = (
            get_object_or_404(record_model, pk=record_pk)
            if record_pk is not None
            else record_model(form=field.form)
        )

        render_context = {
            "search_term": search_term,
            "page": page,
            "per_page": per_page,
            "record": record,
            record_alias: record,
            **request.GET.dict(),
        }

        # Iterpolate the form_field_options using context from the current request.
        field_type_options = interpolate(
            field.field_type_options, context=render_context
        )

        return cls.get_results(
            request,
            field,
            search_term=search_term,
            page=page,
            per_page=per_page,
            record=(record if record.pk else None),
            **{
                # The record is also made available by a slugified version of
                # the record model's verbose_name for an improved developer
                # experience.
                record_alias: (record if record.pk else None),
                # Rendered form field options are also passed.
                **field_type_options,
            },
        )

    @classmethod
    def get_results(
        cls,
        request: HttpRequest,
        field: "BaseField",
        search_term: str,
        page: int,
        per_page: int,
        record: Optional["BaseRecord"],
        **field_type_options: Any,
    ) -> Tuple[Iterable[AutocompleteResult], bool]:
        """Perform a search and return paginated results.

        Should return an iterable of autocomplete-compatible results and a
        boolean indicating whether there are more results to be fetched via
        pagination.

        Args:
            request: The HTTP request.
            field: The BaseField instance.
            search_term: The term to search for.
            page: The pagination page number.
            per_page: The pagination page size.
            record: The record instance.
            field_type_options: The field's field_type_options after having
                its values interpolated.

        Raises:
            NotImplementedError: If the implementing class doesn't impement
                a get_results() method.
        """
        raise NotImplementedError(  # pragma: no cover
            f"All AutocompleteField types must implement get_results()."
        )


class URLAutocompleteSelectField(BaseAutocompleteSelectField):
    """A field for autocompleting selections from an HTTP endpoint."""

    label = "Autocomplete (URL)"

    @classmethod
    def get_results(
        cls,
        request: HttpRequest,
        field: "BaseField",
        search_term: str,
        page: int,
        per_page: int,
        record: Optional["BaseRecord"],
        **field_type_options: Any,
    ) -> Tuple[Iterable[AutocompleteResult], bool]:
        """Perform a search and return paginated results.

        Search is performed via a GET request to the configured URL.

        If the configured URL is path only (e.g., "/search?query={{term}}")
        and that path can be resolved to a view function in the application,
        the view function will be called directly with the current request
        object (modified with the new path and GET parameters).

        Args:
            request: The HTTP request.
            field: The BaseField instance.
            search_term: The term to search for.
            page: The pagination page number.
            per_page: The pagination page size.
            record: The record instance.
            field_type_options: The field's field_type_options after having
                its values interpolated.

        Returns:
            Tuple[Iterable[AutocompleteResult], bool]: An iterable of
                AutocompleteResult dicts, and a boolean indicating whether
                there are more results to be fetched via pagination.
        """
        results = cast(List[AutocompleteResult], [])
        has_more = False

        url: RenderedString = field_type_options["url"]

        if not url:
            logger.warning(
                f"The URL for field '{field}' was blank, and so no "
                f"autocomplete search could take place. This may be a "
                f"misconfiguration."
            )
            return results, has_more

        mapping = cast(
            AutocompleteResultMapping,
            {**cls.DEFAULT_RESULT_MAPPING, **field_type_options.get("mapping", {})},
        )
        search_manually: bool = "term" not in url.render_context

        # Get the JSON response from the endpoint.
        response_json = cls._get_json_response(request, url)

        # Parse the search response and map each result to a Select2-compatible
        # dict with an "id" and a "text" property.
        raw_results = jp(mapping["root"], response_json, [])
        for raw_result in raw_results:
            result_text = str(jp(mapping["text"], raw_result))
            result_value = jp(mapping["value"], raw_result, default=result_text)
            result_extra = {k: jp(v, raw_result) for k, v in mapping["extra"].items()}

            # If we're configured to search manually, skip results that don't
            # have the search term in the extracted text.
            if search_manually and search_term:
                if search_term.casefold() not in result_text.casefold():
                    continue

            mapped_result = {
                "text": result_text,
                "value": result_value,
                "extra": result_extra,
            }

            # The "id" is the value eventually stored in the database. In this
            # case, it is a stringified version of the result JSON so that it can
            # be deserialized when rendering the initial value for the widget.
            #
            # The use of "id" as opposed to "value" or something that makes
            # more semantic sense is to support the use of the select2
            # implementation that ships with the Django admin.
            mapped_result["id"] = stable_json(mapped_result)

            results.append(cast(AutocompleteResult, mapped_result))

        # If we're configured to paginate manually, then paginate.
        paginator = Paginator(results, per_page)
        paginated_page = paginator.page(page)
        results = cast(List[AutocompleteResult], paginated_page.object_list)
        has_more = paginated_page.has_next()

        return results, has_more

    @classmethod
    def _get_json_response(cls, request: HttpRequest, url: str) -> Any:
        """Make a request to the given URL and return the response JSON.

        Args:
            request: The current HttpRequest
            url: The URL to make a request to.

        Returns:
            Any: The JSON response body.
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
                    response.rendered_content
                    if hasattr(response, "rendered_content")
                    else response.content
                )

        # If we weren't able to call a local view to get our results, we'll
        # make a regular GET request to the URL instead.
        if response_json is None:
            response = requests.get(request.build_absolute_uri(url))
            response.raise_for_status()
            response_json = response.json()

        return response_json


class URLAutocompleteSelectMultipleField(URLAutocompleteSelectField):
    """An autocomplete field that supports multiple selections."""

    label = "Autocomplete Multiple (URL)"

    form_field_class = JSONFormField
    form_widget_class = AutocompleteSelectMultiple


class QuerysetAutocompleteSelectField(BaseAutocompleteSelectField):
    """An autocomplete field that sources options from a queryset."""

    label = "Autocomplete (QuerySet)"

    @classmethod
    def get_results(
        cls,
        request: HttpRequest,
        field: "BaseField",
        search_term: str,
        page: int,
        per_page: int,
        record: Optional["BaseRecord"],
        **field_type_options: Any,
    ) -> Tuple[Iterable[AutocompleteResult], bool]:
        """Perform a search and return paginated results.

        Search is performed with a QuerySet against the configured model
        using an __icontains filter. Each instance is JSONified to enable the
        configured mapping to use JMESPath expressions in its values.

        Args:
            request: The HTTP request.
            field: The BaseField instance.
            search_term: The term to search for.
            page: The pagination page number.
            per_page: The pagination page size.
            record: The record instance.
            field_type_options: The field's field_type_options after having
                its values interpolated.

        Returns:
            Tuple[Iterable[AutocompleteResult], bool]: An iterable of
                AutocompleteResult dicts, and a boolean indicating whether
                there are more results to be fetched via pagination.

        Raises:
            ImproperlyConfigured: If the configured search_field is not a
                concrete field on the configured model (i.e. the field
                doesn't exist or is a property method, etc).
        """
        results = cast(List[AutocompleteResult], [])
        has_more = False

        # Extract the relevant configuration from the form widget options.
        model_name: str = field_type_options["model"]
        filter: Dict[str, Any] = field_type_options.get("filter", {})
        exclude: Dict[str, Any] = field_type_options.get("exclude", {})
        mapping = cast(
            AutocompleteResultMapping,
            {**cls.DEFAULT_RESULT_MAPPING, **field_type_options.get("mapping", {})},
        )

        # Build a set of model field names used in the mapping values. This
        # will be used to transform the database records into JSON before
        # applying the mapping.
        expression_fields: Set[str] = set()
        for expr in (*mapping.values(), *mapping["extra"].values()):
            if not isinstance(expr, str):
                continue
            expression_fields.update(get_expression_fields(expr))

        # Resolve the model class from the Django registry and build a queryset
        # with the given parameters.
        model_cls = cast(Type[DjangoModel], apps.get_model(model_name))
        concrete_model_fields = frozenset(
            [*(f.name for f in model_cls._meta.concrete_fields), "pk"]
        )
        qs = (
            model_cls._default_manager.filter(**(filter or {}))
            .exclude(**(exclude or {}))
            .order_by("pk")
        )

        search_fields = field_type_options.get(
            "search_fields",
            # If no search_fields were configured explicitly, derive them from the
            # fields used in the "text" expression of the configured mapping.
            tuple(
                field_name
                for field_name in get_expression_fields(mapping["text"])
                if field_name in concrete_model_fields
            ),
        )

        # If any of the search_fields is not a concrete model field, it can't be
        # used to filter results.
        if any(f not in concrete_model_fields for f in search_fields):
            raise ImproperlyConfigured(
                f"The search_fields option for {cls.__name__} fields "
                f"must contain only the names of concrete model fields."
            )

        # If no fields were specified to search, log a warning.
        if not search_fields:  # pragma: no cover
            logger.warning(
                f"No search_fields were defined or discovered, and so the "
                f"{cls.__name__} field cannot filter results with a search "
                f"term."
            )

        # If a serch term is given, search for it using case-insensitive
        # queryset filters against any configured search_fields.
        if search_term and search_fields:
            # Look for a vendor-specific method for search, or use the fallback.
            search_method = getattr(
                cls, f"_search_{connections[qs.db].vendor}", cls._search_fallback
            )
            qs = search_method(qs, search_fields=search_fields, search_term=search_term)

        # Paginate the queryset before mapping, since we don't know how big the
        # queryset could be.
        paginator = Paginator(qs, per_page)
        paginated_page = paginator.page(page)
        raw_results = paginated_page.object_list
        has_more = paginated_page.has_next()

        # Parse the search response and map each result to a Select2-compatible
        # dict with an "id" and a "text" property.
        for instance in raw_results:
            # Create a JSON representation based on the fields used in the
            # mapping expressions so that the result can be mapped with
            # JMESPath.
            instance_json = {f: getattr(instance, f, None) for f in expression_fields}

            result_text = str(jp(mapping["text"], instance_json))
            result_value = jp(mapping["value"], instance_json, default=result_text)
            result_extra = {
                k: jp(v, instance_json) for k, v in mapping["extra"].items()
            }

            mapped_result = {
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
            mapped_result["id"] = stable_json(mapped_result)

            results.append(cast(AutocompleteResult, mapped_result))

        return results, has_more

    @classmethod
    def _search_postgresql(
        cls,
        queryset: "QuerySet[DjangoModel]",
        search_fields: Tuple[str, ...],
        search_term: str,
    ) -> "QuerySet[DjangoModel]":
        """Perform a search with a postgres backend.

        Uses postgresql-specific search strategies for better search results.

        Args:
            queryset: The queryset to filter with the given search parameters.
            search_fields: The names of the model fields to search.
            search_term: The term to search for.

        Returns:
            QuerySet[DjangoModel]: The filtered QuerySet.
        """
        return queryset.annotate(_search=SearchVector(*search_fields)).filter(
            _search=SearchQuery(search_term)
        )

    @classmethod
    def _search_fallback(
        cls,
        queryset: "QuerySet[DjangoModel]",
        search_fields: Tuple[str, ...],
        search_term: str,
    ) -> "QuerySet[DjangoModel]":
        """Perform a search with a generic backend.

        Args:
            queryset: The queryset to filter with the given search parameters.
            search_fields: The names of the model fields to search.
            search_term: The term to search for.

        Returns:
            QuerySet[DjangoModel]: The filtered QuerySet.
        """
        search_field = search_fields[0]

        # If there are multiple search_fields, concatenate their values and
        # search the resulting text blob.
        if len(search_fields) > 1:
            # Create a tuple containing each of the search_fields (cast to
            # TextField values), joined by spaces.
            search_domain_fields: Tuple[Union[Cast, Value], ...] = ()
            for field_name in search_fields:
                search_domain_fields = (
                    *search_domain_fields,
                    Cast(field_name, output_field=model_fields.TextField()),
                    Value(" "),
                )

            # Annotate the queryset with a _search attribute containing a
            # space-separated list of field values.
            queryset = queryset.annotate(
                _search=Concat(
                    *search_domain_fields, output_field=model_fields.TextField()
                )
            )

            # Instruct the queryset to search the concatenated field.
            search_field = "_search"

        return queryset.filter(**{f"{search_field}__icontains": search_term})


class QuerysetAutocompleteSelectMultipleField(QuerysetAutocompleteSelectField):
    """A queryset autocomplete field that supports multiple selections."""

    label = "Autocomplete Multiple (QuerySet)"
    form_widget_class = AutocompleteSelectMultiple
