# -*- coding: utf-8 -*-

"""Model definitions for the flexible_forms module."""

import inspect
import logging
import weakref
from types import ModuleType
from typing import (
    TYPE_CHECKING,
    Any,
    Mapping,
    MutableMapping,
    Optional,
    Type,
    TypeVar,
    Union,
    cast,
)

from django import forms
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.forms.fields import FileField
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

# If we're only type checking, import things that would otherwise cause an
# ImportError due to circular dependencies.
if TYPE_CHECKING:  # pragma: no cover
    from flexible_forms.forms import BaseRecordForm

logger = logging.getLogger(__name__)


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


class BaseForm(models.Model):
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

    class Meta:
        abstract = True

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
        if isinstance(data, MultiValueDict):
            data = data.dict()

        if isinstance(files, MultiValueDict):
            files = files.dict()

        if isinstance(initial, MultiValueDict):
            initial = initial.dict()

        Record = cast(Type[BaseRecord], self._meta.get_field("records").related_model)

        instance = instance or Record(form=self)  # type: ignore
        data = cast(Mapping[str, Any], {**(data or instance.data), "form": self.pk})
        files = cast(Mapping[str, Any], files or {})
        initial = cast(Mapping[str, Any], {**(initial or {}), "form": self.pk})

        class_name = self.name.title().replace("_", "")
        form_class_name = f"{class_name}Form"
        all_fields = self.fields.all()  # type: ignore
        field_values = {
            **instance.data,
            **({k: data.get(k) for k in data.keys()}),
            **({k: files.get(k) for k in files.keys()}),
        }

        # Generate the initial list of fields that comprise the form.
        form_fields = {f.name: f.as_form_field() for f in all_fields}

        # Normalize the field values to ensure they are all cast to their
        # appropriate types (as defined by their corresponding form fields).
        for field_name, form_field in form_fields.items():
            field_value = field_values.get(field_name)
            if isinstance(form_field, FileField) and field_value is False:
                field_value = None
            field_values[field_name] = form_field.to_python(field_value)

        # Regenerate the form fields, this time taking the field values into
        # account in order to inform any dynamic behaviors.
        form_fields = {
            f.name: f.as_form_field(
                field_values=field_values,
            )
            for f in all_fields
        }

        # Dynamically generate a form class containing all of the fields.
        # The BaseRecordForm is imported inline to prevent a circular import.
        from flexible_forms.forms import BaseRecordForm

        form_class: Type[BaseRecordForm] = type(
            form_class_name,
            (BaseRecordForm,),
            {
                "__module__": self.__module__,
                "Meta": type("Meta", (BaseRecordForm.Meta,), {"model": Record}),
                **form_fields,
            },
        )

        # Create a form instance from the form class and the passed parameters.
        form_instance = form_class(
            data=data, files=files, instance=instance, initial=initial, **kwargs
        )

        return form_instance


