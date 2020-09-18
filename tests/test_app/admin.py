# -*- coding: utf-8 -*-
from django.contrib import admin
from test_app.models import AppForm, AppRecord

from flexible_forms.admin import FormsAdmin, RecordsAdmin


class AppFormsAdmin(FormsAdmin):
    """An admin class for managing AppForm objects."""


admin.site.register(AppForm, AppFormsAdmin.for_model(AppForm))


class AppRecordsAdmin(RecordsAdmin):
    """An admin class for managing AppRecord objects."""


admin.site.register(AppRecord, AppRecordsAdmin)
