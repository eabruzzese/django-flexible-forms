# -*- coding: utf-8 -*-

"""Field definitions for the flexible_forms module."""

import json
import logging
import urllib.parse as urlparse
from typing import (
    Set,
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
    Type,
    TypedDict,
    cast,
)

import requests
import simpleeval
from django.apps import apps
from django.core.paginator import Paginator
from django.db.models import FileField, ImageField
from django.db.models import Model as DjangoModel, QuerySet, fields as model_fields
from django.forms import fields as form_fields
from django.forms import widgets as form_widgets
from django.forms import model_to_dict
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
    def render_url(
        cls,
        request: HttpRequest,
        field: "BaseField",
        url: str,
        **form_widget_options: Any,
    ) -> Tuple[str, bool]:
        """Render the URL using DTL.

        Uses the record (if available) and the request's GET parameters as
        context when rendering.

        Args:
            request: The current HttpRequest.
            field: The BaseField instance.
            url: The url configured in the form_widget_options.
            form_widget_options: Options passed to the form widget.

        Returns:
            Tuple[str, bool]: The rendered URL and a flag indicating whether
                pagination was handled by the remote endpoint or not.
        """
        # Prevent a circular import.
        from flexible_forms.models import BaseRecord

        # If autocompletion was requested for a specific record, fetch it using
        # the given primary key. Otherwise, make a blank record.
        record_pk = request.GET.get("record_pk", None)
        record_model = field.flexible_forms.get_model(BaseRecord)
        record = (
            get_object_or_404(record_model, pk=record_pk)
            if record_pk is not None
            else record_model(form=field.form)
        )

        # Render the URL as a Django Template, feeding it the current field
        # values, the record instance ("meta"), and the GET parameters.
        url_template = Template(url)
        record_variable = (
            (record._meta.verbose_name or "record").lower().replace(" ", "_")
        )
        url_template_context = Context({record_variable: record, **request.GET.dict()})

        # Extract a list of variables referenced in the template.
        url_template_vars = frozenset(
            v.filter_expression.var.lookups[0]
            for v in url_template.nodelist
            if isinstance(v, VariableNode)
        )

        # If the "page" variable was used when rendering the URL, assume that
        # the remote endpoint has handled pagination already.
        paginated = "page" in url_template_vars
        filtered = "term" in url_template_vars

        return url_template.render(url_template_context), paginated, filtered

    @classmethod
    def get_response_json(
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

        # If we weren't able to call a local view tog et our results, we'll
        # make a regular GET request to the URL instead.
        if response_json is None:
            response = requests.get(request.build_absolute_uri(url))
            response.raise_for_status()
            response_json = response.json()

        return response_json

    @classmethod
    def extract_results(
        cls,
        request: HttpRequest,
        field: "BaseField",
        raw_results: Any,
        mapping: Optional[AutocompleteResultMapping] = None,
        search_field: Optional[str] = None,
        search_manually: bool = True,
        **form_widget_options: Any,
    ) -> List[AutocompleteResult]:
        """Extract a list of autocomplete results from the given response JSON.

        Args:
            request: The current HttpRequest.
            field: The BaseField instance.
            raw_results: The raw JSON received from requesting the configured URL.
            mapping: A mapping of key -> jmespath expression used to
                translate each result from the URL response into an
                autocomplete result.
            form_widget_options: The form_widget_options configured for the field.

        Returns:
            List[AutocompleteResults]: A list of Select2-compatible autocomplete results.
        """
        results = []

        # Define a default result mapping and merge the configured mapping into
        # it, if given.
        mapping = cast(
            AutocompleteResultMapping,
            {
                **cls.DEFAULT_RESULT_MAPPING,
                **(mapping or {}),
            },
        )

        search_term = request.GET.get("query", "")

        # Parse the search response and map each result to a Select2-compatible
        # dict with an "id" and a "text" property.
        raw_results = jp(mapping["root"], raw_results) or []
        for result in raw_results:
            result_text = jp(mapping["text"], result)

            # Exclude any results that don't contain the search term.
            if search_manually:
                searchable_text = str(
                    result[search_field] if search_field else result_text
                )
                if search_term.casefold() not in searchable_text.casefold():
                    continue

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

    @classmethod
    def paginate_results(
        cls,
        request: HttpRequest,
        field: "BaseField",
        results: List[AutocompleteResult],
        paginate_manually: bool = True,
        **form_widget_options: Any,
    ) -> Tuple[List[AutocompleteResult], bool]:
        """Paginate the given list of autocomplete results.

        If paginate is True, uses Django's pagination tools to slice the result.

        Args:
            request: The current HttpRequest.
            field: The BaseField instance.
            results: The autocomplete results extracted from the call to the configured URL.
            paginate: When True, paginates the result set. Otherwise assumes
                that pagination has been handled already.
            form_widget_options: The form_widget_options configured for the field.

        Returns:
            List[AutocompleteResults]: A list of Select2-compatible autocomplete results.
        """
        # Extract pagination info from the request.
        page = int(request.GET.get("page", "1"))
        per_page = int(request.GET.get("per_page", "100"))

        # If the remote endpoint isn't handling pagination, do it manually.
        if paginate_manually:
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

    @classmethod
    def autocomplete(
        cls,
        request: HttpRequest,
        field: "BaseField",
        url: Optional[str] = "",
        **form_widget_options: Any,
    ) -> Tuple[List[AutocompleteResult], bool]:
        """Perform a search against the configured URL.

        Returns a sequence of dicts, each with "id" and "text" values to use
        within a select form element.

        Args:
            request: The HTTP request.
            field: The Field record instance that uses this autocomplete.
            url: The URL from which to retrieve autocomplete results.
            form_widget_options: A dict of form widget options that can be
                used to customize autocomplete behavior.

        Returns:
            Tuple[Sequence[AutocompleteResult], bool]: A two-tuple containing
                a sequence of zero or more select2-compatible search results, and
                a boolean indicating whether or not there are more results to
                fetch.
        """
        # Initialize results with an empty list.
        results: List[AutocompleteResult] = []
        has_more = False

        # If no URL has been configured, return results as-is.
        if not url:
            return results, has_more

        rendered_url, paginated, filtered = cls.render_url(
            request, field, url, **form_widget_options
        )
        response_json = cls.get_response_json(
            request, field, rendered_url, **form_widget_options
        )
        results = cls.extract_results(
            request,
            field,
            response_json,
            search_manually=not filtered,
            **form_widget_options,
        )

        return cls.paginate_results(
            request,
            field,
            results,
            paginate_manually=not paginated,
            **form_widget_options,
        )


class AutocompleteSelectMultipleField(AutocompleteSelectField):
    """An autocomplete field that supports multiple selections."""

    form_field_class = JSONFormField
    form_widget_class = AutocompleteSelectMultiple


class QuerysetAutocompleteSelectField(AutocompleteSelectField):
    """An autocomplete field that sources options from a configured queryset."""

    @classmethod
    def extract_results(
        cls,
        request: HttpRequest,
        field: "BaseField",
        raw_results: "QuerySet[DjangoModel]",
        mapping: Optional[AutocompleteResultMapping],
        search_field: Optional[str] = None,
        search_manually: bool = False,
        **form_widget_options: Any,
    ) -> List[AutocompleteResult]:
        mapping = {**cls.DEFAULT_RESULT_MAPPING, **(mapping or {}), "root": "@"}

        # Build a list of model fields referenced in the mapping expressions.
        expression_fields = set()
        for expr in (*mapping.values(), *mapping["extra"].values()):
            if not isinstance(expr, str):
                continue
            expression_fields.update(get_expression_fields(expr))

        # Map the model instances to dicts so they can be used with JMESPath.
        json_results = [
            {f: getattr(instance, f, None) for f in expression_fields}
            for instance in raw_results.all()
        ]

        return super().extract_results(
            request,
            field,
            raw_results=json_results,
            mapping=mapping,
            search_field=search_field,
            search_manually=search_manually,
            **form_widget_options,
        )

    @classmethod
    def autocomplete(
        cls,
        request: HttpRequest,
        field: "BaseField",
        model: str,
        filter: Optional[Dict[str, Any]] = None,
        exclude: Optional[Dict[str, Any]] = None,
        mapping: Optional[AutocompleteResultMapping] = None,
        search_field: Optional[str] = None,
        **form_widget_options: Any,
    ) -> Tuple[List[AutocompleteResult], bool]:
        # Build the queryset from the configured parameters.
        model_cls = cast(DjangoModel, apps.get_model(model))
        qs = (
            model_cls._default_manager.filter(**(filter or {}))
            .exclude(**(exclude or {}))
            .order_by("pk")
        )

        # If the field is configured with a search_field, use it to filter results.
        search_term = request.GET.get("term")
        if search_term and search_field:
            qs = qs.filter(**{f"{search_field}__icontains": search_term})

        # Paginate the results first (to allow Django's paginator to work with the QuerySet).
        results, has_more = cls.paginate_results(
            request, field, results=qs, paginate_manually=True, **form_widget_options
        )

        # Map the results to options using the given mapping.
        results = cls.extract_results(
            request,
            field,
            raw_results=results,
            mapping={
                **(mapping or {}),
                "root": "@",
            },
            search=False,
        )

        return results, has_more


class QuerysetAutocompleteSelectMultipleField(QuerysetAutocompleteSelectField):
    """A queryset autocomplete field that supports multiple selections."""

    form_field_class = JSONFormField
    form_widget_class = AutocompleteSelectMultiple
