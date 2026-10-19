# Postup dvojího přepisu tabulek standardu (FEDIAF 2025)

> Legenda: ✅ ověřeno · 🟡 ověřit v originále · 🛠 pracovní návrh · 🩺 posoudí vet. nutriční specialista.
> Celý postup je 🛠 pracovní návrh. Před prvním použitím ho schválí 🩺 specialista.

**Pro koho:** dva přepisovatelé (dále **A** a **B**), kurátor dat, který soubory porovná (role
`data_curator`), a recenzující veterinární nutriční specialista (role `nutrition_reviewer`).
**Navazuje na:** [03-nutricni-pozadavky.md](03-nutricni-pozadavky.md) §3.5 (postup importu),
[07-django-schema.md](07-django-schema.md) §7.6 (verzování dat), [zdroje.md](zdroje.md) (pravidlo stavu P).

Tento dokument záměrně **neobsahuje žádné hodnoty nutričních požadavků** kromě jednoho už
zdokumentovaného příkladu převodu (§7). Všechny hodnoty se berou jen z originálu.

## 1. Účel

Tabulky standardu mají stovky buněk. Jediná přehlédnutá chyba (posunutý řádek, záměna mg a µg,
hodnota z jiného sloupce) se promítne do každého výpočtu dávky. Proto platí tři pojistky:

1. **Dvojí nezávislý přepis.** Dvě osoby přepíší stejné tabulky, aniž by o sobě věděly, co zapsaly.
   Nástroj soubory porovná a každý rozdíl se dohledá v originále.
2. **Automatické kontroly.** Nástroj `python -m refdata` ověří tvar každého řádku (slovníky, čísla,
   jednotky, původ hodnoty) a vnitřní konzistenci tabulek (minimum < maximum, převody mezi bázemi,
   sloupce 95/110 a 75/100).
3. **Revize specialistou.** Do výpočtů vstupuje jen verze dat, kterou specialista schválil.

Nástroj nezná originál. Neověří, že hodnota je *správná*, jen že je zapsaná ve správném tvaru, že
si tabulky navzájem neodporují a že se oba přepisy shodují. Kontrola proti originálu zůstává na lidech.

## 2. Zdroj: jen originální PDF

- **Jediný povolený zdroj:** originální PDF *FEDIAF Nutritional Guidelines 2025* (`[FEDIAF2025]`,
  odkaz v [zdroje.md](zdroje.md)). Na titulní straně ověřte, že jde o vydání 2025.
- **Nikdy nepřepisujte z:**
  - dokumentů tohoto repozitáře (`docs/`, `data/`): obsahují jen orientační údaje, většinou ověřené
    přes sekundární zdroje (stav S), a ty se do dat nesmí dostat (pravidlo v [zdroje.md](zdroje.md)),
  - paměti, starších vydání FEDIAF, studií nebo webů, které FEDIAF citují, ani z výstupů AI nástrojů.
- Oba přepisovatelé musí pracovat se **stejným souborem PDF**. Před začátkem každý spočítá jeho
  kontrolní součet a pošle ho kurátorovi:

  ```bash
  sha256sum FEDIAF-Nutritional-Guidelines_2025-ONLINE.pdf
  ```

  Kurátor práci spustí, až se oba součty shodují.

## 3. Příprava souboru

1. Zkopírujte šablonu [`data/reference/standard_import_template.csv`](../data/reference/standard_import_template.csv)
   do vlastního pracovního souboru, např. `fediaf2025_AA.csv` (AA = vaše iniciály). Soubor ukládejte
   **mimo sdílený repozitář**, dokud ho neodevzdáte (§5).
2. První řádek (hlavičku) neměňte. Tři ukázkové řádky šablony **smažte**. Jejich předvyplněná pole
   (fáze, `k`, báze, typ, jednotka, tabulka) by oba přepisovatelé převzali stejně a `compare` by v nich
   chybu nenašel. Každý řádek zapište celý sami z originálu.
3. Editor: textový editor, nebo LibreOffice Calc s těmito volbami při otevření i uložení:
   kódování **UTF-8**, oddělovač **čárka**, všechny sloupce typu **Text**.
4. **Pozor na Excel s českým nastavením:** ukládá desetinnou čárku a středník jako oddělovač, maže
   koncové nuly (`0.50` → `0.5`) a převádí text na data. Takový soubor nástroj odmítne nebo, hůř,
   ztratí informaci o přesnosti. Excel proto nepoužívejte.

