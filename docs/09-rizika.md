# 9. Hlavní bezpečnostní a odborná rizika

> Legenda: ✅ ověřeno · 🟡 ověřit · 🛠 pracovní návrh · 🩺 posoudí vet. nutriční specialista.

## 9.1 Rizika pro zdraví zvířete (odborná)

| # | Riziko | Příklad / doklad | Opatření v aplikaci | Stav |
|---|---|---|---|---|
| R1 | **Falešný dojem kompletnosti** | Většina domácích receptů nesplňuje standardy `[Stockman2013]`, `[Wilson2019]` | Konzervativní souhrn (§6.6.4), „X z Y vyhodnoceno", žádná zelená při chybějících datech | ✅ / 🛠 |
| R2 | **Chybná nebo neúplná data o surovinách** | Maso s kostí, jód a taurin v databázích chybí ([04](04-databaze-surovin-a-zdroju.md) §4.5) | Hodnocení kvality A–D, stav MISSING ≠ 0, převzetí jen podle pravidel | 🛠 |
| R3 | **Nadbytek Ca v růstu** (velká plemena) | `[Hazewinkel1985]`, AAFCO max. 1,8 % DM | Růst je v MVP blokovaný. Později přísná maxima podle velikosti | ✅ |
| R4 | **Hypervitaminóza A** (játra, olej z tresčích jater) | `[Polizopoulou2005]` | Maximum vitaminu A, pravidlo podílu jater | ✅ / práh 🩺 |
| R5 | **Alimentární tyreotoxikóza** (tkáň štítné žlázy) | `[Broome2015]`, `[Kohler2012]` | Bezpečnostní příznak suroviny, úroveň „vyžaduje posouzení" | ✅ |
| R6 | **Kosti: poranění a obstrukce** | Kostní cizí těleso jako rizikový faktor komplikací `[Gianella2009]` | Trvalé upozornění u dávek s kostí, zvýšené u psů < 10 kg | ✅ |
| R7 | **Deficit taurinu u koček** | `[Pion1987]` | Taurin je u koček povinná živina. Bez dat je rozbor neúplný | ✅ |
| R8 | **Thiamin a vitamin E u diet s rybami** | `[Markovich2014]`, `[Niza2003]` | Pravidla interakcí (§6.7) | 🟡 |
| R9 | **Nebezpečné dávky doplňků** | vitamin D, jód, Zn, Cu | Doplňky jen se zadanou maximální dávkou. Optimalizátor je nepřidává sám | 🛠 |
| R10 | **Použití standardu pro jiný druh nebo fázi** | Hodnoty pro psa u kočky | DB omezení + validace + test | 🛠 |
| R11 | **Podcenění variability energie** | 95–200 kcal/kg^0,75 `[Bermingham2014]` | Rozsah, adaptivní korekce, žádný univerzální násobitel | ✅ |
| R12 | **Mikrobiologická a parazitologická rizika** (zvíře i domácnost) | `[vanBree2018]`: *Salmonella* 20 %, *Listeria* 54 %, ESBL *E. coli* 80 % vzorků. `[Hamper2017]`: *Salmonella* Heidelberg a toxin *C. difficile* u koťat na syrové dietě | Trvalé upozornění v rozboru a v PDF. Hygienická doporučení (text 🩺) | ✅ |
| R13 | **Léčebné diety z běžného algoritmu** | CKD, játra, pankreatitida, diabetes, urolitiáza | Bezpečnostní brána (§9.2) | 🛠 🩺 |

## 9.2 Bezpečnostní brána: zdravotní stavy a fáze 🛠 🩺

| Stav zvířete | Úroveň v MVP | Proč |
|---|---|---|
| Chronické onemocnění ledvin (CKD) | ⛔ Automatický výpočet nelze doporučit | Úprava P, bílkovin, Na a dalších podle stadia vyžaduje veterinární plán |
| Onemocnění jater | ⛔ | Individuální úprava bílkovin, Cu a dalších |
| Pankreatitida, hyperlipidémie | ⛔ | Strop tuku stanoví veterinář. Syrové tučné suroviny jsou rizikové |
| Diabetes mellitus | ⛔ | Vazba na terapii inzulinem a režim krmení |
| Urolitiáza a onemocnění močových cest | ⛔ | Závisí na typu urolitu (struvit, oxalát, urát…) |
| Potravní alergie | 🩺 Vyžaduje posouzení | Eliminační dieta je diagnostický postup. Aplikace umí jen filtrovat alergeny |
| Růst (štěně, kotě) | ⛔ v MVP, 🩺 později | Rovnice a limity Ca; vysoké riziko chyby |
| Březost, laktace | ⛔ | Neověřené rovnice a vysoké nároky |
| BCS ≤ 3/9 nebo ≥ 7/9 | 🩺 Vyžaduje posouzení | Hubnutí nebo přibírání potřebuje plán a kontrolu |
| BCS 1–2/9, rychlý úbytek hmotnosti | ⛔ | Může jít o onemocnění. Riziko refeeding syndromu 🟡 |
| Senior se svalovou ztrátou (MCS) | 🩺 | `[WSAVA2011]` ✅ |
| Užívání léků ovlivňujících výživu | 🩺 | Interakce posoudí veterinář |

Brána je **data-driven** (`HealthCondition.mode`, `WarningRule`). Seznam spravuje a schvaluje specialista.

## 9.3 Rizika softwarová a datová 🛠

| # | Riziko | Opatření |
|---|---|---|
| T1 | Záměna jednotek nebo bází (na 100 g vs. na 1 000 kcal, sušina vs. původní hmota) | Typ `Quantity` s bází, výjimky, property testy ([11](11-testovaci-plan.md)) |
| T2 | Chybný přepis tabulek standardu | Dvojí přepis, automatické kontroly konzistence (§3.5), schválení specialistou |
| T3 | Dvojí započtení suroviny nebo doplňku | `UniqueConstraint`, varování v editoru, test |
| T4 | Tichá změna výsledků po aktualizaci dat | Neměnné verze, snapshot, hash, `verify_analysis` |
| T5 | Chyba zaokrouhlení mění stav | Porovnání nezaokrouhlených hodnot, test „< 100 %" |
| T6 | Únik osobních údajů | Objektová oprávnění, testy, šifrované zálohy, GDPR procesy |
| T7 | Optimalizátor vrátí nebezpečné nebo nereálné řešení | Meze surovin, doplňky jen po výslovném povolení, re-analýza, přiznání neřešitelnosti |
| T8 | Licenční problém s daty | Registr licencí u zdroje, import jen po ověření licence |
| T9 | Zastarání standardu | Pole `edition_version`, upozornění na novou verzi, roční revize |

## 9.4 Právní a komunikační rizika 🛠 🩺

- **Odpovědnost:** podmínky užití musí jasně říct, že aplikace není veterinární služba. Text musí
  posoudit právník. Disclaimer ale **nenahrazuje** technická opatření výše.
- **Komunikace:** marketing nesmí tvrdit „kompletní a vyvážený BARF". Taková tvrzení jsou v rozporu
  s R1 a mohou narazit na předpisy o tvrzeních u krmiv 🟡.
