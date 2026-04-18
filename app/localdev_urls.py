"""Minimal URLConf for manually reviewing the server-rendered monthly workspace."""

from __future__ import annotations

from app.api.django_runtime import build_django_monthly_workspace_page_urlpatterns

urlpatterns = [
    *build_django_monthly_workspace_page_urlpatterns(),
]
