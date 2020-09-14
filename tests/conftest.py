# -*- coding: utf-8 -*-

"""Pytest fixtures and configuration."""

import uuid
from contextlib import _GeneratorContextManager, contextmanager
from datetime import timedelta
from io import BytesIO
from typing import (
    Any,
    Callable,
    Generator,
    Iterator,
    Mapping,
    Optional,
    Type,
    TypeVar,
    Union,
    cast,
)

import pytest
from django import forms
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import models, transaction
from hypothesis import strategies as st
from hypothesis.errors import InvalidArgument
from hypothesis.extra.django import register_field_strategy
from hypothesis.extra.django._fields import _global_field_lookup
from PIL import Image

T = TypeVar("T")
Fixture = Generator[T, None, None]
ContextManagerFixture = Fixture[Callable[..., _GeneratorContextManager]]


@pytest.fixture(scope="session")
def rollback() -> ContextManagerFixture:
    """A fixture for providing an automatic rollback context manager.

    Yields a context manager that will automatically roll back any database changes
    made within its scope.

    Particularly useful when using Hypothesis to bypass its limitations with Pytest.

    Args:
        db: The Django database. Unused locally, but required to enable database
            access for the fixture.

    Yields:
        Callable[[], None]: A context manager that will roll back any database changes
            made within its scope.
    """

    @contextmanager
    def _rollback() -> Iterator:
        """Automatically roll back any database changes made while yielding."""
        sid = transaction.savepoint()
        try:
            yield
        except BaseException:
            transaction.savepoint_rollback(sid)
            raise
        finally:
            transaction.savepoint_rollback(sid)

    yield _rollback


def _generate_uploaded_file(
    name: Optional[str] = None,
    content: Optional[bytes] = None,
    content_type: Optional[str] = None,
) -> SimpleUploadedFile:
    """Generate an uploaded file object.

    Simulates a file that has been uploaded and handled by Django.

    Args:
        name: The name of the file. Defaults to a newly-generated
            UUIDv4 if left unspecified.
        content: The contents of the file. Defaults to an empty
            bytestring if left unspectified.
        content_type: The Content-Type of the file. Defaults to
            "application/octet-stream" (a binary file) if left unspecified.

    Returns:
        SimpleUploadedFile: An object returned by Django representing a handle to the file.
    """
    return SimpleUploadedFile(
        str(name or uuid.uuid4().hex),
        content or b"",
        content_type=(content_type or "application/octet-stream"),
    )


def file_strategy(
    **strategies: st.SearchStrategy,
) -> st.SearchStrategy[SimpleUploadedFile]:
    """Define a binary file upload generation strategy for Hypothesis.

    Args:
        strategies: Keyword arguments to be passed to the builds strategy
            for _generate_uploaded_file.

    Returns:
        st.SearchStrategy[SimpleUploadedFile]: A Hypothesis search strategy that
            will generate random binary files to simulate file uploads.
    """
    builds_strategies: Mapping[str, st.SearchStrategy] = {
        "content": st.binary(min_size=1),
        "content_type": st.just("application/octet-stream"),
        **strategies,
    }

    return st.builds(_generate_uploaded_file, **builds_strategies)


@st.composite
def image_strategy(
    draw: Callable[..., Any], **strategies: st.SearchStrategy
) -> SimpleUploadedFile:
    """Define an image file upload generation strategy for Hypothesis.

    Args:
        strategies: Keyword arguments to be passed to the file_strategy.

    Returns:
        st.SearchStrategy[SimpleUploadedFile]: A Hypothesis search strategy that
            will generate random image files to simulate file uploads.
    """
    # Generate a new 100x100 image.
    image = draw(
        st.builds(
            Image.new,
            mode=st.just("RGB"),
            size=st.tuples(
                st.integers(min_value=100, max_value=4096),
                st.integers(min_value=100, max_value=4096),
            ),
        ),
    )

    # Save the image to a BytesIO buffer with a random PIL-supported image
    # format.
    image_format = draw(
        st.sampled_from(
            [
                "BMP",
                "DIB",
                "EPS",
                "GIF",
                "IM",
                "JPEG",
                "MPO",
                "PCX",
                "PNG",
                "PPM",
                "SPIDER",
                "TGA",
                "TIFF",
                "WEBP",
            ]
        ),
    )

    image_bytes = draw(st.just(BytesIO()))
    draw(
        st.builds(
            image.save,
            st.just(image_bytes),
            format=st.just(image_format),
        ),
    )

    # Generate the file using a modified file_strategy.
    builds_strategies: Mapping[str, st.SearchStrategy] = {
        "name": st.just(f"image.{image_format.lower()}"),
        "content": st.just(image_bytes.getvalue()),
        "content_type": st.just(f"image/{image_format.lower()}"),
        **strategies,
    }

    return cast(SimpleUploadedFile, draw(file_strategy(**builds_strategies)))


def using_sqlite() -> bool:
    """Return True if the database engine in use is SQLite.

    Returns:
        bool: True if the database engine in use is SQLite.
    """
    try:
        return (
            getattr(settings, "DATABASES", {})
            .get("default", {})
            .get("ENGINE", "")
            .endswith(".sqlite3")
        )
    except ImproperlyConfigured:
        return None


@pytest.fixture(scope="session")
def duration_strategy() -> st.SearchStrategy[timedelta]:
    """Handle DurationField values.

    SQLite stores timedeltas as six bytes of microseconds and therefore needs
    special handling.

    Returns:
        st.SearchStrategy[timedelta]: A search strategy for timedeltas,
            modified for SQLite if needed.
    """
    if using_sqlite():
        delta = timedelta(microseconds=2 ** 47 - 1)
        return st.timedeltas(-delta, delta)
    return st.timedeltas()


@pytest.fixture(scope="session")
def patch_field_strategies() -> ContextManagerFixture:
    """Return a monkey-patcher for Hypothesis field strategies."""

    @contextmanager
    def _patch_field_strategy(
        strategies: Mapping[
            Union[Type[models.Model], Type[forms.Field]], st.SearchStrategy[Any]
        ],
    ) -> Iterator:
        """Monkey-patch a Hypothesis field strategy.

        Resets the strategy to its original value when finished.
        """
        original_strategies = {}

        for field_class, new_strategy in strategies.items():
            # Retrieve the original strategy.
            original_strategies[field_class] = _global_field_lookup.get(
                field_class,
            )

            # Patch in the new strategy.
            _global_field_lookup[field_class] = new_strategy

        # Yield to the caller.
        try:
            yield

        # Revert to the original strategy (or remove it, if there was no
        # original strategy).
        finally:
            for field_class, original_strategy in original_strategies.items():
                del _global_field_lookup[field_class]
                if original_strategy:
                    _global_field_lookup[field_class] = original_strategy

    return _patch_field_strategy


_hypothesis_initialized = False


def _initialize_hypothesis() -> None:
    """Performs initialization for Hypothesis.

    Registers field generation strategies for types not natively
    supported by the Hypothesis Django integration.
    """

    try:
        # The OrderWrt fields are automatically set to None.
        register_field_strategy(models.OrderWrt, st.none())

        # Files and images have valid data generated for them using our
        # strategies.
        register_field_strategy(models.FileField, file_strategy())
        register_field_strategy(forms.FileField, file_strategy())
        register_field_strategy(models.ImageField, image_strategy())
        register_field_strategy(forms.ImageField, image_strategy())
    except InvalidArgument:
        pass


# Initialize Hypothesis.
_initialize_hypothesis()
