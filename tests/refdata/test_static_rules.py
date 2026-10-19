"""Statická pravidla zdrojového kódu balíčku ``refdata``.

Kontrola ``float`` je sdílená s testy ``nutricalc`` (``tests/static_checks.py``).
"""

import ast
import re
from pathlib import Path

import pytest

from tests.static_checks import float_offenders

PACKAGE_DIR = Path(__file__).resolve().parents[2] / "refdata"
TESTS_DIR = Path(__file__).resolve().parent
SOURCES = sorted(PACKAGE_DIR.glob("*.py"))
CODE_PATTERN = re.compile(r"[EWI]_[A-Z0-9_]+")


def test_package_sources_exist() -> None:
    names = {path.name for path in SOURCES}
    assert {"vocab.py", "decimal_utils.py", "validate.py", "compare.py", "cli.py"} <= names


@pytest.mark.parametrize("path", SOURCES, ids=lambda path: path.name)
def test_no_float_literals_or_float_calls(path: Path) -> None:
    assert float_offenders(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    "snippet",
    [
        "x = 1.5",
        "x = -0.5",
        "x = 1e3",
        "x = 2j",
        "y = float(s)",
        "y = builtins.float(s)",
        "ys = list(map(float, xs))",
        "to_f = float",
        "ok = isinstance(x, float)",
        "def f() -> float: ...",
        "from builtins import float as F",
        "import math",
        "from statistics import mean",
        "y = 1 / 2",
        "y = len(a) / len(b)",
        "y = x.__float__()",
    ],
)
def test_float_checker_flags_known_bad_snippets(snippet: str) -> None:
    assert float_offenders(snippet) != []


def test_float_checker_accepts_decimal_code() -> None:
    clean = (
        "from decimal import Decimal\n"
        "x = Decimal('1.5') / 2\n"
        "y = Decimal(1) / Decimal(3)\n"
        "label = 'float'\n"
        "z = 7 // 2\n"
    )
    assert float_offenders(clean) == []


@pytest.mark.parametrize(
    "path", [p for p in SOURCES if p.name not in {"cli.py", "__main__.py"}], ids=lambda p: p.name
)
def test_no_print_in_library_code(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    ]
    assert calls == []


def _finding_codes() -> set[str]:
    codes = set()
    for path in SOURCES:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if CODE_PATTERN.fullmatch(node.value):
                codes.add(node.value)
    return codes


def _case_table_codes() -> set[str]:
    """Kódy v tabulkách ``*_CASES`` testů.

    Každou takovou tabulku čte parametrizovaný test, který pro pozitivní
    vstup ověří, že nález vznikne, a pro blízký negativní vstup, že nevznikne.
    """
    codes = set()
    for path in TESTS_DIR.glob("test_*.py"):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(t, ast.Name) and t.id.endswith("_CASES") for t in node.targets):
                continue
            codes.update(
                constant.value
                for constant in ast.walk(node.value)
                if isinstance(constant, ast.Constant)
                and isinstance(constant.value, str)
                and CODE_PATTERN.fullmatch(constant.value)
            )
    return codes


def test_every_finding_code_has_a_positive_and_negative_case() -> None:
    codes = _finding_codes()
    assert len(codes) >= 30
    assert sorted(codes - _case_table_codes()) == []
