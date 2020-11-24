# -*- coding: utf-8 -*-
from django.urls import path

from . import views

app_name = "flexible_forms"
urlpatterns = [
    path(
        "<str:app_label>/<str:model_name>/<int:field_pk>/autocomplete",
        views.autocomplete,
        name="autocomplete",
    ),
]
