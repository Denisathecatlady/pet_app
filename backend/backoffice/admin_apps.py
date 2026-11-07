"""The app configuration that replaces ``django.contrib.admin`` (documented Django way).

``INSTALLED_APPS`` lists ``backoffice.admin_apps.BarfAdminConfig`` instead of
``django.contrib.admin``. It is the same app (same label ``admin``) whose default site is
:class:`backoffice.admin_site.BarfAdminSite`, so ``admin.site`` and every ``@admin.register``
use it. This module is kept apart from ``backoffice/apps.py`` because importing ``AdminConfig``
there would make Django's detection of the app configuration of ``backoffice`` ambiguous.
"""

from django.contrib.admin.apps import AdminConfig


class BarfAdminConfig(AdminConfig):
    default_site = "backoffice.admin_site.BarfAdminSite"

    def ready(self) -> None:
        super().ready()  # autodiscovers the admin modules of every app
        from . import third_party_admin

        third_party_admin.adapt_registered_admins()
