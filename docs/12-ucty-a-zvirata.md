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
  nejnovější nahoře, a grafy hmotnosti a BCS, §12.11), zdravotní stavy z číselníku, cílová hmotnost se stavem *orientační* /
  *potvrzeno veterinářem*, sdílení s veterinářem a úroveň upozornění (§12.5);
- **přehled** (`/prehled/`, přihlášený uživatel na `/` je přesměrován sem): karty vlastních zvířat
  a u veterináře oddíl *Sdílená zvířata*. Karta ukazuje jméno, druh, věk, poslední hmotnost
  a poslední BCS s datem, odznak úrovně upozornění, od dvou měření miniaturní graf hmotnosti
  (sparkline) s textem a odkaz na stránku sledování (§12.11);
- **knihovna zdrojů** (aplikace `catalog`): veřejné stránky `/zdroje/` s odbornými zdroji, úrovní
  důkazů a stavem jejich ověření; nezávisí na přihlášení ani na zvířatech
  ([13](13-zdroje-v-aplikaci.md)).

Kalkulačka, recepty, suroviny, standardy, výpočet energie a nutriční rozbor jsou **odložené**
(§12.7). Kód webové aplikace neimportuje `nutricalc` ani `refdata` (hlídá test
`tests/backend/test_backend_static.py`) a neobsahuje žádné hodnoty energie ani živin. Tentýž test
hledá v kódu a šablonách aplikace `animals` jen jednotky energie (`kcal`, `kJ`) a zápisy vzorců
RER/MER; jiná čísla (koeficienty, mg živin) nepozná, ta hlídá revize kódu.

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
| Zobrazit profil, měření, stavy a grafy hmotnosti a BCS (`VIEW`) | ✔ | ✔ | 404 | přihlášení |
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
- **Změny stavu jen metodou POST s tokenem CSRF.** Smazání zvířete, měření, odebrání stavu
  a zrušení sdílení má potvrzovací stránku (GET nic nemění). Potvrzení cílové hmotnosti přijímá
  jen POST (GET = 405).
- **Stránky přihlášeného uživatele** se neukládají do mezipaměti prohlížeče (`Cache-Control:
  private, no-store`, middleware `NoStoreForSignedInUsersMiddleware`): po odhlášení na sdíleném
  počítači je nejde zobrazit tlačítkem Zpět.
- Majitel, který je zároveň veterinářem, své zvíře sám potvrdit nemůže a nemůže ho sdílet sám se sebou.
- Správce v administraci vidí a mění vše (§12.8).

Testy: `tests/backend/test_animals_permissions.py` (každý pohled × každá role × GET a POST,
POST-only, CSRF).

## 12.4 Data zvířete 🛠

Modely odpovídají docs/07 §7.4 **bez nutričních vazeb** (`preferred_standard_profile`,
`standard_choice_reason` přibudou s kalkulačkou). Odchylky od návrhu v §7.4:

- `uuid` pro adresy (`Animal`, `BodyMeasurement`, `AnimalShare`);
- alergie jako `JSONField` (seznam textů; ve formuláři text oddělený čárkami, normalizovaný na
  malá písmena a bez duplicit) místo `ArrayField`;
- `medications_affecting_diet` není samostatné pole (stav `MEDICATION_AFFECTING_DIET` + poznámka);
  `AnimalHealthCondition` má navíc pole `note`;
- `HealthCondition.source` (vazba na `ScientificSource`) nahrazuje textové pole `source_note`
  a přibyl popis `description_cs`: katalog zdrojů zatím neexistuje;
- `HealthCondition.mode` používá vlastní volby `ConditionMode` (`EXPERT_REQUIRED`, `BLOCKED`),
  ne celé `WarningLevel`, protože jiné úrovně stav mít nesmí;
- abstraktní `TimeStamped` se nepoužívá: `Animal` má `created_at` a `updated_at`, ale ne
  `created_by` (zakládá vždy majitel); `BodyMeasurement` má `created_at` a `created_by`, ale ne
  `updated_at` (měření se neupravují); `AnimalHealthCondition` časové údaje nemá. Kdo a kdy
  záznam změnil, ukládá u všech modelů historie (`django-simple-history`).

