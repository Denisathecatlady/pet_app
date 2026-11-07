# 14. Administrace (správa aplikace)

> Kapitola popisuje 🛠 implementovaný stav **zabezpečení administrace** (role správců, jejich
> oprávnění, ochrana před zneužitím oprávnění, skrytá adresa, limity relací, dvoufázové ověření,
> záznam přístupů) a **správu uživatelů a rolí** (ověření veterinářů, žádosti subjektů údajů,
> zámky přihlášení, neaktivované registrace). Administrace je vestavěná administrace Djanga
> (aplikace `backoffice` a `accounts` v adresáři `backend/`), žádné vlastní rozhraní. Body pro
> právníka jsou v §14.9.
> Legenda: ✅ ověřeno · 🟡 ověřit · 🛠 pracovní návrh · 🩺 posoudí vet. nutriční specialista.

## 14.1 Rozsah a rozhodnutí 🛠

Zadavatel rozhodl, že se **rozšíří vestavěná administrace Djanga** (nestaví se samostatné
rozhraní) a že obsahuje: (a) uživatele a role, (b) správu dat a jejich schvalování, (c) provozní
přehled na úvodní stránce administrace, (d) zabezpečení správců. Všechno je česky (hlavička
*BARF Nutri – správa*, názvy, nápovědy, akce, zprávy).

Tato kapitola popisuje **(a) uživatele a role a (d) zabezpečení správců**: nejdřív základ, bez
kterého by administrace rozdávala přístup k osobním údajům a zdravotním údajům zvířat (§14.2 až
§14.8), potom správu uživatelů a rolí nad ním (§14.11 až §14.14). Správa dat a jejich schvalování
(b) a provozní přehled (c) zatím nejsou (§14.10). Nic z toho nepočítá výživu a nepřidává žádná
nutriční, energetická ani dávkovací čísla ([12](12-ucty-a-zvirata.md) §12.7).

| Oblast | Kde je v kódu | Kde je testovaná |
|---|---|---|
| Role, odvozené `is_staff` (§14.2) | `accounts/roles.py`, `accounts/staff.py`, `accounts/signals.py`, migrace `accounts.0003` | `test_staff_roles.py` |
| Matice oprávnění a synchronizace (§14.3) | `accounts/roles.py` (`ROLE_PERMISSIONS`), `accounts/role_permissions.py` | `test_role_permissions.py`, `test_admin_permissions.py` |
| Uživatelé v administraci (§14.4) | `accounts/admin.py` | `test_user_admin.py` |
| Skrytá adresa (§14.4) | `config/env.py`, `config/urls.py`, `config/settings/` | `test_admin_settings.py` |
| Relace správců (§14.5) | `accounts/session_policy.py`, `accounts/middleware.py` | `test_staff_session.py` |
| Dvoufázové ověření (§14.6) | `accounts/two_factor.py`, `accounts/two_factor_views.py`, `accounts/middleware.py`, `backoffice/admin_site.py` | `test_two_factor.py`, `test_two_factor_views.py`, `test_two_factor_admin.py` |
| Záznam přístupů (§14.7) | `backoffice/` | `test_admin_access_log.py` |
| Ověření veterinářů (§14.11) | `accounts/vet_verification.py`, `accounts/vet_admin.py`, `accounts/models.py`, stránka `/ucet/veterinar/` | `test_vet_verification.py`, `test_vet_verification_admin.py` |
| Žádosti subjektů údajů (§14.12) | `accounts/data_subject.py`, `accounts/data_subject_admin.py`, `accounts/deadlines.py`, `accounts/models.py` | `test_data_subject_requests.py`, `test_deadlines.py` |
| Zámky přihlášení (§14.13) | `backoffice/third_party_admin.py` | `test_lockout_admin.py` |
| Neaktivované registrace (§14.14) | `accounts/admin.py`, `accounts/services.py` | `test_pending_registrations_admin.py` |
| Vzhled stavů v administraci (§14.15) | `static/css/admin.css`, `templates/admin/` | `test_admin_colours.py` |

## 14.2 Role a odvozené `is_staff` 🛠

Role jsou skupiny Djanga ([12](12-ucty-a-zvirata.md) §12.2). Do administrace se smí přihlásit jen
účet s `User.is_staff`. **Příznak `is_staff` se nenastavuje ručně, je odvozený:**

> `is_staff` platí pro superuživatele a pro členy kterékoli skupiny správců
> (`accounts.roles.STAFF_ROLES`); pro všechny ostatní neplatí.

| Role (skupina) | Název | Skupina správců | Co smí v administraci |
|---|---|---|---|
| `owner` | Majitel zvířat | ne | nic (nepřihlásí se do administrace) |
| `vet` | Veterinární lékař | ne | nic |
| `support_admin` | Správce uživatelů | **ano** | uživatelé, odemykání přihlášení, ověření veterinářů a žádosti subjektů údajů (§14.3, §14.4, §14.11 až §14.14) |
| `data_curator` | Kurátor dat | **ano** | knihovna zdrojů: zobrazit, přidat, změnit |
| `nutrition_reviewer` | Odborný revizor výživy | **ano** | zdroje (jen zobrazit) a číselník zdravotních stavů (zobrazit, změnit) |
| superuživatel (`is_superuser`) | správce | (vždy) | vše, včetně přidělování rolí |

- `User.save()` odvodí příznak při každém uložení bez `update_fields` a při uložení, jehož
  `update_fields` obsahuje `is_superuser` nebo `is_staff`. Uložení jen jiných polí (např. `last_login`
  při přihlášení) příznak nepřepočítává.
- Přijímač `m2m_changed` na skupinách ho přepočítá při přidání, odebrání i vyprázdnění rolí, v obou
  směrech vazby (`user.groups` i `group.user_set`). Smazání skupiny a změna jejího názvu přepočítá
  členy také (smazaná nebo přejmenovaná skupina správců už členy správci nedělá).
- Pole `is_staff` je v administraci jen ke čtení a `create_user(is_staff=True)` ho neovlivní.
- Migrace `accounts.0003_support_admin_and_derived_staff` vytvoří skupinu `support_admin` a **přepočítá
  `is_staff` všem stávajícím účtům**. Kdo měl příznak ručně a není superuživatel ani člen skupiny
  správců, o přístup do administrace přijde; přidělte mu roli.
- Skupinu přiděluje jen superuživatel (§14.4). Registrace vytváří vždy jen roli `owner`.

## 14.3 Matice oprávnění 🛠

`accounts.roles.ROLE_PERMISSIONS` je **jediná závazná tabulka**: skupina → seznam oprávnění
`app_label.codename`. U každé role je v komentáři zdůvodnění. Funkce `sync_role_permissions`
(`accounts/role_permissions.py`) nastaví oprávnění každé skupiny z tabulky **přesně**:

- běží **po každém `migrate`** (přijímač `post_migrate` po poslední aplikaci, až Django vytvořil
  všechna oprávnění) a ručně příkazem `manage.py sync_role_permissions` (`--dry-run` jen vypíše změnu);
- je **idempotentní** (druhé spuštění nic nezmění) a ohlásí, co přidala a co odebrala (oprávnění,
  které někdo přidal skupině ručně, se odebere: změna patří do tabulky);
- **nikdy nesahá na uživatele ani superuživatele** (jen na oprávnění skupin v tabulce; skupiny,
  které v tabulce nejsou, nechá být);
- **neznámý kód oprávnění** (překlep, smazaný model) je srozumitelná chyba
  `UnknownPermissionError`, v příkazu `CommandError`, a nezmění se nic;
- ve zčásti zmigrované databázi, kde oprávnění ještě nejsou vytvořená, `post_migrate` chybějící
  řádky přeskočí a zapíše varování; příkaz je naopak chybou odmítne.

