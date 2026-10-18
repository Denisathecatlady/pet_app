# 5. Matematický model energetické potřeby

> Legenda: ✅ ověřeno (P = primárně, S = sekundárně) · 🟡 ověřit v originále · 🛠 pracovní návrh ·
> 🩺 posoudí vet. nutriční specialista.

## 5.0 Základní teze

Energetickou potřebu **nelze spolehlivě určit jen z hmotnosti**. Udržovací potřeba dospělých psů se
podle přehledu NRC 2006 pohybuje mezi 95 a 200 kcal ME/kg BW^0,75 podle plemene, aktivity a způsobu
chovu `[Bermingham2014]` ✅. U štěňat bývá skutečný příjem při ideální kondici nižší, než předpovídá
rovnice NRC `[YorkshireGrowth2017]`, `[NorfolkGrowth2021]`, `[PuppyIntake2019]` ✅ (abstrakty).
U laktujících koček byl naopak příjem vyšší než doporučení NRC `[Wichert2009]` ✅ (abstrakt).

Výstup modelu je proto vždy:
- **bodový odhad + rozsah** (ne jedno číslo),
- označení **„odhad – upravte podle vývoje hmotnosti a BCS"**,
- vazba na použitou rovnici, koeficient, zdroj a verzi dat.

Všechny koeficienty jsou **data** (tabulka `EnergyFactor`), ne konstanty v kódu 🛠.

## 5.1 Značení a jednotky

| Symbol | Význam | Jednotka |
|---|---|---|
| `BW` | aktuální tělesná hmotnost | kg |
| `BW_m` | očekávaná hmotnost v dospělosti (růst) | kg |
| `p` | `BW / BW_m` (podíl dospělé hmotnosti) | – |
| `RER` | klidová energetická potřeba (resting energy requirement) | kcal ME/den |
| `MER` | udržovací energetická potřeba (maintenance energy requirement) | kcal ME/den |
| `DER` | odhad celkové denní potřeby v aplikaci (MER × případné úpravy) | kcal ME/den |
| `k` | koeficient udržovací potřeby | kcal ME/kg BW^n/den |
| `n` | exponent metabolické hmotnosti: **0,75 pro psy, 0,67 pro kočky** | – |

Energie se v aplikaci vyjadřuje v **kcal metabolizovatelné energie (ME)**. Převod na kJ: 1 kcal =
4,184 kJ ✅ (definice termochemické kalorie, odpovídá převodu MJ ve FEDIAF).

## 5.2 Klidová energetická potřeba (RER)

$$RER = 70 \cdot BW^{0{,}75} \quad [\text{kcal ME/den}]$$

- Zdroj: `[NRC2006]` přes `[PNA-RER]` ✅ S. Stejná rovnice platí pro psy i kočky ✅ S.
- Použití 🛠: informativní (např. hospitalizovaná zvířata, kontext pro veterináře). **Pro výpočet
  dávky se nepoužívá** paušální násobek RER. Aplikace používá přímo tvar `k · BW^n` s koeficientem podle
  zdroje (§5.3), protože ten FEDIAF a NRC uvádějí a ověřují.
- Omezení: U obézních zvířat rovnice založená jen na hmotnosti potřebu nadhodnocuje, protože tuková
  tkáň je metabolicky méně aktivní než svalová ✅ S (Wikivet).

## 5.3 Udržovací potřeba dospělých (MER)

$$MER = k \cdot BW^{n}$$

### Psi (`n = 0,75`)

| Situace (klíč `EnergyFactor`) | `k` | Zdroj | Stav |
|---|---|---|---|
| Referenční hodnota tabulek, nižší potřeba | 95 | `[FEDIAF2025]` | ✅ P |
| Referenční hodnota tabulek, běžná | 110 | `[FEDIAF2025]` | ✅ P |
| Nízká aktivita | ≈ 95 | FEDIAF podle `[MDPI2025]` | ✅ S |
| Střední aktivita | ≈ 110 | totéž | ✅ S |
| Střední aktivita, vysoká zátěž | ≈ 125 | totéž | ✅ S |
| Vysoká aktivita (pracovní psi) | 150–175 | totéž | ✅ S |
| Extrémní podmínky (závodní psi spřežení) | 860–1 240 | totéž | ✅ S, **mimo rozsah aplikace** |
| Úpravy podle věku a plemene | – | FEDIAF kap. o energii | 🟡 doplnit z originálu |

