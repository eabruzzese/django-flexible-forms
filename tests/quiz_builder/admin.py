# -*- coding: utf-8 -*-
from django.contrib import admin
from quiz_builder.models import Quiz, QuizSubmission

from flexible_forms.admin import FormsAdmin, RecordsAdmin

admin.site.register(Quiz, FormsAdmin)


admin.site.register(QuizSubmission, RecordsAdmin)
