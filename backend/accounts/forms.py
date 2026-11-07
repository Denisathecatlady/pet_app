"""Forms of the accounts app (Czech labels and messages)."""

from typing import Any

from django import forms
from django.contrib.auth import authenticate, password_validation
from django.contrib.auth import forms as auth_forms
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.http import HttpRequest
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.html import format_html

from . import two_factor
from .models import (
    VET_REQUEST_MESSAGE_MAX_LENGTH,
    User,
    UserManager,
    VetVerificationRequest,
)
from .services import (
    activation_password_matches,
    claim_email_slot,
    deliver,
    password_matches,
)

INVALID_LOGIN_MESSAGE = (
    "Zadejte správný e-mail a heslo. Pokud jste se právě zaregistrovali, "
    "nejprve aktivujte účet odkazem z e-mailu."
)


class RegistrationForm(forms.Form):
    required_css_class = "required"

    email = forms.EmailField(
        label="E-mail",
        max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}),
    )
    password1 = forms.CharField(
        label="Heslo",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Heslo znovu",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    consent = forms.BooleanField(
        required=True,
        error_messages={"required": "Bez souhlasu s podmínkami nelze účet založit."},
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        help_text = password_validation.password_validators_help_text_html()
        self.fields["password1"].help_text = help_text
        self.fields["consent"].label = format_html(
            'Souhlasím s <a href="{}">podmínkami užití</a> a beru na vědomí '
            '<a href="{}">zásady ochrany osobních údajů</a>.',
            reverse("core:terms"),
            reverse("core:privacy"),
        )

    def clean_email(self) -> str:
        return UserManager.normalize_email(self.cleaned_data["email"])

    def clean(self) -> dict[str, Any]:
        # Both checks run, so all password errors show after one submission.
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1:
            candidate = User(email=cleaned.get("email") or "")
            try:
                password_validation.validate_password(password1, candidate)
            except ValidationError as error:
                self.add_error("password1", error)
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "Hesla se neshodují.")
        return cleaned


class ActivationForm(forms.Form):
    """Password of the latest registration, required to activate the account."""

    password = forms.CharField(
        label="Heslo zvolené při registraci",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password", "autofocus": True}),
        help_text=(
            "Pokud jste se s touto adresou registrovali vícekrát, platí heslo z poslední "
            "registrace."
        ),
    )

    def __init__(self, *args: Any, user: User, **kwargs: Any) -> None:
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self) -> str:
        password = self.cleaned_data["password"]
        if not activation_password_matches(self.user, password):
            raise ValidationError(
                "Heslo nesouhlasí s heslem z poslední registrace této adresy. Zkuste ho zadat "
                "znovu, nebo se zaregistrujte znovu a aktivujte účet odkazem z nového e-mailu.",
                code="password_mismatch",
            )
        return password


class LoginForm(forms.Form):
    """E-mail + password login. Field ``email`` is what django-axes reads."""

    email = forms.EmailField(
        label="E-mail",
        max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}),
    )
    password = forms.CharField(
        label="Heslo",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def __init__(self, request: HttpRequest | None = None, *args: Any, **kwargs: Any) -> None:
        self.request = request
        self.user_cache: User | None = None
        super().__init__(*args, **kwargs)

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        email = cleaned.get("email")
        password = cleaned.get("password")
        if email and password:
            self.user_cache = authenticate(
                self.request, email=UserManager.normalize_email(email), password=password
            )
            if self.user_cache is None:
                raise ValidationError(INVALID_LOGIN_MESSAGE, code="invalid_login")
        return cleaned

    def get_user(self) -> User | None:
        return self.user_cache


class ResendActivationForm(forms.Form):
    email = forms.EmailField(
        label="E-mail",
        max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}),
    )


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name")
        labels = {"first_name": "Jméno", "last_name": "Příjmení"}
        widgets = {
            "first_name": forms.TextInput(attrs={"autocomplete": "given-name"}),
            "last_name": forms.TextInput(attrs={"autocomplete": "family-name"}),
        }


class VetVerificationForm(forms.ModelForm):
    """The request for the role of a veterinarian (docs/14 §14.11)."""

    required_css_class = "required"

    class Meta:
        model = VetVerificationRequest
        fields = ("workplace", "professional_id", "message")
        widgets = {
            "workplace": forms.TextInput(attrs={"autocomplete": "organization"}),
            "professional_id": forms.TextInput(attrs={"autocomplete": "off"}),
            "message": forms.Textarea(
                attrs={"rows": 4, "maxlength": VET_REQUEST_MESSAGE_MAX_LENGTH}
            ),
        }

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        for name in ("workplace", "professional_id"):
            if name in cleaned:
                cleaned[name] = " ".join(cleaned[name].split())
        return cleaned


class PasswordChangeForm(auth_forms.PasswordChangeForm):
    """Password change whose old-password check is rate limited by django-axes."""

    def __init__(self, user: User, *args: Any, request: HttpRequest, **kwargs: Any) -> None:
        self.request = request
        super().__init__(user, *args, **kwargs)

    def clean_old_password(self) -> str:
        old_password = self.cleaned_data["old_password"]
        if not password_matches(self.request, self.user, old_password):
            raise ValidationError(
                self.error_messages["password_incorrect"], code="password_incorrect"
            )
        return old_password