Tabulka níže je **výstup příkazu `manage.py print_role_matrix`** (test `test_role_permissions.py`
hlídá, aby se s kódem shodovala). Sloupce jsou role, které něco smějí; `owner` a `vet` nemají v
administraci žádné oprávnění.

<!-- role-matrix:begin -->
| Oprávnění | Kód | Správce uživatelů | Kurátor dat | Odborný revizor výživy |
|---|---|:---:|:---:|:---:|
| zobrazit: žádost subjektu údajů | `accounts.view_datasubjectrequest` | ✔ | – | – |
| přidat: žádost subjektu údajů | `accounts.add_datasubjectrequest` | ✔ | – | – |
| změnit: žádost subjektu údajů | `accounts.change_datasubjectrequest` | ✔ | – | – |
| Může provést výmaz účtu k žádosti | `accounts.erase_datasubjectrequest` | ✔ | – | – |
| Může vytvořit export osobních údajů k žádosti | `accounts.export_datasubjectrequest` | ✔ | – | – |
| zobrazit: uživatel | `accounts.view_user` | ✔ | – | – |
| změnit: uživatel | `accounts.change_user` | ✔ | – | – |
| zobrazit: žádost o ověření veterináře | `accounts.view_vetverificationrequest` | ✔ | – | – |
| Může schvalovat, zamítat a odebírat roli veterináře | `accounts.decide_vetverificationrequest` | ✔ | – | – |
| zobrazit: zdravotní stav (číselník) | `animals.view_healthcondition` | – | – | ✔ |
| změnit: zdravotní stav (číselník) | `animals.change_healthcondition` | – | – | ✔ |
| zobrazit: počítadlo neúspěšných přihlášení | `axes.view_accessattempt` | ✔ | – | – |
| smazat: počítadlo neúspěšných přihlášení | `axes.delete_accessattempt` | ✔ | – | – |
| zobrazit: odborný zdroj | `catalog.view_scientificsource` | – | ✔ | ✔ |
| přidat: odborný zdroj | `catalog.add_scientificsource` | – | ✔ | – |
| změnit: odborný zdroj | `catalog.change_scientificsource` | – | ✔ | – |

Role bez jakéhokoli oprávnění v administraci: Majitel zvířat (`owner`), Veterinární lékař (`vet`).
<!-- role-matrix:end -->

Zdůvodnění 🛠:

- **Správce uživatelů** řeší uživatele, zamčená přihlášení, žádosti o roli veterináře a žádosti
  subjektů údajů. Nemá **žádné oprávnění k zvířatům, měřením, zdravotním stavům a sdílení**: k
  vyřešení účtu, odemčení přihlášení ani výmazu účtu zdravotní údaje zvířat nepotřebuje
  (minimalizace, [12](12-ucty-a-zvirata.md) §12.8 bod 5). Nevidí záznam přístupů (nemá číst záznam
  o vlastním přístupu). Nemůže uživatele přidat ani smazat v seznamu uživatelů; účet smaže jen
  postupem pro žádost subjektu údajů (§14.12, jen účty, které nejsou správci) a neaktivovanou
  registraci starší než lhůta akcí v §14.14. Žádost o roli veterináře ani žádost subjektu údajů po
  zápisu nemůže změnit ani smazat: jsou to důkazy (žádost se řeší akcemi, §14.11, §14.12).
  Rozhodnout smí jen o cizí žádosti: o vlastní nikdy (čtyři oči).
- **Kurátor dat** spravuje knihovnu zdrojů; zdroj nemaže (citovaný zdroj nemizí potichu).
- **Odborný revizor výživy** čte zdroje a upravuje číselník zdravotních stavů, který řídí bezpečnostní
  bránu ([09](09-rizika.md) §9.2). Zvířata nevidí.
- **Superuživatel** vidí a smí všechno včetně záznamu přístupů a přidělování rolí. Je to účet
  s největším rizikem: mějte jich co nejméně (§14.6, §14.9).

Vlastní oprávnění (`decide_vetverificationrequest`, `export_datasubjectrequest`,
`erase_datasubjectrequest`) jsou v `Meta.permissions` modelů a matice je vypíše jejich českým
názvem. Nikdo kromě správce uživatelů a superuživatelů je nemá (test
`test_the_decision_permissions_belong_to_support_only`).

Jak matici **rozšířit**: přidejte kódy do `ROLE_PERMISSIONS` s komentářem, spusťte testy
(`test_role_permissions.py` ověří, že kódy existují), `manage.py migrate` nebo
`sync_role_permissions`, a znovu vložte výstup `print_role_matrix` mezi značky výše.

## 14.4 Uživatelé v administraci a skrytá adresa 🛠

### Ochrana před eskalací oprávnění

Nikdo, kdo není superuživatel, nesmí sobě ani jiným dát víc, než sám má. `accounts/admin.py`:

| Akce | Superuživatel | Správce uživatelů (a každý jiný správce, který dostal oprávnění ke změně uživatele) |
|---|---|---|
| Vidí v seznamu | všechny účty | **jen účty, které nejsou správci** (superuživatelé a správci se nezobrazí, ani ve vyhledávání a filtrech) |
| Mění | všechna pole kromě `is_staff` a hesla | jen **jméno, příjmení a aktivní účet** u uživatele, který není správce; e-mail je jen ke čtení |
| `is_superuser`, individuální oprávnění, role | smí měnit | **nejsou ve formuláři**, podvržený požadavek je ignoruje |
| Mění, deaktivuje nebo maže správce a superuživatele | ano | ne (účet pro něj neexistuje, odpověď je přesměrování jako u chybějícího záznamu) |
| Maže uživatele (stránka i hromadná akce *Odstranit vybrané*) | ano | **ne**, ani když skupina nebo uživatel dostal oprávnění `delete_user` |
| Přidává uživatele | ano (jen e-mail, bez hesla) | ne |
| Heslo | **nikdo ho nevidí ani nenastavuje** | totéž |
| Akce *Odeslat odkaz na obnovu hesla* | ano | ano (jen u uživatelů, které vidí) |
| Akce *Zrušit dvoufázové ověření* | ano | ne (akce se nenabízí) |
| Akce *Znovu odeslat aktivační e-mail*, *Smazat neaktivované registrace starší než lhůta* (§14.14) | ano | ano (jen u uživatelů, které vidí) |

- **Heslo.** Pole s heslem není ve formuláři nikoho a stránka pro zadání cizího hesla neexistuje
  (adresa `<id>/password/` byla odstraněna). Nový účet se zakládá jen z e-mailu (bez hesla). Heslo
  si uživatel nastaví sám přes odkaz z e-mailu. Akce *Odeslat odkaz na obnovu hesla* pošle **běžný
  e-mail pro obnovu hesla** (stejný text a stejné limity jako na webu: jeden e-mail daného druhu za
  120 s a 10 za den, sdílené s veřejným formulářem). Neaktivní účet e-mail nedostane; správce se
  to dozví ze zprávy. Odkaz platí 24 hodin a jednou. Účet bez hesla (založený správcem) e-mail
  dostane (veřejný formulář i akce ho posílají každému aktivnímu účtu s danou adresou).
- **Změna e-mailu** je změna toho, kdo účet ovládá (e-mail je přihlašovací jméno a cíl odkazů),
  proto ji smí jen superuživatel.
- **Změny** jsou v protokolu administrace Djanga (*Historie*) a v záznamu přístupů (§14.7).
- Smazání účtu uživatele z podnětu subjektu údajů se vyřizuje postupem pro žádosti (§14.12);
  hromadné mazání v seznamu uživatelů zůstává jen superuživateli. Výjimka: neaktivovanou
  registraci starší než lhůta smaže i správce uživatelů akcí z §14.14.
- Seznam uživatelů má filtr *čeká na aktivaci* a akce *Znovu odeslat aktivační e-mail* a
  *Smazat neaktivované registrace starší než lhůta* (§14.14).

