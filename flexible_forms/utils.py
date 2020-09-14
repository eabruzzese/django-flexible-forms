# -*- coding: utf-8 -*-

"""Common utilities."""

from typing import (
    TYPE_CHECKING,
    Any,
    Mapping,
    Optional,
    Set,
    Type,
    TypeVar,
    Union,
    cast,
)

import swapper
from simpleeval import DEFAULT_FUNCTIONS, DEFAULT_OPERATORS, SimpleEval

if TYPE_CHECKING:  # pragma: no cover
    from flexible_forms.models import (
        BaseField,
        BaseFieldModifier,
        BaseForm,
        BaseRecord,
        BaseRecordAttribute,
    )

    SwappableModel = Type[
        Union[
            BaseForm,
            BaseField,
            BaseFieldModifier,
            BaseRecord,
            BaseRecordAttribute,
        ]
    ]

T = TypeVar("T", bound=Type)


def all_subclasses(cls: T) -> Set[T]:
    """Return a set of subclasses for the given class.

    Recurses through the class hierarchy to find all descendants.

    Args:
        cls: The class for which to find all subclasses.

    Returns:
        Set[T]: The set of all descendants of `cls`.
    """
    return set(cls.__subclasses__()).union(
        [s for c in cls.__subclasses__() for s in all_subclasses(c)]
    )


def empty(value: Any) -> bool:
    """Return True if the given value is "empty".

    Considers a value empty if it's iterable and has no elements, of if the
    value is in the given sequence of `empty_values` (only None by default).

    Args:
        value: The value to test for emptiness.

    Returns:
        bool: True if the given value is empty.
    """
    if hasattr(value, "__iter__"):
        try:
            next(iter(value))
        except StopIteration:
            return True
        return False

    return value is None


class FormEvaluator(SimpleEval):
    """An evaluator subclass for evaluating form expressions."""

    OPERATORS = {
        **DEFAULT_OPERATORS.copy(),
    }

    FUNCTIONS = {
        **DEFAULT_FUNCTIONS.copy(),
        "empty": empty,
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs = {
            **kwargs,
            "operators": self.OPERATORS,
            "functions": self.FUNCTIONS,
        }
        super().__init__(*args, **kwargs)


def evaluate_expression(
    expression: str,
    names: Optional[
        Mapping[
            str,
            Any,
        ]
    ] = None,
    **kwargs: Any,
) -> Any:
    """Safely evaluate a Python expression.

    Evaluates a Python expression in a controlled environment.

    Args:
        expression: The Python expression to evaluate.
        names: A mapping of variable names and
            their values available to the expression.
        kwargs: Passed to the FormEvaluator constructor.

    Returns:
        Any: The value of the expression, cast using the given `cast`
            callable if specified.
    """
    evaluator = FormEvaluator(names=names)
    return evaluator.eval(expression)


def _get_swappable_model(model_name: str) -> "SwappableModel":
    """Return a swappable model class from its name.

    Args:
        model_name: The name of the swappable model.

    Returns:
        Type[SwappableModel]: The model class for the swappable model.
    """
    return cast("SwappableModel", swapper.load_model("flexible_forms", model_name))


def get_form_model() -> Type["BaseForm"]:
    """Return the configured Form model.

    Returns:
        Type[BaseForm]: The configured Form model.
    """
    return cast(Type["BaseForm"], _get_swappable_model("Form"))


def get_field_model() -> Type["BaseField"]:
    """Return the configured Field model.

    Returns:
        Type[BaseField]: The configured Field model.
    """
    return cast(Type["BaseField"], _get_swappable_model("Field"))


def get_field_modifier_model() -> Type["BaseFieldModifier"]:
    """Return the configured FieldModifier model.

    Returns:
        Type[BaseFieldModifier]: The configured FieldModifier model.
    """
    return cast(Type["BaseFieldModifier"], _get_swappable_model("FieldModifier"))


def get_record_model() -> Type["BaseRecord"]:
    """Return the configured Record model.

    Returns:
        Type[BaseRecord]: The configured Record model.
    """
    return cast(Type["BaseRecord"], _get_swappable_model("Record"))


def get_record_attribute_model() -> Type["BaseRecordAttribute"]:
    """Return the configured RecordAttribute model.

    Returns:
        Type[BaseRecordAttribute]: The configured RecordAttribute model.
    """
    return cast(Type["BaseRecordAttribute"], _get_swappable_model("RecordAttribute"))
