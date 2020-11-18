# -*- coding: utf-8 -*-
from django.urls import path

from . import views

app_name = "flexible_forms"
urlpatterns = [
    path(
        "autocomplete/<str:field_app_label>/<str:field_model_name>/<int:field_pk>",
        views.autocomplete,
        name="autocomplete",
    ),
]