### Skrytá adresa administrace

Administrace není na `/admin/`, ale na adrese z proměnné prostředí `DJANGO_ADMIN_URL`
(nastavení `ADMIN_URL`; `config/urls.py` ji použije, `reverse("admin:index")` ji vrací):

| Prostředí | Výchozí | Pravidla |
|---|---|---|
| vývoj, testy | `admin/` (vývoj smí proměnnou změnit, testy ji nečtou) | |
| produkce | **žádná: bez proměnné aplikace nenastartuje** | hodnota nesmí být `admin/` (v žádné velikosti písmen), musí končit lomítkem, nesmí začínat lomítkem, smí obsahovat jen písmena, číslice a `-_.~/` a nesmí začínat cestou, kterou aplikace sama používá (`ucet/`, `zvirata/`, `zdroje/`, `prehled/`, `static/` …) |

Hodnotu vygenerujte náhodně, např. `python -c "import secrets; print(secrets.token_urlsafe(16) + '/')"`.
Na staré adrese `/admin/` je pak 404. **Skrytá adresa je jen první, levná vrstva proti
skenerům**, ne ochrana: prozradí ji odkaz *Administrace* viditelný správcům, záznam přístupů
(sloupec adresa), protokol reverzní proxy a historie prohlížeče. Skutečnou ochranu dělají
dvoufázové ověření, oprávnění a limity relací.

Administrace **nemá vlastní přihlašovací stránku**: `admin:login` přesměruje na přihlášení
aplikace (`/ucet/prihlaseni/`, se zámkem `django-axes`), které je jedinou cestou dovnitř. Změna
hesla v administraci vede na stránku změny hesla aplikace (omezování pokusů přes `django-axes`).
Hlavička administrace je *BARF Nutri – správa*.

## 14.5 Relace správců 🛠

Přihlášený **správce** (`is_staff`; ostatní uživatele se to netýká) je odhlášen:

| Nastavení | Výchozí | Význam |
|---|---|---|
| `STAFF_SESSION_IDLE_SECONDS` | 1800 (30 minut) | bez jediného požadavku po tuto dobu |
| `STAFF_SESSION_MAX_SECONDS` | 43200 (12 hodin) | od přihlášení heslem, **i když je správce stále aktivní** |

Čas přihlášení a čas posledního požadavku jsou v relaci (`staff_session_login_at`,
`staff_session_last_seen`); zapisuje je přihlášení a každý požadavek správce. Relace správce
**bez času přihlášení** (nevznikla přihlášením této aplikace) platí za prošlou. Po vypršení se
správce odhlásí, přesměruje se na přihlášení (u GET s návratovou adresou) a tam se zobrazí
zpráva, např. *Z bezpečnostních důvodů jsme vás odhlásili, protože jste byli déle než 30 minut
nečinní. Přihlaste se prosím znovu.* nebo *… protože od přihlášení uplynulo více než 12 hodin.*
Nové přihlášení znamená novou relaci: heslo samotné ji neotevře, je potřeba druhý faktor (§14.6).

V produkci lze meze změnit proměnnými `DJANGO_STAFF_SESSION_IDLE_SECONDS` a
`DJANGO_STAFF_SESSION_MAX_SECONDS` (kladná čísla). Čas čte jediná funkce
`accounts.session_policy.now_seconds()`, kterou testy nahrazují.

## 14.6 Dvoufázové ověření 🛠

Používá se `django-otp` 1.7.5: **časový jednorázový kód (TOTP)** z aplikace v telefonu a
**záložní kódy** (jednorázové). QR kód se kreslí knihovnou `qrcode` 8.2 jako vložené SVG (bez Pillow,
bez inline stylů a skriptů, takže se vejde do přísné CSP).

### Kdo ho musí mít

| Uživatel | Bez zařízení | Se zařízením a neověřenou relací | Ověřená relace |
|---|---|---|---|
| **Správce** (`is_staff`), pokud `REQUIRE_2FA_FOR_STAFF` | každý požadavek vede na nastavení | každý požadavek vede na ověření | bez omezení |
| Kdokoli jiný | bez omezení (dobrovolné) | **každý požadavek vede na ověření**: kdo si zapnul, musí se ověřit při každém přihlášení | bez omezení |

Výjimky, které brána (`TwoFactorEnforcementMiddleware`) vždy pustí: odhlášení, právní stránky
(*Podmínky užití*, *Ochrana osobních údajů*), statické soubory a stránka, na kterou uživatele
brána posílá (nastavení, resp. ověření). Návratová adresa (`?next=`) se předává jen u GET;
bezpečně (žádná jiná adresa ani schéma, žádné smyčky na stránky `/ucet/2fa/`).
`BarfAdminSite.has_permission` navíc vyžaduje ověřenou relaci správce, i kdyby brána chyběla
(selže bezpečně). `REQUIRE_2FA_FOR_STAFF` je ve výchozím stavu `True`; **vývoj** ho může vypnout
proměnnou `DJANGO_REQUIRE_2FA_FOR_STAFF=false`, **produkce při `false` nenastartuje**. I při
vypnutí musí uživatel, který si ověření zapnul, projít ověřením.

### Adresy `/ucet/2fa/`

| Adresa (`accounts:` …) | Metody | Význam |
|---|---|---|
| `/ucet/2fa/` (`two_factor`) | GET | stav: zapnuto / povinné, nenastaveno / vypnuto, od kdy, počet nepoužitých záložních kódů; odkazy |
| `/ucet/2fa/nastaveni/` (`two_factor_setup`) | GET, POST | QR kód jako vložené SVG a **tajný klíč textem** (po čtveřicích) pro ruční zadání; zařízení se aktivuje **až po zadání kódu z něj**. Při prvním nastavení se v odpovědi ukáže 10 záložních kódů. Kdo už zařízení má, tudy ho **vymění** (a zadá heslo) |
| `/ucet/2fa/overeni/` (`two_factor_verify`) | GET, POST | druhý krok přihlášení: kód z aplikace, nebo záložní kód |
| `/ucet/2fa/kody/` (`two_factor_codes`) | GET, POST | nové záložní kódy; vyžaduje **aktuální kód z aplikace**; ukáže se jednou |
| `/ucet/2fa/vypnout/` (`two_factor_disable`) | GET, POST | vypnutí; **jen pro ty, pro které není povinné** (správce dostane 403); vyžaduje heslo a aktuální kód |

Stránka *Můj účet* ukazuje stav (ikona + text + barva) a odkaz na správu. Brána stojí **jeden
dotaz navíc** u každého požadavku přihlášeného uživatele (hledání zařízení, u ověřené relace načtení
zařízení z relace). Po ověření se klíč relace
vymění (ochrana proti fixaci relace). Stránky se nikdy neukládají do mezipaměti.

- **Čekající zařízení.** QR kód a klíč se po prvním zobrazení uloží jako nepotvrzené zařízení a
  při obnovení stránky zůstanou stejné; nepotvrzené zařízení starší než 1 hodina se zahodí a
  vznikne nový klíč. Nepotvrzené zařízení nic neopravňuje.
- **Záložní kódy:** 10 kódů po 8 znacích (`abcd-efgh`, velikost písmen a pomlčka nehrají roli), každý
  jednou. Nové kódy nahradí staré.
- **Zadání:** kód z aplikace se hledá vždy jen u zařízení aplikace, záložní kód vždy jen mezi
  záložními kódy (podle tvaru), takže zadání jednoho druhu neuplatní omezování druhého.

### Omezování pokusů 🛠

Chybný kód omezuje **`django-otp` exponenciálním zpomalením u zařízení**: po *n* chybných kódech
za sebou je další pokus možný nejdříve za `FACTOR × 2^(n−1)` sekund, pokus během čekání se nepočítá
a správný kód počítadlo vynuluje. Zvlášť pro zařízení aplikace a zvlášť pro záložní kódy.

