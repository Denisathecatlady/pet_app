"""docs/zdroje.md is the single source of truth: the data file, the model choices and the
public page must say the same as the document (docs/13 §13.5).

The document is parsed here (the application never reads docs/ at run time). When this
file fails after somebody edited the document, edit ``backend/catalog/data/sources.json``
(and the template of "Co zatím chybí") to match, then run ``manage.py load_sources``.
"""

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest
from django.urls import reverse
from django.utils.html import strip_tags

from catalog.loader import DATA_FILE
from catalog.models import (
    EvidenceLevel,
    ScientificSource,
    SourceType,
    VerificationLevel,
    strongest_level,
)
from config.settings.base import REPO_DIR

DOC_PATH = REPO_DIR / "docs" / "zdroje.md"

# --- Parsing the document ---------------------------------------------------------------------

MARKS = ("B", "A", "P", "S")
STRENGTH = {"B": 1, "S": 2, "A": 3, "P": 4}


def plain(text: str) -> str:
    """Remove Markdown emphasis and code marks, collapse white space."""
    return " ".join(re.sub(r"[*`]", "", text).split())


@dataclass(frozen=True)
class DocRow:
    key: str
    section: int
    cells: dict[str, str]  # role → plain text; roles: source, year, link, type, scope, check
    extra: str = ""  # text of the document outside the table that belongs to this key


ROLES = (
    ("Klíč", "key"),
    ("Zdroj", "source"),
    ("Rok", "year"),
    ("DOI", "link"),
    ("URL", "link"),
    ("Typ", "type"),
    ("Úroveň", "type"),
    ("Druh", "scope"),
    ("Ověření", "check"),
    ("Hlavní zjištění", "check"),
    ("Ověřeno", "check"),
)


def role_of(header: str) -> str:
    for prefix, role in ROLES:
        if header.startswith(prefix):
            return role
    raise AssertionError(f"Unknown column in docs/zdroje.md: {header!r}")


def split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split(" | ")]


def parse_doc(text: str) -> list[DocRow]:
    """Rows of the tables in sections 1 to 6, with the paragraph "Co je ověřeno z [Klíč]"."""
    blocks = {
        match.group(1): plain(match.group(0))
        for match in re.finditer(
            r"\*\*Co je ověřeno z `\[(\w+)\]`.*?(?=\n## |\Z)", text, flags=re.DOTALL
        )
    }
    rows: list[DocRow] = []
    section = 0
    roles: list[str] = []
    for line in text.splitlines():
        heading = re.match(r"^## (\d+)\.", line)
        if heading:
            section = int(heading.group(1))
            roles = []
        elif line.startswith("| Klíč |"):
            roles = [role_of(header) for header in split_row(line)]
        elif line.startswith("| `[") and 1 <= section <= 6:
            cells = split_row(line)
            assert len(cells) == len(roles), f"row of {cells[0]} does not fit its table header"
            by_role = {role: plain(cell) for role, cell in zip(roles, cells, strict=True)}
            key = re.fullmatch(r"\[([^\]]+)\]", by_role.pop("key"))
            assert key, cells[0]
            rows.append(DocRow(key.group(1), section, by_role, blocks.get(key.group(1), "")))
    return rows


def split_clauses(text: str) -> list[str]:
    """Split at ``;``, ``,`` and sentence-ending full stops outside parentheses."""
    clauses, depth, current = [], 0, ""
    for index, char in enumerate(text):
        depth += char == "("
        depth -= char == ")"
        ends_sentence = char == "." and (index + 1 == len(text) or text[index + 1] == " ")
        if depth == 0 and (char in ";," or ends_sentence):
            clauses.append(current.strip())
            current = ""
        else:
            current += char
    clauses.append(current.strip())
    return [clause for clause in clauses if clause]


