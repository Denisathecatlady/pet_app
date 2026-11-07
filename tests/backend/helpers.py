"""Constants and helpers shared by the Django tests."""

import re

PASSWORD = "Kopretina-Rybník-2026"
OTHER_PASSWORD = "Javorový-List-9876"


def extract_link(body: str) -> str:
    """Return the path of the first http(s) link in an e-mail body."""
    match = re.search(r"https?://[^/\s]+(/\S*)", body)
    assert match, body
    return match.group(1)


# --- Two-factor authentication -------------------------------------------------------------


def totp_token(device, *, steps: int = 0) -> str:
    """Return the current code of a TOTP device, ``steps`` time steps ahead (-1 = previous).

    A code works once and only if its time step is later than the last accepted one, so a test
    that verifies twice asks for ``steps=1`` the second time (the device tolerates one step).
    """
    import time

    from django_otp.oath import TOTP

    generator = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift + steps)
    generator.time = time.time()
    return f"{generator.token():0{device.digits}d}"


def wrong_token(device) -> str:
    """Return six digits that the device does not accept now (not one of the codes it tolerates)."""
    valid = {totp_token(device, steps=step) for step in (-2, -1, 0, 1, 2)}
    return next(
        code for code in (f"{n:06d}" for n in range(111111, 999999, 111111)) if code not in valid
    )


def enroll(user, *, confirmed: bool = True):
    """Give ``user`` a TOTP device (confirmed unless told otherwise) and return it."""
    from django_otp.plugins.otp_totp.models import TOTPDevice

    return TOTPDevice.objects.create(user=user, name="Test", confirmed=confirmed)


def log_in_verified(client, user):
    """Sign ``user`` in with a session that has passed the second factor; return the device.

    Use it wherever a test needs a staff user (``force_login`` alone leaves a staff user
    without a device, who is sent to the enrolment page by every request).
    """
    from django_otp import DEVICE_ID_SESSION_KEY

    device = enroll(user)
    client.force_login(user)
    session = client.session
    session[DEVICE_ID_SESSION_KEY] = device.persistent_id
    session.save()
    return device
