# 2. Přehled odborných standardů a jejich rozdíly

> Legenda: ✅ ověřeno · 🟡 ověřit v originále · 🛠 pracovní návrh · 🩺 posoudí vet. nutriční specialista.
> Klíče zdrojů viz [zdroje.md](zdroje.md).

## 2.1 Přehled

| | **FEDIAF** `[FEDIAF2025]` | **NRC** `[NRC2006]` | **AAFCO** `[AAFCO2014]` | **WSAVA** `[WSAVA2011]` |
|---|---|---|---|---|
| Kdo | Evropská federace výrobců krmiv. Recenze nezávislou vědeckou radou ✅ | Výbor National Academies (USA) | Asociace kontrolních úředníků pro krmiva (USA) | Světová asociace veterinárních lékařů malých zvířat |
| Účel | Doporučení pro **komerční** kompletní a doplňková krmiva | Vědecká syntéza fyziologických potřeb | Regulační profily pro značení krmiv v USA | **Postup** hodnocení výživy, ne číselné požadavky |
| Právní váha | Nezávazná (samoregulace) ✅ | Žádná (vědecký podklad) | Závazná přes legislativu států USA 🟡 | Žádná (doporučený postup) |
| Aktuální verze | 2025 (září 2025) ✅. Aktualizuje se zhruba každý rok | 2006 (žádná novější edice) ✅ | Revize profilů 2014, v Official Publication od 2016 ✅ | 2011 (+ nástroje BCS/MCS) ✅ |
| Typ hodnot | **Minimální doporučené úrovně** s rezervou na dostupnost. Nutriční maxima (N) a zákonná maxima EU (L) ✅ | **MR** (minimální požadavek), **AI** (adekvátní příjem), **RA** (doporučená dávka), **SUL** (bezpečný horní limit) 🟡 | Minima a vybraná maxima 🟡 | – |
| Vyjádření | Na 100 g sušiny, na 1 000 kcal ME, na MJ ME ✅ | Na kg BW^0,75 (psi), na kg BW^0,67 (kočky) a na 1 000 kcal ME při 4 000 kcal/kg sušiny ✅ (energetická hustota) | Na sušinu (4 000 kcal/kg) a na 1 000 kcal ME 🟡 | – |
| Referenční energie | Psi 95 a 110 kcal/kg^0,75. Kočky 75 a 100 kcal/kg^0,67 ✅ | Individuální (rovnice) | Pevná energetická hustota | – |
| Životní fáze | Psi: dospělí, *časný růst (< 14 týdnů) a reprodukce*, *pozdní růst (≥ 14 týdnů)*. Kočky: dospělé, růst a reprodukce 🟡 | Růst, dospělost, březost, laktace ✅ | „Growth & Reproduction", „Adult Maintenance". Kategorie „All Life Stages" musí splnit G&R ✅ | – |

## 2.2 Klíčové rozdíly a jejich praktický význam

### a) Požadavek není totéž co doporučení ✅ / 🟡
FEDIAF výslovně uvádí, že tabulkové hodnoty jsou *minimální doporučené úrovně pro komerční krmiva*,
nikoli minimální požadavky ✅ `[FEDIAF2025]`. NRC rozlišuje MR (nejnižší koncentrace s prokázanou
účinností při vysoké dostupnosti), AI (když MR nelze stanovit), RA (doporučená dávka) a SUL (bezpečný
horní limit) 🟡 `[NRC2006]`.

**Dopad na aplikaci 🛠:** Každý požadavek v databázi má povinný atribut `requirement_type`
(`MIN_RECOMMENDED`, `MR`, `AI`, `RA`, `NUTRITIONAL_MAX`, `LEGAL_MAX_EU`, `SUL` atd.). Text výsledku se
podle typu liší. Například „pod minimem doporučeným FEDIAF" neznamená automaticky „fyziologický
deficit", ale „není splněno doporučení s bezpečnostní rezervou".

### b) Referenční energetický příjem ✅
FEDIAF uvádí pro psy dvě sady hodnot (95 a 110 kcal/kg^0,75), protože zvíře s nižším příjmem energie
musí mít živiny v **hustší** koncentraci na 1 000 kcal ✅ `[FEDIAF2025]`. Poměr 110/95 = 1,158 je
přesně faktor, o který se požadavek na 1 000 kcal zvýší.

