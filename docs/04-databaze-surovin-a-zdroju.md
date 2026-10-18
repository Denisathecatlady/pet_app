# 4. Návrh databáze surovin a odborných zdrojů

> Legenda: ✅ ověřeno · 🟡 ověřit v originále · 🛠 pracovní návrh · 🩺 posoudí vet. nutriční specialista.

## 4.1 Principy 🛠

1. **Surovina ≠ složení.** `Ingredient` popisuje *co* to je (druh, anatomická část, stav). Složení je
   v samostatném, **verzovaném** `IngredientProfile`. Jedna surovina může mít více profilů z různých
   zdrojů (USDA, vlastní laboratorní rozbor, prohlášení výrobce). V každém rozboru je profil pevně daný.
2. **Granularita podle anatomie.** „Kuře" není surovina. Suroviny jsou například:
   *kuřecí prsní svalovina bez kůže, syrová*, *kuřecí krk s kůží a kostí, syrový*, *kuřecí srdce, syrové*.
   Svalovina bez kosti, maso s kostí a samotná kost jsou **tři různé položky**. Hodnoty se mezi nimi
   nepřenášejí.
3. **Jedlý podíl.** Hodnoty se vždy vztahují k **100 g podávané hmoty** (as fed) v daném stavu.
   U masa s kostí podávaného celé to znamená včetně kosti. Pokud zdroj udává hodnoty jen pro jedlý podíl
   bez kosti (běžné v databázích pro lidi), **nelze ho použít pro surovinu s kostí** bez explicitní
   a zdokumentované kombinace (§4.5).
4. **Původ každé hodnoty.** Každá hodnota má zdroj, typ původu, kvalitu a případně rozsah.
5. **Prázdné ≠ nula.** Rozlišujeme: *změřeno*, *pod mezí detekce*, *nula z definice* (např. vláknina
   ve svalovině 🩺) a *chybí*.

## 4.2 Kategorie surovin 🛠

| Kód | Kategorie | Příklady | Specifické atributy | Bezpečnostní příznaky |
|---|---|---|---|---|
| `MUSCLE` | Svalovina | hovězí kližka, krůtí prsa, králičí stehno bez kosti | % tuku (variabilní) | – |
| `HEART` | Srdce | hovězí, kuřecí, krůtí srdce | – | – |
| `LIVER` | Játra | hovězí, kuřecí, vepřová játra | – | `HIGH_VIT_A`, `HIGH_CU` (hovězí) |
| `OTHER_ORGAN` | Ledviny, slezina, mozek, varlata… | | | – |
| `MEATY_BONE` | Maso s kostí | kuřecí krk, křídlo, kachní krk | **podíl kosti %** a zdroj | `BONE_RISK` `[Gianella2009]` ✅ |
| `BONE` | Kost samotná | | | `BONE_RISK` |
| `THYROID_RISK` (příznak) | Jícny, hrtany, krční maso | hovězí jícen | – | `THYROID_TISSUE` `[Broome2015]`, `[Kohler2012]` ✅ |
| `FAT` | Tuk, lůj | hovězí lůj, kuřecí kůže | profil mastných kyselin | – |
| `FISH` | Ryby a mořské suroviny | losos, sardinka, makrela | druh ryby | `THIAMINASE` (podle druhu 🟡), `HIGH_PUFA` |
| `EGG` | Vejce | celé vejce, žloutek | syrové/vařené | `RAW_EGG_WHITE` (avidin) 🟡 |
| `PLANT` | Rostlinné složky | dýně, mrkev | stav úpravy | `TOXIC_FOR_SPECIES` (cibule, česnek, pórek u koček `[Wilson2019]` ✅) |
| `OIL` | Oleje | rybí olej, olej z tresčích jater | – | `HIGH_VIT_A_D` (tresčí játra 🟡) |
| `SUPPLEMENT` | Doplňky | uhličitan vápenatý, vaječné skořápky, jodidová sůl, vitaminové premixy | deklarované složení, max. dávka | `REQUIRES_DOSING_LIMIT` |

## 4.3 Atributy suroviny (`Ingredient`) 🛠