| Nastavení | Hodnota | Význam |
|---|---|---|
| `OTP_TOTP_THROTTLE_FACTOR` | 2 | kód z aplikace: 2, 4, 8, 16 … sekund (po 10 chybách za sebou asi 17 minut, po 15 asi 9 hodin) |
| `OTP_STATIC_THROTTLE_FACTOR` | 2 | totéž pro záložní kódy |
| `OTP_TOTP_ISSUER` | `BARF Nutri` | název v aplikaci pro ověřování |

**Chyba neprozradí, jestli zařízení existuje.** Špatný kód, kód použitý podruhé, zařízení v čekání,
nesmyslný tvar i uživatel bez zařízení dostanou **jednu a tutéž zprávu** (`INVALID_TOKEN_MESSAGE`);
`two_factor.verify` vrací ve všech těchto případech `None`. Chybný kód se zkouší až po ověření ostatních polí:
špatné heslo nespotřebuje kód.

### Spolupráce s `django-axes`

Zámek přihlášení heslem (5 chyb, 1 hodina, podle e-mailu a IP adresy, [12](12-ucty-a-zvirata.md)
§12.10) **zůstává beze změny**. Chybné kódy se do něj nepočítají (omezuje je `django-otp`). Navíc
platí: **kdo je pro daný účet zamčený, nemůže druhý faktor ani projít, ani měnit**. Účet, který
se kvůli zámku nemůže přihlásit, nemá relaci, kterou by ověřoval; a relace, která už existuje,
dostane při odeslání formuláře (ověření, nové záložní kódy, vypnutí, nastavení nebo výměna zařízení)
odpověď zámku (HTTP 429), když je dvojice e-mail + IP adresa zamčená.

### GDPR 🛠

- **Export** (*Můj účet → Stáhnout moje data*): oddíl `two_factor` obsahuje `enrolled` (ano/ne),
  `confirmed_at` (čas potvrzení zařízení) a `unused_recovery_codes` (počet). **Nikdy tajný klíč ani kódy.**
- **Smazání účtu** smaže všechna zařízení i záložní kódy (kaskádou).

### Ztráta zařízení 🛠

1. Správce má **záložní kódy** (jednou použitelné); po přihlášení si přes *Změnit zařízení* nastaví nové.
2. Správce nemá nic: **superuživatel** vybere účet v administraci a použije akci
   **Zrušit dvoufázové ověření**. Akce se zapíše do protokolu administrace Djanga a do záznamu
   přístupů (§14.7). Správce pak musí zařízení nastavit znovu při dalším požadavku.
3. Není-li použitelný žádný superuživatel: **`manage.py reset_2fa <e-mail>`** na serveru (přístup
   k shellu je důkaz oprávnění). Zapíše se do záznamu přístupů (řádek `manage.py reset_2fa`) a
   do protokolu aplikace.

### Omezení `django-otp` a zbytková rizika (upřímně) 🛠

1. **Tajný klíč TOTP i záložní kódy jsou v databázi v čitelné podobě** (`django-otp` je
   neukládá šifrovaně ani jako otisk; záložní kódy tedy, na rozdíl od hesel, nejsou hašované).
   Kdo získá databázi nebo **zálohu**, získá druhý faktor všech uživatelů. Proti tomu pomáhají
   jen šifrované zálohy a omezený přístup k databázi ([13](13-nasazeni-a-provoz.md) §13.8);
   do administrace se klíče nezobrazují (správa zařízení `django-otp` je odstraněna).
2. **Okno před prvním nastavením.** Správci, který ještě nemá zařízení, může ho nastavit i ten,
   kdo zná jeho heslo. Přidělte roli a nechte zařízení nastavit hned, případ podezření
   řešte `reset_2fa`.
3. **Žádný pevný zámek, jen zpomalení.** Útočník, který zná heslo, může zpomalit ověření správce
   (po desítkách chyb za sebou na dlouhé hodiny). Správce má záložní kódy (jiné počítadlo) a
   superuživatel může ověření zrušit. Zároveň to znamená, že hrubou silou nelze kód uhodnout.
4. **Počítadlo je u zařízení, ne u IP adresy ani účtu.** Správce bez zařízení nemá co omezovat;
   chrání ho zámek hesla.
5. **TOTP není odolný proti phishingu** v reálném čase (kód lze přeposlat). Hardwarové klíče
   (WebAuthn) ani e-mailové kódy nejsou. `django-otp` přijímá kód z okna ±1 krok (30 s);
   jednou přijatý kód se znovu nepřijme.
6. **Ověřená relace platí do vypršení** (správce: §14.5) nebo do smazání zařízení; změna hesla
   ověření neruší.
7. Záložní kódy mají 40 bitů; chrání je zpomalení a to, že je zná jen uživatel.
8. Nový klíč existuje v databázi v nepotvrzené podobě nejvýše hodinu a jeho stránka se neukládá do
   mezipaměti.

## 14.7 Záznam přístupů do administrace 🛠

Odpověď na [12](12-ucty-a-zvirata.md) §12.8 bod 5 (záznam o přístupu správců k datům). Model
`backoffice.AdminAccessLog` (bez historie změn, řádky samy jsou historie):

| Sloupec | Obsah |
|---|---|
| `timestamp` | čas |
| `staff_user`, `staff_email` | kdo (cizí klíč s `SET_NULL` po smazání účtu + e-mail jako text, který zůstává) |
| `action` | `VIEW_LIST`, `VIEW_OBJECT`, `ADD`, `CHANGE`, `DELETE`, `EXPORT`, `UNLOCK`, `LOGIN` |
| `app_label`, `model`, `object_pk` | co (u seznamu a přihlášení bez klíče) |
| `ip_address` | IP adresa **stejným způsobem jako zámek přihlášení** (`TRUSTED_PROXY_COUNT`, hodnoty, které dopsal klient, se ignorují) |
| `path` | cesta **bez parametrů** |

**Nikdy se neukládá** hledaný text, hodnoty filtrů a řazení ani odeslaná data: ukládá se jen cesta
bez řetězce za otazníkem a klíč záznamu.

**Co se zapisuje:** seznam (`VIEW_LIST`), stránka záznamu a jeho historie, také starší verze z historie,
a potvrzovací stránka smazání (`VIEW_OBJECT`), přidání (`ADD`), uložená změna (`CHANGE`), smazání
(`DELETE`, jeden řádek na záznam), přihlášení správce (`LOGIN`), odemčení přihlášení
(`UNLOCK`: akce *Odemknout* i smazání počítadla, jeden řádek na každé odstraněné počítadlo), a
každá vlastní akce (u akce, která sama
nezapsala nic, jeden řádek na vybraný záznam jako `CHANGE`; export označený
`@access_logged_action(AdminAccessAction.EXPORT)` jako `EXPORT`). Akce s potvrzovací stránkou
(§14.11, §14.12, §14.14) zapisují sama: zobrazená stránka (ukazuje data) a odmítnutá akce jako
`VIEW_OBJECT`, provedená změna jako `CHANGE` (u každé žádosti zvlášť), smazání jako `DELETE`,
export jako `EXPORT`. Odmítnutá akce se tak nezapíše jako změna. Odmítnutý požadavek (403) a
neexistující záznam řádek nezanechá. Chyba zápisu se nepotlačí: přístup, který nelze zapsat, nemá
proběhnout bez povšimnutí.

**Které modely:** ty, které mají atribut `contains_personal_data = True`: `User`,
`VetVerificationRequest`, `DataSubjectRequest`, `Animal`,
`BodyMeasurement`, `AnimalHealthCondition`, `AnimalShare`, jejich modely historie
(`django-simple-history`), samotný `AdminAccessLog` a modely `django-axes` (záznamy o přihlášení
nesou e-mail a IP adresu). Jejich `ModelAdmin` **musí** používat `AccessLoggedAdminMixin`:

