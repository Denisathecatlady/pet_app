# 13. Knihovna zdrojů ve webové aplikaci

> Kapitola popisuje 🛠 implementovaný stav aplikace `catalog` v adresáři `backend/`: veřejnou
> knihovnu odborných zdrojů (model `ScientificSource`, [07](07-django-schema.md) §7.4, obrazovka
> *Knihovna zdrojů* v [08](08-uzivatelske-rozhrani.md) §8.3). **Jediným zdrojem pravdy je registr
> [zdroje.md](zdroje.md).** Knihovna neobsahuje žádné nutriční, energetické ani dávkovací hodnoty
> vlastní; nic nepočítá a nic nedoporučuje (kalkulačka je odložená, [12](12-ucty-a-zvirata.md) §12.7).
> Legenda: ✅ ověřeno · 🟡 ověřit · 🛠 pracovní návrh · 🩺 posoudí vet. nutriční specialista.

## 13.1 Rozsah 🛠

- model `ScientificSource` s historií změn, administrace, veřejné stránky `/zdroje/` a
  `/zdroje/<citační klíč>/`;
- data: všech **37 záznamů** oddílů 1 až 6 registru (5 + 11 + 5 + 9 + 4 + 3), soubor
  `backend/catalog/data/sources.json`;
- načtení: datová migrace `catalog.0002_load_sources` (nová instalace) a příkaz
  `manage.py load_sources` (pozdější aktualizace);
- test shody s dokumentem (`tests/backend/test_catalog_sync.py`).

Oddíl 7 registru (*Zdroje, které je nutné doplnit*) **není seznam zdrojů**. Stránka knihovny ho
ukazuje jako samostatný statický blok *Co zatím chybí* (text je opsaný z dokumentu a test hlídá,
aby se s ním shodoval).

## 13.2 Co uživatel vidí 🛠

Obě stránky jsou **veřejné, bez přihlášení**: jde o transparentnost důkazů, ne o osobní údaje.
Odkaz *Knihovna zdrojů* je v hlavní navigaci pro všechny a na úvodní stránce. Stránky přijímají
jen GET a HEAD.

| Stránka | Obsah |
|---|---|
| `/zdroje/` (`catalog:source_list`) | Výrazný **pruh**: *Zdroj v knihovně není automaticky ověřený v originále* (srozumitelně: zdroj může být uvedený, i když se nepodařilo ověřit jeho obsah v původním dokumentu; podívejte se na stav ověření; zjištění jsou popis zdroje, ne návod ke krmení). Hledání a filtry. Seznam po 25 zdrojích. **Legenda.** Blok *Co zatím chybí* |
| `/zdroje/<klíč>/` (`catalog:source_detail`) | Pruh, **stav ověření** (značka, přesný význam, značky registru, *co přesně bylo ověřeno*, datum), všechna pole zdroje, hlavní zjištění, omezení, legenda. Neznámý klíč: 404 (klíč se rozlišuje podle velikosti písmen) |

**Filtry a hledání** (vše volitelné; adresy jsou česky, hodnoty jsou kódy modelu):

| Parametr | Význam | Povolené hodnoty |
|---|---|---|
| `q` | text v klíči, názvu a autorech; každé slovo se musí najít (velikost písmen se nerozlišuje), nejvýše 5 slov a 100 znaků | libovolný text |
| `uroven` | úroveň důkazů | `L1` až `L6` |
| `druh` | druh zvířat, **přesná hodnota** (zdroje o psech i kočkách jsou pod `BOTH`) | `DOG`, `CAT`, `BOTH`, `NOT_APPLICABLE` |
| `typ` | typ zdroje | kódy `SourceType` |
| `overeni` | stav ověření | `B`, `A`, `P`, `S`, `NONE` |
| `strana` | strana seznamu | celé číslo ≥ 1 |

Každý parametr má bílý seznam. **Nepovolená hodnota se ignoruje** jako by chyběla (žádná chyba,
žádné 500): `uroven=l1`, `druh=dog`, `strana=abc`, `strana=0`, řídicí znaky i velmi dlouhý text.
Strana za posledním stránkováním se bere jako strana 1. Počet dotazů do databáze je u seznamu
vždy 3 (počet nalezených, strana, počet všech zdrojů) a u detailu 1, bez ohledu na počet zdrojů.

