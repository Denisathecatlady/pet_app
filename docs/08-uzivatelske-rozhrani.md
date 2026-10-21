# 8. Návrh uživatelského rozhraní

> Kapitola je 🛠 pracovní návrh. Texty varování a jejich úrovně posoudí 🩺 specialista.

## 8.1 Zásady

1. **Čeština, odborně, ale srozumitelně.** Každý odborný pojem má nápovědu (tooltip): RER, ME, BCS,
   sušina, „minimum doporučené FEDIAF"…
2. **Stav ≠ barva.** Každý stav má **ikonu + text + barvu** (přístupnost WCAG 2.1 AA, kontrast ≥ 4,5:1,
   srozumitelné i pro barvoslepé).
3. **Nejistota je vidět.** Úplnost dat a spolehlivost se zobrazují **samostatně** od stavu splnění.
   Zelená nikdy neznamená „bezpečné a kompletní" (§8.4).
4. **Zdroj je jeden klik.** U každého čísla jde zobrazit původ (surovina → profil → zdroj → tabulka
   nebo strana).
5. **Progresivní detail.** Souhrn → kategorie živin → živina → příspěvky surovin → surová data.

## 8.2 Mapa obrazovek

```
Dashboard zvířat
 ├─ Detail zvířete ── Sledování hmotnosti a BCS ── Zdravotní stavy
 │    └─ Kalkulačka denní dávky (energie)
 ├─ Recepty ── Editor dávky ── Nutriční rozbor ── Deficity a nadbytky
 │              │                  └─ Porovnání standardů
 │              └─ Historie revizí ── Porovnání receptů
 ├─ Databáze surovin ── Detail suroviny (profily, zdroje, kvalita)
 ├─ Knihovna zdrojů
 ├─ Export PDF
 └─ Nastavení (výchozí standard, jednotky, odborný režim)
```

## 8.3 Obrazovky

