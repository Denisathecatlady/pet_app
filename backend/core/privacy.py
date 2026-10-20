"""Helpers for removing personal data kept outside an object's own table (GDPR art. 17)."""

from typing import Any, Final

from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.models import ContentType

DELETED_OBJECT_REPR: Final = "[smazaný záznam]"


def anonymise_admin_log(instance: Any) -> int:
    """Replace the text of a deleted object in the admin log (``LogEntry.object_repr``).

    The admin log stores ``str(obj)`` of every object an administrator added, changed
    or deleted, e.g. a user's e-mail or an animal's name. After the object is deleted
    the entries stay as an audit trail (who did what and when, which fields changed),
    but without the object's text. Use from a ``post_delete`` receiver.

    Output: number of updated log entries.
    """
    content_type = ContentType.objects.get_for_model(instance, for_concrete_model=False)
    return LogEntry.objects.filter(content_type=content_type, object_id=str(instance.pk)).update(
        object_repr=DELETED_OBJECT_REPR
    )