def doc_marks(text: str, *, first_sentence_only: bool) -> set[str]:
    """The marks B, A, P, S a verification text assigns.

    A clause counts when it is only a mark (``B``, ``A (autory doplnit)``) or ends with a
    mark (``Rovnice RER S``). ``S/P`` (it is not decided which) counts as the weaker one, S.
    With ``first_sentence_only`` (the findings columns) only the first sentence is read,
    because findings may contain letters such as “vitaminy A a D”.
    """
    if first_sentence_only:
        text = re.split(r"\.(?:\s|$)(?![^(]*\))", text, maxsplit=1)[0]
    marks: set[str] = set()
    for clause in split_clauses(text):
        bare = re.sub(r"\s*\([^)]*\)", "", clause).strip()
        if re.fullmatch(r"[BAPS]", bare):
            marks.add(bare)
        elif bare.endswith(" S/P") or bare == "S/P" or re.search(r"\bS/P\b", bare):
            marks.add("S")
        elif re.search(r"\s[BAPS]$", bare):
            marks.add(bare[-1])
    return marks


def expected_marks(row: DocRow) -> set[str]:
    check = row.cells.get("check", "")
    if row.section in (1, 2):
        return doc_marks(check, first_sentence_only=False)
    if row.section == 6:
        return set()
    return doc_marks(check, first_sentence_only=True)


def expected_year(row: DocRow) -> int | None:
    cell = row.cells["year"] if "year" in row.cells else row.cells["source"]
    match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", cell)
    return int(match.group(1)) if match else None


def expected_url(row: DocRow) -> str:
    match = re.search(r"https?://[^\s)]+", row.cells["link"])
    return match.group(0).rstrip(".,;") if match else ""


def expected_doi(row: DocRow) -> str:
    match = re.search(r"10\.\d{4,9}/[^\s,)]+", row.cells["link"])
    return match.group(0).rstrip(".,;") if match else ""


def expected_level(row: DocRow) -> str:
    match = re.search(r"\bL[1-6]\b", row.cells["type"])
    assert match, row.key
    return match.group(0)


DOC_TEXT = DOC_PATH.read_text(encoding="utf-8")
DOC_ROWS = parse_doc(DOC_TEXT)
FILE_SOURCES = {
    entry["citation_key"]: entry
    for entry in json.loads(DATA_FILE.read_text(encoding="utf-8"))["sources"]
}


# --- Parser self-tests (so a failure below is about the data, not about the parser) --------------


@pytest.mark.parametrize(
    ("text", "first_only", "expected"),
    [
        ("B, A", False, {"B", "A"}),
        ("B", False, {"B"}),
        ("B (částečně), A", False, {"B", "A"}),
        ("A (autory a časopis doplnit)", False, {"A"}),
        ("B; vybrané rovnice S", False, {"B", "S"}),
        ("B; struktura tabulek S/P (viz níže)", False, {"B", "S"}),
        ("Rovnice pro koťata S. Tvrzení o nižší RER u obézních zvířat S", False, {"S"}),
        (
            "Kategorie aktivity (95 / 110, extrémní 860–1 240 kcal/kg^0,75) S. Autory doplnit",
            False,
            {"S"},
        ),
        ("B. Sekundární přehled shrnuje vitaminy A a D. Přesná procenta neověřena.", True, {"B"}),
        ("B, A. Hodnoceno 200 receptů. Jen 9 splnilo minima.", True, {"B", "A"}),
        ("Existence ověřena (autory doplnit). Studie uvádí Ca a P.", True, set()),
        ("B (spoluautory doplnit), A. Z 90 konzerv mělo 12 thiamin pod minimem.", True, {"B", "A"}),
        ("Pět datových typů: Foundation Foods. Licence neověřena.", False, set()),
    ],
)
def test_mark_parser(text, first_only, expected):
    assert doc_marks(text, first_sentence_only=first_only) == expected


def test_document_is_parsed_completely():
    sections = {row.section for row in DOC_ROWS}
    assert sections == {1, 2, 3, 4, 5, 6}
    assert len(DOC_ROWS) == 37
    assert len({row.key for row in DOC_ROWS}) == 37
    assert DOC_ROWS[0].key == "FEDIAF2025" and "Edice 2025 vyšla" in DOC_ROWS[0].extra


