# django-flexible-forms

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