**Kontroly** (metoda `clean()` s českými hláškami a zároveň `CheckConstraint` v databázi, kde to jde):
datum narození ani měření není v budoucnosti; měření ani začátek zdravotního stavu nesmí být
dřívější než přesné datum narození (u data označeného jako odhad se nekontroluje); odhad data
narození jen se zadaným datem; velikostní kategorie jen u psa; březost a laktace jen u samice;
BCS 1–9; MCS a další volby jen z číselníků; potvrzená cílová hmotnost musí mít hodnotu,
veterináře a čas potvrzení a nově zadané potvrzení musí patřit účtu s rolí `vet`; změnu druhu
odmítne, pokud uložená měření nesedí do mezí nového druhu.

**Nové zvíře** nemá předvyplněný fyziologický stav: majitel ho musí zvolit, aby štěně nebo kotě
neskončilo jako „dospělé zvíře“ jen proto, že výchozí volbu nezměnil (§12.5).

**Technické meze hmotnosti** (konstanta `WEIGHT_BOUNDS_KG`): zachytávají jen překlepy (gramy místo
kilogramů). **Nejsou to nutriční ani referenční data.** 🩺 ke schválení.

| Druh | Povolená hmotnost (kg) |
|---|---|
| pes | 0,5–120 |
| kočka | 0,5–15 |

Platí pro hmotnost v měření, očekávanou hmotnost v dospělosti a cílovou hmotnost. Databáze
u měření hlídá obálku 0,5–120 kg, mez podle druhu kontroluje `clean()`.

**Aktivita** se volí ze čtyř slovních popisů (nízká, střední, střední s vysokou zátěží, vysoká)
bez jakýchkoli koeficientů. Kategorie pocházejí z tabulky **psů** v docs/05 §5.3; tabulka koček
má jiné situace (štíhlá aktivní kočka, nižší potřeba u kastrovaných a kočky v bytě). Aplikace
zatím nabízí stejné čtyři popisy i u koček; jak je u koček popsat a přiřadit situacím docs/05,
rozhodne specialista před kalkulačkou (§12.9).

**Cílová hmotnost** (docs/05 §5.3, docs/08 §8.7) je *orientační* (`UNVERIFIED`), dokud ji
nepotvrdí veterinář se sdílením (`VET_CONFIRMED` + kdo a kdy). Pravidla:

- Potvrzení odešle i hodnotu, kterou veterinář viděl. Kontrola i zápis běží nad řádkem zvířete
  zamčeným v databázi (`SELECT … FOR UPDATE`); úprava profilu majitelem zamyká týž řádek. Když se
  hodnota mezitím změnila, aplikace potvrzení odmítne; potvrzení zapsané během majitelovy úpravy
  se nepřepíše starými údaji (test `test_animals_concurrency.py`).
- Změní-li se **cílová hmotnost, druh nebo fyziologický stav**, stav se vrátí na *orientační*
  a potvrzení se smaže. Platí to pro každou cestu úpravy (formulář majitele i administrace),
  protože to dělá `Animal.clean()`. Veterinář potvrdil hodnotu pro zvíře, jak bylo popsané.
- V administraci jsou údaje o potvrzení jen ke čtení: potvrdit může jen veterinář se sdílením.
- Smaže-li veterinář účet nebo mu správce odebere roli `vet`, jím potvrzené cílové hmotnosti se
  vrátí na *orientační* (potvrzení bez dohledatelného veterinárního lékaře neplatí). 🩺 §12.9.

**Měření** zapsané veterinářem se ukládá jako *posoudil: veterinární lékař*. Jeho e-mail vidí
majitel a veterinář sám; další veterináři, se kterými majitel zvíře sdílí, vidí jen
„veterinární lékař“ (§12.6, minimalizace). Totéž platí pro e-mail u potvrzené cílové hmotnosti.
Měření se neupravují; chybné měření majitel smaže a zapíše znovu.