class BaseField(models.Model):
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

    initial = models.TextField(
        blank=True,
        default="",
        help_text=("The default value if no value is given during initialization."),
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

    # The `form` is set by the implementing class.
    form: models.ForeignKey

    class Meta:
        abstract = True
        unique_together = ("form", "name")
        order_with_respect_to = "name"

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


class BaseFieldModifier(models.Model):
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

    attribute = models.TextField()
    expression = models.TextField()

    # The `field` is set by the implementing class.
    field: models.ForeignKey
    field_id: int

    # The _validated flag is used to check whether the expression has been
    # validated. If it's false by the time that save() is called, we validate
    # there.
    _validated = False

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


class RecordManager(models.Manager):
    """A manager for Records.

    Automatically optimizes record retrieval by eagerly loading
    relationships.
    """

    def get_queryset(self) -> "models.QuerySet[BaseRecord]":
        """Define the default QuerySet for fetching Records.

        Eagerly fetches often-used relationships automatically.

        Returns:
            models.QuerySet['BaseRecord']: An optimized queryset of Records.
        """
        return cast(
            "models.QuerySet[BaseRecord]",
            (
                super()
                .get_queryset()
                .select_related("form")
                .prefetch_related("form__fields", "attributes__field")
            ),
        )


class BaseRecord(models.Model):
    """An instance of a Form."""

    # The `form` is set by the implementing class.
    form: models.ForeignKey
    form_id: int

    objects = RecordManager()

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return f"Record {self.pk} (form_id={self.form_id if self.form else None})"

    def __init__(
        self, *args: Any, form: Optional[BaseForm] = None, **kwargs: Any
    ) -> None:
        super().__init__(*args, form=form, **kwargs)
        self._staged_changes: MutableMapping[str, Any] = {}

    @property
    def fields(self) -> Mapping[str, BaseField]:
        """Return a map of Fields for the Record's form, keyed by their names.

        Returns:
            Mapping[str, BaseField]: A mapping of Field instances by their
                names.
        """
        return {f.name: f for f in self.form.fields.all()}

    @cached_property
    def data(self) -> Mapping[str, Any]:
        """Return a dict of Record attributes and their values.

        Returns:
            Mapping[str, Any]: A dict of Record attributes and their values.
        """
        return {
            **{name: field.initial for name, field in self.fields.items()},
            **(
                {a.field.name: a.value for a in self.attributes.all()}  # type: ignore
                if self.pk
                else {}
            ),
            **self._staged_changes,
        }

    def set_attribute(self, field_name: str, value: Any, commit: bool = False) -> None:
        """Set an attribute of the record to the given value.

        Args:
            field_name: The name of the attribute to set.
            value: The value.
            commit: True if the record should be persisted.
        """
        RecordAttribute = cast(
            Type[BaseRecordAttribute], self._meta.get_field("attributes").related_model
        )
        if commit:
            RecordAttribute.objects.update_or_create(
                record=self,
                field=self.fields[field_name],
                defaults={
                    "value": value,
                },
            )
        else:
            self._staged_changes[field_name] = RecordAttribute(
                field=self.fields[field_name], value=value
            ).value

        self._invalidate_cache()

    def _invalidate_cache(self) -> None:
        """Invalidate any cached properties on the instance."""
        try:
            del self.data
        except AttributeError:
            pass

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Save the record and invalidate the property caches."""
        super().save(*args, **kwargs)
        for field_name, value in self._staged_changes.items():
            self.set_attribute(field_name, value, commit=True)
        self._invalidate_cache()


class BaseRecordAttribute(models.Model):
    """A value for an attribute on a single Record."""

    ##
    # _VALUE_FIELD_PREFIX
    #
    # A prefix used to denote value fields for the attribute.
    #
    _VALUE_FIELD_PREFIX = "_value_"

    class Meta:
        abstract = True

    # The `record` and `field` are set by the implementing class.
    record: models.ForeignKey
    record_id: int
    field: models.ForeignKey
    field_id: int

    def __str__(self) -> str:
        return f"RecordAttribute {self.pk} (record_id={self.record_id}, field_id={self.field_id})"

    def __init__(
        self,
        *args: Any,
        record: Optional[BaseRecord] = None,
        field: Optional[BaseField] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, record=record, field=field, **kwargs)

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


FlexibleFormModel = Union[
    BaseForm,
    BaseField,
    BaseFieldModifier,
    BaseRecord,
    BaseRecordAttribute,
]

T = TypeVar("T", bound=FlexibleFormModel)


class FlexibleForms:
    """A class for generating new sets of concrete flexible form models.

    Enables users to have multiple sets of FlexibleForm models in their
    application.

    Effectively frees the developer from having to shoehorn all of their use
    cases into a single set of models and tables, and allows them to
    customize each set of models and tailor them to each specific use case.

    For example, in a school setting it might be useful to have a flexible
    model structure for Quizzes, and another one for Projects, each with
    their own set of models, database tables, and attributes:

    ```python
    # quizzes/models.py
    from django.contrib.auth import get_user_model
    from django.db import models
    from flexible_forms.models import BaseForm, BaseRecord
    from django.utils import timezone

    quizzes = FlexibleForms(model_prefix="Quiz")

    @quizzes
    class QuizAssignment(BaseForm):
        due = models.DateTimeField(default=timezone.now)

        class Meta(BaseForm.Meta):
            ordering = ("-due",)

    @quizzes
    class QuizSubmission(BaseRecord):
        student = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
        submitted = models.DateTimeField(default=timezone.now)
        grade = models.PositiveIntegerField()

    quizzes.make_flexible()
    ```

    ```python
    # projects/models.py
    from django.db import models
    from flexible_forms.models import BaseForm
    from django.utils import timezone

    projects = FlexibleForms(model_prefix="Project")

    @projects
    class ProjectAssignment(BaseForm):
        due = models.DateTimeField(default=timezone.now)
        grading_criteria = models.TextField()

        class Meta(BaseForm.Meta):
            ordering = ("-due",)

    projects.make_flexible()
    ```
    """

    finalized = False
    model_prefix: str
    module: str

    form_model: Optional[Type[BaseForm]] = None
    field_model: Optional[Type[BaseField]] = None
    field_modifier_model: Optional[Type[BaseFieldModifier]] = None
    record_model: Optional[Type[BaseRecord]] = None
    record_attribute_model: Optional[Type[BaseRecordAttribute]] = None

    def __init__(
        self, model_prefix: Optional[str] = None, module: Optional[str] = None
    ) -> None:
        """Initialize a group of flexible form models.

        Args:
            model_prefix: A string that will be prepended to each default
                model name. For example, specifying "Foo" for the model_prefix
                will cause any auto-generated models to start with "Foo". E.g.,
                "FooForm", "FooRecord", etc.
            module: The __module__ attribute to use for generated model
                classes. If left unspecified, uses `inspect` to determine the
                module name of the caller automatically.
        """
        self.model_prefix = model_prefix or ""
        self.module = (
            module
            or cast(ModuleType, inspect.getmodule(inspect.stack()[1][0])).__name__
        )
        self._finalizer = weakref.finalize(self, self._check_finalized, self)

    def make_flexible(self) -> None:
        """Build the flexible models.

        Adjusts the registered models so that they can be used with the
        flexible_forms tooling.
        """
        self.form_model = self._make_form_model()
        self.field_model = self._make_field_model(form_model=self.form_model)
        self.field_modifier_model = self._make_field_modifier_model(
            field_model=self.field_model
        )
        self.record_model = self._make_record_model(form_model=self.form_model)
        self.record_attribute_model = self._make_record_attribute_model(
            record_model=self.record_model, field_model=self.field_model
        )

        self.finalized = True

    def __call__(self, model: Type[T]) -> Type[T]:
        """Allows a FlexibleForms instance to be used as a decorator.

        Assigns the wrapped model class to the appropriate slot based on its
        type. The model must implement one of the flexible_forms base classes
        in order to work.

        Args:
            model: The model to register.

        Raises:
            ValueError: If the given model class does not extend one of the
                flexible_forms.models base classes.

        Returns:
            Type: The given model class.
        """
        if issubclass(model, BaseForm):
            self.form_model = model
        elif issubclass(model, BaseField):
            self.field_model = model
        elif issubclass(model, BaseFieldModifier):
            self.field_modifier_model = model
        elif issubclass(model, BaseRecord):
            self.record_model = model
        elif issubclass(model, BaseRecordAttribute):
            self.record_attribute_model = model
        else:
            raise ValueError(
                f"{model} must implement one of the flexible_forms.models.Base* classes."
            )
        return model

    def _make_form_model(self) -> Type[BaseForm]:
        """Prepare the Field model.

        Returns:
            Type[BaseForm]: The prepared Form class.
        """
        return self.form_model or self._default_model(BaseForm)

    def _make_field_model(self, form_model: Type[BaseForm]) -> Type[BaseField]:
        """Prepare the Field model.

        Args:
            form_model: The model to use when building the "form" foreign key association.

        Returns:
            Type[BaseField]: The prepared Field class.
        """
        field_model = self.field_model or self._default_model(BaseField)
        field_model.add_to_class(  # type: ignore
            "form",
            models.ForeignKey(
                form_model,
                on_delete=models.CASCADE,
                related_name="fields",
                editable=False,
            ),
        )
        return field_model

    def _make_field_modifier_model(
        self, field_model: Type[BaseField]
    ) -> Type[BaseFieldModifier]:
        """Prepare the FieldModifier model.

        Args:
            field_model: The model to use when building the "field" foreign key association.

        Returns:
            Type[BaseFieldModifier]: The prepared FieldModifier class.
        """
        field_modifier_model = self.field_modifier_model or self._default_model(
            BaseFieldModifier
        )
        field_modifier_model.add_to_class(  # type: ignore
            "field",
            models.ForeignKey(
                field_model,
                on_delete=models.CASCADE,
                related_name="modifiers",
                editable=False,
            ),
        )
        return field_modifier_model

    def _make_record_model(self, form_model: Type[BaseForm]) -> Type[BaseRecord]:
        """Prepare the Record model.

        Args:
            form_model: The model to use when building the "form" foreign key association.

        Returns:
            Type[BaseRecord]: The prepared Record model.
        """
        record_model = self.record_model or self._default_model(BaseRecord)
        record_model.add_to_class(  # type: ignore
            "form",
            models.ForeignKey(
                form_model,
                on_delete=models.CASCADE,
                related_name="records",
                # editable=False,
            ),
        )
        return record_model

    def _make_record_attribute_model(
        self, record_model: Type[BaseRecord], field_model: Type[BaseField]
    ) -> Type[BaseRecordAttribute]:
        """Build the RecordAttribute model.

        Args:
            record_model: The model to use when building the "record" foreign key association.
            field_model: The model to use when building the "field" foreign key association.

        Returns:
            Type[BaseRecordAttribute]: The prepared BaseRecordAttribute model class.
        """
        record_attribute_model = self.record_attribute_model or self._default_model(
            BaseRecordAttribute
        )
        record_attribute_model.add_to_class(  # type: ignore
            "record",
            models.ForeignKey(
                record_model,
                on_delete=models.CASCADE,
                related_name="attributes",
                editable=False,
            ),
        )
        record_attribute_model.add_to_class(  # type: ignore
            "field",
            models.ForeignKey(
                field_model,
                on_delete=models.CASCADE,
                related_name="attributes",
                editable=False,
            ),
        )
        return record_attribute_model

    def _default_model(self, base_model: Type[T]) -> Type[T]:
        """Create a default model from the given base model.

        Derives the model name by removing the "Base" prefix.

        Args:
            base_model: The base model from which to derive the default model.

        Returns:
            type: A new model class derived from the base model.
        """
        model_name = base_model.__name__.replace("Base", self.model_prefix)
        return type(
            model_name,
            (base_model,),
            {"__module__": self.module},
        )

    @staticmethod
    def _check_finalized(flexible_forms: "FlexibleForms") -> None:
        """Ensure that make_flexible has been called.

        Attempts to catch a developer mistake where they forget to call
        make_flexible after defining their model overrides.

        Args:
            flexible_forms: The FlexibleForms object to be checked.

        Raises:
            ImproperlyConfigured: If make_flexible has not been called on the
                object before exiting.
        """
        if not flexible_forms.finalized:
            raise ImproperlyConfigured(
                f"A FlexibleForms object was created in {flexible_forms.module}, but "
                f"`make_flexible` was never called on it."
            )
