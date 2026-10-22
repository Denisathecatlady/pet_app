# 13. Nasazení a provoz (zálohy, obnova, denní úlohy)

> Kapitola popisuje 🛠 provozní stránku webové aplikace: proměnné prostředí, první nasazení, provoz za
> reverzní proxy, denní úlohy a hlavně **zálohování a obnovu databáze** podle [07](07-django-schema.md)
> §7.7 (původní požadavek „bezpečné zálohování a ochrana dat“). Nástroje jsou v adresáři
> [`deploy/`](../deploy/), jejich testy v `tests/ops/`.
> **Číslo 13 nese i [13-zdroje-v-aplikaci.md](13-zdroje-v-aplikaci.md)**; na tuto kapitolu proto
> odkazujeme vždy celým názvem souboru.
> Legenda: ✅ ověřeno · 🟡 ověřit · 🛠 pracovní návrh · 🩺 posoudí vet. nutriční specialista.
> V této kapitole znamená **🟡 netestováno**, že postup vychází z dokumentace produktu a nebyl zde
> spuštěn, protože potřebuje server, který vývojové prostředí nemá (§13.12).

## 13.1 Rozsah a hranice 🛠

Kapitola popisuje provoz **stávající** aplikace (účty, zvířata, knihovna zdrojů). Kalkulačka,
energie a nutriční rozbor jsou odložené a v provozu se neřeší. Skripty zálohují celou databázi,
tedy osobní údaje majitelů (e-mail, jméno), údaje o zvířatech, jejich zdravotních stavech a
měřeních, historii změn a záznamy o přihlášení (`django-axes`). **Záloha je stejně citlivá jako
živá databáze** a zachází se s ní stejně (§13.11, §13.14).

| Co | Kde |
|---|---|
| Skripty | `deploy/backup_db.sh`, `deploy/restore_db.sh`, `deploy/restore_test.sh`, denní úlohy aplikace `deploy/run_manage.sh`, společné funkce `deploy/lib.sh` |
| Ukázka plánovače | `deploy/crontab.example` |
| Testy skriptů | `tests/ops/` (spouští je celá sada: `.venv/bin/python -m pytest -q`) |
| Proměnné aplikace | [`.env.example`](../.env.example), §13.2 |

## 13.2 Proměnné prostředí

Aplikace (`config.settings.prod`) čte vše citlivé z proměnných prostředí a bez povinných
**nenastartuje**. Soubor `.env.example` nečte sama: proměnné předá správce procesů (systemd
`EnvironmentFile=`, kontejner, shell). Do repozitáře se nic nedává (`.gitignore` obsahuje `.env`).

### Aplikace

| Proměnná | Povinná | Význam |
|---|---|---|
| `DJANGO_SECRET_KEY` | ano | Náhodná hodnota, alespoň 50 znaků (`django.core.management.utils.get_random_secret_key()`). Při změně se odhlásí všichni uživatelé |
| `DJANGO_ALLOWED_HOSTS` | ano | Názvy serveru oddělené čárkou, např. `barf.example.cz`. Jiná hlavička `Host` dostane odpověď 400 |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST` | ano | Připojení k PostgreSQL |
| `POSTGRES_PORT` | ne | Výchozí 5432 |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | ne | Původy s `https://`, ze kterých se smí odesílat formuláře (za proxy obvykle `https://barf.example.cz`) |
| `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS` | ne | Výchozí `true` |
| `DJANGO_SECURE_HSTS_PRELOAD` | ne | Výchozí `false`. Zapínat jen po uvážení, odstranění ze seznamů prohlížečů trvá měsíce. Proto `check --deploy` hlásí upozornění `security.W021` a je to záměr |
| `DJANGO_SECURE_PROXY_SSL_HEADER` | ne | Za proxy, která hlavičku přepisuje: `HTTP_X_FORWARDED_PROTO,https` (§13.5) |
| `DJANGO_TRUSTED_PROXY_COUNT` | ne | Počet důvěryhodných proxy, které připisují `X-Forwarded-For` (obvykle 1). Musí být alespoň 1, jakmile je nastavena `DJANGO_SECURE_PROXY_SSL_HEADER`, jinak aplikace nenastartuje |
| `DJANGO_STATIC_ROOT` | ne | Cíl `collectstatic`, výchozí `staticfiles/` v kořeni repozitáře |
| `DJANGO_EMAIL_HOST`, `DJANGO_EMAIL_PORT` | ne | SMTP server, výchozí `localhost` a 587 |
| `DJANGO_EMAIL_HOST_USER`, `DJANGO_EMAIL_HOST_PASSWORD` | ne | Přihlášení k SMTP |
| `DJANGO_EMAIL_USE_TLS`, `DJANGO_EMAIL_USE_SSL` | ne | Výchozí `true` a `false`; nelze zapnout obě |
| `DJANGO_DEFAULT_FROM_EMAIL` | ne | Odesílatel, např. `BARF Nutri <noreply@barf.example.cz>` |
| `DJANGO_CONTACT_EMAIL` | ne | Adresa správce, kterou aplikace ukazuje uživatelům (např. žádost o roli `vet`) |
| `DJANGO_LOG_LEVEL` | ne | Úroveň protokolu na standardní výstup, výchozí `INFO` |

`manage.py` má výchozí nastavení `config.settings.dev`. **Na serveru vždy nastavte**
`DJANGO_SETTINGS_MODULE=config.settings.prod` (`wsgi.py` už `prod` používá).

