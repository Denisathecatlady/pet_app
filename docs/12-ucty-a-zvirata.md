# 12. Uživatelské účty, zvířata a sdílení s veterinářem (webová aplikace)

> Kapitola popisuje 🛠 implementovaný stav webové aplikace (aplikace `accounts`, `animals`, `core`
> v adresáři `backend/`). Texty upozornění, číselník zdravotních stavů a technické meze hmotnosti
> posoudí 🩺 specialista, právní texty a body v §12.8 právník.
> Legenda: ✅ ověřeno · 🟡 ověřit · 🛠 pracovní návrh · 🩺 posoudí vet. nutriční specialista.

## 12.1 Rozsah této iterace 🛠

Webová aplikace vede evidenci, **nepočítá** výživu. Obsahuje:

- **účty** (aplikace `accounts`): registrace s aktivací e-mailem, přihlášení e-mailem s ochranou
  proti hádání hesla (`django-axes`), změna a obnova hesla, profil, role, export osobních údajů
  a smazání účtu;
- **zvířata** (aplikace `animals`): profil psa nebo kočky, měření hmotnosti, BCS a MCS (tabulka,
  nejnovější nahoře), zdravotní stavy z číselníku, cílová hmotnost se stavem *orientační* /
  *potvrzeno veterinářem*, sdílení s veterinářem a úroveň upozornění (§12.5);
- **přehled** (`/prehled/`, přihlášený uživatel na `/` je přesměrován sem): karty vlastních zvířat
  a u veterináře oddíl *Sdílená zvířata*. Karta ukazuje jméno, druh, věk, poslední hmotnost
  a poslední BCS s datem a odznak úrovně upozornění.

Kalkulačka, recepty, suroviny, standardy, výpočet energie a nutriční rozbor jsou **odložené**
(§12.7). Kód webové aplikace neimportuje `nutricalc` ani `refdata` a neobsahuje žádné hodnoty
energie ani živin; obojí hlídá test `tests/backend/test_backend_static.py`.

## 12.2 Role 🛠

Role jsou skupiny Djanga (docs/07 §7.6), vytváří je migrace `accounts.0002_create_roles`.

| Role | Kdo ji přiděluje | Co v této iteraci umožňuje |
|---|---|---|
| `owner` (majitel zvířat) | registrace | Vlastní zvířata. Vlastnictví ale určuje vazba `Animal.owner`, ne skupina: zvíře může založit každý přihlášený uživatel a je pak jeho majitelem |
| `vet` (veterinární lékař) | jen správce v administraci (README, *Role veterinárního lékaře*) | Majitel s ním může sdílet zvíře. Přístup ke sdílenému zvířeti trvá, jen dokud má účet tuto roli **a** sdílení je aktivní |
| `data_curator`, `nutrition_reviewer` | správce | Zatím bez funkce (připraveno pro správu dat, docs/07 §7.6) |
| správce (`is_staff`, `is_superuser`) | `createsuperuser` | Administrace `/admin/` včetně historie změn všech záznamů |

## 12.3 Matice oprávnění 🛠

Všechny pohledy se zvířetem získávají zvíře jedinou funkcí `animals.permissions.get_animal_for`.
Zvíře, které uživatel vidět nesmí, vrací **404** (neprozradí ani, že existuje); viditelné zvíře
se zakázanou akcí vrací **403**. Nepřihlášený návštěvník je přesměrován na přihlášení.

| Akce (`Action`) | Majitel | Veterinář s aktivním sdílením | Veterinář se zrušeným sdílením nebo bez něj, jiný majitel | Nepřihlášený |
|---|---|---|---|---|
| Zobrazit profil, měření, stavy (`VIEW`) | ✔ | ✔ | 404 | přihlášení |
| Upravit profil, smazat měření (`EDIT`) | ✔ | 403 | 404 | přihlášení |
| Smazat zvíře (`DELETE`) | ✔ | 403 | 404 | přihlášení |
| Zapsat měření (`ADD_MEASUREMENT`) | ✔ (posoudil: majitel) | ✔ (posoudil: veterinář) | 404 | přihlášení |
| Potvrdit cílovou hmotnost (`CONFIRM_TARGET_WEIGHT`) | 403 | ✔ | 404 | přihlášení |
| Přidat, upravit, odebrat zdravotní stav (`MANAGE_CONDITIONS`) | ✔ | 403 | 404 | přihlášení |
| Sdílet a rušit sdílení (`MANAGE_SHARES`) | ✔ | 403 | 404 | přihlášení |
| Založit zvíře | každý přihlášený | – | – | přihlášení |

