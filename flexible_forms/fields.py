# -*- coding: utf-8 -*-

"""Field definitions for the flexible_forms module."""

from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Optional,
    Tuple,
    Type,
    Union,
    cast
)

from django.db.models import Field, FileField, ImageField, Model
from django.db.models import fields as model_fields
from django.forms import fields as form_fields
from django.forms import widgets as form_widgets

try:
    from django.db.models import JSONField
except ImportError:
    from django.contrib.postgres.fields import JSONField

from .utils import all_subclasses

##
# _EMPTY_CHOICES
_EMPTY_CHOICES = (
    ('EMPTY', 'Select a value.'),
)


class FlexibleField:
    """A prefabricated field to use with flexible forms.

    Provides an interface to emit a model field, form field, or widget.
    """

    ##
    # key
    #
    # The machine-friendly key of the field type, e.g. "SINGLE_LINE_TEXT".
    #
    key: str = ''

    ##
    # label
    #
    # The human-friendly key of the field type, e.g. "Single-line Text".
    #
    label: str = ''

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
    def as_form_field(cls, **kwargs: Any) -> form_fields.Field:
        """Return an instance of the field for use in a Django form.

        Receives a dict of kwargs to pass through to the form field constructor.

        Args:
            kwargs (Any): A dict of kwargs to be passed to the constructor of the
                `form_field_class`.

        Returns:
            form_fields.Field: An instance of the form field.
        """
        if cls.form_widget_class:
            kwargs['widget'] = cls.form_widget_class(**{
                **cls.form_widget_options,
                **kwargs.pop('form_widget_options', {})
            })

        return cls.form_field_class(**{
            **cls.form_field_options,
            **kwargs,
        })

    @classmethod
    def as_model_field(cls, **kwargs: Any) -> model_fields.Field:
        """Return an instance of the field for use in a Django model.

        Receives a dict of kwargs to pass through to the model field constructor.

        Args:
            kwargs (Any): A dict of kwargs to be passed to the constructor of the
                `model_field_class`.

        Returns:
            model_fields.Field: An instance of the model field.
        """
        return cls.model_field_class(**{
            **cls.model_field_options,
            **kwargs,
        })


class SingleLineTextField(FlexibleField):
    """A field for collecting single-line text values."""

    key = 'SINGLE_LINE_TEXT'
    label = 'Single-line Text'

    form_field_class = form_fields.CharField
    model_field_class = model_fields.TextField


class MultiLineTextField(FlexibleField):
    """A field for collecting multiline text values."""

    key = 'MULTI_LINE_TEXT'
    label = 'Multi-line Text'

    form_field_class = form_fields.CharField
    form_widget_class = form_widgets.Textarea
    model_field_class = model_fields.TextField


class EmailField(FlexibleField):
    """A field for collecting email addresses."""

    key = 'EMAIL'
    label = 'Email Address'

    form_field_class = form_fields.EmailField
    model_field_class = model_fields.EmailField


class URLField(FlexibleField):
    """A field for collecting URL values."""

    key = 'URL'
    label = 'URL'

    form_field_class = form_fields.URLField
    model_field_class = model_fields.URLField
    model_field_options = {'max_length': 2083}


class SensitiveTextField(FlexibleField):
    """A field for collecting sensitive text values.

    Primarily useful for obfuscating the input when on-screen.
    """

    key = 'SENSITIVE'
    label = 'Sensitive text'

    form_field_class = form_fields.CharField
    form_widget_class = form_widgets.PasswordInput
    model_field_class = model_fields.TextField


class IntegerField(FlexibleField):
    """A field for collecting integer values."""

    key = 'INTEGER'
    label = 'Integer'

    form_field_class = form_fields.IntegerField
    form_field_options = {'min_value': -2147483648, 'max_value': 2147483647}
    model_field_class = model_fields.IntegerField


class PositiveIntegerField(FlexibleField):
    """A field for collecting positive integer values."""

    key = 'POSITIVE_INTEGER'
    label = 'Positive Integer'

    form_field_class = form_fields.IntegerField
    form_field_options = {'min_value': 0, 'max_value': 2147483647}
    model_field_class = model_fields.PositiveIntegerField


class DecimalField(FlexibleField):
    """A field for collecting decimal number values."""

    key = 'DECIMAL'
    label = 'Decimal Number'

    form_field_class = form_fields.DecimalField
    form_field_options = {'max_digits': 15, 'decimal_places': 6}
    model_field_class = model_fields.DecimalField
    model_field_options = {'max_digits': 15, 'decimal_places': 6}


