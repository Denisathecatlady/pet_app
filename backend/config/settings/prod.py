"""Production settings: everything sensitive comes from environment variables.

Required: DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS, POSTGRES_DB, POSTGRES_USER,
POSTGRES_PASSWORD, POSTGRES_HOST (POSTGRES_PORT defaults to 5432). Importing this
module without them raises ImproperlyConfigured, so the application refuses to start.

Optional: DJANGO_CSRF_TRUSTED_ORIGINS, DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS (default
true), DJANGO_SECURE_HSTS_PRELOAD (default false), DJANGO_SECURE_PROXY_SSL_HEADER
(e.g. ``HTTP_X_FORWARDED_PROTO,https``, only behind a proxy that overwrites the header),
DJANGO_TRUSTED_PROXY_COUNT, DJANGO_STATIC_ROOT, DJANGO_EMAIL_HOST, DJANGO_EMAIL_PORT,
DJANGO_EMAIL_HOST_USER, DJANGO_EMAIL_HOST_PASSWORD, DJANGO_EMAIL_USE_TLS,
DJANGO_EMAIL_USE_SSL, DJANGO_DEFAULT_FROM_EMAIL, DJANGO_LOG_LEVEL.
"""

from django.core.exceptions import ImproperlyConfigured

from config.env import (
    database_from_env,
    env_bool,
    env_int,
    env_list,
    env_str,
    require_env,
)

from .base import *  # noqa: F403
from .base import STATIC_ROOT as _DEFAULT_STATIC_ROOT

DEBUG = False

SECRET_KEY = require_env("DJANGO_SECRET_KEY")
if len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5 or SECRET_KEY.startswith("django-insecure"):
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be a random value of at least 50 characters "
        "(see django.core.management.utils.get_random_secret_key)."
    )

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("Required environment variable DJANGO_ALLOWED_HOSTS is not set.")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

DATABASES = {"default": database_from_env()}

# --- HTTPS and cookies --------------------------------------------------------------------
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 365 * 24 * 60 * 60
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", True)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", False)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

_proxy_ssl_header = env_list("DJANGO_SECURE_PROXY_SSL_HEADER")
if _proxy_ssl_header:
    if len(_proxy_ssl_header) != 2 or not _proxy_ssl_header[0].startswith("HTTP_"):
        raise ImproperlyConfigured(
            "DJANGO_SECURE_PROXY_SSL_HEADER must look like 'HTTP_X_FORWARDED_PROTO,https'."
        )
    SECURE_PROXY_SSL_HEADER = (_proxy_ssl_header[0], _proxy_ssl_header[1])

TRUSTED_PROXY_COUNT = env_int("DJANGO_TRUSTED_PROXY_COUNT", 0)

# --- Static files (collectstatic; served by the web server) -------------------------------
STATIC_ROOT = env_str("DJANGO_STATIC_ROOT", str(_DEFAULT_STATIC_ROOT))
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"},
}

# --- E-mail (SMTP) ------------------------------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env_str("DJANGO_EMAIL_HOST", "localhost")
EMAIL_PORT = env_int("DJANGO_EMAIL_PORT", 587)
EMAIL_HOST_USER = env_str("DJANGO_EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env_str("DJANGO_EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("DJANGO_EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("DJANGO_EMAIL_USE_SSL", False)
if EMAIL_USE_TLS and EMAIL_USE_SSL:
    raise ImproperlyConfigured("DJANGO_EMAIL_USE_TLS and DJANGO_EMAIL_USE_SSL are exclusive.")
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = env_str("DJANGO_DEFAULT_FROM_EMAIL", "BARF Nutri <noreply@localhost>")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# --- Logging to stdout (collected by the process manager or container runtime) -----------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "plain",
        },
    },
    "root": {"handlers": ["stdout"], "level": env_str("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {
        "django": {"handlers": ["stdout"], "level": "INFO", "propagate": False},
    },
}
