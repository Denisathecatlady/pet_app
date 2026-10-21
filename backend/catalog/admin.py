"""Admin of the catalog app. ``ScientificSource`` keeps its history (SimpleHistoryAdmin)."""

from django import forms
from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import MARKERS, LifeStage, ScientificSource


class ScientificSourceForm(forms.ModelForm):
    """Check boxes for the two JSON lists, so nobody has to type JSON."""

    life_stages = forms.MultipleChoiceField(
        label="životní fáze",
        choices=LifeStage.choices,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text=ScientificSource._meta.get_field("life_stages").help_text,
    )
    verification_markers = forms.MultipleChoiceField(
        label="značky ověření",
        choices=[(marker.value, f"{marker.value}: {marker.label}") for marker in MARKERS],
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text=ScientificSource._meta.get_field("verification_markers").help_text,
    )

    class Meta:
        model = ScientificSource
        fields = "__all__"

    def clean_life_stages(self) -> list[str]:
        chosen = set(self.cleaned_data["life_stages"])
        return [stage for stage in LifeStage.values if stage in chosen]

    def clean_verification_markers(self) -> list[str]:
        chosen = set(self.cleaned_data["verification_markers"])
        return [marker.value for marker in MARKERS if marker.value in chosen]


@admin.register(ScientificSource)
class ScientificSourceAdmin(SimpleHistoryAdmin):
    """Library of sources. Changes made here are overwritten by the next
    ``manage.py load_sources`` for every field present in ``catalog/data/sources.json``;
    a lasting change belongs to docs/zdroje.md and the JSON file (docs/13 §13.5)."""

    form = ScientificSourceForm
    list_display = (
        "citation_key",
        "short_title",
        "year",
        "evidence_level",
        "source_type",
        "species_scope",
        "verification_level",
        "last_verified_at",
    )
    list_filter = ("evidence_level", "source_type", "species_scope", "verification_level")
    search_fields = ("citation_key", "title", "authors_or_org", "doi")
    raw_id_fields = ("verified_by",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("citation_key", "title", "authors_or_org", "year")}),
        ("Vydání a odkazy", {"fields": ("publication_details", "edition_version", "doi", "url")}),
        (
            "Povaha zdroje",
            {
                "fields": (
                    "source_type",
                    "type_note",
                    "evidence_level",
                    "species_scope",
                    "life_stages",
                    "units_and_conditions",
                )
            },
        ),
        (
            "Ověření",
            {
                "fields": (
                    "verification_level",
                    "verification_markers",
                    "verification_note",
                    "last_verified_at",
                    "verified_by",
                )
            },
        ),
        ("Obsah a omezení", {"fields": ("key_findings", "limitations")}),
        ("Záznam", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="název")
    def short_title(self, obj: ScientificSource) -> str:
        title = " ".join(obj.title.split())
        return title if len(title) <= 80 else f"{title[:79]}…"
