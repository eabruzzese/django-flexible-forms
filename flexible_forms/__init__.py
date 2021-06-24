# -*- coding: utf-8 -*-
import django

try:
    from importlib.metadata import version
except ImportError:  # pragma: no cover
    from importlib_metadata import version

# Django < 3.2 needs default_app_config in order to correctly register the app
# without specifying the full module path in settings.py
if django.VERSION < (3, 2):  # pragma: no-cover
    default_app_config = "flexible_forms.apps.FlexibleFormsConfig"

try:
    __version__ = version(__name__)
except:
    pass
