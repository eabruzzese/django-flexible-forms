# -*- coding: utf-8 -*-
from importlib.metadata import version

default_app_config = "flexible_forms.apps.FlexibleFormsConfig"

try:
    __version__ = version(__name__)
except:
    pass
