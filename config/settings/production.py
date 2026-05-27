"""Production settings (Heroku-friendly)."""
import dj_database_url

from .base import *  # noqa: F401,F403
from .base import MIDDLEWARE

DEBUG = False
DATABASES = {"default": dj_database_url.config(conn_max_age=600, ssl_require=True)}
MIDDLEWARE.insert(
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
    "whitenoise.middleware.WhiteNoiseMiddleware",
)
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
