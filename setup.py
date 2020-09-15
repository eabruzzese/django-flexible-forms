# -*- coding: utf-8 -*-

# DO NOT EDIT THIS FILE!
# This file has been autogenerated by dephell <3
# https://github.com/dephell/dephell

try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

readme = ''

setup(
    long_description=readme,
    name='django-flexible-forms',
    version='0.2.0',
    description='A reusable Django app for managing database-backed forms.',
    python_requires='==3.*,>=3.6.0',
    author='Eric Abruzzese',
    author_email='eric.abruzzese@gmail.com',
    license='MIT',
    packages=['flexible_forms'],
    package_dir={"": "."},
    package_data={},
    install_requires=[
        'django>=2.2',
        'importlib-metadata==1.*,>=1.7.0; python_version < "3.8"',
        'simpleeval==0.*,>=0.9.10', 'swapper==1.*,>=1.1.2'
    ],
    extras_require={
        "dev": [
            "autopep8==1.*,>=1.5.4", "black==20.*,>=20.8.0.b1",
            "darglint==1.*,>=1.5.4", "django-nested-admin==3.*,>=3.3.2",
            "django-stubs==1.*,>=1.5.0", "docformatter==1.*,>=1.3.1",
            "factory-boy==3.*,>=3.0.1", "hypothesis[django]==5.*,>=5.26.0",
            "isort==5.*,>=5.4.2", "mypy>=0.770", "pillow==7.*,>=7.2.0",
            "psycopg2-binary==2.*,>=2.8.6", "pydocstyle==5.*,>=5.1.1",
            "pytest==6.*,>=6.0.1", "pytest-cov==2.*,>=2.10.1",
            "pytest-django==3.*,>=3.9.0", "pytest-randomly==3.*,>=3.4.1",
            "pytest-timeout==1.*,>=1.4.2", "sphinx==3.*,>=3.2.1",
            "sphinx-autoapi==1.*,>=1.5.0"
        ]
    },
)
