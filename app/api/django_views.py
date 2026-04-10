"""Django-first HTTP adapter helpers for the V2 scheduler.

Django is the primary runtime entry path for V2. These helpers keep views thin
by translating Django requests into API schemas, delegating to the existing
framework-neutral route handlers, and serializing API schemas back to JSON.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods
from pydantic import ValidationError

from app.api.routes import RouteDefinition

DjangoView = Callable[[HttpRequest], HttpResponse]


def build_django_route_view(route: RouteDefinition) -> DjangoView:
    """Build one thin Django view around a framework-neutral route definition."""

    @require_http_methods([route.method])
    def view(request: HttpRequest) -> HttpResponse:
        try:
            api_request = route.request_schema.model_validate(
                _decode_json_object(request)
            )
            api_response = route.response_schema.model_validate(
                route.handler(api_request)
            )
        except json.JSONDecodeError:
            return _json_error("Request body must be valid JSON.", status=400)
        except ValidationError as exc:
            return JsonResponse(
                {
                    "detail": "Request validation failed.",
                    "errors": json.loads(exc.json()),
                },
                status=400,
            )
        except LookupError as exc:
            return _json_error(str(exc), status=404)
        except ValueError as exc:
            return _json_error(str(exc), status=400)

        return JsonResponse(api_response.model_dump(mode="json"), status=200)

    view.__name__ = route.name
    view.__doc__ = (
        f"Django adapter view for the V2 '{route.name}' monthly scheduling route."
    )
    return view


def _decode_json_object(request: HttpRequest) -> dict[str, Any]:
    """Parse one JSON object body from a Django request."""

    if not request.body:
        return {}

    payload = json.loads(request.body)
    if not isinstance(payload, dict):
        raise ValueError("Request body must decode to a JSON object.")
    return payload


def _json_error(detail: str, *, status: int) -> JsonResponse:
    """Return a small JSON error response for transport-layer failures."""

    return JsonResponse({"detail": detail}, status=status)


__all__ = ["DjangoView", "build_django_route_view"]