Další pravidla:

- **Adresy** obsahují veřejné UUID (`/zvirata/<uuid>/…`), nikdy celočíselné id. Měření a sdílení
  mají vlastní UUID, zdravotní stav se adresuje kódem z číselníku. Podřízený záznam se hledá vždy
  jen u daného zvířete (cizí záznam = 404).
- **Změny stavu jen metodou POST s tokenem CSRF.** Smazání zvířete, měření a odebrání stavu má
  potvrzovací stránku (GET nic nemění). Zrušení sdílení a potvrzení cílové hmotnosti přijímají jen
  POST (GET = 405).
- Majitel, který je zároveň veterinářem, své zvíře sám potvrdit nemůže a nemůže ho sdílet sám se sebou.
- Správce v administraci vidí a mění vše (§12.8).

Testy: `tests/backend/test_animals_permissions.py` (každý pohled × každá role × GET a POST,
POST-only, CSRF).

## 12.4 Data zvířete 🛠

Modely odpovídají docs/07 §7.4 **bez nutričních vazeb** (`preferred_standard_profile`,
`standard_choice_reason` přibudou s kalkulačkou). Odchylky od návrhu v §7.4: `uuid` pro adresy,
alergie jako `JSONField` (seznam textů; ve formuláři text oddělený čárkami, normalizovaný na malá
písmena a bez duplicit), `medications_affecting_diet` není samostatné pole (stav
`MEDICATION_AFFECTING_DIET` + poznámka).

**Kontroly** (metoda `clean()` s českými hláškami a zároveň `CheckConstraint` v databázi, kde to jde):
datum narození ani měření není v budoucnosti; odhad data narození jen se zadaným datem; velikostní
kategorie jen u psa; březost a laktace jen u samice; BCS 1–9; MCS a další volby jen z číselníků;
potvrzená cílová hmotnost musí mít hodnotu, veterináře a čas potvrzení; změnu druhu odmítne, pokud
uložená měření nesedí do mezí nového druhu.

**Technické meze hmotnosti** (konstanta `WEIGHT_BOUNDS_KG`): zachytávají jen překlepy (gramy místo
kilogramů). **Nejsou to nutriční ani referenční data.** 🩺 ke schválení.

| Druh | Povolená hmotnost (kg) |
|---|---|
| pes | 0,5–120 |
| kočka | 0,5–15 |

Platí pro hmotnost v měření, očekávanou hmotnost v dospělosti a cílovou hmotnost. Databáze
u měření hlídá obálku 0,5–120 kg, mez podle druhu kontroluje `clean()`.

**Aktivita** se volí ze čtyř slovních popisů (nízká, střední, střední s vysokou zátěží, vysoká;
kategorie docs/05 §5.3) bez jakýchkoli koeficientů.

**Cílová hmotnost** (docs/05 §5.3, docs/08 §8.7) je *orientační* (`UNVERIFIED`), dokud ji
nepotvrdí veterinář se sdílením (`VET_CONFIRMED` + kdo a kdy). Potvrzení odešle i hodnotu, kterou
veterinář viděl; když se mezitím změnila, aplikace potvrzení odmítne. Změní-li majitel hodnotu,
stav se vrátí na *orientační* a potvrzení se smaže. Smaže-li veterinář účet, jím potvrzené cílové
hmotnosti se také vrátí na *orientační* (potvrzení bez dohledatelné osoby neplatí).

**Měření** zapsané veterinářem se ukládá jako *posoudil: veterinární lékař* a ukazuje jeho e-mail.
Měření se neupravují; chybné měření majitel smaže a zapíše znovu.

**Zdravotní stavy** se vybírají z číselníku `HealthCondition`, který naplní migrace
`animals.0002_seed_health_conditions` podle docs/09 §9.2. Pole *Omezení stravy podle veterináře*
aplikace jen zobrazí, nic z něj nevyvozuje.

