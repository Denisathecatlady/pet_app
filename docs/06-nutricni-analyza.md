# 6. Výpočet živin a porovnání s referenčními hodnotami

> Legenda: ✅ ověřeno (P/S) · 🟡 ověřit v originále · 🛠 pracovní návrh · 🩺 posoudí vet. nutriční specialista.

Tohle je jádro aplikace. Celý modul je **čistý Python bez závislosti na Djangu** (balíček
`nutricalc`). Je deterministický a testovatelný izolovaně (viz [07-django-schema.md](07-django-schema.md), §7.1).

## 6.1 Průběh výpočtu 🛠

```
Vstup (neměnný snapshot)
  ├─ zvíře: druh, BW, fáze, aktivita, kastrace, BCS, zdravotní stavy
  ├─ recept: [(surovina, profil_verze, gramy)]
  ├─ standard: StandardProfile (standard + verze + druh + fáze + ref. energie)
  └─ verze: data_version_ingredients, data_version_standard, engine_version
        │
        ▼
1. Validace vstupů (druh profilu = druh zvířete, jednotky, kladné gramy, duplicity)
2. Bezpečnostní brána (zdravotní stavy, fáze, BCS) → může skončit stavem BLOCKED
3. Energie dávky (ME) z makroživin podle zvolené metody (§6.3)
4. Součty živin s intervaly a stavem úplnosti (§6.5)
5. Přepočty: na den, na 1 000 kcal, na kg BW^n, (na 100 g sušiny informativně)
6. Požadavky: přepočet na skutečný příjem energie (§6.4)
7. Porovnání → stav živiny (§6.6) + spolehlivost
8. Pravidla interakcí a bezpečnostní upozornění (§6.7)
9. Souhrnný stav (konzervativní, §6.6.4)
10. Výstup: RecipeAnalysis + hash vstupů → uložení (neměnné)
```

## 6.2 Jednotky, báze a ochrana před záměnou 🛠

Každé číslo v jádře je typ `Quantity(value: Decimal, unit: Unit, basis: Basis)`:

| `Basis` | Význam |
|---|---|
| `PER_100G_AS_FED` | na 100 g podávané (původní) hmoty |
| `PER_100G_DM` | na 100 g sušiny |
| `PER_DAY` | celkem za den |
| `PER_1000KCAL_ME` | na 1 000 kcal ME |
| `PER_KG_BW075` / `PER_KG_BW067` | na kg metabolické hmotnosti |

- Sčítat a porovnávat lze **jen** veličiny se stejnou jednotkou **i bází**. Jinak vznikne výjimka
  `BasisMismatchError` nebo `UnitMismatchError`. Tím se v kódu znemožní záměna „na 100 g" a „na 1 000 kcal"
  a záměna sušiny s původní hmotou.
- Převody bází jsou jen explicitní funkce:
  - `as_fed → DM`: `x_DM = x_AF / (1 − voda/100)`. Vyžaduje známý obsah vody, jinak `MissingDataError`.
  - `PER_DAY → PER_1000KCAL`: `x_1000 = x_den / (ME_den / 1000)`.
  - `PER_1000KCAL → PER_DAY`: `x_den = x_1000 · ME_den / 1000`.
- **Kanonické jednotky** (uložení): g (makroživiny, aminokyseliny, Ca, P, K, Na, Cl, Mg), mg (Fe, Cu, Zn,
  Mn, I, vitamin E, B-vitaminy kromě B12, folátu a biotinu), µg (Se, vitamin A jako retinol, vitamin D,
  B12, folát, biotin, vitamin K), kcal.
- **Mezinárodní jednotky (IU)** se převádějí při importu podle formy látky. Konvence 1 IU vitaminu A =
  0,3 µg retinolu a 1 IU vitaminu D = 0,025 µg cholekalciferolu jsou běžné. U vitaminu E závisí převod na
  formě (RRR vs. all-rac, ester). Proto 🟡: konvence se převezmou z přílohy použitého standardu a uloží
  jako data (`UnitConversion` se zdrojem). Originální hodnota v IU zůstává uložená.

## 6.3 Metabolizovatelná energie dávky

Energie se nepřebírá z databází pro lidi (USDA uvádí energii podle Atwaterových faktorů pro člověka) 🛠.
ME se počítá z makroživin podle **zvolené a uložené metody**:

