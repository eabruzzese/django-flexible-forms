# -*- coding: utf-8 -*-

"""Django admin configurations for flexible_forms."""

import logging
from typing import Any, Iterable, Optional, Type, cast

from django import forms
from django.conf import settings
from django.contrib import admin
from django.contrib.admin.options import InlineModelAdmin
from django.db import models
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils.safestring import SafeText, mark_safe

from flexible_forms.models import (
    BaseField,
    BaseFieldModifier,
    BaseForm,
    BaseRecord,
)

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


class FieldModifiersInline(TabularInline):
    """An inline representing a single modifier for a field on a form."""

    classes = ("collapse",)
    model = BaseFieldModifier
    extra = 1

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
    model = BaseField
    extra = 1
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

    @property
    def inlines(self) -> Iterable[InlineModelAdmin]:
        """Return valid inlines for the given BaseField implementation.

        Returns:
            Iterable[InlineModelAdmin]: An iterable of InlineModelAdmin classes.
        """
        return (
            *super().inlines,
            cast(
                FieldModifiersInline,
                type(
                    "FieldModifiersInline",
                    (FieldModifiersInline,),
                    {
                        "model": self.model._flexible_model_for(BaseFieldModifier),
                    },
                ),
            ),
        )


class FormsAdmin(ModelAdmin):
    """An admin configuration for managing flexible forms."""

    class Meta:
        pass

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

    @property
    def inlines(self) -> Iterable[InlineModelAdmin]:
        """Return valid inlines for the given BaseForm implementation.

        Returns:
            Iterable[InlineModelAdmin]: An iterable of InlineModelAdmin classes.
        """
        return (
            *super().inlines,
            cast(
                FieldsInline,
                type(
                    "FieldsInline",
                    (FieldsInline,),
                    {"model": self.model._flexible_model_for(BaseField)},
                ),
            ),
        )

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
        Record = self.model
        app_label = Record._meta.app_label  # noqa: WPS437
        model_name = Record._meta.model_name  # noqa: WPS437

        changelist_url = reverse(f"admin:{app_label}_{model_name}_changelist")
        filtered_changelist_url = f"{changelist_url}?_form_id={form.pk}"
        record_count = form.records__count  # type: ignore

        return mark_safe(
            f'<a href="{filtered_changelist_url}">{record_count}</a>'
        )  # noqa: S308, S703, E501

    _records_count.short_description = "Records"  # type: ignore
    _records_count.admin_order_field = "records__count"  # type: ignore

    def _add_record(self, form: "BaseForm") -> SafeText:
        Record = form._flexible_model_for(BaseRecord)
        app_label = Record._meta.app_label  # noqa: WPS437
        model_name = Record._meta.model_name  # noqa: WPS437

        add_url = (
            reverse(
                f"admin:{app_label}_{model_name}_add",
            )
            + f"?_form_id={form.pk}"
        )

        return mark_safe(
            f'<a href="{add_url}">Add record</a>'
        )  # noqa: S308, S703, E501


class RecordsAdmin(admin.ModelAdmin):
    """An admin configuration for managing records."""

    class Meta:
        pass

    # Type hints.
    model: Type[BaseRecord]

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
            .select_related("_form")
            .prefetch_related("_form__fields__modifiers", "_attributes__field")
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
            return type(
                obj._form.as_django_form(
                    request.POST,
                    request.FILES,
                    instance=obj,
                )
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
        form_id = request.GET.get("_form_id")
        Form = self.model._flexible_model_for(BaseForm)

        if form_id:
            record = self.model._default_manager.create(
                _form=Form._default_manager.get(pk=form_id),
            )

            app_label = record._meta.app_label  # noqa: WPS437
            model_name = record._meta.model_name  # noqa: WPS437
            change_url = reverse(
                f"admin:{app_label}_{model_name}_change",
                args=(record.pk,),
            )

            return HttpResponseRedirect(change_url)

        return super().add_view(request, *args, **kwargs)