| Kód | Název | Úroveň |
|---|---|---|
| `CKD` | Chronické onemocnění ledvin (CKD) | ⛔ BLOCKED |
| `LIVER_DISEASE` | Onemocnění jater | ⛔ BLOCKED |
| `PANCREATITIS` | Pankreatitida | ⛔ BLOCKED |
| `HYPERLIPIDEMIA` | Hyperlipidémie | ⛔ BLOCKED |
| `DIABETES_MELLITUS` | Diabetes mellitus | ⛔ BLOCKED |
| `UROLITHIASIS` | Urolitiáza a onemocnění močových cest | ⛔ BLOCKED |
| `FOOD_ALLERGY` | Potravní alergie | 🩺 EXPERT_REQUIRED |
| `MEDICATION_AFFECTING_DIET` | Užívání léků ovlivňujících výživu | 🩺 EXPERT_REQUIRED |
| `OTHER_CHRONIC` | Jiné chronické onemocnění | 🩺 EXPERT_REQUIRED |

Řádek „Pankreatitida, hyperlipidémie“ z §9.2 je rozdělen na dva stavy. `OTHER_CHRONIC` v tabulce
§9.2 není: je to doplněná položka pro chronická onemocnění mimo seznam. Popisy jsou převzaté ze
sloupce „Proč“ v §9.2. Číselník lze upravit v administraci (změny se zaznamenávají).

**Historie změn** (docs/07 §7.6): všechny modely aplikace `animals` mají `django-simple-history`
(kdo, kdy, jaké hodnoty). Historie uživatelských záznamů se maže spolu se záznamem (§12.6).

## 12.5 Úroveň upozornění u zvířete 🛠 🩺

Funkce `animals.services.attention(animal)` vrací úroveň a seznam důvodů v češtině. Vyhodnocuje se
jen to, co je v evidenci; úroveň je nejvyšší z úrovní všech důvodů. Vzhled podle docs/08 §8.1
a §8.6: vždy ikona + text + barva.

| Pravidlo | Úroveň | Podklad |
|---|---|---|
| Fyziologický stav růst, březost nebo laktace | ⛔ Automatický výpočet nelze doporučit | docs/09 §9.2 (růst, březost, laktace); docs/01 §1.5 |
| Zdravotní stav s úrovní `BLOCKED` | ⛔ | docs/09 §9.2 |
| Poslední zadané BCS 1 nebo 2 | ⛔ | docs/09 §9.2 (BCS 1–2/9) |
| Zdravotní stav s úrovní `EXPERT_REQUIRED` | 🩺 Vyžaduje odborné posouzení | docs/09 §9.2 |
| Poslední zadané BCS 3 nebo 6–9 | 🩺 | docs/09 §9.2, docs/05 §5.3 |
| Poslední zadané MCS ukazuje jakoukoli ztrátu svalové hmoty | 🩺 | docs/09 §9.2 (MCS, `[WSAVA2011]`) |
| Podle data narození mladší 12 měsíců, ale stav „dospělé zvíře“ | 🩺 | docs/09 §9.2 (růst) |
| Žádné měření s BCS | ⓘ Informativní doporučení | docs/09 §9.2 (BCS nezadané) |
| Zadaná cílová hmotnost není potvrzená veterinářem | ⓘ | docs/05 §5.3, docs/08 §8.7 |
| Nic z uvedeného | ○ Bez upozornění v evidenci | – |

- „Poslední BCS / MCS“ je nejnovější měření, které danou hodnotu obsahuje (novější měření bez BCS
  starší BCS nepřepíše). Stáří měření se zatím nehodnotí.
- *Bez upozornění v evidenci* je záměrně neutrální (šedá, ne zelená, docs/08 §8.1) a stránka
  výslovně říká, že to neznamená zdravé zvíře ani vhodnou stravu. Žádný text neslibuje bezpečnost
  ani úplnost (test `test_reasons_do_not_promise_safety`).
- U úrovní ⛔ a 🩺 stránka zvířete doporučí poradit se s veterinárním lékařem, nejlépe
  s veterinárním nutričním specialistou.
- **Neimplementováno:** „rychlý úbytek hmotnosti“ z §9.2 (chybí odborně stanovený práh) a omezení
  pravidla MCS na seniory (pravidlo platí pro každý věk, přísnější varianta).

Testy: `tests/backend/test_animals_attention.py` (každé pravidlo zvlášť, kombinace, věk).

## 12.6 Ochrana osobních údajů (GDPR) 🛠

