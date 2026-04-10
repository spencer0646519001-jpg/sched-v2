from __future__ import annotations

import datetime as dt
import json

from django.conf import settings

if not settings.configured:
    settings.configure(
        ALLOWED_HOSTS=["testserver"],
        DEFAULT_CHARSET="utf-8",
        SECRET_KEY="test-secret-key",
        USE_TZ=True,
    )

from django.test import RequestFactory

from app.api.django_urls import build_monthly_schedule_urlpatterns
from app.api.django_views import build_django_route_view
from app.api.routes import RouteDefinition
from app.api.schemas import (
    MonthPlanningMetadataSchema,
    MonthPlanningResultSchema,
    MonthPlanningSummarySchema,
    PreviewMonthScheduleRequestSchema,
    PreviewMonthScheduleResponseSchema,
)


def test_build_django_route_view_serializes_schema_response() -> None:
    route = RouteDefinition(
        name="preview_month_schedule",
        method="POST",
        path="/v2/monthly-schedules/preview",
        request_schema=PreviewMonthScheduleRequestSchema,
        response_schema=PreviewMonthScheduleResponseSchema,
        handler=_preview_handler,
    )
    request = RequestFactory().post(
        route.path,
        data=json.dumps(
            {
                "tenant_slug": "tenant-a",
                "year": 2026,
                "month": 4,
            }
        ),
        content_type="application/json",
    )

    response = build_django_route_view(route)(request)

    payload = json.loads(response.content)
    assert response.status_code == 200
    assert payload["request"]["tenant_slug"] == "tenant-a"
    assert payload["result"]["summary"]["total_assignments"] == 0
    assert payload["result"]["metadata"]["source_type"] == "preview"


def test_build_django_route_view_returns_validation_errors() -> None:
    route = RouteDefinition(
        name="preview_month_schedule",
        method="POST",
        path="/v2/monthly-schedules/preview",
        request_schema=PreviewMonthScheduleRequestSchema,
        response_schema=PreviewMonthScheduleResponseSchema,
        handler=_preview_handler,
    )
    request = RequestFactory().post(
        route.path,
        data=json.dumps(
            {
                "tenant_slug": "   ",
                "year": 2026,
                "month": 4,
            }
        ),
        content_type="application/json",
    )

    response = build_django_route_view(route)(request)

    payload = json.loads(response.content)
    assert response.status_code == 400
    assert payload["detail"] == "Request validation failed."


def test_build_monthly_schedule_urlpatterns_uses_route_metadata() -> None:
    route = RouteDefinition(
        name="preview_month_schedule",
        method="POST",
        path="/v2/monthly-schedules/preview",
        request_schema=PreviewMonthScheduleRequestSchema,
        response_schema=PreviewMonthScheduleResponseSchema,
        handler=_preview_handler,
    )

    patterns = build_monthly_schedule_urlpatterns(_FakeRoutes(route))

    assert len(patterns) == 1
    assert patterns[0].name == "preview_month_schedule"
    assert str(patterns[0].pattern) == "v2/monthly-schedules/preview"


def _preview_handler(
    request: PreviewMonthScheduleRequestSchema,
) -> PreviewMonthScheduleResponseSchema:
    return PreviewMonthScheduleResponseSchema(
        request=request,
        result=MonthPlanningResultSchema(
            assignments=[],
            warnings=[],
            summary=MonthPlanningSummarySchema(
                total_assignments=0,
                total_warnings=0,
                assignments_by_worker={},
                paid_hours_by_worker={},
                warnings_by_type={},
            ),
            metadata=MonthPlanningMetadataSchema(
                generated_at=dt.datetime(2026, 4, 11, 0, 0, tzinfo=dt.timezone.utc),
                source_type="preview",
                refinement_applied=False,
                notes=["django-adapter-test"],
            ),
        ),
    )


class _FakeRoutes:
    def __init__(self, route: RouteDefinition) -> None:
        self._route = route

    def route_definitions(self) -> tuple[RouteDefinition, ...]:
        return (self._route,)
