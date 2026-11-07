"""Admin of the animals app. Every model keeps its history (SimpleHistoryAdmin).

The models with personal data (animals, measurements, conditions of animals, shares) record
every access in the access log of the administration (``AccessLoggedAdminMixin``, docs/14 §14.7).
The codebook ``HealthCondition`` holds no personal data.
"""

from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from backoffice.access_log import AccessLoggedAdminMixin

from .models import (
    Animal,
    AnimalHealthCondition,
    AnimalShare,
    BodyMeasurement,
    HealthCondition,
)


@admin.register(Animal)
class AnimalAdmin(AccessLoggedAdminMixin, SimpleHistoryAdmin):
    """Animals. Only a vet with a share confirms a target weight (docs/05 §5.3), so the
    confirmation is read-only here; changing the target weight, species or state in the
    admin cancels it (``Animal.clean``)."""

    list_display = ("name", "species", "owner", "physiological_state", "target_weight_status")
    list_filter = ("species", "physiological_state", "target_weight_status")
    search_fields = ("name", "owner__email", "uuid")
    raw_id_fields = ("owner",)
    readonly_fields = (
        "uuid",
        "target_weight_status",
        "target_weight_confirmed_by",
        "target_weight_confirmed_at",
        "created_at",
        "updated_at",
    )


@admin.register(BodyMeasurement)
class BodyMeasurementAdmin(AccessLoggedAdminMixin, SimpleHistoryAdmin):
    list_display = ("animal", "measured_on", "weight_kg", "bcs", "mcs", "assessed_by")
    list_filter = ("assessed_by", "mcs")
    search_fields = ("animal__name", "animal__owner__email")
    raw_id_fields = ("animal", "created_by")
    readonly_fields = ("uuid", "created_at")
    date_hierarchy = "measured_on"


@admin.register(HealthCondition)
class HealthConditionAdmin(SimpleHistoryAdmin):
    list_display = ("code", "name_cs", "mode")
    list_filter = ("mode",)
    search_fields = ("code", "name_cs")


@admin.register(AnimalHealthCondition)
class AnimalHealthConditionAdmin(AccessLoggedAdminMixin, SimpleHistoryAdmin):
    list_display = ("animal", "condition", "diagnosed_by_vet", "since")
    list_filter = ("condition", "diagnosed_by_vet")
    search_fields = ("animal__name", "animal__owner__email")
    raw_id_fields = ("animal",)


@admin.register(AnimalShare)
class AnimalShareAdmin(AccessLoggedAdminMixin, SimpleHistoryAdmin):
    list_display = ("animal", "vet", "granted_by", "created_at", "revoked_at")
    list_filter = ("revoked_at",)
    search_fields = ("animal__name", "vet__email", "granted_by__email")
    raw_id_fields = ("animal", "vet", "granted_by")
    readonly_fields = ("uuid", "created_at")