**Zdravotní stavy** se vybírají z číselníku `HealthCondition`, který naplní migrace
`animals.0002_seed_health_conditions` podle docs/09 §9.2. Migrace `0003` zapíše výchozí stav
číselníku do historie, takže první úprava specialistou zůstane vedle původních hodnot. Zpětná
migrace `0002` smaže jen stavy, které nemá zapsané žádné zvíře. Pole *Omezení stravy podle
veterináře* aplikace jen zobrazí, nic z něj nevyvozuje.

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
| Podle data narození mladší 12 měsíců, ale stav „dospělé zvíře“ | 🩺 | docs/09 §9.2 (růst); **odchylka**, viz níže |
| Žádné měření s BCS | ⓘ Informativní doporučení | docs/09 §9.2 (BCS nezadané) |
| Zadaná cílová hmotnost není potvrzená veterinářem | ⓘ | docs/05 §5.3, docs/08 §8.7 |
| Nic z uvedeného | ○ Bez upozornění v evidenci | – |

- „Poslední BCS / MCS“ je nejnovější měření, které danou hodnotu obsahuje (novější měření bez BCS
  starší BCS nepřepíše). Stáří měření se zatím nehodnotí.
- *Bez upozornění v evidenci* je záměrně neutrální (šedá, ne zelená, docs/08 §8.1) a stránka
  výslovně říká, že to neznamená zdravé zvíře ani vhodnou stravu. Žádný text neslibuje bezpečnost
  ani úplnost (test `test_reasons_do_not_promise_safety`).
- U úrovní ⛔ a 🩺 stránka zvířete doporučí majiteli poradit se s veterinárním lékařem, nejlépe
  s veterinárním nutričním specialistou. Veterinář se sdílením vidí místo toho text pro
  veterináře (zvíře je v pásmu, kde má výživu naplánovat veterinář nebo specialista).
- Panel upozornění ukáže každou úroveň jednou (ikona + text + barva) a pod ní její důvody, od
  nejzávažnější. Texty důvodů úroveň neopakují. U ⛔ panel dodá, že pro zvíře v tomto stavu
  aplikace automatický výpočet dávky nenabídne a kalkulačka zatím není k dispozici. Štítek ⛔
  „Automatický výpočet nelze doporučit“ je převzatý z docs/08 §8.6 (🩺 §12.9).
- Důvody u BCS čtou zadané skóre, nestanovují diagnózu: „Poslední zadané BCS je 8/9 (ze dne …),
  což na devítibodové škále odpovídá obezitě.“ (1–2 výrazná podvýživa, 3 podváha, 6–7 nadváha,
  8–9 obezita; shodně se škálou ve formuláři měření, 🩺 §12.9).
- **Odchylka od docs/09 §9.2:** docs/09 dává růstu (štěně, kotě) v MVP ⛔. Zadání této iterace
  určilo pro „mladší 12 měsíců, ale stav dospělé zvíře“ úroveň 🩺; aplikace ji drží jako pojistku
  a hlavní ochranou je, že nové zvíře nemá předvyplněný stav (§12.4). Úroveň i hranici
  12 měsíců (velká a obří plemena rostou déle) musí schválit specialista (§12.9).
- Alergie zapsané v profilu (pole *Alergie a nesnášenlivosti*) úroveň nemění; stav
  `FOOD_ALLERGY` (🩺) se počítá, jen když je zadaný jako zdravotní stav. Formulář a stránka
  zvířete proto u vyplněných alergií bez tohoto stavu napoví, ať majitel potravní alergii
  zjištěnou veterinářem zadá i jako zdravotní stav (🩺 §12.9).
- **Neimplementováno:** „rychlý úbytek hmotnosti“ z §9.2 (chybí odborně stanovený práh; ani
  stránka sledování, §12.11, změnu hmotnosti nehodnotí) a omezení pravidla MCS na seniory
  (pravidlo platí pro každý věk, přísnější varianta).

Testy: `tests/backend/test_animals_attention.py` (každé pravidlo zvlášť, kombinace, věk).

## 12.6 Ochrana osobních údajů (GDPR) 🛠

