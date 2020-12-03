# -*- coding: utf-8 -*-
from django.dispatch import Signal

# Signals emitted before and after initializing a Record form.
pre_form_init = Signal()
post_form_init = Signal()

# Signals emitted before and after cleaning and validating a Record form.
pre_form_clean = Signal()
post_form_clean = Signal()

# Signals emitted before and after saving a Record form.
pre_form_save = Signal()
post_form_save = Signal()