- **test** (`test_admin_access_log.py`) projde každý registrovaný `ModelAdmin` a selže, když model
  s osobními údaji nemá mixin; selže i při registrovaném modelu, který není ani označený, ani na
  seznamu bez osobních údajů (kdo přidá model, musí ho zařadit);
- stejné pravidlo kontroluje **systémová kontrola** `backoffice.E001` (`manage.py check`, `migrate`).

**Kdo ho smí číst:** záznam je v administraci **jen pro superuživatele**, ke čtení (nelze přidat,
změnit ani smazat); žádná role ho v matici nemá. I čtení záznamu se zapisuje.

**Uchování:** `ADMIN_ACCESS_LOG_RETENTION_DAYS` = **365 dní** (pracovní hodnota, 🟡 rozhodne právník,
§14.9). Starší řádky maže `manage.py purge_admin_access_log` (denně, §14.8); nic jiného
řádky nemaže. Chybné nastavení (ne kladné číslo) nesmaže nic.

## 14.8 Příkazy a provoz 🛠

| Příkaz | Účel |
|---|---|
| `manage.py sync_role_permissions [--dry-run]` | nastaví oprávnění rolí podle `ROLE_PERMISSIONS` (§14.3); běží i po každém `migrate` |
| `manage.py print_role_matrix` | vypíše matici oprávnění jako tabulku v Markdownu |
| `manage.py reset_2fa <e-mail>` | zruší dvoufázové ověření účtu (§14.6) |
| `manage.py purge_admin_access_log` | smaže záznamy přístupů starší než retence (denně: `deploy/crontab.example`) |

Proměnné prostředí ([13](13-nasazeni-a-provoz.md) §13.2): **`DJANGO_ADMIN_URL`** (v produkci
povinná), `DJANGO_REQUIRE_2FA_FOR_STAFF` (výchozí `true`, v produkci `false` aplikaci
nespustí), `DJANGO_STAFF_SESSION_IDLE_SECONDS`, `DJANGO_STAFF_SESSION_MAX_SECONDS`.

**První správce:** `createsuperuser` → přihlášení → aplikace ho pošle na nastavení dvoufázového
ověření (uložte záložní kódy) → role dalším správcům přidělí superuživatel
(*Uživatelské účty → Uživatelé → Oprávnění a role*) a každý si při prvním přihlášení nastaví
dvoufázové ověření.

## 14.9 Body pro právníka 🟡

Doplňují [12](12-ucty-a-zvirata.md) §12.8 (body 13 až 22 tam odkazují sem):

1. **Uchování záznamu přístupů do administrace** (nyní 365 dní, `ADMIN_ACCESS_LOG_RETENTION_DAYS`):
   účel, právní základ, doba; zda a jak se informují správci o tom, že se jejich přístupy zaznamenávají.
2. **E-mail správce v záznamu po smazání jeho účtu**: `staff_user` se vymaže, `staff_email`
   a IP adresa zůstávají do vypršení uchování. Je to v pořádku, nebo se má e-mail anonymizovat?
   Má export údajů správce (*Stáhnout moje data*) obsahovat i jeho vlastní řádky záznamu? (Nyní
   neobsahuje.)
3. **Rozsah přístupu správců k datům** podle matice (§14.3): zejména že *správce uživatelů* vidí
   e-mail, jméno a stav všech účtů, které nejsou správci, a že superuživatel vidí všechna data, včetně
   zdravotních údajů zvířat. Smluvní zajištění správců.
4. **IP adresy a e-maily v záznamech `django-axes`** a v záznamu přístupů: doba uchování se řídí
   zámkem přihlášení, resp. bodem 1.
5. **Tajné klíče a záložní kódy dvoufázového ověření** jsou v databázi a v zálohách v čitelné
   podobě (§14.6): zda je to přijatelné, nebo je třeba je šifrovat před uložením (vyžaduje vlastní
   zařízení nad `django-otp`).
6. **Ověření veterinářů** (§14.11): jaké údaje smí aplikace od žadatele žádat (pracoviště, evidenční
   číslo v profesní evidenci, zpráva), právní základ a **doba uchování žádosti** (nyní do smazání
   účtu, i po zamítnutí), co smí obsahovat interní poznámka *Jak byla totožnost a oprávnění
   ověřena* a zda ji žadatel dostane při žádosti o přístup k údajům (nyní se nevydává, export ji
   neobsahuje), jakou odpovědnost má provozovatel za to, že roli dostal někdo, kdo veterinářem
   není, a smluvní zajištění správců, kteří o roli rozhodují.
7. **Lhůta pro vyřízení žádosti subjektu údajů** (§14.12): nyní **jeden kalendářní měsíc od přijetí**
   (`DATA_SUBJECT_REQUEST_PERIOD_MONTHS`, pracovní hodnota), kdy a jak ji lze prodloužit
   (aplikace jen vyžaduje odůvodnění v poli *odůvodnění prodloužení*) a zda a jak se žadatel o
   prodloužení informuje (aplikace žadateli nic neposílá).
8. **Ověření totožnosti žadatele** (§14.12): jaký způsob je přiměřený (aplikace jen eviduje
   *totožnost ověřena* a poznámku, jak), co smí poznámka obsahovat (nyní pokyn: bez čísel dokladů
   a bez kopií) a jak dlouho se uchovává.
9. **Záznam o žádosti po výmazu účtu** (§14.12): zůstane označení žadatele (pseudonym), druh a
   dny žádosti, stav, poznámky správce a automatická poznámka o výmazu (počty smazaných záznamů,
   datum). Je to přiměřené, kdy se smaže a zda stačí pseudonym? Stejně tak záznam přístupů
   (řádek `DELETE` s číslem smazaného účtu, §14.7).
10. **Předání exportu žadateli** (§14.12): aplikace soubor jen vytvoří a stáhne ho správce; jak se
    soubor žadateli bezpečně předá (šifrování, kanál) a zda může správce soubor otevřít, je mimo
    aplikaci a rozhodne ho právník.
11. **Kdo smí co vyřídit** (§14.12): správce uživatelů smí exportovat a smazat jen účty, které nejsou
    správci; účty správců jen superuživatel. Žádná role nesmí smazat záznam o žádosti. Je to
    správné rozdělení?
12. **Obsah exportu** (§14.11, §14.12): export obsahuje žádosti o roli veterináře bez interní
    poznámky a bez toho, kdo rozhodl, a žádosti, které uživatel sám podal jako subjekt údajů, jen
    s druhem, dny a stavem (bez poznámek správce a označení). Je takový rozsah správný?
13. **Zrušení zámku přihlášení** (§14.13) a **smazání neaktivované registrace** (§14.14) správcem
    uživatelů: obojí je zapsané v záznamu přístupů; odemčení nemá podmínku ověření totožnosti
    toho, kdo o něj žádá.

## 14.10 Co zatím není 🛠

- **Správa dat a jejich schvalování** (stavy DRAFT, IN_REVIEW, APPROVED, RETIRED,
  [07](07-django-schema.md) §7.6) a **provozní přehled** na úvodní stránce administrace.
- **Příjem žádostí subjektů údajů od uživatele** na stránce účtu: žádost zapíše správce do
  evidence (§14.12; hodnota *stránka účtu* v poli *přijato* je připravená, ale stránka žádost
  zatím nepřijímá). **Oprava, omezení zpracování a námitka** nemají vlastní nástroj: eviduje se
  a vyřizuje ručně. **Upozornění na blížící se lhůtu** je jen sloupec v seznamu, e-mail ani
  oznámení žádné není. Žadateli aplikace nic neposílá.
