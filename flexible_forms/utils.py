# -*- coding: utf-8 -*-

"""Common utilities."""

from typing import Set, Type, TypeVar

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
