"""Custom user: e-mail is the login name, there is no username (docs/07 §7.7)."""

from datetime import date
from typing import Any, Final

from django.conf import settings
from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone
from simple_history.models import HistoricalRecords

from .deadlines import default_due_date
from .roles import ROLE_LABELS, STAFF_ROLES, Role


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
        ``is_staff`` is derived from the roles (:meth:`User.derive_is_staff`), so passing
        ``is_staff=True`` has no effect: add the user to a staff group instead.
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
    # Marker for the access log of the administration (docs/14 §14.7): the admin of every
    # model that sets this must use ``backoffice.access_log.AccessLoggedAdminMixin``.
    contains_personal_data = True

    username = None  # type: ignore[assignment]
    email = models.EmailField(
        "e-mail",
        unique=True,
        error_messages={"unique": "Uživatel s tímto e-mailem již existuje."},
    )
    is_staff = models.BooleanField(
        "přístup do administrace",
        default=False,
        editable=False,
        help_text=(
            "Odvozeno z rolí a nelze ho měnit ručně: platí pro superuživatele a členy skupin "
            "správců (správce uživatelů, kurátor dat, odborný revizor výživy)."
        ),
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

    def derive_is_staff(self) -> bool:
        """Return whether the user belongs in the administration: superuser or staff role.

        ``is_staff`` is never set by hand. A user without a primary key has no groups yet,
        so only a superuser is staff until the groups are added (the ``m2m_changed``
        receiver in ``accounts.signals`` then updates the flag).
        """
        if self.is_superuser:
            return True
        if self.pk is None:
            return False
        return self.groups.filter(name__in=STAFF_ROLES).exists()

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.email = UserManager.normalize_email(self.email)
        if self.is_active:
            self.activation_pending = False
        update_fields = kwargs.get("update_fields")
        if update_fields is None or "is_superuser" in update_fields or "is_staff" in update_fields:
            self.is_staff = self.derive_is_staff()
            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "is_staff"}
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


def _choices(field: str, choices: type[models.TextChoices]) -> Q:
    return Q(**{f"{field}__in": choices.values})


# --- Verification of veterinarians (docs/14 §14.11) ------------------------------------------

# Lengths of what an applicant types. The message is read by a person; it is no place for
# documents or personal identification numbers (the form says so).
VET_REQUEST_MESSAGE_MAX_LENGTH: Final = 1000
VET_REQUEST_NOTE_MAX_LENGTH: Final = 2000


class VetVerificationStatus(models.TextChoices):
    PENDING = "PENDING", "čeká na posouzení"
    APPROVED = "APPROVED", "schváleno"
    REJECTED = "REJECTED", "zamítnuto"
    REVOKED = "REVOKED", "role odebrána"