### Kočky (`n = 0,67`)

| Situace | `k` | Zdroj | Stav |
|---|---|---|---|
| Referenční, štíhlé aktivní kočky | 100 | `[FEDIAF2025]` | ✅ P |
| Referenční, nižší potřeba (kastrované, indoor) | 75 | `[FEDIAF2025]` | ✅ P hodnota, 🟡 přiřazení skupině |
| Kočky s nadváhou | samostatná rovnice NRC (uváděn exponent 0,4) | `[NRC2006]` | 🟡 **neověřeno, v MVP se nepoužije** |

### Rozsah odhadu 🛠
- **Bodový odhad:** koeficient zvolené kategorie aktivity.
- **Rozsah:** sousední kategorie (např. u „střední aktivity" psa 95–125). Pokud zdroj udává rozsah
  (150–175), použije se ten.
- 🩺 Specialista potvrdí, že rozsah je klinicky smysluplný a že se uživateli zobrazí srozumitelně.

### Kastrace, kondice a individuální variabilita 🛠
- **Kastrace:** aplikace **nepoužívá** paušální násobitel (žádný konkrétní faktor nebyl v této fázi
  ověřen). Kastrace posune výchozí kategorii k nižšímu koeficientu (např. 95 místo 110 u psa,
  75 místo 100 u kočky) a zobrazí upozornění. 🩺 Pravidlo musí schválit specialista.
- **BCS:** výpočet probíhá z **aktuální** hmotnosti. Je-li BCS mimo pásmo 4–5/9, aplikace výpočet
  dávky pro hubnutí nebo přibírání **nenabízí automaticky** (stav *vyžaduje odborné posouzení*, viz
  [09-rizika.md](09-rizika.md)). Devítibodová škála BCS: `[Laflamme1997d]`, `[Laflamme1997c]` ✅ B.
- **Cílová hmotnost** se ukládá jako *orientační údaj* se stavem `UNVERIFIED` / `VET_CONFIRMED`.
  Do výpočtu vstupuje jen ve stavu `VET_CONFIRMED`.

## 5.4 Růst (mimo MVP, implementace jen v odborném režimu)

**Štěňata** `[NRC2006]` ✅ S (sekundární zdroje, ověřit v NRC kap. 15):

$$ME = 130 \cdot BW^{0{,}75} \cdot 3{,}2 \cdot \left(e^{-0{,}87\,p} - 0{,}1\right)$$

**Koťata** `[NRC2006]` ✅ S (Wikivet, ověřit v NRC):

$$ME = 100 \cdot BW^{0{,}67} \cdot 6{,}7 \cdot \left(e^{-0{,}189\,p} - 0{,}66\right)$$

- Vstup `BW_m` je **odhad**, který sám nese velkou nejistotu (zvlášť u kříženců). Aplikace ho vyžaduje
  od uživatele, označí ho a nikdy ho sama nedopočítává.
- Novější studie ukazují, že rovnice pro štěňata může potřebu nadhodnocovat (viz §5.0). Výsledek je
  vždy odhad s nutnou kontrolou růstové křivky.
- 🩺 Před zapnutím: ověřit rovnice v NRC, platnost od odstavu, horní mez `p`, chování pro `p → 1`.

## 5.5 Březost a laktace (mimo MVP)

NRC vyjadřuje potřebu březích fen přes `BW^0,75`. U laktujících fen kombinuje `BW^0,75`, `BW` a počet
štěňat. U koček analogicky přes `BW^0,67`, `BW` a počet koťat ✅ S (popis struktury rovnic v NRC 2006).
**Konkrétní konstanty a týdenní faktory laktace nebyly v této fázi ověřeny** 🟡. Aplikace tyto stavy
v MVP označí jako *automatický výpočet nelze doporučit*.

## 5.6 Adaptivní korekce podle skutečného vývoje 🛠 🩺

Odhad je jen výchozí bod. Skutečnou potřebu ukáže vývoj hmotnosti a BCS:

1. Uživatel zaznamenává hmotnost (doporučeně 1× týdně) a BCS (1× za 2–4 týdny).
2. Aplikace porovná trend (lineární regrese posledních N měření) s cílem (stabilní hmotnost).
3. Při trvalé odchylce **navrhne** úpravu energie (např. ±5–10 %) a **vysvětlí** důvod. Uživatel ji
   musí potvrdit. Návrh nikdy neproběhne automaticky.
4. Odvozený empirický koeficient zvířete: `k_emp = (skutečný příjem kcal/den) / BW^n` při stabilní
   hmotnosti a BCS. Uloží se jako individuální koeficient se zdrojem „vlastní pozorování".

🩺 Velikost kroku, délku sledovaného období a prahy odchylky musí stanovit specialista. Zde uvedená
čísla jsou jen ilustrační.

## 5.7 Determinismus výpočtu 🛠

- Aritmetika `decimal.Decimal` s pevným kontextem (přesnost 28 platných číslic, `ROUND_HALF_EVEN`)
  nastaveným lokálně ve výpočetním jádře.
- Mocnina s neceločíselným exponentem: `Decimal.__pow__`. Exponenciála: `Decimal.exp()`. Obojí je
  v Pythonu deterministické a korektně zaokrouhlené.
- Zaokrouhlení **pouze při zobrazení** (energie na celé kcal). Uložené výsledky mají plnou přesnost.

## 5.8 Kontrolní příklady (vypočteno pro testy, ne klinická doporučení)

| Vstup | Mezivýsledek | Výsledek |
|---|---|---|
| RER, BW = 10 kg | 10^0,75 = 5,623413… | **393,64 kcal** |
| RER, BW = 1 kg | 1^0,75 = 1 | **70,00 kcal** |
| Pes 20 kg, k = 95 | 20^0,75 = 9,457416… | **898,45 kcal** |
| Pes 20 kg, k = 110 | – | **1 040,32 kcal** |
| Kočka 4 kg, k = 100 | 4^0,67 = 2,531513… | **253,15 kcal** |
| Kočka 4 kg, k = 75 | – | **189,86 kcal** |
| Štěně 10 kg, `BW_m` 30 kg (`p` = 1/3) | faktor 3,2·(e^(−0,29) − 0,1) = 2,074443… | **1 516,51 kcal** |
| Kotě 2 kg, `BW_m` 4 kg (`p` = 0,5) | faktor 6,7·(e^(−0,0945) − 0,66) = 1,673846… | **266,32 kcal** |

Hodnoty spočítalo jádro v Pythonu s `Decimal` (přesnost 28). V testech se porovnávají s tolerancí
`1e-6 kcal`. 🩺 Specialista ověří alespoň 3 příklady ručně nebo ve svém softwaru.

## 5.9 Vstupy, výstupy, chyby (rozhraní funkce) 🛠

```text
estimate_energy(species, body_weight_kg, life_stage, activity, neutered, bcs,
                expected_adult_weight_kg=None, energy_factor_set: DataVersion) -> EnergyEstimate

EnergyEstimate:
  kcal_point: Decimal, kcal_low: Decimal, kcal_high: Decimal
  method_code: str            # např. "FEDIAF2025_MER_DOG"
  factor: EnergyFactor (k, n, source)
  rer_kcal: Decimal           # informativně
  flags: [Flag]               # EXPERT_REQUIRED, BLOCKED, INFO…
  inputs_hash: str, data_version: str, engine_version: str

Chyby:
  InvalidInput        – BW ≤ 0, BW mimo věrohodný rozsah druhu, BCS mimo 1–9
  SpeciesMismatch     – koeficient pro jiný druh
  UnsupportedState    – růst / březost / laktace v MVP → výsledek BLOCKED (nikoli výjimka pro UI)
  MissingFactor       – pro kombinaci druh × fáze × aktivita chybí schválený koeficient
```
