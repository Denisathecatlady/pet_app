"""Custom user: e-mail is the login name, there is no username (docs/07 §7.7)."""

from typing import Any

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower

from .roles import ROLE_LABELS, Role


class UserManager(BaseUserManager["User"]):
    use_in_migrations = True

    @classmethod
    def normalize_email(cls, email: str | None) -> str:
        """Return the e-mail stripped and lower-cased (the whole address, not only the domain).

        Lower-casing the local part makes ``Jana@x.cz`` and ``jana@x.cz`` one account,
        which is what users expect, and keeps login, lockout and uniqueness consistent.
        """
        return (email or "").strip().lower()

    def get_by_natural_key(self, username: str | None) -> "User":
        """Look a user up by e-mail regardless of letter case (used by authentication)."""
        return self.get(email=self.normalize_email(username))

    def _create_user(self, email: str, password: str | None, **extra_fields: Any) -> "User":
        email = self.normalize_email(email)
        if not email:
            raise ValueError("The e-mail address must be set.")
        user = self.model(email=email, **extra_fields)
        user.set_password(password)  # None gives an unusable password
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields: Any) -> "User":
        """Create a regular user.

        Inputs: e-mail, optional password (``None`` = unusable) and model fields.
        Output: the saved user. Raises ``ValueError`` for an empty e-mail.
        """
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(
        self, email: str, password: str | None = None, **extra_fields: Any
    ) -> "User":
        """Create an active superuser.

        Raises ``ValueError`` for an empty e-mail or when ``is_staff`` / ``is_superuser``
        is explicitly false.
        """
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        if extra_fields["is_staff"] is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields["is_superuser"] is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    username = None  # type: ignore[assignment]
    email = models.EmailField(
        "e-mail",
        unique=True,
        error_messages={"unique": "Uživatel s tímto e-mailem již existuje."},
    )
    activation_pending = models.BooleanField(
        "čeká na aktivaci",
        default=False,
        help_text=(
            "Účet vznikl registrací a čeká na potvrzení e-mailu. Jen takový účet lze "
            "aktivovat odkazem; účet deaktivovaný správcem se sám znovu aktivovat nedá."
        ),
    )

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        verbose_name = "uživatel"
        verbose_name_plural = "uživatelé"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(email=Lower("email")),
                name="accounts_user_email_lowercase",
                violation_error_message="E-mail musí být uložen malými písmeny.",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.email = UserManager.normalize_email(self.email)
        if self.is_active:
            self.activation_pending = False
        super().save(*args, **kwargs)

    def has_role(self, role: str) -> bool:
        """Return whether the user belongs to the group of ``role`` (see ``accounts.roles``)."""
        if self.pk is None:
            return False
        return self.groups.filter(name=role).exists()

    @property
    def is_owner(self) -> bool:
        return self.has_role(Role.OWNER)

    @property
    def is_vet(self) -> bool:
        return self.has_role(Role.VET)

    @property
    def is_data_curator(self) -> bool:
        return self.has_role(Role.DATA_CURATOR)

    @property
    def is_nutrition_reviewer(self) -> bool:
        return self.has_role(Role.NUTRITION_REVIEWER)

    def role_labels(self) -> list[str]:
        """Return the Czech labels of the user's roles, sorted by label."""
        if self.pk is None:
            return []
        names = self.groups.values_list("name", flat=True)
        return sorted(ROLE_LABELS.get(name, name) for name in names)
