from __future__ import annotations

import importlib
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import override_settings

from app.monthly_workspace_demo_data import (
    DEMO_CONSTRAINT_CONFIG,
    DEMO_MONTH_SCOPE,
    DEMO_SHIFTS,
    DEMO_STATIONS,
    DEMO_TENANT_SLUG,
    DEMO_WORKERS,
)
from app.infra.django_app.models import (
    ConstraintConfig as DjangoConstraintConfig,
    LeaveRequest as DjangoLeaveRequest,
    MonthlyAssignment as DjangoMonthlyAssignment,
    MonthlyCandidatePreview as DjangoMonthlyCandidatePreview,
    MonthlyPlanVersion as DjangoMonthlyPlanVersion,
    MonthlyWorkspace as DjangoMonthlyWorkspace,
    ShiftDefinition as DjangoShiftDefinition,
    Station as DjangoStation,
    Tenant as DjangoTenant,
    Worker as DjangoWorker,
    WorkerStationSkill as DjangoWorkerStationSkill,
)


@pytest.fixture(autouse=True)
def _clear_scheduler_tables() -> None:
    DjangoMonthlyCandidatePreview.objects.all().delete()
    DjangoLeaveRequest.objects.all().delete()
    DjangoConstraintConfig.objects.all().delete()
    DjangoMonthlyAssignment.objects.all().delete()
    DjangoMonthlyPlanVersion.objects.all().delete()
    DjangoMonthlyWorkspace.objects.all().delete()
    DjangoWorkerStationSkill.objects.all().delete()
    DjangoShiftDefinition.objects.all().delete()
    DjangoStation.objects.all().delete()
    DjangoWorker.objects.all().delete()
    DjangoTenant.objects.all().delete()


def test_localdev_urlconf_exposes_monthly_workspace_page() -> None:
    from app.localdev_urls import urlpatterns

    assert [pattern.name for pattern in urlpatterns] == [
        "monthly_schedule_workspace",
        "monthly_schedule_workspace_export_csv",
    ]
    assert [str(pattern.pattern) for pattern in urlpatterns] == [
        "v2/monthly-workspace",
        "v2/monthly-workspace/export.csv",
    ]


def test_localdev_urlconf_mounts_admin_only_when_enabled() -> None:
    import app.localdev_urls as localdev_urls

    localdev_urls = importlib.reload(localdev_urls)

    assert "admin/" not in {str(pattern.pattern) for pattern in localdev_urls.urlpatterns}

    with override_settings(
        ENABLE_DJANGO_ADMIN=True,
        INSTALLED_APPS=[
            "django.contrib.admin",
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django.contrib.sessions",
            "django.contrib.messages",
            "django.contrib.staticfiles",
            "app.infra.django_app.apps.SchedulerInfraConfig",
        ],
    ):
        localdev_urls = importlib.reload(localdev_urls)

    assert "admin/" in {str(pattern.pattern) for pattern in localdev_urls.urlpatterns}

    localdev_urls = importlib.reload(localdev_urls)

    assert "admin/" not in {str(pattern.pattern) for pattern in localdev_urls.urlpatterns}


def test_admin_local_settings_enable_private_admin_stack() -> None:
    from app import admin_local_settings

    assert admin_local_settings.ROOT_URLCONF == "app.localdev_urls"
    assert admin_local_settings.ENABLE_DJANGO_ADMIN is True
    assert "django.contrib.admin" in admin_local_settings.INSTALLED_APPS
    assert "django.contrib.auth" in admin_local_settings.INSTALLED_APPS
    assert "django.contrib.sessions.middleware.SessionMiddleware" in (
        admin_local_settings.MIDDLEWARE
    )
    assert "django.contrib.auth.middleware.AuthenticationMiddleware" in (
        admin_local_settings.MIDDLEWARE
    )


def test_deploy_settings_keep_admin_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DJANGO_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ALLOWED_HOSTS", "testserver")

    from app import deploy_settings

    deploy_settings = importlib.reload(deploy_settings)

    assert deploy_settings.ENABLE_DJANGO_ADMIN is False
    assert "django.contrib.admin" not in deploy_settings.INSTALLED_APPS


