from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.db import IntegrityError, connection, transaction

from app.infra.django_app.models import (
    MonthlyAssignment,
    MonthlyPlanVersion,
    MonthlyWorkspace,
    ShiftDefinition,
    Station,
    Tenant,
    Worker,
)


@pytest.fixture(autouse=True)
def _clear_scheduler_tables() -> None:
    MonthlyAssignment.objects.all().delete()
    MonthlyPlanVersion.objects.all().delete()
    MonthlyWorkspace.objects.all().delete()
    ShiftDefinition.objects.all().delete()
    Station.objects.all().delete()
    Worker.objects.all().delete()
    Tenant.objects.all().delete()


def test_initial_migration_creates_expected_tables() -> None:
    table_names = set(connection.introspection.table_names())

    assert {
        "scheduler_infra_tenant",
        "scheduler_infra_worker",
        "scheduler_infra_station",
        "scheduler_infra_shiftdefinition",
        "scheduler_infra_monthlyworkspace",
        "scheduler_infra_monthlyassignment",
        "scheduler_infra_monthlyplanversion",
    }.issubset(table_names)


def test_monthly_persistence_models_support_apply_and_save_shape() -> None:
    tenant = Tenant.objects.create(
        slug="tenant-a",
        name="Tenant A",
        default_locale="en-US",
    )
    worker = Worker.objects.create(
        tenant=tenant,
        code="W1",
        name="Alex",
        role="cook",
        is_active=True,
    )
    station = Station.objects.create(
        tenant=tenant,
        code="GRILL",
        name="Grill",
        is_active=True,
    )
    shift = ShiftDefinition.objects.create(
        tenant=tenant,
        code="DAY",
        name="Day",
        paid_hours=Decimal("8.00"),
        is_off_shift=False,
    )
    workspace = MonthlyWorkspace.objects.create(
        tenant=tenant,
        year=2026,
        month=4,
        status="draft",
        source_type="preview",
    )
    assignment = MonthlyAssignment.objects.create(
        workspace=workspace,
        assignment_date=dt.date(2026, 4, 1),
        worker=worker,
        shift_definition=shift,
        station=station,
        assignment_source="apply",
        note="Initial preview apply",
    )
    plan_version = MonthlyPlanVersion.objects.create(
        workspace=workspace,
        tenant=tenant,
        version_number=1,
        label="Baseline",
        summary="Initial saved plan",
        snapshot_json={
            "workspace_id": workspace.id,
            "assignment_ids": [assignment.id],
        },
    )

    workspace.source_version = plan_version
    workspace.save()
    workspace.refresh_from_db()

    assert workspace.source_version_id == plan_version.id
    assert workspace.assignments.get().id == assignment.id
    assert workspace.plan_versions.get().id == plan_version.id


def test_unique_constraints_are_enforced_for_core_slice() -> None:
    tenant = Tenant.objects.create(
        slug="tenant-a",
        name="Tenant A",
        default_locale="en-US",
    )
    other_tenant = Tenant.objects.create(
        slug="tenant-b",
        name="Tenant B",
        default_locale="en-US",
    )

    Worker.objects.create(
        tenant=tenant,
        code="W1",
        name="Alex",
        role="cook",
        is_active=True,
    )
    Worker.objects.create(
        tenant=other_tenant,
        code="W1",
        name="Jordan",
        role="cook",
        is_active=True,
    )
    Station.objects.create(
        tenant=tenant,
        code="GRILL",
        name="Grill",
        is_active=True,
    )
    ShiftDefinition.objects.create(
        tenant=tenant,
        code="DAY",
        name="Day",
        paid_hours=Decimal("8.00"),
        is_off_shift=False,
    )
    workspace = MonthlyWorkspace.objects.create(
        tenant=tenant,
        year=2026,
        month=4,
        status="draft",
        source_type="preview",
    )
    second_workspace = MonthlyWorkspace.objects.create(
        tenant=tenant,
        year=2026,
        month=5,
        status="draft",
        source_type="preview",
    )
    worker = Worker.objects.get(tenant=tenant, code="W1")
    station = Station.objects.get(tenant=tenant, code="GRILL")
    shift = ShiftDefinition.objects.get(tenant=tenant, code="DAY")

    MonthlyAssignment.objects.create(
        workspace=workspace,
        assignment_date=dt.date(2026, 4, 1),
        worker=worker,
        shift_definition=shift,
        station=station,
        assignment_source="apply",
    )
    MonthlyPlanVersion.objects.create(
        workspace=workspace,
        tenant=tenant,
        version_number=1,
        snapshot_json={"workspace_id": workspace.id},
    )
    MonthlyPlanVersion.objects.create(
        workspace=second_workspace,
        tenant=tenant,
        version_number=1,
        snapshot_json={"workspace_id": second_workspace.id},
    )

    _assert_integrity_error(
        lambda: Tenant.objects.create(
            slug="tenant-a",
            name="Tenant A Duplicate",
            default_locale="en-US",
        )
    )
    _assert_integrity_error(
        lambda: Worker.objects.create(
            tenant=tenant,
            code="W1",
            name="Duplicate Worker",
            role="cook",
            is_active=True,
        )
    )
    _assert_integrity_error(
        lambda: Station.objects.create(
            tenant=tenant,
            code="GRILL",
            name="Duplicate Station",
            is_active=True,
        )
    )
    _assert_integrity_error(
        lambda: ShiftDefinition.objects.create(
            tenant=tenant,
            code="DAY",
            name="Duplicate Shift",
            paid_hours=Decimal("8.00"),
            is_off_shift=False,
        )
    )
    _assert_integrity_error(
        lambda: MonthlyWorkspace.objects.create(
            tenant=tenant,
            year=2026,
            month=4,
            status="draft",
            source_type="preview",
        )
    )
    _assert_integrity_error(
        lambda: MonthlyAssignment.objects.create(
            workspace=workspace,
            assignment_date=dt.date(2026, 4, 1),
            worker=worker,
            shift_definition=shift,
            station=station,
            assignment_source="apply",
        )
    )
    _assert_integrity_error(
        lambda: MonthlyPlanVersion.objects.create(
            workspace=workspace,
            tenant=tenant,
            version_number=1,
            snapshot_json={"workspace_id": workspace.id},
        )
    )


def test_check_constraints_guard_basic_numeric_invariants() -> None:
    tenant = Tenant.objects.create(
        slug="tenant-a",
        name="Tenant A",
        default_locale="en-US",
    )
    workspace = MonthlyWorkspace.objects.create(
        tenant=tenant,
        year=2026,
        month=4,
        status="draft",
        source_type="preview",
    )

    _assert_integrity_error(
        lambda: ShiftDefinition.objects.create(
            tenant=tenant,
            code="NEG",
            name="Negative Hours",
            paid_hours=Decimal("-1.00"),
            is_off_shift=False,
        )
    )
    _assert_integrity_error(
        lambda: MonthlyWorkspace.objects.create(
            tenant=tenant,
            year=2026,
            month=13,
            status="draft",
            source_type="preview",
        )
    )
    _assert_integrity_error(
        lambda: MonthlyPlanVersion.objects.create(
            workspace=workspace,
            tenant=tenant,
            version_number=0,
            snapshot_json={"workspace_id": workspace.id},
        )
    )


def _assert_integrity_error(operation) -> None:
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            operation()