**Stav ověření je vždy ikona + text + barva** (docs/08 §8.1), rámeček se u úrovní liší i
stylem čáry (plná, tečkovaná, čárkovaná), takže nic nestojí jen na barvě:

| Stav | Ikona | Barva | Text |
|---|---|---|---|
| `P` | ✓ | zelená | P – ověřeno v primárním zdroji |
| `A` | ◆ | modrá | A – ověřen abstrakt nebo souhrn |
| `S` | ◇ | jantarová | S – ověřeno jen přes sekundární zdroj |
| `B` | ○ | jantarová, tečkovaný rámeček | B – ověřeny jen bibliografické údaje |
| `NONE` | ? | šedá, čárkovaný rámeček | Neověřeno |

Legenda pod těmito krátkými názvy uvádí **přesné významy** z registru (*Jak číst sloupec
Ověření*) a **úrovně L1 až L6** (*Úrovně odbornosti zdroje*) a odstavec o tom, jak rešerše
proběhla. Zrcadlí ji štítky `VerificationLevel` a `EvidenceLevel`; test je porovnává s dokumentem.

**Soukromí.** `verified_by` odkazuje na účet kurátora. Veřejná stránka ukáže jen *kurátor
aplikace (jméno se veřejně nezobrazuje)*, nikdy jméno ani e-mail. Odkazy na externí stránky mají
`rel="noopener noreferrer external"`, odkaz se vypíše jen pro adresy `http://` a `https://`
(hlídá i omezení v databázi), texty se escapují (žádné inline skripty ani styly, CSP).

## 13.3 Model `ScientificSource` a odchylky od docs/07 §7.4 🛠

| Pole | Poznámka |
|---|---|
| `citation_key` | jedinečný slug (`FEDIAF2025`, `PNA-RER`); jedinečný i bez ohledu na velikost písmen; začíná písmenem nebo číslicí |
| `title`, `authors_or_org` | název a autoři; autoři mohou být prázdní (u pěti zdrojů registr píše „autory doplnit“) |
| `year` | 1900 až letošní rok + 1 (hlídá validátor; databáze má hrubé meze 1900–2100). **Může být prázdný** (viz níže) |
| `publication_details` | **navíc:** časopis, ročník, strany, vydavatel, identifikátory PubMed a PMC, zrcadlo souboru |
| `doi`, `url` | DOI bez adresy (`10.xxxx/…`), odkaz jen `http(s)` |
| `source_type`, `type_note` | typ (`GUIDELINE`, `MONOGRAPH`, `META_ANALYSIS`, `REVIEW`, `ORIGINAL_STUDY`, `CASE_REPORT`, `FOOD_DATABASE`, `LAB_ANALYSIS`, `MANUFACTURER_DECLARATION`, `SECONDARY`); **navíc** upřesnění typu, jak ho uvádí registr („Validační studie“) |
| `evidence_level` | `L1` až `L6` s českými popisy z registru |
| `species_scope`, `life_stages` | `DOG`, `CAT`, `BOTH`, `NOT_APPLICABLE`; seznam fází `ADULT`, `GROWTH`, `REPRODUCTION`, `ALL_STAGES` (JSON) |
| `units_and_conditions`, `edition_version` | jednotky a podmínky platnosti, vydání nebo verze |
| `verification_level` | `B`, `A`, `P`, `S`, `NONE`; vždy **nejsilnější ze značek** (§13.4) |
| `verification_markers` | **navíc:** všechny značky B, A, P, S, které registr u zdroje uvádí (JSON) |
| `verification_note` | co přesně bylo ověřeno; poznámky z registru |
| `last_verified_at`, `verified_by` | datum (může být prázdné) a účet; `verified_by` má `on_delete=SET_NULL` |
| `limitations`, `key_findings` | omezení a hlavní zjištění (volitelné) |
| `created_at`, `updated_at` | časy záznamu |

Odchylky od náčrtu v §7.4 (a proč):

1. **`year` smí být prázdný.** `[Wikivet]`, `[USDA-FDC]` a `[CIQUAL]` nemají v registru rok;
   vymyslet ho by porušilo pravidlo nevymýšlet údaje.
