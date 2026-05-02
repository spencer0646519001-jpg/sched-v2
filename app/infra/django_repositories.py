"""Django ORM-backed repository adapters for the first V2 vertical slice.

These adapters are intentionally thin. They keep Django model usage inside the
repository layer and translate explicitly to the framework-neutral dataclasses
consumed by services and the engine boundary.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from copy import deepcopy
from decimal import Decimal

from django.db import transaction
from django.db.models import Max

from app.infra.django_app.models import (
    ConstraintConfig as DjangoConstraintConfig,
    LeaveRequest as DjangoLeaveRequest,
    MonthlyAssignment as DjangoMonthlyAssignment,
    MonthlyCandidatePreview as DjangoMonthlyCandidatePreview,
    MonthlyPlanVersion as DjangoMonthlyPlanVersion,
    MonthlyWorkspace as DjangoMonthlyWorkspace,
    RefineRequest as DjangoRefineRequest,
    ShiftDefinition as DjangoShiftDefinition,
    Station as DjangoStation,
    Tenant as DjangoTenant,
    Worker as DjangoWorker,
    WorkerStationSkill as DjangoWorkerStationSkill,
)
from app.infra.models import (
    ConstraintConfig,
    JsonObject,
    LeaveRequest,
    MonthlyAssignment,
    MonthlyCandidatePreview,
    MonthlyPlanVersion,
    MonthlyWorkspace,
    RecordId,
    RefineRequest,
    ShiftDefinition,
    Station,
    Tenant,
    Worker,
    WorkerStationSkill,
)
from app.infra.repositories import CurrentWorkspaceState

_SUPPORTED_CONSTRAINT_CONFIG_KEYS = (
    "stations",
    "morning_shifts",
    "stations_require_morning",
    "min_staff_weekday",
    "min_staff_weekend",
    "max_staff_per_day",
    "min_rest_days_per_month",
    "max_consecutive_days",
    "required_chefs_weekday",
    "required_chefs_weekend",
    "allowed_auto_shifts_weekday",
    "allowed_auto_shifts_weekend",
    "require_one_chef",
    "count_chefs_in_headcount",
    "chefs_have_no_shift",
)


def _serialize_record_id(value: object) -> RecordId:
    """Normalize Django primary keys to the string ids used by dataclasses."""

    return str(value)


def _parse_record_id(record_id: RecordId | None, *, label: str) -> int:
    """Convert framework-neutral ids back to the integer Django PK shape."""

    if record_id is None:
        raise ValueError(f"{label} must be populated for Django persistence.")

    try:
        return int(record_id)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{label} must be a numeric Django-backed record id."
        ) from exc


def _tenant_from_model(model: DjangoTenant) -> Tenant:
    return Tenant(
        id=_serialize_record_id(model.pk),
        slug=model.slug,
        name=model.name,
    )


def _worker_from_model(model: DjangoWorker) -> Worker:
    return Worker(
        id=_serialize_record_id(model.pk),
        tenant_id=_serialize_record_id(model.tenant_id),
        name=model.name,
        role=model.role,
        code=model.code,
        is_active=model.is_active,
        scheduling_profile_json=(
            deepcopy(model.scheduling_profile_json)
            if model.scheduling_profile_json
            else None
        ),
    )


def _station_from_model(model: DjangoStation) -> Station:
    return Station(
        id=_serialize_record_id(model.pk),
        tenant_id=_serialize_record_id(model.tenant_id),
        name=model.name,
        code=model.code,
        is_active=model.is_active,
    )


def _shift_from_model(model: DjangoShiftDefinition) -> ShiftDefinition:
    return ShiftDefinition(
        id=_serialize_record_id(model.pk),
        tenant_id=_serialize_record_id(model.tenant_id),
        code=model.code,
        name=model.name,
        paid_hours=model.paid_hours,
        start_time=model.start_time,
        end_time=model.end_time,
        is_off_shift=model.is_off_shift,
        # The first real Django slice has no persisted inactive flag yet.
        is_active=True,
    )


def _leave_request_from_model(model: DjangoLeaveRequest) -> LeaveRequest:
    return LeaveRequest(
        id=_serialize_record_id(model.pk),
        tenant_id=_serialize_record_id(model.tenant_id),
        worker_id=_serialize_record_id(model.worker_id),
        leave_date=model.leave_date,
        reason=model.reason,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _constraint_config_from_model(model: DjangoConstraintConfig) -> ConstraintConfig:
    return ConstraintConfig(
        id=_serialize_record_id(model.pk),
        tenant_id=_serialize_record_id(model.tenant_id),
        scope_type=model.scope_type,
        year=model.year,
        month=model.month,
        config_json=_normalize_constraint_config_json(model.config_json),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _workspace_from_model(model: DjangoMonthlyWorkspace) -> MonthlyWorkspace:
    return MonthlyWorkspace(
        id=_serialize_record_id(model.pk),
        tenant_id=_serialize_record_id(model.tenant_id),
        year=model.year,
        month=model.month,
        status=model.status,
        is_current=True,
        source_version_id=(
            _serialize_record_id(model.source_version_id)
            if model.source_version_id is not None
            else None
        ),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _assignment_from_model(model: DjangoMonthlyAssignment) -> MonthlyAssignment:
    return MonthlyAssignment(
        id=_serialize_record_id(model.pk),
        workspace_id=_serialize_record_id(model.workspace_id),
        worker_id=_serialize_record_id(model.worker_id),
        assignment_date=model.assignment_date,
        shift_definition_id=_serialize_record_id(model.shift_definition_id),
        station_id=(
            _serialize_record_id(model.station_id)
            if model.station_id is not None
            else None
        ),
        note=model.note,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _worker_station_skill_from_model(
    model: DjangoWorkerStationSkill,
) -> WorkerStationSkill:
    return WorkerStationSkill(
        id=_serialize_record_id(model.pk),
        tenant_id=_serialize_record_id(model.tenant_id),
        worker_id=_serialize_record_id(model.worker_id),
        station_id=_serialize_record_id(model.station_id),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _plan_version_from_model(model: DjangoMonthlyPlanVersion) -> MonthlyPlanVersion:
    workspace = model.workspace
    return MonthlyPlanVersion(
        id=_serialize_record_id(model.pk),
        tenant_id=_serialize_record_id(model.tenant_id),
        year=workspace.year,
        month=workspace.month,
        version_number=model.version_number,
        snapshot_json=deepcopy(model.snapshot_json),
        workspace_id=_serialize_record_id(model.workspace_id),
        summary=model.summary,
        created_at=model.created_at,
    )


def _candidate_preview_from_model(
    model: DjangoMonthlyCandidatePreview,
) -> MonthlyCandidatePreview:
    return MonthlyCandidatePreview(
        id=_serialize_record_id(model.pk),
        tenant_id=_serialize_record_id(model.tenant_id),
        year=model.year,
        month=model.month,
        result_json=deepcopy(model.result_json),
        input_fingerprint=model.input_fingerprint,
        created_at=model.created_at,
    )


def _refine_request_from_model(model: DjangoRefineRequest) -> RefineRequest:
    return RefineRequest(
        id=_serialize_record_id(model.pk),
        tenant_id=_serialize_record_id(model.tenant_id),
        workspace_id=_serialize_record_id(model.workspace_id),
        request_text=model.request_text,
        status=model.status,
        parsed_intent_json=(
            deepcopy(model.parsed_intent_json)
            if model.parsed_intent_json is not None
            else None
        ),
        result_preview_json=(
            deepcopy(model.result_preview_json)
            if model.result_preview_json is not None
            else None
        ),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _derive_workspace_source_type(workspace: MonthlyWorkspace) -> str:
    """Infer the persisted workspace origin from the neutral workspace record."""

    if workspace.source_version_id is not None:
        return "restore"
    return "preview"


def _normalize_constraint_config_json(config_json: object) -> dict[str, object]:
    """Project persisted config JSON down to the planner-supported subset only."""

    if not isinstance(config_json, dict):
        raise ValueError("Constraint config JSON must be a JSON object.")

    normalized: dict[str, object] = {}
    for key in _SUPPORTED_CONSTRAINT_CONFIG_KEYS:
        if key not in config_json:
            continue
        value = deepcopy(config_json[key])
        if key == "stations" and not isinstance(value, dict):
            continue
        normalized[key] = value
    return normalized


def _require_workspace_model(
    workspace_id: RecordId,
    *,
    label: str,
) -> DjangoMonthlyWorkspace:
    """Load one workspace row or fail with a lookup-safe error."""

    workspace = DjangoMonthlyWorkspace.objects.filter(
        pk=_parse_record_id(workspace_id, label=label)
    ).first()
    if workspace is None:
        raise LookupError(f"{label} was not found.")
    return workspace


def _assert_workspace_matches_tenant(
    workspace: DjangoMonthlyWorkspace,
    *,
    tenant_id: RecordId,
    tenant_label: str,
    workspace_label: str,
) -> None:
    """Ensure a workspace row stays inside the expected tenant boundary."""

    tenant_pk = _parse_record_id(tenant_id, label=tenant_label)
    if workspace.tenant_id != tenant_pk:
        raise LookupError(f"{workspace_label} does not belong to {tenant_label}.")


def _assert_record_ids_belong_to_tenant(
    model: type[
        DjangoWorker | DjangoShiftDefinition | DjangoStation
    ],
    record_ids: set[int],
    *,
    tenant_pk: int,
    record_label: str,
) -> None:
    """Reject related record ids that fall outside the workspace tenant."""

    if not record_ids:
        return

    matching_ids = set(
        model.objects.filter(pk__in=record_ids, tenant_id=tenant_pk).values_list(
            "pk",
            flat=True,
        )
    )
    if matching_ids != record_ids:
        raise LookupError(f"{record_label} must belong to the workspace tenant.")


def _calculate_monthly_candidate_input_fingerprint(
    *,
    tenant_pk: int,
    year: int,
    month: int,
) -> str:
    """Hash the persisted inputs that make a candidate safe to apply later."""

    payload = {
        "tenant_id": tenant_pk,
        "year": year,
        "month": month,
        "workers": list(
            DjangoWorker.objects.filter(tenant_id=tenant_pk)
            .order_by("code", "id")
            .values(
                "id",
                "code",
                "name",
                "role",
                "is_active",
                "scheduling_profile_json",
            )
        ),
        "worker_station_skills": list(
            DjangoWorkerStationSkill.objects.filter(tenant_id=tenant_pk)
            .order_by("worker_id", "station_id", "id")
            .values(
                "id",
                "worker_id",
                "station_id",
                "created_at",
                "updated_at",
            )
        ),
        "stations": list(
            DjangoStation.objects.filter(tenant_id=tenant_pk)
            .order_by("code", "id")
            .values("id", "code", "name", "is_active")
        ),
        "shifts": list(
            DjangoShiftDefinition.objects.filter(tenant_id=tenant_pk)
            .order_by("code", "id")
            .values(
                "id",
                "code",
                "name",
                "paid_hours",
                "is_off_shift",
                "start_time",
                "end_time",
            )
        ),
        "leave_requests": list(
            DjangoLeaveRequest.objects.filter(
                tenant_id=tenant_pk,
                leave_date__year=year,
                leave_date__month=month,
            )
            .order_by("leave_date", "worker_id", "id")
            .values(
                "id",
                "worker_id",
                "leave_date",
                "reason",
                "created_at",
                "updated_at",
            )
        ),
        "constraint_config": _resolved_constraint_config_fingerprint_payload(
            tenant_pk=tenant_pk,
            year=year,
            month=month,
        ),
        "current_workspace": _current_workspace_fingerprint_payload(
            tenant_pk=tenant_pk,
            year=year,
            month=month,
        ),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=_fingerprint_json_default,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _resolved_constraint_config_fingerprint_payload(
    *,
    tenant_pk: int,
    year: int,
    month: int,
) -> dict[str, object] | None:
    config = (
        DjangoConstraintConfig.objects.filter(
            tenant_id=tenant_pk,
            scope_type="monthly",
            year=year,
            month=month,
        )
        .order_by("id")
        .values(
            "id",
            "scope_type",
            "year",
            "month",
            "config_json",
            "created_at",
            "updated_at",
        )
        .first()
    )
    if config is not None:
        return config

    return (
        DjangoConstraintConfig.objects.filter(
            tenant_id=tenant_pk,
            scope_type="default",
        )
        .order_by("id")
        .values(
            "id",
            "scope_type",
            "year",
            "month",
            "config_json",
            "created_at",
            "updated_at",
        )
        .first()
    )


def _current_workspace_fingerprint_payload(
    *,
    tenant_pk: int,
    year: int,
    month: int,
) -> dict[str, object] | None:
    workspace = (
        DjangoMonthlyWorkspace.objects.filter(
            tenant_id=tenant_pk,
            year=year,
            month=month,
        )
        .order_by("id")
        .values(
            "id",
            "status",
            "source_type",
            "source_version_id",
            "created_at",
            "updated_at",
        )
        .first()
    )
    if workspace is None:
        return None

    workspace["assignments"] = list(
        DjangoMonthlyAssignment.objects.filter(workspace_id=workspace["id"])
        .order_by("assignment_date", "worker_id", "id")
        .values(
            "id",
            "assignment_date",
            "worker_id",
            "shift_definition_id",
            "station_id",
            "assignment_source",
            "note",
            "created_at",
            "updated_at",
        )
    )
    return workspace


def _fingerprint_json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


class DjangoTenantRepository:
    """Django-backed tenant lookups for service entry points."""

    def get_by_id(self, tenant_id: RecordId) -> Tenant | None:
        tenant = DjangoTenant.objects.filter(
            pk=_parse_record_id(tenant_id, label="tenant_id")
        ).first()
        if tenant is None:
            return None
        return _tenant_from_model(tenant)

    def get_by_slug(self, slug: str) -> Tenant | None:
        tenant = DjangoTenant.objects.filter(slug=slug).first()
        if tenant is None:
            return None
        return _tenant_from_model(tenant)


class DjangoWorkerRepository:
    """Django-backed worker reads for the first monthly planning slice."""

    def list_for_tenant(self, tenant_id: RecordId) -> list[Worker]:
        workers = DjangoWorker.objects.filter(
            tenant_id=_parse_record_id(tenant_id, label="tenant_id")
        ).order_by("code", "id")
        return [_worker_from_model(worker) for worker in workers]

    def list_station_skills(self, tenant_id: RecordId) -> list[WorkerStationSkill]:
        skills = (
            DjangoWorkerStationSkill.objects.filter(
                tenant_id=_parse_record_id(tenant_id, label="tenant_id")
            )
            .select_related("worker", "station")
            .order_by("worker_id", "station__code", "station_id", "id")
        )
        return [_worker_station_skill_from_model(skill) for skill in skills]


class DjangoStationRepository:
    """Django-backed station reads for assignment destination lookups."""

    def list_for_tenant(self, tenant_id: RecordId) -> list[Station]:
        stations = DjangoStation.objects.filter(
            tenant_id=_parse_record_id(tenant_id, label="tenant_id")
        ).order_by("code", "id")
        return [_station_from_model(station) for station in stations]


class DjangoShiftRepository:
    """Django-backed shift definition reads for preview/apply/export flows."""

    def list_for_tenant(self, tenant_id: RecordId) -> list[ShiftDefinition]:
        shifts = DjangoShiftDefinition.objects.filter(
            tenant_id=_parse_record_id(tenant_id, label="tenant_id")
        ).order_by("code", "id")
        return [_shift_from_model(shift) for shift in shifts]


class DjangoLeaveRequestRepository:
    """Django-backed approved leave reads for one tenant/month preview run."""

    def list_for_month(
        self,
        tenant_id: RecordId,
        year: int,
        month: int,
    ) -> list[LeaveRequest]:
        leave_requests = (
            DjangoLeaveRequest.objects.filter(
                tenant_id=_parse_record_id(tenant_id, label="tenant_id"),
                leave_date__year=year,
                leave_date__month=month,
            )
            .select_related("worker")
            .order_by("leave_date", "worker__code", "worker_id", "id")
        )
        return [_leave_request_from_model(row) for row in leave_requests]


class DjangoConstraintConfigRepository:
    """Resolve one effective planner config for a tenant and target month."""

    def get_resolved_for_month(
        self,
        tenant_id: RecordId,
        year: int,
        month: int,
    ) -> ConstraintConfig | None:
        tenant_pk = _parse_record_id(tenant_id, label="tenant_id")
        monthly_config = (
            DjangoConstraintConfig.objects.filter(
                tenant_id=tenant_pk,
                scope_type="monthly",
                year=year,
                month=month,
            )
            .order_by("id")
            .first()
        )
        if monthly_config is not None:
            return _constraint_config_from_model(monthly_config)

        default_config = (
            DjangoConstraintConfig.objects.filter(
                tenant_id=tenant_pk,
                scope_type="default",
            )
            .order_by("id")
            .first()
        )
        if default_config is None:
            return None
        return _constraint_config_from_model(default_config)


class DjangoWorkspaceRepository:
    """Persist and reload the single current workspace for one tenant/month."""

    def load_current(
        self,
        tenant_id: RecordId,
        year: int,
        month: int,
    ) -> CurrentWorkspaceState | None:
        workspace = (
            DjangoMonthlyWorkspace.objects.filter(
                tenant_id=_parse_record_id(tenant_id, label="tenant_id"),
                year=year,
                month=month,
            )
            .select_related("source_version")
            .first()
        )
        if workspace is None:
            return None

        assignments = DjangoMonthlyAssignment.objects.filter(
            workspace_id=workspace.pk
        ).order_by("assignment_date", "worker_id", "id")
        return CurrentWorkspaceState(
            workspace=_workspace_from_model(workspace),
            assignments=[_assignment_from_model(row) for row in assignments],
        )

    def save_current_workspace(self, workspace: MonthlyWorkspace) -> MonthlyWorkspace:
        tenant_pk = _parse_record_id(workspace.tenant_id, label="workspace.tenant_id")
        persisted, _created = DjangoMonthlyWorkspace.objects.update_or_create(
            tenant_id=tenant_pk,
            year=workspace.year,
            month=workspace.month,
            defaults={
                "status": workspace.status,
                "source_type": _derive_workspace_source_type(workspace),
                "source_version_id": (
                    _parse_record_id(
                        workspace.source_version_id,
                        label="workspace.source_version_id",
                    )
                    if workspace.source_version_id is not None
                    else None
                ),
            },
        )
        return _workspace_from_model(persisted)

    def replace_assignments(
        self,
        workspace_id: RecordId,
        assignments: Sequence[MonthlyAssignment],
    ) -> list[MonthlyAssignment]:
        workspace = _require_workspace_model(workspace_id, label="workspace_id")
        workspace_pk = workspace.pk
        tenant_pk = workspace.tenant_id
        parsed_assignments: list[tuple[MonthlyAssignment, int, int, int | None]] = []
        worker_ids: set[int] = set()
        shift_ids: set[int] = set()
        station_ids: set[int] = set()

        create_rows: list[DjangoMonthlyAssignment] = []
        for assignment in assignments:
            if assignment.workspace_id != workspace_id:
                raise ValueError(
                    "All replacement assignments must belong to the target workspace."
                )
            if (
                assignment.assignment_date.year != workspace.year
                or assignment.assignment_date.month != workspace.month
            ):
                raise ValueError(
                    "assignment.assignment_date "
                    f"{assignment.assignment_date.isoformat()} must stay within "
                    f"workspace month {workspace.year:04d}-{workspace.month:02d}."
                )
            worker_pk = _parse_record_id(
                assignment.worker_id,
                label="assignment.worker_id",
            )
            shift_pk = _parse_record_id(
                assignment.shift_definition_id,
                label="assignment.shift_definition_id",
            )
            station_pk = (
                _parse_record_id(
                    assignment.station_id,
                    label="assignment.station_id",
                )
                if assignment.station_id is not None
                else None
            )
            worker_ids.add(worker_pk)
            shift_ids.add(shift_pk)
            if station_pk is not None:
                station_ids.add(station_pk)
            parsed_assignments.append((assignment, worker_pk, shift_pk, station_pk))

        _assert_record_ids_belong_to_tenant(
            DjangoWorker,
            worker_ids,
            tenant_pk=tenant_pk,
            record_label="assignment.worker_id",
        )
        _assert_record_ids_belong_to_tenant(
            DjangoShiftDefinition,
            shift_ids,
            tenant_pk=tenant_pk,
            record_label="assignment.shift_definition_id",
        )
        _assert_record_ids_belong_to_tenant(
            DjangoStation,
            station_ids,
            tenant_pk=tenant_pk,
            record_label="assignment.station_id",
        )

        for assignment, worker_pk, shift_pk, station_pk in parsed_assignments:
            create_rows.append(
                DjangoMonthlyAssignment(
                    workspace_id=workspace_pk,
                    assignment_date=assignment.assignment_date,
                    worker_id=worker_pk,
                    shift_definition_id=shift_pk,
                    station_id=station_pk,
                    assignment_source="apply",
                    note=assignment.note,
                )
            )

        with transaction.atomic():
            DjangoMonthlyAssignment.objects.filter(workspace_id=workspace_pk).delete()
            if create_rows:
                DjangoMonthlyAssignment.objects.bulk_create(create_rows)

        persisted_rows = DjangoMonthlyAssignment.objects.filter(
            workspace_id=workspace_pk
        ).order_by("assignment_date", "worker_id", "id")
        return [_assignment_from_model(row) for row in persisted_rows]


class DjangoPlanVersionRepository:
    """Persist immutable saved versions without exposing ORM rows upstream."""

    def get_next_version_number(
        self,
        tenant_id: RecordId,
        year: int,
        month: int,
    ) -> int:
        aggregate = DjangoMonthlyPlanVersion.objects.filter(
            tenant_id=_parse_record_id(tenant_id, label="tenant_id"),
            workspace__year=year,
            workspace__month=month,
        ).aggregate(max_version_number=Max("version_number"))
        current_max = aggregate["max_version_number"] or 0
        return current_max + 1

    def save(self, version: MonthlyPlanVersion) -> MonthlyPlanVersion:
        workspace = _require_workspace_model(
            version.workspace_id,
            label="version.workspace_id",
        )
        _assert_workspace_matches_tenant(
            workspace,
            tenant_id=version.tenant_id,
            tenant_label="version.tenant_id",
            workspace_label="version.workspace_id",
        )
        persisted = DjangoMonthlyPlanVersion.objects.create(
            workspace_id=workspace.pk,
            tenant_id=_parse_record_id(version.tenant_id, label="version.tenant_id"),
            version_number=version.version_number,
            label=None,
            summary=version.summary,
            snapshot_json=deepcopy(version.snapshot_json),
        )
        hydrated = DjangoMonthlyPlanVersion.objects.select_related("workspace").get(
            pk=persisted.pk
        )
        return _plan_version_from_model(hydrated)

    def list_for_month(
        self,
        tenant_id: RecordId,
        year: int,
        month: int,
    ) -> list[MonthlyPlanVersion]:
        versions = (
            DjangoMonthlyPlanVersion.objects.filter(
                tenant_id=_parse_record_id(tenant_id, label="tenant_id"),
                workspace__year=year,
                workspace__month=month,
            )
            .select_related("workspace")
            .order_by("version_number", "id")
        )
        return [_plan_version_from_model(version) for version in versions]

    def get_by_id(self, version_id: RecordId) -> MonthlyPlanVersion | None:
        version = (
            DjangoMonthlyPlanVersion.objects.filter(
                pk=_parse_record_id(version_id, label="version_id")
            )
            .select_related("workspace")
            .first()
        )
        if version is None:
            return None
        return _plan_version_from_model(version)


class DjangoMonthlyCandidatePreviewRepository:
    """Persist and reload server-side candidate previews for page actions."""

    def create(
        self,
        *,
        tenant_id: RecordId,
        year: int,
        month: int,
        result_json: JsonObject,
        input_fingerprint: str | None = None,
    ) -> MonthlyCandidatePreview:
        tenant_pk = _parse_record_id(tenant_id, label="tenant_id")
        resolved_input_fingerprint = (
            input_fingerprint
            if input_fingerprint is not None
            else _calculate_monthly_candidate_input_fingerprint(
                tenant_pk=tenant_pk,
                year=year,
                month=month,
            )
        )
        persisted = DjangoMonthlyCandidatePreview.objects.create(
            tenant_id=tenant_pk,
            year=year,
            month=month,
            result_json=deepcopy(result_json),
            input_fingerprint=resolved_input_fingerprint,
        )
        return _candidate_preview_from_model(persisted)

    def get_for_scope(
        self,
        candidate_id: RecordId,
        *,
        tenant_id: RecordId,
        year: int,
        month: int,
    ) -> MonthlyCandidatePreview | None:
        candidate = DjangoMonthlyCandidatePreview.objects.filter(
            pk=_parse_record_id(candidate_id, label="candidate_id"),
            tenant_id=_parse_record_id(tenant_id, label="tenant_id"),
            year=year,
            month=month,
        ).first()
        if candidate is None:
            return None
        return _candidate_preview_from_model(candidate)

    def current_input_fingerprint(
        self,
        *,
        tenant_id: RecordId,
        year: int,
        month: int,
    ) -> str:
        return _calculate_monthly_candidate_input_fingerprint(
            tenant_pk=_parse_record_id(tenant_id, label="tenant_id"),
            year=year,
            month=month,
        )

    def is_fresh(self, candidate: MonthlyCandidatePreview) -> bool:
        if not candidate.input_fingerprint:
            return False
        return candidate.input_fingerprint == self.current_input_fingerprint(
            tenant_id=candidate.tenant_id,
            year=candidate.year,
            month=candidate.month,
        )


class DjangoRefineRequestRepository:
    """Persist bounded refine requests and later enrich them with preview data."""

    def create(self, request: RefineRequest) -> RefineRequest:
        workspace = _require_workspace_model(
            request.workspace_id,
            label="request.workspace_id",
        )
        _assert_workspace_matches_tenant(
            workspace,
            tenant_id=request.tenant_id,
            tenant_label="request.tenant_id",
            workspace_label="request.workspace_id",
        )
        persisted = DjangoRefineRequest.objects.create(
            tenant_id=_parse_record_id(request.tenant_id, label="request.tenant_id"),
            workspace_id=workspace.pk,
            request_text=request.request_text,
            status=request.status,
            parsed_intent_json=(
                deepcopy(request.parsed_intent_json)
                if request.parsed_intent_json is not None
                else None
            ),
            result_preview_json=(
                deepcopy(request.result_preview_json)
                if request.result_preview_json is not None
                else None
            ),
        )
        return _refine_request_from_model(persisted)

    def list_for_workspace(self, workspace_id: RecordId) -> list[RefineRequest]:
        requests = DjangoRefineRequest.objects.filter(
            workspace_id=_parse_record_id(workspace_id, label="workspace_id")
        ).order_by("created_at", "id")
        return [_refine_request_from_model(request) for request in requests]

    def update_parsed_preview(
        self,
        refine_request_id: RecordId,
        *,
        status: str,
        parsed_intent_json: JsonObject | None = None,
        result_preview_json: JsonObject | None = None,
    ) -> RefineRequest | None:
        request = DjangoRefineRequest.objects.filter(
            pk=_parse_record_id(refine_request_id, label="refine_request_id")
        ).first()
        if request is None:
            return None

        request.status = status
        request.parsed_intent_json = (
            deepcopy(parsed_intent_json)
            if parsed_intent_json is not None
            else None
        )
        request.result_preview_json = (
            deepcopy(result_preview_json)
            if result_preview_json is not None
            else None
        )
        request.save(
            update_fields=[
                "status",
                "parsed_intent_json",
                "result_preview_json",
                "updated_at",
            ]
        )
        return _refine_request_from_model(request)


__all__ = [
    "DjangoConstraintConfigRepository",
    "DjangoLeaveRequestRepository",
    "DjangoMonthlyCandidatePreviewRepository",
    "DjangoPlanVersionRepository",
    "DjangoRefineRequestRepository",
    "DjangoShiftRepository",
    "DjangoStationRepository",
    "DjangoTenantRepository",
    "DjangoWorkerRepository",
    "DjangoWorkspaceRepository",
]