class VetVerificationRequest(models.Model):
    """A user's request for the role ``vet`` and the administrator's decision about it.

    The role itself is the group ``vet`` (it is what grants anything); this record says who
    asked, who decided, when and how the identity and the entitlement were checked. At most
    one request per user is pending. Decisions are made only by
    ``accounts.vet_verification`` (the administration actions call it): a rejected or revoked
    request is a closed record, the user files a new one.
    """

    # Marker for the access log of the administration (docs/14 §14.7): its admin must use
    # backoffice.access_log.AccessLoggedAdminMixin.
    contains_personal_data = True

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="vet_verification_requests",
        verbose_name="žadatel",
    )
    submitted_at = models.DateTimeField("odesláno", default=timezone.now, editable=False)
    professional_id = models.CharField(
        "Evidenční číslo v profesní evidenci, pokud existuje",
        max_length=64,
        blank=True,
        help_text="Číslo, pod kterým jste vedeni v profesní evidenci veterinárních lékařů.",
    )
    workplace = models.CharField(
        "pracoviště",
        max_length=200,
        help_text="Název a místo ordinace, kliniky nebo jiného pracoviště.",
    )
    message = models.TextField(
        "zpráva pro správce",
        blank=True,
        validators=[MaxLengthValidator(VET_REQUEST_MESSAGE_MAX_LENGTH)],
        help_text="Nepovinné. Nepište rodné číslo ani čísla dokladů.",
    )
    status = models.CharField(
        "stav",
        max_length=8,
        choices=VetVerificationStatus.choices,
        default=VetVerificationStatus.PENDING,
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="rozhodl",
    )
    decided_at = models.DateTimeField("rozhodnuto", null=True, blank=True)
    decision_note = models.TextField(
        "odůvodnění rozhodnutí",
        blank=True,
        validators=[MaxLengthValidator(VET_REQUEST_NOTE_MAX_LENGTH)],
        help_text="Uvidí ho žadatel (na stránce a v e-mailu). Povinné při zamítnutí a odebrání.",
    )
    verification_method_note = models.TextField(
        "Jak byla totožnost a oprávnění ověřena",
        blank=True,
        validators=[MaxLengthValidator(VET_REQUEST_NOTE_MAX_LENGTH)],
        help_text=(
            "Interní poznámka, žadatel ji neuvidí. Povinná při schválení. Nezapisujte do ní "
            "čísla dokladů."
        ),
    )

    history = HistoricalRecords(cascade_delete_history=True)

    class Meta:
        verbose_name = "žádost o ověření veterináře"
        verbose_name_plural = "žádosti o ověření veterináře"
        ordering = ["-submitted_at", "-pk"]
        permissions = [
            (
                "decide_vetverificationrequest",
                "Může schvalovat, zamítat a odebírat roli veterináře",
            ),
        ]
        indexes = [models.Index(fields=["status", "-submitted_at"], name="accounts_vetreq_status")]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(status=VetVerificationStatus.PENDING),
                name="accounts_vetverificationrequest_one_pending_per_user",
                violation_error_message="Tento uživatel už má nevyřízenou žádost.",
            ),
            models.CheckConstraint(
                condition=_choices("status", VetVerificationStatus),
                name="accounts_vetverificationrequest_status_valid",
                violation_error_message="Neplatný stav žádosti.",
            ),
            models.CheckConstraint(
                condition=Q(status=VetVerificationStatus.PENDING, decided_at__isnull=True)
                | (~Q(status=VetVerificationStatus.PENDING) & Q(decided_at__isnull=False)),
                name="accounts_vetverificationrequest_decided_at_follows_status",
                violation_error_message="Čas rozhodnutí patří jen k vyřízené žádosti.",
            ),
            models.CheckConstraint(
                condition=~Q(status=VetVerificationStatus.APPROVED)
                | Q(verification_method_note__regex=r"\S"),
                name="accounts_vetverificationrequest_approval_has_method_note",
                violation_error_message=(
                    "Schválení vyžaduje popis, jak byla totožnost a oprávnění ověřena."
                ),
            ),
            models.CheckConstraint(
                condition=Q(
                    status__in=[VetVerificationStatus.PENDING, VetVerificationStatus.APPROVED]
                )
                | Q(decision_note__regex=r"\S"),
                name="accounts_vetverificationrequest_refusal_has_note",
                violation_error_message="Zamítnutí a odebrání role vyžaduje odůvodnění.",
            ),
        ]

    def __str__(self) -> str:
        # No personal data: the administration log keeps this text after the account is gone.
        return f"žádost o ověření veterináře č. {self.pk}"

    @property
    def is_pending(self) -> bool:
        return self.status == VetVerificationStatus.PENDING

    def clean(self) -> None:
        """Raises ``ValidationError`` when a decided request lacks the note its decision needs."""
        errors = {}
        if (
            self.status == VetVerificationStatus.APPROVED
            and not self.verification_method_note.strip()
        ):
            errors["verification_method_note"] = "Popište, jak byla totožnost a oprávnění ověřena."
        refused = self.status in (VetVerificationStatus.REJECTED, VetVerificationStatus.REVOKED)
        if refused and not self.decision_note.strip():
            errors["decision_note"] = "Uveďte odůvodnění rozhodnutí."
        if errors:
            raise ValidationError(errors)


