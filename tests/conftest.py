from __future__ import annotations

import django
from django.apps import apps
from django.conf import settings
from django.core.management import call_command


if not settings.configured:
    settings.configure(
        ALLOWED_HOSTS=["testserver"],
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": ":memory:",
            }
        },
        DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
        DEFAULT_CHARSET="utf-8",
        INSTALLED_APPS=[
            "django.contrib.contenttypes",
            "app.infra.django_app.apps.SchedulerInfraConfig",
        ],
        SECRET_KEY="test-secret-key",
        TIME_ZONE="UTC",
        USE_TZ=True,
    )

if not apps.ready:
    django.setup()

call_command("migrate", interactive=False, verbosity=0)

