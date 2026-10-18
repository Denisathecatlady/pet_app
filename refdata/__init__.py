"""Kontrola přepisu tabulek nutričních standardů (balíček ``refdata``).

Čistý Python bez Djanga a bez vedlejších efektů: čtení souborů probíhá jen
v explicitních načítacích funkcích (:func:`refdata.catalog.load_catalog`,
:func:`refdata.standard_rows.load_standard_csv`). Všechna čísla jsou
``decimal.Decimal`` parsovaná z textu, nikdy ``float``.
"""

__version__ = "0.1.0"