class PasswordResetForm(auth_forms.PasswordResetForm):
    """Built-in reset form with a per-user e-mail limit and delivery through ``deliver``.

    ``sent_to`` lists the users an e-mail was prepared for (active and not throttled): the
    administration action *Odeslat odkaz na obnovu hesla* reports from it.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.sent_to: list[User] = []

    def get_users(self, email: str):  # type: ignore[no-untyped-def]
        """Yield the active account with this address if its e-mail limit allows a message.

        Unlike Django's form this also serves an account without a password: an account an
        administrator created has none, and the link is how its owner sets one.
        """
        for user in User.objects.filter(email=UserManager.normalize_email(email), is_active=True):
            if claim_email_slot("password-reset", user):
                self.sent_to.append(user)
                yield user

    def send_mail(  # type: ignore[override]
        self,
        subject_template_name: str,
        email_template_name: str,
        context: dict[str, Any],
        from_email: str | None,
        to_email: str,
        html_email_template_name: str | None = None,
    ) -> None:
        """Render the reset e-mail in the request and hand it to ``services.deliver``.

        With background delivery the page answers equally fast for known and unknown
        addresses (no account enumeration by timing).
        """
        subject = "".join(render_to_string(subject_template_name, context).splitlines())
        body = render_to_string(email_template_name, context)
        deliver(EmailMessage(subject, body, from_email, [to_email]))


class AccountDeleteForm(forms.Form):
    password = forms.CharField(
        label="Současné heslo",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def __init__(self, *args: Any, request: HttpRequest, **kwargs: Any) -> None:
        self.request = request
        super().__init__(*args, **kwargs)

    def clean_password(self) -> str:
        password = self.cleaned_data["password"]
        if not password_matches(self.request, self.request.user, password):
            raise ValidationError("Heslo není správné.", code="password_incorrect")
        return password


# --- Two-factor authentication (docs/14 §14.6) -------------------------------------------

# One message for every failure: wrong code, code used twice, device throttled, malformed
# code, no device. A different text would tell an attacker which of them happened.
INVALID_TOKEN_MESSAGE = (
    "Kód nebyl přijat. Zkontrolujte, že je v telefonu správný čas, a zkuste to za chvíli "
    "znovu: po každé chybě se čekací doba před dalším pokusem prodlužuje."
)


class TwoFactorTokenForm(forms.Form):
    """A code typed by a signed-in user; subclasses decide what the code is checked against.

    The code is checked last and only when every other field is valid, so a wrong password
    does not use up a code (a code from the app works once). A failed code gives
    ``INVALID_TOKEN_MESSAGE`` whatever the reason.
    """

    required_css_class = "required"
    token_label = "Kód z aplikace"
    token_help_text = "Šest číslic z aplikace pro ověřování."

    def __init__(self, *args: Any, user: User, **kwargs: Any) -> None:
        self.user = user
        self.device: Any = None  # the device that accepted the code, once the form is valid
        super().__init__(*args, **kwargs)
        self.fields["token"] = forms.CharField(
            label=self.token_label,
            help_text=self.token_help_text,
            max_length=32,
            widget=forms.TextInput(
                attrs={
                    "autocomplete": "one-time-code",
                    "autocapitalize": "none",
                    "autocorrect": "off",
                    "spellcheck": "false",
                    "autofocus": True,
                }
            ),
        )

    def accepts(self, token: str) -> bool:
        """Check the code; set ``self.device`` when it is accepted."""
        raise NotImplementedError

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        token = cleaned.get("token")
        if token and not self.errors and not self.accepts(token):
            self.add_error("token", ValidationError(INVALID_TOKEN_MESSAGE, code="invalid_token"))
        return cleaned


class PasswordConfirmationMixin:
    """The current password in front of the code, checked through django-axes."""

    request: HttpRequest
    user: User

    def add_password_field(self) -> None:
        self.fields = {  # type: ignore[attr-defined]
            "password": forms.CharField(
                label="Současné heslo",
                strip=False,
                widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
            ),
            **self.fields,  # type: ignore[attr-defined]
        }

    def clean_password(self) -> str:
        password = self.cleaned_data["password"]  # type: ignore[attr-defined]
        if not password_matches(self.request, self.user, password):
            raise ValidationError("Heslo není správné.", code="password_incorrect")
        return password


class VerifyForm(TwoFactorTokenForm):
    """The second factor at sign-in: a code from the app or a recovery code."""

    token_label = "Kód z aplikace nebo záložní kód"
    token_help_text = (
        "Šest číslic z aplikace pro ověřování. Záložní kód (osm znaků) lze použít jen jednou."
    )

    def accepts(self, token: str) -> bool:
        self.device = two_factor.verify(self.user, token)
        return self.device is not None


class TotpTokenForm(TwoFactorTokenForm):
    """A current code from the authenticator app (recovery codes are not accepted)."""

    def accepts(self, token: str) -> bool:
        return two_factor.verify_totp(self.user, token)


class EnrollmentForm(PasswordConfirmationMixin, TwoFactorTokenForm):
    """Confirms a new authenticator with a code from it.

    When the user already has one (``replacing``) the password is asked for as well, so a
    stolen session alone cannot swap the second factor. A valid form has activated the
    device (``self.device``).
    """

    token_help_text = "Šest číslic, které aplikace právě ukazuje."

    def __init__(
        self, *args: Any, user: User, request: HttpRequest, replacing: bool, **kwargs: Any
    ) -> None:
        self.request = request
        super().__init__(*args, user=user, **kwargs)
        if replacing:
            self.add_password_field()

    def accepts(self, token: str) -> bool:
        self.device = two_factor.confirm_enrollment(self.user, token)
        return self.device is not None


class DisableForm(PasswordConfirmationMixin, TotpTokenForm):
    """Switching two-factor authentication off needs the password and a current code."""

    def __init__(self, *args: Any, user: User, request: HttpRequest, **kwargs: Any) -> None:
        self.request = request
        super().__init__(*args, user=user, **kwargs)
        self.add_password_field()
