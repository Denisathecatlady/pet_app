"""Local development settings. Never use them on a server."""

from config.env import database_from_env, env_list

from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", *env_list("DJANGO_ALLOWED_HOSTS")]

# DEV ONLY: publicly known key, valid solely for local development.
SECRET_KEY = "django-insecure-dev-only-0f6c1b9e-never-use-in-production"  # noqa: S105

# DEV ONLY: local PostgreSQL role and database ``barf`` with password ``barf``.
LOCAL_DATABASE_DEFAULTS = {
    "POSTGRES_DB": "barf",
    "POSTGRES_USER": "barf",
    "POSTGRES_PASSWORD": "barf",
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5432",
}
DATABASES = {"default": database_from_env(LOCAL_DATABASE_DEFAULTS)}

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
