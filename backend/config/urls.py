"""Root URL configuration."""

from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "BARF Nutri – administrace"
admin.site.site_title = "BARF Nutri – administrace"
admin.site.index_title = "Správa aplikace"

urlpatterns = [
    path("", include("core.urls")),
    path("ucet/", include("accounts.urls")),
    path("zvirata/", include("animals.urls")),
    path("zdroje/", include("catalog.urls")),
    path("admin/", admin.site.urls),
]
