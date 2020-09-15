from django.contrib import admin

from flexible_forms.admin import (
    FormsAdmin as BaseFormsAdmin,
    RecordsAdmin as BaseRecordsAdmin
)
from test_app.models import (
    Form,
    Record
)

class FormsAdmin(BaseFormsAdmin):
    model = Form

#admin.site.register(Form, FormsAdmin)

class RecordsAdmin(BaseRecordsAdmin):
    model = Record

#admin.site.register(Record, RecordsAdmin)
