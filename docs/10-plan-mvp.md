# 10. Realistický plán vývoje MVP

> Kapitola je 🛠 pracovní návrh. Odhady pracnosti předpokládají jednoho vývojáře s podporou AI
> a dostupného veterinárního nutričního specialistu pro revize. Jsou orientační.

## 10.1 Strategie: nejdřív správnost, pak šíře

Nejdřív vznikne **úzké, ale ověřené** jádro: jeden druh, jedna fáze, jeden standard a malá databáze
surovin s doloženými daty. Teprve po odborné validaci výsledků se přidává šíře (kočky, růst, optimalizace).
Každá další funkce stojí na jádře, kterému už lze věřit.

## 10.2 Milníky

| Milník | Obsah | Výstup | Kritérium dokončení | Odhad |
|---|---|---|---|---|
| **M0 – Fáze 1** (tento dokument) | Koncepce, rešerše, model, schéma, UI, rizika | `docs/` | Revize specialistou: připomínky zapracované, otázky z kontrolních seznamů zodpovězené | – |
| **M1 – Data** | Import FEDIAF 2025 (pes dospělý, sloupce 95 a 110) dvojím přepisem. Katalog živin. 20–30 surovin z USDA FDC (Foundation / SR Legacy). Registr zdrojů | `DataVersion` STANDARDS a INGREDIENTS ve stavu `APPROVED` | Projdou všechny kontroly konzistence (§3.5). Specialista schválil | 2–3 týdny |
| **M2 – Výpočetní jádro `nutricalc`** | units, energy (RER, MER dospělý pes), ME dávky (NRC), součty s intervaly a úplností, požadavky, vyhodnocení, Ca:P, souhrn, základní pravidla | Balíček + testy | 100 % pokrytí kritických modulů, property testy, golden testy (syntetické) | 3–4 týdny |
| **M3 – Validace jádra** ⭐ | 5–10 reálných dávek: srovnání se specialistou | Validační protokol | Odchylky vysvětlené a v toleranci | 1–2 týdny (podle dostupnosti specialisty) |
| **M4 – Minimální Django** | Modely, admin pro kurátory, služba rozboru, uložení `RecipeAnalysis`, `verify_analysis`, účty, 1 zvíře → recept → rozbor (server-rendered) | Běžící aplikace (interní) | Integrační testy, oprávnění, reprodukovatelnost přes DB | 3–4 týdny |
| **M5 – UI MVP** | Profil zvířete, hmotnost a BCS, kalkulačka energie, editor dávky, nutriční rozbor, deficity, export PDF | Uzavřená beta | Testy UI, přístupnost (axe), uživatelské testy s 3–5 chovateli | 3–4 týdny |
| **M6 – Kočky (MVP-1)** | Profil FEDIAF pro dospělé kočky, taurin, ARA, pravidla pro kočky, rovnice ME pro kočky po ověření | Rozšíření | Validace dávek pro kočky specialistou | 2–3 týdny |
| **M7 – Fáze 5** | Optimalizace (LP), porovnání standardů (NRC, AAFCO), růst v odborném režimu | | Validace, testy neřešitelnosti | 4–6 týdnů |

> **Stav M2 🛠:** jádro `nutricalc` je implementované v rozsahu MVP-0 (units, energy, composition, me,
> requirements, evaluation, rules, gate, snapshot, analysis) a pokryté testy na **syntetických** datech
> (`SYN_*`, `TESTSTD`, golden příklady docs/05 §5.8 a docs/06 §6.10). Čeká na schválená data M1
> a na odbornou validaci M3 🩺.

> **Stav M4/M5 (část) 🛠:** webová aplikace má účty a role, GDPR export a výmaz, profily zvířat,
> sledování hmotnosti, BCS a MCS (tabulka a grafy hmotnosti a BCS bez JavaScriptu, sparkline na
> přehledu, [12](12-ucty-a-zvirata.md) §12.11), zdravotní stavy, sdílení s veterinářem, potvrzení
> cílové hmotnosti a přehled s úrovní upozornění ([12](12-ucty-a-zvirata.md)). Kalkulačka, recepty, rozbor
> a PDF (zbytek M4 a M5) jsou na žádost zadavatele odložené a čekají na M1 a M3.

> **Stav registru zdrojů (součást M1) 🛠:** všech 37 zdrojů registru [zdroje.md](zdroje.md) je
> v aplikaci jako `ScientificSource` a veřejná *Knihovna zdrojů* ukazuje jejich úroveň odbornosti a
> stav ověření ([13](13-zdroje-v-aplikaci.md)). Žádný zdroj zatím nemá v knihovně značku **P**
> (ověřená hodnota v primárním zdroji); data standardů a surovin (zbytek M1) a jejich schválení
> specialistou zůstávají odložené. **Oprava značky:** hodnoty `[FEDIAF2025]` (95/110 a 75/100 kcal ME, Ca:P 2:1) byly v dokumentech [03](03-nutricni-pozadavky.md) §3.3 a [05](05-energeticky-model.md) §5.3 dříve značeny ✅ P. Čteny byly jen z výpisů vyhledávače, proto jsou nově ✅ S, jako v registru zdrojů.

