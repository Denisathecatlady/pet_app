"""Výpočetní jádro aplikace BARF Nutri (balíček ``nutricalc``).

Čistý Python bez Djanga, bez I/O a bez náhodnosti (docs/07 §7.1 a §7.2).
Všechna čísla jsou ``decimal.Decimal`` a veškerá aritmetika běží v lokálním
kontextu :data:`nutricalc.decimal_ctx.CALC_CONTEXT`, takže výsledek nezávisí
na globálním nastavení modulu ``decimal``. Čísla typu ``float`` veřejné
funkce odmítají výjimkou ``TypeError``.

Moduly:

- :mod:`nutricalc.errors` – výjimky jádra,
- :mod:`nutricalc.decimal_ctx` – kontext ``Decimal`` a striktní převod čísel,
- :mod:`nutricalc.vocab` – řízené slovníky (druh, báze, jednotka, stavy…),
- :mod:`nutricalc.flags` – upozornění výsledků (:class:`~nutricalc.flags.Flag`),
- :mod:`nutricalc.units` – veličiny s jednotkou a bází a explicitní převody,
- :mod:`nutricalc.energy` – energetická potřeba zvířete (docs/05),
- :mod:`nutricalc.composition` – hodnoty živin surovin a součty dávky (docs/06 §6.5),
- :mod:`nutricalc.me` – metabolizovatelná energie dávky (docs/06 §6.3),
- :mod:`nutricalc.requirements` – požadavky standardu a výběr sloupce (docs/06 §6.4),
- :mod:`nutricalc.evaluation` – stavy živin, Ca:P, spolehlivost a souhrn (docs/06 §6.6),
- :mod:`nutricalc.rules` – deklarativní pravidla upozornění (docs/06 §6.7),
- :mod:`nutricalc.gate` – bezpečnostní brána (docs/09 §9.2),
- :mod:`nutricalc.snapshot` – neměnný vstup, kanonický JSON a hash (docs/07 §7.2),
- :mod:`nutricalc.analysis` – celý rozbor ``analyze_recipe`` (docs/06 §6.1, §6.9).

Koeficienty energetické potřeby ``k``, hodnoty požadavků, prahy a pravidla
jsou data, která předává volající; v kódu jsou jen publikované koeficienty
rovnic s odkazem na zdroj (docs/05 §5.0, docs/06 §6.7).
"""

__version__ = "0.1.0"

ENGINE_VERSION = __version__
"""Verze výpočetní logiky ukládaná do každého výsledku (docs/07 §7.2)."""
