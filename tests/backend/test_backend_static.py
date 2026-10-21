"""Static guards of the web application (scope of this iteration, docs/12)."""

import ast

import pytest

from config.settings.base import BASE_DIR
from tests.static_checks import float_offenders, import_offenders

PYTHON_SOURCES = sorted(BASE_DIR.rglob("*.py"))


@pytest.mark.parametrize("path", PYTHON_SOURCES, ids=lambda p: str(p.relative_to(BASE_DIR)))
def test_backend_does_not_import_calculation_packages(path):
    """The calculator is postponed: Django code must not use nutricalc or refdata yet."""
    assert import_offenders(path.read_text(encoding="utf-8"), ["nutricalc", "refdata"]) == []


def test_animals_ui_has_no_energy_units():
    sources = [*(BASE_DIR / "animals").rglob("*.py"), *(BASE_DIR / "templates").rglob("*.html")]
    for path in sources:
        text = path.read_text(encoding="utf-8").lower()
        for unit in ("kcal", "kj/", "kcal/kg", "mer =", "rer ="):
            assert unit not in text, (path, unit)


ANIMALS_FLOAT_FREE = sorted(
    path for path in (BASE_DIR / "animals").glob("*.py") if path.name != "charts.py"
)


@pytest.mark.parametrize("path", ANIMALS_FLOAT_FREE, ids=lambda p: p.name)
def test_animals_code_outside_charts_uses_no_float(path):
    """Weights are Decimal; floats are allowed only for pixel geometry in ``charts.py``."""
    assert float_offenders(path.read_text(encoding="utf-8")) == []


# Everything in ``charts.py`` that touches weights, differences, percentages, axis values
# or dates is float-free; floats appear only in the pixel mapping and the geometry types.
CHARTS_DECIMAL_ONLY = (
    "nice_ticks",
    "weight_axis",
    "date_ticks",
    "_day_ticks",
    "_month_ticks",
    "select_period",
    "summarize_weight",
    "change_sentence",
    "kg_text",
    "signed_kg",
    "signed_percent",
    "WeightSummary",
)


def test_charts_keeps_decimals_out_of_float_code():
    source = (BASE_DIR / "animals" / "charts.py").read_text(encoding="utf-8")
    nodes = {
        node.name: node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef | ast.ClassDef)
    }
    for name in CHARTS_DECIMAL_ONLY:
        segment = ast.get_source_segment(source, nodes[name])
        assert float_offenders(segment) == [], name
    assert "float(" in source  # the pixel mapping really is where floats are allowed