> **Stav provozu (součást M4) 🛠:** pro zálohy a obnovu databáze jsou hotové skripty `deploy/`
> (`backup_db.sh`, `restore_db.sh`, `restore_test.sh`, `run_manage.sh` pro denní úlohy aplikace,
> `crontab.example`) s automatickými testy `tests/ops/` a
> [provozní příručka](13-nasazeni-a-provoz.md) (nasazení, proxy a TLS, denní úlohy, retence
> 30 dní + 12 měsíců, měsíční test obnovy, oddělený účet pro zálohy, GDPR a zálohy).
> **Není implementováno:** přenos záloh mimo server (skripty zapisují jen do `BACKUP_DIR`,
> přenos je ruční krok, §13.11) a WAL archivace (jen popsaná). **Nevyzkoušeno:** WAL archivace
> (obnova k okamžiku), běh za skutečnou reverzní proxy s TLS, běh pod cronem a rozdělení účtů
> `barf` a `barf-backup`.

Celkem do uzavřené bety (M1–M5): zhruba **12–17 týdnů** práce plus čas na revize specialisty. Největší
nejistota je v datech (M1) a v dostupnosti specialisty (M3), ne v programování.

## 10.3 Co v MVP záměrně **není**

- Růst, březost, laktace (stav `BLOCKED`), léčebné diety (stav `BLOCKED`), hubnutí (stav `EXPERT_REQUIRED`).
- Optimalizátor a automatický návrh dávky.
- Více standardů současně (jen FEDIAF 2025). NRC a AAFCO přibudou až s obrazovkou „Porovnání standardů".
- Maso s kostí bez doloženého složení.
- Mobilní aplikace, platby, veřejné sdílení receptů.

## 10.4 Rozhodnutí, která potřebuji od tebe nebo od specialisty

1. **Kdo bude odborný garant** (veterinární nutriční specialista) a v jakém rozsahu bude revidovat.
2. **Licence dat:** potvrzení podmínek užití USDA FDC, CIQUAL a české databáze pro tento účel.
3. **Zdroj dat o mase s kostí:** laboratorní rozbory (náklady), nebo dočasně vynechat.
4. **Přístup k originálu FEDIAF 2025:** povolit doménu `europeanpetfood.org` ve vývojovém prostředí,
   nebo PDF vložit do repozitáře (licenci FEDIAF ověřit), aby šel přepis kontrolovat.
5. **Cílová skupina bety:** chovatelé, nebo veterináři? Podle toho se upraví texty a odborný režim.

---

## 10.5 Doporučení: nejmenší funkční verze (MVP-0) ⭐

> **Výpočetní jádro „dospělý zdravý pes – FEDIAF 2025" s 20–30 doloženými surovinami, bez UI, ověřené
> specialistou na 5–10 reálných dávkách.** Odpovídá milníkům M1 + M2 + M3.

**Rozsah MVP-0:**
- Druh: **pes**, fáze: **dospělý, udržovací** (sloupce 95 a 110 kcal/kg^0,75), bez zdravotních omezení,
  BCS 4–5/9.
- Energie: RER (informativně) a MER = k · BW^0,75 s rozsahem (§5.3).
- ME dávky: `NRC2006_DOG_CF` + `MOD_ATWATER` vedle sebe pro srovnání.
- Živiny: všechny živiny profilu FEDIAF pro dospělého psa, s úplností, intervaly a spolehlivostí.
  Ca:P. Souhrnný stav.
- Suroviny: svalovina, srdce, játra, ledviny, vejce, ryby, tuk, rybí olej, uhličitan vápenatý,
  1–2 premixy. **Bez masa s kostí**, dokud nebude doložené jeho složení.
- Rozhraní: CLI / Python API + JSON nebo CSV export, který si specialista otevře v tabulkovém
  procesoru. Django admin jen pro správu dat.
- Testy: kompletní katalog z [11](11-testovaci-plan.md) pro tento rozsah.

**Proč právě tohle:**
1. **Ověřuje to nejrizikovější část**, tedy správnost výpočtu a práci s chybějícími daty. UI nebo
   architektura rizikem nejsou.
2. **Malý počet proměnných:** jeden druh, jedna fáze a jeden standard. Případnou odchylku od výpočtu
   specialisty lze dohledat k jedné příčině (data, metoda ME, přepočet požadavků, zaokrouhlení).
3. **Dospělý zdravý pes** je fáze s nejnižším klinickým rizikem a s nejlépe doloženými vstupy.
   Růst je kvůli limitům Ca rizikovější `[Hazewinkel1985]`. Kočky potřebují taurin, pro který chybí
   data o surovinách `[Pion1987]`.
4. **Jádro bez Djanga** se po validaci beze změny použije v plné aplikaci. Nic se nezahazuje.
5. Výstup validace (protokol + golden testy) je **trvalá pojistka**: každá budoucí změna kódu nebo dat
   se proti němu automaticky otestuje.

**Kritérium úspěchu MVP-0:** Specialista potvrdí na 5–10 dávkách shodu v dohodnuté toleranci. Všechny
odchylky budou vysvětlené. U žádné živiny s chybějícími daty se neobjeví číselné hodnocení. Teprve
potom má smysl stavět UI (M4–M5).
