# BARF Nutri – odborná aplikace pro výpočet a kontrolu výživy psů a koček

Webová aplikace (Python, Django, PostgreSQL) pro **nutriční analýzu** syrových (BARF) a domácích dávek.
Nepočítá jen poměr svalovina : kosti : orgány. Počítá skutečný obsah živin, porovná ho se zvoleným
verzovaným standardem (výchozí FEDIAF 2025) a u každého čísla ukáže zdroj a spolehlivost.

> **Stav projektu: Fáze 1 – analýza a odborné základy (dokončena, čeká na odbornou revizi).**
> Aplikace (Django, UI) zatím nevznikla. Existuje pomocný nástroj `refdata` pro kontrolu přepisu
> tabulek standardu (milník M1) a výpočetní jádro `nutricalc` (milník M2: od energie a součtů živin
> po vyhodnocení proti standardu a souhrn, ověřené jen na syntetických datech), viz [Nástroje](#nástroje).

## Dokumentace Fáze 1

| # | Dokument | Obsah |
|---|---|---|
| 1 | [Produktová koncepce](docs/01-produktova-koncepce.md) | Problém, vize, uživatelé, hranice bezpečného použití |
| 2 | [Odborné standardy](docs/02-odborne-standardy.md) | FEDIAF × NRC × AAFCO × WSAVA, rozdíly a pravidla práce |
| 3 | [Nutriční požadavky](docs/03-nutricni-pozadavky.md) | Fáze, seznam živin, ověřené hodnoty, postup importu tabulek |
| 4 | [Databáze surovin a zdrojů](docs/04-databaze-surovin-a-zdroju.md) | Kategorie, atributy, kvalita dat, maso s kostí, externí databáze |
| 5 | [Energetický model](docs/05-energeticky-model.md) | RER, MER, růst, adaptivní korekce, kontrolní příklady |
| 6 | [Nutriční analýza](docs/06-nutricni-analyza.md) | Jednotky, ME, součty s chybějícími daty, stavy, interakce, optimalizace |
| 7 | [Architektura a schéma Django](docs/07-django-schema.md) | Vrstvy, determinismus, modely, ER diagram, bezpečnost, API |
| 8 | [Uživatelské rozhraní](docs/08-uzivatelske-rozhrani.md) | Obrazovky, vizualizace stavů a nejistoty, úrovně upozornění |
| 9 | [Rizika](docs/09-rizika.md) | Odborná, softwarová a právní rizika, bezpečnostní brána |
| 10 | [Plán MVP](docs/10-plan-mvp.md) | Milníky, odhady, **doporučení nejmenší verze (MVP-0)** |
| 11 | [Testovací plán](docs/11-testovaci-plan.md) | Katalog testů, golden příklady, odborná validace |
| – | [Registr zdrojů](docs/zdroje.md) | Všechny citace s úrovní ověření |

Datové šablony: [`data/reference/nutrients.csv`](data/reference/nutrients.csv) (katalog 52 položek:
živiny a proximátní složky) a [`data/reference/standard_import_template.csv`](data/reference/standard_import_template.csv)
(šablona pro dvojí přepis tabulek standardu, **bez hodnot**).

### Legenda stavů v dokumentech

| Značka | Význam |
|---|---|
| ✅ | Ověřeno proti dohledatelnému zdroji (P = primárně, S = přes sekundární zdroj) |
| 🟡 | Ověřit v originále před použitím (sekundární nebo neověřený údaj) |
| 🛠 | Pracovní návrh (technické nebo produktové rozhodnutí) |
| 🩺 | Musí posoudit veterinární nutriční specialista před nasazením |

## Nástroje

Balíček [`refdata/`](refdata/) kontroluje dvojí přepis tabulek standardu (čistý Python 3.12+, jen
standardní knihovna, čísla jako `Decimal`). Postup pro přepisovatele a specialistu:
[docs/postup-prepisu-standardu.md](docs/postup-prepisu-standardu.md).

```bash
# kontrola jednoho přepisu (během práce s --allow-empty, před odevzdáním bez něj)
.venv/bin/python -m refdata validate cesta/prepis.csv [--allow-empty] [--catalog CESTA] [--json]

# porovnání dvou nezávislých přepisů A a B
.venv/bin/python -m refdata compare cesta/prepis_A.csv cesta/prepis_B.csv [--json]
```

Návratový kód: `0` bez chyb, `1` alespoň jedna chyba (ERROR, včetně souboru přepisu v jiném kódování
než UTF-8), `2` chybné použití, soubor nelze otevřít nebo katalog nelze použít.

Balíček [`nutricalc/`](nutricalc/) je výpočetní jádro (čistý Python 3.12+, bez Djanga a bez I/O,
jen `Decimal` v lokálním kontextu, deterministické). Vstupem je neměnný snapshot `AnalysisInput`
se všemi daty, výstupem `AnalysisResult` s hashem vstupu i výsledku; jádro nic nečte z databáze
ani ze souborů. Moduly:

| Modul | Obsah |
|---|---|
| `errors`, `decimal_ctx`, `vocab`, `flags` | výjimky, kontext `Decimal` a striktní převod čísel, slovníky, upozornění |
| `units` | `Quantity` (hodnota + jednotka + báze), převody g/mg/µg a kcal/kJ, explicitní převody bází |
| `energy` | RER, MER = k · BW^n, rovnice růstu (mimo MVP), `estimate_energy` se stavy OK / EXPERT_REQUIRED / BLOCKED ([05](docs/05-energeticky-model.md)) |
| `composition` | hodnoty živin se stavy (`MISSING` ≠ 0), denní součty s intervaly a úplností ([06](docs/06-nutricni-analyza.md) §6.5) |
| `me` | ME dávky z makroživin: `NRC2006_DOG_CF`, `NRC2006_DOG_TDF`, `MOD_ATWATER` ([06](docs/06-nutricni-analyza.md) §6.3) |
| `requirements` | požadavky a sloupce standardu, `k_skut = DER / BW^n`, výběr sloupce a přepočet jen minim ([06](docs/06-nutricni-analyza.md) §6.4) |
| `evaluation` | stavy živin (`BELOW_MIN` … `NOT_EVALUABLE`), pokrytí a zobrazení „< 100 %“, Ca:P, spolehlivost, konzervativní souhrn ([06](docs/06-nutricni-analyza.md) §6.6) |
| `rules`, `gate` | deklarativní pravidla upozornění (data, ne kód) a bezpečnostní brána OK / EXPERT_REQUIRED / BLOCKED ([06](docs/06-nutricni-analyza.md) §6.7, [09](docs/09-rizika.md) §9.2) |
| `snapshot`, `analysis` | `AnalysisInput`, kanonický JSON a SHA-256, `analyze_recipe` ([07](docs/07-django-schema.md) §7.2, [06](docs/06-nutricni-analyza.md) §6.9) |

Koeficienty `k`, požadavky, prahy a pravidla jsou data, která předává volající. Testovací suroviny
a standardy jsou syntetické (`SYN_*`, `TESTSTD`).

Testy (vývojové závislosti `pytest` a `hypothesis` podle `pyproject.toml`): `.venv/bin/python -m pytest -q`
(jen jádro: `.venv/bin/python -m pytest -q tests/nutricalc`). Testy jádra obsahují referenční příklady
docs/05 §5.8 a docs/06 §6.10, vlastnostní testy (nezávislost na pořadí, chybějící data ≠ 0) a statické
kontroly zdrojů (žádný `float`, I/O, čas ani náhoda).

## Předávací zpráva Fáze 1

**Výsledek:** Návrh všech 10 požadovaných oblastí + testovací plán + registr zdrojů.

**Soubory:** `README.md`, `docs/01–11*.md`, `docs/zdroje.md`, `data/reference/nutrients.csv`,
`data/reference/standard_import_template.csv`.

**Provedené testy:** Kód zatím neexistuje, takže žádné automatické testy. Kontrolní příklady energie
a ME (docs/05 §5.8, docs/06 §6.3 a §6.10) byly spočítány v Pythonu s `Decimal` (přesnost 28).
CSV soubory prošly kontrolou struktury.

**Známé problémy a omezení:**
1. Originální PDF FEDIAF 2025, NRC 2006 a AAFCO nebyla z vývojového prostředí dostupná (blokované
   domény). Struktura a vybrané hodnoty jsou ověřené přes vyhledávání, **úplné číselné tabulky
   požadavků zatím nejsou přepsané**. Je to záměr: viz docs/03 §3.0.
2. Plné texty studií nebyly čteny, ověření proběhlo na úrovni bibliografie a abstraktů (viz
   docs/zdroje.md).
3. Neověřené zůstávají: rovnice pro březost a laktaci, koeficienty ME pro kočky, rovnice pro obézní
   kočky, licence databází složení potravin.
4. Datová mezera: složení masa s kostí (Ca, P), jód a taurin v surovinách.

**Další kroky:**
1. Odborná revize Fáze 1 veterinárním nutričním specialistou (kontrolní seznamy v docs/02, 03 a 11).
2. Zpřístupnit originál FEDIAF 2025 a provést dvojí přepis tabulek (M1).
3. Ověřit licence USDA FDC, CIQUAL a NutriDatabáze ČR.
4. Začít Fázi 2/3 implementací jádra `nutricalc` podle MVP-0 (docs/10 §10.5).

## Důležité upozornění

Aplikace není veterinární služba a nenahrazuje vyšetření ani individuální dietní plán. Syrová strava
nese mikrobiologická a parazitologická rizika pro zvířata i lidi v domácnosti (docs/09).
