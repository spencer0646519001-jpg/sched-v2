"""Django runtime composition for the first V2 monthly scheduling slice.

This module keeps Django as the practical entry point while preserving the
existing boundaries:
- views stay thin through the reusable route adapter
- services remain framework-neutral
- Django ORM usage stays inside repository adapters

The current runtime wires preview/apply/save plus bounded explain/refine/export
paths while keeping Django-specific response handling thin.
"""

from __future__ import annotations

from django.urls import URLPattern

from app.api.django_workspace import build_django_monthly_workspace_urlpatterns
from app.api.django_urls import build_monthly_schedule_urlpatterns
from app.api.routes import MonthlyScheduleRoutes, build_month_schedule_routes
from app.ai.interfaces import AudioTranscriptionClient
from app.ai.openai_client import (
    build_explain_model_client_from_env,
    build_refine_model_client_from_env,
)
from app.engine.monthly import generate_month_plan
from app.infra.django_repositories import (
    DjangoConstraintConfigRepository,
    DjangoLeaveRequestRepository,
    DjangoPlanVersionRepository,
    DjangoRefineRequestRepository,
    DjangoShiftRepository,
    DjangoStationRepository,
    DjangoTenantRepository,
    DjangoWorkerRepository,
    DjangoWorkspaceRepository,
)
from app.services.apply import ApplyMonthScheduleService
from app.services.explain import ExplainDayScheduleService
from app.services.explain_langgraph import LangGraphDayExplainWorkflow
from app.services.export import ExportMonthScheduleService
from app.services.preview import (
    MonthlySchedulePreviewEngine,
    PreviewMonthScheduleService,
)
from app.services.refine import RefineMonthScheduleService
from app.services.refine_langgraph import LangGraphRefineWorkflow
from app.services.save import SaveMonthScheduleService


def build_django_monthly_schedule_routes(
    *,
    preview_engine: MonthlySchedulePreviewEngine | None = None,
) -> MonthlyScheduleRoutes:
    """Compose the Django-backed runtime slice for preview/apply/save/export."""

    tenant_repository = DjangoTenantRepository()
    worker_repository = DjangoWorkerRepository()
    station_repository = DjangoStationRepository()
    shift_repository = DjangoShiftRepository()
    leave_request_repository = DjangoLeaveRequestRepository()
    constraint_config_repository = DjangoConstraintConfigRepository()
    workspace_repository = DjangoWorkspaceRepository()
    resolved_preview_engine = (
        preview_engine if preview_engine is not None else generate_month_plan
    )

    return build_month_schedule_routes(
        preview_service=PreviewMonthScheduleService(
            tenant_repository=tenant_repository,
            worker_repository=worker_repository,
            station_repository=station_repository,
            shift_repository=shift_repository,
            leave_request_repository=leave_request_repository,
            constraint_config_repository=constraint_config_repository,
            engine_runner=resolved_preview_engine,
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
        explain_service=ExplainDayScheduleService(
            tenant_repository=tenant_repository,
            worker_repository=worker_repository,
            station_repository=station_repository,
            shift_repository=shift_repository,
            leave_request_repository=leave_request_repository,
            constraint_config_repository=constraint_config_repository,
            workspace_repository=workspace_repository,
            workflow=LangGraphDayExplainWorkflow(
                model_client=build_explain_model_client_from_env()
            ),
        ),
        refine_service=RefineMonthScheduleService(
            tenant_repository=tenant_repository,
            worker_repository=worker_repository,
            station_repository=station_repository,
            shift_repository=shift_repository,
            leave_request_repository=leave_request_repository,
            constraint_config_repository=constraint_config_repository,
            workspace_repository=workspace_repository,
            refine_request_repository=DjangoRefineRequestRepository(),
            workflow=LangGraphRefineWorkflow(
                engine_runner=resolved_preview_engine,
                model_client=build_refine_model_client_from_env(),
            ),
        ),
        export_service=ExportMonthScheduleService(
            tenant_repository=tenant_repository,
            worker_repository=worker_repository,
            station_repository=station_repository,
            shift_repository=shift_repository,
            workspace_repository=workspace_repository,
        ),
    )


def build_django_monthly_schedule_urlpatterns(
    *,
    preview_engine: MonthlySchedulePreviewEngine | None = None,
) -> list[URLPattern]:
    """Build Django URL patterns for the preview/apply/save/export slice."""

    return build_monthly_schedule_urlpatterns(
        build_django_monthly_schedule_routes(preview_engine=preview_engine)
    )


def build_django_monthly_workspace_page_urlpatterns(
    *,
    preview_engine: MonthlySchedulePreviewEngine | None = None,
    transcription_client: AudioTranscriptionClient | None = None,
) -> list[URLPattern]:
    """Build Django URL patterns for the reviewer-visible monthly workspace page."""

    return build_django_monthly_workspace_urlpatterns(
        preview_engine=preview_engine,
        transcription_client=transcription_client,
    )


__all__ = [
    "build_django_monthly_schedule_routes",
    "build_django_monthly_schedule_urlpatterns",
    "build_django_monthly_workspace_page_urlpatterns",
]