- **Ověření veterináře proti registru**: aplikace neověřuje nic sama, ověřuje člověk a zapíše
  způsob (§14.11). Superuživatel může skupinu `vet` přidat také ručně ve formuláři uživatele,
  mimo tento postup a bez poznámky o ověření.
- **Krokové potvrzení** citlivých akcí v administraci (znovu heslo nebo kód): jen výměna a vypnutí
  zařízení vyžadují heslo.
- **Hardwarové klíče (WebAuthn)**, e-mailové kódy, ověření zařízení.
- **Oznámení správci** o přihlášení z nové adresy, hlídání neobvyklého počtu zobrazení
  záznamů.
- Záznam přístupů **nehlídá** přístup k databázi nebo shellu mimo administraci.

## 14.11 Ověření veterinářů 🛠

Roli `vet` ([12](12-ucty-a-zvirata.md) §12.2) dostane účet, jehož žádost správce schválil. Aplikace
**neověřuje totožnost ani oprávnění sama** (nezná žádný registr): ověřuje člověk a způsob zapíše do
poznámky. Role je skupina Djanga; žádost je záznam o tom, kdo o ni požádal, kdo rozhodl, kdy a jak
bylo ověřeno.

### Stránka uživatele `/ucet/veterinar/` (`accounts:vet_verification`)

Jen pro přihlášeného (jinak přesměrování na přihlášení), `GET` a `POST`, stránka se neukládá do
mezipaměti. Obsahuje:

1. **Co role umožňuje** ([12](12-ucty-a-zvirata.md) §12.2, §12.3): majitel s ním může sdílet zvíře,
   veterinář vidí sdílené zvíře, zapisuje měření a potvrzuje cílovou hmotnost, přístup trvá, jen
   dokud má účet roli **a** sdílení je aktivní; role neotevírá cizí zvířata ani administraci; po
   odebrání role přístup zanikne a potvrzené cílové hmotnosti se vrátí na orientační.
2. **Stav poslední žádosti**: stav jako ikona + text + barva (ⓘ čeká na posouzení, ✓ schváleno, ⛔
   zamítnuto, ⚠ role odebrána), odesláno, pracoviště, rozhodnuto a **odůvodnění** (interní poznámku o
   ověření uživatel nikdy nevidí). Kdo roli má, vidí *Roli veterinárního lékaře máte*.
3. **Formulář** jen pro účet bez role a bez čekající žádosti (po zamítnutí nebo odebrání role lze
   podat novou): *pracoviště* (povinné, do 200 znaků), *evidenční číslo v profesní evidenci, pokud
   existuje* (do 64 znaků; popisek nejmenuje žádný skutečný registr) a *zpráva pro správce* (do
   1000 znaků). Pokyn: nepsat rodné číslo ani čísla dokladů a nepřikládat kopie. `POST`, který žádost
   podat nemůže (role nebo čekající žádost už je), nic nezmění.

Texty uživatel- i správce-zadané se vypisují jen automaticky escapovanou šablonou (test XSS).
Stránka nemá inline styl ani skript (CSP). Odkaz na ni je na stránce *Můj účet*.

### Model `accounts.VetVerificationRequest` (s historií změn, `contains_personal_data`)

| Pole | Význam |
|---|---|
| `user` | žadatel (`CASCADE`: smazáním účtu se žádost i její historie smaže) |
| `submitted_at`, `professional_id`, `workplace`, `message` | co žadatel zadal |
| `status` | `PENDING` čeká · `APPROVED` schváleno · `REJECTED` zamítnuto · `REVOKED` role odebrána |
| `decided_by` (`SET_NULL`), `decided_at` | kdo a kdy rozhodl |
| `decision_note` | odůvodnění; **uvidí ho žadatel** (stránka, e-mail); povinné při zamítnutí a odebrání |
| `verification_method_note` | *Jak byla totožnost a oprávnění ověřena*; **interní**, povinné při schválení |

Databáze hlídá: nejvýše jedna čekající žádost na uživatele (částečně jedinečné omezení), čas
rozhodnutí právě u vyřízené žádosti, poznámku o ověření u schválené a odůvodnění u zamítnuté nebo
odebrané. Přechody: `PENDING → APPROVED` nebo `REJECTED`, `APPROVED → REVOKED`; vyřízená žádost je
konečná (uživatel podá novou). Text objektu (`__str__`) neobsahuje osobní údaje, protože zůstává
v protokolu administrace.

### Rozhodování v administraci (*Uživatelské účty → Žádosti o ověření veterináře*)

Seznam: žadatel, pracoviště, stav (ikona + text + barva), odesláno, rozhodnuto, rozhodl; filtry
(stav, odesláno, rozhodnuto), hledání (e-mail, pracoviště, evidenční číslo). Záznam nelze přidat
ani změnit (kdokoli, i superuživatel): je důkaz; smazat ho smí jen superuživatel. Rozhoduje se
třemi akcemi, každá otevře **potvrzovací stránku s poznámkami**:

| Akce | Stav před | Povinná poznámka | Účinek |
|---|---|---|---|
| *Schválit* | čeká | *Jak byla totožnost a oprávnění ověřena* (odůvodnění pro žadatele nepovinné) | stav `APPROVED`, uživatel přidán do skupiny `vet` |
| *Zamítnout* | čeká | odůvodnění | stav `REJECTED`, role se nemění |
| *Odebrat roli veterináře* | schváleno | odůvodnění | stav `REVOKED`, uživatel vyřazen ze skupiny `vet` |

- **Jedna transakce.** Změna žádosti i skupiny se provede najednou. Vybraných žádostí může být víc
  (poznámky se uloží ke každé); selže-li jedna (např. ji mezitím vyřídil jiný správce), **nezmění se
  žádná**. Žádost se před rozhodnutím znovu načte pod zámkem.
- **Čtyři oči.** Vlastní žádost nesmí vyřídit nikdo, ani superuživatel; vybraná cizí žádost se
  vyřídí a vlastní se přeskočí s upozorněním.
- **Vyřízená žádost je konečná.** Schválit nebo zamítnout lze jen čekající, odebrat jen schválenou;
  jiná se přeskočí a zpráva řekne proč (*Žádost už byla vyřízena*). Neaktivní účet se neschválí.
- **Odebrání role** spustí stejný přijímač jako ruční odebrání skupiny ([12](12-ucty-a-zvirata.md)
  §12.4): cílové hmotnosti, které uživatel potvrdil, se vrátí na *orientační*. Sdílení zůstávají
  jako záznam souhlasu majitele, ale nic neotevírají, dokud uživatel roli nemá; po nové žádosti a
  schválení přístup obnoví, potvrzení ne.
- **Oprávnění.** Akce vyžadují `accounts.decide_vetverificationrequest` (matice §14.3: správce
  uživatelů a superuživatel); samotné `view` seznam ukáže, akce nenabídne. Služba
  `accounts.vet_verification.decide` si oprávnění ověřuje sama.
- **Kdo co vidí.** Jako v seznamu uživatelů (§14.4) nevidí nesuperuživatel žádosti správců, kromě
  vlastní (tu vidí, ale vyřídit ji nesmí); žádost správce vyřídí superuživatel.
- **Záznam přístupů.** Seznam `VIEW_LIST`; zobrazená potvrzovací stránka i odmítnutá akce
  `VIEW_OBJECT`; každá vyřízená žádost `CHANGE` (spolu se záznamem v protokolu administrace bez
  osobních údajů). Změny jsou v historii záznamu (*Historie*).

### E-maily

Texty česky, odesílá je `accounts.services.deliver` stejně jako ostatní e-maily účtu a platí pro ně
**stejné omezení** (`claim_email_slot`: jeden e-mail daného druhu za 120 s a 10 e-mailů denně na
účet; druh = rozhodnutí, takže schválení a hned následující odebrání dojdou obě):

