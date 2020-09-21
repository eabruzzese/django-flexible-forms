# -*- coding: utf-8 -*-

"""Model definitions for the flexible_forms module."""

import inspect
import logging
import weakref
from types import ModuleType
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Set,
    Type,
    TypeVar,
    Union,
    cast,
)

from django import forms
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models, transaction
from django.db.models.manager import BaseManager
from django.db.models.query import Prefetch
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

logger = logging.getLogger(__name__)

# If we're only type checking, import things that would otherwise cause an
# ImportError due to circular dependencies.
if TYPE_CHECKING:  # pragma: no cover
    from flexible_forms.forms import BaseRecordForm

FlexibleModel = Union[
    "BaseForm",
    "BaseField",
    "BaseFieldModifier",
    "BaseRecord",
    "BaseRecordAttribute",
]

T = TypeVar(
    "T",
    bound=FlexibleModel,
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


class FlexibleBaseModel(models.Model):
    """A common base for all FlexibleField base models."""

    class Meta:
        abstract = True

    # A mapping of base model class to its implementation.
    _flexible_models: Mapping[Any, Any] = {}

    @classmethod
    def _flexible_model_for(cls, base_model: Type[T]) -> Type[T]:
        """Return the current implementation of the given base_model.

        Args:
            base_model: The flexible_forms base model for which to return the implementation.

        Returns:
            Type[FleixbleModel]: The model class for the given base model in
                the current implementation.
        """
        return cast(Type[T], cls._flexible_models[base_model])


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

    # Type hints for inbound relationships.
    fields: "BaseManager[BaseField]"
    records: "BaseManager[BaseRecord]"

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

        # Derive the Record model from the relationship field.
        Record = self._flexible_model_for(BaseRecord)

        instance = instance or Record(_form=self)  # type: ignore
        data = cast(Mapping[str, Any], {**(data or instance._data), "_form": self.pk})
        files = cast(Mapping[str, Any], files or {})
        initial = cast(Mapping[str, Any], {**(initial or {}), "_form": self.pk})

        class_name = self.name.title().replace("_", "")
        form_class_name = f"{class_name}Form"
        all_fields = self.fields.all()
        field_values = {
            **instance._data,
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
            # HACK: If the widget allows for multiple selections, make sure the
            # value is a list. This method should be refactored to use
            # MultiValueDict structures instead.
            if getattr(form_field.widget, "allow_multiple_selected", False):
                field_value = [field_value]
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
                    "_form__fields",
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

    # The `_form` is set by the implementing class.
    _form: BaseForm
    _form_id: int
    _attributes: "BaseManager[BaseRecordAttribute]"

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

    def __str__(self) -> str:
        return f"Record {self.pk} (_form_id={self._form_id if self._form else None})"

    def __init__(
        self, *args: Any, _form: Optional[BaseForm] = None, **kwargs: Any
    ) -> None:
        super().__init__(*args, _form=_form, **kwargs)
        self._staged_changes = {}
        self._initialized = True

    @property
    def _fields(self) -> Mapping[str, BaseField]:
        """Return a map of Fields for the Record's form, keyed by their names.

        Returns:
            Mapping[str, BaseField]: A mapping of Field instances by their
                names.
        """
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
        if not self._initialized or name.startswith("_"):
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
        if not self._initialized or name.startswith("_"):
            super().__setattr__(name, value)
            return

        if name in frozenset(f.name for f in self._meta.get_fields()):
            super().__setattr__(name, value)
            return

        RecordAttribute = self._flexible_model_for(BaseRecordAttribute)
        self._staged_changes[name] = RecordAttribute(
            record=self,  # type: ignore
            field=self._fields[name],
            value=value,
        ).value
        self._invalidate_cache()

    def _invalidate_cache(self) -> None:
        """Invalidate cached properties on the Record."""
        try:
            del self._data
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
        RecordAttribute = self._flexible_model_for(BaseRecordAttribute)
        attribute_map = {a.field.name: a for a in self._attributes.all()}

        value_fields: Set[str] = set()
        update: List[BaseRecordAttribute] = []
        insert: List[BaseRecordAttribute] = []
        for field_name, value in self._staged_changes.items():
            # Find the existing attribute object or create a new one.
            attribute = attribute_map.get(field_name) or RecordAttribute(
                record=self,  # type: ignore
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

        # Invalidate the cache.
        self._invalidate_cache()


class BaseRecordAttribute(FlexibleBaseModel):
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
    record: BaseRecord
    record_id: int
    field: BaseField
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

        # Generate a map of base models to their implementations and copy it to
        # each flexible model. This makes it easier to get the model(s) we need
        # for business logic.
        model_map = {
            BaseForm: self.form_model,
            BaseField: self.field_model,
            BaseFieldModifier: self.field_modifier_model,
            BaseRecord: self.record_model,
            BaseRecordAttribute: self.record_attribute_model,
        }

        for model_class in model_map.values():
            model_class._flexible_models = model_map

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
            "_form",
            models.ForeignKey(
                form_model,
                on_delete=models.CASCADE,
                related_name="records",
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
                related_name="_attributes",
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
