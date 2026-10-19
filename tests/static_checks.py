"""Statické kontroly zdrojového kódu sdílené testy balíčků ``refdata`` a ``nutricalc``.

Každá funkce dostane zdrojový text modulu a vrátí seznam nálezů ve tvaru
``"ř. N: popis"`` (prázdný seznam = bez nálezu). Kontroly procházejí AST,
takže se netýkají textu v řetězcích a komentářích.
"""

import ast
from collections.abc import Iterable

FLOAT_NAMES = frozenset({"float", "complex"})
FLOAT_ATTRIBUTES = FLOAT_NAMES | {"__float__", "__complex__"}
FLOAT_MODULES = frozenset({"math", "cmath", "statistics", "fractions"})
INT_CALLS = frozenset({"len", "int"})


def _is_int_like(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, int) and not isinstance(node.value, bool)
    if isinstance(node, ast.UnaryOp):
        return _is_int_like(node.operand)
    return (
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in INT_CALLS
    )


def float_offenders(source: str) -> list[str]:
    """Vrátí místa, kudy by se do kódu mohl dostat ``float``.

    Hlásí literál float/complex, jakékoli použití jména ``float``/``complex``
    (volání, předání jako funkce, alias, ``isinstance``, anotace), atribut
    ``__float__``, import z ``math``/``cmath``/``statistics``/``fractions`` a
    pravé dělení dvou celých čísel (``1 / 2``, ``len(a) / len(b)``).
    """
    offenders = []
    for node in ast.walk(ast.parse(source)):
        line = getattr(node, "lineno", "?")
        if isinstance(node, ast.Constant) and isinstance(node.value, (float, complex)):
            offenders.append(f"ř. {line}: literál {node.value!r}")
        elif isinstance(node, ast.Name) and node.id in FLOAT_NAMES:
            offenders.append(f"ř. {line}: jméno {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in FLOAT_ATTRIBUTES:
            offenders.append(f"ř. {line}: atribut {node.attr}")
        elif isinstance(node, ast.Import):
            offenders.extend(
                f"ř. {line}: import {alias.name}"
                for alias in node.names
                if alias.name.split(".")[0] in FLOAT_MODULES
            )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.split(".")[0] in FLOAT_MODULES or any(
                alias.name in FLOAT_NAMES for alias in node.names
            ):
                offenders.append(f"ř. {line}: import z {module}")
        elif (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Div)
            and _is_int_like(node.left)
            and _is_int_like(node.right)
        ):
            offenders.append(f"ř. {line}: dělení celých čísel")
    return offenders


def import_offenders(source: str, forbidden_modules: Iterable[str]) -> list[str]:
    """Vrátí importy zakázaných modulů (včetně podmodulů a ``from … import``).

    Vstup: zdrojový text a kořenová jména zakázaných modulů (např. ``"os"``
    zakáže i ``os.path``). Relativní importy (``from . import x``) se nehlásí.
    """
    forbidden = frozenset(forbidden_modules)
    offenders: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            offenders.extend(
                f"ř. {node.lineno}: import {alias.name}"
                for alias in node.names
                if alias.name.split(".")[0] in forbidden
            )
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            module = node.module or ""
            if module.split(".")[0] in forbidden:
                offenders.append(f"ř. {node.lineno}: import z {module}")
    return offenders


def name_offenders(source: str, forbidden_names: Iterable[str]) -> list[str]:
    """Vrátí každé použití zakázaného jména (volání i předání, např. ``open``)."""
    forbidden = frozenset(forbidden_names)
    return [
        f"ř. {node.lineno}: jméno {node.id}"
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Name) and node.id in forbidden
    ]


def attribute_offenders(source: str, forbidden_attributes: Iterable[str]) -> list[str]:
    """Vrátí každý přístup k zakázanému atributu (např. ``datetime.now``)."""
    forbidden = frozenset(forbidden_attributes)
    return [
        f"ř. {node.lineno}: atribut {node.attr}"
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute) and node.attr in forbidden
    ]
