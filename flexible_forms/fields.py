# -*- coding: utf-8 -*-

"""Field definitions for the flexible_forms module."""

from typing import Any, Dict, Mapping, Optional, Sequence, Tuple, Type

import simpleeval
from django.db.models import FileField, ImageField
from django.db.models import fields as model_fields
from django.forms import fields as form_fields
from django.forms import widgets as form_widgets

try:
    from django.db.models import JSONField  # type: ignore
except ImportError:  # pragma: no cover
    from django.contrib.postgres.fields import JSONField

from .utils import all_subclasses, evaluate_expression

##
# _EMPTY_CHOICES
_EMPTY_CHOICES = (("EMPTY", "Select a value."),)


class FlexibleField:
    """A prefabricated field to use with flexible forms.

    Provides an interface to emit a model field, form field, or widget.
    """

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
    def name(cls) -> str:
        """Return the string representation of the field type.

        Useful for creating a type lookup, or for storing in the database.

        Returns:
            str: The string representation of the field type.
        """
        return cls.__name__

    @classmethod
    def as_form_field(
        cls,
        modifiers: Sequence[Tuple[str, str]] = (),
        field_values: Optional[Mapping[str, Optional[Any]]] = None,
        form_widget_options: Optional[Mapping[str, Optional[Any]]] = None,
        **kwargs: Any,
    ) -> form_fields.Field:
        """Return an instance of the field for use in a Django form.

        Receives a dict of kwargs to pass through to the form field constructor.

        Args:
            modifiers: A sequence of modifiers to
                be applied to the field.
            field_values: A mapping of the
                current form values.
            form_widget_options: A mapping of
                options to pass to the widget constructor if a widget is
                configured.
            kwargs: A dict of kwargs to be passed to the constructor of the
                `form_field_class`.

        Returns:
            form_fields.Field: An instance of the form field.
        """
        # If a form widget is explicitly configured, use it.
        if cls.form_widget_class:
            kwargs["widget"] = cls.form_widget_class(
                **{
                    **cls.form_widget_options,
                    **(form_widget_options or {}),
                }
            )

        # Generate the form field class.
        form_field = cls.form_field_class(
            **{
                **cls.form_field_options,
                **kwargs,
            }
        )

        # Apply any modifiers to the field.
        form_field = cls.apply_modifiers(
            form_field=form_field,
            modifiers=modifiers,
            field_values=field_values,
        )

        # Any fields with "None" as an option in their choices can never be
        # required.
        if any(c[0] is None for c in getattr(form_field, "choices", [])):
            form_field.required = False

        return form_field

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
                    **getattr(form_field, "_applied_modifiers", {}),
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


class SingleLineTextField(FlexibleField):
    """A field for collecting single-line text values."""

    label = "Single-line Text"

    form_field_class = form_fields.CharField
    model_field_class = model_fields.TextField


class MultiLineTextField(FlexibleField):
    """A field for collecting multiline text values."""

    label = "Multi-line Text"

    form_field_class = form_fields.CharField
    form_widget_class = form_widgets.Textarea
    model_field_class = model_fields.TextField


class EmailField(FlexibleField):
    """A field for collecting email addresses."""

    label = "Email Address"

    form_field_class = form_fields.EmailField
    model_field_class = model_fields.EmailField


class URLField(FlexibleField):
    """A field for collecting URL values."""

    label = "URL"

    form_field_class = form_fields.URLField
    model_field_class = model_fields.URLField
    model_field_options = {"max_length": 2083}


class SensitiveTextField(FlexibleField):
    """A field for collecting sensitive text values.

    Primarily useful for obfuscating the input when on-screen.
    """

    label = "Sensitive text"

    form_field_class = form_fields.CharField
    form_widget_class = form_widgets.PasswordInput
    model_field_class = model_fields.TextField


class IntegerField(FlexibleField):
    """A field for collecting integer values."""

    label = "Integer"

    form_field_class = form_fields.IntegerField
    form_field_options = {"min_value": -2147483648, "max_value": 2147483647}
    model_field_class = model_fields.IntegerField


class PositiveIntegerField(FlexibleField):
    """A field for collecting positive integer values."""

    label = "Positive Integer"

    form_field_class = form_fields.IntegerField
    form_field_options = {"min_value": 0, "max_value": 2147483647}
    model_field_class = model_fields.PositiveIntegerField


class DecimalField(FlexibleField):
    """A field for collecting decimal number values."""

    label = "Decimal Number"

    form_field_class = form_fields.DecimalField
    form_field_options = {"max_digits": 15, "decimal_places": 6}
    model_field_class = model_fields.DecimalField
    model_field_options = {"max_digits": 15, "decimal_places": 6}


class DateField(FlexibleField):
    """A field for collecting date data."""

    label = "Date"

    form_field_class = form_fields.DateField
    model_field_class = model_fields.DateField