## 4. Pravidla zápisu

### 4.1 Jedna buňka tabulky = jeden řádek

Každá číselná buňka tabulky (jedna živina × jeden sloupec profilu × jedna báze) je jeden řádek CSV.
Pokud tabulka uvádí stejnou živinu na 100 g sušiny, na 1 000 kcal ME i na MJ ME, vzniknou tři řádky.
Právě díky tomu nástroj zkontroluje převody mezi bázemi. Nic nepřepočítávejte: zapisujte jen to, co je
vytištěno.

Pokud originál uvádí maximum (`NUTRITIONAL_MAX`, `LEGAL_MAX_EU`) nebo poměr jednou společně pro oba
sloupce energie (pes 95 i 110, kočka 75 i 100), zapište ho pro **každý z obou profilů** zvlášť: dva řádky
se stejnou hodnotou a stejným původem, každý se svou fází a `k`. Kontrola `E_MIN_NOT_BELOW_MAX`
porovnává minima jen s maximy stejného profilu (fáze a `k`). Maximum zapsané jen u jednoho sloupce by se
s minimy druhého sloupce nikdy neporovnalo. Které buňky jsou společné, určí kurátor v písemném zadání (§9).

| Sloupec | Co zapsat |
|---|---|
| `standard_code` | `FEDIAF` |
| `edition` | `2025` |
| `species` | `DOG` nebo `CAT` |
| `life_stage` | Klíč fáze podle [03](03-nutricni-pozadavky.md) §3.1: pes `ADULT_MAINTENANCE`, `ADULT_MAINTENANCE_LOW`, `EARLY_GROWTH_REPRO`, `LATE_GROWTH`; kočka `ADULT_MAINTENANCE`, `ADULT_MAINTENANCE_LOW`, `GROWTH_REPRO`. Přiřazení sloupců tabulek k fázím určí kurátor písemně před začátkem (§9) |
| `reference_energy_k` | Referenční energie sloupce v kcal ME/kg metabolické hmotnosti, jak ji uvádí hlavička tabulky. U dospělých fází povinná: podle [03](03-nutricni-pozadavky.md) §3.1 pes `ADULT_MAINTENANCE` = `110`, `ADULT_MAINTENANCE_LOW` = `95`, kočka `ADULT_MAINTENANCE` = `100`, `ADULT_MAINTENANCE_LOW` = `75` (přiřazení u koček 🟡 ověřit). Nástroj tuto vazbu nekontroluje, proto ji ověřuje kurátor a specialista (§10). U růstu a reprodukce ji vyplňte jen tehdy, když ji tabulka uvádí |
| `reference_energy_exponent` | `0.75` pro psy, `0.67` pro kočky |
| `basis` | Podle jednotky v hlavičce tabulky: `PER_100G_DM` (na 100 g sušiny), `PER_1000KCAL_ME`, `PER_MJ_ME`, `PER_KG_BW075` (jen psi), `PER_KG_BW067` (jen kočky) |
| `nutrient_code` | Kód z katalogu [`data/reference/nutrients.csv`](../data/reference/nutrients.csv) |
| `requirement_type` | FEDIAF: `MIN_RECOMMENDED` (doporučené minimum), `NUTRITIONAL_MAX` (nutriční maximum, v tabulce „N“), `LEGAL_MAX_EU` (zákonné maximum EU, „L“), `RATIO_MIN` / `RATIO_MAX` (poměry). Typy `MR`, `AI`, `RA`, `SUL` patří k NRC |
| `value` | Číslo **přesně tak, jak je vytištěno**: desetinná tečka (nikdy čárka), **včetně koncových nul**, bez mezer, znaménka a oddělovače tisíců. Čárka v anglickém originálu odděluje tisíce: vynechte ji (`1,000` → `1000`), nikdy ji nenahrazujte tečkou (`1.000` je jedna). Nejvýše 15 platných číslic. Počet desetinných míst určuje toleranci kontrol (§7) |
| `unit` | Jednotka, jak je vytištěna: `g`, `mg`, `ug` (µg), `kcal` (jen `ENERGY_ME`), `IU` (jen vitaminy A, D, E), `ratio` (poměr) |
| `condition_note` | Podmínka z poznámky pod čarou nebo z textu tabulky (např. rozdílné hodnoty pro vlhké a suché krmivo). Text **zkopírujte z PDF** (anglicky, beze změn), aby se A a B shodovali: podmínka je součástí klíče řádku. Nástroj v klíči sjednotí mezery, zalomení řádků, nezlomitelné mezery a ligatury z kopírování. Velikost písmen a znění se ale shodovat musí. Bez podmínky nechte prázdné |
| `source_table` | Označení tabulky, jak je vytištěno (např. `III-3b`). **Povinné** |
| `source_page` | Číslo strany vytištěné na stránce. Pokud chybí, číslo strany v prohlížeči PDF a do `note` napište „strana PDF“. **Povinné** |
| `transcriber` | Vaše iniciály. A a B musí mít různé iniciály |
| `transcribed_at` | Datum přepisu ve tvaru `RRRR-MM-DD` |
| `note` | Volný text: nejasnosti, ruční ověření, případně token `CONFIRMED_AS_PRINTED` (§8) |