2. **`verified_by` má `SET_NULL`, ne `PROTECT`:** smazání účtu kurátora musí projít (GDPR čl. 17).
   Datum ověření zůstane. Při smazání se vymaže i `verified_by` v historii změn (signál).
3. **Pole `publication_details`, `type_note`, `verification_markers`** jsou navíc, jinak by se
   ztratily údaje z registru (časopis a strany, upřesnění typu, kombinace značek).
4. **Pole `species` se jmenuje `species_scope`**, `life_stages` je JSON seznam (ne `ArrayField`),
   `verification_note` a `key_findings` jsou nová pole podle zadání.
5. `authors_or_org` může být prázdné (viz výše). Historie se po smazání zdroje **nemaže**
   (je to auditní stopa referenčních dat).

Omezení v databázi i při validaci (`full_clean`, česky): formát klíče a jeho jedinečnost, neprázdný
název, rozmezí roku, formát DOI, adresa `http(s)`, povolené hodnoty všech výčtů, a:

- **neověřený zdroj (`NONE`) nemá datum ani osobu ověření, ověřený má datum**;
- **stav ověření se rovná nejsilnější značce** (bez značky je `NONE`);
- **databáze složení potravin je `L5`, sekundární nebo populární zdroj je `L6`** (slabý typ si
  nemůže přiřadit vyšší úroveň důkazů);
- datum ověření není v budoucnosti, `life_stages` a `verification_markers` jsou seznamy známých
  jedinečných kódů.

Administrace (`/admin/catalog/scientificsource/`): `SimpleHistoryAdmin`, filtry (úroveň, typ,
druh, ověření), hledání (klíč, název, autoři, DOI), životní fáze a značky ověření jako zaškrtávací
pole. Oprávnění k modelu se zatím přidělují ručně (skupina `data_curator` nemá žádná práva,
[12](12-ucty-a-zvirata.md) §12.2).

## 13.4 Jak se záznam registru převádí na pole 🛠

Buňka *Zdroj* v registru slučuje autory, název a údaje o vydání; převod je ruční a **nic
neupravuje, nepřidává ani nevynechává** (test porovnává slova dokumentu a souboru v obou směrech,
§13.6).

| Údaj v registru | Kam |
|---|---|
| autoři / organizace, název | `authors_or_org`, `title` (název bez závěrečné tečky) |
| časopis, ročník, strany, vydavatel, PubMed, PMC, zrcadlo | `publication_details` |
| *Rok* (nebo rok v buňce *Zdroj*) | `year`; „září 2025“ → 2025, „2019?“ → 2019 (otazník je v `limitations`), „–“ → prázdný |
| datum a verze vydání | `edition_version` |
| URL, DOI | `url`; `doi` jen tam, kde ho registr uvádí (též v adrese `doi.org`) |
| *Typ, úroveň* | `evidence_level` (`L1`…`L6`), `source_type` podle úrovně a slov v buňce, upřesnění do `type_note` |
| *Druh, fáze* (oddíl 1) | `species_scope`, `life_stages`, text navíc do `units_and_conditions` |
| značky ověření | `verification_markers`, `verification_level`, text navíc do `verification_note` |
| hlavní zjištění | `key_findings` |
| „neověřeno“, „doplnit“, „jen komerční“, „právně nezávazná“… | `limitations` nebo `verification_note` |
| odstavec *Co je ověřeno z [FEDIAF2025]* | `verification_note`, `units_and_conditions`, `limitations` |
| „Totéž“ (`[FEDIAF2024]`) | název a autoři se opíšou z `[FEDIAF2025]` |

**Značky a stav ověření.**

- Registr uvádí u zdroje i víc značek (např. `B, A`). Pole `verification_level` je jedno, proto je
  to **nejsilnější značka v pořadí P > A > S > B**: značka sekundárního zdroje (S) říká o obsahu
  víc než samotná bibliografie (B), abstrakt (A) víc než sekundární zdroj, primární zdroj (P) nejvíc.
  Všechny značky zůstávají v `verification_markers` a stránka je vypisuje. 🩺 Pořadí potvrdí specialista.
