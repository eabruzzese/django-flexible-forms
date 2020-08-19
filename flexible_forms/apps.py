# -*- coding: utf-8 -*-

"""Flexible forms.

A Django app to support configuration-driven forms backed by the
database.
"""

from django.apps import AppConfig


class FlexibleFormsConfig(AppConfig):
    """A Django admin configuration for flexible_forms.

    Handles initialization logic for the flexible_forms app.
    """

    name = 'flexible_forms'
    verbose_name = 'Flexible Forms'