Ukázka tvaru řádku (hodnota je zástupný text, ne číslo k opsání):

```csv
FEDIAF,2025,DOG,ADULT_MAINTENANCE,110,0.75,PER_1000KCAL_ME,ZN,MIN_RECOMMENDED,<číslo z originálu>,mg,,<tabulka>,<strana>,AA,<datum>,
```

### 4.2 Zvláštní případy

- **Prázdná buňka, pomlčka, „–“:** řádek nevytvářejte. Nulu nikdy nedoplňujte.
- **Značka poznámky u čísla** (např. horní index „a“): do `value` jen číslo. Podmínku z poznámky
  zapište do `condition_note`, ostatní vysvětlení do `note`.
- **Rozsah, „<“, „>“ nebo text místo čísla:** nic si nedomýšlejte. Hodnotu nechte prázdnou, situaci
  popište v `note` a dejte vědět kurátorovi. Před odevzdáním se taková buňka musí vyřešit.
- **Poměr** vytištěný jako `a:1`: do `value` zapište `a`, jednotka `ratio`, typ `RATIO_MIN` nebo
  `RATIO_MAX`.
- **Jednotka se liší od katalogu** (např. tabulka uvádí mg, katalog µg): jednotku ponechte podle
  originálu, **nepřepočítávejte** a upozorněte kurátora. Nástroj nahlásí `E_UNIT_NOT_CANONICAL` a soubor
  do vyřešení nelze odevzdat. Řeší kurátor: ověří jednotku v originále. Jde-li o chybu přepisu, opraví se
  jednotka podle originálu. Pokud standard opravdu používá jinou jednotku než katalog, kurátor navrhne
  změnu kanonické jednotky v katalogu `data/reference/nutrients.csv` (ukládací jednotky viz
  [06](06-nutricni-analyza.md) §6.2), specialista ji schválí a teprve pak se přepis znovu zkontroluje.
  Ruční přepočet hodnoty v přepisu není dovolen.
- **IU** jen u vitaminů A, D a E. Hodnotu ponechte v IU. Převod se převezme z přílohy standardu jako
  samostatný ověřený záznam (`W_NEEDS_CONVERSION`). Převodní údaje z přílohy přepíší A i B nezávisle
  (s tabulkou a stranou), kurátor oba zápisy porovná a specialista je ověří. Řádky v IU se v kontrolách
  mezi řádky (§7) neporovnávají s řádky v µg nebo mg, jejich vztah k minimům a maximům proto
  specialista ověří ručně.

## 5. Nezávislost práce

- Každý přepisuje sám. Až do porovnání **nesdílejte** soubory, poznámky ani snímky obrazovky a
  nebavte se o konkrétních hodnotách.
- Dotazy k postupu (ne k hodnotám) posílejte kurátorovi. Kurátor odpoví písemně oběma stejně.
- Hotový soubor odevzdejte kurátorovi zvlášť. Porovnání spouští jen kurátor.
- Pokud oba soubory u buňky uvádějí stejné iniciály (bez ohledu na velikost písmen a tečky, `A.A.` = `aa`),
  nahlásí nástroj u každé takové buňky chybu `E_SAME_TRANSCRIBER` a porovnání neprojde. Úplnost původu
  (`transcriber`, `source_table`, `source_page`) `compare` nekontroluje. To dělá přísné `validate` obou
  souborů (§9).

## 6. Příkazy

