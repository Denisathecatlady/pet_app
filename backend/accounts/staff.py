"""Keeping ``User.is_staff`` equal to what the roles say (docs/14 §14.2).

``User.is_staff`` is derived: true for superusers and for members of a staff-capable group
(``accounts.roles.STAFF_ROLES``). ``User.save`` handles the superuser flag, the receivers in
``accounts.signals`` call :func:`refresh_staff_flags` whenever group membership changes, a
group is renamed or a group is deleted.
"""

from collections.abc import Iterable

from django.db.models import Q

from .models import User
from .roles import STAFF_ROLES


def refresh_staff_flags(user_ids: Iterable[int] | None = None) -> int:
    """Set ``is_staff`` of the given users (all users when ``None``) to its derived value.

    Uses ``QuerySet.update``: no ``save`` signals and no extra queries per user.

    Output: the number of users whose flag changed.
    """
    users = User.objects.all() if user_ids is None else User.objects.filter(pk__in=list(user_ids))
    staff_ids = User.objects.filter(Q(is_superuser=True) | Q(groups__name__in=STAFF_ROLES)).values(
        "pk"
    )
    granted = users.filter(pk__in=staff_ids, is_staff=False).update(is_staff=True)
    revoked = users.filter(is_staff=True).exclude(pk__in=staff_ids).update(is_staff=False)
    return granted + revoked