| Funkce | Jak |
|---|---|
| Export (čl. 15 a 20) | *Můj účet → Stáhnout moje data (JSON)*. Oddíl `animals`: vlastní zvířata se všemi měřeními, zdravotními stavy, sdíleními a historií změn každého záznamu; u veterináře seznam přijatých sdílení (jen UUID zvířete a data, bez údajů majitele). Údaje jiných uživatelů export neobsahuje |
| Výmaz (čl. 17) | Smazání účtu smaže všechna zvířata uživatele, jejich měření, stavy, sdílení **i historii změn** (`cascade_delete_history`). Smazání jednoho zvířete, měření nebo stavu maže i jeho historii |
| Smazání účtu veterináře | Zaniknou sdílení, která dostal (i s historií). Jím zapsaná měření zůstanou majiteli, jen bez vazby na účet. Jím potvrzené cílové hmotnosti se vrátí na *orientační*. Stránka smazání účtu to veterináři předem vysvětlí |
| Sdílení | Výslovné, jen s účtem s rolí `vet`, kdykoli odvolatelné; odvolání platí okamžitě. Záznam o odvolaném sdílení zůstává (kdo, komu, od kdy do kdy) do smazání zvířete nebo účtu |
| Minimalizace | Veterinář vidí e-mail a jméno majitele, profil, měření a stavy sdíleného zvířete; nic dalšího |

## 12.7 Co zatím není 🛠

- Kalkulačka denní dávky, recepty, suroviny, standardy, výpočet energie, nutriční rozbor, PDF
  (odloženo na žádost zadavatele; navazuje na M1 a M3, docs/10).
- Graf hmotnosti (zatím tabulka), HTMX, REST API (docs/07 §7.8), 2FA pro role `vet`, `data_curator`
  a `nutrition_reviewer` (docs/07 §7.7).
- E-mailové oznámení veterináři o novém sdílení, žádost veterináře o sdílení, převod zvířete na
  jiného majitele, více majitelů jednoho zvířete.
- Úprava uloženého měření (jen smazání a nový zápis).
- Pravidlo „rychlý úbytek hmotnosti“ (§12.5).

## 12.8 Body pro právníka

1. Texty *Podmínky užití* a *Ochrana osobních údajů* jsou koncepty se zástupnými místy
   `[DOPLNÍ PRÁVNÍK]`.
2. Právní základ zpracování údajů o zvířatech a o zdravotním stavu zvířete a zda je potřeba
   výslovný souhlas se sdílením s veterinářem (aplikace sdílí jen na výslovný pokyn majitele).
3. Předání e-mailu a jména majitele veterináři při sdílení.
4. Doba uchování záznamů o odvolaných sdíleních a historie změn (nyní do smazání zvířete nebo účtu)
   a záznamů o přihlášení (`django-axes`).
5. Přístup správců k datům v administraci (rozsah, záznam o přístupu, smluvní zajištění).
6. Záznamy o činnostech zpracování, zpracovatelé (hosting, e-mail), zálohy po výmazu
   (docs/07 §7.7: zálohy 30 dní a měsíční 12 měsíců).
7. Ověření veterinárního lékaře: role `vet` se přiděluje ručně; jak správce ověří, že jde o lékaře.

## 12.9 Body pro specialistu 🩺

1. Technické meze hmotnosti 0,5–120 kg (pes) a 0,5–15 kg (kočka) (§12.4).
2. Číselník zdravotních stavů a jejich úrovně, zejména doplněný `OTHER_CHRONIC` a rozdělení
   pankreatitidy a hyperlipidémie. Popis u `FOOD_ALLERGY` („Aplikace umí jen filtrovat alergeny“)
   předjímá kalkulačku; dnes aplikace alergeny jen eviduje.
3. Hranice 12 měsíců pro upozornění „mladé zvíře ve stavu dospělé“: velká a obří plemena rostou
   déle, hranice by mohla záviset na velikostní kategorii.
4. Mapování BCS na úrovně (1–2 ⛔, 3 a 6–9 🩺, 4–5 bez upozornění) a MCS pro všechny věkové skupiny.
5. Práh pro „rychlý úbytek hmotnosti“ (kolik % za jaké období).
6. Všechny texty důvodů upozornění, slovní popisy aktivity a popisy BCS a MCS ve formuláři.
7. Co přesně potvrzení cílové hmotnosti veterinářem znamená a kdy má propadnout (např. po určité
   době nebo po změně BCS).
