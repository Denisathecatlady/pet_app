from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("", views.source_list, name="source_list"),
    path("<slug:citation_key>/", views.source_detail, name="source_detail"),
]