| Metoda (kód) | Vzorec | Zdroj | Stav |
|---|---|---|---|
| `NRC2006_DOG_CF` | GE = 5,7·B + 9,4·T + 4,1·(BNLV + V); stravitelnost energie % = 91,2 − 1,43·V_DM%; DE = GE·stravitelnost/100; **ME = DE − 1,04·B** | `[NRC2006]` | ✅ S |
| `NRC2006_DOG_TDF` | stravitelnost % = 96,6 − 0,95·TDF_DM%, ostatní stejně | `[NRC2006]`, doporučeno `[Calvez2019]` | ✅ S |
| `NRC2006_CAT` | analogicky s koeficienty pro kočky | `[NRC2006]` | 🟡 koeficienty neověřeny |
| `MOD_ATWATER` | ME = 3,5·B + 8,5·T + 3,5·BNLV | `[NRC2006]`, AAFCO | 🟡 (obecně známé, ověřit) |

B = bílkoviny, T = tuk, BNLV = bezdusíkaté látky výtažkové, V = hrubá vláknina, TDF = celková vláknina
(vše v g). `[Calvez2019]` ✅ zjistil, že ME psích a kočičích krmiv nejlépe předpovídá rovnice NRC 2006
(varianta s TDF a měřenou GE). Studie ale hodnotila **komerční suchá a vlhká krmiva**. Pro syrové dávky
jde o extrapolaci 🩺.

**Výchozí metoda 🛠 🩺:** `NRC2006_DOG_CF` / `_TDF` pro psy, `NRC2006_CAT` pro kočky po ověření koeficientů.
Modifikované Atwaterovy faktory byly odvozeny pro komerční krmiva. U vysoce stravitelných syrových dávek
mohou ME podhodnotit. Rozdíl ukazuje příklad:

| 100 g suroviny: B = 20 g, T = 10 g, BNLV = 0, V = 0 | ME |
|---|---|
| `NRC2006_DOG_CF` (GE 208,0 → DE 189,696) | **168,90 kcal** |
| `MOD_ATWATER` | **155,0 kcal** |
| Atwater 4/9/4 (jen pro srovnání) | **170,0 kcal** |

Rozdíl kolem 9 % se přímo promítne do „gramů krmiva na den". Metoda se proto vždy zobrazuje u výsledku
a je součástí hashe vstupů.

**Chybějící BNLV:** Pokud zdroj uvádí „sacharidy dopočtem" (USDA *Carbohydrate, by difference*),
použijí se se stavem `CALCULATED`. Pokud chybí popel i sacharidy, ME suroviny je `PARTIAL` (počítá se
jen z B a T) a výsledek energie dostane upozornění.

**Implementace v jádře (`nutricalc.me`) 🛠 🩺:**
- ME **dávky** se počítá z **denních součtů** makroživin celé dávky. Rovnice NRC jsou odvozené pro celé
  krmivo a stravitelnost závisí na podílu vlákniny v sušině celé dávky, proto ME dávky obecně není
  součtem ME surovin. ME jednotlivých surovin se počítá stejnou metodou zvlášť a slouží jen k podílům
  surovin na energii.
