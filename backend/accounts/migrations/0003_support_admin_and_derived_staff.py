"""Role ``support_admin`` and ``User.is_staff`` derived from the roles (docs/14 §14.2).

The names are frozen here on purpose (migrations must not import app code that may change
later); they must match ``accounts.roles``. The data step sets ``is_staff`` of every existing
user to its derived value: true for superusers and members of a staff role, false for everybody
else. A user who was flagged ``is_staff`` by hand without a role loses access to the
administration; give them a role.
"""

from django.db import migrations, models

SUPPORT_ADMIN = "support_admin"
STAFF_ROLE_NAMES = ("data_curator", "nutrition_reviewer", SUPPORT_ADMIN)


def create_support_admin_and_derive_staff(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    User = apps.get_model("accounts", "User")
    Group.objects.get_or_create(name=SUPPORT_ADMIN)
    staff = models.Q(is_superuser=True) | models.Q(groups__name__in=STAFF_ROLE_NAMES)
    staff_ids = User.objects.filter(staff).values("pk")
    User.objects.filter(pk__in=staff_ids, is_staff=False).update(is_staff=True)
    User.objects.filter(is_staff=True).exclude(pk__in=staff_ids).update(is_staff=False)


def delete_support_admin(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name=SUPPORT_ADMIN).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_create_roles"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="is_staff",
            field=models.BooleanField(
                default=False,
                editable=False,
                help_text=(
                    "Odvozeno z rolí a nelze ho měnit ručně: platí pro superuživatele a členy "
                    "skupin správců (správce uživatelů, kurátor dat, odborný revizor výživy)."
                ),
                verbose_name="přístup do administrace",
            ),
        ),
        migrations.RunPython(create_support_admin_and_derive_staff, delete_support_admin),
    ]
