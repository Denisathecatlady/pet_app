"""Create the role groups of docs/07 §7.6.

The names are frozen here on purpose (migrations must not import app code that may
change later); they must match ``accounts.roles.Role``.
"""

from django.db import migrations

ROLE_NAMES = ("owner", "vet", "data_curator", "nutrition_reviewer")


def create_roles(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in ROLE_NAMES:
        Group.objects.get_or_create(name=name)


def delete_roles(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=ROLE_NAMES).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [migrations.RunPython(create_roles, delete_roles)]