**Dopad 🛠:** Pokud skutečný příjem zvířete leží mimo referenční hodnoty, aplikace požadavek na 1 000 kcal
přepočítá (rovnice v [06-nutricni-analyza.md](06-nutricni-analyza.md), §6.4). Pokud standard takový
přepočet nepřipouští, aplikace na to upozorní. 🩺 Specialista musí potvrdit, pro které živiny je
lineární přepočet metodicky správný.

### c) Velká plemena v růstu (vápník) ✅
AAFCO od revize 2014 omezuje vápník na **max. 1,8 % sušiny** u krmiv pro růst psů velkých plemen
(dospělá hmotnost ≥ 70 lb, tj. ≈ 32 kg). Pro ostatní krmiva platí **max. 2,5 % sušiny** ✅ (sekundární
zdroje k `[AAFCO2014]`). Hodnota 1,8 % odpovídá horní hranici NRC pro růst při 4 000 kcal ME/kg ✅.
Podkladem jsou studie nadbytku Ca u rostoucích dog `[Hazewinkel1985]` ✅.

### d) Poměr Ca:P ✅ / 🟡
FEDIAF 2025 uvádí pro dospělé psy nutriční maximum poměru Ca:P **2:1** ✅. Pro růst jsou maxima
přísnější (sekundárně uváděno 1,6:1 pro časný a 1,8:1 pro pozdní růst) 🟡, nutné ověřit v tabulce
`[FEDIAF2025]`.

### e) Stáří dat ✅
NRC je z roku 2006. FEDIAF se aktualizuje ročně a zapracovává novější data. Proto jako **výchozí standard
pro ČR a EU** navrhuji FEDIAF 🛠.

### f) Standard pro komerční krmivo × domácí dávka 🛠 🩺
Všechny číselné standardy vznikly pro komerční krmiva. Pro domácí dávku je jejich použití **analogické**:
bezpečnostní rezervy FEDIAF počítají s typickou dostupností živin v průmyslových krmivech, ne v syrových
surovinách. Specialista musí rozhodnout, zda pro BARF použít FEDIAF beze změny (konzervativní varianta,
doporučuji pro MVP), nebo NRC RA s vlastním odůvodněním.

## 2.3 Pravidla práce se standardy v aplikaci 🛠

1. **Žádné míchání.** Jeden rozbor = jeden `StandardProfile` (standard + verze + druh + fáze + referenční
   energie). Chybí-li ve standardu hodnota pro danou živinu, zobrazí se „standard nestanovuje", **nikdy**
   se nedoplní hodnota z jiného standardu.
2. **Porovnání vedle sebe.** Samostatná obrazovka „Porovnání standardů" ukáže stejnou dávku hodnocenou
   podle FEDIAF, NRC a AAFCO ve sloupcích a vysvětlí rozdíly (typ hodnoty, referenční energie).
3. **Volba s odůvodněním.** Změna výchozího standardu u zvířete vyžaduje poznámku (proč). Poznámka se uloží
   do auditní historie.
4. **Zákonná maxima (L) jako informace.** Zákonná maxima EU platí pro komerční krmiva. U domácí dávky se
   zobrazí jako informativní upozornění, ne jako „porušení".
5. **Druh a fáze jsou tvrdé klíče.** Profil pro psa nelze přiřadit kočce (databázové omezení i validace).
   Profil pro dospělé nelze použít u zvířete mladšího, než stanoví pravidlo fáze.

## 2.4 Co musí zkontrolovat specialista 🩺

- [ ] Volbu FEDIAF 2025 jako výchozího standardu pro BARF a případné výjimky.
- [ ] Metodiku přepočtu požadavků při příjmu energie mimo referenční hodnoty.
- [ ] Mapování typů hodnot NRC (MR/AI/RA/SUL) na texty v aplikaci.
- [ ] Hranice věku a hmotnosti pro přechod mezi fázemi (časný/pozdní růst, dospělost, senior).