Spouštějte z kořene repozitáře (potřebujete jen Python ze složky `.venv`, žádné další balíčky):

```bash
# během práce: nevyplněné řádky jsou jen INFO
.venv/bin/python -m refdata validate cesta/fediaf2025_AA.csv --allow-empty

# před odevzdáním: musí skončit s 0 chybami (ERROR)
.venv/bin/python -m refdata validate cesta/fediaf2025_AA.csv

# kurátor: porovnání přepisu A a B (obsahuje i chyby parsování obou souborů)
.venv/bin/python -m refdata compare cesta/fediaf2025_AA.csv cesta/fediaf2025_BB.csv
```

- `--json` vypíše nálezy ve formátu JSON (pro archivaci protokolu).
- `--catalog CESTA` použije jiný katalog živin. Výchozí je `data/reference/nutrients.csv` v repozitáři,
  nezávisle na aktuální složce.
- **Návratový kód:** `0` = žádná chyba, `1` = alespoň jedna chyba (ERROR), `2` = chybné použití příkazu,
  soubor nelze otevřít (neexistuje, chybí práva) nebo katalog nelze použít. Chyby obsahu souboru přepisu,
  včetně kódování (`E_ENCODING`) a hlavičky (`E_HEADER`), jsou nálezy ERROR s kódem `1`.
- Řádek výpisu má tvar `CHYBA E_KÓD (ř. 12): zpráva`. Číslo řádku odpovídá řádku souboru (hlavička
  je řádek 1). U `compare` zpráva vždy uvádí, ke kterému souboru (A, nebo B) se který řádek vztahuje.
  Poslední řádek výpisu je souhrn počtů podle závažnosti.

**Závažnost:** `ERROR` brání odevzdání a předání dat. `WARNING` je nutné ručně ověřit v originále a
výsledek zapsat do `note`. `INFO` je jen informace.

## 7. Jak vyřešit jednotlivé nálezy

**Tolerance kontrol konzistence** se odvozuje z vytištěné přesnosti: hodnota s *n* desetinnými místy
zastupuje interval ± polovina posledního místa. Zdokumentovaný příklad z
[03](03-nutricni-pozadavky.md) §3.3 (pes dospělý, 110 kcal/kg^0,75; stav ✅ S, tedy přes sekundární
zdroj): Ca `1.25` g na 1 000 kcal ME znamená interval `[1.245; 1.255]`. Hodnota `0.50` g na 100 g sušiny je
v 03 §3.3 **dopočtená** (1,25 ÷ 2,5), ne opsaná. Zde ji bereme, jako by byla vytištěna se dvěma
desetinnými místy (skutečnou přesnost v originále je nutné ověřit), takže znamená `[0.495; 0.505]` a po
vynásobení faktorem 2,5 (FEDIAF předpokládá 4 000 kcal ME/kg sušiny) `[1.2375; 1.2625]`. Intervaly se
překrývají, kontrola projde. Hodnota `0.60` by neprošla (`E_BASIS_DM_1000`). Proto je důležité zapisovat
koncové nuly. Příklad slouží jen k vysvětlení tolerance: i tyto buňky se přepisují z originálu, ne z tohoto
dokumentu.

### Soubor jako celek

| Kód | Závažnost | Co znamená | Co udělat |
|---|---|---|---|
| `E_ENCODING` | ERROR | Soubor není v UTF-8 | Uložte znovu jako CSV v UTF-8 |
| `E_HEADER` | ERROR | Hlavička se liší od šablony (nebo je soubor prázdný) | Zkopírujte první řádek přesně ze šablony |
| `E_CSV_SYNTAX` | ERROR | Chybné uvozovky, soubor nelze dočíst | Opravte uvozovky na uvedeném řádku |
| `E_COLUMN_COUNT` | ERROR | Řádek má jiný počet sloupců, byl vynechán | Text s čárkou dejte do uvozovek, doplňte chybějící sloupce |

### Jeden řádek

