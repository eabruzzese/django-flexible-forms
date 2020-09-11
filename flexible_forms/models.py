# -*- coding: utf-8 -*-

"""Model definitions for the flexible_forms module."""

import logging

from collections import defaultdict
from typing import Mapping, Optional, TYPE_CHECKING, Any, Dict, Tuple
from django.core.files.base import File
from django.utils.functional import cached_property

import swapper
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django import forms
from django.utils.text import slugify

from flexible_forms.fields import FIELDS_BY_KEY

try:
    from django.db.models import JSONField
except ImportError:
    from django.contrib.postgres.fields import JSONField

# If we're only type checking, import things that would otherwise cause an
# ImportError due to circular dependencies.
if TYPE_CHECKING:
    from flexible_forms.forms import RecordForm


logger = logging.getLogger(__name__)


##
# FIELD_TYPE_OPTIONS
#
# A choice-field-friendly list of all available field types. Sorted for
# migration stability.
#
FIELD_TYPE_OPTIONS = sorted(
    ((k, v.label) for k, v in FIELDS_BY_KEY.items()),
    key=lambda o: o[0]
)


class BaseForm(models.Model):
    """A model representing a single type of customizable form."""

    label = models.TextField(
        blank=True, default='', help_text='The human-friendly name of the form.')
    machine_name = models.TextField(
        blank=True,
        help_text=(
            'The machine-friendly name of the form. Computed automatically '
            'from the label if not specified.'
        ),
    )
    description = models.TextField(blank=True, default='')

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return str(self.label)

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Save the model.

        Sets the machine_name if not specified.

        Args:
            args: (Passed to super)
            kwargs: (Passed to super)
        """
        self.machine_name = (
            self.machine_name or slugify(self.label).replace('-', '_')
        )

        super().save(*args, **kwargs)

    def as_django_form(
        self,
        data: Optional[Mapping[str, Any]] = None,
        files: Optional[Mapping[str, File]] = None,
        instance: Optional['Record'] = None,
        **kwargs: Any
    ) -> 'RecordForm':
        """Return the form represented as a Django form instance.

        Args:
            data (Optional[Mapping[str, Any]]): Data to be passed to the
                Django form constructor.
            files (Optional[Mapping[str, File]]): Data to be passed to the
                Django form constructor.
            instance (Optional[Record]): The Record instance to be passed to
                the Django form constructor.

        Returns:
            RecordForm: A configured RecordForm (a Django ModelForm instance).
        """
        data = data or {}
        files = files or {}
        instance_data = instance.data if instance else {}

        # The RecordForm is imported inline to prevent a circular import.
        from flexible_forms.forms import RecordForm

        class_name = self.machine_name.title().replace('_', '')
        form_class_name = f'{class_name}Form'
        all_fields = self.fields.all()
        field_values = {
            **instance_data,
            **({k: data.get(k) for k in data.keys()}),
            **({k: files.get(k) for k in files.keys()}),
        }

        # Generate the initial list of fields that comprise the form.
        form_fields = {
            f.machine_name: f.as_form_field() for f in all_fields
        }

        # Normalize the field values to ensure they are all cast to their
        # appropriate types (as defined by their corresponding form fields).
        for field_name, form_field in form_fields.items():
            field_value = field_values.get(field_name)
            field_values[field_name] = form_field.to_python(field_value)

        # Regenerate the form fields, this time taking the field values into
        # account in order to inform any dynamic behaviors.
        form_fields = {
            f.machine_name: f.as_form_field(field_values=field_values) for f in all_fields
        }

        # Dynamically generate a form class containing all of the fields.
        form_class = type(form_class_name, (RecordForm,), {
            '__module__': self.__module__,
            **form_fields
        })

        # Create a form instance from the form class and the passed parameters.
        form_instance = form_class(
            data=data, files=files, instance=instance, **kwargs)

        return form_instance


class Form(BaseForm):
    """A swappable concrete implementation of a flexible form."""

    class Meta:
        swappable = swapper.swappable_setting('flexible_forms', 'Form')


class BaseField(models.Model):
    """A field on a form.

    A field belonging to a Form. Attempts to emulate a subset of
    Django's Field interface for that forms can be built dynamically.
    """

    label = models.TextField(
        help_text='The label to be displayed for this field in the form.',
    )

    machine_name = models.TextField(
        blank=True,
        help_text=(
            'The machine-friendly name of the field. Computed automatically '
            'from the label if not specified.'
        ),
    )

    label_suffix = models.TextField(
        blank=True,
        default='',
        help_text=(
            'The character(s) at the end of the field label (e.g. "?" or ":").'
        ),
    )

    help_text = models.TextField(
        blank=True,
        default='',
        help_text='Text to help the user fill out the field.',
    )

    required = models.BooleanField(
        default=False,
        help_text='If True, requires a value be present in the field.',
    )

    initial = models.TextField(
        blank=True,
        default='',
        help_text=(
            'The default value if no value is given during initialization.'
        ),
    )

    field_type = models.TextField(
        choices=FIELD_TYPE_OPTIONS,
        help_text='The form widget to use when displaying the field.',
    )

    model_field_options = JSONField(
        blank=True,
        default=dict,
        help_text='Custom arguments passed to the model field constructor.',
        encoder=DjangoJSONEncoder
    )

    form_field_options = JSONField(
        blank=True,
        default=dict,
        help_text='Custom arguments passed to the form field constructor.',
        encoder=DjangoJSONEncoder
    )

    form_widget_options = JSONField(
        blank=True,
        default=dict,
        help_text='Custom arguments passed to the form widget constructor.',
        encoder=DjangoJSONEncoder
    )

    form = models.ForeignKey(
        swapper.get_model_name('flexible_forms', 'Form'),
        on_delete=models.CASCADE,
        related_name='fields',
        editable=False,
    )

    ##
    # Ephemeral attributes.
    #
    # While a Field instance is being rendered into a Django form field, it may
    # hold additional information to assist in that rendering. For example, a
    # particular field might be "hidden" or "readonly" based on some criteria
    # while the field is being rendered.
    #
    # These ephemeral attributes are declared here to assist with typing and
    # reduce opacity into this process.
    #
    hidden: bool = False
    readonly: bool = False

    class Meta:
        abstract = True
        unique_together = ('form', 'machine_name')
        order_with_respect_to = 'form'

    def __str__(self) -> str:
        return f'Field `{self.label}` (type {self.field_type}, form ID {self.form_id})'

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Save the model.

        Sets the machine name if not specified, and ensures that the related
        form is the same as the form that the section belongs to.

        Args:
            args: (Passed to super)
            kwargs: (Passed to super)
        """
        self.machine_name = (
            self.machine_name or slugify(self.label).replace('-', '_')
        )

        super().save(*args, **kwargs)

    def as_form_field(self, field_values: Optional[Mapping[str, Any]] = None) -> forms.Field:
        """Return a Django form Field definition.

        Returns:
            forms.Field: The configured Django form Field instance.
        """
        return FIELDS_BY_KEY[self.field_type].as_form_field(**{
            # Special parameters.
            'field_modifiers': (
                (m.attribute_name, m.value_expression)
                for m in self.field_modifiers.all()
            ),
            'field_values': field_values,
            'form_widget_options': self.form_widget_options,
            # Django form field arguments.
            'required': self.required,
            'label': self.label,
            'label_suffix': self.label_suffix,
            'initial': self.initial,
            'help_text': self.help_text,
            **self.form_field_options,
        })

    def as_model_field(self) -> models.Field:
        """Return a Django model Field definition.

        Returns:
            models.Field: The configured Django model Field instance.
        """
        return FIELDS_BY_KEY[self.field_type].as_model_field(**{
            'null': not self.required,
            'blank': not self.required,
            'default': self.initial,
            'help_text': self.help_text,
            **self.model_field_options,
        })

    def apply_modifiers(self, field_values: Optional[Mapping[str, Any]] = None) -> Tuple['Field', Mapping[str, str]]:
        """Return the field with its modifiers applied.

        Applies all of the field's configured modifiers one by one until all
        of them have been evaluated.

        Args:
            field (BaseField): The field to modify.
            field_values (Optional[Mapping[str, Any]]): The field_values to pass to the
                `apply()` method of each modifier.

        Returns:
            Tuple[Field, Mapping[str, str]]: A tuple containing the modified
                field and a list of any errors that occurred while evaluating
                the modifiers.
        """
        field = self
        errors = defaultdict(set)

        for field_modifier in self.field_modifiers.all():
            field, error = field_modifier.apply(
                self, field_values=field_values)

            # If any errors were encountered while evaluating the expression,
            # add them to the collection.
            if error:
                errors[field_modifier.attribute_name].add(error)

        return field, errors


