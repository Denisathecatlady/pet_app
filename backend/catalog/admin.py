"""Admin of the catalog app. ``ScientificSource`` keeps its history (SimpleHistoryAdmin)."""

from typing import Any

from django import forms
from django.contrib import admin
from django.http import HttpRequest
from simple_history.admin import SimpleHistoryAdmin

from .models import MARKERS, LifeStage, ScientificSource, VerificationLevel

# Changing any of these means somebody checked the source: the admin then records who.
VERIFICATION_FIELDS = frozenset(
    {"verification_level", "verification_markers", "verification_note", "last_verified_at"}
)


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

    # Declared here so that the form field states how an address without a scheme is read.
    url = forms.URLField(label="odkaz", max_length=500, required=False, assume_scheme="https")

    class Meta:
        model = ScientificSource
        # verified_by is not a form field (see ScientificSourceAdmin.save_model).
        exclude = ("verified_by",)
        labels = {
            "evidence_level": "úroveň odbornosti zdroje",
            "verification_note": "poznámka k ověření z registru",
        }

    def clean(self) -> dict:
        """The date of the verification goes with a verified status, none with ``NONE``.

        The database constraint also names ``verified_by``, which is not a form field, so the
        form does not validate it; this check keeps the message in the form instead of an
        error page.
        """
        cleaned = super().clean()
        level = cleaned.get("verification_level")
        verified_on = cleaned.get("last_verified_at")
        if level == VerificationLevel.NONE and verified_on is not None:
            self.add_error("last_verified_at", "Neověřený zdroj nemá datum ani osobu ověření.")
        elif level and level != VerificationLevel.NONE and verified_on is None:
            self.add_error("last_verified_at", "U ověřeného zdroje zadejte datum ověření.")
        return cleaned

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
    a lasting change belongs to docs/zdroje.md and the JSON file
    (docs/13-zdroje-v-aplikaci.md §13.5)."""

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
    # No raw-id or select widget for verified_by: it would show the e-mail address of any
    # account, whatever the staff member may see in the user admin (data minimisation,
    # docs/13-zdroje-v-aplikaci.md §13.3). The admin sets the field itself.
    readonly_fields = ("verified_by_info", "created_at", "updated_at")
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
                    "verified_by_info",
                )
            },
        ),
        ("Obsah a omezení", {"fields": ("key_findings", "limitations")}),
        ("Záznam", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="ověřil")
    def verified_by_info(self, obj: ScientificSource | None) -> str:
        """Whether a person is recorded, never who (the account is not shown here)."""
        if obj is not None and obj.verified_by_id is not None:
            return "zaznamenán kurátor (jméno se tady nezobrazuje)"
        return "nezaznamenán"

    def save_model(self, request: HttpRequest, obj: ScientificSource, form: Any, change: bool):
        """Record the signed-in staff member as the verifier when the verification changed.

        A source without a verified status has no verifier (a database constraint).
        """
        if obj.verification_level == VerificationLevel.NONE:
            obj.verified_by = None
        elif not change or VERIFICATION_FIELDS & set(form.changed_data):
            obj.verified_by = request.user
        super().save_model(request, obj, form, change)

    @admin.display(description="název")
    def short_title(self, obj: ScientificSource) -> str:
        title = " ".join(obj.title.split())
        return title if len(title) <= 80 else f"{title[:79]}…"
