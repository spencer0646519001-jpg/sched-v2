"""Pydantic transport schemas for the V2 monthly scheduling API.

These models define request and response shapes for the API layer only.
Routes should translate between these schemas and the service-layer dataclasses
rather than reusing persistence models or engine contracts directly.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator

ApiJsonObject: TypeAlias = dict[str, Any]


class ApiSchema(BaseModel):
    """Closed-base schema used by all API request and response models."""

    model_config = ConfigDict(extra="forbid")


class TenantMonthScopeSchema(ApiSchema):
    """Shared tenant/month selector reused by the monthly scheduling endpoints."""

    tenant_slug: str = Field(min_length=1)
    year: int = Field(ge=1)
    month: int = Field(ge=1, le=12)

    @field_validator("tenant_slug")
    @classmethod
    def _validate_tenant_slug(cls, value: str) -> str:
        """Reject blank tenant selectors while keeping the transport layer thin."""

        if not value.strip():
            raise ValueError("tenant_slug must not be blank.")
        return value


class MonthPlanningAssignmentSchema(ApiSchema):
    """API-facing assignment row used in preview, apply, and refine payloads."""

    date: dt.date
    worker_code: str = Field(min_length=1)
    shift_code: str = Field(min_length=1)
    source: str = Field(min_length=1)
    station_code: str | None = None
    note: str | None = None


class MonthPlanningWarningSchema(ApiSchema):
    """Structured warning payload keyed for future localized presentation."""

    type: str = Field(min_length=1)
    message_key: str = Field(min_length=1)
    worker_code: str | None = None
    date: dt.date | None = None
    details: ApiJsonObject | None = None


class MonthPlanningSummarySchema(ApiSchema):
    """Compact monthly aggregates that clients can render or inspect later."""

    total_assignments: int = Field(ge=0)
    total_warnings: int = Field(ge=0)
    assignments_by_worker: dict[str, int] = Field(default_factory=dict)
    paid_hours_by_worker: dict[str, Decimal] = Field(default_factory=dict)
    warnings_by_type: dict[str, int] = Field(default_factory=dict)


class MonthPlanningMetadataSchema(ApiSchema):
    """Execution metadata about how a month-planning result was produced."""

    generated_at: dt.datetime
    source_type: str = Field(min_length=1)
    refinement_applied: bool
    notes: list[str] | None = None


class MonthPlanningResultSchema(ApiSchema):
    """Reusable month-planning result envelope for preview/apply/refine flows."""

    assignments: list[MonthPlanningAssignmentSchema] = Field(default_factory=list)
    warnings: list[MonthPlanningWarningSchema] = Field(default_factory=list)
    summary: MonthPlanningSummarySchema
    metadata: MonthPlanningMetadataSchema


class PreviewMonthScheduleRequestSchema(TenantMonthScopeSchema):
    """Transport request for a read-only month preview."""


class PreviewMonthScheduleResponseSchema(ApiSchema):
    """Transport response carrying the requested scope and computed preview."""

    request: PreviewMonthScheduleRequestSchema
    result: MonthPlanningResultSchema


class ApplyMonthScheduleRequestSchema(TenantMonthScopeSchema):
    """Transport request for applying a planning result to current workspace."""

    result: MonthPlanningResultSchema


class ApplyMonthScheduleResponseSchema(TenantMonthScopeSchema):
    """Transport response after replacing the current workspace assignments."""

    workspace_id: str = Field(min_length=1)
    workspace_status: str = Field(min_length=1)
    assignment_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    workspace_created: bool


class SaveMonthScheduleRequestSchema(TenantMonthScopeSchema):
    """Transport request for snapshotting the current mutable month state."""

    label: str | None = None
    note: str | None = None


class SaveMonthScheduleResponseSchema(TenantMonthScopeSchema):
    """Transport response describing one immutable saved month version."""

    version_id: str = Field(min_length=1)
    version_number: int = Field(ge=1)
    workspace_id: str = Field(min_length=1)
    assignment_count: int = Field(ge=0)


class RefineMonthScheduleRequestSchema(TenantMonthScopeSchema):
    """Transport request for one natural-language month adjustment attempt."""

    request_text: str = Field(min_length=1)

    @field_validator("request_text")
    @classmethod
    def _validate_request_text(cls, value: str) -> str:
        """Reject whitespace-only refine input at the API boundary."""

        if not value.strip():
            raise ValueError("request_text must not be blank.")
        return value


class RefineMonthScheduleResponseSchema(TenantMonthScopeSchema):
    """Transport response with stored refine metadata and candidate result."""

    workspace_id: str = Field(min_length=1)
    refine_request_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    parsed_intent_json: ApiJsonObject
    candidate_result: MonthPlanningResultSchema


class ExportMonthScheduleRequestSchema(TenantMonthScopeSchema):
    """Transport request for exporting the current workspace month view."""


class ExportMonthScheduleRowSchema(ApiSchema):
    """Flat export row that clients can render directly or convert to CSV."""

    assignment_date: dt.date
    worker_code: str = Field(min_length=1)
    worker_name: str = Field(min_length=1)
    worker_role: str = Field(min_length=1)
    shift_code: str = Field(min_length=1)
    shift_name: str = Field(min_length=1)
    station_code: str | None = None
    station_name: str | None = None


class ExportMonthScheduleResponseSchema(TenantMonthScopeSchema):
    """Transport response for the current month export payload."""

    workspace_id: str = Field(min_length=1)
    workspace_status: str = Field(min_length=1)
    row_count: int = Field(ge=0)
    rows: list[ExportMonthScheduleRowSchema] = Field(default_factory=list)
    csv_text: str


__all__ = [
    "ApiJsonObject",
    "ApiSchema",
    "ApplyMonthScheduleRequestSchema",
    "ApplyMonthScheduleResponseSchema",
    "ExportMonthScheduleRequestSchema",
    "ExportMonthScheduleResponseSchema",
    "ExportMonthScheduleRowSchema",
    "MonthPlanningAssignmentSchema",
    "MonthPlanningMetadataSchema",
    "MonthPlanningResultSchema",
    "MonthPlanningSummarySchema",
    "MonthPlanningWarningSchema",
    "PreviewMonthScheduleRequestSchema",
    "PreviewMonthScheduleResponseSchema",
    "RefineMonthScheduleRequestSchema",
    "RefineMonthScheduleResponseSchema",
    "SaveMonthScheduleRequestSchema",
    "SaveMonthScheduleResponseSchema",
    "TenantMonthScopeSchema",
]
