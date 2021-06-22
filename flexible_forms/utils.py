# -*- coding: utf-8 -*-

"""Common utilities."""

import json
from functools import lru_cache, singledispatch
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Type,
    TypeVar,
    Union,
)

import jmespath
from django.db import DatabaseError
from django.db.backends.base.base import BaseDatabaseWrapper
from django.template import Context, Template
from django.template.base import VariableNode
from jmespath.parser import Parser
from simpleeval import DEFAULT_FUNCTIONS, DEFAULT_OPERATORS, EvalWithCompoundTypes

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


class FormEvaluator(EvalWithCompoundTypes):
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


@lru_cache(128)
def get_expression_fields(jmespath_expression: str) -> Tuple[str, ...]:
    """Return a list of fields referenced in the given JMESPath expression.

    Args:
        jmespath_expression: The expression for which to extract a list of
            referenced fields.

    Returns:
        Set[str]: A set containing the names of fields referenced in the
            expression.
    """
    return tuple(_get_fields(Parser().parse(jmespath_expression).parsed).keys())


def _get_fields(
    node: Dict[str, Any], ignore_fields: Sequence[str] = ("null",)
) -> Dict[str, None]:
    referenced_fields: Dict[str, None] = {}

    node_type = node["type"]
    children = node["children"]
    value = node.get("value")

    if node_type == "field" and value not in ignore_fields:
        referenced_fields[str(value)] = None
    elif node_type == "subexpression":
        referenced_fields.update(_get_fields(children[0]))
    else:
        for child in children:
            referenced_fields.update(_get_fields(child))

    return referenced_fields


class NOT_PROVIDED:
    """A proxy type for specifying that something was not defined.

    Useful when None is a valid value.
    """


class RenderedString(str):
    """A string with an attribute containing the render context.

    The __context__ property will be a dict containing the keys of the variables
    used to render the string. Variables in the original context that were not
    used to render the string will be excluded. Variables that were referenced
    in the string but not provided in the context should use the NOT_PROVIDED
    proxy value.
    """

    __context__: Dict[str, Any]


@singledispatch
def interpolate(data: Any, context: Dict[str, Any], strict=True) -> Any:
    """Interpolate the given data using DTL.

    Handles (nested) dicts and lists and will interpolate strings containing DTL tokens.

    Args:
        data: The data to be interpolated.
        context: The context with which to interpolate strings containing DTL tokens.
        strict: When True, an exception will be raised if the data
            references a variable that is not provided in the context.

    Returns:
        Any: The interpolated data.
    """
    # The default implementation returns the data as-is.
    return data


@interpolate.register(str)
def _interpolate_str(data: str, context: Dict[str, Any], strict=True) -> RenderedString:
    """Handles interpolation of string values.

    Interpolates strings using the default Django Template Language engine.

    Args:
        data: The data to be interpolated.
        context: The context with which to interpolate strings containing DTL tokens.

    Returns:
        RenderedString: The rendered string with a __context__ property
            containing the variables used in rendering.
    """
    # Render the given string as a Django template with the given context.
    template = Template(data)
    template_context = Context(context, autoescape=False)
    rendered_string = RenderedString(template.render(template_context))

    # Extract a dict of variables used to render the string.
    rendered_context = {
        var: template_context.get(var, NOT_PROVIDED)
        for var in frozenset(
            v.filter_expression.var.lookups[0]
            for v in template.nodelist
            if isinstance(v, VariableNode)
        )
    }

    # Attach the render context to the string.
    rendered_string.__context__ = rendered_context

    missing_variables = frozenset(k for k, v in rendered_context.items() if v is NOT_PROVIDED)
    if strict and missing_variables:
        raise LookupError(
            f'The template references variables that were not in the context '
            f'provided: {", ".join(missing_variables)}')

    return rendered_string


@interpolate.register(dict)
def _interpolate_dict(data: dict, context: Dict[str, Any], strict=True) -> dict:
    """Handles interpolation of dict values.

    Interpolates the values of the dict as appropriate (renders strings, or
    recurses for list or dict values).

    Args:
        data: The data to be interpolated.
        context: The context with which to interpolate strings containing DTL tokens.

    Returns:
        dict: The interpolated dict.
    """
    return {k: interpolate(v, context, strict) for k, v in data.items()}


@interpolate.register(list)
def _interpolate_list(data: list, context: Dict[str, Any], strict=True) -> list:
    """Handles interpolation of list values.

    Interpolates the elements of the list as appropriate (renders strings, or
    recurses for list or dict elements).

    Args:
        data: The list to be interpolated.
        context: The context with which to interpolate strings containing DTL tokens.

    Returns:
        list: The interpolated list.
    """
    return [interpolate(v, context, strict) for v in data]


# Determine if the database support trigram similarity by checking for
# the pg_trgm extension.
def check_supports_pg_trgm(connection: BaseDatabaseWrapper) -> bool:
    """Determine if trigram similarity support is present.

    Attempts to run a query against the extensions table in PostgreSQL to
    look for the pg_trgm extension. Failures assume a lack of support.

    Args:
        connection: The database connection.

    Returns:
        bool: True if trigram support is present.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM pg_extension
                WHERE extname = 'pg_trgm' LIMIT 1;
            """
            )
            return bool(cursor.fetchone())
    except DatabaseError:
        return False


def collect_annotations(obj: Type) -> Dict[str, Type]:
    """Collects annotations from an object hierarchy."""
    annotations = getattr(obj, "__annotations__", {})
    for base in obj.__bases__:
        annotations = {
            **annotations,
            **collect_annotations(base)
        }
    return annotations


def make_autocomplete_option(value: Dict[str, Any]) -> str:
    pass