class TimeField(FlexibleField):
    """A field for collecting time data."""

    label = "Time"

    form_field_class = form_fields.TimeField
    model_field_class = model_fields.TimeField


class DateTimeField(FlexibleField):
    """A field for collecting datetime data."""

    label = "Date & Time"

    form_field_class = form_fields.DateTimeField
    model_field_class = model_fields.DateTimeField


class DurationField(FlexibleField):
    """A field for collecting duration data."""

    label = "Duration"

    form_field_class = form_fields.DurationField
    model_field_class = model_fields.DurationField


class CheckboxField(FlexibleField):
    """A field for collecting a boolean value with a checkbox."""

    label = "Checkbox"

    form_field_class = form_fields.BooleanField
    form_widget_class = form_widgets.CheckboxInput
    model_field_class = model_fields.BooleanField


class YesNoRadioField(FlexibleField):
    """A field for collecting a yes/no value with radio buttons."""

    label = "Yes/No Radio Buttons"

    form_field_class = form_fields.TypedChoiceField
    form_field_options = {
        "choices": (
            (True, "Yes"),
            (False, "No"),
        ),
        "coerce": lambda v: True if v in ("True", True) else False,
    }
    form_widget_class = form_widgets.RadioSelect
    model_field_class = model_fields.BooleanField


class YesNoUnknownRadioField(FlexibleField):
    """A field for collecting a yes/no/unknown value with radio buttons."""

    label = "Yes/No/Unknown Radio Buttons"

    form_field_class = form_fields.TypedChoiceField
    form_field_options = {
        "choices": (
            (True, "Yes"),
            (False, "No"),
            (None, "Unknown"),
        ),
        "coerce": lambda v: (
            True if v in ("True", True) else False if v in ("False", False) else None
        ),
    }
    form_widget_class = form_widgets.RadioSelect
    model_field_class = model_fields.BooleanField
    model_field_options = {"null": True}


class YesNoSelectField(FlexibleField):
    """A field for collecting a boolean value with a yes/no select field."""

    label = "Yes/No Dropdown"

    form_field_class = form_fields.TypedChoiceField
    form_field_options = {
        "choices": (
            (True, "Yes"),
            (False, "No"),
        ),
        "coerce": lambda v: True if v in ("True", True) else False,
    }
    form_widget_class = form_widgets.Select
    model_field_class = model_fields.BooleanField


class YesNoUnknownSelectField(FlexibleField):
    """A field for collecting a boolean value with a yes/no select field."""

    label = "Yes/No/Unknown Dropdown"

    form_field_class = form_fields.TypedChoiceField
    form_field_options = {
        "choices": (
            (True, "Yes"),
            (False, "No"),
            (None, "Unknown"),
        ),
        "coerce": lambda v: (
            True if v in ("True", True) else False if v in ("False", False) else None
        ),
    }
    model_field_class = model_fields.BooleanField
    model_field_options = {"null": True}


class SingleChoiceSelectField(FlexibleField):
    """A field for collecting a single text value from a select list."""

    label = "Single-choice Dropdown"

    form_field_class = form_fields.ChoiceField
    form_field_options = {"choices": _EMPTY_CHOICES}
    model_field_class = model_fields.TextField


class SingleChoiceRadioSelectField(FlexibleField):
    """A field for collecting a text value from a set of radio buttons."""

    label = "Radio Buttons"

    form_field_class = form_fields.ChoiceField
    form_field_options = {"choices": _EMPTY_CHOICES}
    form_widget_class = form_widgets.RadioSelect
    model_field_class = model_fields.TextField


class MultipleChoiceSelectField(FlexibleField):
    """A field for collecting multiple text values from a select list."""

    label = "Multiple-choice Dropdown"

    form_field_class = form_fields.MultipleChoiceField
    form_field_options = {"choices": _EMPTY_CHOICES}
    model_field_class = JSONField


class MultipleChoiceCheckboxField(FlexibleField):
    """A field for collecting multiple text values from a checkbox list."""

    label = "Multiple-choice Checkboxes"

    form_field_class = form_fields.MultipleChoiceField
    form_field_options = {"choices": _EMPTY_CHOICES}
    form_widget_class = form_widgets.CheckboxSelectMultiple
    model_field_class = JSONField


class FileUploadField(FlexibleField):
    """A field for collecting file uploads."""

    label = "File Upload"

    form_field_class = form_fields.FileField
    model_field_class = FileField


class ImageUploadField(FlexibleField):
    """A field for collecting image uploads."""

    label = "Image Upload"

    form_field_class = form_fields.ImageField
    model_field_class = ImageField


##
# FIELD_TYPES
#
# A dict mapping of field types, where the key is the string representation of
# the field type (usually its class name), and the value is the `FlexibleField`
# class itself.
#
# Built dynamically to include all descendants of `FlexibleField`.
#
FIELD_TYPES: Dict[str, Type[FlexibleField]] = {
    f.name(): f for f in all_subclasses(FlexibleField)
}