| Funkce | Jak |
|---|---|
| Export (čl. 15 a 20) | *Můj účet → Stáhnout moje data (JSON)*. Oddíl `account`: profil, role, úspěšná přihlášení, počitadla neúspěšných pokusů o přihlášení (čas, IP adresa, prohlížeč; bez dat odeslaného formuláře) a případný protokol jednotlivých pokusů. Oddíl `animals`: vlastní zvířata se všemi měřeními, zdravotními stavy, sdíleními a historií změn každého záznamu; u veterináře seznam přijatých sdílení (jen UUID zvířete a data, bez údajů majitele). Jiní uživatelé se v exportu objeví jen takto: e-mail veterinárního lékaře, se kterým uživatel zvíře sdílel (sdílení, potvrzení cílové hmotnosti, autor měření nebo změny); kdokoli jiný (např. správce, který záznam upravil v administraci) jen rolí „správce aplikace“ nebo „jiný uživatel“, bez e-mailu. Oddíl `catalog`: zdroje, u kterých je uživatel zapsán jako ověřovatel, a změny zdrojů, které provedl v administraci ([13](13-zdroje-v-aplikaci.md) §13.8) |
| Výmaz (čl. 17) | Smazání účtu smaže všechna zvířata uživatele, jejich měření, stavy, sdílení **i historii změn** (`cascade_delete_history`) a záznamy o přihlášení (`django-axes`). Smazání jednoho zvířete, měření nebo stavu maže i jeho historii. V protokolu administrace zůstane záznam o úpravě (kdo, kdy, která pole), ale text smazaného objektu (e-mail, jméno zvířete) se nahradí „[smazaný záznam]“. Úklid běží v signálu `post_delete`, tedy i při smazání účtu správcem v administraci a při mazání neaktivovaných registrací |
| Smazání účtu kurátora zdrojů | Zdroj, který kurátor ověřil, zůstane (je to veřejný odborný záznam); pole *ověřil* se vymaže i z historie změn zdroje a datum ověření zůstane ([13](13-zdroje-v-aplikaci.md) §13.3) |
| Neaktivované registrace | Registraci lze založit na cizí e-mail; neaktivovaný účet smaže příkaz `purge_pending_accounts` po 7 dnech (`PENDING_ACCOUNT_RETENTION`, spouští se denně, README) |
| Smazání účtu veterináře | Zaniknou sdílení, která dostal (i s historií). Jím zapsaná měření zůstanou majiteli, jen bez vazby na účet. Jím potvrzené cílové hmotnosti se vrátí na *orientační*. Stránka smazání účtu to veterináři předem vysvětlí |
| Sdílení | Výslovné, jen s účtem s rolí `vet`, kdykoli odvolatelné; odvolání platí okamžitě. Záznam o odvolaném sdílení zůstává (kdo, komu, od kdy do kdy) do smazání zvířete nebo účtu |
| Minimalizace | Veterinář vidí e-mail a jméno majitele, profil, měření a stavy sdíleného zvířete; nic dalšího. E-maily jiných veterinářů (autor měření, kdo potvrdil cílovou hmotnost) mu aplikace neukáže. Formulář sdílení to majiteli před udělením souhlasu vypíše |

## 12.7 Co zatím není 🛠

- Kalkulačka denní dávky, recepty, suroviny, standardy, výpočet energie, nutriční rozbor, PDF
  (odloženo na žádost zadavatele; navazuje na M1 a M3, docs/10).
- HTMX, REST API (docs/07 §7.8), 2FA pro role `vet`, `data_curator` a `nutrition_reviewer`
  (docs/07 §7.7). Grafy hmotnosti a BCS už jsou (§12.11); chybí trendová upozornění, návrh úpravy
  energie a graf MCS (§12.11).
- E-mailové oznámení veterináři o novém sdílení, žádost veterináře o sdílení, převod zvířete na
  jiného majitele, více majitelů jednoho zvířete.
- Úprava uloženého měření (jen smazání a nový zápis).
- Pravidlo „rychlý úbytek hmotnosti“ (§12.5, §12.11) a jakákoli trendová upozornění.
- Žádost o roli veterinárního lékaře v aplikaci: veterinář zatím píše na adresu správce
  (`DJANGO_CONTACT_EMAIL`, patička a stránka *Můj účet*), správce roli přidělí v administraci.
