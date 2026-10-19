"""Výjimky výpočetního jádra ``nutricalc``.

Všechny výjimky jádra dědí z :class:`NutricalcError`. Zprávy jsou česky a
říkají, co je špatně a co udělat. Chybný *typ* argumentu (například číslo
``float`` místo ``Decimal`` nebo ``bool`` místo čísla) hlásí vestavěná
výjimka ``TypeError``, ne výjimka jádra.

Hierarchie::

    NutricalcError
    ├── ValidationError            neplatná data nebo vstup
    │   ├── InvalidInputError      neplatné číslo nebo údaj o zvířeti
    │   └── DuplicateItemError     stejná surovina v receptu dvakrát
    ├── UnitMismatchError          různé nebo nepřevoditelné jednotky
    ├── BasisMismatchError         různé báze (na 100 g, na den, na 1000 kcal…)
    ├── MissingDataError           chybí údaj nutný pro převod
    ├── SpeciesMismatchError       koeficient nebo metoda pro jiný druh
    └── UnsupportedMethodError     metoda není ověřená ani implementovaná

Stavy jako *BLOCKED* nebo *EXPERT_REQUIRED* nejsou výjimky, ale součást
výsledku (docs/05 §5.9, docs/06 §6.9).
"""


class NutricalcError(Exception):
    """Základ všech výjimek jádra."""


class ValidationError(NutricalcError):
    """Neplatná data nebo vstup.

    Příklady: gramy suroviny ≤ 0, prázdný recept, rozporná hodnota živiny
    (minimum nad hodnotou), obsah vody ≥ 100 g/100 g u převodu na sušinu.
    """


class InvalidInputError(ValidationError):
    """Neplatné číslo nebo údaj o zvířeti.

    Příklady: text, který není číslem v povoleném tvaru, záporné číslo tam,
    kde znaménko není dovolené, ``NaN``, hmotnost ≤ 0 nebo mimo technické
    meze věrohodnosti druhu, BCS mimo 1–9, podíl dospělé hmotnosti > 1.
    """


class DuplicateItemError(ValidationError):
    """Stejná surovina je v receptu vícekrát.

    Položky se nikdy neslučují automaticky; rozhodnout musí uživatel
    (docs/06 §6.9, docs/11 §11.2).
    """


class UnitMismatchError(NutricalcError):
    """Veličiny mají různé jednotky nebo jednotku nelze převést.

    Jádro jednotky nikdy tiše nepřevádí; převod je jen explicitní
    (:meth:`nutricalc.units.Quantity.to_unit`).
    """


class BasisMismatchError(NutricalcError):
    """Veličiny mají různé báze (např. na 100 g a na 1000 kcal ME).

    Převod báze je jen explicitní funkcí z :mod:`nutricalc.units`.
    """


class MissingDataError(NutricalcError):
    """Chybí údaj, bez kterého nelze převod nebo výpočet provést.

    Příklad: převod na sušinu bez známého obsahu vody. Chybějící údaj se
    nikdy nenahrazuje nulou.
    """


class SpeciesMismatchError(NutricalcError):
    """Koeficient, exponent nebo metoda patří k jinému druhu zvířete."""


class UnsupportedMethodError(NutricalcError):
    """Metoda výpočtu není ověřená nebo v této verzi jádra není dostupná."""