- **`S/P` u `[FEDIAF2025]`** („struktura tabulek S/P“) registr nerozhodl; počítá se **slabší
  značka, S**. Text „S/P“ zůstává v `verification_note`. Plné tabulky FEDIAF nebyly ověřeny.
- **Zdroj bez značky má stav `NONE`:** `[SciRep2025]` („Existence ověřena“) a oddíl 6
  (`[USDA-FDC]`, `[CIQUAL]`, `[NutriDB-CZ]`) nemají v registru žádnou z B, A, P, S; kurátor jim
  může značku přidělit po ověření. Text registru zůstává ve `verification_note` a stránka u nich
  říká, že registr žádnou značku nepřiřazuje. Datum ověření mají jen zdroje se značkou.
- **Datum ověření:** všem zdrojům se značkou je přiřazeno **18. 10. 2026**, protože registr říká
  „Rešerše proběhla 18. 10. 2026“. `verified_by` je prázdné (registr nikoho nejmenuje).
- Žádný zdroj zatím nemá značku **P**: plné texty nebyly dostupné (registr, *Jak číst sloupec
  Ověření*). Připomínka z registru: *do databáze nutričních standardů ani surovin se nesmí dostat
  žádná hodnota bez stavu P*; knihovna žádné takové hodnoty neobsahuje.

**Druh a fáze.** U oddílu 1 je zapsal registr. U ostatních zdrojů se **druh určuje z názvu zdroje**
(`dog(s)`, `canine`, `cat(s)`, `feline`, *terrier*, *Great Danes*…; oba druhy → `BOTH`),
u databází potravin je `NOT_APPLICABLE`; fáze se uvádějí jen tehdy, když je název nebo text
registru výslovně nese (*adult*, *maintenance*, *growth*, *gestation*, *lactation*, „dospělí“,
„dospělý pes“; *maintenance* se bere jako `ADULT`, *gestation* a *lactation* jako
`REPRODUCTION`). Prázdný seznam znamená „neuvedeno“. 🩺 U tří zdrojů název druh neuvádí a rozhodlo
se takto: `[Wikivet]` a `[PNA-RER]` jsou `BOTH` (obecná sekundární literatura o zvířatech), `[MDPI2025]`
je `DOG`, protože registr z ní přebírá jen kategorie aktivity psů.

**Čísla v poznámkách.** Poznámky k ověření a zjištění opisují registr včetně jeho čísel (např. energetický
základ tabulek FEDIAF u `[FEDIAF2025]`, kategorie aktivity psů u `[MDPI2025]`, obsah Ca a P u
`[SciRep2025]`). Jsou to **popis zdroje a stavu jeho ověření, ne doporučení**; stránka to u hlavních
zjištění i v pruhu říká. Knihovna je nepoužívá k žádnému výpočtu.

**Opsáno beze změny:** překlep v registru „u rostoucích dog“ (`[Hazewinkel1985]`) a větu v první
osobě „proto je nepřebírám“ (`[SciRep2025]`) se neopravovaly; opravit je lze v dokumentu i v souboru.

## 13.5 Jak knihovnu aktualizovat 🛠

1. Upravte **[zdroje.md](zdroje.md)** (jediný zdroj pravdy): nový řádek tabulky, změna značky
   ověření, doplněný autor.
2. Upravte stejný záznam v `backend/catalog/data/sources.json` (ručně, podle §13.4; soubor je JSON
   s položkami `format_version` a `sources`, pořadí záznamů je pořadí v dokumentu).
3. Spusťte `.venv/bin/python -m pytest -q tests/backend/test_catalog_sync.py`. Test **říká, co se
   v dokumentu a v souboru liší**: množina klíčů, rok, značky a stav ověření, úroveň důkazů, URL a DOI,
   slova (co v souboru chybí a co v něm přibylo), legendy a blok *Co zatím chybí*.
4. `cd backend && ../.venv/bin/python manage.py load_sources --dry-run` vypíše, co by se změnilo;
   bez `--dry-run` se změny zapíšou. Příkaz:
   - **vytvoří** nové zdroje a **aktualizuje** změněné podle `citation_key` (upsert), nic **nemaže**,
     `verified_by` nikdy nemění (v souboru není);
   - ověří všechno (`full_clean`) před zápisem a zapisuje v jedné transakci: chyba v souboru nezmění nic;
   - vypíše počty (*Vytvořeno, aktualizováno, beze změny*); druhé spuštění je beze změny (idempotentní);
   - u změněných zdrojů zapíše záznam do historie s důvodem změny.
