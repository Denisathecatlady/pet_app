# 11. Testovací a validační plán

> Kapitola je 🛠 pracovní návrh. Referenční příklady v §11.3 schvaluje 🩺 specialista.

## 11.1 Úrovně testů

| Úroveň | Nástroj | Co ověřuje | Kdy běží |
|---|---|---|---|
| Jednotkové testy jádra | `pytest` | Každá funkce `nutricalc` zvlášť | Každý commit (CI) |
| Vlastnostní (property-based) testy | `hypothesis` | Invarianty (linearita, nezávislost na pořadí…) | Každý commit |
| Referenční (golden) testy | `pytest` + JSON fixtury | Ručně ověřené příklady, bitová shoda výsledku | Každý commit. Změna = review |
| Testy importu dat | `pytest` | Kontroly konzistence tabulek standardů (§3.5) | Při každém importu a v CI |
| Integrační testy Django | `pytest-django` | Modely, omezení DB, služby, oprávnění, API | Každý commit |
| Testy UI | Playwright | Klíčové toky (zvíře → recept → rozbor → PDF), přístupnost (axe) | Před vydáním |
| Odborná validace | specialista | Výsledky na reálných dávkách vs. vlastní výpočet nebo software specialisty | Před každým vydáním, které mění data nebo logiku |

Cílové pokrytí jádra: 100 % řádků a větví v `units`, `composition`, `evaluation` (vynuceno v CI).

## 11.2 Katalog testů podle oblastí

### Jednotky a převody
- `Quantity` se stejnou jednotkou a bází se sčítá. Jiná báze vyhodí `BasisMismatchError`, jiná jednotka
  `UnitMismatchError`.
- g ↔ mg ↔ µg, kcal ↔ kJ (4,184), IU → µg podle `UnitConversion` (z dat, ne z kódu).
- as fed → sušina: 25 g/100 g při 75 % vody = 100 g/100 g DM. Bez vody vyhodí `MissingDataError`.
- Den ↔ 1 000 kcal: 3,1 g/den při 506,688 kcal = 6,118 g/1 000 kcal (příklad z §6.10).
- **Statická kontrola:** v balíčku `nutricalc` se nesmí objevit `float(` ani literál s desetinnou
  tečkou mimo `Decimal("…")` (vlastní lint pravidlo plus test, který prochází AST).

### Energie
- Kontrolní příklady z [05](05-energeticky-model.md) §5.8 (RER 10 kg = 393,64; pes 20 kg k = 110 =
  1 040,32; kočka 4 kg k = 100 = 253,15; štěně; kotě) s tolerancí 1e-6.
- Monotonie: MER roste s BW. `k` pro kočku se nesmí použít u psa (`SpeciesMismatch`).
- Růst, březost a laktace v MVP vrátí `BLOCKED` (ne výjimku, ne číslo).
- BW ≤ 0, BCS mimo 1–9 a nevěrohodná hmotnost druhu vrátí `InvalidInput`.

### ME dávky
- `NRC2006_DOG_CF` pro B = 20, T = 10: GE 208,0, DE 189,696, **ME 168,896**.
- `MOD_ATWATER` pro stejný vstup: 155,0. Metoda je součástí hashe (jiná metoda = jiný hash).

### Součty živin z více surovin
- Linearita: zdvojnásobení všech gramů zdvojnásobí denní součty. Hodnoty na 1 000 kcal se nezmění
  (property test).
- Nezávislost na pořadí: permutace položek dá stejný výsledek i stejný hash (property test).
- Aditivita: rozbor (A + B) = rozbor A + rozbor B pro denní součty.

### Ca:P
- Ca 5,0 g a P 3,1 g → 1,6129…
- P = 0 → výsledek „nelze vyhodnotit" (ne dělení nulou ani nekonečno).
- Ca `PARTIAL` → poměr se nepočítá.
- Interval: [Ca_lo / P_hi, Ca_hi / P_lo] (příklad §6.10: [1,613; 1,618]).

