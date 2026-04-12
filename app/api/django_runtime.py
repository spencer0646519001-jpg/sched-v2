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

import datetime as dt
from decimal import Decimal

from django.urls import URLPattern

from app.api.django_urls import build_monthly_schedule_urlpatterns
from app.api.routes import MonthlyScheduleRoutes, build_month_schedule_routes
from app.engine.contracts import (
    AssignmentOutput,
    MonthPlanningInput,
    MonthPlanningMetadata,
    MonthPlanningResult,
    MonthPlanningSummary,
)
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
                else _DeterministicPreviewEngine()
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


class _DeterministicPreviewEngine:
    """Temporary deterministic preview engine for the first Django slice.

    The pure scheduling engine is still deferred. This adapter gives the Django
    runtime one honest, reviewable preview result assembled from persisted
    worker/station/shift inputs so preview -> apply -> save can run end-to-end.
    """

    def __call__(self, planning_input: MonthPlanningInput) -> MonthPlanningResult:
        active_shift = next(
            (
                shift
                for shift in planning_input.shifts
                if not shift.is_off_shift
            ),
            None,
        )
        active_station_codes = [
            station.station_code
            for station in planning_input.stations
            if station.is_active
        ]

        assignments: list[AssignmentOutput] = []
        if active_shift is not None:
            assignment_date = dt.date(planning_input.year, planning_input.month, 1)
            for worker in planning_input.workers:
                if not worker.is_active:
                    continue
                assignments.append(
                    AssignmentOutput(
                        date=assignment_date,
                        worker_code=worker.worker_code,
                        shift_code=active_shift.shift_code,
                        station_code=_pick_station_code(
                            worker_station_skills=worker.station_skills,
                            active_station_codes=active_station_codes,
                        ),
                        source="preview",
                        note="Temporary Django runtime preview assignment.",
                    )
                )

        assignments_by_worker: dict[str, int] = {}
        paid_hours_by_worker: dict[str, Decimal] = {}
        if active_shift is not None:
            for assignment in assignments:
                assignments_by_worker[assignment.worker_code] = (
                    assignments_by_worker.get(assignment.worker_code, 0) + 1
                )
            paid_hours_by_worker = {
                worker_code: active_shift.paid_hours * assignment_count
                for worker_code, assignment_count in assignments_by_worker.items()
            }

        return MonthPlanningResult(
            assignments=assignments,
            warnings=[],
            summary=MonthPlanningSummary(
                total_assignments=len(assignments),
                total_warnings=0,
                assignments_by_worker=assignments_by_worker,
                paid_hours_by_worker=paid_hours_by_worker,
                warnings_by_type={},
            ),
            metadata=MonthPlanningMetadata(
                generated_at=dt.datetime.now(tz=dt.timezone.utc),
                source_type="preview",
                refinement_applied=False,
                notes=["temporary-django-runtime-engine"],
            ),
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


def _pick_station_code(
    *,
    worker_station_skills: list[str],
    active_station_codes: list[str],
) -> str | None:
    """Prefer a worker's declared station skill, then fall back to any station."""

    for station_code in worker_station_skills:
        if station_code in active_station_codes:
            return station_code
    if active_station_codes:
        return active_station_codes[0]
    return None


__all__ = [
    "build_django_monthly_schedule_routes",
    "build_django_monthly_schedule_urlpatterns",
]