5. Nový zdroj se zobrazí hned; **smazání zdroje** příkaz neumí (záměrně): smaže se v administraci.

Úprava v administraci se přepíše při dalším `load_sources`, pokud je pole v souboru. Trvalá změna
patří do dokumentu a souboru. Na čisté instalaci načte soubor `migrate` (migrace `0002`, má vlastní
nezávislý zavaděč a nevolá kód aplikace; zná jen pole, která model v dané migraci má, a existující
zdroje nepřepisuje). Test ověřuje, že příkaz po migraci nenajde žádný rozdíl.

## 13.6 Testy 🛠

| Soubor | Co hlídá |
|---|---|
| `test_catalog_models.py` | validace a omezení databáze (rok, klíč, DOI, URL, výčty, pravidla ověření, typ × úroveň), pořadí, historie, smazání účtu s `verified_by` |
| `test_catalog_loader.py` | `load_sources`: úplnost (37), idempotence, aktualizace, nikdy nemaže, `--dry-run`, chyby souboru nic nezapíšou, **datová migrace na čisté databázi** |
| `test_catalog_sync.py` | **shoda s `docs/zdroje.md`**: stejná množina klíčů, roky, značky a stav ověření, úroveň, URL, DOI; slova v obou směrech; legendy; blok *Co zatím chybí*; citace v ostatních dokumentech jen registrovaných klíčů |
| `test_catalog_views.py` | veřejný přístup, filtry, hledání, stránkování, nepovolené parametry, 404, XSS, legenda a pruh, ikona + text + barva, stálý počet dotazů |
| `test_catalog_admin_gdpr.py` | administrace, export osobních údajů (oddíl `catalog`), smazání účtu ověřovatele (stránkou i v administraci) |

## 13.7 Co zatím není 🛠

- vazby `ScientificSource` z dalších modelů (hodnoty, požadavky, koeficienty, pravidla, zdravotní
  stavy): docs/08 §8.3 chce u zdroje i *kde se zdroj v aplikaci používá*, což přijde s těmito
  modely;
- API `/api/v1/sources/` ([07](07-django-schema.md) §7.8), řazení seznamu podle jiných sloupců,
  hledání bez ohledu na diakritiku;
- formulář pro kurátora mimo administraci, skupinová práva pro `data_curator`;
- generování `sources.json` z dokumentu (převod je ruční a rozhoduje o něm člověk, hlídá ho test).

## 13.8 Body pro specialistu 🩺 a pro právníka

Specialista:

1. Pořadí značek ověření pro stav zdroje s více značkami (P > A > S > B, §13.4) a zacházení
   s `S/P` u `[FEDIAF2025]` jako se `S`.
2. Zdroje bez značky (`[SciRep2025]` a oddíl 6) jsou `NONE`. Mají dostat značku?
3. Zařazení druhu u `[Wikivet]`, `[PNA-RER]`, `[MDPI2025]` a životních fází odvozených z názvů (§13.4).
4. Texty pruhu a legendy (srozumitelnost pro majitele), krátké názvy úrovní (*doporučení instituce*,
   *kazuistika*…) a názvy stavů ověření.
5. Zda mají poznámky u zdrojů obsahovat čísla (energetický základ FEDIAF, kategorie aktivity,
   Ca a P) v takové podobě, nebo se na veřejné stránce zkrátit.

Právník:

1. Odkaz `verified_by` je osobní údaj kurátora: veřejně se nezobrazuje, je v exportu osobních údajů
   (oddíl `catalog`: ověřené zdroje a změny provedené v administraci) a při smazání účtu se vymaže
   i z historie změn. Stačí to?
2. Knihovna je veřejná a odkazuje na cizí dokumenty (citace, URL, DOI). Opisují se jen bibliografické
   údaje a stručný popis; plné texty se nekopírují. Je to v pořádku (autorský zákon, podmínky stran
   FEDIAF, NRC, AAFCO)?