- Omezení počtu registrací z jedné adresy a celkový limit neúspěšných přihlášení z jedné IP
  adresy (§12.10).

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
   (docs/07 §7.7: zálohy 30 dní a měsíční 12 měsíců). Podklady pro rozhodnutí
   (retence, obnova vrací smazané účty, záznam o výmazech): [13-nasazeni-a-provoz.md](13-nasazeni-a-provoz.md) §13.14.
7. Ověření veterinárního lékaře: role `vet` se přiděluje ručně; jak správce ověří, že jde o lékaře.
8. Doba uchování neaktivovaných registrací (pracovně 7 dní, `PENDING_ACCOUNT_RETENTION`). Jde
   o údaje osoby, která registraci možná nezaložila.
9. Export majitele obsahuje e-maily veterinářů, se kterými zvíře sdílel (sdílení, potvrzení,
   autor měření a změn); správce je v exportu jen rolí. Je tento rozsah správný?
10. Protokol administrace: po výmazu se text objektu (e-mail, jméno zvířete) nahradí
    „[smazaný záznam]“, záznam o úkonu správce zůstává. Stačí anonymizace, nebo smazat celý záznam?
11. Relace (`django_session`) smazaného uživatele na jiných zařízeních zůstanou do vypršení
    (bez platného účtu jsou nepoužitelné); prošlé relace maže `manage.py clearsessions`.
    Doba uchování neúspěšných pokusů o přihlášení (`django-axes`, nyní do vypršení zámku nebo
    úspěšného přihlášení ze stejné adresy).
12. Text o zálohách po výmazu v *Ochraně osobních údajů* a na stránce po smazání účtu (zástupné
    místo `[DOPLNÍ PRÁVNÍK]`) a kontakt na správce aplikace (`[DOPLNÍ PROVOZOVATEL]`).

## 12.9 Body pro specialistu 🩺

1. Technické meze hmotnosti 0,5–120 kg (pes) a 0,5–15 kg (kočka) (§12.4).
2. Číselník zdravotních stavů a jejich úrovně, zejména doplněný `OTHER_CHRONIC` a rozdělení
   pankreatitidy a hyperlipidémie. Popis u `FOOD_ALLERGY` („Aplikace umí jen filtrovat alergeny“)
   předjímá kalkulačku; dnes aplikace alergeny jen eviduje.
3. Upozornění „mladé zvíře ve stavu dospělé“: úroveň 🩺 podle zadání, docs/09 §9.2 dává růstu ⛔
   (§12.5, odchylka). Má být ⛔? A hranice 12 měsíců: velká a obří plemena rostou déle, hranice
   by mohla záviset na velikostní kategorii.
4. Mapování BCS na úrovně (1–2 ⛔, 3 a 6–9 🩺, 4–5 bez upozornění) a MCS pro všechny věkové skupiny.
5. Práh pro „rychlý úbytek hmotnosti“ (kolik % za jaké období, od kolika měření, jak zacházet
   s kolísáním způsobeným vážením a hydratací). Bez něj aplikace žádnou změnu hmotnosti nehodnotí
   a neupozorňuje na ni: stránka sledování jen popisuje, co bylo zapsáno (§12.11). Po stanovení
   prahu by se upozornění mělo objevit na stránce zvířete i na kartě přehledu.
6. Všechny texty důvodů upozornění, slovní popisy aktivity a popisy BCS a MCS ve formuláři.
7. Co přesně potvrzení cílové hmotnosti veterinářem znamená a kdy má propadnout (např. po určité
   době nebo po změně BCS). Dnes propadá při změně hodnoty, druhu nebo fyziologického stavu, při
   smazání účtu veterináře a při odebrání role `vet` (§12.4). Mají propadat i při změně velikostní
   kategorie nebo kastrace?
8. Popisy aktivity u koček a jejich přiřazení k situacím koček v docs/05 §5.3 (§12.4); zda
   kočkám nabízet „vysokou“ aktivitu (pracovní zvíře).
