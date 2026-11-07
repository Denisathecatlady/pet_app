"""Root URL configuration.

The administration lives at ``settings.ADMIN_URL`` (``admin/`` in development and tests,
a hard to guess path in production, docs/14 §14.4). Its titles are set by
``backoffice.admin_site.BarfAdminSite``.
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("", include("core.urls")),
    path("ucet/", include("accounts.urls")),
    path("zvirata/", include("animals.urls")),
    path("zdroje/", include("catalog.urls")),
    path(settings.ADMIN_URL, admin.site.urls),
]