### Nedostatky a nadbytky
- Hranice: hodnota = min → `ADEQUATE`, min − 1e-9 → `BELOW_MIN`.
- Interval přes hranici → `BORDERLINE_*`.
- Nad zákonným, ale pod nutričním maximem → `ABOVE_LEGAL_MAX_INFO` (ne „porušení").
- **Záměna minima a cíle:** požadavek typu `NUTRITIONAL_MAX` se nikdy nevyhodnotí jako minimum
  (parametrizovaný test přes všechny `RequirementType`).

### Chybějící data
- `MISSING` není 0: surovina bez údaje → `PARTIAL` nebo `NOT_EVALUABLE`, nikdy `BELOW_MIN` s hodnotou 0.
- `PARTIAL` s dolní mezí ≥ min → `MIN_MET_PARTIAL`. Dolní mez > max → `ABOVE_MAX`.
- `BELOW_LOD` s LOD → interval [0, LOD]. Bez LOD se chová jako `MISSING` pro horní mez.
- Souhrn: jediná povinná živina `NOT_EVALUABLE` → souhrn „Neúplné vyhodnocení", nikdy „splněno".
- Referenční příklad SYN_A / SYN_B (§6.10): podíl hmotnosti bez údaje 85,7 %.

### Zaokrouhlování
- Porovnání probíhá nad nezaokrouhlenou hodnotou (99,96 % → stav `BELOW_MIN`, zobrazení „< 100 %").
- Zobrazení podle `Nutrient.display_decimals`, `ROUND_HALF_EVEN`. Uložená data mají plnou přesnost.

### Druhově specifické testy
- Kočka bez dat o taurinu → souhrn nikdy „splněno".
- Profil standardu pro psa nelze přiřadit kočce (DB omezení i validace služby).
- β-karoten se nezapočítává do vitaminu A (u koček vždy, u psů podle schváleného pravidla).
- Surovina `TOXIC_FOR_SPECIES` u daného druhu → `BLOCKED`.

### Životní fáze
- Volba sloupce 95 / 110 a přepočet pod 95 (§6.4): pro `k_skut` = 120, 100 a 80 je výsledkem sloupec
  110 bez změny, sloupec 95 bez změny a sloupec 95 × 95/80.
- Maxima se nepřepočítávají.
- Zvíře mladší, než stanoví pravidlo pro dospělost → dospělý profil nelze použít.

### Ochrana před typickými chybami (zadání bod 13)

| Chyba | Test |
|---|---|
| Smíchání hodnot na 100 g a na 1 000 kcal | `BasisMismatchError` (jednotkový + property test) |
| Smíchání sušiny a původní hmoty | dtto. Import odmítne hodnotu bez `original_basis` |
| Dvojí započítání kosti nebo doplňku | `UniqueConstraint` (integrační), `DuplicateItemError` (jádro), varování v editoru |
| Záměna jednotek | `UnitMismatchError`. Import kontroluje kanonickou jednotku živiny |
| Nekompletní data jako kompletní | testy chybějících dat (výše) |
| Záměna minima a cílové hodnoty | parametrizovaný test `RequirementType` |
| Doporučení pro jiný druh nebo fázi | `SpeciesMismatchError`, testy fází |

### Reprodukovatelnost
- Stejný snapshot → stejný `result_hash` (opakovaně, na jiném stroji v CI matrixu, Linux i macOS).
- Změna verze dat → nový hash. Starý rozbor `verify_analysis` stále reprodukuje.
- Snapshot je kompletní: jádro spuštěné bez databáze (mock, který vyhodí výjimku při přístupu) projde.

## 11.3 Referenční (golden) příklady 🩺

1. **Syntetické** (bez reálných dat, testují mechaniku): SYN_A/SYN_B (§6.10), příklady energie (§5.8).
2. **Reálné dávky** (po importu schválených dat): 5–10 dávek pro dospělého psa (malý, střední, velký,
   nízká a vysoká aktivita, s kostí i bez kosti, s rybou a s játry). Pro každou:
   - nezávislý výpočet specialistou (vlastní software nebo tabulkový kalkulátor),
   - dohodnutá tolerance (např. ≤ 1 % u součtů, kde se shodují vstupní data),
   - **zdokumentování každé odchylky**: rozdílná data, metoda ME, zaokrouhlení.
3. Golden fixtury jsou verzované. Změna očekávaného výsledku vyžaduje schválení v pull requestu (CODEOWNERS:
   role `nutrition_reviewer`).

## 11.4 Odborná validace 🩺

- Validační protokol: rozsah (druh, fáze, živiny), data a verze, příklady, tolerance, výsledky, podpis
  a datum.
- Validace je podmínkou pro přepnutí `DataVersion` do `APPROVED` a pro vydání verze jádra, která mění
  výsledky.
- Seznam známých omezení (`docs/omezeni.md`) se po každé validaci aktualizuje.
