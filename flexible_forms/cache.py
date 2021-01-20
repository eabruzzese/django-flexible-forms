# -*- coding: utf-8 -*-
from django.conf import settings
from django.core.cache import DEFAULT_CACHE_ALIAS, caches

cache = caches[getattr(settings, "FLEXIBLE_FORMS_CACHE", DEFAULT_CACHE_ALIAS)]
cache_prefix = "flexible_forms"
