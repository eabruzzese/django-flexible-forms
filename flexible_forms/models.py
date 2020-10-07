# -*- coding: utf-8 -*-

"""Model definitions for the flexible_forms module."""

import inspect
import logging
from itertools import groupby
from types import ModuleType
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
)

from django import forms
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models, transaction
from django.db.models.base import ModelBase
from django.db.models.fields.mixins import FieldCacheMixin
from django.db.models.fields.related import (
    ForeignObject,
    ForwardManyToOneDescriptor,
    ReverseManyToOneDescriptor,
)
from django.db.models.options import Options
from django.db.models.query import Prefetch
from django.forms.widgets import Widget
from django.utils.datastructures import MultiValueDict
from django.utils.functional import cached_property
from django.utils.text import slugify
from simpleeval import FunctionNotDefined, NameNotDefined

from flexible_forms.fields import FIELD_TYPES
from flexible_forms.utils import FormEvaluator, evaluate_expression

try:
    from django.db.models import JSONField  # type: ignore
except ImportError:  # pragma: no cover
    from django.contrib.postgres.fields import JSONField

logger = logging.getLogger(__name__)

# If we're only type checking, import things that would otherwise cause an
# ImportError due to circular dependencies.
if TYPE_CHECKING:  # pragma: no cover
    from flexible_forms.forms import BaseRecordForm

T = TypeVar(
    "T",
    bound="FlexibleBaseModel",
)

##
# FIELD_TYPE_OPTIONS
#
# A choice-field-friendly list of all available field types. Sorted for
# migration stability.
#
FIELD_TYPE_OPTIONS = sorted(
    ((k, v.label) for k, v in FIELD_TYPES.items()),
    key=lambda o: o[0],
)


class FlexibleRelation(ForeignObject, FieldCacheMixin):
    """A custom field for defining a swappable ForeignKey field for a model."""

    related_accessor_class: Type[ReverseManyToOneDescriptor]
    forward_related_accessor_class: Type[ForwardManyToOneDescriptor]

    _to_base_model: Type["FlexibleBaseModel"]

    _original_field_name: str
    _original_related_name: str
    _original_args: Sequence[Any]
    _original_kwargs: Dict[str, Any]

    _aliased_to: str

    concrete: bool

    def __init__(
        self,
        to: Type["FlexibleBaseModel"],
        *args: Any,
        related_name: str,
        **kwargs: Any,
    ) -> None:
        self._to_base_model = to
        self._original_related_name = related_name
        self._original_args = args
        self._original_kwargs = kwargs.copy()

        kwargs["related_name"] = related_name

        super().__init__(to, *args, **kwargs)

    def contribute_to_class(
        self, cls: Type[models.Model], name: str, private_only: bool = False
    ) -> None:
        """Add the relation and optional alias fields to the class.

        Args:
            cls: The class to contribute to.
            name: The name of the attribute that the FlexibleRelation was assigned to.
            private_only: Unused.
        """
        if cls._meta.abstract or not hasattr(cls, "_flexible_forms"):
            super().contribute_to_class(cls, name, private_only=private_only)
            return

        cls = cast(Type[FlexibleBaseModel], cls)

        self._original_field_name = name

        # Resolve the appropriate concrete model and field names for the configured _to_base_model.
        to_concrete_model = cls._flexible_forms.get_registered_model(
            self._to_base_model
        )
        field_name = getattr(cls._flexible_meta, f"{name}_relation_name")
        related_name = getattr(
            to_concrete_model._flexible_meta,
            f"{self._original_related_name}_relation_name",
        )

        # Invoke the field constructor now that we've discovered all of the
        # necessary flexible configuration, then add it to the class with
        # contribute_to_class.
        super().__init__(
            to_concrete_model,
            *self._original_args,
            **{**self._original_kwargs, "related_name": related_name},
        )
        super().contribute_to_class(cls, field_name, private_only=private_only)

        # If the field name or related name configured in the FlexibleMeta
        # differs from the original name, add an alias field so that this field
        # can be accessed from either property.
        if field_name != self._original_field_name:
            alias_field = self.__class__(
                to_concrete_model,
                *self._original_args,
                related_name=self._original_related_name,
                **self._original_kwargs,
            )
            alias_field.model = cls
            alias_field.opts = self.opts
            alias_field.name = self._original_field_name
            alias_field.verbose_name = self._original_field_name.replace("_", " ")
            alias_field.attname = self.attname
            alias_field.column = self.column
            alias_field.concrete = True

            alias_field._aliased_to = field_name
            self._aliased_to = alias_field.name

            cls._meta = self._reconfigure_meta(
                cls._meta, self._original_field_name, field_name
            )
            cls._meta.add_field(alias_field, private=True)
            setattr(cls, alias_field.name, getattr(cls, field_name))
            setattr(cls, f"{alias_field.name}_id", getattr(cls, f"{field_name}_id"))

        if related_name != self._original_related_name:
            setattr(
                to_concrete_model,
                self._original_related_name,
                self.related_accessor_class(cast(FieldCacheMixin, self.remote_field)),
            )

    def get_cache_name(self) -> str:
        """Generate a cache name for the aliased field.

        If the FlexibleRelation has an alias field, the alias is added to the cache key.

        Returns:
            str: The cache key for the FlexibleRelation field.
        """
        cache_name = super().get_cache_name()
        cache_alias = getattr(self, "_aliased_to", "")
        return "+".join(sorted(filter(bool, (cache_name, cache_alias))))

    def _reconfigure_meta(
        self, meta: Options, from_field: str, to_field: str
    ) -> Options:
        # Replace any references to old field names in order_with_respect_to.
        meta.order_with_respect_to = (
            to_field  # type: ignore
            if meta.order_with_respect_to == from_field
            else meta.order_with_respect_to
        )
        meta.original_attrs["order_with_respect_to"] = meta.order_with_respect_to

        meta.unique_together = _replace_element(
            from_field, to_field, meta.unique_together
        )
        meta.original_attrs["unique_together"] = meta.unique_together

        meta.index_together = _replace_element(
            from_field, to_field, meta.index_together
        )
        meta.original_attrs["index_together"] = meta.index_together

        indexes = []
        for index in meta.indexes:
            index_class = index.__class__
            _, _, kwargs = index.deconstruct()
            kwargs["fields"] = _replace_element(from_field, to_field, kwargs["fields"])
            indexes.append(index_class(**kwargs))
        meta.indexes = indexes
        meta.original_attrs["indexes"] = meta.indexes

        constraints = []
        for constraint in meta.constraints:
            constraint_class = constraint.__class__
            _, _, kwargs = constraint.deconstruct()
            kwargs["fields"] = _replace_element(from_field, to_field, kwargs["fields"])
            constraints.append(constraint_class(**kwargs))
        meta.constraints = constraints
        meta.original_attrs["constraints"] = meta.constraints

        return meta


