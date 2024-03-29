# -*- coding: utf-8 -*-
from django.dispatch import Signal

# Signals emitted before and after preparing a Django form class from a BaseForm.
pre_form_class_prepare = Signal()
post_form_class_prepare = Signal()

# Signals emitted before and after building the fieldsets for a BaseForm.
pre_fieldsets_prepare = Signal()
post_fieldsets_prepare = Signal()

# Signals emitted before and after initializing a Record form.
pre_form_init = Signal()
post_form_init = Signal()

# Signals emitted before and after cleaning and validating a Record form.
pre_form_clean = Signal()
post_form_clean = Signal()

# Signals emitted before and after saving a Record form.
pre_form_save = Signal()
post_form_save = Signal()
