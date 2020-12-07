# -*- coding: utf-8 -*-
import difflib
import json
from unittest.util import safe_repr

import pytest
from django.forms.renderers import DjangoTemplates, Jinja2
from django.test.html import parse_html
from django.utils.datastructures import MultiValueDict

from flexible_forms.widgets import (
    AutocompleteSelect,
    AutocompleteSelectMultiple,
)

try:
    import jinja2
except ImportError:
    jinja2 = None

_RENDERER = Jinja2() if jinja2 else DjangoTemplates()


def check_html(widget, name, value, expected_html=None, attrs=None, **kwargs) -> bool:
    widget_html = widget.render(name, value, attrs=attrs, renderer=_RENDERER, **kwargs)

    if jinja2:
        widget_html = widget_html.replace("&#34;", "&quot;")
        widget_html = widget_html.replace("&#39;", "&#x27;")

    dom1 = parse_html(widget_html)
    dom2 = parse_html(expected_html or "")

    if dom1 != dom2:
        msg = "%s != %s" % (safe_repr(dom1, True), safe_repr(dom2, True))
        diff = "\n" + "\n".join(
            difflib.ndiff(
                str(dom1).splitlines(),
                str(dom2).splitlines(),
            )
        )
        pytest.fail(msg + diff)


def test_autocomplete_select_empty_optional() -> None:
    widget = AutocompleteSelect()
    widget.is_required = False

    expected_html = """
    <select
        class="admin-autocomplete"
        data-ajax--cache="true"
        data-ajax--delay="250"
        data-ajax--type="GET"
        data-ajax--url=""
        data-allow-clear="true"
        data-close-on-select="true"
        data-disabled="false"
        data-placeholder=""
        data-tags="true"
        data-theme="admin-autocomplete"
        name="test">
    <option value="">
    </select>
    """

    check_html(widget, name="test", value=None, expected_html=expected_html)


def test_autocomplete_select_empty_required() -> None:
    """Ensure that a required empty autocomplete has no blank option and cannot
    be cleared."""
    widget = AutocompleteSelect()
    widget.is_required = True

    field_name = "test"
    field_value = [""]

    # The widget value is extracted from the submitted form data. It is always
    # a list of strings, where each string is a stable JSON representation of a
    # selected option. The widget value is stored in the database.
    form_data = MultiValueDict({field_name: field_value})
    widget_value = widget.value_from_datadict(
        data=form_data, files=None, name=field_name
    )
    assert widget_value == []

    expected_html = """
    <select
        class="admin-autocomplete"
        data-ajax--cache="true"
        data-ajax--delay="250"
        data-ajax--type="GET"
        data-ajax--url=""
        data-allow-clear="false"
        data-close-on-select="true"
        data-disabled="false"
        data-placeholder=""
        data-tags="true"
        data-theme="admin-autocomplete"
        name="test">
    </select>
    """

    check_html(
        widget, name="test", value=json.dumps(widget_value), expected_html=expected_html
    )


def test_autocomplete_select_single_value_required() -> None:
    """Ensure that a required autocomplete renders its selected value as its
    only option."""
    widget = AutocompleteSelect()
    widget.is_required = True

    field_name = "test"
    field_value = ['{"id":"1","text":"Test option"}']

    # The widget value is extracted from the submitted form data. It is always
    # a list of strings, where each string is a stable JSON representation of a
    # selected option. The widget value is stored in the database.
    form_data = MultiValueDict({field_name: field_value})
    widget_value = widget.value_from_datadict(
        data=form_data, files=None, name=field_name
    )
    assert widget_value == [{"id": "1", "text": "Test option"}]

    expected_html = """
    <select
        class="admin-autocomplete"
        data-ajax--cache="true"
        data-ajax--delay="250"
        data-ajax--type="GET"
        data-ajax--url=""
        data-allow-clear="false"
        data-close-on-select="true"
        data-disabled="false"
        data-placeholder=""
        data-tags="true"
        data-theme="admin-autocomplete"
        name="test">
    <option selected value='{"id":"1","text":"Test option"}'>Test option</option>
    </select>
    """

    check_html(
        widget,
        name="test",
        value=json.dumps(widget_value),
        expected_html=expected_html,
    )


def test_autocomplete_select_single_value_freetext() -> None:
    """Ensure that a required autocomplete renders its selected value as its
    only option."""
    widget = AutocompleteSelect()
    widget.is_required = True

    field_name = "test"
    field_value = ["freetext option"]

    # The widget value is extracted from the submitted form data. It is always
    # a list of strings, where each string is a stable JSON representation of a
    # selected option. The widget value is stored in the database.
    form_data = MultiValueDict({field_name: field_value})
    widget_value = widget.value_from_datadict(
        data=form_data, files=None, name=field_name
    )
    assert widget_value == [{"id": "freetext option", "text": "freetext option"}]

    expected_html = """
    <select
        class="admin-autocomplete"
        data-ajax--cache="true"
        data-ajax--delay="250"
        data-ajax--type="GET"
        data-ajax--url=""
        data-allow-clear="false"
        data-close-on-select="true"
        data-disabled="false"
        data-placeholder=""
        data-tags="true"
        data-theme="admin-autocomplete"
        name="test">
    <option selected value='{"id":"freetext option","text":"freetext option"}'>freetext option</option>
    </select>
    """

    check_html(
        widget,
        name="test",
        value=json.dumps(widget_value),
        expected_html=expected_html,
    )


def test_autocomplete_select_freetext_error() -> None:
    """Ensure that an error is thrown for freetext values if allow_freetext is
    False."""
    widget = AutocompleteSelect()
    widget.allow_freetext = False

    with pytest.raises(ValueError):
        widget.value_from_datadict(data={"test": "freetext"}, files=None, name="test")


def test_autocomplete_select_format_decode() -> None:
    """Ensure that format_value returns non-JSON values as-is."""
    widget = AutocompleteSelect()

    values = (1, 1.0, "not json", {}, [])

    for value in values:
        assert widget.format_value(value) is value


def test_autocomplete_select_multiple_value_required() -> None:
    """Ensure that a required autocomplete renders its selected value as its
    only option."""
    widget = AutocompleteSelectMultiple()
    widget.is_required = True

    field_name = "test"
    field_value = [
        '{"id":"1","text":"Test option"}',
        '{"id":"2","text":"Test option 2"}',
    ]

    # The widget value is extracted from the submitted form data. It is always
    # a list of strings, where each string is a stable JSON representation of a
    # selected option. The widget value is stored in the database.
    form_data = MultiValueDict({field_name: field_value})
    widget_value = widget.value_from_datadict(
        data=form_data, files=None, name=field_name
    )
    assert widget_value == [
        {"id": "1", "text": "Test option"},
        {"id": "2", "text": "Test option 2"},
    ]

    expected_html = """
    <select
        class="admin-autocomplete"
        data-ajax--cache="true"
        data-ajax--delay="250"
        data-ajax--type="GET"
        data-ajax--url=""
        data-allow-clear="false"
        data-close-on-select="false"
        data-disabled="false"
        data-placeholder=""
        data-tags="true"
        data-theme="admin-autocomplete"
        multiple
        name="test">
    <option selected value='{"id":"1","text":"Test option"}'>Test option</option>
    <option selected value='{"id":"2","text":"Test option 2"}'>Test option 2</option>
    </select>
    """

    check_html(
        widget,
        name="test",
        value=json.dumps(widget_value),
        expected_html=expected_html,
    )