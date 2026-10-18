# BARF Nutri – odborná aplikace pro výpočet a kontrolu výživy psů a koček

Webová aplikace (Python, Django, PostgreSQL) pro **nutriční analýzu** syrových (BARF) a domácích dávek.
Nepočítá jen poměr svalovina : kosti : orgány. Počítá skutečný obsah živin, porovná ho se zvoleným
verzovaným standardem (výchozí FEDIAF 2025) a u každého čísla ukáže zdroj a spolehlivost.

> **Stav projektu: Fáze 1 – analýza a odborné základy (dokončena, čeká na odbornou revizi).**
> Zatím nevznikl žádný aplikační kód.

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
