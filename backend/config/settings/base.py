"""Settings shared by every environment (dev, test, prod).

Nothing secret lives here. ``SECRET_KEY`` and ``DATABASES`` are set by the
environment modules: dev and test with local development defaults, prod
strictly from environment variables (docs/07 §7.7).
"""

from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
REPO_DIR = BASE_DIR.parent

DEBUG = False
ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "simple_history",
    "axes",
    "core",
    "accounts",
    "animals",
    "catalog",
    # Further project apps (recipes, analyses, …) are added below as they are built.
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "core.middleware.ContentSecurityPolicyMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.NoStoreForSignedInUsersMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    # django-axes 8: AxesMiddleware must be the last middleware.
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.contact",
            ],
        },
    },
]

# --- Users, authentication and passwords --------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    # django-axes: must come first so that locked-out clients never reach ModelBackend.
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

PASSWORD_MIN_LENGTH = 12
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
        "OPTIONS": {"user_attributes": ("email", "first_name", "last_name")},
    },
    {
        "NAME": "accounts.validators.MinimumLengthValidator",
        "OPTIONS": {"min_length": PASSWORD_MIN_LENGTH},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "core:home"

# Validity of password reset and account activation links (seconds).
PASSWORD_RESET_TIMEOUT = 24 * 60 * 60
# Minimum gap between two account e-mails of one kind (activation, notices, password reset)
# to one user, and the maximum of all account e-mails to one user in 24 hours.
ACCOUNT_EMAIL_THROTTLE_SECONDS = 120
ACCOUNT_EMAIL_DAILY_LIMIT = 10
# Send account e-mails after the response (accounts.services.deliver). Production turns it
# on so that response time does not reveal which addresses have an account.
ACCOUNT_EMAIL_IN_BACKGROUND = False
# Registrations not activated within this time are deleted by
# ``manage.py purge_pending_accounts`` (working value, docs/12 §12.8 for the lawyer).
PENDING_ACCOUNT_RETENTION = timedelta(days=7)

# --- Login rate limiting (django-axes 8) --------------------------------------------------
LOGIN_FAILURE_LIMIT = 5
LOGIN_COOLOFF = timedelta(hours=1)

AXES_ENABLED = True
AXES_FAILURE_LIMIT = LOGIN_FAILURE_LIMIT
AXES_COOLOFF_TIME = LOGIN_COOLOFF
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_USERNAME_FORM_FIELD = "email"
AXES_USERNAME_CALLABLE = "accounts.axes_hooks.get_username"
AXES_CLIENT_IP_CALLABLE = "accounts.axes_hooks.get_client_ip"
AXES_LOCKOUT_CALLABLE = "accounts.views.lockout"
AXES_RESET_ON_SUCCESS = True
# POST fields masked before axes stores a failed attempt. Password change and account
# deletion re-authenticate through axes, so their password fields must be listed too.
AXES_SENSITIVE_PARAMETERS = [
    "password",
    "old_password",
    "new_password1",
    "new_password2",
    "password1",
    "password2",
    "csrfmiddlewaretoken",
]
# Number of trusted reverse proxies that append to X-Forwarded-For (0 = use REMOTE_ADDR).
# Behind a proxy it must be set (prod.py refuses 0 with a proxy SSL header): otherwise every
# client has the proxy's address and the lockout applies to the e-mail alone.
TRUSTED_PROXY_COUNT = 0

# --- Sessions, cookies and browser security -----------------------------------------------
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
# Sent by core.middleware.ContentSecurityPolicyMiddleware. Templates use no inline
# scripts, inline styles or third-party assets.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; "
    "object-src 'none'; img-src 'self' data:; script-src 'self'; style-src 'self'"
)

# --- Database ------------------------------------------------------------------------------
# PostgreSQL only, configured from POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST
# and POSTGRES_PORT through config.env.database_from_env(): dev and test fall back to local
# development values, prod requires the variables.
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Internationalisation -------------------------------------------------------------------
LANGUAGE_CODE = "cs"
TIME_ZONE = "Europe/Prague"
USE_I18N = True
USE_TZ = True

# --- Static files ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = REPO_DIR / "staticfiles"

# --- E-mail and contact --------------------------------------------------------------------
# Address of the application administrator shown to users (e.g. how to get the vet role).
# Empty shows a placeholder for the operator to fill in.
CONTACT_EMAIL = ""
DEFAULT_FROM_EMAIL = "BARF Nutri <noreply@localhost>"
SERVER_EMAIL = DEFAULT_FROM_EMAIL
EMAIL_SUBJECT_PREFIX = "[BARF Nutri] "