class DateField(FlexibleField):
    """A field for collecting date data."""

    key = 'DATE'
    label = 'Date'

    form_field_class = form_fields.DateField
    model_field_class = model_fields.DateField


class TimeField(FlexibleField):
    """A field for collecting time data."""

    key = 'TIME'
    label = 'Time'

    form_field_class = form_fields.TimeField
    model_field_class = model_fields.TimeField


class DateTimeField(FlexibleField):
    """A field for collecting datetime data."""

    key = 'DATETIME'
    label = 'Date & Time'

    form_field_class = form_fields.DateTimeField
    model_field_class = model_fields.DateTimeField


class DurationField(FlexibleField):
    """A field for collecting duration data."""

    key = 'DURATION'
    label = 'Duration'

    form_field_class = form_fields.DurationField
    model_field_class = model_fields.DurationField


class CheckboxField(FlexibleField):
    """A field for collecting a boolean value with a checkbox."""

    key = 'CHECKBOX'
    label = 'Checkbox'

    form_field_class = form_fields.BooleanField
    form_widget_class = form_widgets.CheckboxInput
    model_field_class = model_fields.BooleanField


class YesNoRadioField(FlexibleField):
    """A field for collecting a boolean value with a yes/no radio button set."""

    key = 'YES_NO_RADIO'
    label = 'Yes/No Radio Buttons'

    form_field_class = form_fields.TypedChoiceField
    form_field_options = {
        'choices': (
            ('Yes', True),
            ('No', False),
        ),
        'coerce': bool
    }
    form_widget_class = form_widgets.RadioSelect
    model_field_class = model_fields.BooleanField


class YesNoUnknownRadioField(FlexibleField):
    """A field for collecting a null-boolean value with a yes/no/unknown radio button set."""

    key = 'YES_NO_UNKNOWN_RADIO'
    label = 'Yes/No/Unknown Radio Buttons'

    form_field_class = form_fields.NullBooleanField
    form_widget_class = form_widgets.RadioSelect
    model_field_class = model_fields.BooleanField
    model_field_options = {'null': True}


class YesNoSelectField(FlexibleField):
    """A field for collecting a boolean value with a yes/no select field."""

    key = 'YES_NO_SELECT'
    label = 'Yes/No Dropdown'

    form_field_class = form_fields.TypedChoiceField
    form_field_options = {
        'choices': (
            ('Yes', True),
            ('No', False),
        ),
        'coerce': bool
    }
    form_widget_class = form_widgets.Select
    model_field_class = model_fields.BooleanField


class YesNoUnknownSelectField(FlexibleField):
    """A field for collecting a boolean value with a yes/no select field."""

    key = 'YES_NO_SELECT'
    label = 'Yes/No/Unknown Dropdown'

    form_field_class = form_fields.NullBooleanField
    model_field_class = model_fields.BooleanField
    model_field_options = {'null': True}


class SingleChoiceSelectField(FlexibleField):
    """A field for collecting a single text value from a select list."""

    key = 'SINGLE_CHOICE_SELECT'
    label = 'Single-choice Dropdown'

    form_field_class = form_fields.ChoiceField
    form_field_options = {'choices': _EMPTY_CHOICES}
    model_field_class = model_fields.TextField


class SingleChoiceRadioSelectField(FlexibleField):
    """A field for collecting a text value from a set of radio buttons."""

    key = 'SINGLE_CHOICE_RADIO_SELECT'
    label = 'Radio Buttons'

    form_field_class = form_fields.ChoiceField
    form_field_options = {'choices': _EMPTY_CHOICES}
    form_widget_class = form_widgets.RadioSelect
    model_field_class = model_fields.TextField


class MultipleChoiceSelectField(FlexibleField):
    """A field for collecting multiple text values from a select list."""

    key = 'MULTIPLE_CHOICE_SELECT'
    label = 'Multiple-choice Dropdown'

    form_field_class = form_fields.MultipleChoiceField
    form_field_options = {'choices': _EMPTY_CHOICES}
    model_field_class = JSONField


class MultipleChoiceCheckboxField(FlexibleField):
    """A field for collecting multiple text values from a checkbox list."""

    key = 'MULTIPLE_CHOICE_CHECKBOX'
    label = 'Multiple-choice Checkboxes'

    form_field_class = form_fields.MultipleChoiceField
    form_field_options = {'choices': _EMPTY_CHOICES}
    form_widget_class = form_widgets.CheckboxSelectMultiple
    model_field_class = JSONField


class FileUploadField(FlexibleField):
    """A field for collecting file uploads."""

    key = 'FILE_UPLOAD'
    label = 'File Upload'

    form_field_class = form_fields.FileField
    model_field_class = FileField