| Kód | Závažnost | Co znamená | Co udělat |
|---|---|---|---|
| `E_PARSE_DECIMAL` | ERROR | `value`, `reference_energy_k` nebo `reference_energy_exponent` není číslo v povoleném tvaru, nebo má víc než 15 platných číslic | Jen číslice a desetinná tečka přesně podle originálu, bez znaménka, exponentu a mezer. Čárku oddělující tisíce vynechte (`1,000` → `1000`), nikdy ji nenahrazujte tečkou. Desetinnou čárku z českého zvyku nepoužívejte |
| `E_NONPOSITIVE_VALUE` | ERROR | Hodnota je 0 | Ověřte v originále. Prázdnou buňku nepřepisujte jako 0, řádek smažte |
| `E_EMPTY_VALUE` | ERROR | Chybí hodnota (přísná kontrola) | Doplňte číslo z originálu, nebo řádek smažte |
| `I_NOT_FILLED` | INFO | Nevyplněný řádek (jen s `--allow-empty`) | Před odevzdáním doplňte, nebo smažte |
| `E_MISSING_PROVENANCE` | ERROR | Chybí `source_table`, `source_page` nebo `transcriber` | Doplňte. U řádku s hodnotou platí i s `--allow-empty` |
| `E_BAD_DATE` | ERROR | `transcribed_at` chybí nebo není skutečné datum `RRRR-MM-DD` | Opravte (např. `2026-01-31`) |
| `E_UNKNOWN_SPECIES` | ERROR | Druh není `DOG` ani `CAT` | Opravte (velká písmena) |
| `E_UNKNOWN_LIFE_STAGE` | ERROR | Fáze neexistuje nebo neplatí pro druh | Použijte klíč z §4.1 podle přiřazení od kurátora |
| `E_UNKNOWN_REQ_TYPE` | ERROR | Neznámý typ požadavku | Použijte typ z §4.1 |
| `E_UNKNOWN_BASIS` | ERROR | Neznámá báze | Použijte bázi z §4.1 podle hlavičky tabulky |
| `E_UNKNOWN_UNIT` | ERROR | Neznámá jednotka | `g`, `mg`, `ug`, `kcal`, `IU`, `ratio` (µg pište jako `ug`) |
| `E_UNKNOWN_NUTRIENT` | ERROR | Kód živiny není v katalogu | Opravte kód. Chybí-li živina v katalogu, řeší kurátor |
| `E_SPECIES_EXPONENT` | ERROR | Exponent chybí nebo neodpovídá druhu | Pes `0.75`, kočka `0.67` |
| `E_BASIS_SPECIES` | ERROR | `PER_KG_BW075` u kočky nebo `PER_KG_BW067` u psa | Opravte bázi nebo druh |
| `E_MISSING_REF_ENERGY` | ERROR | Dospělá fáze bez `reference_energy_k` | Doplňte z hlavičky tabulky |
| `E_RATIO_TYPE` | ERROR | Poměrová živina bez typu `RATIO_*` a jednotky `ratio`, nebo naopak | Poměr: `RATIO_MIN`/`RATIO_MAX` + `ratio`. Ostatní živiny tyto hodnoty nesmí mít |
| `E_KCAL_UNIT` | ERROR | Jednotka `kcal` u jiné živiny než `ENERGY_ME` | Opravte jednotku |
| `E_UNIT_NOT_CANONICAL` | ERROR | Jednotka se liší od kanonické jednotky v katalogu (nebo IU mimo vitaminy A, D, E) | Ověřte jednotku v originále. Pokud ji originál opravdu používá, nepřepočítávejte, napište to do `note` a předejte kurátorovi. Soubor do vyřešení nejde odevzdat, postup řešení je v §4.2 |
| `W_NEEDS_CONVERSION` | WARNING | Vitamin A, D nebo E v IU | Ponechte IU. Převod z přílohy standardu přepíší A i B nezávisle, kurátor je porovná (§4.2). Kontroly mezi řádky řádek v IU neporovnají s řádky v µg/mg |
| `W_SPECIES_NOT_RELEVANT` | WARNING | Katalog živinu u druhu nesleduje | Ověřte druh a živinu. Pokud řádek sedí, upozorněte kurátora katalogu |
| `E_DUPLICATE_KEY` | ERROR | Stejná buňka (klíč) je v souboru vícekrát | Smažte duplicitu, nebo řádky rozlište v `condition_note` podle originálu |

### Vztahy mezi řádky

Tyto kontroly běží jen nad řádky bez chyb, s vyplněnou hodnotou a se stejnou jednotkou.

