"""Django runtime composition for the first V2 monthly scheduling slice.

This module keeps Django as the practical entry point while preserving the
existing boundaries:
- views stay thin through the reusable route adapter
- services remain framework-neutral
- Django ORM usage stays inside repository adapters

Only the first vertical slice is wired here for now: preview, apply, and save.
Refine and export remain deferred to later PRs.
"""

from __future__ import annotations

from django.urls import URLPattern

from app.api.django_urls import build_monthly_schedule_urlpatterns
from app.api.routes import MonthlyScheduleRoutes, build_month_schedule_routes
from app.engine.monthly import generate_month_plan
from app.infra.django_repositories import (
    DjangoPlanVersionRepository,
    DjangoShiftRepository,
    DjangoStationRepository,
    DjangoTenantRepository,
    DjangoWorkerRepository,
    DjangoWorkspaceRepository,
)
from app.infra.models import ConstraintConfig
from app.services.apply import ApplyMonthScheduleService
from app.services.preview import (
    MonthlySchedulePreviewEngine,
    PreviewMonthScheduleService,
)
from app.services.save import SaveMonthScheduleService


def build_django_monthly_schedule_routes(
    *,
    preview_engine: MonthlySchedulePreviewEngine | None = None,
) -> MonthlyScheduleRoutes:
    """Compose the first Django-backed runtime slice for preview/apply/save."""

    tenant_repository = DjangoTenantRepository()
    worker_repository = DjangoWorkerRepository()
    station_repository = DjangoStationRepository()
    shift_repository = DjangoShiftRepository()
    workspace_repository = DjangoWorkspaceRepository()

    return build_month_schedule_routes(
        preview_service=PreviewMonthScheduleService(
            tenant_repository=tenant_repository,
            worker_repository=worker_repository,
            station_repository=station_repository,
            shift_repository=shift_repository,
            leave_request_repository=_NoOpLeaveRequestRepository(),
            constraint_config_repository=_FixedConstraintConfigRepository(),
            engine_runner=(
                preview_engine
                if preview_engine is not None
                else generate_month_plan
            ),
        ),
        apply_service=ApplyMonthScheduleService(
            tenant_repository=tenant_repository,
            worker_repository=worker_repository,
            station_repository=station_repository,
            shift_repository=shift_repository,
            workspace_repository=workspace_repository,
        ),
        save_service=SaveMonthScheduleService(
            tenant_repository=tenant_repository,
            workspace_repository=workspace_repository,
            plan_version_repository=DjangoPlanVersionRepository(),
        ),
    )


def build_django_monthly_schedule_urlpatterns(
    *,
    preview_engine: MonthlySchedulePreviewEngine | None = None,
) -> list[URLPattern]:
    """Build Django URL patterns for the preview/apply/save runtime slice."""

    return build_monthly_schedule_urlpatterns(
        build_django_monthly_schedule_routes(preview_engine=preview_engine)
    )


class _NoOpLeaveRequestRepository:
    """Temporary runtime adapter until Django leave persistence exists."""

    def list_for_month(
        self,
        tenant_id: str,
        year: int,
        month: int,
    ) -> list[object]:
        del tenant_id, year, month
        return []


class _FixedConstraintConfigRepository:
    """Temporary runtime adapter until constraint persistence is implemented."""

    def get_resolved_for_month(
        self,
        tenant_id: str,
        year: int,
        month: int,
    ) -> ConstraintConfig:
        return ConstraintConfig(
            tenant_id=tenant_id,
            scope_type="monthly",
            year=year,
            month=month,
            config_json={"max_weekly_hours": 40},
        )


__all__ = [
    "build_django_monthly_schedule_routes",
    "build_django_monthly_schedule_urlpatterns",
]
