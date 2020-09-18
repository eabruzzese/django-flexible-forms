# django-flexible-forms

![build](https://github.com/eabruzzese/django-flexible-forms/workflows/build/badge.svg)
[![codecov](https://codecov.io/gh/eabruzzese/django-flexible-forms/branch/master/graph/badge.svg)](https://codecov.io/gh/eabruzzese/django-flexible-forms)

The `django-flexible-forms` module allows you to define forms in your
database and use them like regular ol' Django forms.

Features include:

- Database-driven form configuration. Define your forms and their fields with
  database records. Great for form builders.
- A familiar Django forms API. No special syntax or vocabulary necessary for
  core features. Create your `Form` in the database, call `as_django_form()` on
  it, and you'll have a run-of-the-mill `django.forms.ModelForm` instance.
- Dynamic form support. Wanna hide a field until another field is filled out,
  or only require a field based on the current form state? You can configure
  those behaviors by adding `FieldModifier`s to your form fields.

# Table of Contents

- [django-flexible-forms](#django-flexible-forms)
  - [Installation](#installation)
    - [1. Install the package.](#1-install-the-package)
    - [2. Add it to your INSTALLED_APPS in settings.py.](#2-add-it-to-your-installed_apps-in-settingspy)
    - [3. Decide if you want to customize the models](#3-decide-if-you-want-to-customize-the-models)
  - [Quickstart](#quickstart)
    - [1. Define a Form in your database.](#1-define-a-form-in-your-database)
    - [2. Get a Django form from your Form model.](#2-get-a-django-form-from-your-form-model)
    - [3. Save the form to create a Record.](#3-save-the-form-to-create-a-record)
    - [4. Add FieldModifiers to your Fields to make your form dynamic.](#4-add-fieldmodifiers-to-your-fields-to-make-your-form-dynamic)
  - [Customizing the models](#customizing-the-models)
    - [1. Extend the base model for the model you want to customize.](#1-extend-the-base-model-for-the-model-you-want-to-customize)
    - [2. Tell django-flexible-forms that you want to use your model instead of the built-in one.](#2-tell-django-flexible-forms-that-you-want-to-use-your-model-instead-of-the-built-in-one)
    - [3. Be sure to use the get_modelname_model() utilities when referencing your form class.](#3-be-sure-to-use-the-get_modelname_model-utilities-when-referencing-your-form-class)
    - [models.py](#modelspy)
    - [settings.py](#settingspy)
  - [Field types](#field-types)
    - [Built-in field types](#built-in-field-types)
    - [Writing custom field types](#writing-custom-field-types)
      - [1. Create a class that extends flexible_forms.fields.FieldType](#1-create-a-class-that-extends-flexible_formsfieldsfieldtype)
      - [2. Migrate the database.](#2-migrate-the-database)
      - [3. Use your new field type.](#3-use-your-new-field-type)
  - [Setting up for development](#setting-up-for-development)
  - [Running the test suite](#running-the-test-suite)

## Installation

### 1. Install the package.

```
pip install django-flexible-forms
```

### 2. Add it to your `INSTALLED_APPS` in `settings.py`.

```python
# your_app/settings.py

# ...

INSTALLED_APPS = (
    # ...
    'flexible_forms',
    # ...
)

# ...
```

### 3. Decide if you want to customize the models

`django-flexible-forms` provides swappable models so that you can add your
own fields to them as needed.

> ⚠️ **Note:** It's recommended that you do this during installation if
> you're going to do it: migrating a swappable model later can be painful and
> time-consuming.

To for details on model customization, see the [Customizing the models](#customizing-the-models) section.

## Quickstart Tutorial

### 1. Define a `Form` in your database.

Forms are created with the Django ORM. Just create a new `Form` instance and add some `Field`s to it.

> **Note:** All of `django-flexible-forms`' models are swappable with your
> own implementations, which is why we're using `get_form_model()` and
> `get_field_model()` in the example below.
>
> See the section on [customizing the models]() for more details.

```python
from flexible_forms.utils import get_form_model, get_field_model

Form = get_form_model()
Field = get_field_model()

# Forms are created with the Django ORM.
form = Form.objects.create(label='Bridgekeeper')

# You can add a field and customize almost anything about it. Only the `label`
# and `field_type` are required.
form.fields.create(
    # While not required, it is recommended to set the name attribute
    # explicitly. It's used frequently to reference and store your form data.
    name='your_name',
    # Field types are specified by the class name of the FieldType. See
    # below for a list of the built-in field types, and a guide on how to write
    # your own (it's easy!).
    field_type='SingleLineTextField',
    # The rest of the model attributes are just the common constructor
    # parameters of a django.forms.Field object.
    label='What... is your name',
    label_suffix='?',
    help_text='Tell me your full name.',
    required=True,
    initial='',
    # Attributes specific to a field type are stored in the form_field_options
    # JSON field on the model.
    form_field_options={'max_length': 255},
    # The form field widget can also be customized with form_widget_options.
    form_widget_options={'attrs': {'size': 50}},
)
```

### 2. Get a Django form from your `Form` model.

Once you have a `Form` with some `Field`s configured, just call
`as_django_form()` on it to get a `django.forms.ModelForm`.

```python
django_form = form.as_django_form()
print(django_form.is_valid())  # False
print(django_form.errors)  # {'your_name': ['This field is required.']}
```

The `as_django_form()` method has the same signature as the `ModelForm`
constructor. You can pass it `data`, `files`, `instance`, `initial`, etc as
needed.

```python
django_form = form.as_django_form(data={'your_name': 'Sir Lancelot of Camelot'})
print(django_form.is_valid())  # True
```

### 3. Save the form to create a `Record`.

If you call `save()` on the `ModelForm` you got from `as_django_form()`,
it'll create (or update) a `Record` instance. Your data can be accessed via
the `data` property.

```python
record = django_form.save()
record.save()
print(record.data)  # {'your_name': 'Sir Lancelot of Camelot'}
```

You can pass the record back to `as_django_form` as the `instance` to update records.

```python
django_form = form.as_django_form(instance=record)
print(django_form.is_valid())  # True
print(django_form.cleaned_data)  # {'form': <Form: Form object (1)> , 'your_name': 'Sir Lancelot of Camelot'}
```

### 4. Add `FieldModifier`s to your `Field`s to make your form dynamic.

You can make a field change its behavior based on the current set of field
values. For example, you may want to make a field required only if another
field has a value. We can add `FieldModifier`s to our `Field`s to achieve
this.

A `FieldModifier` has two fields:

- `attribute`: The attribute that you want to modify dynamically.
- `expression`: A simple Python expression that returns the value that should
  be assigned to the `attribute` on the field.

```python
# Let's add another Field to our form that's only required if the first field
# is filled out.
your_quest_field = form.fields.create(
    name='your_quest',
    label='What... is your quest?',
    field_type='MultiLineTextField',
    required=True,
)
quest_field.modifiers.create(
    # The attribute is an arbitrary string in the FieldModifier model, but it
    # is expected to be either an attribute of a `django.forms.Field` object,
    # or have a custom handler implemented for it.
    attribute='required',
    # Expressions have access to the values of every field on the form. Each
    # field's value gets assigned to a variable using the field's name.
    expression='not your_name'
)
```

Now, when you call `as_django_form()`, the `expression` will be evaluated
with the current set of form inputs and assigned to `required`. In essence,
this happens:

```python
django_form = form.as_django_form()

# Under the hood (simplified)...
your_name_value = django_form.data.get('your_name')
django_form.fields.your_quest.required = not your_name_value
```

> **Note:** Expression evaluation is handled by the excellent
> [simpleeval](https://github.com/danthedeckie/simpleeval) library, and is
> currently limited to a very small set of operations (basic math, emptiness
> checks, random number helpers). Broader support and customization are
> coming soon.

## Customizing the models

`django-flexible-forms` allows you to swap out the implementation for any or all of the models it provides. This can be useful for adding your own metadata fields or relationships without having to hack around the fact that you're using a third-party module.

> **Note:** It is **highly** recommended that you do this before putting it into production. Migrating a swappable model later can be painful and time consuming.

Customizing the models is pretty simple.

### 1. Extend the base model for the model you want to customize.

```python
# your_app/models.py

from django.db import models
from flexible_forms.models import BaseForm

class AppForm(BaseForm):
    # Add your custom attributes, etc.
    custom_attribute = models.TextField()
```

### 2. Tell `django-flexible-forms` that you want to use your model instead of the built-in one.

```python
# your_app/settings.py

FLEXIBLE_FORMS_FORM_MODEL = "your_app.AppForm"
```

### 3. Be sure to use the `get_modelname_model()` utilities when referencing your form class.

```python
from flexible_forms.utils import get_form_model

Form = get_form_model()  # your_app.AppForm
```

Here's a few handy "kitchen sink" snippets you can use if you want to
override all of the builtin models:

### Example `models.py`

```python
# your_app/models.py

from flexible_forms.models import (
    BaseForm,
    BaseField,
    BaseFieldModifier,
    BaseRecord,
    BaseRecordAttribute
)

class Form(BaseForm):
    """A custom implementation of flexible_forms.Form."""

class Field(BaseField):
    """A custom implementation of flexible_forms.Field."""

class FieldModifier(BaseFieldModifier):
    """A custom implementation of flexible_forms.FieldModifier."""

class Record(BaseRecord):
    """A custom implementation of flexible_forms.Record."""

class RecordAttribute(BaseRecordAttribute):
    """A custom implementation of flexible_forms.RecordAttribute."""
```

### Example `settings.py`

```python
# your_app/settings.py

# Swappable model overrides for flexible_forms
FLEXIBLE_FORMS_FORM_MODEL = "your_app.Form"
FLEXIBLE_FORMS_FIELD_MODEL = "your_app.Field"
FLEXIBLE_FORMS_RECORD_MODEL = "your_app.Record"
FLEXIBLE_FORMS_RECORDATTRIBUTE_MODEL = "your_app.RecordAttribute"
FLEXIBLE_FORMS_FIELDMODIFIER_MODEL = "your_app.FieldModifier"
```

## Field types

A field type is a class that extends `flexible_forms.fields.FieldType`. Each
of these classes is essentially a configuration object (with a small API) that
bundles together a `django.forms.FormField`, a `django.forms.widgets.Widget`,
and a `django.db.models.Field` into a factory object that can produce
configured form and model fields.

### Built-in field types

Here's a list of all of the built-in field types.

| Field Type                     | Form Field            | Form Widget              | Model Field            |
| ------------------------------ | --------------------- | ------------------------ | ---------------------- |
| `CheckboxField`                | `BooleanField`        | `CheckboxInput`          | `BooleanField`         |
| `DurationField`                | `DurationField`       | `TextInput`              | `DurationField`        |
| `DateTimeField`                | `DateTimeField`       | `DateTimeInput`          | `DateTimeField`        |
| `ImageUploadField`             | `ImageField`          | `ClearableFileInput`     | `ImageField`           |
| `TimeField`                    | `TimeField`           | `TimeInput`              | `TimeField`            |
| `FileUploadField`              | `FileField`           | `ClearableFileInput`     | `FileField`            |
| `DateField`                    | `DateField`           | `DateInput`              | `DateField`            |
| `MultipleChoiceCheckboxField`  | `MultipleChoiceField` | `CheckboxSelectMultiple` | `JSONField`            |
| `DecimalField`                 | `DecimalField`        | `NumberInput`            | `DecimalField`         |
| `MultipleChoiceSelectField`    | `MultipleChoiceField` | `SelectMultiple`         | `JSONField`            |
| `PositiveIntegerField`         | `IntegerField`        | `NumberInput`            | `PositiveIntegerField` |
| `SingleChoiceRadioSelectField` | `ChoiceField`         | `RadioSelect`            | `TextField`            |
| `IntegerField`                 | `IntegerField`        | `NumberInput`            | `IntegerField`         |
| `SingleChoiceSelectField`      | `ChoiceField`         | `Select`                 | `TextField`            |
| `SensitiveTextField`           | `CharField`           | `PasswordInput`          | `TextField`            |
| `YesNoUnknownSelectField`      | `TypedChoiceField`    | `Select`                 | `BooleanField`         |
| `URLField`                     | `URLField`            | `URLInput`               | `URLField`             |
| `YesNoSelectField`             | `TypedChoiceField`    | `Select`                 | `BooleanField`         |
| `EmailField`                   | `EmailField`          | `EmailInput`             | `EmailField`           |
| `YesNoUnknownRadioField`       | `TypedChoiceField`    | `RadioSelect`            | `BooleanField`         |
| `MultiLineTextField`           | `CharField`           | `Textarea`               | `TextField`            |
| `YesNoRadioField`              | `TypedChoiceField`    | `RadioSelect`            | `BooleanField`         |
| `SingleLineTextField`          | `CharField`           | `TextInput`              | `TextField`            |

### Writing custom field types

The library has lots of built-in field types, but you'll almost certainly
want to implement your own.

Common reasons to implement your own field type include:

- You need a `ChoiceField` with options fetched from a QuerySet.
- You want to change the widget for a field.
- You want to create a complex field that uses multiple fields to collect information.
- You want to handle a custom `attribute` for a `FieldModifier`.

Luckily, creating a custom field type is easy, and most use cases only
require a few lines of code.

#### 1. Create a class that extends `flexible_forms.fields.FieldType`

Field types are mostly configuration. Just create a new class that extends `flexible_forms.forms.FieldType` and set your options:

- **`label`** Is the human-readable name of the field type. It'll show up in
  the dropdown for selecting a field type in the Django admin.
- **`form_field_class`** is the `django.forms.Field` class that you want to use to
  represent the form field, e.g. `forms.CharField` or `forms.IntegerField`.
  They're all supported, so use whatever you want (or make your own!).
- **`form_field_options`** is a `dict` of parameters that will be passed to the
  `form_field_class` when the field gets added to a form.
- **`form_widget_class`** is the `django.forms.widgets.Widget` class that you want
  to use to display the form field. You only need to specify this if the
  default widget for your `form_field_class` isn't sufficient for your use case
  (e.g., you want to use a `RadioSelect` instead of a `Select`, or something).
- **`form_widget_options`**, like `form_field_options`, is a dict of parameters
  passed to the `form_widget_class` constructor when the field gets added to
  a form. It's not often used, but comes in handy sometimes for manipulating
  the rendered HTML element.

```python
from django import forms
from django.contrib.auth import get_user_model
from flexible_forms.fields import FieldType

User = get_user_model()

class StaffUserEmailDropdownField(FieldType):
    """A dropdown of Users with the is_staff flag.

    Stores the email address instead of the primary key.
    """
    label = "Staff User (Email)"

    # We want a ModelChoiceField.
    form_field_class = forms.ModelChoiceField
    form_field_options = {
        # Populate the options with a list of staff users.
        'queryset': User.objects.filter(is_staff=True),
        # Set a more descriptive label for the empty option.
        'empty_label': 'Select a staff member',
        # Use the email address as the value instead of the primary key.
        'to_field_name': 'email',
    }
    # Specify the widget (only needed if the default isn't sufficient, but
    # specified here for demo purposes).
    form_widget_class = forms.widgets.Select
    form_widget_options = {
        # Turn off autocomplete for the <select> widget.
        'autocomplete': 'off'
    }
    # Store the selected value in an EmailField.
    model_field_class = models.EmailField
```

#### 2. Migrate the database.

Once you've defined your new field type, `django-flexible-forms` will find it
automatically (it finds all of the subclasses of `FieldType`). Just migrate
the database to get it added to the list of supported field types, and use it
like you would any other field. Adding a new field type does not alter any
data; it's just updating metadata for the model.

#### 3. Use your new field type.

Now when you're building your forms, you can use the class name of your field
type for `Field.field_type`. For example:

```python
form.fields.create(
    label='Staff User',
    field_type='StaffUserEmailDropdownField'
)

# Alternatively...
from my_app.custom_field_types import StaffUserEmailDropdownField

form.fields.create(
    label='Staff User',
    # Field types have a `name()` method that's used under the hood.
    field_type=StaffUserEmailDropdownField.name()
)
```

## Setting up for development

To get the project up and running, you'll want to install the requirements using [Poetry](https://python-poetry.org/docs/#installation):

```
$ poetry install
```

Then set up the test project:

```
$ tests/manage.py migrate --run-syncdb
$ tests/manage.py shell --command "from django.contrib.auth.models import User; User.objects.create_superuser('admin', 'admin@example.com', 'admin')"
$ tests/manage.py runserver 127.0.0.1:9001
$ open http://127.0.0.1:9001/admin
```

You can log in to the Django admin of the test project with username `admin` and password `admin`.

## Running the test suite

To run the test suite, just invoke `pytest` on the `tests/` directory:

```
$ pytest tests/
```