def test_seed_monthly_workspace_demo_is_idempotent_and_reviewable() -> None:
    stdout = StringIO()

    call_command("seed_monthly_workspace_demo", stdout=stdout)
    call_command("seed_monthly_workspace_demo", stdout=stdout)

    assert DjangoTenant.objects.filter(slug=DEMO_TENANT_SLUG).count() == 1
    seeded_workers = {
        row["code"]: row
        for row in DjangoWorker.objects.filter(tenant__slug=DEMO_TENANT_SLUG).values(
            "code",
            "name",
            "role",
            "is_active",
        )
    }
    seeded_profiles = {
        row["code"]: row["scheduling_profile_json"] or {}
        for row in DjangoWorker.objects.filter(tenant__slug=DEMO_TENANT_SLUG).values(
            "code",
            "scheduling_profile_json",
        )
    }
    seeded_stations = {
        row["code"]: row
        for row in DjangoStation.objects.filter(tenant__slug=DEMO_TENANT_SLUG).values(
            "code",
            "name",
            "is_active",
        )
    }
    seeded_shifts = {
        row["code"]: row
        for row in DjangoShiftDefinition.objects.filter(
            tenant__slug=DEMO_TENANT_SLUG
        ).values(
            "code",
            "name",
            "paid_hours",
            "start_time",
            "end_time",
            "is_off_shift",
        )
    }
    seeded_station_skills = {worker.code: [] for worker in DEMO_WORKERS}
    for worker_code, station_code in DjangoWorkerStationSkill.objects.filter(
        tenant__slug=DEMO_TENANT_SLUG
    ).order_by("worker_id", "station__code", "station_id", "id").values_list(
        "worker__code",
        "station__code",
    ):
        seeded_station_skills[worker_code].append(station_code)

    assert seeded_workers == {
        worker.code: {
            "code": worker.code,
            "name": worker.name,
            "role": worker.role,
            "is_active": worker.is_active,
        }
        for worker in DEMO_WORKERS
    }
    assert seeded_stations == {
        station.code: {
            "code": station.code,
            "name": station.name,
            "is_active": station.is_active,
        }
        for station in DEMO_STATIONS
    }
    assert seeded_shifts == {
        shift.code: {
            "code": shift.code,
            "name": shift.name,
            "paid_hours": shift.paid_hours,
            "start_time": shift.start_time,
            "end_time": shift.end_time,
            "is_off_shift": shift.is_off_shift,
        }
        for shift in DEMO_SHIFTS
    }
    assert seeded_station_skills == {
        worker.code: sorted(worker.station_skills)
        for worker in DEMO_WORKERS
    }
    assert seeded_profiles == {
        worker.code: worker.scheduling_profile.as_json()
        for worker in DEMO_WORKERS
    }
    assert DjangoConstraintConfig.objects.filter(
        tenant__slug=DEMO_TENANT_SLUG,
        scope_type="default",
    ).count() == 1
    seeded_config = DjangoConstraintConfig.objects.get(
        tenant__slug=DEMO_TENANT_SLUG,
        scope_type="default",
    ).config_json
    assert seeded_config["morning_shifts"] == ["1"]
    assert seeded_config["stations_require_morning"] == {"gateau": 1}
    assert seeded_config["required_chefs_weekday"] == 1
    assert seeded_config["required_chefs_weekend"] == 2
    assert seeded_config["allowed_auto_shifts_weekday"] == ["A", "B", "C", "D"]
    assert seeded_config["allowed_auto_shifts_weekend"] == [
        "1",
        "2",
        "3",
        "4",
        "A",
        "B",
        "C",
        "D",
    ]
    assert seeded_config == DEMO_CONSTRAINT_CONFIG
    assert (
        "http://127.0.0.1:8000/v2/monthly-workspace"
        f"?tenant_slug={DEMO_TENANT_SLUG}&month_scope={DEMO_MONTH_SCOPE}"
    ) in stdout.getvalue()
