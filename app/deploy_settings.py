"""Environment-driven Django settings for portfolio/demo deployment."""

from __future__ import annotations

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SQLITE_PATH = Path("/data/sched-v2.sqlite3")


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"{name} must be set for demo deployment.")
    return value


def _env_bool(name: str, *, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    return raw_value.strip().casefold() in {"1", "true", "yes", "on"}


def _comma_separated_env(name: str) -> list[str]:
    raw_value = _required_env(name)
    values = [part.strip() for part in raw_value.split(",") if part.strip()]
    if not values:
        raise ImproperlyConfigured(f"{name} must contain at least one host.")
    return values


DEBUG = _env_bool("DJANGO_DEBUG", default=False)
SECRET_KEY = _required_env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = _comma_separated_env("ALLOWED_HOSTS")

ROOT_URLCONF = "app.localdev_urls"
ENABLE_DJANGO_ADMIN = False

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "app.infra.django_app.apps.SchedulerInfraConfig",
]

MIDDLEWARE: list[str] = []

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.getenv("SCHED_V2_SQLITE_PATH", str(DEFAULT_SQLITE_PATH)),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DEFAULT_CHARSET = "utf-8"
TIME_ZONE = "UTC"
USE_TZ = True