# --- Requests of data subjects (docs/14 §14.12) -----------------------------------------------


class DataSubjectRequestType(models.TextChoices):
    ACCESS = "ACCESS", "přístup k údajům (čl. 15)"
    RECTIFICATION = "RECTIFICATION", "oprava údajů (čl. 16)"
    ERASURE = "ERASURE", "výmaz (čl. 17)"
    RESTRICTION = "RESTRICTION", "omezení zpracování (čl. 18)"
    PORTABILITY = "PORTABILITY", "přenositelnost údajů (čl. 20)"
    OBJECTION = "OBJECTION", "námitka proti zpracování (čl. 21)"
    OTHER = "OTHER", "jiná žádost"


class DataSubjectRequestChannel(models.TextChoices):
    EMAIL = "EMAIL", "e-mail"
    POST = "POST", "pošta"
    ACCOUNT_PAGE = "ACCOUNT_PAGE", "stránka účtu"
    OTHER = "OTHER", "jinak"


class DataSubjectRequestStatus(models.TextChoices):
    RECEIVED = "RECEIVED", "přijata"
    IN_PROGRESS = "IN_PROGRESS", "vyřizuje se"
    COMPLETED = "COMPLETED", "vyřízena"
    REJECTED = "REJECTED", "zamítnuta"


OPEN_REQUEST_STATUSES: Final = [
    DataSubjectRequestStatus.RECEIVED.value,
    DataSubjectRequestStatus.IN_PROGRESS.value,
]
FINISHED_REQUEST_STATUSES: Final = [
    DataSubjectRequestStatus.COMPLETED.value,
    DataSubjectRequestStatus.REJECTED.value,
]