- **Žadateli o rozhodnutí** (schváleno, zamítnuto, role odebrána): obsahuje odůvodnění, u zamítnutí
  odkaz na stránku pro novou žádost, u odebrání upozornění, co zaniká. **Neobsahuje interní poznámku
  o ověření.** Neposílá se na neaktivní účet. Zpráva správci řekne, kolik e-mailů neodešlo.
- **Provozovateli** (`DJANGO_CONTACT_EMAIL`) o nové žádosti: jen e-mail žadatele a pokyn, kde
  rozhodnout; **bez pracoviště, zprávy a bez odkazu** (adresa administrace se nerozesílá poštou).
  Bez nastavené adresy se neposílá. Omezeno na žadatele stejně jako ostatní e-maily.

### Osobní údaje

Export (*Můj účet → Stáhnout moje data*) má oddíl `vet_verification`: co uživatel zadal, stav,
čas a odůvodnění; **ne** interní poznámku o ověření ani to, kdo rozhodl (otázka pro právníka, §14.9
bod 12). Smazání účtu žádosti i jejich historii smaže (kaskáda).

## 14.12 Žádosti subjektů údajů 🛠

Evidence žádostí o výkon práv (GDPR čl. 15 až 21) a dva nástroje pro vyřízení: export a výmaz
účtu. **Právní stránku (lhůty, ověření totožnosti, odmítnutí, uchování) rozhodne právník**, viz §14.9
body 7 až 12; aplikace má pracovní hodnoty, které jsou pojmenované a snadno měnitelné.

### Model `accounts.DataSubjectRequest` (s historií změn, `contains_personal_data`)

| Pole | Význam |
|---|---|
| `request_type` | přístup (čl. 15) · oprava (16) · výmaz (17) · omezení (18) · přenositelnost (20) · námitka (21) · jiná |
| `received_on`, `received_via` | den přijetí (po zápisu jen ke čtení) a způsob: e-mail, pošta, stránka účtu, jinak |
| `subject_label` | **pseudonym** žadatele (číslo účtu, číslo žádosti), ne celé jméno: nápověda to říká, záznam přetrvá výmaz účtu |
| `user` | účet žadatele, nepovinný, `SET_NULL`: po výmazu účtu se vyprázdní |
| `identity_verified`, `identity_note` | totožnost ověřena a jak (bez čísel dokladů a kopií); formulář ověření bez poznámky nepřijme |
| `due_on`, `extension_reason` | termín vyřízení a odůvodnění jeho změny |
| `status` | `RECEIVED` přijata · `IN_PROGRESS` vyřizuje se · `COMPLETED` vyřízena · `REJECTED` zamítnuta |
| `handled_by`, `completed_on`, `outcome_note` | kdo vyřizuje (doplní se podle přihlášeného správce), kdy se vyřídilo (doplní se podle stavu), co se udělalo nebo proč se zamítlo |

**Termín** je výchozí den přijetí plus `DATA_SUBJECT_REQUEST_PERIOD_MONTHS` kalendářních měsíců
(**pracovně 1**, 🟡 rozhodne právník, §14.9 bod 7) a počítá ho čistá funkce
`accounts.deadlines.default_due_date` (konec kratšího měsíce se zkrátí: 31. 1. + měsíc = 28. nebo
29. 2.). Prázdný termín se doplní. **Jiný termín (delší i kratší) vyžaduje odůvodnění** v poli
*odůvodnění prodloužení*; formulář jinak hlásí chybu. Zamítnutí vyžaduje důvod v poznámce.
Databáze hlídá platný druh, způsob a stav, termín ne před přijetím a datum vyřízení právě u
vyřízené žádosti.

### Seznam

Číslo, druh, označení, účet, přijato, termín, **stav lhůty**, stav, totožnost ověřena. Sloupec
**po termínu** je vždy ikona + text + barva: ✓ vyřízeno (zelená) · ⛔ po termínu o N d (červená) · ⚠
blíží se termín, zbývá N d (žlutá; `DUE_SOON_DAYS` = 7, provozní hodnota) · ⓘ v termínu, zbývá N d
(modrá). Termín, který je dnes, ještě po termínu není. Filtry: stav, druh, způsob přijetí,
totožnost ověřena, **po termínu** (jen otevřené žádosti po termínu), den přijetí. Hledání:
označení, e-mail účtu, poznámka k vyřízení. Počet dotazů nezávisí na počtu žádostí.

Správce uživatelů žádosti zapisuje a upravuje (oprávnění `view`, `add`, `change`, vlastní `export`
a `erase`), **nemůže je smazat**; smazat smí jen superuživatel. Účet žadatele smí správce uživatelů
přiřadit jen z účtů, které nejsou správci (hledání v poli účtu vidí jen takové). Evidenci vidí
celou: u žádosti spojené s účtem správce (přiřadil ji superuživatel, nebo se žadatel stal správcem
později) vidí i e-mail účtu, ale export ani výmaz pro ni nepoužije (zpráva řekne proč).

### Akce *Vytvořit export osobních údajů*

Stáhne **tentýž JSON jako uživatelův vlastní export** (`accounts.export.export_json` přes registr
exportérů, [12](12-ucty-a-zvirata.md) §12.6, §14.6): bez hesla, tajného klíče a záložních kódů
dvoufázového ověření, bez údajů jiných lidí. Soubor se jmenuje
`barf-nutri-export-zadost-<č. žádosti>-<datum>.json` (ne podle e-mailu) a stahuje se bez ukládání do
mezipaměti. **Podmínky:** vybrána právě jedna žádost; je otevřená (přijata nebo se vyřizuje); má
propojený účet; totožnost je ověřena; správce uživatelů smí jen účet, který není správce (superuživatel
jakýkoli). Jinak zpráva řekne důvod a nic se nevytvoří. Zápisy: záznam přístupů `EXPORT` u
žádosti i u účtu a záznam v historii žádosti. Export žádost nevyřídí a žadateli ho aplikace
neposílá: předání je na správci (§14.9 bod 10).

### Akce *Provést výmaz účtu*

Potvrzovací stránka ukáže číslo a druh žádosti, **e-mail účtu** a **seznam toho, co se smaže**
(počty podle modelů ze stejného prohledávače závislostí, který používá smazání v administraci
Djanga, takže se doplní i nový model; k tomu záznamy o přihlášení `django-axes` podle e-mailu) a
vysvětlí, co zůstane (protokol administrace bez textu smazaných objektů, řádek v záznamu přístupů,
zálohy do konce jejich uchování, žádost bez odkazu na účet). Výmaz se provede po **opsání e-mailu
účtu** (na velikosti písmen a mezerách nezáleží).

- **Stejná funkce jako smazání účtu uživatelem:** `accounts.services.delete_account`. Smaže účet,
  zvířata, měření, stavy, sdílení, žádosti o roli veterináře, zařízení dvoufázového ověření a
  záložní kódy, záznamy o přihlášení i **historii změn** všech těchto záznamů a anonymizuje text
  v protokolu administrace ([12](12-ucty-a-zvirata.md) §12.6). Test porovná databázi po smazání
  uživatelem a po výmazu pro žádost: smazáno je totéž.
- **Žádost se v téže transakci vyřídí:** stav `COMPLETED`, datum vyřízení dnes, `handled_by`
  (když nebyl nikdo) a **automatická poznámka** (datum, počty smazaných záznamů, věta o zálohách; bez
  osobních údajů). Selže-li cokoli včetně zápisu do záznamu přístupů, nesmaže se nic.
- **Podmínky** jako u exportu a navíc: správce uživatelů smí jen účet, který není správce (superuživatel
  i správce, ale **nikdy vlastní účet**: ten maže uživatel sám na stránce *Můj účet*); vybrána jedna
  žádost. Vyřízená žádost se podruhé nevyřídí.