| Kód | Závažnost | Co znamená | Co udělat |
|---|---|---|---|
| `E_MIN_NOT_BELOW_MAX` | ERROR | Ve stejném profilu (fáze a `k`), bázi a podmínce není minimum (`MIN_RECOMMENDED`, `MR`, `AI`, `RA`) menší než každé maximum (`NUTRITIONAL_MAX`, `SUL`, `LEGAL_MAX_EU`), nebo `RATIO_MIN` ≥ `RATIO_MAX` | Ověřte obě buňky: obvykle jde o záměnu řádku, sloupce nebo typu požadavku. Maxima společná pro oba sloupce energie zapisujte u obou profilů (§4.1) |
| `W_NUTRITIONAL_ABOVE_LEGAL` | WARNING | Ve stejném profilu, bázi a podmínce je nutriční maximum (`NUTRITIONAL_MAX`) větší než zákonné maximum EU (`LEGAL_MAX_EU`). Je to neobvyklé, ale možné: zákonný limit pro komerční krmiva může být nižší než nutriční maximum, proto to není chyba | Ověřte obě buňky v originále a výsledek kontroly zapište do `note` |
| `E_BASIS_DM_1000` | ERROR / WARNING | Neplatí `na 1000 kcal ME = na 100 g sušiny × 2.5`. U poměrů (`RATIO_MIN`, `RATIO_MAX`) se hodnoty na obou bázích musí shodovat, protože poměr na bázi nezávisí | Ověřte obě buňky v originále. Viz §8 |
| `E_BASIS_MJ_1000` | ERROR / WARNING | Neplatí `na 1000 kcal ME = na MJ ME × 4.184` (u poměrů shoda) | Dtto |
| `E_BASIS_DM_MJ` | ERROR / WARNING | Neplatí `na MJ ME = na 100 g sušiny × 2.5 / 4.184` (u poměrů shoda) | Dtto |
| `W_SCALED_PAIR` | WARNING | U požadavku typu minimum v dospělé fázi neplatí `hodnota(95) ≈ hodnota(110) × 110/95` (pes), resp. `hodnota(75) ≈ hodnota(100) × 100/75` (kočka). Sloupec s nižší energií má mít **vyšší** hodnotu. Páruje se podle `k`, na názvu dospělé fáze nezáleží | FEDIAF nemusí všechny řádky odvozovat přepočtem. Ověřte obě buňky ručně a výsledek zapište do `note`. U maxim, poměrů a fází růstu a reprodukce se kontrola nepoužívá |

### Porovnání A × B (`compare`)

| Kód | Závažnost | Co znamená | Co udělat |
|---|---|---|---|
| `E_ONLY_IN_A` / `E_ONLY_IN_B` | ERROR | Buňka je jen v jednom souboru | Dohledejte v originále. Chybí-li řádek, doplňte ho, jinak opravte klíčová pole (druh, fáze, k, báze, živina, typ, podmínka) |
| `E_VALUE_MISMATCH` | ERROR | Hodnoty se číselně liší (prázdná proti vyplněné se také liší) | Dohledejte buňku v originále a opravte chybný soubor |
| `W_PRECISION_DIFFERS` | WARNING | Číselně stejné, ale jiný počet desetinných míst (`1.0` × `1.00`) | Zapište přesnost přesně podle originálu |
| `E_UNIT_MISMATCH` | ERROR | Různé jednotky | Ověřte jednotku v originále |
| `W_PROVENANCE_DIFFERS` | WARNING | Různá tabulka nebo strana | Ověřte, odkud hodnota pochází, a údaje sjednoťte |
| `E_SAME_TRANSCRIBER` | ERROR | Oba soubory uvádějí stejné iniciály (velikost písmen a tečky se nerozlišují) | Dvojí přepis musí pořídit dvě různé osoby. Řádky musí přepsat druhá osoba |
| `E_DUPLICATE_KEY` | ERROR | Klíč se opakuje v jednom ze souborů (porovná se první výskyt) | Odstraňte duplicitu v uvedeném souboru |
| `I_COMPARE_SKIPPED` | INFO | Porovnání neproběhlo, protože některý soubor nejde celý načíst | Opravte chyby souboru (`E_HEADER`, `E_ENCODING`, `E_CSV_SYNTAX`) a spusťte znovu |

Zprávy chyb parsování z `compare` začínají „Soubor A:“ nebo „Soubor B:“.

**Rozdíl se nikdy neřeší „hlasováním“** ani převzetím hodnoty z druhého souboru. Rozhoduje jen originál.

## 8. Pravidlo `CONFIRMED_AS_PRINTED`

