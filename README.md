# django-flexible-forms

![build](https://github.com/eabruzzese/django-flexible-forms/workflows/build/badge.svg)
[![codecov](https://codecov.io/gh/eabruzzese/django-flexible-forms/branch/master/graph/badge.svg)](https://codecov.io/gh/eabruzzese/django-flexible-forms)

> ⚠️ **Warning:** This project is currently under heavy active development
> and is not yet stable. It is not advisable to use this in any kind of
> production context.

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

## Setting up for development

To get the project up and running, you'll need [Poetry](https://python-poetry.org/docs/#installation).

Once you have Poetry installed, simply run:

```
$ bin/setup
```

To start the test project:

```
$ bin/start
```

You can log in to the Django admin of the test project with username `admin` and password `admin`.

## Running the test suite

To run the test suite, run:

```
$ bin/test
```