9. Mají alergie zapsané jen v profilu zvýšit úroveň upozornění (např. ⓘ s návrhem zadat stav
   `FOOD_ALLERGY`), nebo stačí nápověda (§12.5)?
10. Slovní výklad BCS v důvodech upozornění (6–7 nadváha, 8–9 obezita) (§12.5).
11. Štítek ⛔ „Automatický výpočet nelze doporučit“ (docs/08 §8.6) se ukazuje i u zvířete,
    ačkoli kalkulačka zatím není. Má mít pro profil zvířete vlastní znění?
12. Popisné texty stránky sledování (§12.11): věta „Zda je změna žádoucí, posoudí veterinární
    lékař.“, zda uvádět změnu i v procentech (nemůže působit jako hodnocení?), nabídka období
    30 dní, 90 dní, 1 rok a vše a to, že graf vzniká až ze dvou měření.
13. Pásmo „4–5 z 9“ jako podklad grafu BCS (docs/05 §5.3: pásmo, pro které je výpočet z aktuální
    hmotnosti určen). Stránka ho neoznačuje za „ideální“ ani „zdravé“. Je takové pojmenování
    v pořádku, nebo se má pásmo nekreslit? Formulář měření (§12.4) dosud popisuje BCS 4–5 jako
    „ideální kondici“: slovo sjednotit.
14. Minimální rozsah osy hmotnosti v grafu (nejméně 1 kg nebo 5 % nejvyšší zobrazené hmotnosti),
    aby kolísání o desítky gramů nevypadalo jako velká změna. Potvrdit hodnoty.
15. Má stránka sledování připomínat doporučenou četnost vážení (docs/05 §5.6: hmotnost 1× týdně,
    BCS 1× za 2–4 týdny) a zobrazovat svalovou kondici (MCS) v grafu? Zatím je MCS jen v tabulce
    a žádná připomínka se nezobrazuje.

## 12.10 Zabezpečení účtů a zbytková rizika 🛠

- **Předem založený cizí účet (pre-hijacking):** kdokoli může registrovat cizí e-mail. Opakovaná
  registrace neaktivovaného účtu nastaví heslo z poslední registrace a aktivace odkazem vyžaduje
  právě toto heslo. Účet tedy aktivuje jen ten, kdo má odkaz (schránku) a zná heslo; nikdy
  majitel schránky s heslem útočníka. Zbytkové riziko: útočník může opakovanou registrací měnit
  heslo neaktivovaného účtu a aktivaci tím zdržovat (aplikace pak poradí zaregistrovat se znovu).
- **Výčet účtů podle doby odpovědi:** stránky s e-mailovou adresou (registrace, nový aktivační
  odkaz, obnova hesla) ukazují vždy stejnou zprávu a v produkci odesílají e-mail až po odpovědi
  (`ACCOUNT_EMAIL_IN_BACKGROUND`, vlákno). Zbytek: rozdíly v práci databáze v řádu milisekund;
  e-mail, který se právě odesílá, se při tvrdém ukončení procesu ztratí (chyby odeslání se
  zapisují do logu).
- **Zahlcení cizí schránky:** nejvýše jeden e-mail daného druhu za 120 s a nejvýše 10 e-mailů
  z účtu denně na jeden účet; limity jsou v databázové cache sdílené všemi procesy
  (`createcachetable`, README).
- **Hádání hesla:** `django-axes` zamyká kombinaci e-mail + IP adresa po 5 chybách na 1 hodinu
  (podle zadání). Nebrání tomu, aby jedna adresa zkoušela několik běžných hesel u mnoha účtů
  (password spraying); zámek jen podle IP by zase zamykal celé sítě za NAT. Další omezení
  zvážit před ostrým provozem (§12.7). Za proxy musí být nastaven `DJANGO_TRUSTED_PROXY_COUNT`,
  jinak produkční nastavení odmítne start (jinak by zámek platil jen podle e-mailu a kdokoli by
  mohl zamknout cizí účet).

## 12.11 Sledování hmotnosti a kondice (grafy) 🛠