# --- The data file says what the document says ------------------------------------------------


def test_same_set_of_citation_keys():
    """Every entry of sections 1 to 6, and nothing else (section 7 is not a source list)."""
    assert set(FILE_SOURCES) == {row.key for row in DOC_ROWS}
    assert len(FILE_SOURCES) == len(DOC_ROWS)


def test_file_keeps_the_order_of_the_document():
    keys = [entry["citation_key"] for entry in json.loads(DATA_FILE.read_text("utf-8"))["sources"]]
    assert keys == [row.key for row in DOC_ROWS]


@pytest.mark.parametrize("row", DOC_ROWS, ids=lambda row: row.key)
def test_same_year(row):
    assert FILE_SOURCES[row.key]["year"] == expected_year(row)


@pytest.mark.parametrize("row", DOC_ROWS, ids=lambda row: row.key)
def test_same_verification_status(row):
    """The marks, the summarising level and the dates follow the document."""
    entry = FILE_SOURCES[row.key]
    marks = expected_marks(row)
    assert set(entry["verification_markers"]) == marks
    assert entry["verification_level"] == strongest_level(marks)
    assert (entry["last_verified_at"] is not None) is bool(marks)


@pytest.mark.parametrize("row", DOC_ROWS, ids=lambda row: row.key)
def test_same_evidence_level_links_and_type(row):
    entry = FILE_SOURCES[row.key]
    assert entry["evidence_level"] == expected_level(row)
    assert entry["url"] == expected_url(row)
    assert entry["doi"] == expected_doi(row)
    allowed = {
        "L1": {"GUIDELINE", "MONOGRAPH"},
        "L2": {"META_ANALYSIS", "REVIEW"},
        "L3": {"ORIGINAL_STUDY"},
        "L4": {"CASE_REPORT"},
        "L5": {"FOOD_DATABASE"},
        "L6": {"SECONDARY"},
    }
    assert entry["source_type"] in allowed[entry["evidence_level"]]
    type_text = row.cells["type"]
    for phrase, source_type in [
        ("Metaanalýza", "META_ANALYSIS"),
        ("(přehled)", "REVIEW"),
        ("(série případů)", "CASE_REPORT"),
        ("Vědecká monografie", "MONOGRAPH"),
        ("Sekundární. L6", "SECONDARY"),
    ]:
        if phrase in type_text:
            assert entry["source_type"] == source_type


@pytest.mark.parametrize("row", [row for row in DOC_ROWS if row.section == 1], ids=lambda r: r.key)
def test_species_and_life_stages_of_standards(row):
    """Section 1 states the species and the life stages in its own column."""
    entry = FILE_SOURCES[row.key]
    scope = row.cells["scope"]
    assert "Psi a kočky" in scope and entry["species_scope"] == "BOTH"
    stages = set()
    for stage, words in {
        "ADULT": ("Dospělí", "Adult"),
        "GROWTH": ("růst", "Growth"),
        "REPRODUCTION": ("reprodukce", "Reproduction"),
        "ALL_STAGES": ("Všechny fáze",),
    }.items():
        if any(word in scope for word in words):
            stages.add(stage)
    assert set(entry["life_stages"]) == stages


def test_food_databases_have_no_species():
    for row in DOC_ROWS:
        entry = FILE_SOURCES[row.key]
        assert (row.section == 6) == (entry["species_scope"] == "NOT_APPLICABLE")


# --- Nothing dropped, nothing invented -------------------------------------------------------

TOKEN = re.compile(r"[^\W_]+(?:[.,:/–-][^\W_]+)*")

