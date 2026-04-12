"""Django ORM-backed repository adapters for the first V2 vertical slice.

These adapters are intentionally thin. They keep Django model usage inside the
repository layer and translate explicitly to the framework-neutral dataclasses
consumed by services and the engine boundary.
"""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy

from django.db import transaction
from django.db.models import Max

from app.infra.django_app.models import (
    MonthlyAssignment as DjangoMonthlyAssignment,
    MonthlyPlanVersion as DjangoMonthlyPlanVersion,
    MonthlyWorkspace as DjangoMonthlyWorkspace,
    ShiftDefinition as DjangoShiftDefinition,
    Station as DjangoStation,
    Tenant as DjangoTenant,
    Worker as DjangoWorker,
)
from app.infra.models import (
    MonthlyAssignment,
    MonthlyPlanVersion,
    MonthlyWorkspace,
    RecordId,
    ShiftDefinition,
    Station,
    Tenant,
    Worker,
    WorkerStationSkill,
)
from app.infra.repositories import CurrentWorkspaceState


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


def _derive_workspace_source_type(workspace: MonthlyWorkspace) -> str:
    """Infer the persisted workspace origin from the neutral workspace record."""

    if workspace.source_version_id is not None:
        return "restore"
    return "preview"


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
        del tenant_id
        return []


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
        persisted, _created = DjangoMonthlyWorkspace.objects.update_or_create(
            tenant_id=_parse_record_id(workspace.tenant_id, label="workspace.tenant_id"),
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
        workspace_pk = _parse_record_id(workspace_id, label="workspace_id")
        create_rows: list[DjangoMonthlyAssignment] = []
        for assignment in assignments:
            if assignment.workspace_id != workspace_id:
                raise ValueError(
                    "All replacement assignments must belong to the target workspace."
                )
            create_rows.append(
                DjangoMonthlyAssignment(
                    workspace_id=workspace_pk,
                    assignment_date=assignment.assignment_date,
                    worker_id=_parse_record_id(
                        assignment.worker_id,
                        label="assignment.worker_id",
                    ),
                    shift_definition_id=_parse_record_id(
                        assignment.shift_definition_id,
                        label="assignment.shift_definition_id",
                    ),
                    station_id=(
                        _parse_record_id(
                            assignment.station_id,
                            label="assignment.station_id",
                        )
                        if assignment.station_id is not None
                        else None
                    ),
                    assignment_source="apply",
                    note=None,
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
        persisted = DjangoMonthlyPlanVersion.objects.create(
            workspace_id=_parse_record_id(
                version.workspace_id,
                label="version.workspace_id",
            ),
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


__all__ = [
    "DjangoPlanVersionRepository",
    "DjangoShiftRepository",
    "DjangoStationRepository",
    "DjangoTenantRepository",
    "DjangoWorkerRepository",
    "DjangoWorkspaceRepository",
]
