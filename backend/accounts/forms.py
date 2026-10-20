"""Forms of the accounts app (Czech labels and messages)."""

from typing import Any

from django import forms
from django.contrib.auth import authenticate, password_validation
from django.contrib.auth import forms as auth_forms
from django.core.exceptions import ValidationError
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html

from .models import User, UserManager
from .services import claim_email_slot, password_matches

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
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "Hesla se neshodují.")
        elif password1:
            candidate = User(email=cleaned.get("email") or "")
            try:
                password_validation.validate_password(password1, candidate)
            except ValidationError as error:
                self.add_error("password1", error)
        return cleaned


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
    """Built-in reset form with a per-user limit on how often the e-mail is sent."""

    def get_users(self, email: str):  # type: ignore[no-untyped-def]
        return (
            user for user in super().get_users(email) if claim_email_slot("password-reset", user)
        )


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
