"""Django URL registration helpers for the V2 scheduler runtime.

The framework-neutral route bundle remains reusable, but Django is now the
primary runtime path for V2. URL mapping stays thin and delegates request
translation to the dedicated Django view adapter.
"""

from __future__ import annotations

from django.urls import URLPattern, path

from app.api.django_views import build_django_route_view
from app.api.routes import MonthlyScheduleRoutes


def build_monthly_schedule_urlpatterns(
    routes: MonthlyScheduleRoutes,
) -> list[URLPattern]:
    """Build Django URL patterns from the monthly schedule route bundle."""

    return [
        path(
            _normalize_django_path(route.path),
            build_django_route_view(route),
            name=route.name,
        )
        for route in routes.route_definitions()
    ]


def _normalize_django_path(route_path: str) -> str:
    """Convert absolute-style route metadata into Django `path` syntax."""

    return route_path.lstrip("/")


__all__ = ["build_monthly_schedule_urlpatterns"]
