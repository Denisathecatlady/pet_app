# 1. Produktová koncepce a hlavní přínos

> Legenda stavů: ✅ ověřeno proti zdroji · 🟡 ověřit v originále · 🛠 pracovní návrh · 🩺 musí posoudit
> veterinární nutriční specialista. Klíče zdrojů viz [zdroje.md](zdroje.md).

## 1.1 Problém, který aplikace řeší

**Krmná dávka sestavená podle procent (např. 80 % svaloviny, 10 % kostí, 10 % orgánů) nic neříká o tom,
zda je nutričně kompletní.** To je hlavní odborná premisa celého produktu.

| Tvrzení | Zdroj | Stav |
|---|---|---|
| Z 200 publikovaných receptů domácích dávek pro psy splnilo všechna minima AAFCO jen 9 a všechna minima NRC jen 5. | `[Stockman2013]` | ✅ (abstrakt) |
| Ze 114 receptů pro kočky žádný nesplnil všechna doporučení NRC, ani recepty od veterinářů. | `[Wilson2019]` | ✅ (abstrakt) |
| V BARF dávkách dospělých psů v Německu se opakovaně objevovala nevyváženost Ca, Cu, Zn, I, vitaminů A a D a poměru Ca:P. | `[Dillitzer2011]` | ✅ bibliografie, 🟡 přesná čísla (jen přes sekundární přehled) |
| Přínosy syrového krmení nejsou prokázané. Prokázaná jsou nutriční a mikrobiologická rizika, i pro lidi v domácnosti. | `[Freeman2013]`, `[Davies2019]` | ✅ (abstrakt) |

Z toho plyne, že potřeba není „další BARF kalkulačka". Potřebný je **analytický nástroj**, který
spočítá skutečný obsah živin v dávce a porovná ho s jasně uvedeným standardem. Zároveň musí
**otevřeně ukázat, co spočítat nelze**.

## 1.2 Vize produktu 🛠

> Odborná webová aplikace v češtině. Spočítá energetickou potřebu konkrétního psa nebo kočky a skutečný
> obsah živin v jeho dávce. Výsledek porovná se zvoleným, verzovaným nutričním standardem a u každého
> čísla ukáže, odkud pochází a jak spolehlivé je.

### Dva oddělené výpočty (požadavek zadání, bod 2)

```
┌──────────────────────────────┐        ┌──────────────────────────────────────┐
│ A. KOLIK krmit               │        │ B. ČÍM krmit (nutriční analýza)      │
│ Energetický model            │        │ Σ živin ze surovin → na den,         │
│ RER → MER/DER (odhad ± rozsah)│──kcal─▶│ na 1 000 kcal → srovnání se          │
│ podle druhu, fáze, kondice   │        │ standardem → deficity, nadbytky,     │
│                              │        │ chybějící data, spolehlivost         │
└──────────────────────────────┘        └──────────────────────────────────────┘
```

Výsledek A je **odhad** s rozsahem. Výsledek B je **výpočet z dat** s vyznačenou úplností.
Procentuální rozdělení dávky (svalovina, kosti, orgány) aplikace zobrazí, ale jen jako popisnou
statistiku. **Nikdy ho nepoužije jako kritérium kompletnosti.** 🛠

## 1.3 Cíloví uživatelé 🛠

| Persona | Potřeba | Riziko, které aplikace hlídá |
|---|---|---|
| **Informovaný chovatel** krmící BARF | Ověřit vlastní recept, zjistit deficity, dávkovat podle hmotnosti | Falešný pocit jistoty („zelená = kompletní") |
| **Veterinární lékař / nutriční poradce** | Rychlý rozbor dávky klienta, export do PDF, porovnání standardů | Použití dat pro jiný druh nebo fázi, nekompletní data |
| **Veterinární nutriční specialista** (Diplomate ECVCN / ACVIM-Nutrition) | Revize a schvalování dat a standardů, individuální plány | Neschválená data v produkci |

## 1.4 Hlavní přínos (hodnotová nabídka) 🛠

1. **Analýza místo procent.** Skutečný přísun živin na den a na 1 000 kcal se zdrojem každé hodnoty.
2. **Poctivá nejistota.** „Nelze vyhodnotit – chybí data" místo nuly. U hodnot je rozsah a hodnocení
   kvality dat.
3. **Verzovaná reprodukovatelnost.** Každý rozbor je navázaný na konkrétní verzi dat a výpočetního
   jádra, takže ho lze kdykoli zopakovat se stejným výsledkem.
4. **Bezpečnostní hranice.** Aplikace pozná situace, kde automatický výpočet nestačí (růst, březost,
   nemoc, extrémní BCS), a místo receptu doporučí odborníka.
5. **Druhová specifičnost.** Psi a kočky mají oddělené modely. Hodnoty pro psy se nikdy nepoužijí pro
   kočky.

## 1.5 Co aplikace **není** (hranice bezpečného použití) 🛠 🩺

| Aplikace NENÍ | Důvod |
|---|---|
| Náhrada veterinárního vyšetření | Nutriční hodnocení podle WSAVA zahrnuje anamnézu, vyšetření a BCS/MCS `[WSAVA2011]` ✅ |
| Generátor léčebných diet | CKD, onemocnění jater, pankreatitida, diabetes, urolitiáza: viz [09-rizika.md](09-rizika.md) |
| Důkaz bezpečnosti syrové stravy | Mikrobiologická rizika nesouvisí se složením živin `[vanBree2018]` ✅ |
| Certifikace „kompletního krmiva" | FEDIAF a AAFCO jsou standardy pro komerční krmiva. Pro domácí dávku je použití analogické, ne regulační. 🟡 |
| Nástroj pro růst, březost a laktaci v MVP | Vysoké riziko chyby (Ca u velkých plemen `[Hazewinkel1985]` ✅) a neověřené rovnice |

## 1.6 Klíčové principy návrhu 🛠

1. **Data nad algoritmem.** Všechny konstanty (násobitele energie, požadavky, složení) jsou v databázi
   se zdrojem a verzí. V kódu nejsou žádná „magická čísla".
2. **Tři stavy hodnoty:** *změřeno / dopočteno*, *analyticky nula nebo pod mezí detekce*, *neznámo*.
   Neznámá hodnota se nikdy nepočítá jako 0.
3. **Jeden standard na rozbor.** Hodnoty z různých standardů se nemíchají. Porovnání standardů se
   zobrazuje vedle sebe.
4. **Konzervativní souhrn.** Celkové „vyhovuje" se zobrazí jen tehdy, když jsou vyhodnoceny všechny
   povinné živiny daného profilu. Jinak se ukáže „vyhodnoceno X z Y živin".
5. **Optimalizace nikdy nemá poslední slovo.** Každý návrh optimalizátoru znovu projde analytickým
   modulem a stejnými kontrolami jako ručně zadaný recept.
6. **Lidská kontrola dat.** Data standardů a surovin mají workflow *koncept → revize → schváleno*.
   Do produkčních výpočtů vstupují jen schválená data.