class FlexibleForeignKey(FlexibleRelation, models.ForeignKey):
    """A ForeignKey implementation of FlexibleRelation."""


class FlexibleOneToOneField(FlexibleRelation, models.OneToOneField):
    """A OneToOneField implementation of FlexibleRelation."""


class FlexibleMetaclass(ModelBase):
    """A metaclass for custom model definition behavior."""

    def __new__(
        cls: Type["FlexibleMetaclass"],
        name: str,
        bases: Union[Tuple, Tuple[Type[Any]]],
        attrs: Dict[str, Any],
    ) -> "FlexibleMetaclass":
        """Build a new Django model with Flexible Forms capabilities.

        Args:
            cls: This metaclass.
            name: The name of the model to be created.
            bases: Base classes the model should inherit from.
            attrs: A dict of class attributes for the model.

        Returns:
            Type[models.Model]: The new Django model class.
        """
        # Process the FlexibleMeta inner class.
        FlexibleMeta = attrs.pop("FlexibleMeta", None)
        if FlexibleMeta:
            attrs["_flexible_meta"] = FlexibleMeta()

        # Copy the _flexible_forms reference to the attrs dict so that concrete
        # implementations have access to it while they're being defined.
        try:
            flexible_base_model = cast(
                Type["FlexibleBaseModel"],
                next(base for base in bases if issubclass(base, FlexibleBaseModel)),
            )
            attrs["_flexible_forms"] = flexible_base_model._flexible_forms
        except (NameError, StopIteration, AttributeError):
            pass

        # Prepare the model class as usual.
        model_class = cast(
            Type["FlexibleBaseModel"], super().__new__(cls, name, bases, attrs)
        )

        # If we've just prepared a concrete model, register it with the
        # _flexible_forms instance attached to it.
        if not model_class._meta.abstract:
            model_class._flexible_forms.register_model(model_class)

        return model_class


def _replace_element(
    needle: Any,
    replacement: Any,
    haystack: Union[List[Any], Tuple[Any, ...]],
) -> Union[List[Any], Tuple[Any, ...]]:
    elements = type(haystack)()
    for element in haystack:
        if isinstance(element, str):
            element = replacement if element == needle else element
        elif hasattr(element, "__iter__"):
            element = _replace_element(needle, replacement, element)
        elements = [*elements, element]
    return elements


class FlexibleBaseModel(models.Model, metaclass=FlexibleMetaclass):
    """A common base for all FlexibleField base models."""

    class Meta:
        abstract = True

    _flexible_forms: "FlexibleForms"
    _flexible_meta: Any

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        for field_name, value in tuple(kwargs.items()):
            try:
                field = self._meta.get_field(field_name)
            except FieldDoesNotExist:
                continue
            aliased_field_name = getattr(field, "_aliased_to", None)

            if aliased_field_name:
                kwargs[aliased_field_name] = value

            # If both the field and its alias are specified, they should have
            # the same value to prevent conflicts.
            aliased_field_value = kwargs.get(aliased_field_name)
            if aliased_field_name in kwargs and aliased_field_value != value:
                raise ValueError(
                    f"Both {field_name} and its alias {aliased_field_name} were "
                    f"specified, but they have different values ({field_name}={value}, "
                    f"{aliased_field_name}={aliased_field_value}). They should either "
                    f"have the same value, or only one should be specified."
                )

        super().__init__(*args, **kwargs)

    @classmethod
    def _flexible_model_for(cls, base_model: Type[T]) -> Type[T]:
        """Return the current implementation of the given base_model.

        Args:
            base_model: The flexible_forms base model for which to return the implementation.

        Returns:
            Type[FleixbleModel]: The model class for the given base model in
                the current implementation.
        """
        return cast(Type[T], cls._flexible_forms.get_registered_model(base_model))


