# -*- coding: utf-8 -*-

"""Common utilities."""

import json
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    Type,
    TypeVar,
    Union,
)

import jmespath
from jmespath.parser import Parser
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


def jp(expr: str, data: Any, default: Any = None) -> Any:
    """A shorthand helper for querying dicts with jmespath.

    Args:
        expr: The JMESPath expression.
        data: The data to query.
        default: The default value to return if the query returns None.

    Returns:
        Any: The result of the query, or the value of default.
    """
    result = jmespath.search(expression=expr, data=data)
    return default if result is None else result


def get_expression_fields(jmespath_expression: str) -> Set[str]:
    """Return a list of fields referenced in the given JMESPath expression.

    Args:
        jmespath_expression: The expression for which to extract a list of
            referenced fields.

    Returns:
        Set[str]: A set containing the names of fields referenced in the
            expression.
    """
    return _get_fields(Parser().parse(jmespath_expression).parsed)


def _get_fields(
    node: Dict[str, Any], ignore_fields: Sequence[str] = ("null",)
) -> Set[str]:
    referenced_fields: Set[str] = set()

    node_type = node["type"]
    children = node["children"]
    value = node.get("value")

    if node_type == "field" and value not in ignore_fields:
        referenced_fields.add(str(value))
    elif node_type == "subexpression":
        referenced_fields.update(_get_fields(children[0]))
    else:
        referenced_fields.update(*(_get_fields(c) for c in children))

    return referenced_fields
