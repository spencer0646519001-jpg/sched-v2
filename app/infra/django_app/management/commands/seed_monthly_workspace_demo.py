"""Seed a small local dataset for manually reviewing the monthly workspace."""

from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand

from app.infra.django_app.models import (
    ConstraintConfig,
    ShiftDefinition,
    Station,
    Tenant,
    Worker,
)


class Command(BaseCommand):
    help = "Seed a tiny demo tenant and staffing data for the monthly workspace page."

    def handle(self, *args: object, **options: object) -> None:
        tenant, _created = Tenant.objects.update_or_create(
            slug="demo-restaurant",
            defaults={
                "name": "Demo Restaurant",
                "default_locale": "en-US",
            },
        )

        worker_rows = (
            {
                "code": "W1",
                "name": "Alex",
                "role": "cook",
                "is_active": True,
            },
            {
                "code": "W2",
                "name": "Blair",
                "role": "cook",
                "is_active": True,
            },
            {
                "code": "CHEF1",
                "name": "Casey",
                "role": "chef",
                "is_active": True,
            },
        )
        for worker_row in worker_rows:
            Worker.objects.update_or_create(
                tenant=tenant,
                code=worker_row["code"],
                defaults={
                    "name": worker_row["name"],
                    "role": worker_row["role"],
                    "is_active": worker_row["is_active"],
                },
            )

        Station.objects.update_or_create(
            tenant=tenant,
            code="GRILL",
            defaults={
                "name": "Grill",
                "is_active": True,
            },
        )
        ShiftDefinition.objects.update_or_create(
            tenant=tenant,
            code="DAY",
            defaults={
                "name": "Day",
                "paid_hours": Decimal("8.00"),
                "is_off_shift": False,
            },
        )
        ConstraintConfig.objects.update_or_create(
            tenant=tenant,
            scope_type="default",
            defaults={
                "year": None,
                "month": None,
                "config_json": {
                    "stations": {"GRILL": 1},
                    "min_staff_weekday": 1,
                    "min_staff_weekend": 1,
                    "max_staff_per_day": 1,
                    "min_rest_days_per_month": 0,
                    "max_consecutive_days": 31,
                },
            },
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Seeded demo monthly workspace data.\n"
                "Open: http://127.0.0.1:8000/v2/monthly-workspace"
                "?tenant_slug=demo-restaurant&month_scope=2026-04"
            )
        )