Obrazovka *Sledování hmotnosti a kondice* z docs/08 §8.3 je stránka `/zvirata/<uuid>/hmotnost/`
(`animals:tracking`). Vede na ni tlačítko *Graf hmotnosti a kondice* a odkaz v sekci měření na
detailu zvířete a odkaz *Hmotnost a kondice* na kartě přehledu. Drobečky: Přehled › zvíře ›
Sledování hmotnosti a kondice. Stránka je **jen popisná**: ukazuje, co bylo zapsáno. Nehodnotí
vývoj hmotnosti ani kondice, nepočítá žádné míry změny proti prahům a nedává doporučení ke krmení.

| Oblast | Pravidlo |
|---|---|
| Oprávnění | `VIEW` přes `get_animal_for` (§12.3): majitel a veterinář s aktivním sdílením 200, ostatní 404, nepřihlášený je přesměrován na přihlášení. Jen metoda GET (POST = 405), stránka se neukládá do mezipaměti prohlížeče |
| Období | Parametr `?obdobi=` s hodnotami `30`, `90`, `365`, `vse`; výchozí je 90. Jiná hodnota (i chybějící) vrací výchozí období bez chyby. Pevné období je přesně tolik kalendářních dnů končících dnešním dnem (30 dní = dnes a 29 předchozích dnů), *Vše* začíná prvním měřením. Osa x vždy končí dnešním dnem, takže dlouhá pauza od posledního měření je vidět. Přepínač jsou odkazy, zvolené období má `aria-current="true"`, je vyplněné, tučné a označené ✓ |
| Graf hmotnosti | Čára a body z měření v období, osa y v kg. Rozsah osy pokrývá data **i cílovou hmotnost** (čára je vždy v grafu) a nikdy nejde pod nulu; je nejméně 1 kg nebo 5 % nejvyšší hodnoty široký, aby drobné kolísání nevypadalo jako velká změna (🩺 §12.9, bod 14). Značky osy y jsou kulatá čísla (krok 1, 2 nebo 5 × mocnina deseti), osa x má popisky ve dnech, pondělcích, měsících nebo letech podle délky období (nejvýše 7). Hodnota posledního bodu je popsaná vedle něj |
| Kdo měření zapsal | **Tvar značky**, ne jen barva: kolečko = majitel, kosočtverec = veterinární lékař (barva se liší navíc). Legenda pod grafem popisuje jen tvary, které jsou nakreslené |
| Cílová hmotnost | Čárkovaná vodorovná čára s popiskem *cílová hmotnost (orientační)* nebo *cílová hmotnost (potvrzeno veterinářem)* podle `target_weight_status` (docs/05 §5.3) a hodnotou. Nikdy se nenazývá „ideální“. Bez zadané cílové hmotnosti se nekreslí |
| Graf BCS | Samostatné body (bez spojnice) na celé devítibodové ose 1–9, jen měření, která mají BCS. Podkladem je pásmo 4–5 z 9 (od 3,5 do 5,5), popsané *pásmo 4–5 z 9* a v legendě. Je to vodítko ze škály (docs/05 §5.3), ne hodnocení: text pod grafem říká, že skóre i jeho význam posoudí veterinární lékař. Měření bez BCS graf vynechá |
| Souhrn | Počet měření v období, první a poslední hmotnost s daty, rozdíl v kg a v % (vůči první hmotnosti, na jedno desetinné místo) a počet dní mezi nimi. Věta: *Změna hmotnosti za zvolené období: −1,2 kg (−3,8 %). Zda je změna žádoucí, posoudí veterinární lékař.* Čísla a věta se zobrazí od dvou měření |
| Více měření v jeden den | Všechna se nakreslí a vypíší; první a poslední hmotnost se řídí pořadím zápisu (poslední zapsané měření dne je „poslední“) |
| Tabulka | **Vždy** pod grafy: datum, hmotnost, BCS, MCS, posoudil, poznámka, nejnovější nahoře. Obsahuje všechna měření ze zobrazeného období, tedy stejná data jako grafy (MCS jen zde). Počet měření mimo období a odkaz *zobrazit vše* jsou nad tabulkou. E-mail veterináře ve sloupci *Posoudil* vidí jen majitel a veterinář, který měření zapsal (stejné pravidlo jako na detailu, §12.6) |
| Prázdné stavy | Méně než dvě měření v období (graf hmotnosti) nebo méně než dvě hodnocení BCS (graf BCS): místo grafu vysvětlení (žádné měření, jediné měření s hodnotou a datem, měření jen mimo období) a tlačítko *Zapsat měření* na formulář měření. Tabulka zůstává |
| Dostupnost | Každý graf je `<figure>` s `<svg role="img">`, `<title>` (jméno zvířete a období) a `<desc>` (období, počet měření, první a poslední hmotnost, změna s větou o veterináři, cílová hmotnost, význam tvarů). Grafy jsou v posuvné oblasti s `tabindex="0"` (na úzkém displeji se posouvají do stran, text zůstává čitelný). Nadpisy jdou po úrovních (h1, h2, h3), tabulka je alternativa pro čtečky |
| Barvy | Barvy jsou vlastnosti CSS (`--chart-*`, světlý i tmavý režim). Značky, čáry a osy mají proti pozadí grafu kontrast nejméně 4,1 : 1 (požadavek 3 : 1; mřížka je jen pomocná a záměrně nenápadná), text grafu nejméně 7 : 1. Dvojice barev značek (majitel a veterinář) prošla kontrolou odlišitelnosti (OKLab, simulace barvosleposti). V režimu vysokého kontrastu se použijí systémové barvy |
| Bezpečnost | Jméno zvířete se vypisuje jen automaticky escapovanou šablonou (i v `<title>` SVG). Grafy neobsahují inline styly ani skripty (CSP `style-src 'self'`, `script-src 'self'`): vzhled řídí třídy v `app.css`. Texty v SVG jsou čísla, data a pevné popisky, nikdy text zadaný uživatelem |