class BaseForm(FlexibleBaseModel):
    """A model representing a single type of customizable form."""

    name = models.TextField(
        blank=True,
        help_text=(
            "The machine-friendly name of the form. Computed automatically "
            "from the label if not specified."
        ),
    )
    label = models.TextField(
        blank=True,
        default="",
        help_text="The human-friendly name of the form.",
    )
    description = models.TextField(blank=True, default="")

    fields: "models.BaseManager[BaseField]"
    fieldsets: "models.BaseManager[BaseFieldset]"
    records: "models.BaseManager[BaseRecord]"

    class Meta:
        abstract = True

    class FlexibleMeta:
        fields_relation_name = "fields"
        fieldsets_relation_name = "fieldsets"
        records_relation_name = "records"

    def __str__(self) -> str:
        return self.label or "New Form"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Save the model.

        Sets the name if not specified.

        Args:
            args: (Passed to super)
            kwargs: (Passed to super)
        """
        self.name = self.name or slugify(self.label).replace("-", "_")

        super().save(*args, **kwargs)

    @property
    def initial_values(self) -> "MultiValueDict[str, Any]":
        """Return a mapping of initial values for the form."""
        return MultiValueDict(
            {
                **{
                    f.name: f.initial if isinstance(f.initial, list) else [f.initial]
                    for f in self.fields.all()
                },
                "_form": [self],
            }
        )

    def as_django_fieldsets(
        self,
    ) -> List[Tuple[Optional[str], Dict[str, Any]]]:
        """Generate a Django fieldsets configuration for the form.

        The Django admin supports the specification of fieldsets -- a
        simple way of grouping fields together. This property builds
        """
        django_fieldsets: List[Tuple[Optional[str], Dict[str, Any]]] = []
        fieldsets = self.fieldsets.all()

        seen_fields = set()
        for fieldset in fieldsets:
            fieldset_items: Union[Tuple, Tuple[Union[Sequence[str], str]]] = ()

            # Sort the fieldset items by their vertical order, then group them
            # by that order. This creates "rows" of items that have the same
            # vertical_order.
            vertically_sorted_items = sorted(
                fieldset.items.all(), key=lambda f: int(f.vertical_order)
            )
            vertical_groups = groupby(
                vertically_sorted_items,
                lambda f: int(f.vertical_order),
            )

            # For each of the vertical groups that were created, sort them by
            # their horizontal_order. This sets their horizontal display order
            # so that items with a lower horizontal order are displayed first.
            for _order, vertical_group in vertical_groups:
                sorted_group = [
                    i.field.name
                    for i in sorted(
                        vertical_group, key=lambda i: int(i.horizontal_order)
                    )
                ]
                seen_fields.update(sorted_group)
                fieldset_items = (
                    *fieldset_items,
                    tuple(sorted_group) if len(sorted_group) > 1 else sorted_group[0],
                )

            # Add the configured fieldset to the rest of them.
            django_fieldsets = [
                *django_fieldsets,
                (
                    fieldset.name or None,
                    {
                        "classes": tuple(filter(bool, fieldset.classes.split(" "))),
                        "description": fieldset.description or None,
                        "fields": fieldset_items,
                    },
                ),
            ]

        return django_fieldsets

    def as_django_form(
        self,
        data: Optional[Mapping[str, Any]] = None,
        files: Optional[Mapping[str, Any]] = None,
        instance: Optional["BaseRecord"] = None,
        initial: Optional[Mapping[str, Any]] = None,
        **kwargs: Any,
    ) -> "BaseRecordForm":
        """Return the form represented as a Django form instance.

        Args:
            data: Data to be passed to the
                Django form constructor.
            files: Data to be passed to the
                Django form constructor.
            instance: The Record instance to be passed to
                the Django form constructor.
            initial: Initial values for the
                form fields.
            **kwargs: Passed to the Django ModelForm constructor.

        Returns:
            BaseRecordForm: A configured BaseRecordForm (a Django ModelForm instance).
        """
        all_fields = self.fields.all()

        # Build a MultiValueDict containing all field values. This combines all
        # of the form data into a single structure that will be used when
        # evaluating expressions against the form state.
        form_state: MultiValueDict[str, Any] = self.initial_values
        form_state.update(initial or {})
        form_state.update(instance._data if instance else {})
        form_state.update(data or {})
        form_state.update(files or {})

        # Normalize the field values to ensure they are all cast to their
        # appropriate types (as defined by their corresponding form fields).
        form_fields: MutableMapping[str, forms.Field] = {
            f.name: f.as_form_field() for f in all_fields
        }
        for field_name, form_field in form_fields.items():
            field_widget = cast(Widget, form_field.widget)
            field_value = field_widget.value_from_datadict(
                data=form_state,  # type: ignore
                files=form_state,
                name=field_name,
            )
            # Try to perform as much of the value coercion process as possible
            # while attempting to avoid running expensive validators.
            try:
                field_value = form_field.to_python(field_value)
                if callable(getattr(form_field, "_coerce", None)):
                    field_value = form_field._coerce(field_value)  # type: ignore
            except ValidationError:
                pass
            form_state[field_name] = field_value

        # Regenerate the form fields, this time taking the field values into
        # account in order to inform any dynamic behaviors.
        form_fields = {}
        for field in all_fields:
            form_field = field.as_form_field(field_values=form_state)
            form_fields[field.name] = form_field

        RecordModel = self._flexible_model_for(BaseRecord)

        # Import the form class inline to prevent a circular import.
        from flexible_forms.forms import BaseRecordForm

        form_name = f"{self.name.title().replace('_', '')}Form"
        form_class: Type[BaseRecordForm] = type(
            form_name,
            (BaseRecordForm,),
            {
                "__module__": self.__module__,
                "Meta": type(
                    "Meta",
                    (BaseRecordForm.Meta,),
                    {"model": RecordModel},
                ),
                **form_fields,
            },
        )

        initial = {"_form": self, **(initial or {})}

        # Create a form instance from the form class and the passed parameters.
        form_instance = form_class(
            data=data,
            files=files,
            instance=instance,
            initial=initial,
            **kwargs,
        )

        return form_instance


class BaseField(FlexibleBaseModel):
    """A field on a form.

    A field belonging to a Form. Attempts to emulate a subset of
    Django's Field interface for that forms can be built dynamically.
    """

    label = models.TextField(
        help_text="The label to be displayed for this field in the form.",
    )

    name = models.TextField(
        blank=True,
        help_text=(
            "The machine-friendly name of the field. Computed automatically "
            "from the label if not specified."
        ),
    )

    label_suffix = models.TextField(
        blank=True,
        default="",
        help_text=('The character(s) at the end of the field label (e.g. "?" or ":").'),
    )

    help_text = models.TextField(
        blank=True,
        default="",
        help_text="Text to help the user fill out the field.",
    )

    required = models.BooleanField(
        default=False,
        help_text="If True, requires a value be present in the field.",
    )

    initial = JSONField(
        blank=True,
        null=True,
        help_text=("The default value if no value is given during initialization."),
        encoder=DjangoJSONEncoder,
    )

    field_type = models.TextField(
        choices=FIELD_TYPE_OPTIONS,
        help_text="The form widget to use when displaying the field.",
    )

    form_field_options = JSONField(
        blank=True,
        default=dict,
        help_text="Custom arguments passed to the form field constructor.",
        encoder=DjangoJSONEncoder,
    )

    form_widget_options = JSONField(
        blank=True,
        default=dict,
        help_text="Custom arguments passed to the form widget constructor.",
        encoder=DjangoJSONEncoder,
    )

    form: "models.ForeignKey[BaseForm, BaseForm]" = FlexibleForeignKey(
        BaseForm, on_delete=models.CASCADE, related_name="fields"
    )
    form_id: Optional[int]

    fieldset_item: "models.OneToOneField[BaseFieldsetItem, BaseFieldsetItem]"
    fieldset_item_id: Optional[int]

    modifiers: "models.BaseManager[BaseFieldModifier]"
    attributes: "models.BaseManager[BaseRecordAttribute]"

    class Meta:
        abstract = True
        order_with_respect_to = "form"
        unique_together = ("form", "name")

    class FlexibleMeta:
        form_relation_name = "form"
        fieldset_item_relation_name = "fieldset_item"
        modifiers_relation_name = "modifiers"
        attributes_relation_name = "attributes"

    def __str__(self) -> str:
        return self.label or "New Field"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Save the model.

        Sets the machine name if not specified, and ensures that the related
        form is the same as the form that the section belongs to.

        Args:
            args: (Passed to super)
            kwargs: (Passed to super)
        """
        self.name = self.name or slugify(self.label).replace("-", "_")

        super().save(*args, **kwargs)

    def as_form_field(
        self,
        field_values: Optional[Mapping[str, Any]] = None,
    ) -> forms.Field:
        """Return a Django form Field definition.

        Args:
            field_values: The current values of
                all fields in the form.

        Returns:
            forms.Field: The configured Django form Field instance.
        """
        return FIELD_TYPES[self.field_type].as_form_field(
            **{
                # Special parameters.
                "modifiers": (
                    (m.attribute, m.expression)
                    for m in self.modifiers.all()  # type: ignore
                ),
                "field_values": field_values,
                "form_widget_options": self.form_widget_options,
                # Django form field arguments.
                "required": self.required,
                "label": self.label,
                "label_suffix": self.label_suffix,
                "initial": self.initial,
                "help_text": self.help_text,
                **self.form_field_options,
            }
        )

    def as_model_field(self) -> models.Field:
        """Return a Django model Field definition.

        Returns:
            models.Field: The configured Django model Field instance.
        """
        return FIELD_TYPES[self.field_type].as_model_field(
            null=not self.required,
            blank=not self.required,
            default=self.initial,
            help_text=self.help_text,
        )


