"""User roles (docs/07 §7.6). Each role is a Django ``Group`` with the same name.

The groups are created by migration ``0002_create_roles``. ``admin`` is not a
group: it is Django's ``is_staff`` / ``is_superuser``.
"""

from types import MappingProxyType
from typing import Final

from django.db import models


class Role(models.TextChoices):
    OWNER = "owner", "Majitel zvířat"
    VET = "vet", "Veterinární lékař"
    DATA_CURATOR = "data_curator", "Kurátor dat"
    NUTRITION_REVIEWER = "nutrition_reviewer", "Odborný revizor výživy"


ROLE_LABELS: Final = MappingProxyType({role.value: str(role.label) for role in Role})
