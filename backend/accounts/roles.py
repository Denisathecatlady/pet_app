"""User roles (docs/07 §7.6) and what each staff role may do in the administration.

Each role is a Django ``Group`` with the same name. The groups are created by the
migrations ``0002_create_roles`` and ``0003_support_admin_and_derived_staff``. ``admin`` is
not a group: it is a superuser (``is_superuser``).

``User.is_staff`` (access to the administration) is derived from the roles: it is true for
superusers and for members of a staff-capable group (``STAFF_ROLES``), false for everybody
else (docs/14 §14.2). ``ROLE_PERMISSIONS`` is the single authoritative list of what the
groups may do; ``sync_role_permissions`` (``accounts.role_permissions``) applies it.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from django.db import models


class Role(models.TextChoices):
    OWNER = "owner", "Majitel zvířat"
    VET = "vet", "Veterinární lékař"
    DATA_CURATOR = "data_curator", "Kurátor dat"
    NUTRITION_REVIEWER = "nutrition_reviewer", "Odborný revizor výživy"
    SUPPORT_ADMIN = "support_admin", "Správce uživatelů"


ROLE_LABELS: Final = MappingProxyType({role.value: str(role.label) for role in Role})

# Roles whose members may sign in to the administration (User.is_staff is derived from them).
# ``owner`` and ``vet`` are application roles without any access to the administration.
STAFF_ROLES: Final = frozenset(
    {Role.DATA_CURATOR.value, Role.NUTRITION_REVIEWER.value, Role.SUPPORT_ADMIN.value}
)

# What each role may do in the administration, as 'app_label.codename' of Django permissions.
# A superuser needs no entry (Django grants everything). ``sync_role_permissions`` makes the
# permissions of each group listed here EXACTLY this list (idempotent, after every migrate),
# so a permission added to a group by hand disappears again: change this table instead, and
# keep the rationale next to the entry. Groups that are not listed are left alone.
#
# Principles: least privilege; no staff role sees personal data it does not need
# (data minimisation, docs/12 §12.8 point 5); no permission to delete data of users.
# docs/14 §14.3 prints the resulting matrix (``manage.py print_role_matrix``); a test keeps
# the document in sync with this table.
ROLE_PERMISSIONS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        # Application roles: no access to the administration at all.
        Role.OWNER.value: (),
        Role.VET.value: (),
        # Support (users, locked-out sign-ins, vet verification, data subject requests). May
        # view users and change their basic fields (names, active flag) - the user admin limits
        # this to non-staff users and hides the superuser flag, permissions and staff groups
        # from them (docs/14 §14.4). No add or delete of users: erasure of an ordinary user
        # goes through the data subject request flow below (a verified request, the typed
        # e-mail, non-staff accounts only). Sees failed sign-in counters (axes) and may delete
        # them, which unlocks the account (action "Odemknout"). Decides requests for the role
        # of a veterinarian (never their own; a decided request is final) and handles requests
        # of data subjects: records them, exports the data of a non-staff account and erases
        # it. Deliberately NOT included: any permission on animals, measurements, health
        # conditions and shares (support has no need to see health data of animals, docs/12
        # §12.8 point 5), changing or deleting a vet verification request or a data subject
        # request once recorded (they are evidence), and the admin access log (a support
        # person must not be able to read the record of their own access).
        Role.SUPPORT_ADMIN.value: (
            "accounts.view_user",
            "accounts.change_user",
            "accounts.view_vetverificationrequest",
            "accounts.decide_vetverificationrequest",
            "accounts.view_datasubjectrequest",
            "accounts.add_datasubjectrequest",
            "accounts.change_datasubjectrequest",
            "accounts.export_datasubjectrequest",
            "accounts.erase_datasubjectrequest",
            "axes.view_accessattempt",
            "axes.delete_accessattempt",
        ),
        # Curator imports and maintains the library of sources. No delete: a source that
        # was cited stays (a wrong one is corrected or marked, never removed silently).
        Role.DATA_CURATOR.value: (
            "catalog.view_scientificsource",
            "catalog.add_scientificsource",
            "catalog.change_scientificsource",
        ),
        # Reviewer reads sources and maintains the codebook of health conditions that
        # drives the safety gate (docs/09 §9.2). Cannot edit sources or see any animal.
        Role.NUTRITION_REVIEWER.value: (
            "catalog.view_scientificsource",
            "animals.view_healthcondition",
            "animals.change_healthcondition",
        ),
    }
)