class DataSubjectRequest(models.Model):
    """A request of a person to exercise a right over their personal data (GDPR art. 15-21).

    The record of how the request was handled outlives the account it concerns: ``user`` is
    emptied when the account is erased. Staff identify the person by ``subject_label``, a
    pseudonym (e.g. the account number), never by a full name. The period for the answer is
    a working value for the lawyer (``settings.DATA_SUBJECT_REQUEST_PERIOD_MONTHS``);
    ``due_on`` is filled from it and changing it needs a reason (``extension_reason``).
    """

    # Marker for the access log of the administration (docs/14 §14.7): its admin must use
    # backoffice.access_log.AccessLoggedAdminMixin.
    contains_personal_data = True

    request_type = models.CharField(
        "druh žádosti", max_length=13, choices=DataSubjectRequestType.choices
    )
    received_on = models.DateField("přijato dne", default=timezone.localdate)
    received_via = models.CharField(
        "přijato", max_length=12, choices=DataSubjectRequestChannel.choices
    )
    subject_label = models.CharField(
        "označení žadatele",
        max_length=100,
        help_text=(
            "Pseudonym, např. číslo účtu nebo číslo žádosti. Nepište celé jméno ani e-mail: "
            "záznam o vyřízení se uchovává i po výmazu účtu."
        ),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="data_subject_requests",
        verbose_name="účet žadatele",
        help_text="Vyplňte, jen pokud žádost patří k účtu v aplikaci. Po výmazu účtu se vyprázdní.",
    )
    identity_verified = models.BooleanField(
        "totožnost ověřena",
        default=False,
        help_text="Export a výmaz účtu jsou možné, jen když je totožnost žadatele ověřena.",
    )
    identity_note = models.TextField(
        "jak byla totožnost ověřena",
        blank=True,
        help_text="Bez kopií dokladů a čísel dokladů.",
    )
    due_on = models.DateField(
        "termín vyřízení",
        blank=True,
        help_text=(
            "Prázdné = standardní lhůta od přijetí. Jiný termín vyžaduje odůvodnění prodloužení."
        ),
    )
    extension_reason = models.TextField("odůvodnění prodloužení", blank=True)
    status = models.CharField(
        "stav",
        max_length=11,
        choices=DataSubjectRequestStatus.choices,
        default=DataSubjectRequestStatus.RECEIVED,
    )
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="vyřizuje",
    )
    completed_on = models.DateField("vyřízeno dne", null=True, blank=True)
    outcome_note = models.TextField(
        "poznámka k vyřízení",
        blank=True,
        help_text="Co bylo uděláno, nebo důvod zamítnutí. Bez osobních údajů žadatele.",
    )

    history = HistoricalRecords(cascade_delete_history=True)

    class Meta:
        verbose_name = "žádost subjektu údajů"
        verbose_name_plural = "žádosti subjektů údajů"
        ordering = ["due_on", "pk"]
        permissions = [
            (
                "export_datasubjectrequest",
                "Může vytvořit export osobních údajů k žádosti",
            ),
            ("erase_datasubjectrequest", "Může provést výmaz účtu k žádosti"),
        ]
        indexes = [models.Index(fields=["status", "due_on"], name="accounts_dsr_status_due")]
        constraints = [
            models.CheckConstraint(
                condition=_choices("request_type", DataSubjectRequestType),
                name="accounts_datasubjectrequest_type_valid",
                violation_error_message="Neplatný druh žádosti.",
            ),
            models.CheckConstraint(
                condition=_choices("received_via", DataSubjectRequestChannel),
                name="accounts_datasubjectrequest_channel_valid",
                violation_error_message="Neplatný způsob přijetí.",
            ),
            models.CheckConstraint(
                condition=_choices("status", DataSubjectRequestStatus),
                name="accounts_datasubjectrequest_status_valid",
                violation_error_message="Neplatný stav žádosti.",
            ),
            models.CheckConstraint(
                condition=Q(due_on__gte=models.F("received_on")),
                name="accounts_datasubjectrequest_due_after_received",
                violation_error_message="Termín nemůže předcházet přijetí žádosti.",
            ),
            models.CheckConstraint(
                condition=Q(status__in=FINISHED_REQUEST_STATUSES, completed_on__isnull=False)
                | Q(status__in=OPEN_REQUEST_STATUSES, completed_on__isnull=True),
                name="accounts_datasubjectrequest_completed_on_follows_status",
                violation_error_message="Datum vyřízení patří jen k vyřízené žádosti.",
            ),
        ]

    def __str__(self) -> str:
        # No personal data: the administration log keeps this text after the account is gone.
        return f"žádost subjektu údajů č. {self.pk}"

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_REQUEST_STATUSES

    def standard_due_date(self) -> date:
        """The deadline the working period gives for the day the request was received."""
        return default_due_date(self.received_on, settings.DATA_SUBJECT_REQUEST_PERIOD_MONTHS)

    def clean(self) -> None:
        """Raises ``ValidationError`` for the rules the form shows next to the fields.

        A deadline other than the standard one needs ``extension_reason``; verified identity
        needs the note how it was verified; a rejection needs its reason.
        """
        errors = {}
        if self.due_on is None and self.received_on:
            self.due_on = self.standard_due_date()  # before the constraints are checked
        if (
            self.received_on
            and self.due_on
            and self.due_on != self.standard_due_date()
            and not self.extension_reason.strip()
        ):
            errors["extension_reason"] = (
                "Jiný termín než standardní lhůtu (od přijetí žádosti) zdůvodněte."
            )
        if self.identity_verified and not self.identity_note.strip():
            errors["identity_note"] = "Uveďte, jak byla totožnost ověřena."
        if self.status == DataSubjectRequestStatus.REJECTED and not self.outcome_note.strip():
            errors["outcome_note"] = "Uveďte důvod zamítnutí."
        if errors:
            raise ValidationError(errors)

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Fill the standard deadline and keep the completion date in step with the status."""
        update_fields = kwargs.get("update_fields")
        if self.due_on is None:
            self.due_on = self.standard_due_date()
        if self.status in FINISHED_REQUEST_STATUSES:
            self.completed_on = self.completed_on or timezone.localdate()
        else:
            self.completed_on = None
        if update_fields is not None:
            kwargs["update_fields"] = {*update_fields, "due_on", "completed_on"}
        super().save(*args, **kwargs)