class ImageUploadField(FlexibleField):
    """A field for collecting image uploads."""

    key = 'IMAGE_UPLOAD'
    label = 'Image Upload'

    form_field_class = form_fields.ImageField
    model_field_class = ImageField


##
# FIELDS_BY_KEY
#
# A dict mapping of field types, where the key is the `key` attribute of the
# `FlexibleField` class, and the value is the `FlexibleField` class itself.
#
# Built dynamically to include all descendants of `FlexibleField`.
#
FIELDS_BY_KEY: Dict[str, Type[FlexibleField]] = {
    f.key: f for f in all_subclasses(FlexibleField)}


class ValueRouter:
    """Injects a field into a model for each type specified.

    Overrides the `value` getter and setter to route to the appropriate field.

    For example, this model:

    class MyModel(models.Model):
        value = ValueRouter(
            types=(
                models.TextField(),
                models.DecimalField(max_digits=19, decimal_places=10)
            )
        )

    Will be rendered equivalent to:

    class MyModel(models.Model):
        # A field for storing the name of the field where the value can be found.
        _value_field = models.CharField(
            choices=(
                ('_textfield_value', 'TextField'),
                ('_decimalfield_value', 'DecimalField'),
            )
        )

        # A field for each distinct type of value.
        _textfield_value = models.TextField(blank=True, null=True)
        _decimalfield_value = models.DecimalField(
            blank=True, null=True, max_digits=19, decimal_places=10)

        @property
        def value(self) -> Union[str, Decimal]:
            return getattr(self, self._value_field)

        @value.setter
        def value(self, value) -> None:
            setattr(self, self._value_field, value)
    """

    def __init__(self, types: Iterable[Field]):
        """Configure the ValueRouter.

        Args:
            types (Iterable[Field]): An iterable of model field
                instances that the ValueRouter should support.
        """
        self._types = frozenset(types)

    def contribute_to_class(self, cls: Type[Model], name: str) -> None:
        """Add model fields based on what is supported by dynamic forms.

        Args:
            cls: The class to be modified.
            name: The name of the attribute that ValueRouter is assigned to.
        """
        value_fields = {
            f'_{t.__class__.__name__.lower()}_value': t
            for t in self._types
        }

        # Add fields for storing each type of field value, and add them
        # to the list of supported value fields.
        value_field_choices: List[Tuple[str, str]] = []
        for field_name, field in value_fields.items():
            # All value fields must be nullable, regardless of type.
            field.blank = True
            field.null = True

            # All fields should default to null so that it's easy to
            # identify which field should be canonical.
            field.default = None

            # Add the field to the class.
            cls.add_to_class(field_name, field)  # type: ignore

            # Add the field to the list of field type choices.
            value_field_choices.append(
                (field_name, str(field.__class__.__name__),
                 ))

        # Add a _value_field field to help with routing.
        cls.add_to_class(f'_{name}_field', model_fields.CharField(  # type: ignore
            choices=sorted(value_field_choices),
            max_length=len(max(dict(value_field_choices).keys(), key=len)),
            default=''
        ))

        def _value_type_getter(model: Model) -> str:
            return str(getattr(model, f'_{name}_field'))

        def _value_type_setter(model: Model, field_type: Union[Field, Type[Field]]) -> None:
            value_field_name = f'_' + (
                field_type.__class__.__name__
                if isinstance(field_type, Field)
                else field_type.__name__
            ).lower() + '_value'

            setattr(model, f'_{name}_field', value_field_name)

        # Add a set_type method to the class.
        cls.add_to_class(  # type: ignore
            f'{name}_type',
            property(fget=_value_type_getter, fset=_value_type_setter)
        )

        def _value_getter(model: Model) -> Any:
            """Get the value from the appropriate value field."""
            if not model._value_field:  # type: ignore
                raise KeyError('The model does not have a _value_field set.')
            return getattr(model, model._value_field)  # type: ignore

        def _value_setter(model: Model, value: Any) -> None:
            """Set the appropriate value field to the given value.

            Args:
                model (Model): The model instance on which to set the value.
                value (Any): The value to set.
            """
            if not model._value_field:  # type: ignore
                raise KeyError('The model does not have a _value_field set.')

            # Nullify other values before setting the new one (for safety).
            for field_name in value_fields.keys():
                setattr(model, field_name, None)

            setattr(model, model._value_field, value)  # type: ignore

        # Add a property for accessing the appropriate field.
        cls.add_to_class(name, property(fget=_value_getter,
                                        fset=_value_setter))  # type: ignore
