"""Signed one-time token for the account activation link."""

from django.contrib.auth.tokens import PasswordResetTokenGenerator


class ActivationTokenGenerator(PasswordResetTokenGenerator):
    """Token that stops working once the account is active.

    The hash covers ``is_active`` and ``activation_pending``, which change on
    activation, so a used link is invalid. The link also expires after
    ``settings.PASSWORD_RESET_TIMEOUT`` and is signed with ``SECRET_KEY``.
    """

    key_salt = "accounts.tokens.ActivationTokenGenerator"

    def _make_hash_value(self, user, timestamp: int) -> str:  # type: ignore[no-untyped-def]
        return f"{user.pk}|{user.email}|{user.is_active}|{user.activation_pending}|{timestamp}"


activation_token = ActivationTokenGenerator()