- `NRC2006_DOG_TDF`: TDF vstupuje jen do stravitelnosti. GE používá BNLV + hrubou vlákninu jako
  u `NRC2006_DOG_CF` („ostatní stejně"), protože BNLV je definována dopočtem s hrubou vlákninou 🟡.
- Vstupy jsou bodové hodnoty. `BELOW_LOD` a `TRACE` se počítají jako 0 s upozorněním.
- Chybí-li BNLV, dopočte se jako 100 − (voda + B + T + popel + V) na 100 g, pokud jsou všechny složky
  známé (záporný výsledek → 0 s upozorněním). Jinak se BNLV počítá jako 0 a ME je `PARTIAL`.
- Chybí-li vláknina metody, počítá se jako 0 a ME je `PARTIAL`. Chybí-li vláknina pro stravitelnost,
  ME může být nadhodnocená. U `NRC2006_DOG_TDF` bez hrubé vlákniny může být podhodnocená GE.
  Podíl vlákniny v sušině potřebuje obsah vody. Bez něj (při vláknině > 0) je ME neznámá.
- Chybí-li B nebo T u kterékoli suroviny, ME dávky je **neznámá** (`UNKNOWN`), nikdy se nedopočítává
  nulou.
- `NRC2006_CAT` jádro odmítne (`UnsupportedMethodError`), dokud nebudou koeficienty ověřené.
  Metody `NRC2006_DOG_*` u kočky vyhodí `SpeciesMismatchError`.

## 6.4 Přepočet požadavků na skutečné zvíře 🛠 🩺

Standardy na 1 000 kcal předpokládají referenční příjem (pes 110 nebo 95 kcal/kg^0,75, kočka 100 nebo
75 kcal/kg^0,67) ✅. Zvíře s nižším příjmem energie potřebuje živiny ve vyšší koncentraci.

1. Skutečný koeficient zvířete: `k_skut = DER / BW^n`.
2. Návrh výběru sloupce a přepočtu (konzervativní):
   - `k_skut ≥ 110` (pes) → sloupec 110, bez snížení požadavků,
   - `95 ≤ k_skut < 110` → sloupec 95,
   - `k_skut < 95` → sloupec 95 × (95 / k_skut).
   Pro kočky totéž s hodnotami 100 a 75.
3. Denní požadavek: `req_den = req_1000 · DER / 1000`.

🩺 Specialista potvrdí, pro které živiny je lineární přepočet přes metabolickou hmotnost správný.
U maxim se požadavek **nepřepočítává směrem nahoru**: maxima zůstávají na 1 000 kcal beze změny.

## 6.5 Součty živin, chybějící data a nejistota 🛠

Pro živinu *n* a suroviny *i* s množstvím *g_i* (g, as fed) a hodnotou *v_i* (na 100 g as fed):

$$c_i = \frac{g_i}{100} \cdot v_i \qquad T_n = \sum_i c_i$$

### 6.5.1 Stavy hodnot suroviny

| `value_kind` | Interval [lo, hi] příspěvku |
|---|---|
| `MEASURED`, `CALCULATED`, `BORROWED`, `IMPUTED` | [min, max], pokud je zdroj uvádí, jinak [v, v] |
| `BELOW_LOD` | [0, LOD]. Bez LOD jako `MISSING` |
| `TRACE` | [0, LOD], pokud je LOD známé, jinak jako `MISSING` pro horní mez |
| `ZERO_BY_DEFINITION` | [0, 0] |
| `MISSING` | **neznámo**, nikdy 0 |

### 6.5.2 Stav úplnosti součtu

| Stav | Podmínka | Hodnota |
|---|---|---|
| `COMPLETE` | žádná surovina s g > 0 nemá `MISSING` | T, interval [Σlo, Σhi] |
| `PARTIAL` | některé suroviny mají `MISSING` | **dolní mez** Σlo přes známé. Horní mez neznámá. Uvádí se podíl hmotnosti a energie dávky bez údaje |
| `UNKNOWN` | žádná přispívající surovina nemá údaj | „Nelze vyhodnotit – chybí data" |

Intervaly se sčítají jako **nejhorší případ** (Σlo, Σhi). Je to konzervativní a deterministické.
Statistické šíření nejistoty (např. přes SD) přidám až po konzultaci, protože vyžaduje předpoklad
nezávislosti chyb. 🛠

## 6.6 Porovnání a stavy živin 🛠

### 6.6.1 Stavy

| Stav | Podmínka (porovnává se **nezaokrouhlená** hodnota) | Text v UI |
|---|---|---|
| `BELOW_MIN` | `COMPLETE` a hi < min | Pod minimem (standard X) |
| `BORDERLINE_MIN` | `COMPLETE` a lo < min ≤ hi | Na hranici minima (v rozsahu nejistoty) |
| `ADEQUATE` | `COMPLETE`, lo ≥ min a (žádné max nebo hi ≤ max) | V rozmezí standardu |
| `MIN_MET_PARTIAL` | `PARTIAL` a dolní mez ≥ min | Minimum splněno i bez chybějících dat. Maximum nelze ověřit |
| `ABOVE_MAX` | lo > max (platí i pro `PARTIAL`) | Překročeno nutriční maximum |
| `BORDERLINE_MAX` | `COMPLETE` a lo ≤ max < hi | Na hranici maxima |
| `ABOVE_LEGAL_MAX_INFO` | překročeno jen zákonné maximum EU pro krmiva | Informativně: nad zákonným limitem pro komerční krmiva |
| `ABOVE_SUL` | (NRC) lo > SUL | Nad bezpečným horním limitem |
| `NOT_EVALUABLE` | `UNKNOWN`, nebo `PARTIAL` s dolní mezí < min | **Nelze vyhodnotit – chybí data** |
| `NO_REFERENCE` | standard pro druh a fázi hodnotu nestanovuje | Standard nestanovuje |

### 6.6.2 Procento pokrytí
- Jen pro požadavky typu minimum (`MIN_RECOMMENDED`, `RA`, `AI`, `MR`): `pokrytí = T_1000 / req_1000 · 100 %`.
- U maxima se zobrazuje „% maxima". Nikdy se nespojuje do jednoho procenta s minimem.
- **Pravidlo zaokrouhlení zobrazení:** když je skutečná hodnota < 100 % a po zaokrouhlení by vyšla
  „100 %", zobrazí se „< 100 %". Zaokrouhlení nesmí změnit stav (pokryto testem).

### 6.6.3 Poměr Ca:P
`Ca:P = T_Ca / T_P` (hmotnostní poměr). Počítá se jen tehdy, když jsou Ca i P `COMPLETE`.
Interval: [Ca_lo / P_hi, Ca_hi / P_lo]. Porovnává se s minimem a maximem poměru ve standardu
(dospělý pes max. 2:1 ✅ `[FEDIAF2025]`).

### 6.6.4 Souhrnný stav dávky (konzervativní)
1. `BLOCKED`, pokud zasáhla bezpečnostní brána.
2. Jinak, pokud některá **povinná** živina profilu je `NOT_EVALUABLE` → „**Neúplné vyhodnocení**
   (vyhodnoceno X z Y)". Žádná zelená.
3. Jinak, pokud existuje `BELOW_MIN`, `ABOVE_MAX` nebo `ABOVE_SUL` → „Nalezeny nedostatky nebo nadbytky".
4. Jinak, pokud existuje `BORDERLINE_*` → „Na hranici – doporučena kontrola".
5. Jinak → „Všechny vyhodnocené požadavky standardu X (verze, druh, fáze) jsou splněny".
   **Tato věta neříká, že dávka je bezpečná nebo kompletní.** Pod ní se vždy zobrazí trvalé upozornění
   na mikrobiologická rizika a omezení dat.

### 6.6.5 Spolehlivost výsledku živiny
Spolehlivost = **nejhorší** `quality_grade` mezi surovinami, které přispívají ≥ 5 % k horní mezi součtu
(práh 🛠 🩺). Zobrazuje se jako A–D s vysvětlením. Spolehlivost se nikdy neprolíná s barvou stavu.

## 6.7 Interakce, dostupnost a bezpečnostní pravidla

Pravidla jsou **data** (`WarningRule`: podmínka, závažnost, text, zdroj). Obsah živiny ≠ biologická
dostupnost. Aplikace to uvádí obecně a u známých interakcí konkrétně:

| Pravidlo | Spouštěč (návrh) | Závažnost | Zdroj | Stav |
|---|---|---|---|---|
| Poměr Ca:P mimo rozsah | §6.6.3 | Nutriční varování | `[FEDIAF2025]` | ✅ |
| Vysoký podíl jater → vitamin A | `LIVER` > práh nebo vitamin A u horní meze | Nutriční varování | `[Polizopoulou2005]` | ✅ (práh 🩺) |
| Tkáň štítné žlázy | surovina s `THYROID_TISSUE` | Vyžaduje posouzení | `[Broome2015]`, `[Kohler2012]` | ✅ |
| Kosti → poranění, obstrukce | `MEATY_BONE` / `BONE` v dávce | Informativní / varování (malí psi < 10 kg) | `[Gianella2009]` | ✅ |
| PUFA ↔ vitamin E | vysoký podíl ryb nebo rybího oleje | Nutriční varování | `[Niza2003]`, AAFCO | 🟡 |
| Thiamináza (syrové ryby) | `THIAMINASE` u kočky | Nutriční varování | sekundární | 🟡 |
| Syrový vaječný bílek → biotin | `RAW_EGG_WHITE` nad práh | Informativní | `[NRC2006]` | 🟡 |
| Vysoký Ca ↔ dostupnost Zn, antagonismus Zn ↔ Cu | poměry nad práh | Informativní | `[NRC2006]` | 🟡 |
| β-karoten není zdroj vitaminu A pro kočky | kočka a rostlinné složky | Informativní | `[NRC2006]` | 🟡 |
| Pro druh toxická surovina | `TOXIC_FOR_SPECIES` | **Automatický výpočet nelze doporučit** | `[Wilson2019]` (česnek, cibule) | ✅ |
| Syrová strava obecně | vždy | Informativní, trvale | `[vanBree2018]`, `[Davies2019]` | ✅ |

## 6.8 Návrh dávky a optimalizace (Fáze 5) 🛠

- **Model:** lineární programování (knihovna HiGHS přes `scipy.optimize.linprog`). Proměnné = gramy
  povolených surovin.
- **Omezení:** energie v pásmu DER ± x %; každé minimum (přepočtené, §6.4) ≤ součet ≤ maximum;
  Ca:P linearizovaně (`Ca − r_min·P ≥ 0`, `Ca − r_max·P ≤ 0`); meze surovin (min/max g, max. podíl jater,
  max. podíl kostí); doplňky **jen ty, které uživatel výslovně povolil**, s maximální dávkou.
- **Cíl:** minimalizovat vážené odchylky od cílových hodnot (elastické proměnné) a změnu oproti výchozímu
  receptu uživatele.
- **Do optimalizace vstupují jen živiny `COMPLETE`** pro všechny kandidátní suroviny. Ostatní se
  vypíšou jako „neoptimalizováno – chybí data".
- **Neřešitelnost:** pokud řešení neexistuje, systém to **přizná**. Pomocí elastických proměnných
  ukáže, která omezení nelze splnit (např. „s těmito surovinami nelze dosáhnout minima Zn bez doplňku").
  Nikdy nevrátí „nejlepší dostupné" řešení jako vyhovující.
- **Ověření:** výsledek se zaokrouhlí na praktické gramy a **znovu projde celým analytickým modulem**.
  Uloží se jen výsledek této druhé analýzy.
- **Determinismus:** stejný solver, verze a tolerance. Při více optimálních řešeních rozhoduje pevné
  pořadí proměnných (seřazené podle `uuid`).
- Optimalizace je **vypnutá** pro stavy `EXPERT_REQUIRED` a `BLOCKED`.

## 6.9 Rozhraní funkce analýzy 🛠

```text
analyze_recipe(snapshot: AnalysisInput) -> AnalysisResult

AnalysisInput (neměnný, serializovatelný; z něj se počítá SHA-256 hash):
  animal: AnimalSnapshot
  items: list[RecipeItem(ingredient_uuid, profile_version_id, grams: Decimal)]
  standard_profile_id, data_versions{ingredients, standards, energy}, me_method, engine_version

AnalysisResult:
  energy: EnergyResult (ME dávky, DER zvířete, odchylka %)
  nutrients: list[NutrientResult(code, total_day, per_1000kcal, interval, completeness,
                                 missing_mass_share, requirement, requirement_type, coverage_pct,
                                 status, confidence, contributors[top 3])]
  ratios: list[RatioResult]          # Ca:P
  warnings: list[Warning(level, rule_code, message, source_key)]
  summary: SummaryStatus, evaluated_count, required_count
  input_hash, engine_version, data_versions, computed_at

Chyby (výjimky, ne výsledek):
  ValidationError        – záporné nebo nulové gramy, neexistující surovina, nepovolená verze
  SpeciesMismatchError   – profil standardu pro jiný druh nebo fázi
  BasisMismatchError / UnitMismatchError – programátorská chyba (zachytí testy)
  DuplicateItemError     – stejná surovina dvakrát (místo sloučení musí rozhodnout uživatel)
Stavy (součást výsledku, ne výjimky): BLOCKED, EXPERT_REQUIRED, NOT_EVALUABLE…
```

## 6.10 Ilustrační výpočet se **syntetickými daty**

> Suroviny SYN_A a SYN_B jsou **smyšlené testovací fixtury**, nejde o reálné suroviny ani reálné hodnoty.

| Surovina | Gramy | B | T | P (g/100 g) | Ca (g/100 g) |
|---|---|---|---|---|---|
| SYN_A | 300 | 20 | 10 | 0,200 | `MISSING` |
| SYN_B (minerální) | 50 | 0 | 0 | 5,0 | 10,0 |

- ME (NRC pes): SYN_A 168,896 kcal/100 g × 3 = **506,688 kcal**. SYN_B 0 kcal.
- P: 0,6 + 2,5 = **3,1 g/den** → 3,1 / 0,506688 = **6,118 g / 1 000 kcal** (`COMPLETE`).
- Ca: dolní mez 5,0 g, ale SYN_A nemá údaj → `PARTIAL`. Na SYN_A připadá **85,7 % hmotnosti** dávky
  bez údaje. **Ca:P nelze vyhodnotit.**
- Varianta: SYN_A má Ca `BELOW_LOD` s LOD 0,005 g/100 g → Ca ∈ [5,000; 5,015] g → `COMPLETE`.
  Ca:P ∈ [1,613; 1,618].

Tento příklad je v testovacím plánu jako referenční test chybějících dat (viz
[11-testovaci-plan.md](11-testovaci-plan.md)).
