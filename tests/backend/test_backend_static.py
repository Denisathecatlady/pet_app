"""Static guards of the web application (scope of this iteration, docs/12)."""

import pytest

from config.settings.base import BASE_DIR
from tests.static_checks import import_offenders

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
