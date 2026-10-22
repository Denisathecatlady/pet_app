# 3. Nutriční požadavky psů a koček podle životních fází

> Legenda: ✅ ověřeno · 🟡 ověřit v originále · 🛠 pracovní návrh · 🩺 posoudí vet. nutriční specialista.
> Klíče zdrojů viz [zdroje.md](zdroje.md).

## 3.0 Proč tu nejsou kompletní číselné tabulky

Zadání zakazuje vymýšlet nutriční hodnoty. Originál `[FEDIAF2025]` nebyl z vývojového prostředí dostupný
(blokovaná doména). Z paměti by šlo „doplnit" stovky buněk tabulek, ale riziko chybného přepisu je u
takového objemu nepřijatelné. Tento dokument proto obsahuje:

1. **úplný seznam živin a životních fází**, které aplikace musí pokrýt (struktura požadavků),
2. **několik ověřených hodnot** (s vyznačenou úrovní ověření),
3. **kontrolovaný postup importu** číselných tabulek z originálu, včetně automatických kontrol, které
   chyby přepisu zachytí.

Číselné hodnoty se doplní v Fázi 2 z originálního PDF dvojím nezávislým přepisem (§3.5).

## 3.1 Životní fáze (klíče profilů)

| Druh | Fáze (klíč) | Referenční energie | Zdroj | Stav | V MVP |
|---|---|---|---|---|---|
| Pes | `ADULT_MAINTENANCE` | 110 kcal ME/kg BW^0,75 | `[FEDIAF2025]` | ✅ | **ano** |
| Pes | `ADULT_MAINTENANCE_LOW` | 95 kcal ME/kg BW^0,75 (zvířata s nízkou potřebou energie) | `[FEDIAF2025]` | ✅ | **ano** |
| Pes | `EARLY_GROWTH_REPRO` | časný růst (< 14 týdnů), březost, laktace | `[FEDIAF2025]` | 🟡 (hranice 14 týdnů jen sekundárně) | ne, blokováno |
| Pes | `LATE_GROWTH` | pozdní růst (≥ 14 týdnů). U velkých plemen platí zvláštní limity Ca | `[FEDIAF2025]`, `[AAFCO2014]` | 🟡 / ✅ (1,8 % DM) | ne, blokováno |
| Kočka | `ADULT_MAINTENANCE` | 100 kcal ME/kg BW^0,67 | `[FEDIAF2025]` | ✅ | ve verzi MVP-1 |
| Kočka | `ADULT_MAINTENANCE_LOW` | 75 kcal ME/kg BW^0,67 (kastrované a indoor kočky, přiřazení ověřit) | `[FEDIAF2025]` | ✅ hodnota / 🟡 přiřazení | ve verzi MVP-1 |
| Kočka | `GROWTH_REPRO` | růst a reprodukce | `[FEDIAF2025]` | 🟡 (členění ověřit) | ne, blokováno |

**Senioři:** Neznám samostatný číselný profil FEDIAF pro seniory 🟡. U seniora 🛠 aplikace použije
dospělý profil a zobrazí upozornění „vyžaduje odborné posouzení". Energie seniorů se liší individuálně
a riziko úbytku svalové hmoty je třeba sledovat (MCS podle WSAVA `[WSAVA2011]` ✅).

## 3.2 Seznam živin, které aplikace hodnotí

Sloupec **Priorita** vyjadřuje, jak silně má aplikace živinu sledovat u BARF dávek. Nevyjadřuje
fyziologickou důležitost (esenciální jsou všechny):
- **A**: v literatuře o BARF a domácích dávkách opakovaně nevyvážené, nebo jde o bezpečnostní riziko
  nadbytku,
- **B**: esenciální, v BARF obvykle méně problematické, ale data často chybí,
- **C**: kontextové (jen pro určité suroviny nebo fáze).

Kanonická jednotka platí pro uložení v databázi (viz [06-nutricni-analyza.md](06-nutricni-analyza.md), §6.2).

### Energie a makroživiny

