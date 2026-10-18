"""Statická pravidla zdrojového kódu balíčku ``refdata``."""

import ast
import re
from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).resolve().parents[2] / "refdata"
TESTS_DIR = Path(__file__).resolve().parent
SOURCES = sorted(PACKAGE_DIR.glob("*.py"))
CODE_PATTERN = re.compile(r"[EWI]_[A-Z0-9_]+")


def test_package_sources_exist() -> None:
    names = {path.name for path in SOURCES}
    assert {"vocab.py", "decimal_utils.py", "validate.py", "compare.py", "cli.py"} <= names


@pytest.mark.parametrize("path", SOURCES, ids=lambda path: path.name)
def test_no_float_literals_or_float_calls(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (float, complex)):
            offenders.append(f"ř. {node.lineno}: literál {node.value!r}")
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name == "float":
                offenders.append(f"ř. {node.lineno}: volání float()")
    assert offenders == []


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


def test_every_finding_code_is_exercised_by_tests() -> None:
    codes = _finding_codes()
    assert len(codes) >= 30
    test_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in TESTS_DIR.glob("test_*.py")
        if path.name != Path(__file__).name
    )
    untested = sorted(code for code in codes if f'"{code}"' not in test_sources)
    assert untested == []