class BaseFieldModifier(FlexibleBaseModel):
    """A dynamic expression for customizing field rendering behavior.

    A FieldModifier is essentially a map of `attribute` -> `expression`,
    where `attribute` is the name of a supported attribute on the
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
    >>> field.modifiers.create(attribute='required', expression='some_input > 1')
    >>> modified = field.as_form_field({'some_input': 2})
    >>> repr(modified.required)
    'True'

    This is useful for modifying the structure and behavior of forms
    dynamically. Some use cases include:

    * Making fields required only if other fields are filled out.
    * Setting default values based on the values of other fields.
    * Hiding a field until another field changes.
    """

    field: "models.ForeignKey[BaseField, BaseField]" = FlexibleForeignKey(
        BaseField, on_delete=models.CASCADE, related_name="modifiers"
    )
    field_id: Optional[int]

    attribute = models.TextField()
    expression = models.TextField()

    # The _validated flag is used to check whether the expression has been
    # validated. If it's false by the time that save() is called, we validate
    # there.
    _validated = False

    class FlexibleMeta:
        field_relation_name = "field"

    def __str__(self) -> str:
        return f"{self.attribute} = {self.expression}"

    def clean(self) -> None:
        """Ensure that the expression is valid for the form.

        Checks to make sure that referenced names and functions are
        defined before saving.
        """
        super().clean()
        self._validated = False

        # No field? No Problem!
        if not hasattr(self, "field"):
            return

        # Validate that the expression is valid for the form. This is
        # accomplished by building a dict of initial values for all fields on
        # the form and running it through the expression evaluator. If any
        # exceptions are raised, they are returned as validation errors.
        field_values = {f.name: f.initial for f in self.field.form.fields.all()}

        try:
            evaluate_expression(self.expression, names=field_values)

        # If the expression references a name that isn't a field on the form
        # (or a builtin), raise a validation error.
        except NameNotDefined as ex:
            valid_fields = ", ".join(field_values.keys())
            name = getattr(ex, "name", "")
            raise ValidationError(
                {
                    "expression": (
                        f"The expression references a variable named '{name}', but no "
                        f"field with that name exists in the form. Valid fields are: "
                        f"{valid_fields}."
                    )
                }
            )

        # If the expression references a function that isn't in scope for the
        # expression, raise a validation error.
        except FunctionNotDefined as ex:
            valid_functions = ", ".join(FormEvaluator.FUNCTIONS.keys())
            func_name = getattr(ex, "func_name", "")
            raise ValidationError(
                {
                    "expression": (
                        f"The expression is trying to use the function {func_name}, "
                        f"but that function does not exist, or cannot be used in "
                        f"expressions. Valid functions are: {valid_functions}"
                    )
                }
            )

        # If the expression encounters another error (e.g., TypeError).
        except BaseException as ex:
            raise ValidationError(
                {
                    "expression": (
                        f"The expression is invalid. Error message: '{str(ex)}'"
                    )
                }
            )

        self._validated = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Save the record.

        Runs deferred validation.

        Args:
            args: Passed to super.
            kwargs: Passed to super.
        """
        # If we haven't validated the expression at this point, run clean().
        if not self._validated:
            self.clean()
        super().save(*args, **kwargs)

    class Meta:
        abstract = True
        order_with_respect_to = "field"


class BaseFieldset(FlexibleBaseModel):
    """A section of Fields within a Form."""

    name = models.TextField(
        blank=True,
        default="",
        help_text="The heading to be used for the fieldset. If left empty, no heading will appear.",
    )
    description = models.TextField(
        blank=True, default="", help_text="The description of the fieldset."
    )
    classes = models.TextField(
        blank=True,
        default="",
        help_text="CSS classes to be be applied to the fieldset when rendered.",
    )

    form: "models.ForeignKey[BaseForm, BaseForm]" = FlexibleForeignKey(
        BaseForm, on_delete=models.CASCADE, related_name="fieldsets"
    )
    items: "models.BaseManager[BaseFieldsetItem]"

    class Meta:
        abstract = True

    class FlexibleMeta:
        form_relation_name = "form"
        items_relation_name = "fieldset_items"

    def __str__(self) -> str:
        return f"Fieldset {self.name} ({self.pk})"


class BaseFieldsetItem(FlexibleBaseModel):
    """A single item within a Fieldset."""

    fieldset: "models.ForeignKey[BaseFieldset, BaseFieldset]" = FlexibleForeignKey(
        BaseFieldset, on_delete=models.CASCADE, related_name="items"
    )
    fieldset_id: Optional[int]
    field: "models.OneToOneField[BaseField, BaseField]" = FlexibleOneToOneField(
        BaseField, on_delete=models.CASCADE, related_name="fieldset_item"
    )
    field_id: Optional[int]

    vertical_order = models.IntegerField(
        help_text=(
            "The vertical order of the item within the fieldset. Items with a lower "
            "vertical order are displayed first. Items with the same vertical order "
            "will be displayed on the same line."
        )
    )
    horizontal_order = models.IntegerField(
        help_text=(
            "The horizontal order of the item within its vertical position. Items "
            "with a lower order are displayed first."
        )
    )

    class Meta:
        abstract = True
        ordering = ["vertical_order", "horizontal_order"]
        unique_together = ("fieldset", "vertical_order", "horizontal_order")

    class FlexibleMeta:
        field_relation_name = "field"
        fieldset_relation_name = "fieldset"

    def __str__(self) -> str:
        return f"Fieldset item {self.pk} for field {self.field_id}"


class RecordManager(models.Manager):
    """A manager for Records.

    Automatically optimizes record retrieval by eagerly loading
    relationships.
    """

    model: Type["BaseRecord"]

    def get_queryset(self) -> "models.QuerySet[BaseRecord]":
        """Define the default QuerySet for fetching Records.

        Eagerly fetches often-used relationships automatically.

        Returns:
            models.QuerySet['BaseRecord']: An optimized queryset of Records.
        """
        RecordAttribute = self.model._flexible_model_for(BaseRecordAttribute)
        return cast(
            "models.QuerySet[BaseRecord]",
            (
                super()
                .get_queryset()
                .select_related("_form")
                .prefetch_related(
                    f"_form__fields",
                    f"_form__fields__modifiers",
                    f"_form__fieldsets",
                    f"_form__fieldsets__items",
                    Prefetch(
                        "_attributes",
                        queryset=RecordAttribute.objects.select_related("field"),
                    ),
                )
            ),
        )


class BaseRecord(FlexibleBaseModel):
    """An instance of a Form.

    The BaseRecord is a bit special. The underlying storage implementation is
    an EAV, but BaseRecord allows callers to access attributes with the usual
    attribute syntax (e.g. record.attribute_name) by overriding __getattr__
    and __setattr__ in order to proxy requests for attributes to the
    underlying BaseRecordAttribute instance(s).

    You might notice that most of the attributes on the BaseRecord are
    prefixed with underscores. This is not necessarily to mark those
    attributes as private, but instead to avoid collisions with EAV attribute
    names.
    """

    _form: "models.ForeignKey[BaseForm, BaseForm]" = FlexibleForeignKey(
        BaseForm, on_delete=models.CASCADE, related_name="records"
    )
    _form_id: Optional[int]
    _attributes: "models.BaseManager[BaseRecordAttribute]"

    objects = RecordManager()

    # The _initialized flag is used to determine if the model instance has been
    # fully initialized by Django. We use the flag to determine if it's safe to
    # start proxying __getattr__ and __setattr__ calls to our _attributes
    # association (which breaks if the instanec is not fully initialized).
    _initialized: bool = False

    # The __setattr__ proxy stores attribute updates in the _staged_changes
    # dict until save() is called. This attempts to mirror the way vanilla
    # Django models work.
    _staged_changes: MutableMapping[str, Any]

    class Meta:
        abstract = True

    class FlexibleMeta:
        _form_relation_name = "_form"
        _attributes_relation_name = "_attributes"

    def __str__(self) -> str:
        return f"Record {self.pk} (_form_id={self._form_id})"

    def __init__(
        self, *args: Any, _form: Optional[BaseForm] = None, **kwargs: Any
    ) -> None:
        super().__init__(*args, _form=_form, **kwargs)
        self._staged_changes = {}
        self._initialized = True

    def as_django_form(self, *args: Any, **kwargs: Any) -> "BaseRecordForm":
        """Create a Django form from the record.

        Uses `self` as the `instance` argument to as_django_form()`

        Args:
            args: Passed to super.
            kwargs: Passed to super.

        Returns:
            BaseRecordForm: A configured Django form for the record.
        """
        kwargs = {"instance": self, **kwargs}
        return self._form.as_django_form(*args, **kwargs)

    @cached_property
    def _fields(self) -> Mapping[str, BaseField]:
        """Return a map of Fields for the Record's form, keyed by their names.

        Returns:
            Mapping[str, BaseField]: A mapping of Field instances by their
                names.
        """
        if not hasattr(self, "_form"):
            return {}
        return {f.name: f for f in self._form.fields.all()}

    @cached_property
    def _data(self) -> Mapping[str, Any]:
        """Return a dict of Record attributes and their values.

        Returns:
            Mapping[str, Any]: A dict of Record attributes and their values.
        """
        initial_values = {name: field.initial for name, field in self._fields.items()}
        attribute_values = cast(
            Dict[str, Any],
            (
                {a.field.name: a.value for a in self._attributes.all()}
                if self.pk
                else {}
            ),
        )
        staged_attributes = {k: v for k, v in self._staged_changes.items()}

        return {
            **initial_values,
            **attribute_values,
            **staged_attributes,
        }

    def __getattr__(self, name: str) -> Any:
        """Get an attribute value from the record.

        Overrides __getattr__ to make attribute access more natural-feeling.
        Attributes on the record can be accessed with obj.attribute syntax.

        If the record hasn't finished initialization yet, falls back to
        default behavior.

        Args:
            name: The name of the attribute to get from the record.

        Raises:
            AttributeError: If the object has no attribute with the given
                name.

        Returns:
            Any: The value of the attribute, if available.
        """
        if (
            not self._initialized
            or name
            in frozenset(
                [
                    *self.__dict__.keys(),
                    *self.__class__.__dict__.keys(),
                ]
            )
            or name.startswith("_")
        ):
            return self.__getattribute__(name)

        if name in self._fields:
            return self._data[name]

        raise AttributeError(
            f"'{self.__class__.__name__}' object has no attribute '{name}'"
        )

    def __setattr__(self, name: str, value: Any) -> None:
        """Set an attribute value by name.

        Args:
            name: The name of the attribute to set.
            value: The value that the attribute should be set to.
        """
        if (
            not self._initialized
            or name
            in frozenset([*self.__dict__.keys(), *self.__class__.__dict__.keys()])
            or name.startswith("_")
        ):
            super().__setattr__(name, value)
            return

        RecordAttribute = cast(Any, self._flexible_model_for(BaseRecordAttribute))
        self._staged_changes[name] = RecordAttribute(
            record=self,
            field=self._fields[name],
            value=value,
        ).value
        self._invalidate_caches("_data")

    def _invalidate_caches(self, *caches: str) -> None:
        """Invalidate cached properties on the Record."""
        caches = caches or ("_data", "_fields")

        for cache in caches:
            try:
                delattr(self, cache)
            except AttributeError:
                pass

    @transaction.atomic
    def save(self, *args: Any, **kwargs: Any) -> None:
        """Save the record and invalidate the property caches."""
        super().save(*args, **kwargs)

        # If there are no attributes to update, return early.
        if not self._staged_changes:
            return

        # Upsert the record attributes.
        RecordAttribute = cast(Any, self._flexible_model_for(BaseRecordAttribute))
        attribute_map = {a.field.name: a for a in self._attributes.all()}

        value_fields: Set[str] = set()
        update: List[BaseRecordAttribute] = []
        insert: List[BaseRecordAttribute] = []
        for field_name, value in self._staged_changes.items():
            # Find the existing attribute object or create a new one.
            attribute = attribute_map.get(field_name) or RecordAttribute(
                record=self,
                field=self._fields[field_name],
            )

            # Set the value for the attribute.
            attribute.value = value

            # Add the attribute object to the appropriate operation set.
            operation = update if attribute.pk else insert
            operation.append(attribute)

            # If we're updating, track which value column should be updated.
            if operation is update:
                value_fields.add(attribute.value_field_name)

        # Perform bulk updates and inserts as necessary.
        if update:
            RecordAttribute._default_manager.bulk_update(
                update, fields=(*value_fields,)
            )
        if insert:
            RecordAttribute._default_manager.bulk_create(insert)

        # Invalidate the data cache.
        self._invalidate_caches("_data")


class BaseRecordAttribute(FlexibleBaseModel):
    """A value for an attribute on a single Record."""

    ##
    # _VALUE_FIELD_PREFIX
    #
    # A prefix used to denote value fields for the attribute.
    #
    _VALUE_FIELD_PREFIX = "_value_"

    record: "models.ForeignKey[BaseRecord, BaseRecord]" = FlexibleForeignKey(
        BaseRecord, on_delete=models.CASCADE, related_name="_attributes"
    )
    record_id: Optional[int]

    field: "models.ForeignKey[BaseField, BaseField]" = FlexibleForeignKey(
        BaseField, on_delete=models.CASCADE, related_name="attributes"
    )
    field_id: Optional[int]

    class Meta:
        abstract = True

    class FlexibleMeta:
        field_relation_name = "field"
        record_relation_name = "record"

    def __str__(self) -> str:
        return f"RecordAttribute {self.pk} (record_id={self.record_id}, field_id={self.field_id})"

    @classmethod
    def get_value_field_name(cls, field_type: str) -> str:
        """Return the name of the field used for storing field_type values.

        Args:
            field_type: The field type.

        Returns:
            str: The name of the model field for storing field_type values.
        """
        return f"{cls._VALUE_FIELD_PREFIX}{field_type}"

    @property
    def value_field_name(self) -> str:
        """Return the name of the field that holds the attribute value.

        Values are stored in columns with appropriate typings for performance
        and lossless storage.

        Returns:
            str: The name of the field that holds the value for the attribute.
        """
        return self.get_value_field_name(self.field.field_type)

    def _get_value(self) -> Any:
        """Return the attribute value.

        Returns:
            Any: The current value of the attribute.
        """
        return getattr(self, self.value_field_name)

    def _set_value(self, new_value: Any) -> None:
        """Set the value of the attribute.

        Sets the value of the attribute to the given value.

        Args:
            new_value: The new value for the attribute.
        """
        # Clear out the
        value_field_names = (
            f.name
            for f in self._meta.get_fields()
            if f.name.startswith(self._VALUE_FIELD_PREFIX)
        )
        for field_name in value_field_names:
            setattr(self, field_name, None)

        setattr(self, self.value_field_name, new_value)

    ##
    # value
    #
    # A getter and setter property for transparently interacting with the value
    # of the attribute.
    #
    value = property(_get_value, _set_value)


##
# Add individual fields for each supported datatype to BaseRecordAttribute.
#
# The EAV pattern used for storing form submissions (Records) achieves lossless
# storage by creating a column of an appropriate datatype for each supported
# field.
#
for field_type, field in sorted(FIELD_TYPES.items(), key=lambda f: f[0]):
    BaseRecordAttribute.add_to_class(  # type: ignore
        BaseRecordAttribute.get_value_field_name(field_type),
        field.as_model_field(blank=True, null=True, default=None),
    )


class FlexibleForms:
    """A class for generating new sets of concrete flexible form models.

    Enables users to have multiple sets of FlexibleForm models in their
    application.

    Effectively frees the developer from having to shoehorn all of their use
    cases into a single set of models and tables, and allows them to
    customize each set of models and tailor them to each specific use case.

    For example, in a school setting it might be useful to have a flexible
    model structure for Quizzes, and another one for Projects, each with
    their own set of models, database tables, and attributes. The developer
    can also choose to rename the relationships that connect these models for
    ergonomics:

    ```python
    # quizzes/models.py
    from django.contrib.auth import get_user_model
    from django.db import models
    from flexible_forms.models import BaseForm, BaseRecord
    from django.utils import timezone

    quizzes = FlexibleForms(model_prefix="Quiz")

    class QuizAssignment(quizzes.BaseForm):
        due = models.DateTimeField(default=timezone.now)

        class Meta(BaseForm.Meta):
            ordering = ("-due",)

        class FlexibleMeta:
            records_relation_name = "submissions"

    class QuizSubmission(quizzes.BaseRecord):
        student = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
        submitted = models.DateTimeField(default=timezone.now)
        grade = models.PositiveIntegerField()

        class FlexibleMeta:
            _form_relation_name = "quiz"
    ```

    ```python
    # projects/models.py
    from django.db import models
    from flexible_forms.models import BaseForm
    from django.utils import timezone

    projects = FlexibleForms(model_prefix="Project")

    class ProjectAssignment(projects.BaseForm):
        due = models.DateTimeField(default=timezone.now)
        grading_criteria = models.TextField()

        class Meta(BaseForm.Meta):
            ordering = ("-due",)
    ```
    """

    def __init__(self, model_prefix: Optional[str] = None) -> None:
        self.model_prefix = model_prefix or ""
        self.module = cast(ModuleType, inspect.getmodule(inspect.stack()[1][0]))
        self.models: Dict[
            Union[Type[FlexibleBaseModel], str], Type[FlexibleBaseModel]
        ] = {}

    def register_model(self, model_class: Type[FlexibleBaseModel]) -> None:
        """Register a concrete implementation of a flexible base model.

        Maps the given model_class' base model class (e.g.,
        flexible_forms.models.BaseForm) the concrete implementation
        (model_class).

        Additionally, adds a string entry (e.g. "flexible_forms.baseform")
        that points to the same concrete implementation.

        Args:
            model_class: The concrete implementation of a flexible base model.
        """
        base_model = self._get_flexible_base_model(model_class)
        base_opts = base_model._meta

        self.models[base_model] = model_class
        self.models[f"{base_opts.app_label}.{base_opts.model_name}"] = model_class

    def get_registered_model(
        self, base_model: Union[str, Type["FlexibleBaseModel"]]
    ) -> Type["FlexibleBaseModel"]:
        """Returns the concrete model for the given flexible base model.

        Args:
            base_model: The base model for which to return the concrete model
                implementation.

        Raises:
            LookupError: if no concrete model has been registered for the
                given base yet.

        Returns:
            Type[FlexibleBaseModel]: The concrete model implementation for
                the base model.
        """
        if base_model not in self.models:
            raise LookupError(
                f"No concrete model has been registered for {base_model}: {self.models}"
            )

        return self.models[base_model]

    def _get_flexible_base_model(
        self, model_class: Type["FlexibleBaseModel"]
    ) -> Type["FlexibleBaseModel"]:
        """Resolve the flexible base model for the given model_class.

        Searches the __bases__ of the given model class for one that
        corresponds to one of the core flexible base models.

        Args:
            model_class: The model class for which to resolve the flexible
                base class.

        Returns:
            Type[FlexibleBaseModel]: The flexible base model.

        Raises:
            ValueError: if the model_class does not inherit from a flexible
                base class.
        """
        flexible_bases = frozenset(FlexibleBaseModel.__subclasses__())
        for base in model_class.__bases__:
            try:
                return next(
                    flexible_base
                    for flexible_base in flexible_bases
                    if issubclass(base, flexible_base)
                )
            except (NameError, StopIteration):
                continue

        raise ValueError(
            f"{model_class.__name__} does not inherit from FlexibleBaseModel."
        )

    @property
    def BaseForm(self) -> Type["BaseForm"]:
        """Return a BaseForm with a reference to _flexible_forms.

        Returns:
            Type[BaseForm]: A BaseForm class with a _flexible_forms
                attribute.
        """
        return self._generate_model(BaseForm)

    @property
    def BaseField(self) -> Type["BaseField"]:
        """Return a BaseField with a reference to _flexible_forms.

        Returns:
            Type[BaseField]: A BaseField class with a _flexible_forms
                attribute.
        """
        return self._generate_model(BaseField)

    @property
    def BaseFieldset(self) -> Type["BaseFieldset"]:
        """Return a BaseFieldset with a reference to _flexible_forms.

        Returns:
            Type[BaseFieldset]: A BaseFieldset class with a _flexible_forms
                attribute.
        """
        return self._generate_model(BaseFieldset)

    @property
    def BaseFieldsetItem(self) -> Type["BaseFieldsetItem"]:
        """Return a BaseFieldsetItem with a reference to _flexible_forms.

        Returns:
            Type[BaseFieldsetItem]: A BaseFieldsetItem class with a
                _flexible_forms attribute.
        """
        return self._generate_model(BaseFieldsetItem)

    @property
    def BaseFieldModifier(self) -> Type["BaseFieldModifier"]:
        """Return a BaseFieldModifier with a reference to _flexible_forms.

        Returns:
            Type[BaseFieldModifier]: A BaseFieldModifier class with a
                _flexible_forms attribute.
        """
        return self._generate_model(BaseFieldModifier)

    @property
    def BaseRecord(self) -> Type["BaseRecord"]:
        """Return a BaseRecord with a reference to _flexible_forms.

        Returns:
            Type[BaseRecord]: A BaseRecord class with a _flexible_forms
                attribute.
        """
        return self._generate_model(BaseRecord)

    @property
    def BaseRecordAttribute(self) -> Type["BaseRecordAttribute"]:
        """Return a BaseRecordAttribute with a reference to _flexible_forms.

        Returns:
            Type[BaseRecordAttribute]: A BaseRecordAttribute class with a
                _flexible_forms attribute.
        """
        return self._generate_model(BaseRecordAttribute)

    def _generate_model(self, base_model: Type[T]) -> Type[T]:
        """Generate a model class from the given base_model.

        Args:
            base_model: The base model for the new model.

        Returns:
            Type[T]: A new model with a reference to _flexible_forms.
        """
        return type(
            f"{self.model_prefix}{base_model.__name__}",
            (base_model,),
            {
                "__module__": self.module.__name__,
                "_flexible_forms": self,
                "Meta": type(
                    "Meta",
                    (base_model.Meta,),
                    {
                        "abstract": True,
                    },
                ),
            },
        )