| Atribut | Typ | Povinný | Poznámka |
|---|---|---|---|
| `uuid`, `code` | UUID, slug | ano | Neměnný identifikátor, např. `chicken-neck-skin-bone-raw` |
| `name_cs`, `name_en` | text | ano | |
| `animal_species` | číselník | ano (u živočišných) | kuře, krůta, skot, prase, jehně, králík, kachna, losos… |
| `anatomical_part` | číselník | ano | svalovina stehna, krk, srdce, játra… |
| `category` | výčet (§4.2) | ano | |
| `preparation_state` | výčet | ano | `RAW`, `FROZEN_RAW`, `COOKED_BOILED`, `COOKED_ROASTED`, `DRIED`, `FREEZE_DRIED`, `CANNED` |
| `contains_bone`, `bone_fraction_pct` (+ zdroj, rozsah) | bool, Decimal | ano / podmíněně | Bez zdroje se podíl kosti neuvádí. Pole zůstane prázdné a výsledek Ca/P bude „nelze vyhodnotit" |
| `skin_included` | bool | podmíněně | |
| `safety_flags` | seznam příznaků | ne | Vyvolávají upozornění v rozboru |
| `allergen_tags` | seznam | ne | Pro filtrování podle alergií zvířete |
| `default_profile` | FK → `IngredientProfile` | ne | Schválený profil použitý jako výchozí |
| `is_supplement` | bool | ano | Doplněk má navíc `Supplement` (dávkování) |

## 4.4 Hodnota živiny (`IngredientNutrientValue`) 🛠

| Atribut | Popis |
|---|---|
| `profile` | FK na verzovaný profil |
| `nutrient` | FK na `Nutrient` (kanonická jednotka) |
| `value` | Decimal, **na 100 g podávané hmoty (as fed)** v kanonické jednotce. `NULL` = chybí |
| `value_kind` | `MEASURED` · `CALCULATED` (např. součet mastných kyselin) · `BORROWED` (převzato z podobné suroviny, s odkazem) · `IMPUTED` (odhad) · `BELOW_LOD` (pod mezí detekce, s hodnotou LOD) · `TRACE` · `ZERO_BY_DEFINITION` · `MISSING` |
| `min`, `max`, `sd`, `n` | Rozsah nebo variabilita, pokud ji zdroj uvádí |
| `original_value`, `original_unit`, `original_basis` | Pro audit převodů (např. původně na 100 g sušiny, v IU, na jedlý podíl) |
| `source` | FK na `ScientificSource` |
| `source_record` | ID záznamu ve zdroji (např. FDC ID + číslo živiny) |
| `method` | Analytická metoda, pokud je známá |
| `quality_grade` | `A` = vlastní akreditovaný rozbor nebo Foundation Foods s metadaty · `B` = recenzovaná databáze (SR Legacy, CIQUAL, ČR) · `C` = převzato z podobné suroviny, deklarace výrobce · `D` = odhad |
| `note` | |

**Pravidlo převzetí (`BORROWED`) 🛠 🩺:** Převzít lze jen v rámci stejného druhu zvířete, stejné kategorie a
stejného stavu úpravy (např. jód z „hovězí svalovina, obecně" pro „hovězí kližku"). Převzetí snižuje
kvalitu na nejvýše `C` a ve výsledku se zobrazí. Mezi kategoriemi se nepřebírá nikdy (svalovina → maso
s kostí ne).

## 4.5 Maso s kostí: kritická datová mezera ✅ / 🛠

Databáze pro lidi typicky uvádějí složení **jedlé části bez kosti**. U BARF je přitom kost hlavním
zdrojem Ca a P. 🛠 Proto:

1. Preferovaný zdroj je **laboratorní rozbor celé suroviny** (mletá i s kostí), případně publikovaná
   analytická data 🟡 (zdroj zatím nenalezen, viz [zdroje.md](zdroje.md) §7).
2. Přípustná alternativa je **výpočetní kombinace** „jedlý podíl + kost" s hmotnostním podílem kosti
   ze zdroje. Výsledný profil má `value_kind = CALCULATED`, kvalitu nejvýše `C` a dokumentovaný vzorec.
   🩺 Specialista musí schválit zdroj složení kosti.
3. Bez kterékoli z těchto možností má surovina **u Ca a P stav MISSING**. Rozbor pak u Ca, P a Ca:P
   ukáže „nelze vyhodnotit". Žádný odhad „cca 10 % kosti" se nepoužije.

## 4.6 Doplňky (`Supplement`) 🛠

