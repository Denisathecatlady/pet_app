"""Searching the public library of sources: query parameters → one page of sources.

Every query parameter is whitelisted: a value that is not allowed is ignored (as if the
parameter were missing), never an error, so a stale or hand-edited link still shows the
library.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Final

from django.core.paginator import Page, Paginator
from django.db.models import Q, QuerySet
from django.utils.http import urlencode

from .models import EvidenceLevel, ScientificSource, SourceType, SpeciesScope, VerificationLevel

PAGE_SIZE: Final = 25
MAX_TEXT_LENGTH: Final = 100
MAX_TERMS: Final = 5
MAX_PAGE_DIGITS: Final = 6

# Names of the query parameters (the URLs of the application are Czech).
PARAM_TEXT: Final = "q"
PARAM_EVIDENCE: Final = "uroven"
PARAM_SPECIES: Final = "druh"
PARAM_TYPE: Final = "typ"
PARAM_VERIFICATION: Final = "overeni"
PARAM_PAGE: Final = "strana"

# A source about both species is also about dogs and also about cats, so the filter "dogs"
# (or "cats") shows it too. "Both species" and "not applicable" are exact.
SPECIES_FILTER: Final = {
    SpeciesScope.DOG: (SpeciesScope.DOG, SpeciesScope.BOTH),
    SpeciesScope.CAT: (SpeciesScope.CAT, SpeciesScope.BOTH),
}

# Columns the list shows; the long text fields are not loaded for it.
LIST_FIELDS: Final = (
    "citation_key",
    "title",
    "authors_or_org",
    "year",
    "source_type",
    "type_note",
    "evidence_level",
    "species_scope",
    "verification_level",
    "last_verified_at",
)


@dataclass(frozen=True)
class SourceQuery:
    """Validated parameters of the list. Empty string = no filter; ``page`` starts at 1."""

    text: str = ""
    evidence: str = ""
    species: str = ""
    source_type: str = ""
    verification: str = ""
    page: int = 1

    @property
    def is_filtered(self) -> bool:
        return bool(
            self.text or self.evidence or self.species or self.source_type or self.verification
        )

    def query_string(self, page: int = 1) -> str:
        """Return the URL-encoded parameters of this query for ``page`` (page 1 is omitted)."""
        pairs = [
            (PARAM_TEXT, self.text),
            (PARAM_EVIDENCE, self.evidence),
            (PARAM_SPECIES, self.species),
            (PARAM_TYPE, self.source_type),
            (PARAM_VERIFICATION, self.verification),
        ]
        if page > 1:
            pairs.append((PARAM_PAGE, str(page)))
        return urlencode([(name, value) for name, value in pairs if value])


@dataclass(frozen=True)
class SourcePage:
    """One page of the list: the query (with the page actually shown), the page object,
    the number of matching sources and the number of all sources."""

    query: SourceQuery
    page: Page
    matched: int
    total: int


def _choice(params: Mapping[str, Any], name: str, allowed: list[str]) -> str:
    value = params.get(name, "")
    return value if isinstance(value, str) and value in allowed else ""


def _clean_text(raw: Any) -> str:
    """Keep printable characters, collapse white space, cut to ``MAX_TEXT_LENGTH``.

    Control characters are dropped: a NUL character would make PostgreSQL refuse the query.
    """
    if not isinstance(raw, str):
        return ""
    printable = "".join(char for char in raw if char.isprintable() or char.isspace())
    return " ".join(printable.split())[:MAX_TEXT_LENGTH]


def parse_query(params: Mapping[str, Any]) -> SourceQuery:
    """Build a ``SourceQuery`` from request parameters (``request.GET``).

    Inputs: a mapping with the parameters ``q``, ``uroven``, ``druh``, ``typ``,
    ``overeni`` and ``strana``. Output: the query; each filter is empty unless its value
    is one of the codes of the model's choices (upper case, exactly), ``q`` is cleaned
    text, ``strana`` is a positive whole number or 1. Never raises.
    """
    page_text = params.get(PARAM_PAGE, "")
    page = 1
    if (
        isinstance(page_text, str)
        and page_text.isascii()
        and page_text.isdigit()
        and len(page_text) <= MAX_PAGE_DIGITS
    ):
        page = max(int(page_text), 1)
    return SourceQuery(
        text=_clean_text(params.get(PARAM_TEXT, "")),
        evidence=_choice(params, PARAM_EVIDENCE, EvidenceLevel.values),
        species=_choice(params, PARAM_SPECIES, SpeciesScope.values),
        source_type=_choice(params, PARAM_TYPE, SourceType.values),
        verification=_choice(params, PARAM_VERIFICATION, VerificationLevel.values),
        page=page,
    )


def _filtered(query: SourceQuery) -> QuerySet[ScientificSource]:
    sources = ScientificSource.objects.only(*LIST_FIELDS)
    if query.evidence:
        sources = sources.filter(evidence_level=query.evidence)
    if query.species:
        scopes = SPECIES_FILTER.get(SpeciesScope(query.species), (query.species,))
        sources = sources.filter(species_scope__in=scopes)
    if query.source_type:
        sources = sources.filter(source_type=query.source_type)
    if query.verification:
        sources = sources.filter(verification_level=query.verification)
    # Every word must be found in the key, the title or the authors (case-insensitive).
    for term in query.text.split()[:MAX_TERMS]:
        sources = sources.filter(
            Q(citation_key__icontains=term)
            | Q(title__icontains=term)
            | Q(authors_or_org__icontains=term)
        )
    return sources


def search_sources(query: SourceQuery) -> SourcePage:
    """Return the page of sources matching ``query``.

    Output: ``SourcePage``. A page number beyond the last page is treated like a missing
    one (page 1). The number of database queries is constant (count of matches, the page,
    count of all sources), whatever the page size.
    """
    paginator = Paginator(_filtered(query), PAGE_SIZE)
    number = query.page if query.page <= paginator.num_pages else 1
    return SourcePage(
        query=replace(query, page=number),
        page=paginator.page(number),
        matched=paginator.count,
        total=ScientificSource.objects.count(),
    )