# Words of the document that the data file expresses as codes (type, species, life stage).
CODED_PHRASES = ("Metaanalýza", "Původní studie", "(přehled)", "(série případů)", "Totéž")
CODED_SCOPE_PHRASES = ("Psi a kočky", "Dospělí", "Všechny fáze", "růst", "reprodukce")
# Sentences of the data file that describe the document instead of copying it.
EDITORIAL = {
    "PuppyIntake2019": "Rok vydání je v registru uveden s otazníkem („2019?“).",
}
# A row that says “Totéž” (the same) takes title and authors from the row it refers to.
SAME_AS = {"FEDIAF2024": "FEDIAF2025"}

FILE_TEXT_FIELDS = (
    "title",
    "authors_or_org",
    "publication_details",
    "doi",
    "url",
    "type_note",
    "units_and_conditions",
    "edition_version",
    "verification_note",
    "limitations",
    "key_findings",
)


def tokens(text: str) -> set[str]:
    return {token.lower() for token in TOKEN.findall(html.unescape(text))}


def doc_tokens(row: DocRow) -> set[str]:
    parts = []
    for role, cell in row.cells.items():
        if role == "type":
            for phrase in CODED_PHRASES:
                cell = cell.replace(phrase, " ")
            cell = re.sub(r"^Sekundární\.", " ", cell)
        elif role == "scope":
            for phrase in CODED_SCOPE_PHRASES:
                cell = cell.replace(phrase, " ")
        elif role == "source":
            cell = cell.replace("Totéž", " ")
        parts.append(cell)
    parts.append(row.extra)
    found = tokens(" ".join(parts)) - {"–"}
    found |= tokens(expected_doi(row))  # the DOI inside a doi.org address is a token of its own
    return {token for token in found if not re.fullmatch(r"L[1-6]", token.upper())}


def file_tokens(entry: dict, key: str) -> set[str]:
    texts = [entry[name] for name in FILE_TEXT_FIELDS]
    if key in EDITORIAL:
        assert EDITORIAL[key] in entry["limitations"]
        texts = [text.replace(EDITORIAL[key], " ") for text in texts]
    return tokens(" ".join(texts))


@pytest.mark.parametrize("row", DOC_ROWS, ids=lambda row: row.key)
def test_every_word_of_the_document_is_in_the_data_file_and_the_other_way_round(row):
    entry = FILE_SOURCES[row.key]
    in_doc = doc_tokens(row)
    in_file = file_tokens(entry, row.key)
    marks = {mark.lower() for mark in MARKS}
    year = {str(entry["year"])} if entry["year"] else set()

    missing = in_doc - in_file - marks - year
    assert not missing, f"in docs/zdroje.md but not in sources.json: {sorted(missing)}"

    allowed = in_doc | marks | year
    if row.key in SAME_AS:
        allowed |= doc_tokens(next(r for r in DOC_ROWS if r.key == SAME_AS[row.key]))
    invented = in_file - allowed
    assert not invented, f"in sources.json but not in docs/zdroje.md: {sorted(invented)}"


def test_totez_rows_copy_title_and_authors():
    for key, source in SAME_AS.items():
        assert FILE_SOURCES[key]["title"] == FILE_SOURCES[source]["title"]
        assert FILE_SOURCES[key]["authors_or_org"] == FILE_SOURCES[source]["authors_or_org"]


def test_no_markdown_is_left_in_the_data_file():
    for entry in FILE_SOURCES.values():
        for name in FILE_TEXT_FIELDS:
            assert "*" not in entry[name] and "`" not in entry[name], (entry["citation_key"], name)


# --- Legends -----------------------------------------------------------------------------------


def legend_rows(heading: str, pattern: str) -> dict[str, str]:
    start = DOC_TEXT.index(heading)
    end = DOC_TEXT.index("\n## ", start) if "\n## " in DOC_TEXT[start:] else len(DOC_TEXT)
    rows = {}
    for line in DOC_TEXT[start:end].splitlines():
        match = re.match(rf"^\| \*\*({pattern})\*\* \| (.+) \|$", line)
        if match:
            rows[match.group(1)] = plain(match.group(2)).rstrip(".")
    return rows