- Zápisy: `VIEW_OBJECT` při zobrazení stránky, `DELETE` účtu (číslo účtu) a `CHANGE` žádosti při
  výmazu, záznam v historii žádosti.

## 14.13 Zámky přihlášení 🛠

*Zámky přihlášení → Počítadla neúspěšných přihlášení* (`django-axes`) ukazují, kdo je zamčený
(pravidla zámku: [12](12-ucty-a-zvirata.md) §12.10, §14.6). Viditelné pro správce uživatelů a
superuživatele (`axes.view_accessattempt`, `axes.delete_accessattempt`).

- **Sloupce:** e-mail, IP adresa, neúspěšných pokusů, poslední pokus a **zamčeno**: ⛔ zamčeno
  (červená) · ⓘ zámek vypršel (modrá; počítadlo dosáhlo limitu, ale od posledního pokusu uplynula
  doba zámku) · ⓘ ne, zbývá pokusů N. Zámek znamená, že **součet neúspěšných pokusů téhož e-mailu
  z téže adresy za dobu zámku** (všechny prohlížeče, protože `django-axes` počítá pro jeden e-mail
  a adresu každý prohlížeč zvlášť, ale zamyká podle součtu) dosáhl `AXES_FAILURE_LIMIT`; počítá se
  jedním dotazem pro celý seznam. Bez doby zámku (`AXES_COOLOFF_TIME = None`) nic nevyprší.
- **Filtry:** zamčeno ano/ne (stejné pravidlo jako sloupec), čas. Hledání: e-mail, IP adresa.
- **Nezobrazují se** odeslaná data požadavku (`get_data`, `post_data`, hlavička Accept): mohlo by
  v nich být špatně napsané heslo.
- **Akce *Odemknout*:** pro e-mail každého vybraného počítadla zavolá vlastní funkci `django-axes`
  `axes.utils.reset(username=…)`, která smaže počítadla toho e-mailu **ze všech adres**
  (odemyká se účet, ne řádek). Počítadla bez e-mailu se přeskočí (volání bez e-mailu by smazalo
  všechna). Zpráva: *Odemčeno účtů: N (smazaných počítadel: M).* Záznam přístupů `UNLOCK` za každé
  odstraněné počítadlo. Smazání jednoho počítadla (stránka smazání) odemyká také a zapisuje také
  `UNLOCK`; hromadné *Odstranit vybrané* se nenabízí.
- Odemčení nic nezjišťuje o tom, kdo o ně žádá: ověřit, že žádá majitel účtu, je na správci (§14.9
  bod 13). Útočník, který zná e-mail, může zámek vyvolat znovu.

## 14.14 Neaktivované registrace 🛠

Registraci lze založit na cizí e-mail ([12](12-ucty-a-zvirata.md) §12.10); neaktivovaný účet
(`activation_pending`, neaktivní) se maže po `PENDING_ACCOUNT_RETENTION` (pracovně 7 dní,
[12](12-ucty-a-zvirata.md) §12.8 bod 8). V seznamu uživatelů:

- **Filtr *čeká na aktivaci*:** *ano* (neaktivní a čeká na potvrzení e-mailu; účet vypnutý správcem
  mezi ně nepatří) a *ano, po lhůtě (smaže se)*.
- **Akce *Znovu odeslat aktivační e-mail*:** stejná služba jako web (`send_activation_email`, odkaz
  platí 24 hodin a jednou, vyžaduje heslo z registrace; omezení jeden e-mail za 120 s a 10 denně na
  účet). Zpráva počítá odeslané, **ty, které zadrželo omezení**, a přeskočené účty, které na
  aktivaci nečekají (aktivní, vypnuté správcem). Zapisuje `CHANGE` u těch, kterým e-mail odešel.
- **Akce *Smazat neaktivované registrace starší než lhůta*:** potvrzovací stránka ukáže **počet**
  (a prvních 20 e-mailů) a kolik vybraných účtů se přeskočí. Maže se **jedinou funkcí**
  `accounts.services.purge_pending_accounts(users=…)`, kterou denně volá i příkaz
  `purge_pending_accounts` (bez výběru = všechny): smaže jen účty, které jsou **neaktivní, čekají na
  aktivaci a jsou starší než lhůta** (`stale_pending_accounts`), ať je vybráno cokoli, a odstraní
  i záznamy podle e-mailu a text v protokolu administrace (signál `post_delete`). Zápisy: `VIEW_OBJECT`
  (stránka), `DELETE` za každý smazaný účet. Akci smí správce uživatelů i superuživatel (maže totéž,
  co by smazal denní příkaz).

## 14.15 Vzhled stavů v administraci 🛠

Stavy v seznamech (stav žádosti, po termínu, zamčeno) jsou vždy **ikona + text + barva**
(`backoffice.admin_tools.status_badge`; ikona má `aria-hidden`, význam nese text). Barvy jsou
v `static/css/admin.css` (načítá ho `templates/admin/base_site.html`), světlý i tmavý režim
administrace Djanga, v režimu vysokého kontrastu silný rámeček. Dvojice barev text/pozadí mají
nejméně 4,5 : 1 a rámeček 3 : 1 proti stránce (`test_admin_colours.py` je přepočítává ze
stylesheetu). Bez inline stylů a skriptů (CSP). Potvrzovací stránky akcí rozšiřují
`admin/accounts/confirm_action.html` (formulář s tokenem CSRF, vybrané záznamy a `post=yes`).

## 14.16 Testy

```bash
.venv/bin/python -m pytest -q tests/backend      # všechno, včetně administrace
```

`test_staff_roles.py` (odvozené `is_staff`), `test_role_permissions.py` (tabulka, synchronizace,
`post_migrate`, příkazy, matice), `test_admin_permissions.py` (**každá role × každý druh stránky a
zápisu**), `test_user_admin.py` (ochrana před eskalací, heslo, akce, role × akce),
`test_admin_settings.py` (skrytá adresa, požadavek na 2FA, meze relací, nastavení produkce),
`test_staff_session.py` (limity relací s upraveným časem), `test_two_factor.py` (služby),
`test_two_factor_views.py` (zápis, ověření, záložní kódy, vypnutí, **brána pro každý stav a
každou stránku**, omezování pokusů, `django-axes`), `test_two_factor_admin.py` (administrace,
export, smazání, zrušení ověření), `test_admin_access_log.py` (záznam pro každý druh stránky,
pravidlo o mixinu, čtení, uchování). Správa uživatelů a rolí: `test_vet_verification.py`
(model, omezení databáze, služby, pravidla rozhodnutí včetně čtyř očí a konečnosti, e-maily,
stránka `/ucet/veterinar/` ve všech stavech, XSS, sdílení a potvrzení po schválení a odebrání),
`test_vet_verification_admin.py` (**každá role × každá akce**, poznámky, jedna transakce, e-maily,
záznam přístupů, počet dotazů seznamu), `test_lockout_admin.py` (zámky vyrobené skutečnými
neúspěšnými přihlášeními přes `django-axes`, odemčení a pak skutečné přihlášení),
`test_pending_registrations_admin.py` (filtr, opětovné odeslání, sdílená funkce mazání,
potvrzovací stránka), `test_data_subject_requests.py` (model a pravidla lhůt, seznam, **každá role ×
export a výmaz**, obsah exportu bez tajemství a shoda s exportem uživatele, **úplnost výmazu** a
shoda se smazáním uživatelem, jedna transakce), `test_deadlines.py` (čisté funkce, `hypothesis`),
`test_admin_colours.py` (kontrast), rozšířené `test_role_permissions.py` a
`test_admin_permissions.py` (matice role × stránka). Testy, které potřebují správce, se přihlašují
`tests/backend/helpers.log_in_verified` (relace s projitým druhým faktorem) a kódy vyrábějí z
`django_otp.oath` (`totp_token`).
