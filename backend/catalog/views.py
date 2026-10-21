"""Public views of the library of sources, mounted under ``/zdroje/``.

No sign-in is needed: the library is about evidence, not about people, and transparency
about how well a source was checked helps every visitor. The views are read-only (GET).
"""

from dataclasses import dataclass

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from . import services
from .display import EVIDENCE_NAMES, VERIFICATION_STYLES
from .models import EvidenceLevel, ScientificSource, SourceType, SpeciesScope, VerificationLevel


@dataclass(frozen=True)
class FilterField:
    """A drop-down of the filter form: parameter name, label, options and the chosen value."""

    name: str
    label: str
    options: list[tuple[str, str]]
    value: str


def _filter_fields(query: services.SourceQuery) -> list[FilterField]:
    return [
        FilterField(
            services.PARAM_EVIDENCE,
            "Úroveň důkazů",
            [(level.value, f"{level.value} – {EVIDENCE_NAMES[level.value]}") for level in EvidenceLevel],
            query.evidence,
        ),
        FilterField(
            services.PARAM_SPECIES,
            "Druh zvířat",
            [(scope.value, scope.label) for scope in SpeciesScope],
            query.species,
        ),
        FilterField(
            services.PARAM_TYPE,
            "Typ zdroje",
            [(kind.value, kind.label) for kind in SourceType],
            query.source_type,
        ),
        FilterField(
            services.PARAM_VERIFICATION,
            "Stav ověření",
            [(level.value, VERIFICATION_STYLES[level.value].name) for level in VerificationLevel],
            query.verification,
        ),
    ]


@require_GET
def source_list(request: HttpRequest) -> HttpResponse:
    """List of sources with filters, text search and pagination (25 per page).

    Query parameters (all optional, invalid values are ignored): ``q`` (text in the key,
    title or authors), ``uroven`` (L1–L6), ``druh`` (DOG, CAT, BOTH, NOT_APPLICABLE),
    ``typ`` (source type code), ``overeni`` (B, A, P, S, NONE) and ``strana``.
    """
    result = services.search_sources(services.parse_query(request.GET))
    query, page = result.query, result.page
    context = {
        "query": query,
        "page": page,
        "sources": page.object_list,
        "matched": result.matched,
        "total": result.total,
        "filter_fields": _filter_fields(query),
        "previous_query": query.query_string(page.number - 1) if page.has_previous() else None,
        "next_query": query.query_string(page.number + 1) if page.has_next() else None,
    }
    return render(request, "catalog/source_list.html", context)


@require_GET
def source_detail(request: HttpRequest, citation_key: str) -> HttpResponse:
    """All fields of one source with the legend; 404 for an unknown citation key."""
    source = get_object_or_404(ScientificSource, citation_key=citation_key)
    return render(request, "catalog/source_detail.html", {"source": source})
