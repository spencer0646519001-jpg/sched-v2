"""Minimal URLConf for manually reviewing the server-rendered monthly workspace."""

from __future__ import annotations

from django.conf import settings
from django.urls import path

from app.api.django_runtime import build_django_monthly_workspace_page_urlpatterns

urlpatterns = [
    *build_django_monthly_workspace_page_urlpatterns(),
]

if getattr(settings, "ENABLE_DJANGO_ADMIN", False):
    from django.contrib import admin

    urlpatterns.append(path("admin/", admin.site.urls))