| Obrazovka | Obsah | Klíčové prvky |
|---|---|---|
| **Dashboard** | Karty zvířat: druh, věk, poslední hmotnost a BCS, trend (sparkline), aktivní recept a jeho souhrnný stav, upozornění | Odznak „vyžaduje odborné posouzení" u zvířat v rizikových stavech |
| **Detail zvířete** | Profil (povinná pole podle zadání bod 4), zdravotní stavy, alergie, výchozí standard (+ důvod volby) | Cílová hmotnost se štítkem „orientační / potvrzeno veterinářem" |
| **Sledování hmotnosti a kondice** | Graf hmotnosti v čase, body BCS a MCS, cílové pásmo, poznámky | Návrh úpravy energie (jen návrh, s vysvětlením a potvrzením) |
| **Kalkulačka denní dávky** | Vstupy → RER (informativně), MER s rozsahem, použitá rovnice a koeficient, zdroj | Velké upozornění „odhad – upravte podle vývoje hmotnosti a BCS" |
| **Databáze surovin** | Vyhledávání a filtry (kategorie, druh, stav úpravy, kvalita dat, alergeny), detail s hodnotami a zdroji | Indikátor úplnosti profilu (např. „37 / 45 živin") |
| **Editor dávky** | Řádky surovin a gramy na den. Živě se počítá energie vs. DER a popisná statistika (podíl svaloviny, kostí, orgánů) | Popisná statistika má štítek „nevypovídá o kompletnosti". Varování při duplicitě |
| **Nutriční rozbor** | Souhrn → tabulka a grafy živin po kategoriích | §8.4–8.5 |
| **Deficity a nadbytky** | Jen problémové živiny a nevyhodnotitelné živiny, s hlavními přispívajícími surovinami | Odkaz „co prověřit" (data, suroviny, konzultace) |
| **Porovnání standardů** | Stejná dávka podle FEDIAF, NRC a AAFCO ve sloupcích | Vysvětlení rozdílů v typu hodnot a referenční energii |
| **Historie jídelníčků / porovnání receptů** | Revize s datem a poznámkou, rozdíl dvou revizí (gramy i živiny) | |
| **Knihovna zdrojů** | Registr `ScientificSource`: úroveň, ověření, omezení, kde se zdroj v aplikaci používá | |
| **Export PDF** | Profil zvířete, recept, rozbor, varování, verze dat a jádra, hash, datum, upozornění na omezení | PDF vždy obsahuje sekci „Omezení a nejistoty" |
| **Nastavení** | Výchozí standard, zobrazení jednotek, odborný režim (role vet) | |

> **Stav obrazovek Dashboard a Sledování hmotnosti a kondice 🛠:** implementováno v rozsahu bez
> kalkulačky ([12](12-ucty-a-zvirata.md) §12.11). Dashboard ukazuje od dvou měření sparkline hmotnosti
> s textovou alternativou; sledování má graf hmotnosti (období 30, 90, 365 dní nebo vše, tvar značky
> podle toho, kdo měření zapsal, čárkovaná cílová hmotnost se štítkem *orientační* / *potvrzeno
> veterinářem*), graf BCS s pásmem 4–5 z 9 a vždy tabulku všech zobrazených měření včetně MCS.
> **Není** implementováno: body MCS v grafu, trendová upozornění, „rychlý úbytek hmotnosti“ (práh
> musí stanovit 🩺 specialista) a *Návrh úpravy energie* (patří ke kalkulačce, docs/05 §5.6).

## 8.4 Vizuální jazyk stavů

| Stav (§6.6) | Ikona | Barva | Text |
|---|---|---|---|
| `ADEQUATE` | ✓ | zelená | V rozmezí standardu |
| `MIN_MET_PARTIAL` | ✓ s tečkovaným obrysem | zelená, šrafovaná | Minimum splněno, maximum nelze ověřit |
| `BORDERLINE_MIN` / `BORDERLINE_MAX` | ◐ | jantarová | Na hranici (v rozsahu nejistoty) |
| `BELOW_MIN` | ▼ | červená | Pod minimem |
| `ABOVE_MAX` / `ABOVE_SUL` | ▲ | červená | Nad maximem |
| `ABOVE_LEGAL_MAX_INFO` | ⓘ | modrá | Nad zákonným limitem pro komerční krmiva (informativně) |
| `NOT_EVALUABLE` | ? | **šedá šrafovaná** (nikdy prázdná ani zelená) | Nelze vyhodnotit – chybí data |
| `NO_REFERENCE` | – | neutrální | Standard nestanovuje |

**Souhrnná karta rozboru (příklad):**

```
┌──────────────────────────────────────────────────────────────────────┐
│  ◐ NEÚPLNÉ VYHODNOCENÍ – vyhodnoceno 31 z 38 povinných živin          │
│  Standard: FEDIAF 2025 · pes · dospělý · 110 kcal/kg^0,75             │
│  ▼ 2 pod minimem (Zn, I)   ▲ 0 nad maximem   ? 7 nelze vyhodnotit     │
│  Energie: 1 012 kcal / den (odhad potřeby 1 040, rozsah 898–1 182)    │
│  Spolehlivost dat: B (nejslabší: jód – převzato z podobné suroviny)   │
│  ⓘ Syrová strava: mikrobiologická rizika pro zvíře i domácnost        │
└──────────────────────────────────────────────────────────────────────┘
```

## 8.5 Graf živiny („bullet chart" na 1 000 kcal)

```
Zinek   ████████████████▌ ┊          │
        0          hodnota min        max
        [▼ Pod minimem · 74 % · interval 70–78 % · spolehlivost B · zdroj ▸]
```

- Lineární osa normalizovaná na minimum (100 % = minimum). Maximum je vyznačeno svislou čarou.
- Interval nejistoty jako vousy (whiskers). U `PARTIAL` je pravá strana otevřená (šipka „≥").
- Kategorie živin jsou sbalitelné. Ve výchozím pohledu: priorita A rozbalená.
- Tabulkový pohled se stejnými daty pro tisk, export a čtečky obrazovky.
- Procenta v náčrtku jsou ilustrační.

## 8.6 Úrovně upozornění (zadání bod 10)

| Úroveň | Vzhled | Chování |
|---|---|---|
| **Informativní doporučení** | ⓘ modrý pruh | Nebrání ničemu |
| **Nutriční varování** | ⚠ jantarový pruh | Zobrazí se v souhrnu i u živiny |
| **Vyžaduje odborné posouzení** | 🩺 fialový rámeček | Výpočet proběhne s vodoznakem. Optimalizace je vypnutá. PDF nese upozornění |
| **Automatický výpočet nelze doporučit** | ⛔ celostránkový stav | Rozbor se nezobrazí jako doporučení. Uživatel vidí, proč, a co dělat dál (kontakt na veterinárního nutričního specialistu) |

## 8.7 Kritické mikrotexty (návrh, 🩺 k revizi)

- Souhrn bez chyb: „Všechny **vyhodnocené** požadavky standardu FEDIAF 2025 (dospělý pes) jsou splněny.
  To neznamená, že dávka je bezpečná: vyhodnocení vychází z dostupných dat o surovinách
  a nezohledňuje mikrobiologická rizika."
- Chybějící data: „Nelze vyhodnotit – pro 2 suroviny (85 % hmotnosti dávky) chybí údaj o vápníku.
  Hodnota 0 by byla zavádějící."
- Cílová hmotnost: „Zadaná cílová hmotnost je orientační. Ideální hmotnost by měl potvrdit veterinář
  podle BCS."
