# -*- coding: utf-8 -*-

"""Common utilities."""

import json
from typing import (
    TYPE_CHECKING,
    Any,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Type,
    TypeVar,
    Union,
)

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
    evaluator = FormEvaluator(names=names, **kwargs)
    return evaluator.eval(expression)


def replace_element(
    needle: Any,
    replacement: Any,
    haystack: Union[List[Any], Tuple[Any, ...]],
) -> Union[List[Any], Tuple[Any, ...]]:
    """Replace a value recursively in a given data structure.

    Args:
        needle: The element to replace.
        replacement: The replacement value.
        haystack: The data structure in which to find and replace values.

    Returns:
        Union[List[Any], Tuple[Any, ...]]: A new data structure of the given
            type with the desired elements replaced.
    """
    elements = type(haystack)()
    for element in haystack:
        if isinstance(element, str):
            element = replacement if element == needle else element
        else:
            element = replace_element(needle, replacement, element)
        elements = type(haystack)([*elements, element])
    return elements


def stable_json(data: Union[dict, list]) -> str:
    """Generate a stable string representation of the given dict or list.

    Args:
        data: The dict or list for which to produce a stable JSON
            representation.

    Returns:
        str: A stable JSON string representation of the given data.
    """
    return json.dumps(
        data, sort_keys=True, ensure_ascii=True, separators=(",", ":"), default=str
    )


from string import Formatter


class LenientFormatter(Formatter):
    """A more lenient version of the default string formatter.

    If a given variable was not specified in the format() kwargs, its value will be an empty string.

    For example:

    >>> formatter = LenientFormatter()
    >>> test_string = "This variable was not provided: {not_provided}, but this one was: {provided}."
    >>> formatter.format(test_string, provided="a value")
    >>> 'This variable was not provided: , but this one was: a value.'
    """

    def get_value(
        self, key: Union[int, str], args: Sequence[Any], kwargs: Mapping[str, Any]
    ) -> Any:
        """Return the value for the given key from the args or kwargs.

        If the key does not exist in the args or kwargs, an empty string is
        returned.

        Args:
            key: The name of the string variable for which to resolve the
                value.
            args: Positional arguments given to format().
            kwargs: keyword arguments given to format().

        Returns:
            Any: The value for key, if given, otherwise an empty string.
        """
        try:
            return super().get_value(key, args, kwargs)
        except (KeyError, IndexError):
            return ""