def test_verification_legend_equals_the_document():
    doc = legend_rows("## Jak číst sloupec", "[BAPS–]")
    assert set(doc) == {"B", "A", "P", "S", "–"}
    doc["NONE"] = doc.pop("–")
    assert {level.value: level.label for level in VerificationLevel} == doc


def test_evidence_legend_equals_the_document():
    doc = legend_rows("## Úrovně odbornosti zdroje", "L[1-6]")
    assert {level.value: level.label for level in EvidenceLevel} == doc


def test_source_types_cover_every_level_of_the_legend():
    covered = {
        "L1": {SourceType.GUIDELINE, SourceType.MONOGRAPH},
        "L2": {SourceType.META_ANALYSIS, SourceType.REVIEW},
        "L3": {SourceType.ORIGINAL_STUDY},
        "L4": {SourceType.CASE_REPORT},
        "L5": {SourceType.FOOD_DATABASE},
        "L6": {SourceType.SECONDARY},
    }
    assert set(covered) == set(EvidenceLevel.values)


# --- The public page says what the document says --------------------------------------------------


def page_text(response) -> str:
    return " ".join(html.unescape(strip_tags(response.content.decode())).split())


def section_7(text: str) -> tuple[str, list[str]]:
    start = text.index("## 7.")
    body = text[start:]
    lead = plain(re.search(r"\n\n(Tyto oblasti.*?:)\n", body, flags=re.DOTALL).group(1))
    items = [
        plain(item)
        for item in re.findall(r"^\d+\. (.*?)(?=\n\d+\. |\Z)", body, flags=re.MULTILINE | re.DOTALL)
    ]
    return lead, items


@pytest.mark.django_db
def test_gaps_block_is_the_text_of_section_7(client):
    lead, items = section_7(DOC_TEXT)
    assert len(items) == 9
    response = client.get(reverse("catalog:source_list"))
    content = response.content.decode()
    block = re.search(r'<ol class="gaps">(.*?)</ol>', content, flags=re.DOTALL).group(1)
    shown = [
        " ".join(html.unescape(strip_tags(item)).split())
        for item in re.findall(r"<li>(.*?)</li>", block, flags=re.DOTALL)
    ]

    assert shown == items
    assert lead in page_text(response)
    assert "Co zatím chybí" in content


@pytest.mark.django_db
def test_section_7_entries_are_not_sources():
    """Section 7 is a list of gaps: nothing from it is a citation key."""
    section = DOC_TEXT[DOC_TEXT.index("## 7.") :]
    assert not re.findall(r"`\[\w+\]`", section)


@pytest.mark.django_db
def test_legend_page_repeats_how_the_research_was_done(client):
    paragraph = re.search(r"\n(Rešerše proběhla .*?)\n\n", DOC_TEXT, flags=re.DOTALL).group(1)
    for url in (reverse("catalog:source_list"), reverse("catalog:source_detail", args=["NRC2006"])):
        assert plain(paragraph) in page_text(client.get(url))


@pytest.mark.django_db
def test_legend_texts_on_the_page_are_the_document_texts(client):
    text = page_text(client.get(reverse("catalog:source_detail", args=["NRC2006"])))
    for label in [*(level.label for level in EvidenceLevel), *(v.label for v in VerificationLevel)]:
        assert f"{label}." in text


# --- Citations elsewhere ----------------------------------------------------------------------


def test_other_documents_cite_only_registered_keys():
    cited = set()
    for path in [*(REPO_DIR / "docs").glob("*.md"), REPO_DIR / "README.md"]:
        cited |= set(re.findall(r"`\[([A-Za-z][A-Za-z0-9_-]*)\]`", path.read_text("utf-8")))
    assert cited - set(FILE_SOURCES) == set()


@pytest.mark.django_db
def test_database_holds_exactly_the_file_after_migration():
    assert set(ScientificSource.objects.values_list("citation_key", flat=True)) == set(FILE_SOURCES)


def test_document_path_exists():
    assert Path(DOC_PATH).is_file()
