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
