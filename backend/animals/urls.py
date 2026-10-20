from django.urls import path

from . import views

app_name = "animals"

urlpatterns = [
    path("nove/", views.animal_create, name="create"),
    path("<uuid:animal_uuid>/", views.animal_detail, name="detail"),
    path("<uuid:animal_uuid>/upravit/", views.animal_edit, name="edit"),
    path("<uuid:animal_uuid>/smazat/", views.animal_delete, name="delete"),
    path("<uuid:animal_uuid>/mereni/nove/", views.measurement_add, name="measurement_add"),
    path(
        "<uuid:animal_uuid>/mereni/<uuid:measurement_uuid>/smazat/",
        views.measurement_delete,
        name="measurement_delete",
    ),
    path("<uuid:animal_uuid>/zdravotni-stavy/novy/", views.condition_add, name="condition_add"),
    path(
        "<uuid:animal_uuid>/zdravotni-stavy/<slug:code>/upravit/",
        views.condition_edit,
        name="condition_edit",
    ),
    path(
        "<uuid:animal_uuid>/zdravotni-stavy/<slug:code>/odebrat/",
        views.condition_remove,
        name="condition_remove",
    ),
    path("<uuid:animal_uuid>/sdileni/nove/", views.share_add, name="share_add"),
    path(
        "<uuid:animal_uuid>/sdileni/<uuid:share_uuid>/zrusit/",
        views.share_revoke,
        name="share_revoke",
    ),
    path(
        "<uuid:animal_uuid>/cilova-hmotnost/potvrdit/",
        views.target_weight_confirm,
        name="target_weight_confirm",
    ),
]
