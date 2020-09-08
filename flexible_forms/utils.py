# -*- coding: utf-8 -*-

"""Common utilities."""

from typing import Any, Callable, Mapping, Optional, Sequence, Set, Type, TypeVar

from simpleeval import DEFAULT_FUNCTIONS, simple_eval

T = TypeVar('T', bound=Type)


def all_subclasses(cls: T) -> Set[T]:
    """Return a set of subclasses for the given class.

    Recurses through the class hierarchy to find all descendants.

    Args:
        cls (Type[Any]): The class for which to find all subclasses.

    Returns:
        Set[Type[Any]]: The set of all descendants of `cls`.
    """
    return set(cls.__subclasses__()).union([
        s for c in cls.__subclasses__() for s in all_subclasses(c)
    ])


def empty(value: Any, empty_values: Sequence = (None,)) -> bool:
    """Return True if the given value is "empty".

    Considers a value empty if it's iterable and has no elements, of if the
    value is in the given sequence of `empty_values` (only None by default).

    Args:
        value (Any): The value to test for emptiness.

    Returns:
        bool: True if the given value is empty.
    """
    if hasattr(value, '__iter__'):
        try:
            next(iter(value))
        except StopIteration:
            return True
        return False

    return value in empty_values


def evaluate_expression(expression: str, cast: Optional[Callable[..., Any]] = None, names: Optional[Mapping[str, Any]] = None) -> Any:
    """Safely evaluate a Python expression.

    Evaluates a Python expression in a controlled environment.

    Args:
        expression (str): The Python expression to evaluate.
        cast (Optional[Callable[..., Any]]): A callable that will be used to
            cast the value returned from the expression.
        kwargs (Any): Passed to simpleeval.simple_eval().

    Returns:
        Any: The value of the expression, cast using the given `cast`
            callable if specified.
    """
    cast = cast or (lambda v: v)

    value = simple_eval(expression, names=names, functions={
        **DEFAULT_FUNCTIONS.copy(),
        'empty': empty,
    })

    return cast(value)