| Kód | Živina | Kan. jednotka | Pes | Kočka | Priorita | Poznámka, zdroj |
|---|---|---|---|---|---|---|
| `ENERGY_ME` | Metabolizovatelná energie | kcal | ● | ● | A | Výpočet viz [05](05-energeticky-model.md) a §6.3 |
| `PROTEIN` | Hrubé bílkoviny | g | ● | ● | A | Kočky mají výrazně vyšší požadavek než psi 🟡 `[NRC2006]` |
| `FAT` | Tuk | g | ● | ● | A | Minimum + praktický strop u pankreatitidy (🩺, [09](09-rizika.md)) |
| `LA` | Kyselina linolová (C18:2 n-6) | g | ● | ● | A | Nízká v libovém mase přežvýkavců 🟡 |
| `ALA` | Kyselina α-linolenová (C18:3 n-3) | g | ● (růst) | ● (růst) | C | 🟡 |
| `ARA` | Kyselina arachidonová (C20:4 n-6) | g | – | ● | A (kočky) | U koček esenciální 🟡 `[NRC2006]`, `[Morris2002]` |
| `EPA_DHA` | EPA + DHA | g | ● (růst) | ● (růst) | B | Ryby a rybí olej: hlídat vitamin E (§3.4) |

### Esenciální aminokyseliny

| Kód | Živina | Jedn. | Pes | Kočka | Priorita | Poznámka |
|---|---|---|---|---|---|---|
| `ARG` | Arginin | g | ● | ● | B | Kočky: nedostatek způsobuje hyperamonémii 🟡 `[Morris2002]` |
| `HIS`, `ILE`, `LEU`, `LYS`, `THR`, `TRP`, `VAL` | Histidin, izoleucin, leucin, lysin, threonin, tryptofan, valin | g | ● | ● | B | V mase obvykle dostatečné, ale **data v databázích často chybí** |
| `MET`, `MET_CYS` | Methionin, methionin + cystin | g | ● | ● | B | |
| `PHE`, `PHE_TYR` | Fenylalanin, fenylalanin + tyrosin | g | ● | ● | B | |
| `TAURINE` | Taurin | g | (–)* | ● | **A (kočky)** | `[Pion1987]` ✅. FEDIAF uvádí rozdílné hodnoty pro vlhká a suchá krmiva 🟡. Obsah taurinu v syrovém mase je datová mezera |

\* U psů není taurin v FEDIAF stanoven jako minimum 🟡. 🩺 Specialista rozhodne, zda zobrazovat
informativní upozornění u specifických situací.

### Minerální látky

| Kód | Živina | Jedn. | Pes | Kočka | Priorita | Poznámka |
|---|---|---|---|---|---|---|
| `CA` | Vápník | g | ● ▲ | ● ▲ | **A** | Hlavní zdroj v BARF je kost. Složení masa s kostí je **datová mezera** |
| `P` | Fosfor | g | ● ▲ | ● ▲ | **A** | |
| `CA_P` | Poměr Ca:P | – | ● ▲ | ● ▲ | **A** | Dospělý pes max. 2:1 ✅ `[FEDIAF2025]` |
| `K` | Draslík | g | ● | ● | B | |
| `NA` | Sodík | g | ● | ● | B | |
| `CL` | Chloridy | g | ● | ● | B | Často chybí v databázích |
| `MG` | Hořčík | g | ● | ● | B | Urolitiáza: 🩺 |
| `FE` | Železo | mg | ● | ● | B | Zákonné maximum EU (L) 🟡 |
| `CU` | Měď | mg | ● | ● | **A** | Játra skotu jsou velmi bohatá. Riziko nadbytku i nedostatku `[Dillitzer2011]` |
| `ZN` | Zinek | mg | ● | ● | **A** | Interakce s Ca (§6.7) |
| `MN` | Mangan | mg | ● | ● | B | V mase nízký 🟡 |
| `I` | Jód | mg | ● | ● | **A** | Datová mezera v databázích. Riziko nadbytku (mořské řasy) i nedostatku |
| `SE` | Selen | µg | ● | ● | B | |

### Vitaminy

