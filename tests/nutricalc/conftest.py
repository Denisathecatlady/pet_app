"""Nastavení testů balíčku ``nutricalc``.

Testy vlastností (hypothesis) běží deterministicky (``derandomize``) a bez
databáze příkladů, aby byl výsledek stejný na každém stroji a v CI.
"""

from hypothesis import settings

settings.register_profile("nutricalc", derandomize=True, database=None, deadline=None)
settings.load_profile("nutricalc")