class Field(BaseField):
    """A concrete implementation of Field."""

    class Meta:
        swappable = swapper.swappable_setting('flexible_forms', 'Field')


class BaseFieldModifier(models.Model):
    """A dynamic expression for customizing field rendering behavior.

    A FieldModifier is essentially a map of `attribute_name` -> `expression`,
    where `attribute_name` is the name of a supported attribute on the
    `Field` model, and `expression` is a valid Python expression.

    When `Field.as_form_field()` or `Field.as_model_field()` is called, the
    `expression` is evaluated using the `simpleeval` module with the given
    field_values (usually the field values submitted to the form), and the
    resulting value is used to override the configured attribute on the
    `Field`.

    For example:

    >>> field = Field(required=False)
    >>> unmodified = field.as_form_field()
    >>> repr(unmodified.required)
    'False'
    >>> field.modifiers.create(attribute_name='required', expression='some_input > 1')
    >>> modified = field.as_form_field({'some_input': 2})
    >>> repr(modified.required)
    'True'

    This is useful for modifying the structure and behavior of forms
    dynamically. Some use cases include:

    * Making fields required only if other fields are filled out.
    * Setting default values based on the values of other fields.
    * Hiding a field until another field changes.
    """

    ATTRIBUTE_HIDDEN = 'hidden'
    ATTRIBUTE_LABEL = 'label'
    ATTRIBUTE_HELP_TEXT = 'help_text'
    ATTRIBUTE_REQUIRED = 'required'
    ATTRIBUTE_INITIAL = 'initial'

    SUPPORTED_ATTRIBUTES = (
        (ATTRIBUTE_HIDDEN, 'Hidden'),
        (ATTRIBUTE_LABEL, 'Label'),
        (ATTRIBUTE_HELP_TEXT, 'Help text'),
        (ATTRIBUTE_REQUIRED, 'Required'),
        (ATTRIBUTE_INITIAL, 'Initial value'),
    )

    field = models.ForeignKey(
        swapper.get_model_name('flexible_forms', 'Field'),
        on_delete=models.CASCADE,
        related_name='field_modifiers',
        editable=False,
    )

    attribute_name = models.TextField(choices=SUPPORTED_ATTRIBUTES)
    value_expression = models.TextField()

    class Meta:
        abstract = True