| Kód | Živina | Kan. jednotka | Pes | Kočka | Priorita | Poznámka |
|---|---|---|---|---|---|---|
| `VIT_A` | Vitamin A (**jen předem vytvořený retinol**) | µg retinolu | ● ▲ | ● ▲ | **A** | Kočky nevyužijí β-karoten 🟡 `[NRC2006]`. Nadbytek z jater `[Polizopoulou2005]` ✅ |
| `BETA_CAROTENE` | β-karoten | µg | info | – | C | **Nezapočítává se** do `VIT_A` (konzervativní volba 🛠 🩺) |
| `VIT_D` | Vitamin D (D3 + D2) | µg | ● ▲ | ● ▲ | **A** | Psi i kočky jsou závislí na příjmu z potravy `[How1994]` ✅ |
| `VIT_E` | Vitamin E | mg α-TE | ● | ● | **A** | Potřeba roste s obsahem PUFA (§3.4) |
| `VIT_K` | Vitamin K | µg | – | (●) | C | U koček podmíněně (vysoký podíl ryb) 🟡 |
| `THIAMINE` | Thiamin (B1) | mg | ● | ● | **A (kočky)** | Thiamináza v syrových rybách 🟡. Ztráty při zpracování `[Markovich2014]` |
| `RIBOFLAVIN` | Riboflavin (B2) | mg | ● | ● | B | |
| `PANTOTHENIC` | Kys. pantothenová (B5) | mg | ● | ● | B | |
| `VIT_B6` | Pyridoxin (B6) | mg | ● | ● | B | |
| `VIT_B12` | Kobalamin (B12) | µg | ● | ● | B | |
| `NIACIN` | Niacin (B3) | mg | ● | ● | B | Kočky mají obligátní příjem z potravy `[Morris2002]` |
| `FOLIC` | Kyselina listová | µg | ● | ● | B | |
| `BIOTIN` | Biotin | µg | (–) | ● | C | Syrový vaječný bílek váže biotin (avidin) 🟡 |
| `CHOLINE` | Cholin | mg | ● | ● | B | Data v databázích často chybí |

● = profil obsahuje minimum (přesné pokrytí podle fází se ověří při importu) · ▲ = existuje nutriční nebo
zákonné maximum (seznam maxim se převezme z originálu) · (–) = standard obvykle nestanovuje 🟡.

## 3.3 Ověřené číselné hodnoty

| Hodnota | Kontext | Zdroj | Stav |
|---|---|---|---|
| Referenční energie 95 a 110 kcal ME/kg BW^0,75 | Psi, dospělí | `[FEDIAF2025]` | ✅ S |
| Referenční energie 75 a 100 kcal ME/kg BW^0,67 | Kočky, dospělé | `[FEDIAF2025]` | ✅ S |
| Ca:P max. 2:1 (nutriční maximum) | Pes dospělý | `[FEDIAF2025]` tab. III-3b | ✅ S |
| Ca min. 1,25 g / 1 000 kcal ME | Pes dospělý, 110 kcal/kg^0,75 | `[FEDIAF2025]` přes `[SciRep2025]` | ✅ S |
| P min. 1,00 g / 1 000 kcal ME | Pes dospělý, 110 kcal/kg^0,75 | `[FEDIAF2025]` přes `[SciRep2025]` | ✅ S |
| Ca max. 1,8 % sušiny | Růst psů velkých plemen (≥ 70 lb) | `[AAFCO2014]` | ✅ S |
| Ca max. 2,5 % sušiny | Ostatní krmiva pro psy | `[AAFCO2014]` | ✅ S |
| Ca:P max. 1,6:1 / 1,8:1 | Pes časný / pozdní růst | FEDIAF 2016 (sekundárně) | 🟡 |

> **Oprava značky 🩺:** hodnoty `[FEDIAF2025]` (95 a 110, 75 a 100 kcal ME, Ca:P 2:1) byly dříve
> označeny ✅ P (ověřeno přímo v primárním zdroji). To bylo silnější, než odpovídá skutečnosti:
> zjištěny byly z výpisů vyhledávače z textu PDF, originál nebyl otevřen. Značka je proto **✅ S**
> a sedí s registrem [zdroje.md](zdroje.md). Do databáze standardů se tyto hodnoty smějí dostat
> až po přepisu z originálu (§3.5).

**Kontrola konzistence (příklad):** 1,25 g Ca/1 000 kcal ÷ 2,5 = 0,50 g Ca/100 g sušiny. Převod
faktorem 2,5 (při 4 000 kcal/kg sušiny) je ve FEDIAF uveden ✅ S. Takové kontroly se při importu spouští
automaticky (§3.5).

## 3.4 Druhově specifické zásady

### Kočky (samostatný model, nikdy ne „malý pes") 🛠
- **Taurin**: dlouhodobý nedostatek způsobuje dilatační kardiomyopatii, která je po suplementaci
  reverzibilní `[Pion1987]` ✅. Aplikace u koček taurin **vždy** zobrazuje. Bez dat o taurinu je výsledek
  „nelze vyhodnotit" a celkový stav dávky nikdy nesmí být „vyhovuje".
- **Kyselina arachidonová, předem vytvořený vitamin A, niacin, arginin**: druhově specifické potřeby
  koček 🟡 `[NRC2006]`, `[Morris2002]`.
