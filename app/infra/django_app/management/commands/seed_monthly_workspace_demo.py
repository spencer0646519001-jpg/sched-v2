"""Seed the mirrored v1 demo world for the local monthly workspace."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from app.monthly_workspace_demo_data import (
    DEMO_CONSTRAINT_CONFIG,
    DEMO_DEFAULT_LOCALE,
    DEMO_MONTH_SCOPE,
    DEMO_SHIFTS,
    DEMO_STATIONS,
    DEMO_TENANT_NAME,
    DEMO_TENANT_SLUG,
    DEMO_WORKERS,
)
from app.infra.django_app.models import (
    ConstraintConfig,
    ShiftDefinition,
    Station,
    Tenant,
    Worker,
    WorkerStationSkill,
)


class Command(BaseCommand):
    help = "Seed the mirrored demo_kitchen staffing data for the monthly workspace page."

    def handle(self, *args: object, **options: object) -> None:
        tenant, _created = Tenant.objects.update_or_create(
            slug=DEMO_TENANT_SLUG,
            defaults={
                "name": DEMO_TENANT_NAME,
                "default_locale": DEMO_DEFAULT_LOCALE,
            },
        )

        for worker_row in DEMO_WORKERS:
            Worker.objects.update_or_create(
                tenant=tenant,
                code=worker_row.code,
                defaults={
                    "name": worker_row.name,
                    "role": worker_row.role,
                    "is_active": worker_row.is_active,
                },
            )

        for station_row in DEMO_STATIONS:
            Station.objects.update_or_create(
                tenant=tenant,
                code=station_row.code,
                defaults={
                    "name": station_row.name,
                    "is_active": station_row.is_active,
                },
            )
        for shift_row in DEMO_SHIFTS:
            ShiftDefinition.objects.update_or_create(
                tenant=tenant,
                code=shift_row.code,
                defaults={
                    "name": shift_row.name,
                    "paid_hours": shift_row.paid_hours,
                    "is_off_shift": shift_row.is_off_shift,
                    "start_time": shift_row.start_time,
                    "end_time": shift_row.end_time,
                },
            )

        workers_by_code = {
            worker.code: worker
            for worker in Worker.objects.filter(tenant=tenant)
        }
        stations_by_code = {
            station.code: station
            for station in Station.objects.filter(tenant=tenant)
        }
        desired_skill_pairs: set[tuple[int, int]] = set()
        for worker_row in DEMO_WORKERS:
            worker = workers_by_code[worker_row.code]
            for station_code in worker_row.station_skills:
                station = stations_by_code[station_code]
                desired_skill_pairs.add((worker.id, station.id))
                WorkerStationSkill.objects.get_or_create(
                    tenant=tenant,
                    worker=worker,
                    station=station,
                )

        for persisted_skill in WorkerStationSkill.objects.filter(tenant=tenant):
            pair = (persisted_skill.worker_id, persisted_skill.station_id)
            if pair not in desired_skill_pairs:
                persisted_skill.delete()

        ConstraintConfig.objects.update_or_create(
            tenant=tenant,
            scope_type="default",
            defaults={
                "year": None,
                "month": None,
                "config_json": DEMO_CONSTRAINT_CONFIG,
            },
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Seeded demo monthly workspace data.\n"
                "Open: http://127.0.0.1:8000/v2/monthly-workspace"
                f"?tenant_slug={DEMO_TENANT_SLUG}&month_scope={DEMO_MONTH_SCOPE}"
            )
        )
