"""Výstup nálezů: český text pro lidi a JSON pro nástroje."""

import json
from collections.abc import Sequence

from refdata.findings import ERROR, INFO, WARNING, Finding, count_by_severity

SEVERITY_LABELS = {ERROR: "CHYBA", WARNING: "VAROVÁNÍ", INFO: "INFO"}


def format_text(findings: Sequence[Finding], title: str) -> str:
    """Vrátí nálezy jako český text.

    Vstup: nálezy (v pořadí, v jakém se mají vypsat) a nadpis.
    Výstup: nadpis, jeden řádek na nález (závažnost, kód, řádky, zpráva) a
    souhrnný řádek s počty podle závažnosti; text končí novým řádkem.
    """
    output = [title, "=" * len(title)]
    for finding in findings:
        where = (
            f"ř. {', '.join(str(line) for line in finding.lines)}" if finding.lines else "soubor"
        )
        output.append(
            f"{SEVERITY_LABELS[finding.severity]} {finding.code} ({where}): {finding.message}"
        )
    if not findings:
        output.append("Žádné nálezy.")
    counts = count_by_severity(findings)
    output.append(
        f"Souhrn: chyby (ERROR) {counts[ERROR]}, varování (WARNING) {counts[WARNING]}, "
        f"informace (INFO) {counts[INFO]}"
    )
    return "\n".join(output) + "\n"


def to_json(findings: Sequence[Finding]) -> str:
    """Vrátí nálezy jako JSON.

    Vstup: nálezy. Výstup: objekt ``{"findings": [...], "summary": {...}}``
    se seřazenými klíči a češtinou bez escapování (``ensure_ascii=False``);
    ``lines`` a ``key`` jsou seznamy (``key`` může být ``null``).
    """
    payload = {
        "findings": [
            {
                "severity": finding.severity,
                "code": finding.code,
                "message": finding.message,
                "lines": list(finding.lines),
                "key": list(finding.key) if finding.key is not None else None,
            }
            for finding in findings
        ],
        "summary": count_by_severity(findings),
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)
