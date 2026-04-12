from django.apps import AppConfig


class SchedulerInfraConfig(AppConfig):
    """Django app config for the first real V2 persistence slice."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "app.infra.django_app"
    label = "scheduler_infra"
    verbose_name = "Scheduler Infra Persistence"

