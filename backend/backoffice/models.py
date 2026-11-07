"""Access log of the administration (docs/12 §12.8 point 5, docs/14 §14.7).

``AdminAccessLog`` records WHO of the staff opened WHICH kind of record WHEN and from WHERE,
for the models that contain personal data. It never records what was searched for, which
filters were used or what was submitted: only the path without its query string.

The log is append-only (a row is never updated by the application) and not deleted
by the application except by ``manage.py purge_admin_access_log`` after the retention
period (``settings.ADMIN_ACCESS_LOG_RETENTION_DAYS``, a working value for the lawyer). It has no
change history: the rows are themselves the history.
"""

from typing import Any

from django.conf import settings
from django.db import models
from django.utils import timezone


class AdminAccessAction(models.TextChoices):
    VIEW_LIST = "VIEW_LIST", "zobrazení seznamu"
    VIEW_OBJECT = "VIEW_OBJECT", "zobrazení záznamu"
    ADD = "ADD", "přidání záznamu"
    CHANGE = "CHANGE", "změna záznamu"
    DELETE = "DELETE", "smazání záznamu"
    EXPORT = "EXPORT", "export údajů"
    UNLOCK = "UNLOCK", "odemčení přihlášení"
    LOGIN = "LOGIN", "přihlášení správce"


class AdminAccessLog(models.Model):
    # The administration of this model is read-only and for superusers only; it is itself
    # access-logged like every other model with personal data (staff e-mail, IP address).
    contains_personal_data = True

    timestamp = models.DateTimeField("čas", default=timezone.now, db_index=True, editable=False)
    staff_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="správce",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        editable=False,
        help_text="Prázdné, pokud byl účet správce mezitím smazán (e-mail zůstává v záznamu).",
    )
    staff_email = models.CharField(
        "e-mail správce",
        max_length=254,
        blank=True,
        editable=False,
        help_text="E-mail v době přístupu; zůstává i po smazání účtu.",
    )
    action = models.CharField(
        "akce", max_length=16, choices=AdminAccessAction.choices, editable=False
    )
    app_label = models.CharField("aplikace", max_length=100, blank=True, editable=False)
    model = models.CharField("model", max_length=100, blank=True, editable=False)
    object_pk = models.CharField("záznam", max_length=64, blank=True, editable=False)
    ip_address = models.GenericIPAddressField("IP adresa", null=True, blank=True, editable=False)
    path = models.CharField(
        "adresa",
        max_length=255,
        blank=True,
        editable=False,
        help_text="Cesta bez parametrů (hledaný text a filtry se nezaznamenávají).",
    )

    class Meta:
        verbose_name = "záznam o přístupu do administrace"
        verbose_name_plural = "přístupy do administrace"
        ordering = ["-timestamp", "-pk"]
        indexes = [models.Index(fields=["staff_user", "-timestamp"], name="backoffice_user_time")]

    def __str__(self) -> str:
        who = self.staff_email or "neznámý správce"
        return (
            f"{self.timestamp:%Y-%m-%d %H:%M:%S} {who} {self.action} {self.app_label}.{self.model}"
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Insert only: a row of the log is never rewritten.

        Raises:
            ValueError: the row already exists in the database.
        """
        if not self._state.adding:
            raise ValueError("A row of the admin access log cannot be changed.")
        super().save(*args, **kwargs)