**Přehled (dashboard).** Karta od dvou měření ukáže miniaturní graf (skrytý před čtečkami
obrazovky, `aria-hidden`) z nejnovějších 12 měření a vedle něj text *Vývoj: poslední hmotnost
21 kg, změna −0,4 kg za 33 dní.* (změna = poslední minus první z těchto měření, dny mezi nimi).
Přehled načítá měření všech zvířat jedním dotazem (`prefetch_related`), takže počet dotazů nezávisí
na počtu zvířat (test `django_assert_max_num_queries`). Karta čte všechna měření zvířete, protože
úroveň upozornění potřebuje poslední BCS a MCS, které mohou být starší než posledních 12 měření:
omezení na posledních N řádků v databázi by je mohlo skrýt.

**Technika.** Výpočet geometrie je v čistém modulu `animals/charts.py` (vstup: měření, období,
dnešní datum, volitelně cílová hmotnost se stavem; výstup: neměnné `dataclass`y se body, značkami
os, souřadnicemi SVG a souhrnem). Dnešní datum dostává jako argument, hodinky nečte. Hmotnosti,
rozdíly, procenta a hodnoty os jsou `Decimal` s pevným kontextem; `float` je jen v pixelových
souřadnicích (hlídá `tests/backend/test_backend_static.py`). Souřadnice se v šablonách vypisují
s `{% localize off %}`, jinak by je české nastavení psalo s desetinnou čárkou.

**Co zatím není.** Trendová upozornění a pravidlo „rychlý úbytek hmotnosti“ (práh musí stanovit
specialista, §12.9 bod 5), proložená trendová přímka, návrh úpravy energie z docs/05 §5.6 a docs/08
§8.3 (patří ke kalkulačce), graf svalové kondice (MCS jen v tabulce), připomínky vážení, interaktivní
popisky (jen prohlížečem zobrazený popisek bodu bez JavaScriptu) a export grafu.

Testy: `tests/backend/test_animals_charts.py` (čisté funkce a vlastnosti `hypothesis`: souřadnice
uvnitř oblasti grafu, x neklesá s datem, značky os pokrývají data, deterministický výstup),
`tests/backend/test_animals_tracking.py` (oprávnění, období, atributy SVG, tabulka, tvary značek,
popisek cílové hmotnosti, prázdné stavy, XSS) a `tests/backend/test_animals_dashboard.py`
(sparkline, počet dotazů).