- Složení se bere z **deklarace výrobce** (kvalita `C`), u čistých chemických látek ze **stechiometrie**.
  Například uhličitan vápenatý obsahuje 40,04 % Ca hmotnostně (40,078 / 100,086 g/mol; vlastní výpočet
  z atomových hmotností). Obsah Ca ve vaječných skořápkách je proměnlivý, proto potřebuje zdroj s rozsahem.
- Povinné atributy: forma látky (např. cholekalciferol, retinyl-acetát, jodičnan draselný), jednotka
  dávky, **maximální denní dávka na kg** (pokud ji výrobce nebo zdroj uvádí) a příznak `requires_vet`.
- Doplňky **nesmí přidávat optimalizátor sám od sebe**. Uživatel je musí výslovně povolit (viz [06](06-nutricni-analyza.md), §6.8).

## 4.7 Externí zdroje dat o složení

| Zdroj | Pokrytí | Vhodnost pro BARF | Omezení | Stav |
|---|---|---|---|---|
| `[USDA-FDC]` **Foundation Foods** | Základní potraviny, rozsáhlá metadata (vzorkování, metody), aktualizace v dubnu a říjnu | **Vysoká** pro svalovinu a orgány, kvalita A–B | Malý počet položek, chybí maso s kostí | ✅ |
| `[USDA-FDC]` **SR Legacy** | Široké pokrytí včetně orgánů a ryb | Vysoká, kvalita B | Uzavřený dataset (2018), u části živin chybí data | ✅ |
| `[USDA-FDC]` Branded, FNDDS | Značkové výrobky, recepty pro lidi | **Nevhodné** | – | ✅ |
| `[CIQUAL]` | Francouzské potraviny | Doplňková, kvalita B | Licenci ověřit | 🟡 |
| `[NutriDB-CZ]` | Potraviny na českém trhu | Doplňková (lokální suroviny) | Podmínky užití ověřit | 🟡 |
| Vlastní laboratorní rozbory | Libovolné, včetně masa s kostí | **Nejvyšší** (kvalita A) | Náklady, nutné akreditované metody | 🛠 |

**Import 🛠:** Pro každý zdroj vznikne samostatný importér (adaptér), který mapuje identifikátory
živin zdroje na naše kódy (`Nutrient.external_codes`, např. čísla živin FDC nebo tagy INFOODS 🟡),
převede jednotky a uloží originál. Import vytvoří **nový** `DataVersion` ve stavu `DRAFT`. Nic se
nepřepisuje.

## 4.8 Registr zdrojů (`ScientificSource`) 🛠

Struktura odpovídá požadavku zadání (bod 3) a tabulkám v [zdroje.md](zdroje.md):

| Pole | Popis |
|---|---|
| `citation_key` | např. `FEDIAF2025` |
| `title`, `authors_or_org`, `year`, `doi`, `url` | |
| `source_type` | `GUIDELINE`, `MONOGRAPH`, `META_ANALYSIS`, `REVIEW`, `ORIGINAL_STUDY`, `CASE_REPORT`, `FOOD_DATABASE`, `LAB_ANALYSIS`, `MANUFACTURER_DECLARATION`, `SECONDARY` |
| `evidence_level` | L1–L6 ([zdroje.md](zdroje.md)) |
| `species` | pes / kočka / obojí / neuvedeno |
| `life_stages` | seznam fází, pro které jsou údaje relevantní |
| `units_and_conditions` | např. „na 1 000 kcal ME, referenční MER 110 kcal/kg^0,75, předpoklad 4 000 kcal/kg DM" |
| `edition_version` | např. „2025 (září 2025)" |
| `last_verified_at`, `verified_by` | |
| `verification_level` | B / A / P / S / – |
| `limitations` | text |

## 4.9 Úvodní rozsah databáze pro MVP 🛠 🩺

Cíl je 20–30 surovin, u kterých lze doložit kompletní nebo téměř kompletní data. Jde o ověřitelnost,
ne o šíři: hovězí, kuřecí a krůtí svalovina (2–3 tučnosti), srdce (hovězí, kuřecí), játra (hovězí,
kuřecí), ledviny (hovězí), celé vejce, losos, sardinka, lůj, rybí olej, uhličitan vápenatý,
1–2 vitaminově-minerální premixy s deklarací. Maso s kostí se do MVP zařadí **jen pokud** bude k dispozici
zdroj složení (§4.5).

🩺 Specialista schválí výběr surovin, přiřazené zdroje a pravidla pro převzetí hodnot.
