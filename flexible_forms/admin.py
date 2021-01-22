# -*- coding: utf-8 -*-

"""Django admin configurations for flexible_forms."""

import logging
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Type,
    cast,
)

from django import forms
from django.conf import settings
from django.contrib import admin
from django.contrib.admin.options import InlineModelAdmin
from django.db import models
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils.safestring import SafeText, mark_safe

from flexible_forms.models import (
    AliasField,
    BaseField,
    BaseFieldModifier,
    BaseFieldset,
    BaseFieldsetItem,
    BaseForm,
    BaseRecord,
    FlexibleBaseModel,
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


DEFAULT_FORMFIELD_OVERRIDES = cast(
    Mapping[Type[models.Field], Mapping[str, Any]],
    {
        models.TextField: {
            "widget": forms.widgets.TextInput(
                attrs={
                    "size": "50",
                },
            ),
        },
    },
)


class FlexibleAdminMixin:
    """An admin class mixin for flexible form models."""

    model: Type[FlexibleBaseModel]
    formfield_overrides = DEFAULT_FORMFIELD_OVERRIDES

    @property
    def exclude(self) -> Sequence[str]:
        """Exclude alias fields from the admin form.

        Handles the case where the implementer has aliased one or more fields
        on the model.

        Returns:
            Tuple[str]: A tuple with the names of aliased fields.
        """
        return tuple(
            f.name for f in self.model._meta.fields if isinstance(f, AliasField)
        )


class FieldModifiersInline(FlexibleAdminMixin, TabularInline):
    """An inline representing a single modifier for a field on a form."""

    classes = ("collapse",)
    model = BaseFieldModifier
    extra = 1

    @property
    def fk_name(self) -> str:
        """Return the name of the field with a ForeignKey to the Field.

        Handles the case where the implementer has aliased the "field" field.

        Returns:
            str: The name of the field ForeignKey field.
        """
        original_fk_name = BaseFieldModifier.FlexibleMeta.field_field_name
        concrete_fk_name = next(  # pragma: no cover
            (
                f.original_field.name
                for f in self.model._meta.fields
                if isinstance(f, AliasField) and f.name == original_fk_name
            ),
            original_fk_name,
        )

        return concrete_fk_name


class FieldsInline(FlexibleAdminMixin, StackedInline):
    """An inline representing a single field on a Form."""

    classes = ("collapse",)
    model = BaseField
    extra = 1

    @property
    def fk_name(self) -> str:
        """Return the name of the field with a ForeignKey to the Form.

        Handles the case where the implementer has aliased the "form" field.

        Returns:
            str: The name of the form ForeignKey field.
        """
        original_fk_name = BaseField.FlexibleMeta.form_field_name
        concrete_fk_name = next(  # pragma: no cover
            (
                f.original_field.name
                for f in self.model._meta.fields
                if isinstance(f, AliasField) and f.name == original_fk_name
            ),
            original_fk_name,
        )

        return concrete_fk_name

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


class FieldsetItemsInline(FlexibleAdminMixin, TabularInline):
    """An inline representing an item in a fieldset on a Form."""

    model = BaseFieldsetItem
    extra = 1

    @property
    def fk_name(self) -> str:
        """Return the name of the field with a ForeignKey to the Fieldset.

        Handles the case where the implementer has aliased the "fieldset" field.

        Returns:
            str: The name of the fieldset ForeignKey field.
        """
        original_fk_name = BaseFieldsetItem.FlexibleMeta.fieldset_field_name
        concrete_fk_name = next(  # pragma: no cover
            (
                f.original_field.name
                for f in self.model._meta.fields
                if isinstance(f, AliasField) and f.name == original_fk_name
            ),
            original_fk_name,
        )

        return concrete_fk_name

    def formfield_for_foreignkey(
        self, db_field: models.Field, request: HttpRequest, **kwargs: Any
    ) -> forms.Field:
        """Modify ForeignKey fields before they're rendered to the form.

        Restricts the "field" choices to only include Fields for the current
        Form.

        Args:
            db_field: The model field to be rendered to the form.
            request: The current HTTP request.
            kwargs: Passed to super.

        Returns:
            forms.Field: A configured form field for the given db_field.
        """
        if db_field.name == "field":
            form_id = request.resolver_match.kwargs.get("object_id")
            Field = self.model._flexible_model_for(BaseField)
            kwargs["queryset"] = (
                Field._default_manager.filter(form=form_id)
                if form_id
                else Field._default_manager.none()
            )
        return cast(
            forms.Field, super().formfield_for_foreignkey(db_field, request, **kwargs)
        )


class FieldsetsInline(FlexibleAdminMixin, StackedInline):
    """An inline representing a fieldset on a Form."""

    classes = ("collapse",)
    model = BaseFieldset
    extra = 1

    @property
    def fk_name(self) -> str:
        """Return the name of the field with a ForeignKey to the Form.

        Handles the case where the implementer has aliased the "form" field.

        Returns:
            str: The name of the form ForeignKey field.
        """
        original_fk_name = BaseFieldset.FlexibleMeta.form_field_name
        concrete_fk_name = next(  # pragma: no cover
            (
                f.original_field.name
                for f in self.model._meta.fields
                if isinstance(f, AliasField) and f.name == original_fk_name
            ),
            original_fk_name,
        )

        return concrete_fk_name

    @property
    def inlines(self) -> Iterable[InlineModelAdmin]:
        """Return valid inlines for the given BaseFieldset implementation.

        Returns:
            Iterable[InlineModelAdmin]: An iterable of InlineModelAdmin classes.
        """
        return (
            *super().inlines,
            cast(
                FieldsetItemsInline,
                type(
                    "FieldsetItemsInline",
                    (FieldsetItemsInline,),
                    {
                        "model": self.model._flexible_model_for(
                            FieldsetItemsInline.model
                        ),
                    },
                ),
            ),
        )


class FormsAdmin(FlexibleAdminMixin, ModelAdmin):
    """An admin configuration for managing flexible forms."""

    class Meta:
        pass

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
                    {"model": self.model._flexible_model_for(FieldsInline.model)},
                ),
            ),
            cast(
                FieldsetsInline,
                type(
                    "FieldsetsInline",
                    (FieldsetsInline,),
                    {"model": self.model._flexible_model_for(FieldsetsInline.model)},
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

    def _fields_count(self, form: BaseForm) -> int:
        """The number of fields related to this form.

        Args:
            form: The form object.

        Returns:
            int: The number of fields on the form.
        """
        return form.fields__count  # type: ignore

    _fields_count.short_description = "Fields"  # type: ignore
    _fields_count.admin_order_field = "fields__count"  # type: ignore

    def _records_count(self, form: BaseForm) -> SafeText:
        """The number of records related to this form.

        Args:
            form: The form object.

        Returns:
            SafeText: The number of records related to the form in a
                hyperlink to the records listing with a filter for the form.
        """
        Record = form._flexible_model_for(BaseRecord)
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

    def _add_record(self, form: BaseForm) -> SafeText:
        Record = form._flexible_model_for(BaseRecord)
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


class RecordsAdmin(FlexibleAdminMixin, ModelAdmin):
    """An admin configuration for managing records."""

    class Meta:
        pass

    list_display = ("__str__", "_form_label")

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
        return cast(
            "models.QuerySet[BaseRecord]",
            (
                super()
                .get_queryset(*args, **kwargs)
                .select_related("form")
                .prefetch_related(
                    "form__fields__modifiers",
                    "form__fieldsets__items__field",
                    "attributes__field",
                )
            ),
        )

    def _form_label(self, record: BaseRecord) -> SafeText:
        """Return the label of the record's form.

        Links to the change form for the form.

        Args:
            record: The record for which to render the form label.

        Returns:
            SafeText: The label of the record's form, linked to the change
                page for that form.
        """
        Form = record.form._flexible_model_for(BaseForm)
        app_label = Form._meta.app_label  # noqa: WPS437
        model_name = Form._meta.model_name  # noqa: WPS437

        change_url = reverse(
            f"admin:{app_label}_{model_name}_change", args=(record.form.pk,)
        )

        return mark_safe(
            f'<a href="{change_url}">{record.form.label}</a>'
        )  # noqa: S308, S703, E501

    _form_label.short_description = "Form"  # type: ignore
    _form_label.admin_order_field = "form__label"  # type: ignore

    def get_fieldsets(
        self,
        request: HttpRequest,
        obj: Optional[models.Model] = None,
    ) -> List[Tuple[Optional[str], Dict[str, Any]]]:
        """Return the fieldset configuration for the form.

        If the form has a fieldset configuration, use it instead of the
        default.
        """
        default_fieldsets = cast(
            List[Tuple[Optional[str], Dict[str, Any]]],
            super().get_fieldsets(request, obj),
        )

        if obj is None:
            return default_fieldsets

        record = cast("BaseRecord", obj)

        # If the record's form specifies a fieldsets configuration, use it.
        # Otherwise, default to Django admin behavior.
        fieldsets = record.form.as_django_fieldsets() or default_fieldsets

        if fieldsets is not default_fieldsets:
            form = self.get_form(request, record)
            form_fields = frozenset(form.base_fields.keys())  # type: ignore
            record_fields = tuple(
                f.name
                for f in record._meta.get_fields(include_parents=True)
                if f.name in form_fields
            )

            # If the record model has top-level attributes (in addition to
            # dynamic form attributes), add a metadata fieldset for managing
            # them.
            if record_fields:
                fieldsets = [
                    *fieldsets,
                    ("Metadata", {"fields": record_fields}),
                ]

        return fieldsets

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
                obj.as_django_form(
                    data=request.POST,
                    files=request.FILES,
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
        form_id = request.GET.get("form_id")
        Form = self.model._flexible_model_for(BaseForm)

        if form_id:
            record = self.model._default_manager.create(
                form=Form._default_manager.get(pk=form_id),
            )

            app_label = record._meta.app_label  # noqa: WPS437
            model_name = record._meta.model_name  # noqa: WPS437
            change_url = reverse(
                f"admin:{app_label}_{model_name}_change",
                args=(record.pk,),
            )

            return HttpResponseRedirect(change_url)

        return cast(HttpResponse, super().add_view(request, *args, **kwargs))