- **Vitamin D** z potravy je nezbytný (stejně jako u psů) `[How1994]` ✅.
- **Játra**: riziko hypervitaminózy A při vysokém podílu jater `[Polizopoulou2005]` ✅. Aplikace hlídá
  maximum vitaminu A a zobrazí upozornění, když podíl jater překročí práh. 🩺 Práh stanoví specialista.
- **Ryby**: thiamináza v některých syrových rybách (u kapra a sledě je popsána ve sekundárních zdrojích)
  🟡. Vysoký příjem PUFA bez dostatku vitaminu E je spojován s pansteatitidou `[Niza2003]` 🟡.
- **Vyšší potřeba bílkovin** než u psů 🟡 `[NRC2006]`.

### Psi 🛠
- **Růst velkých plemen**: nadbytek Ca poškozuje vývoj skeletu `[Hazewinkel1985]` ✅. Proto platí přísná
  maxima Ca (AAFCO 1,8 % DM pro velká plemena ✅). V MVP je růst **blokovaný**.
- **Individuální energie**: podle přehledu NRC 2006 se udržovací potřeba dospělých psů pohybuje mezi
  95 a 200 kcal/kg^0,75 podle plemene, aktivity a chovu. Uvádí to metaanalýza `[Bermingham2014]` ✅.
- **Tkáň štítné žlázy** (jícny, hrtany, krční maso): riziko alimentární tyreotoxikózy `[Kohler2012]`,
  `[Broome2015]` ✅. U surovin je bezpečnostní příznak a aplikace zobrazí varování.

## 3.5 Postup importu číselných tabulek (Fáze 2) 🛠

1. **Zdroj:** výhradně originální PDF `[FEDIAF2025]`. U každé hodnoty se zaznamená tabulka a strana.
2. **Dvojí nezávislý přepis** do šablony
   [`data/reference/standard_import_template.csv`](../data/reference/standard_import_template.csv).
   Přepisují dvě osoby nezávisle na sobě, nástroj soubory porovná a každý rozdíl se dohledá v originále.
3. **Automatické kontroly konzistence** (testy importu):
   - `na 1 000 kcal = na 100 g DM × 2,5` (FEDIAF předpokládá 4 000 kcal/kg DM) ✅ S. Tolerance se odvodí
     od zaokrouhlení v tabulce.
   - `na 1 000 kcal = na MJ × 4,184` ✅ S.
   - `hodnota(95) / hodnota(110) ≈ 110/95 = 1,158` u dospělých psů. Totéž `100/75` u koček, pokud
     tabulka vznikla přepočtem. Odchylky se označí k ručnímu ověření.
   - minimum < každé maximum (nutriční maximum, SUL, zákonné maximum EU), pokud jsou definovány, a
     `RATIO_MIN` < `RATIO_MAX` (chyba). Vztah nutričního a zákonného maxima pevné pravidlo není:
     zákonné maximum EU pro komerční krmiva může být nižší než nutriční maximum 🟡. Nutriční maximum
     nad zákonným je proto jen varování k ověření v originále (`W_NUTRITIONAL_ABOVE_LEGAL`),
   - jednotka odpovídá kanonické jednotce živiny, nebo existuje explicitní převod.

   Kontroly z bodů 2 a 3 provádí nástroj `python -m refdata` (balíček `refdata/`, příkazy `validate`
   a `compare`). Existenci a správnost převodu jednotky (např. IU) nástroj neověřuje, jen ho vyžádá
   (`W_NEEDS_CONVERSION`). Ověří ho kurátor a specialista. Postup pro přepisovatele a specialistu popisuje
   [postup-prepisu-standardu.md](postup-prepisu-standardu.md).
4. **Revize specialistou:** stav `DRAFT` → `IN_REVIEW` → `APPROVED` (viz [07](07-django-schema.md) §7.6). Do produkčních výpočtů vstupují jen schválené
   verze (`DataVersion.status = APPROVED`).
5. **Neměnnost:** schválenou verzi nelze editovat. Oprava = nová verze s poznámkou o změně.

## 3.6 Kontrolní seznam pro specialistu 🩺

- [ ] Úplnost seznamu živin pro psy a kočky (§3.2) a priority A/B/C.
- [ ] Rozhodnutí o β-karotenu (nezapočítávat do vitaminu A u psů?).
- [ ] Prahy upozornění pro játra, ryby a tkáň štítné žlázy.
- [ ] Hranice fází (14 týdnů, dospělost podle velikosti plemene, senior).
- [ ] Zda u psů zobrazovat taurin informativně (např. u specifických diet).
- [ ] Schválení importovaných tabulek FEDIAF 2025.
