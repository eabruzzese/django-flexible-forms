# -*- coding: utf-8 -*-
import django

try:
    from importlib.metadata import version
except ImportError:  # pragma: no cover
    from importlib_metadata import version  # type: ignore

if django.VERSION < (3, 2):
    default_app_config = "flexible_forms.apps.FlexibleFormsConfig"

try:
    __version__ = version(__name__)
except:
    pass
