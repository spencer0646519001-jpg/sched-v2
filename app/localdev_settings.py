"""Minimal local Django settings for manually reviewing the monthly workspace."""

from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = True
SECRET_KEY = "sched-v2-localdev-secret-key"
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

ROOT_URLCONF = "app.localdev_urls"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "app.infra.django_app.apps.SchedulerInfraConfig",
]

MIDDLEWARE: list[str] = []

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(BASE_DIR / "localdev.sqlite3"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DEFAULT_CHARSET = "utf-8"
TIME_ZONE = "UTC"
USE_TZ = True
