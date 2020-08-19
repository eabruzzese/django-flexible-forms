# -*- coding: utf-8 -*-

"""Model definitions for the flexible_forms module."""

from typing import TYPE_CHECKING, Any, Dict, Type, Union

import swapper
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.forms import Field as DjangoFormField
from django.utils.text import slugify

from flexible_forms.fields import FIELDS_BY_KEY, ValueRouter

try:
    from django.db.models import JSONField
except ImportError:
    from django.contrib.postgres.fields import JSONField

# If we're only type checking, import things that would otherwise cause an
# ImportError due to circular dependencies.
if TYPE_CHECKING:
    from flexible_forms.forms import RecordForm


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

    def as_form_class(self) -> Type['RecordForm']:
        """Return the form represented as a Django Form class.

        Returns:
            Type[ModelForm]: The Django Form class representing this Form.
        """
        # The RecordForm is imported inline to prevent a circular import.
        from flexible_forms.forms import RecordForm

        class_name = self.machine_name.title().replace('_', '')
        form_class_name = f'{class_name}Form'

        # Dynamically define a Django Form class using the fields associated
        # with the Form object.
        form_attrs: Dict[str, Union[str, DjangoFormField]] = {
            '__module__': self.__module__,
            **{
                f.machine_name: f.as_form_field()
                for f in self.fields.all()
            }
        }

        return type(form_class_name, (RecordForm,), form_attrs)


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

    def as_form_field(self) -> DjangoFormField:
        """Return a Django form Field definition.

        Returns:
            DjangoFormField: The configured Django form Field instance.
        """
        return FIELDS_BY_KEY[self.field_type].as_form_field(**{
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
            'blank': not self.label,
            'default': self.initial,
            'help_text': self.help_text,
            **self.model_field_options,
        })


class Field(BaseField):
    """A concrete implementation of Field."""

    class Meta:
        swappable = swapper.swappable_setting('flexible_forms', 'Field')


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
            .prefetch_related('attributes__field')
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
    def data(self) -> Dict[str, Any]:
        """Return a dict of Record attributes and their values.

        Returns:
            Dict[str, Any]: A dict of Record attributes and their values.
        """
        return {
            a.field.machine_name: a.value
            for a in self.attributes.all()
        }


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

    # Use our ValueRouter to store different types of data while maintaining
    # data integrity and constraints at the database level.
    value = ValueRouter(types=(
        f.as_model_field() for f in FIELDS_BY_KEY.values()
    ))


class RecordAttribute(BaseRecordAttribute):
    """The default RecordAttribute implementation."""

    class Meta:
        swappable = swapper.swappable_setting(
            'flexible_forms', 'RecordAttribute')
