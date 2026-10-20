"""Settings for the automated tests (pytest-django, PostgreSQL)."""

from config.env import database_from_env

from .base import *  # noqa: F403
from .dev import LOCAL_DATABASE_DEFAULTS

DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

# TEST ONLY: publicly known key.
SECRET_KEY = "test-only-insecure-key-5d1f7a2c-not-for-any-deployment"  # noqa: S105

DATABASES = {"default": database_from_env(LOCAL_DATABASE_DEFAULTS)}

# TEST ONLY: a fast hasher keeps the suite quick. Argon2 stays first in base and prod.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

AXES_ENABLED = True
