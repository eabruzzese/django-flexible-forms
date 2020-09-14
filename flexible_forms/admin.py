# -*- coding: utf-8 -*-

"""Django admin configurations for flexible_forms."""

import logging
from typing import TYPE_CHECKING, Any, Optional, Type, cast

from django import forms
from django.conf import settings
from django.contrib import admin
from django.db import models
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils.safestring import SafeText, mark_safe

logger = logging.getLogger(__name__)

##
# Nested admin support
#
# If the project has the nested_admin Django app installed, we'll try to use it
# so that field modifiers can be configured via the Django Admin.
#
if "nested_admin" in settings.INSTALLED_APPS:
    from nested_admin.nested import NestedModelAdmin as ModelAdmin
    from nested_admin.nested import NestedStackedInline as StackedInline
    from nested_admin.nested import NestedTabularInline as TabularInline
else:  # pragma: no cover
    ModelAdmin = admin.ModelAdmin
    StackedInline = admin.StackedInline
    TabularInline = admin.TabularInline

from flexible_forms.utils import (
    get_field_model,
    get_field_modifier_model,
    get_form_model,
    get_record_model,
)

# Load our swappable models.
Field = get_field_model()
FieldModifier = get_field_modifier_model()
Form = get_form_model()
Record = get_record_model()

if TYPE_CHECKING:  # pragma: no cover
    from flexible_forms.models import BaseForm, BaseRecord


class FieldModifiersInline(TabularInline):
    """An inline representing a single modifier for a field on a form."""

    # classes = ('collapse',)
    extra = 1
    model = FieldModifier

    formfield_overrides = {
        models.TextField: {
            "widget": forms.widgets.TextInput(
                attrs={
                    "size": "50",
                },
            ),
        },
    }


class FieldsInline(StackedInline):
    """An inline representing a single field on a Form."""

    classes = ("collapse",)
    exclude = ("_order", "label_suffix")
    extra = 1
    model = Field
    fk_name = "form"

    formfield_overrides = {
        models.TextField: {
            "widget": forms.widgets.TextInput(
                attrs={
                    "size": "50",
                },
            ),
        },
    }

    inlines = (FieldModifiersInline,)


class FormsAdmin(ModelAdmin):
    """An admin configuration for managing flexible forms."""

    formfield_overrides = {
        models.TextField: {
            "widget": forms.widgets.TextInput(
                attrs={
                    "size": "50",
                },
            ),
        },
    }

    list_display = ("label", "_fields_count", "_records_count", "_add_record")

    inlines = (FieldsInline,)

    def get_queryset(self, *args: Any, **kwargs: Any) -> "models.QuerySet[BaseForm]":
        """Overrides the default queryset to optimize fetches.

        Args:
            args: (Passed to super)
            kwargs: (Passed to super)

        Returns:
            models.QuerySet[Form]: An optimized queryset.
        """
        return cast(
            "models.QuerySet[BaseForm]",
            (
                super()
                .get_queryset(*args, **kwargs)
                .annotate(models.Count("records", distinct=True))
                .annotate(models.Count("fields", distinct=True))
            ),
        )

    def _fields_count(self, form: "BaseForm") -> int:
        """The number of fields related to this form.

        Args:
            form: The form object.

        Returns:
            int: The number of fields on the form.
        """
        return form.fields__count  # type: ignore

    _fields_count.short_description = "Fields"  # type: ignore
    _fields_count.admin_order_field = "fields__count"  # type: ignore

    def _records_count(self, form: "BaseForm") -> SafeText:
        """The number of records related to this form.

        Args:
            form: The form object.

        Returns:
            SafeText: The number of records related to the form in a
                hyperlink to the records listing with a filter for the form.
        """
        app_label = Record._meta.app_label  # noqa: WPS437
        model_name = Record._meta.model_name  # noqa: WPS437

        changelist_url = reverse(f"admin:{app_label}_{model_name}_changelist")
        filtered_changelist_url = f"{changelist_url}?form_id={form.pk}"
        record_count = form.records__count  # type: ignore

        return mark_safe(
            f'<a href="{filtered_changelist_url}">{record_count}</a>'
        )  # noqa: S308, S703, E501

    _records_count.short_description = "Records"  # type: ignore
    _records_count.admin_order_field = "records__count"  # type: ignore

    def _add_record(self, form: "BaseForm") -> SafeText:
        app_label = Record._meta.app_label  # noqa: WPS437
        model_name = Record._meta.model_name  # noqa: WPS437

        add_url = (
            reverse(
                f"admin:{app_label}_{model_name}_add",
            )
            + f"?form_id={form.pk}"
        )

        return mark_safe(
            f'<a href="{add_url}">Add record</a>'
        )  # noqa: S308, S703, E501


admin.site.register(Form, FormsAdmin)


class RecordsAdmin(admin.ModelAdmin):
    """An admin configuration for managing records."""

    def get_queryset(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> "models.QuerySet[BaseRecord]":
        """Overrides the default queryset to optimize fetches.

        Args:
            args: (Passed to super)
            kwargs: (Passed to super)

        Returns:
            models.QuerySet[BaseRecord]: An optimized queryset.
        """
        return (
            super()
            .get_queryset(*args, **kwargs)
            .select_related("form")
            .prefetch_related("form__fields__field_modifiers", "attributes__field")
        )

    def get_form(
        self,
        request: HttpRequest,
        obj: Optional["BaseRecord"] = None,
        *args: Any,
        **kwargs: Any,
    ) -> Type[forms.BaseForm]:
        """Return the Django Form definition for the record.

        Generated dynamically if the Record has a form defined.

        Args:
            request: The current HTTP request.
            obj: The record for which to render the form.
            args: (Passed to super)
            kwargs: (Passed to super)

        Returns:
            forms.Form: The form object to be rendered.
        """
        if obj:
            return (
                cast(
                    "BaseForm",
                    obj.form,
                )
                .as_django_form(
                    request.POST,
                    request.FILES,
                    instance=obj,
                )
                .__class__
            )

        return cast(
            Type[forms.BaseForm],
            super().get_form(request, obj, *args, **kwargs),
        )

    def add_view(
        self,
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> HttpResponse:
        """Overrides add_view to create a dynamic record.

        Uses the query parameters to create a new record of the given type.

        Args:
            request: The current HTTP request.
            args: (Passed to super)
            kwargs: (Passed to super)

        Returns:
            HttpResponse: The HTTP response with the rendered view.
        """
        record = None
        form_id = request.GET.get("form_id")

        if form_id:
            record = Record.objects.create(
                form=Form.objects.get(pk=form_id),
            )

            app_label = record._meta.app_label  # noqa: WPS437
            model_name = record._meta.model_name  # noqa: WPS437
            change_url = reverse(
                f"admin:{app_label}_{model_name}_change",
                args=(record.pk,),
            )

            return HttpResponseRedirect(change_url)

        return super().add_view(request, *args, **kwargs)


admin.site.register(Record, RecordsAdmin)