Tabulka může obsahovat hodnoty, které si po zaokrouhlení přesně neodpovídají (např. jiný zdroj
odvození nebo zaokrouhlení v originále). Pak platí:

1. Token smíte použít **jen po vlastní kontrole obou buněk v originálním PDF**, nikdy jen proto, aby
   nález zmizel.
2. Připište ho do `note` **všech řádků**, kterých se nález týká (obou), např.
   `CONFIRMED_AS_PRINTED AA 2026-01-31`. Pokud ho má jen jeden řádek, zůstává nález `ERROR`. Token platí
   jen jako samostatné slovo velkými písmeny. Jako součást delšího slova (`NOT_CONFIRMED_AS_PRINTED`,
   `UNCONFIRMED_AS_PRINTED`) se nepočítá. Větu typu „zatím ne CONFIRMED_AS_PRINTED“ ale nástroj nerozpozná,
   proto token do `note` nepište, dokud kontrola neproběhla.
3. Token mění závažnost jen u `E_BASIS_DM_1000`, `E_BASIS_MJ_1000` a `E_BASIS_DM_MJ` (z `ERROR` na
   `WARNING`). Ostatní nálezy neovlivní.
4. Každé `WARNING` s tokenem posoudí specialista při revizi (§10).

## 9. Postup krok za krokem

1. **Kurátor připraví práci:** potvrdí vydání a kontrolní součet PDF (§2), určí A a B, seznam tabulek
   k přepisu a písemně přiřazení sloupců tabulek k `life_stage` a `reference_energy_k`. Oba dostanou
   totéž zadání.
2. **A a B přepisují nezávisle** (§5). Průběžně spouštějí `validate --allow-empty` a opravují chyby.
3. **Odevzdání:** přísné `validate` (bez `--allow-empty`) skončí s 0 chybami. Každé `WARNING` je ověřené
   a komentované v `note`. Soubor jde kurátorovi.
4. **Porovnání:** kurátor spustí `compare`. Každý rozdíl dohledá v originále (sám, nebo s A a B nad
   originálem) a opraví chybný soubor. Opakuje se, dokud `compare` i přísné `validate` obou souborů
   nekončí s 0 chybami.
5. **Archivace:** kurátor uloží oba soubory a protokoly (`--json`) k revizi verze dat. Přepisy se
   neukládají do `data/reference/` (ta obsahuje jen šablony a katalog, viz
   [07](07-django-schema.md) §7.1).

## 10. Předání specialistovi a schválení

Sjednocený přepis se importuje jako nová verze dat `DataVersion` (rozsah `STANDARDS`) a projde stavy
podle [07](07-django-schema.md) §7.6 a [03](03-nutricni-pozadavky.md) §3.5 (body 4 a 5):

`DRAFT` (kurátor importuje) → `IN_REVIEW` (revize specialistou) → `APPROVED` (schvaluje specialista,
role `nutrition_reviewer`).

Do produkčních výpočtů vstupuje jen `APPROVED`. Schválenou verzi nelze měnit. Oprava znamená novou
verzi s poznámkou o změně (`changelog`).

**Kontrolní seznam pro specialistu 🩺**

- [ ] Přísné `validate` obou přepisů a `compare` skončily s 0 chybami (protokoly přiloženy).
- [ ] Prošel jsem všechna `WARNING`: `W_SCALED_PAIR`, `W_NUTRITIONAL_ABOVE_LEGAL`, `W_NEEDS_CONVERSION`,
      `W_SPECIES_NOT_RELEVANT`, `W_PRECISION_DIFFERS`, `W_PROVENANCE_DIFFERS` a nálezy `E_BASIS_*` snížené tokenem
      `CONFIRMED_AS_PRINTED`.
- [ ] Namátkově jsem ověřil buňky proti originálu (rozsah vzorku určím sám, alespoň několik buněk
      z každé tabulky).
- [ ] Přiřazení sloupců tabulek k životním fázím a referenční energii odpovídá originálu.
- [ ] Převody IU pocházejí z přílohy standardu, A i B je přepsali nezávisle a jsou uložené jako
      samostatné ověřené záznamy. Vztah řádků v IU k minimům a maximům v µg/mg jsem ověřil ručně.
- [ ] Přepis je úplný vůči seznamu tabulek a katalogu živin (žádná tabulka ani živina nechybí).
- [ ] Schvaluji verzi dat (`APPROVED`).
