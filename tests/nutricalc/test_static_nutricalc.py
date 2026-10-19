"""Statická pravidla balíčku ``nutricalc``: čisté jádro bez float, I/O a náhody.

Kontrola ``float`` je sdílená s testy ``refdata`` (``tests/static_checks.py``).
"""

import ast
from pathlib import Path

import pytest

from tests.static_checks import (
    attribute_offenders,
    float_offenders,
    import_offenders,
    name_offenders,
)

PACKAGE_DIR = Path(__file__).resolve().parents[2] / "nutricalc"
SOURCES = sorted(PACKAGE_DIR.glob("*.py"))

FORBIDDEN_MODULES = frozenset(
    {
        # I/O, síť, procesy, souborový systém
        "os",
        "io",
        "pathlib",
        "shutil",
        "tempfile",
        "glob",
        "socket",
        "ssl",
        "http",
        "urllib",
        "ftplib",
        "smtplib",
        "subprocess",
        "multiprocessing",
        "threading",
        "asyncio",
        "sys",
        "logging",
        "sqlite3",
        "pickle",
        "builtins",
        "importlib",
        # čas a náhoda
        "datetime",
        "time",
        "random",
        "secrets",
        "uuid",
        # rámce a jiné balíčky projektu
        "django",
        "rest_framework",
        "refdata",
        "requests",
        "numpy",
        "scipy",
    }
)
FORBIDDEN_NAMES = frozenset(
    {"open", "print", "input", "eval", "exec", "compile", "__import__", "breakpoint", "globals"}
)
FORBIDDEN_ATTRIBUTES = frozenset({"now", "today", "utcnow", "urandom", "getcontext", "setcontext"})


def test_package_sources_exist() -> None:
    names = {path.name for path in SOURCES}
    assert {
        "__init__.py",
        "errors.py",
        "decimal_ctx.py",
        "vocab.py",
        "flags.py",
        "units.py",
        "energy.py",
        "composition.py",
        "me.py",
        "requirements.py",
        "evaluation.py",
        "rules.py",
        "gate.py",
        "snapshot.py",
        "analysis.py",
    } <= names


# Referenční energie sloupců (95, 110, 75, 100 kcal/kg BW^n) jsou data profilu
# standardu, ne konstanty kódu (docs/05 §5.0, docs/06 §6.4).
REFERENCE_K_LITERALS = frozenset({95, 110, 75, "95", "110", "75"})
DATA_DRIVEN_MODULES = ("requirements.py", "evaluation.py", "rules.py", "gate.py", "analysis.py")


def _constants(source: str) -> list[object]:
    return [
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and not isinstance(node.value, bool)
    ]


@pytest.mark.parametrize("name", DATA_DRIVEN_MODULES)
def test_no_reference_energy_literals(name: str) -> None:
    constants = _constants((PACKAGE_DIR / name).read_text(encoding="utf-8"))
    assert [value for value in constants if value in REFERENCE_K_LITERALS] == []


def test_requirements_module_has_no_hundred_literal() -> None:
    constants = _constants((PACKAGE_DIR / "requirements.py").read_text(encoding="utf-8"))
    assert [value for value in constants if value in (100, "100")] == []


def test_reference_energy_check_flags_known_bad_snippet() -> None:
    assert [v for v in _constants("if k >= Decimal('110'): pass") if v in REFERENCE_K_LITERALS]


@pytest.mark.parametrize("path", SOURCES, ids=lambda path: path.name)
def test_no_float(path: Path) -> None:
    assert float_offenders(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("path", SOURCES, ids=lambda path: path.name)
def test_no_io_time_randomness_or_framework_imports(path: Path) -> None:
    assert import_offenders(path.read_text(encoding="utf-8"), FORBIDDEN_MODULES) == []


@pytest.mark.parametrize("path", SOURCES, ids=lambda path: path.name)
def test_no_forbidden_builtins(path: Path) -> None:
    assert name_offenders(path.read_text(encoding="utf-8"), FORBIDDEN_NAMES) == []


@pytest.mark.parametrize("path", SOURCES, ids=lambda path: path.name)
def test_no_clock_randomness_or_global_context_access(path: Path) -> None:
    assert attribute_offenders(path.read_text(encoding="utf-8"), FORBIDDEN_ATTRIBUTES) == []


def _decimal_imports(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module == "decimal":
            names.update(alias.name for alias in node.names)
    return names


@pytest.mark.parametrize("path", SOURCES, ids=lambda path: path.name)
def test_only_decimal_ctx_touches_decimal_contexts(path: Path) -> None:
    names = _decimal_imports(path.read_text(encoding="utf-8"))
    context_api = {"localcontext", "getcontext", "setcontext", "Context", "DefaultContext"}
    if path.name == "decimal_ctx.py":
        assert names & context_api == {"localcontext", "Context"}
    else:
        assert names & context_api == set()


@pytest.mark.parametrize(
    ("checker", "forbidden", "snippet"),
    [
        (import_offenders, {"os"}, "import os"),
        (import_offenders, {"os"}, "import os.path as p"),
        (import_offenders, {"os"}, "from os import path"),
        (import_offenders, {"refdata"}, "from refdata.vocab import Species"),
        (import_offenders, {"datetime"}, "from datetime import datetime"),
        (name_offenders, {"open"}, "with open('x') as f: pass"),
        (name_offenders, {"open"}, "reader = open"),
        (name_offenders, {"print"}, "print('x')"),
        (attribute_offenders, {"now"}, "stamp = datetime.now()"),
        (attribute_offenders, {"getcontext"}, "decimal.getcontext().prec = 2"),
    ],
)
def test_checkers_flag_known_bad_snippets(
    checker: object, forbidden: set[str], snippet: str
) -> None:
    assert checker(snippet, forbidden) != []  # type: ignore[operator]


@pytest.mark.parametrize(
    ("checker", "forbidden", "snippet"),
    [
        (import_offenders, {"os"}, "import osmosis"),
        (import_offenders, {"os"}, "from . import os"),
        (import_offenders, {"refdata"}, "from nutricalc.vocab import Species"),
        (name_offenders, {"open"}, "label = 'open'"),
        (name_offenders, {"open"}, "def reopen(): pass"),
        (attribute_offenders, {"now"}, "known = state.known"),
    ],
)
def test_checkers_accept_clean_snippets(checker: object, forbidden: set[str], snippet: str) -> None:
    assert checker(snippet, forbidden) == []  # type: ignore[operator]
