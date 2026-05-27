"""Local development settings."""
from .base import *  # noqa: F401,F403
from .base import BASE_DIR

DEBUG = True
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
