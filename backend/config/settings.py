"""Explicit local/HTTPS configuration; no .env file is read by this application."""
import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

ROOT = Path(__file__).resolve().parents[2]
BUILD = os.environ.get("APP_BUILD") == "1"
DEV = os.environ.get("APP_DEV_MODE") == "1"
TRUST_PROXY = os.environ.get("APP_TRUST_PROXY") == "1"
if TRUST_PROXY and DEV:
    raise ImproperlyConfigured("Доверие proxy разрешено только с HTTPS")
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "build-only-never-a-runtime-key" if BUILD else "")
if not BUILD and len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY должен содержать не менее 50 символов")
BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8000" if DEV else "https://localhost")
if not DEV and not BASE_URL.startswith("https://"):
    raise ImproperlyConfigured("Для HTTP требуется явный APP_DEV_MODE=1")
DEBUG = False
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
CSRF_TRUSTED_ORIGINS = [BASE_URL]
INSTALLED_APPS = [
    "django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions",
    "django.contrib.messages", "django.contrib.staticfiles", "rest_framework",
    "allauth", "allauth.account", "allauth.headless", "accounts", "care", "reports", "audit", "assistant", "prescriptions",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware", "whitenoise.middleware.WhiteNoiseMiddleware",
    "config.middleware.SafeResponsesMiddleware", "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware", "django.contrib.messages.middleware.MessageMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [ROOT / "frontend/templates"], "APP_DIRS": True,
    "OPTIONS": {"context_processors": ["django.template.context_processors.request", "django.contrib.auth.context_processors.auth"]}}]
DATABASES = {"default": {"ENGINE": "django.db.backends.postgresql",
    "NAME": os.environ.get("POSTGRES_DB", "compass"), "USER": os.environ.get("POSTGRES_USER", "compass"),
    "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""), "HOST": os.environ.get("POSTGRES_HOST", "db"),
    "PORT": os.environ.get("POSTGRES_PORT", "5432"), "CONN_MAX_AGE": 0,
    "OPTIONS": {"connect_timeout": 3}}}
AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend", "allauth.account.auth_backends.AuthenticationBackend"]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator", "OPTIONS": {"user_attributes": ["email", "display_name"]}},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.Argon2PasswordHasher"]
LANGUAGE_CODE = "ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEV
SESSION_COOKIE_AGE = 8 * 60 * 60
CSRF_COOKIE_SECURE = not DEV
CSRF_COOKIE_HTTPONLY = False  # The frontend reads only the CSRF token, never the session cookie.
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_FAILURE_VIEW = "config.views.csrf_failure"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "no-referrer"
SECURE_SSL_REDIRECT = not DEV and not BUILD
# This opt-in is only valid behind the deployment's loopback-only Caddy,
# which replaces these headers rather than trusting the public client.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if TRUST_PROXY else None
SECURE_REDIRECT_EXEMPT = [r"^health/ready$"]
X_FRAME_OPTIONS = "DENY"
APPEND_SLASH = False
POLZA_API_KEY = os.environ.get("POLZA_API_KEY", "")
POLZA_MODEL = os.environ.get("POLZA_MODEL", "deepseek/deepseek-v4-flash")
if POLZA_MODEL not in {"deepseek/deepseek-v4-flash", "cohere/command-r7b-12-2024"}:
    raise ImproperlyConfigured("POLZA_MODEL: модель не входит в согласованный список")
ASSISTANT_ALERTING_MODE = os.environ.get("ASSISTANT_ALERTING_MODE", "off")
if ASSISTANT_ALERTING_MODE not in {"off", "demo"}:
    raise ImproperlyConfigured("ASSISTANT_ALERTING_MODE: допустимы только off или demo")
CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "auth_rate_limits",
    "OPTIONS": {"MAX_ENTRIES": 100000, "CULL_FREQUENCY": 0}}}
# Never evict live rate-limit entries. Expired entries are cleaned by an operator command.
CACHES["default"]["BACKEND"] = "accounts.cache.RateLimitCache"
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_USER_MODEL_EMAIL_FIELD = "email"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_PREVENT_ENUMERATION = True
ACCOUNT_EMAIL_CONFIRMATION_EXPIRE_DAYS = 1
ACCOUNT_EMAIL_SUBJECT_PREFIX = "Клинический компас · "
ACCOUNT_ADAPTER = "accounts.adapters.AccountAdapter"
ACCOUNT_SIGNUP_FORM_CLASS = "accounts.forms.SignupFields"
ACCOUNT_LOGOUT_ON_PASSWORD_CHANGE = True
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = False
HEADLESS_ONLY = True
HEADLESS_CLIENTS = ("browser",)
HEADLESS_ADAPTER = "accounts.adapters.HeadlessAdapter"
HEADLESS_FRONTEND_URLS = {
    "account_confirm_email": BASE_URL + "/#/verify-email/{key}",
    "account_reset_password": BASE_URL + "/#/password/request",
    "account_reset_password_from_key": BASE_URL + "/#/password/reset/{key}",
    "account_signup": BASE_URL + "/#/register/patient",
}
ALLAUTH_TRUSTED_PROXY_COUNT = 0
ALLAUTH_TRUSTED_CLIENT_IP_HEADER = "X-Real-IP" if TRUST_PROXY else None
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("SMTP_HOST", "mailpit" if DEV else "")
EMAIL_PORT = int(os.environ.get("SMTP_PORT", "1025" if DEV else "587"))
EMAIL_HOST_USER = os.environ.get("SMTP_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("SMTP_TLS", "0" if DEV else "1") == "1"
EMAIL_TIMEOUT = 5
DEFAULT_FROM_EMAIL = os.environ.get("MAIL_FROM", "Клинический компас <no-reply@example.test>")
STATIC_URL = "/static/"
STATIC_ROOT = ROOT / "staticfiles"
STATICFILES_DIRS = [ROOT / "frontend/static"]
STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"}}
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["accounts.permissions.BrowserSessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["accounts.permissions.VerifiedUser"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "EXCEPTION_HANDLER": "config.errors.api_exception_handler",
    "DATETIME_FORMAT": "iso-8601",
}
# Framework exceptions and access logs must not serialize request bodies, cookies, or email tokens.
LOGGING = {"version": 1, "disable_existing_loggers": False,
    "handlers": {"null": {"class": "logging.NullHandler"}},
    "loggers": {"django.request": {"handlers": ["null"], "propagate": False},
                "django.security": {"handlers": ["null"], "propagate": False}}}
