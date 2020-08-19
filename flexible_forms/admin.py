# -*- coding: utf-8 -*-

"""Django admin configurations for flexible_forms."""

from typing import Any, Optional, cast

import swapper
from django import forms
from django.contrib import admin
from django.db import models
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils.safestring import SafeText, mark_safe

# Load our swappable models.
Field = swapper.load_model('flexible_forms', 'Field')
Form = swapper.load_model('flexible_forms', 'Form')
Record = swapper.load_model('flexible_forms', 'Record')


class FieldsInline(admin.StackedInline):
    """An inline representing a single field on an Form."""

    classes = ('collapse',)
    exclude = ('_order', 'label_suffix', 'sort_order')
    extra = 1
    model = Field
    fk_name = 'form'


class FormsAdmin(admin.ModelAdmin):
    """An admin configuration for managing flexible forms."""

    list_display = ('label', '_fields_count', '_records_count', '_add_record')

    inlines = (FieldsInline,)

    def get_queryset(self, *args: Any, **kwargs: Any) -> models.QuerySet[Form]:
        """Overrides the default queryset to optimize fetches.

        Args:
            args: (Passed to super)
            kwargs: (Passed to super)

        Returns:
            models.QuerySet[Form]: An optimized queryset.
        """
        return (
            super()
            .get_queryset(*args, **kwargs)
            .annotate(models.Count('records', distinct=True))
            .annotate(models.Count('fields', distinct=True))
        )

    def _fields_count(self, form: Form) -> int:
        """The number of fields related to this form.

        Args:
            form (Form): The form object.

        Returns:
            int: The number of fields on the form.
        """
        return form.fields__count  # type: ignore

    _fields_count.short_description = 'Fields'  # type: ignore
    _fields_count.admin_order_field = 'fields__count'  # type: ignore

    def _records_count(self, form: Form) -> SafeText:
        """The number of records related to this form.

        Args:
            form (Form): The form object.

        Returns:
            int: The number of records related to the form.
        """
        app_label = Record._meta.app_label  # noqa: WPS437
        model_name = Record._meta.model_name  # noqa: WPS437

        changelist_url = reverse(f'admin:{app_label}_{model_name}_changelist')
        filtered_changelist_url = f'{changelist_url}?form_id={form.pk}'
        record_count = form.records__count  # type: ignore

        return mark_safe(f'<a href="{filtered_changelist_url}">{record_count}</a>')  # noqa: S308, S703, E501

    _records_count.short_description = 'Records'  # type: ignore
    _records_count.admin_order_field = 'records__count'  # type: ignore

    def _add_record(self, form: Form) -> SafeText:
        app_label = Record._meta.app_label  # noqa: WPS437
        model_name = Record._meta.model_name  # noqa: WPS437

        add_url = reverse(
            f'admin:{app_label}_{model_name}_add',
        ) + f'?form_id={form.pk}'

        return mark_safe(f'<a href="{add_url}">Add record</a>')  # noqa: S308, S703, E501


admin.site.register(Form, FormsAdmin)


class RecordsAdmin(admin.ModelAdmin):
    """An admin configuration for managing records."""

    def get_queryset(
        self, *args: Any, **kwargs: Any,
    ) -> models.QuerySet[Record]:
        """Overrides the default queryset to optimize fetches.

        Args:
            args: (Passed to super)
            kwargs: (Passed to super)

        Returns:
            models.QuerySet[Record]: An optimized queryset.
        """
        return (
            super()
            .get_queryset(*args, **kwargs)
            .prefetch_related('attributes', 'form__fields')
        )

    def get_form(
        self,
        request: HttpRequest,
        obj: Optional[Record] = None,  # noqa: WPS110
        *args: Any,
        **kwargs: Any,
    ) -> forms.Form:
        """Return the Django Form definition for the record.

        Generated dynamically if the Record has a form defined.

        Args:
            request (HttpRequest): The current HTTP request.
            obj (Optional[Record]): The record for which to render the form.
            args: (Passed to super)
            kwargs: (Passed to super)

        Returns:
            forms.Form: The form object to be rendered.
        """
        if obj:
            return obj.form.as_form_class()

        return cast(
            forms.Form,
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
            request (HttpRequest): The current HTTP request.
            args: (Passed to super)
            kwargs: (Passed to super)

        Returns:
            HttpResponse: The HTTP response with the rendered view.
        """
        record = None
        form_id = request.GET.get('form_id')

        if form_id:
            record = Record.objects.create(
                form=Form.objects.get(pk=form_id),
            )

            app_label = record._meta.app_label  # noqa: WPS437
            model_name = record._meta.model_name  # noqa: WPS437
            change_url = reverse(
                f'admin:{app_label}_{model_name}_change',
                args=(record.pk,),
            )

            return HttpResponseRedirect(change_url)

        return super().add_view(request, *args, **kwargs)


admin.site.register(Record, RecordsAdmin)