**Soubor s proměnnými (`/etc/barf/app.env`) se nikdy nespouští shellem.** Webový proces ho čte
jako `EnvironmentFile=` systemd a denní úlohy jako `deploy/run_manage.sh` (§13.7), který ho
**jen rozebere**: řádky `NAME=hodnota`, komentáře na vlastním řádku, hodnota může být v jedněch
uvozovkách (`DJANGO_DEFAULT_FROM_EMAIL='BARF Nutri <noreply@barf.example.cz>'`), nic se
nerozvíjí (`$`, `` ` ``, `&`, `;` jsou obyčejné znaky). Vygenerovaný `DJANGO_SECRET_KEY`
(`get_random_secret_key()` vyrábí i znaky `$ & ( ) ! # % ^ * =`) proto lze zapsat tak, jak je.
Aby oba čtenáři viděli totéž, nepoužívejte v hodnotách zpětné lomítko ani uvozovku. Kdyby
soubor načítal shell (`. app.env`), vygenerovaný klíč by se většinou rozbil nebo tiše změnil a
chyba v uvozování by se provedla jako příkaz: proto se tak nikdy nenačítá. Soubor s tajemstvími
patří účtu aplikace a má režim `600` (`chmod 600 /etc/barf/app.env`).

### Skripty záloh

Skripty čtou připojení ze stejných proměnných `POSTGRES_*` jako Django. Proměnné mohou být v
prostředí, nebo v souboru, na který ukazuje `BARF_ENV_FILE`. Soubor se **jen čte**, nikdy se
neprovádí: řádky `NAME=hodnota`, prázdné řádky a řádky začínající `#` (komentář jen na vlastním
řádku), hodnota může být v jedněch uvozovkách, bez rozvoje proměnných. Převezmou se jen názvy
`POSTGRES_*`, `BACKUP_*`, `RESTORE_*`, `PGPASSFILE`, `PGSSLMODE`, `PGSSLROOTCERT`, `GNUPGHOME`;
ostatní řádky (například `DJANGO_*` ze sdíleného souboru) se přeskočí. Soubor musí mít režim `600`
(jinak se skript odmítne spustit). **Proměnná již nastavená v prostředí má přednost před souborem.**

| Proměnná | Skript | Význam |
|---|---|---|
| `BARF_ENV_FILE` | backup, restore, restore_test | Cesta k souboru s konfigurací (režim 600), nepovinná |
| `APP_ENV_FILE` | run_manage | Cesta k souboru s proměnnými aplikace (`app.env`, režim 600), povinná. Rozebírá se stejně jako `BARF_ENV_FILE`, ale přebírají se jen názvy `DJANGO_*` a `POSTGRES_*` a `DJANGO_SETTINGS_MODULE` má výchozí `config.settings.prod` |
| `POSTGRES_DB` | všechny | Zálohovaná (živá) databáze. Název: písmena, číslice, `_` a `-`, začíná písmenem nebo `_` |
| `POSTGRES_USER`, `POSTGRES_HOST` | backup, restore, restore_test | Role a server (název, adresa, nebo adresář soketu). **Server, který není lokální** (jiný než adresář soketu, `localhost`, `127.0.0.1`, `::1`), skript přijme jen s `PGSSLMODE` |
| `PGSSLMODE`, `PGSSLROOTCERT` | backup, restore, restore_test | `PGSSLMODE` musí být `require`, `verify-ca` nebo `verify-full`, jakmile je server vzdálený; výchozí chování knihovny libpq (`prefer`) při zásahu v síti tiše přejde na nešifrované spojení a záloha nese celou databázi. Doporučené je `verify-full` s kořenovým certifikátem v `PGSSLROOTCERT`. Jinak skript skončí kódem 2 |
| `POSTGRES_PORT` | všechny | Nepovinná, výchozí 5432 |
| `POSTGRES_PASSWORD`, `PGPASSFILE`, `PGPASSWORD` | všechny | Heslo, vyžaduje se aspoň jedno. Pořadí: `PGPASSFILE` (soubor v režimu 600, zděděné `PGPASSWORD` se zruší), potom `POSTGRES_PASSWORD`, potom zděděné `PGPASSWORD`. Heslo se předává jen prostředím, **nikdy argumentem** |
| `POSTGRES_MAINTENANCE_DB` | restore, restore_test | Databáze pro `CREATE`/`DROP DATABASE`, výchozí `postgres` |
| `BACKUP_DIR` | backup, restore_test | Absolutní cesta k adresáři záloh. Musí existovat a **nesmí být přístupný ostatním uživatelům** (režim `700`, nejvýše `750`) |
| `BACKUP_PASSPHRASE_FILE` | všechny | Soubor (režim 600), jehož první řádek je heslo k šifrování, alespoň 20 znaků |
| `RESTORE_TARGET_DB` | restore | Databáze, do které se obnovuje |
| `RESTORE_TEST_LOG` | restore_test | Absolutní cesta k protokolu měsíčního testu obnovy (adresář musí existovat) |
| `GNUPGHOME` | backup, restore, restore_test | Nepovinná, domovský adresář GnuPG (výchozí `~/.gnupg` uživatele, pod kterým skript běží) |

Skripty vyžadují bash 4.4+, GNU coreutils a Linux (`stat -c`, `readlink -f`, `date -d`), `gpg`
2.2.7+ (kvůli `--pinentry-mode loopback` a `--no-symkey-cache`), `pg_dump`, `pg_restore` a `psql` ve
verzi serveru nebo novější. `gpg` dostane prostředí bez `POSTGRES_PASSWORD`, `PGPASSWORD` a
`PGPASSFILE`: první volání spustí démona `gpg-agent`, který přežije skript a uchovává prostředí,
se kterým vznikl, takže by v něm heslo k databázi zůstalo i po jeho změně; heslo k zálohám
agent díky `--no-symkey-cache` neukládá.
Zprávy skriptů jsou anglicky (jako komentáře v nastavení), dokumentace česky.

## 13.3 Kontrolní seznam prvního nasazení 🛠

Příkazy se spouštějí z `backend/` s načtenými proměnnými z §13.2 a
`DJANGO_SETTINGS_MODULE=config.settings.prod`. Pořadí je důležité.

1. **Databáze.** Role aplikace a prázdná databáze (hesla ukládejte do správce hesel, ne do historie
   příkazů):
   `CREATE ROLE barf LOGIN PASSWORD '…'; CREATE DATABASE barf OWNER barf ENCODING 'UTF8' TEMPLATE template0;`
   V `pg_hba.conf` povolte roli jen z adresy aplikace a s `scram-sha-256`. Spojení přes síť
   šifrujte (`ssl = on` na serveru, `PGSSLMODE` u klienta; skripty záloh vzdálený server bez
   `PGSSLMODE=require|verify-ca|verify-full` odmítnou, §13.2).
2. **Kód a závislosti.** `python3 -m venv .venv && .venv/bin/pip install -e .` (bez vývojových závislostí, tedy
   bez extra `dev`).
   Verze jsou zamčené v `pyproject.toml`; WSGI server (§13.5) a jeho verzi přidejte vlastním,
   zamčeným souborem požadavků (v `pyproject.toml` není).
3. `manage.py migrate`. Vytvoří tabulky, role (skupiny `owner`, `vet`, `data_curator`,
   `nutrition_reviewer`), číselník zdravotních stavů a knihovnu zdrojů.
4. `manage.py createcachetable`. Limity e-mailů z účtu žijí ve sdílené databázové cache
   (`django_cache`); bez tabulky selže registrace a obnova hesla.
5. `manage.py collectstatic --noinput`. Připraví soubory s otisky v názvu do `DJANGO_STATIC_ROOT`
   (§13.6). Opakovat při každé aktualizaci.
6. `manage.py load_sources`. Idempotentní (podruhé „beze změny“); `migrate` už zdroje načetl,
   příkaz je potřeba jen po změně `backend/catalog/data/sources.json`.
7. `manage.py createsuperuser`. Zadejte e-mail a silné heslo. Bez terminálu lze použít
   `DJANGO_SUPERUSER_EMAIL` a `DJANGO_SUPERUSER_PASSWORD` s `--noinput`, heslo pak ale zůstane
   v historii nebo v prostředí: raději interaktivně.
8. **Přidělení rolí v administraci** (`/admin/`): *Uživatelské účty → Uživatelé*, vyberte účet,
   v *Oprávnění a role* přidejte skupinu (`vet`, `data_curator`, `nutrition_reviewer`) a uložte.
   Registrace vytvoří vždy jen roli `owner`. Podrobně: README, *Role veterinárního lékaře*.
9. `manage.py check --deploy`. Očekávané upozornění je jediné: `security.W021` (HSTS preload,
   §13.2). Cokoli jiného před spuštěním opravte.
10. **Spusťte WSGI server, proxy a plánovač** (§13.5, §13.7) a hned **zálohujte a otestujte
    obnovu** (§13.8), ještě než se do aplikace vloží první skutečná data.
11. Do textů *Podmínky užití* a *Ochrana osobních údajů* doplňte údaje provozovatele
    (`[DOPLNÍ PROVOZOVATEL]`, `[DOPLNÍ PRÁVNÍK]`, [12](12-ucty-a-zvirata.md) §12.8).

**Aktualizace aplikace:** záloha, nový kód a závislosti, `migrate`, `collectstatic`, restart
pracovních procesů, kontrola `check --deploy`. Migrace s nevratnou změnou dat se zkouší nejdřív
na kopii z posledního testu obnovy.

## 13.4 Co bylo a nebylo vyzkoušeno (stručně) 🛠

Podrobně v §13.12. Kroky 3 až 7 a 9 z §13.3, `purge_pending_accounts` a `clearsessions` byly
spuštěny s `config.settings.prod` na pokusné databázi a skripty záloh mají 149 automatických testů.
**Nasazení za skutečnou proxy s TLS, WAL archivace, přenos záloh mimo server a běh pod cronem
vyzkoušené nejsou.**

## 13.5 WSGI server za reverzní proxy s TLS 🛠

Aplikace běží jako WSGI (`config.wsgi:application`) na adrese `127.0.0.1` nebo na soketu a **nikdy
není dostupná přímo z internetu**. TLS ukončuje reverzní proxy (nginx, Caddy, HAProxy), která:

1. přesměruje HTTP na HTTPS (aplikace sama přesměrovává také: `SECURE_SSL_REDIRECT`);
2. **přepisuje** hlavičky `X-Forwarded-Proto` (hodnota `https`) a `X-Forwarded-For` (připíše adresu
   klienta), nikdy je nepřebírá od klienta;
3. předává původní `Host` a servíruje statické soubory (§13.6).

Nastavení aplikace za proxy (musí platit **všechno najednou**, jinak aplikace nenastartuje, nebo
neumí ověřit HTTPS):

```bash
DJANGO_SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https
DJANGO_TRUSTED_PROXY_COUNT=1          # počet proxy, které připisují X-Forwarded-For
DJANGO_ALLOWED_HOSTS=barf.example.cz
DJANGO_CSRF_TRUSTED_ORIGINS=https://barf.example.cz
```

**Počet důvěryhodných proxy.** Zámek přihlášení (`django-axes`, 5 chyb, 1 hodina) je podle e-mailu
a adresy klienta. Za proxy je `REMOTE_ADDR` adresa proxy, takže adresu klienta bere aplikace z
`X-Forwarded-For`: je to **N-tý údaj zprava**, kde N je `DJANGO_TRUSTED_PROXY_COUNT`; údaje vlevo
dodává klient a ignorují se. Jedna proxy před aplikací znamená 1, proxy za CDN 2. Špatná hodnota
dvojím způsobem škodí: příliš nízká zamyká všechny uživatele společně pod adresou proxy, příliš
vysoká dovolí obejít zámek podvrženou hlavičkou. Po nastavení ověřte, že u neúspěšného přihlášení je v
administraci (*Axes → Pokusy o přístup*) adresa klienta, ne adresa proxy.

Příklad pro gunicorn (WSGI server není součástí `pyproject.toml`; zamkněte jeho verzi sami):

```bash
cd backend && ../.venv/bin/python -m gunicorn config.wsgi:application \
    --bind 127.0.0.1:8000 --workers 3 --forwarded-allow-ips 127.0.0.1 \
    --access-logfile - --error-logfile -
```

`--forwarded-allow-ips` musí obsahovat jen adresu proxy. Počet pracovních procesů a časové limity
upravte podle zátěže (nebylo měřeno).

Příklad nginx 🟡 netestováno (nginx zde nebyl k dispozici, certifikáty a cesty upravte):

```nginx
server {
    listen 80;
    server_name barf.example.cz;
    return 301 https://$host$request_uri;
}
server {
    listen 443 ssl;
    server_name barf.example.cz;
    ssl_certificate     /etc/letsencrypt/live/barf.example.cz/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/barf.example.cz/privkey.pem;

    location /static/ {                       # collectstatic, DJANGO_STATIC_ROOT
        alias /srv/barf/staticfiles/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    }
}
```

Aplikace posílá hlavičky `Strict-Transport-Security`, `Content-Security-Policy`, `X-Frame-Options`,
`X-Content-Type-Options` a `Referrer-Policy` sama; proxy je nemá duplikovat.

## 13.6 Statické soubory 🛠

S `DEBUG = False` aplikace statické soubory **neservíruje** (ověřeno: `/static/css/app.css` vrací
404). Bez nastavené proxy by stránky neměly styly. `collectstatic` zkopíruje soubory do
`DJANGO_STATIC_ROOT` a `ManifestStaticFilesStorage` jim dá otisk obsahu do názvu (`app.<otisk>.css`),
proto je lze cachovat natrvalo (`immutable`, příklad v §13.5). Adresář musí číst uživatel webového
serveru, zapisovat jen ten, kdo spouští `collectstatic`. `collectstatic` bez `--clear` staré soubory
nemaže, takže stránky načtené před aktualizací najdou své soubory; starší verze lze po čase smazat ručně.

## 13.7 E-mail a denní úlohy 🛠

**E-mail.** Aktivace registrace a obnova hesla se posílají přes SMTP (`DJANGO_EMAIL_*`). Odesílání
probíhá až po odpovědi serveru (`ACCOUNT_EMAIL_IN_BACKGROUND`), aby doba odpovědi neprozradila, zda
účet existuje. Selhání SMTP se proto nezobrazí uživateli, ale jen v protokolu aplikace jako chyba
`Sending account e-mail … failed` (logger `accounts.services`): sledujte ho. Doména odesílatele potřebuje SPF a DKIM, jinak aktivační e-maily končí ve
spamu 🟡 netestováno.

**Denní úlohy** (cron nebo systemd timer, vzor v `deploy/crontab.example`):

| Úloha | Příkaz | Co dělá |
|---|---|---|
| Neaktivované registrace | `deploy/run_manage.sh purge_pending_accounts` (= `manage.py`, §13.2) | Smaže registrace, které nikdo neaktivoval do 7 dnů (`PENDING_ACCOUNT_RETENTION`). Je to osobní údaj osoby, která registraci možná nezaložila ([12](12-ucty-a-zvirata.md) §12.8, bod 8) |
| Prošlé relace | `deploy/run_manage.sh clearsessions` | Maže prošlé relace z databáze (jinak tabulka `django_session` jen roste) |
| Záloha | `deploy/backup_db.sh` | §13.8 |
| Test obnovy | `deploy/restore_test.sh` | Jednou měsíčně, §13.10 |

`run_manage.sh` načte `APP_ENV_FILE` (parsováním, ne shellem), nastaví `DJANGO_SETTINGS_MODULE`
(výchozí `config.settings.prod`) a spustí `.venv/bin/python manage.py …` v adresáři `backend/`
stejného repozitáře. Crontab zapisuje výstup do `/var/log/barf/` (úlohy aplikace) a
`/var/log/barf-backup/` (zálohy, §13.8) a při selhání vypíše jednu řádku, kterou cron
pošle poštou na `MAILTO`. **Úloha, která nikdy neběžela, žádnou poštu nepošle**: proto je v
kontrolním seznamu (§13.13) ruční kontrola stáří nejnovější zálohy.

## 13.8 Zálohování databáze 🛠

### Co se zálohuje a jak

`backup_db.sh` vytvoří **logickou zálohu** celé databáze `POSTGRES_DB`:

1. Otevře jednu relaci `REPEATABLE READ`, exportuje z ní snímek (`pg_export_snapshot`) a ve
   stejném snímku zjistí seznam tabulek a počty řádků tabulek uživatelů (`accounts_user`),
   zvířat (`animals_animal`) a zdrojů (`catalog_scientificsource`).
2. Spustí `pg_dump --format=custom --snapshot=…` a výstup **rourou** přivede do
   `gpg --symmetric --cipher-algo AES256`. **Nešifrovaná záloha nikdy nevznikne na disku.**
   Heslo čte `gpg` ze souboru (`--passphrase-file`, dávkový režim).
3. Šifrovaný soubor nejdřív zapíše pod dočasným názvem, rozšifruje ho a ověří, že je to čitelný
   archiv PostgreSQL (`pg_restore --list`). Teprve potom ho přejmenuje na
   `barf-RRRRmmddTHHMMSSZ.dump.gpg` (čas UTC) a vedle zapíše **manifest** `….dump.gpg.sha256`.
4. Provede retenci (§13.9).

Manifest má formát `sha256sum` (`sha256sum --check` ho zná) a v řádcích `# klíč=hodnota` nese
seznam tabulek a počty řádků **ve stejném snímku jako záloha**. Díky tomu se počty při testu obnovy
porovnávají přesně, i když aplikace během zálohy zapisuje (vyzkoušeno, §13.12).

Kontrolní součet odhalí poškození a omylem změněný soubor. Úmyslnou změnu hlídá šifrování s
kontrolou integrity (GnuPG) spolu s tajným heslem: kdo heslo nezná, nepodvrhne platnou zálohu.
Zálohu z nedůvěryhodného zdroje přesto neobnovujte rovnou do ostré databáze, ale nejdřív do
pomocné.

Při jakékoli chybě skript skončí nenulovým kódem a **nezanechá žádný soubor** (dočasné soubory se
mažou, i po přerušení Ctrl-C nebo `systemctl stop`, které zastaví celou skupinu procesů; `kill`
samotného skriptu se projeví až po dokončení běžícího kroku). Po `kill -9` nebo výpadku proudu může
zůstat soubor `.barf-partial.*`; je neúplný, smažte ho ručně. Kód 2 znamená chybnou konfiguraci nebo odmítnutí z bezpečnostního důvodu. Skript se
odmítne spustit, když chybí proměnná, `BACKUP_DIR` je čitelný pro ostatní, soubor s heslem má
volná práva nebo heslo kratší než 20 znaků.

### Účty operačního systému: zálohy odděleně od aplikace 🛠

Zálohy, heslo k jejich šifrování a heslo zálohovací role **nepatří účtu, pod kterým běží webová
aplikace**. Kdo získá vykonávání kódu ve webovém procesu (chyba v aplikaci nebo závislosti), by
jinak přečetl heslo i staré zašifrované zálohy, tedy také údaje, které už byly z živé databáze
smazány (§13.14), a mohl by lokální zálohy smazat nebo přepsat. Zálohovací role jen ke čtení v
PostgreSQL (níže) chrání databázi, ne soubory na disku. Doporučené rozdělení:

| Účet | Vlastní a smí číst | Spouští |
|---|---|---|
| `barf` (aplikace) | `/etc/barf/app.env` (600), `/var/log/barf/` | WSGI server, denní úlohy aplikace (`run_manage.sh`) |
| `barf-backup` | `/etc/barf/ops.env`, `restore.env`, `backup-passphrase`, `pgpass` (vše 600), `BACKUP_DIR` `/var/backups/barf` (700), `/var/log/barf-backup/` | `backup_db.sh`, `restore_test.sh`, kopírování záloh mimo server |
| `root` | `/opt/barf` včetně `deploy/` (kód, nikdo jiný nezapisuje) | instalace a aktualizace |

Účet `barf` nečte nic z `/etc/barf` kromě `app.env` ani `/var/backups/barf`; účet `barf-backup`
nečte `app.env`. Skripty `deploy/` patří rootovi a účet aplikace je nemůže změnit, protože
běží s právy záloh. Přenos záloh mimo server (§13.11) patří také účtu `barf-backup`.

**Obnova ostré databáze** (§13.10) je zásah správce: spouští ji osoba s přístupem k heslu k
zálohám (například `sudo -u barf-backup`), ne webová aplikace.

🟡 *Netestováno:* rozdělení na dva účty se zde nezkoušelo (vývojové prostředí běží pod jedním
uživatelem; skripty a testy práva souborů kontrolují, ale oba účty nevytvářejí). Příkazy
ověřte při nasazení.

### Příprava (jednorázově)

```bash
# Jako root. Hesla vytvořte náhodně a uložte je podle §13.11. Heslo k šifrování NEZTRATIT (§13.13).
useradd --system --create-home --home-dir /var/lib/barf-backup --shell /usr/sbin/nologin barf-backup
install -d -m 755 /etc/barf
install -d -o barf-backup -g barf-backup -m 700 /var/backups/barf /var/log/barf-backup
install -d -o barf -g barf -m 750 /var/log/barf
for soubor in backup-passphrase pgpass ops.env restore.env; do
    install -o barf-backup -g barf-backup -m 600 /dev/null "/etc/barf/$soubor"
done
install -o barf -g barf -m 600 /dev/null /etc/barf/app.env
# ">" zachová vlastníka a režim souboru, který už existuje.
openssl rand -base64 36 > /etc/barf/backup-passphrase          # první řádek je heslo
printf '%s\n' 'localhost:5432:*:barf_backup:HESLO_ZALOHOVACI_ROLE' > /etc/barf/pgpass
```

Role v PostgreSQL (vyzkoušeno ručně, §13.12): **zálohovací role jen ke čtení** a **samostatná role pro
test obnovy**, každá s vlastním souborem `BARF_ENV_FILE`. Zálohovací role nemůže data měnit; kdo
ukradne její údaje, nesmaže produkci.

```sql
CREATE ROLE barf_backup LOGIN PASSWORD '…' IN ROLE pg_read_all_data;   -- PostgreSQL 14+
CREATE ROLE barf_restore LOGIN PASSWORD '…' CREATEDB;                  -- jen pro test obnovy
```

`/etc/barf/ops.env` (záloha) a `/etc/barf/restore.env` (test obnovy), oba vlastní `barf-backup`, režim 600:

```
POSTGRES_DB=barf
POSTGRES_USER=barf_backup
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
PGPASSFILE=/etc/barf/pgpass
BACKUP_DIR=/var/backups/barf
BACKUP_PASSPHRASE_FILE=/etc/barf/backup-passphrase
```

Je-li databáze na **jiném serveru**, přidejte `PGSSLMODE=verify-full` a
`PGSSLROOTCERT=/etc/barf/db-ca.crt`; bez `PGSSLMODE` (`require`, `verify-ca` nebo `verify-full`)
skript vzdálený server odmítne (§13.2).

V `restore.env` je `POSTGRES_USER=barf_restore`, vlastní `PGPASSFILE` (v souboru je heslo role
`barf_restore`; řádek `localhost:5432:*:barf_restore:…` s hvězdičkou, protože test obnovy se
připojuje i k pomocným databázím) a navíc `RESTORE_TEST_LOG=/var/log/barf-backup/restore-test.log`.

### Spuštění a plán

```bash
# jako účet barf-backup (sudo -u barf-backup …)
BARF_ENV_FILE=/etc/barf/ops.env deploy/backup_db.sh        # vypíše cestu k nové záloze
BARF_ENV_FILE=/etc/barf/ops.env deploy/backup_db.sh --prune-only   # jen retence
```

Plán: `deploy/crontab.example` obsahuje **dva crontaby**: pro účet `barf-backup` (záloha denně, test
obnovy 3. dne v měsíci) a pro účet `barf` (denní úlohy aplikace, §13.7).
Zálohovat se má alespoň jednou denně; retence počítá soubory (§13.9).

Po zálohování **přeneste soubory mimo server** (§13.11). Skripty to záměrně nedělají.

## 13.9 Retence 🛠

Podle [07](07-django-schema.md) §7.7: **30 denních záloh a měsíční zálohy 12 měsíců.** `backup_db.sh`
po každé úspěšné záloze ponechá:

- **nejnovějších 30 záloh** (počítají se soubory, při jedné záloze denně je to 30 dní);
- **první zálohu každého z posledních 12 kalendářních měsíců**; měsíce se počítají zpětně od
  měsíce nejnovější zálohy (včetně něj);

všechny ostatní soubory s názvem **přesně** `barf-RRRRmmddTHHMMSSZ.dump.gpg` (včetně platného
data a času) smaže i s jejich manifestem. Cizí soubory, složky, odkazy a soubory s jiným názvem
se nikdy nemažou (test to ověřuje na řadě podobných názvů). Osiřelý manifest (bez zálohy) se smaže.
Retence čte čas **z názvů souborů**, ne z hodin serveru ani z data souboru, takže po výpadku
zálohování se poslední dobré zálohy nesmažou. Obráceně to znamená, že při dlouhém výpadku staré
soubory zůstanou, dokud nevzniknou nové: stáří nejnovější zálohy proto hlídejte zvlášť (§13.13).

**Názvy napřed před hodinami serveru.** Jediné, co se s hodinami serveru porovnává: název, jehož
čas je o **víc než jeden den napřed**, se do výpočtu nezapočítá a **nikdy se nemaže**. Vzniká,
když se hodiny serveru vrátily zpět (vybitá baterie hodin, obnovený snímek virtuálního stroje),
nebo když do adresáře někdo vloží soubor s budoucím datem (adresář se skupinou s právem zápisu).
Kdyby se započítal, byl by „nejnovější“ zálohou: posunul by okno 12 měsíců do budoucnosti
(jediný soubor `barf-20991231T235959Z.dump.gpg` stačil ke smazání všech měsíčních záloh) a 30
takových názvů by vytlačilo i právě vytvořenou zálohu. Skript je hlásí v protokolu řádkou
`WARNING … ahead of the clock` (a `N ignored` v závěrečném řádku). Zkontrolujte hodiny, nebo
soubory odstraňte ručně; do té doby zůstávají.

**Právě vytvořená záloha se nikdy nesmaže.** Kdyby ji pravidlo vyřadilo (v adresáři je 30 a víc
novějších názvů, které ještě nejsou „z budoucnosti“), skript **nesmaže nic**, zapíše `ERROR` a
skončí kódem 1; záloha zůstává.

**Neřešeno:** hodiny, které skočí **dopředu**, skript nepozná (název z budoucnosti je pak
skutečně nejnovější). Hodiny serveru proto udržujte synchronizované (NTP). Obě chování
ověřují `tests/ops/test_ops_prune.py` a `test_ops_backup.py` (§13.12).

Retence se týká jen adresáře `BACKUP_DIR`. **Kopie mimo server mají vlastní pravidlo**, které musí
dávat stejné lhůty (jinak zůstanou osobní údaje déle, než slibuje *Ochrana osobních údajů*, §13.14).

## 13.10 Obnova a měsíční test obnovy 🛠

### Obnova: `restore_db.sh`

```bash
RESTORE_TARGET_DB=barf_obnova BARF_ENV_FILE=/etc/barf/restore.env \
    deploy/restore_db.sh --create /var/backups/barf/barf-20261021T001723Z.dump.gpg
```

Skript: (1) ověří kontrolní součet z manifestu, (2) jednou rozšifruje zálohu „do ztracena“ (špatné
heslo nebo poškozený soubor se zjistí před zásahem do databáze), (3) rozšifruje ji do roury a
spustí `pg_restore --no-owner --no-privileges --single-transaction`. Objekty patří obnovující roli
a celé obnovení je **jedna transakce**: nepovede-li se, databáze zůstane beze změny. **Objekty
patří roli, pod kterou obnovu spustíte**: obnovu ostré databáze proto spouštějte pod rolí aplikace
(ne pod rolí z `restore.env`), jinak aplikace k tabulkám nedostane přístup. Cílová databáze musí
být prázdná. S `--create` se neexistující vytvoří a při nezdaru zase zahodí (jen
ta, kterou skript sám vytvořil).

**Ochrana ostré databáze.** Je-li `RESTORE_TARGET_DB` stejná jako `POSTGRES_DB`, skript odmítne
(kód 2), dokud nepřidáte `--i-know-this-overwrites-production`. Pak nahradí tabulky ze zálohy
(`pg_restore --clean --if-exists`); objekty, které v záloze nejsou, zůstanou.

**Ochrana systémových databází.** `RESTORE_TARGET_DB` nesmí být `postgres`, `template0`,
`template1` ani `POSTGRES_MAINTENANCE_DB` (kód 2, nic se nezmění). Prázdná `template1` nebo
`postgres` by jinak prošla kontrolou „cíl je prázdný“ a údaje majitelů a zvířat by se zkopírovaly
do každé databáze vytvořené později (včetně pomocných databází testu obnovy). Z toho plyne, že
živá databáze aplikace se nesmí jmenovat `postgres` ani `template1`.

### Postup při ztrátě nebo poškození databáze

1. **Zastavte aplikaci** (WSGI server), ať nikdo nezapisuje. Zachovejte, co se dá (zkopírujte
   poškozenou databázi nebo aspoň protokoly), a zapište čas události.
2. Vyberte zálohu: po havárii nejnovější, po chybě v datech poslední před chybou. Jméno souboru
   říká čas UTC. Po obnově záznamů do pomocné databáze si ji prohlédněte, než ji nasadíte.
3. **Doporučený postup (bez přepisu):** obnovte do nové databáze, zkontrolujte ji a pak prohoďte
   názvy. Příkazy `psql` spouští superuživatel, obnovu role aplikace (`barf`; soubor s jejími
   údaji např. `/etc/barf/recover.env`, režim 600):
   ```bash
   psql -d postgres -c "CREATE DATABASE barf_nova OWNER barf ENCODING 'UTF8' TEMPLATE template0"
   BARF_ENV_FILE=/etc/barf/recover.env RESTORE_TARGET_DB=barf_nova \
       deploy/restore_db.sh /var/backups/barf/barf-….dump.gpg
   # po kontrole, aplikace je zastavená a nikdo není připojen:
   psql -d postgres -c 'ALTER DATABASE barf RENAME TO barf_stara' \
                    -c 'ALTER DATABASE barf_nova RENAME TO barf'
   ```
   Stará databáze zůstane jako `barf_stara` pro případ, že obnova nestačí.
4. **Přepis na místě** (když přejmenování nejde): pod rolí aplikace `RESTORE_TARGET_DB=barf` (stejné
   jako `POSTGRES_DB`) a `--i-know-this-overwrites-production`. Objekty, které v záloze nejsou,
   zůstanou; proto je přejmenování čistší.
5. **Nový server bez databáze:** vytvořte roli a prázdnou databázi (`CREATE DATABASE barf OWNER
   barf …`), nainstalujte aplikaci (§13.3 kroky 1 a 2) a spusťte
   `restore_db.sh --i-know-this-overwrites-production …` pod rolí aplikace (cíl je stejný jako
   `POSTGRES_DB`, proto příznak). Potom `manage.py migrate` (nic nezmění) a `check --deploy`.
6. Spusťte aplikaci, přihlaste se, zkontrolujte přehled a knihovnu zdrojů.
7. **Znovu proveďte výmazy a změny po záloze** (§13.14) a zapište incident (§13.13).

### Měsíční test obnovy: `restore_test.sh`

Požadavek [07](07-django-schema.md) §7.7. Skript obnoví **nejnovější** zálohu do pomocné databáze
`barf_restore_test_<čas UTC>`, zkontroluje ji a **vždy ji zahodí** (databáze, kterou nelze zahodit,
je FAIL: držela by kopii osobních údajů). Kontroly:

- existují tabulky: `django_migrations`, `accounts_user`, `animals_animal`,
  `animals_bodymeasurement`, `catalog_scientificsource`;
- seznam tabulek je stejný jako v manifestu (je-li zapsán);
- počty řádků v `accounts_user`, `animals_animal` a `catalog_scientificsource` se rovnají počtům
  ze stejného snímku jako záloha (manifest). Záloha bez zapsaných počtů se nesrovnává, počty se
  jen vypíšou.

Výsledek je jedna řádka v `RESTORE_TEST_LOG` (a na standardním výstupu):

```
2026-11-03T03:41:18Z file=barf-20261103T011723Z.dump.gpg result=OK users=212 animals=348 sources=37 note=tables present, counts equal the manifest
2026-12-03T03:41:20Z file=barf-20261203T011722Z.dump.gpg result=FAIL users=- animals=- sources=- note=restore into barf_restore_test_20261203t034119z failed (see the messages above)
```

Sloupce: čas UTC, soubor, `OK`/`FAIL`, počty uživatelů, zvířat a zdrojů (`-` = nezjištěno) a
poznámka. Nenulový návratový kód (1) = FAIL, kód 2 = chybná konfigurace (neproběhl žádný test a
nezapsala se žádná řádka).

**Protokol testů obnovy** (vedejte též ručně, např. v provozním deníku):

| Datum | Záloha | Výsledek | Kdo zkontroloval | Poznámka |
|---|---|---|---|---|
| (doplní provozovatel) | | | | |

Při FAIL: 1. Neignorujte. 2. Podívejte se do protokolu (`/var/log/barf-backup/restore-test.log`), kde je
důvod. 3. Udělejte novou zálohu a test opakujte. 4. Nepovede-li se, berte **všechny** zálohy jako
nepoužitelné, dokud se příčina nenajde (§13.13). Jednou ročně doporučujeme **ruční zkoušku**:
obnovit zálohu do kopie, nechat na ní běžet aplikaci a přihlásit se (🛠 doporučení).

## 13.11 Kam zálohy patří 🛠

- **Mimo hlavní infrastrukturu** ([07](07-django-schema.md) §7.7): jiný účet, poskytovatel nebo
  oblast než server s databází. Záloha na stejném disku nechrání před jeho ztrátou, ransomwarem
  ani chybou správce. Skript zapisuje jen do `BACKUP_DIR`, přenos zajistěte zvlášť (rsync přes SSH,
  nástroj pro objektové úložiště apod. 🟡 netestováno) a hlídejte jeho výsledek.
- **Šifrované už při vzniku.** Soubory jsou AES-256 zašifrované před uložením, přenos mimo server
  proto smí běžet i přes nedůvěryhodné úložiště; přesto přenášejte přes TLS nebo SSH.
- **Samostatný účet operačního systému pro zálohy** (`barf-backup`, §13.8): zálohy, heslo k nim
  a soubor s heslem zálohovací role nesmí číst ani měnit účet webové aplikace. Útočník, který
  získá kód ve webovém procesu, jinak rozšifruje i údaje, které už byly z živé databáze smazány
  (§13.14), a může zálohy smazat. Skripty v `deploy/` patří rootovi. Tento bod zatím není
  vyzkoušený na skutečném serveru (§13.12).
- **Heslo k šifrování uchovávejte odděleně od záloh**: jiný systém, jiný účet, jiná osoba nebo
  alespoň správce hesel a uzavřená obálka v trezoru. Kdo má zálohy i heslo, má všechna data.
  Aby zálohy šly dělat automaticky, leží heslo i na serveru (`/etc/barf/backup-passphrase`, režim
  600). Jeho kopie mimo server (pro obnovu) ale nesmí ležet vedle záloh, a server nemá mít právo
  kopie záloh mimo server mazat.
- **Mimo server jen přidávat.** Přihlášení, kterým se zálohy kopírují, nemá mazat; mazání řídí
  životní cyklus úložiště (stejné lhůty jako §13.9). Zrcadlení s mazáním (`rsync --delete` apod.)
  by útočníkovi, který smaže místní zálohy, smazalo i kopie.
- **Starší hesla** po výměně uschovejte po celou dobu, kdy existují zálohy jimi zašifrované
  (až 12 měsíců): staré zálohy otevře jen staré heslo.
- **Přístup** k záloze má jen správce; v seznamu osob s přístupem jsou jména, ne sdílené účty.

## 13.12 Co se vyzkoušelo a co ne 🛠

Vývojové prostředí: PostgreSQL 16.15 (localhost), GnuPG 2.4.4, bash 5.2, coreutils 9.4,
Debian/Ubuntu.

**Vyzkoušeno:**

- `tests/ops/` (149 testů; pracují jen s pokusnými databázemi `barf_ops_test_*` a
  `barf_restore_test_*`, které si vytvoří test obnovy, a nikdy nesahají na `barf` ani `test_barf`): záloha vytvoří právě jeden `.gpg` a jeden `.sha256`; soubor není bez
  rozšifrování platný dump a neobsahuje čitelné údaje; obnova do nové databáze reprodukuje obsah
  **všech** tabulek (MD5 přes text všech řádků každé tabulky); odmítnutí ostré databáze bez příznaku a přepis s ním;
  neúspěšný přepis ostré databáze nezmění nic (jedna transakce); poškozený soubor (kontrolní součet,
  i poškození s přepsaným manifestem, i useknutý archiv); záloha selže při chybějící proměnné, při
  světově čitelném `BACKUP_DIR`, volných právech k heslu, krátkém hesle a nezanechá žádný soubor;
  retence na vytvořených názvech souborů včetně nahodilých (`hypothesis`) a ochrany cizích souborů;
  **názvy napřed před hodinami serveru** se nezapočítají a nemažou (jediný soubor z roku 2099
  nesmaže měsíční zálohy; 31 názvů „z budoucnosti“ nesmaže novou zálohu) a záloha, kterou by
  pravidlo vyřadilo, zůstane s kódem 1 (§13.9); **vzdálený server bez `PGSSLMODE`** všechny tři
  skripty odmítnou (kód 2), lokální (soket, `localhost`, `127.0.0.1`, `::1`) projdou; **obnova do
  `postgres`, `template0`, `template1` a do udržovací databáze** se odmítne (testy používají
  poškozený soubor, takže systémovou databázi nemohou změnit ani při chybě pravidla); `gpg`
  nedostane `POSTGRES_PASSWORD`, `PGPASSWORD` ani `PGPASSFILE` (obal na `gpg` zapisuje své
  prostředí);
  `run_manage.sh`: 200 vygenerovaných klíčů `get_random_secret_key()` dorazí beze změny, `$(…)`,
  `;`, `&` a `$HOME` v hodnotě se nespustí ani nerozvinou, jiné názvy než `DJANGO_*` a
  `POSTGRES_*` se přeskočí, soubor s volnými právy se odmítne;
  `.gitignore` zachytí soubory `*.env`, `*passphrase*`, `*pgpass*`, `*.dump`, `*.dump.gpg`;
  test obnovy zapíše `OK` a `FAIL` (poškozená záloha, rozdílné počty, rozdílný seznam tabulek,
  chybějící tabulky, žádná záloha) a vždy zahodí pomocnou databázi; **žádný program nedostane heslo
  ani tajemství v argumentech** (zachyceno obalem na `pg_dump`, `psql`, `pg_restore`, `gpg`).
- `shellcheck` 0.10.0 bez nálezů (test se přeskočí, když není nainstalován).
- Ručně: záloha při souběžném zápisu do databáze (počty v manifestu se po obnově shodovaly přesně);
  záloha rolí jen ke čtení (`pg_read_all_data`) a test obnovy rolí s `CREATEDB`, role bez
  `CREATEDB` test obnovy správně odmítne; první nasazení s `config.settings.prod` na pokusné
  databázi (`migrate`, `createcachetable`, `collectstatic`, `load_sources`,
  `createsuperuser --noinput`, `purge_pending_accounts`, `clearsessions`, `check --deploy`) s
  proměnnými ze souboru `app.env` načteného skriptem `run_manage.sh`, včetně vygenerovaného klíče
  s `$ & # ( ) ^ %` bez uvozovek (`migrate`, `clearsessions`, `purge_pending_accounts`,
  `check --deploy` s `config.settings.prod`: jediné upozornění `security.W021`); gunicorn s
  hlavičkami proxy zadanými ručně (`curl`): bez `X-Forwarded-Proto: https` přesměrování 301, s ní
  200, cizí `Host` 400, `/static/` 404.

**Nevyzkoušeno (🟡):**

- skutečná reverzní proxy (příklad nginx), certifikáty TLS, chování `X-Forwarded-For` za více
  proxy a ověření zámku přihlášení z různých adres;
- **WAL archivace a obnova k okamžiku (§13.15)**: vyžaduje úpravu `postgresql.conf` a restart
  serveru;
- běh pod cronem a systemd a zasílání pošty na `MAILTO` (příkazy z `crontab.example` byly spuštěny
  ručně v ekvivalentní podobě, rozpis se kontroluje jen staticky);
- **rozdělení na účty `barf` a `barf-backup`** (§13.8): práva souborů skripty a testy kontrolují,
  ale dva účty se zde nevytvářely; stejně tak chování cronu pro účet s `nologin`;
- **TLS k vzdálenému PostgreSQL**: pravidlo `PGSSLMODE` se kontroluje, spojení s TLS se zde
  nezkoušelo (lokální server je bez TLS a vzdálený server nebyl k dispozici);
- přenos záloh mimo server a jejich životní cyklus;
- zálohování velké databáze (snímek drží transakci po celou dobu zálohy; u malé databáze trvá
  sekundy), výkon při zátěži, obnova na jinou hlavní verzi PostgreSQL nebo s jinou kolací;
- odesílání e-mailů přes skutečný SMTP server;
- jiný systém než Linux (skripty používají GNU `stat`, `readlink -f`).

## 13.13 Kontrolní seznam provozu a incidentů 🛠

**Pravidelně**

| Kdy | Co |
|---|---|
| Denně (nebo upozornění) | Existuje záloha ne starší než 26 hodin v `BACKUP_DIR` **i mimo server**; pošta z cronu je prázdná |
| Měsíčně | V `RESTORE_TEST_LOG` je nová řádka `result=OK`; zapsat do protokolu (§13.10) |
| Ročně | Ruční zkouška obnovy včetně spuštění aplikace; kontrola, že heslo k šifrování otevře nejstarší zálohu a že kopie hesla existuje na dvou místech |
| Při změně správce | Vyměnit hesla (databáze, `DJANGO_SECRET_KEY`, SMTP, heslo k zálohám, §13.11), odebrat přístupy |

**Incidenty**

| Situace | Postup |
|---|---|
| **Ztracené nebo zapomenuté heslo k šifrování** | **Zálohy zašifrované tímto heslem jsou nenávratně ztracené.** Žádný záložní klíč neexistuje (AES-256 symetricky). Vytvořte okamžitě nové heslo a novou zálohu, starou řadu ověřte jinou kopií hesla. Prevence: aspoň dvě nezávislá místa (§13.11) |
| Heslo k šifrování uniklo | Vytvořte nové heslo a novou zálohu (`backup_db.sh` s novým `BACKUP_PASSPHRASE_FILE`); staré zálohy buď smažte, nebo přešifrujte (rozšifrovat starým heslem a zašifrovat novým, ručně přes `gpg`). Pokud unikly i soubory záloh, jde o **únik osobních údajů**: posuďte s právníkem povinnost hlášení ([12](12-ucty-a-zvirata.md) §12.8, lhůta podle GDPR čl. 33 je 72 hodin) |
| Záloha nevznikla, soubor starší než 26 h | Podívejte se do `/var/log/barf-backup/backup.log`. Nejčastěji plný disk, změněné heslo role, nedostupný server. Opravit a spustit ručně |
| `restore_test.sh` skončil FAIL | Viz §13.10; do opravy nelze spoléhat na žádnou zálohu |
| Databáze ztracena nebo poškozena | Postup v §13.10 |
| Server napaden, podezření na únik | Odpojit aplikaci; zachovat kopii disku a protokolů; vyměnit **všechna** tajemství (`DJANGO_SECRET_KEY` odhlásí všechny, heslo databáze, SMTP, heslo k zálohám); zálohy mimo server berte jako důvěrné; únik řešit s právníkem |
| Disk se plní zálohami | Zkontrolujte, že retence běží (v protokolu „retention: N backup(s) kept“); `--prune-only` ji spustí ručně. Nikdy nemažte soubory ručně podle data bez ohledu na retenci |
| Obnova ze zálohy vrátila smazaný účet | §13.14: výmaz je třeba provést znovu |

## 13.14 GDPR: smazaný účet zůstane v zálohách 🛠

Smazání účtu v aplikaci smaže údaje z živé databáze (včetně historie změn, [12](12-ucty-a-zvirata.md)
§12.6). **V záloze, která vznikla před smazáním, zůstávají až do konce retence**: nejdéle
**12 měsíců** (první záloha měsíce), běžně 30 dní. Totéž platí pro archiv WAL (§13.15), pokud se
používá, a pro kopie mimo server. Texty *Ochrana osobních údajů* a stránka po smazání účtu to
zatím uvádějí jen jako zástupný text ([12](12-ucty-a-zvirata.md) §12.8, body 6 a 12).

K posouzení právníkem (dopad na provoz, ne právní závěr):

1. Přijmout, že údaje zůstávají v záloze po omezenou, uživateli sdělenou dobu a že se zálohy
   nepoužívají k jinému účelu než k obnově.
2. **Po každé obnově ze zálohy výmazy provedené po vzniku zálohy zopakovat**, jinak se smazaný
   účet vrátí. Aplikace zatím nevede záznam o provedených výmazech (ani ve formě odvozeného
   identifikátoru), takže by se výmazy musely dohledat ručně, např. z žádostí. Záznam o výmazech
   je otevřený bod pro právníka a pro další vývoj: je třeba rozhodnout, co smí obsahovat.
3. Zvážit kratší měsíční retenci (hodnoty jsou v `deploy/backup_db.sh` jako `KEEP_NEWEST` a
   `KEEP_MONTHS` a změna se musí promítnout do testů a textu *Ochrany osobních údajů*).
4. Přístup k zálohám a heslu je správa přístupu k osobním údajům (záznam o zpracování, [12](12-ucty-a-zvirata.md)
   §12.8, bod 6).

## 13.15 WAL archivace a obnova k okamžiku (PITR) 🟡 netestováno

[07](07-django-schema.md) §7.7 požaduje kromě denního dumpu **nepřetržitou archivaci WAL** (obnova
k libovolnému okamžiku, nejmenší ztráta dat po havárii). Je to nastavení **serveru PostgreSQL**
a vyžaduje restart; v tomto vývojovém prostředí ho nešlo použít, proto je zde jen dokumentace
a **nebylo vyzkoušeno**. Před nasazením ji ověřte podle kapitoly *Continuous Archiving and
Point-in-Time Recovery (PITR)* dokumentace PostgreSQL 16
(<https://www.postgresql.org/docs/16/continuous-archiving.html>) a **vyzkoušejte celý postup obnovy** na
pomocném serveru.

Soubory WAL i základní záloha obsahují tytéž osobní údaje jako dump: **musí být šifrované**
a uložené mimo server (§13.11). Doporučujeme osvědčený nástroj (pgBackRest, WAL-G), který šifrování,
kontrolu a retenci řeší, místo ručně psaného `archive_command`.

`postgresql.conf` (hodnoty jsou ukázka):

```
wal_level = replica
archive_mode = on                      # změna vyžaduje restart
archive_command = '/usr/local/bin/barf-wal-archive %p %f'   # ukázkový název, skript v repozitáři není: zašifruje a odešle %p jako %f, vrací 0 jen při úspěchu
archive_timeout = 300                  # nejvýše 5 minut bez odeslaného WAL
```

Ukázka bez šifrování pouze pro pochopení (**v ostrém provozu nepoužívat**; příkaz nesmí přepsat
existující soubor a musí selhat, když cíl nepřijal data):

```
archive_command = 'test ! -f /mnt/archiv/%f && cp %p /mnt/archiv/%f'
```

Základní záloha (jednou týdně nebo dle nástroje), např. `pg_basebackup --format=tar --gzip
--checkpoint=fast --wal-method=none --pgdata=…` a její šifrovaný přenos mimo server. Role pro
`pg_basebackup` potřebuje atribut `REPLICATION` a záznam v `pg_hba.conf`.

Obnova k okamžiku (náčrt): zastavit PostgreSQL, odložit starý datový adresář, rozbalit základní
zálohu, vytvořit prázdný soubor `recovery.signal` a nastavit:

```
restore_command = '/usr/local/bin/barf-wal-restore %f %p'   # ukázkový název: stáhne a rozšifruje %f do %p
recovery_target_time = '2026-10-21 10:00:00+02'              # okamžik před chybou
recovery_target_action = 'promote'
```

Server spustit, v protokolu ověřit dosažení cíle, zkontrolovat aplikaci a nastavení `recovery_*`
zase odstranit. Retence WAL musí odpovídat §13.9 a §13.14. Dump (§13.8) zůstává nezávislou
druhou ochranou: obnovitelný je i na jiné hlavní verzi PostgreSQL, WAL ne.

## 13.16 Otevřené body 🛠

1. **WAL archivace a PITR** zprovoznit a vyzkoušet na serveru (§13.15).
2. **Přenos záloh mimo server** a jeho hlídání (§13.11) není součástí skriptů.
3. **Záznam o výmazech** pro opakování po obnově (§13.14), rozhodnutí právníka.
4. Retence počítá soubory, ne dny (§13.9); automatická kontrola stáří nejnovější zálohy chybí
   (§13.13 ji ukládá jako ruční nebo monitorovací úkol).
5. WSGI server a reverzní proxy nejsou součástí repozitáře; přidat zamčenou verzi a ověřenou
   konfiguraci až při volbě hostingu.
6. **Hodiny serveru, které skočí dopředu**, retence nepozná (§13.9); synchronizace času (NTP) a
   hlídání stáří nejnovější zálohy to musí pokrýt.
7. **Rozdělení účtů `barf` a `barf-backup`** (§13.8) vyzkoušet na serveru a zapsat výsledek.
