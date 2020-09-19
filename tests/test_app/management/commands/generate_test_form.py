# -*- coding: utf-8 -*-
from argparse import ArgumentParser
from typing import Any

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction

from flexible_forms.fields import FIELD_TYPES


class Command(BaseCommand):
    help = 'Generates a "kitchen sink" form with every field type for testing.'

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Parse command arguments.

        Args:
            parser: The argument parser.
        """
        parser.add_argument(
            "--model", help="The app_label.ModelName of the target Form model."
        )
        parser.add_argument("label", help="The label of the Form record.")

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        """Generate a form with every field type for testing.

        Args:
            args: Other arguments passed to handle.
            options: Parsed arguments to the command.
        """
        Form = apps.get_model(*options["model"].split("."))
        form = Form._default_manager.create(label=options["label"])

        # Create a field in the form for every defined field type.
        for field_type in FIELD_TYPES.keys():
            form.fields.create(
                name=field_type,
                label=f"Test {field_type} Field",
                field_type=field_type,
                required=False,
            )

        self.stdout.write(self.style.SUCCESS("Done!"))