class FieldModifier(BaseFieldModifier):
    """A concrete implementation of FieldModifier."""

    class Meta:
        swappable = swapper.swappable_setting(
            'flexible_forms', 'FieldModifier')


class RecordManager(models.Manager):
    """A manager for Records.

    Automatically optimizes record retrieval by eagerly loading
    relationships.
    """

    def get_queryset(self) -> models.QuerySet['Record']:
        """Define the default QuerySet for fetching Records.

        Eagerly fetches often-used relationships automatically.

        Returns:
            models.QuerySet['Record']: An optimized queryset of Records.
        """
        return (
            super().get_queryset()
            .select_related('form')
            .prefetch_related('form__fields', 'attributes__field')
        )


class BaseRecord(models.Model):
    """An instance of a Form."""

    form = models.ForeignKey(
        swapper.get_model_name('flexible_forms', 'Form'),
        on_delete=models.CASCADE,
        related_name='records',
    )

    objects = RecordManager()

    class Meta:
        abstract = True

    def __str__(self) -> str:
        if not self.form_id or not self.pk:
            return 'Unsaved Record'
        return f'{self.form} {self.pk}'

    @property
    def fields(self) -> Mapping[str, BaseField]:
        return {
            f.machine_name: f
            for f in self.form.fields.all()
        }

    @cached_property
    def data(self) -> Dict[str, Any]:
        """Return a dict of Record attributes and their values.

        Returns:
            Dict[str, Any]: A dict of Record attributes and their values.
        """
        return {
            **{
                name: field.initial
                for name, field in self.fields.items()
            },
            **{
                a.field.machine_name: a.value
                for a in self.attributes.all()
            }
        }

    def set_attribute(self, field_name: str, value: Any) -> None:
        """Set an attribute of the record to the given value.

        Args:
            field_name (str): The name of the attribute to set.
            value (Any): The value.
        """
        print(f'{field_name=},{value=}')
        if not self.pk:
            self.save()

        RecordAttribute = swapper.load_model(
            'flexible_forms', 'RecordAttribute')
        RecordAttribute.objects.update_or_create(
            record=self,
            field=self.fields[field_name],
            defaults={
                'value': value
            }
        )

        self._invalidate_cache()

    def _invalidate_cache(self) -> None:
        """Invalidate any cached properties on the instance."""
        try:
            del self.data
        except AttributeError:
            pass

    def save(self, *args, **kwargs) -> None:
        """Save the record and invalidate the property caches."""
        super().save(*args, **kwargs)
        self._invalidate_cache()


class Record(BaseRecord):
    """The default Record implementation."""

    class Meta:
        swappable = swapper.swappable_setting('flexible_forms', 'Record')


class BaseRecordAttribute(models.Model):
    """A value for an attribute on a single Record."""

    class Meta:
        abstract = True

    record = models.ForeignKey(
        swapper.get_model_name('flexible_forms', 'Record'),
        on_delete=models.CASCADE,
        related_name='attributes',
    )
    field = models.ForeignKey(
        swapper.get_model_name('flexible_forms', 'Field'),
        on_delete=models.CASCADE,
        related_name='attributes',
    )

    def _get_value(self) -> Any:
        return getattr(self, f'_{self.field.field_type}_value')

    def _set_value(self, new_value: Any) -> Any:
        setattr(self, f'_{self.field.field_type}_value', new_value)

    value = property(_get_value, _set_value)


##
# Add individual fields for each supported datatype to BaseRecordAttribute.
#
# The EAV pattern used for storing form submissions (Records) achieves lossless
# storage by creating a column of an appropriate datatype for each supported
# field.
#
for key, field in sorted(FIELDS_BY_KEY.items(), key=lambda f: f[0]):
    BaseRecordAttribute.add_to_class(
        f'_{key}_value', field.as_model_field(blank=True, null=True, default=None))


class RecordAttribute(BaseRecordAttribute):
    """The default RecordAttribute implementation."""

    class Meta:
        swappable = swapper.swappable_setting(
            'flexible_forms', 'RecordAttribute')
