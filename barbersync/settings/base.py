"""
BarberSync – Django settings.
Multi-tenant SaaS for barbershop management.
"""

import os
from pathlib import Path

import environ

# ──────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    LOCAL=(bool, False),
)
environ.Env.read_env(os.path.join(BASE_DIR, ".env"))

SECRET_KEY = env("SECRET_KEY", default="insecure-dev-key-change-me")
DEBUG = env("DEBUG", default=False)
LOCAL = env("LOCAL", default=False)
ALLOWED_HOSTS = env.get_value("ALLOWED_HOSTS", default="localhost,127.0.0.1").split(",")

# ──────────────────────────────────────────────
# Application definition
# ──────────────────────────────────────────────
INSTALLED_APPS = [
    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    # Third-party
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "corsheaders",
    "django_q",
    # BarberSync apps
    "apps.core",
    "apps.accounts",
    "apps.scheduling",
    "apps.inventory",
    "apps.finance",
    "apps.clients",
    "apps.notifications",
    "apps.booking",
    "apps.billing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # BarberSync: inject current tenant into request
    "apps.core.middleware.TenantMiddleware",
    "apps.core.middleware.TenantSecurityMiddleware",
    "apps.core.middleware.GlobalRateLimitMiddleware",
    "apps.accounts.middleware.OnboardingMiddleware",
    "apps.billing.middleware.SubscriptionAccessMiddleware",
]

ROOT_URLCONF = "barbersync.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.tenant_context",
            ],
        },
    },
]

WSGI_APPLICATION = "barbersync.wsgi.application"

# ──────────────────────────────────────────────
# Database – PostgreSQL
# ──────────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "workforce_db"),
        "USER": os.getenv("DB_USER", "postgres"),
        "PASSWORD": os.getenv("DB_PASSWORD", "postgres"),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5432"),
    }
}

# ──────────────────────────────────────────────
# Cache (Redis / LocMem)
# ──────────────────────────────────────────────
if LOCAL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "barbersync-local-mem",
        }
    }
else:
    REDIS_URL = env("REDIS_URL", default="redis://127.0.0.1:6379/1")
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
            }
        }
    }

# ──────────────────────────────────────────────
# Auth
# ──────────────────────────────────────────────
AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/app/schedule/"
LOGOUT_REDIRECT_URL = "/"

# ──────────────────────────────────────────────
# django-allauth
# ──────────────────────────────────────────────
SITE_ID = 1

ACCOUNT_LOGIN_METHODS = {"email"}
# ACCOUNT_EMAIL_REQUIRED = True
# ACCOUNT_USERNAME_REQUIRED = False

ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]

ACCOUNT_EMAIL_VERIFICATION = "optional"
ACCOUNT_SIGNUP_REDIRECT_URL = LOGIN_REDIRECT_URL

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
        "APP": {
            "client_id": env("GOOGLE_CLIENT_ID", default=""),
            "secret": env("GOOGLE_CLIENT_SECRET", default=""),
        },
    }
}

SOCIALACCOUNT_ADAPTER = "apps.accounts.adapters.SocialAccountAdapter"

# ──────────────────────────────────────────────
# Internationalization
# ──────────────────────────────────────────────
LANGUAGE_CODE = "es"
TIME_ZONE = "America/Bogota"
USE_I18N = True
USE_TZ = True

# ──────────────────────────────────────────────
# Static & Media files
# ──────────────────────────────────────────────
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ──────────────────────────────────────────────
# Default PK
# ──────────────────────────────────────────────
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ──────────────────────────────────────────────
# Django-Q2 (async task queue)
# ──────────────────────────────────────────────
Q_CLUSTER = {
    "name": "barbersync",
    "workers": 2,
    "recycle": 500,
    "timeout": 120,
    "retry": 180,
    "compress": True,
    "orm": "default",  # Uses the DB as broker (no Redis needed to start)
    "ack_failures": True,
    "max_attempts": 3,
    "label": "Django Q2",
}

# ──────────────────────────────────────────────
# Email
# ──────────────────────────────────────────────
if DEBUG:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    EMAIL_BACKEND = "anymail.backends.mailgun.EmailBackend"
    ANYMAIL = {
        "MAILGUN_API_KEY": env("MAILGUN_API_KEY", default=""),
        "MAILGUN_SENDER_DOMAIN": env("MAILGUN_SENDER_DOMAIN", default=""),
    }

DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@barbersync.app")

# ──────────────────────────────────────────────
# CORS (public booking API)
# ──────────────────────────────────────────────
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])

# ──────────────────────────────────────────────
# Business defaults
# ──────────────────────────────────────────────
BARBERSYNC_DEFAULT_OPEN_HOUR = 8
BARBERSYNC_DEFAULT_CLOSE_HOUR = 20
BARBERSYNC_DEFAULT_HISTORY_MONTHS = 6

# ──────────────────────────────────────────────
# Stripe / Billing
# ──────────────────────────────────────────────
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", default="")
STRIPE_PUBLISHABLE_KEY = env("STRIPE_PUBLISHABLE_KEY", default="")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", default="")
BILLING_DEFAULT_PROVIDER = env("BILLING_DEFAULT_PROVIDER", default="stripe")
BILLING_DEFAULT_CURRENCY = env("BILLING_DEFAULT_CURRENCY", default="USD")
BILLING_BASE_URL = env("BILLING_BASE_URL", default="")

# ──────────────────────────────────────────────
# Wompi (Colombia – COP)
# ──────────────────────────────────────────────
WOMPI_PUBLIC_KEY = env("WOMPI_PUBLIC_KEY", default="")
WOMPI_PRIVATE_KEY = env("WOMPI_PRIVATE_KEY", default="")
WOMPI_EVENT_SECRET = env("WOMPI_EVENT_SECRET", default="")
WOMPI_INTEGRITY_SECRET = env("WOMPI_INTEGRITY_SECRET", default="")
WOMPI_SANDBOX = env.bool("WOMPI_SANDBOX", default=True)

# ──────────────────────────────────────────────
# Country-to-provider routing
# ──────────────────────────────────────────────
BILLING_COUNTRY_PROVIDER_MAP = {
    "CO": {"default": "wompi", "allowed": ["wompi", "stripe"]},
}
BILLING_COUNTRY_CURRENCY_MAP = {
    "CO": "COP",
    "US": "USD",
}


# ──────────────────────────────────────────────
# Security (production)
# ──────────────────────────────────────────────
if not DEBUG:
    print("DEBUG is False, setting security settings")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"