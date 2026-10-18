# Registr odborných zdrojů (Fáze 1)

Tento soubor je **jediné místo**, odkud ostatní dokumenty citují. Každý zdroj má klíč v hranatých
závorkách (např. `[FEDIAF2025]`), který se používá v textu. Stejná struktura se později stane
tabulkou `ScientificSource` v databázi (viz [07-django-schema.md](07-django-schema.md)).

## Jak číst sloupec „Ověření v této fázi"

Rešerše proběhla 18. 10. 2026. Síťová politika vývojového prostředí **neumožnila stáhnout plné texty**
(domény `europeanpetfood.org`, `aafco.org`, `pmc.ncbi.nlm.nih.gov` byly blokované). Ověření proto
proběhlo přes webové vyhledávání nad abstrakty, stránkami vydavatelů a sekundárními zdroji.

| Značka | Význam |
|---|---|
| **B** | Bibliografické údaje (autoři, rok, časopis, ročník, strany) ověřeny. |
| **A** | Ověřen obsah abstraktu nebo souhrnu (hlavní zjištění). |
| **P** | Ověřena konkrétní hodnota nebo tabulka přímo v primárním zdroji. |
| **S** | Hodnota ověřena jen přes sekundární zdroj, který primární zdroj cituje. |
| **–** | Neověřeno. Uvedeno z odborné znalosti. Před použitím je nutné to ověřit. |

> **Pravidlo pro vývoj:** Do databáze nutričních standardů ani surovin se nesmí dostat žádná hodnota
> bez stavu **P**. Hodnoty se stavem S nebo – slouží jen jako orientace pro kontrolu přepisu.

## Úrovně odbornosti zdroje

| Úroveň | Typ |
|---|---|
| **L1** | Konsenzuální doporučení vědecké nebo odborné instituce (NRC, FEDIAF, AAFCO, WSAVA). |
| **L2** | Systematický přehled nebo metaanalýza v recenzovaném časopise. |
| **L3** | Původní recenzovaná studie (experimentální, observační). |
| **L4** | Kazuistika nebo série případů. |
| **L5** | Databáze složení potravin (kvalita se liší podle záznamu, hodnotí se zvlášť). |
| **L6** | Sekundární nebo populární zdroj. Smí sloužit jen k dohledání primárního zdroje. |

---

## 1. Nutriční standardy a doporučení

| Klíč | Zdroj | Rok | DOI / URL | Typ, úroveň | Druh, fáze | Ověření |
|---|---|---|---|---|---|---|
| `[FEDIAF2025]` | FEDIAF – The European Pet Food Industry Federation. *Nutritional Guidelines for Complete and Complementary Pet Food for Cats and Dogs.* Brusel. | září 2025 | https://europeanpetfood.org/wp-content/uploads/2025/09/FEDIAF-Nutritional-Guidelines_2025-ONLINE.pdf | Průmyslová doporučení, recenzovaná nezávislou vědeckou radou (Scientific Advisory Board). L1. **Právně nezávazná.** | Psi a kočky. Dospělí, růst, reprodukce. | B; struktura tabulek S/P (viz níže) |
| `[FEDIAF2024]` | Totéž, verze 2024 (předchozí vydání, pro historii verzí). | červenec 2024 | https://europeanpetfood.org/wp-content/uploads/2024/09/FEDIAF-Nutritional-Guidelines_2024.pdf (zrcadlo: ukpetfood.org) | L1 | Psi a kočky | B |
| `[NRC2006]` | National Research Council. *Nutrient Requirements of Dogs and Cats.* Washington, DC: The National Academies Press. | 2006 | https://nap.nationalacademies.org/catalog/10668 (DOI 10.17226/10668, DOI zatím neověřen) | Vědecká monografie (Ad Hoc Committee on Dog and Cat Nutrition). L1 | Psi a kočky. Všechny fáze. | B; vybrané rovnice S |
| `[AAFCO2014]` | AAFCO. *Dog and Cat Food Nutrient Profiles* (revize 2014, v Official Publication od roku 2016). Pet Food Report 2014, Appendix A. | 2014 | https://www.aafco.org/wp-content/uploads/2023/01/Pet_Food_Report_Annual_2014-Appendix_A-Revised_AAFCO_Nutrient_Profiles-Final_092214.pdf | Regulační profily (USA, přes legislativu států). L1 | Psi a kočky. Profily „Growth & Reproduction" a „Adult Maintenance". | B; limit Ca pro velká plemena S |
| `[WSAVA2011]` | Freeman L, Becvarova I, Cave N, et al. WSAVA Nutritional Assessment Guidelines. *J Small Anim Pract.* 2011;52(7):385–396. | 2011 | https://wsava.org/global-guidelines/global-nutrition-guidelines/ | Doporučený postup hodnocení výživy. L1 | Psi a kočky | B, A |

**Co je ověřeno z `[FEDIAF2025]` (stav S/P, přes vyhledávání v textu PDF):**
- Edice 2025 vyšla v září 2025. Novinka FEDIAF z 8. 9. 2025 uvádí upravené nutriční tabulky a zpřesněné přílohy.
- Tabulky pro psy vycházejí z denního příjmu energie **95 nebo 110 kcal ME/kg BW^0,75**.
  Pro kočky z **75 nebo 100 kcal ME/kg BW^0,67**.
- Hodnoty jsou *minimální doporučené úrovně pro komerční krmivo* (obsahují bezpečnostní rezervu na
  biologickou dostupnost). Nejde o minimální fyziologické požadavky. Jsou odvozené z doporučení NRC
  (2006) pro středně velkého štíhlého psa o hmotnosti 15 kg.
- Tabulka III-3b (psi, jednotka na 1 000 kcal ME) je na straně 16 z 98. Pro dospělé psy uvádí
  maximální poměr Ca:P **2:1 (N = nutriční maximum)**.
- FEDIAF ponechává exponent 0,75 podle NRC 2006. Exponent 0,67 zmiňuje jako alternativu blíže
  vztaženou k povrchu těla.
- **Neověřeno:** úplné číselné tabulky (mikroživiny, vitaminy, maxima). PDF nebylo z prostředí dostupné.
  Viz postup importu v [03-nutricni-pozadavky.md](03-nutricni-pozadavky.md).

## 2. Energetická potřeba a hodnocení kondice

| Klíč | Zdroj | Rok | DOI / URL | Typ, úroveň | Ověření |
|---|---|---|---|---|---|
| `[Bermingham2014]` | Bermingham EN, Thomas DG, Cave NJ, et al. Energy requirements of adult dogs: a meta-analysis. *PLoS One.* 2014;9(10):e109681. | 2014 | https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4196927/ | Metaanalýza. L2 | B, A |
| `[Calvez2019]` | Calvez J, Weber M, Ecochard C, Kleim L, Flanagan J, Biourge V, German AJ. Metabolisable energy content in canine and feline foods is best predicted by the NRC2006 equation. *PLoS One.* 2019;14(9):e0223099. (Korekce 19. 3. 2025: PMC11922269.) | 2019 | https://doi.org/10.1371/journal.pone.0223099 | Původní studie. L3 | B, A. 335 krmných pokusů (207 psí, 128 kočičí), **jen komerční suchá a vlhká krmiva, ne syrové dávky**. Doporučení: NRC 2006 (TDF) s měřenou GE |
| `[Laflamme1997d]` | Laflamme D. Development and validation of a body condition score system for dogs. *Canine Pract.* 1997;22(4):10–15. | 1997 | – | Validační studie. L3 | B |
| `[Laflamme1997c]` | Laflamme D. Development and validation of a body condition score system for cats: a clinical tool. *Feline Pract.* 1997;25(5–6):13–18. | 1997 | – | Validační studie. L3 | B |
| `[Wichert2009]` | Wichert B, et al. Energy and protein needs of cats for maintenance, gestation and lactation. *J Feline Med Surg.* 2009. PubMed 19564126. | 2009 | https://pubmed.ncbi.nlm.nih.gov/19564126/ | Původní studie. L3 | B (částečně), A |
| `[YorkshireGrowth2017]` | Energy requirements for growth in the Yorkshire terrier. *J Nutr Sci.* 2017. PMC5468749. | 2017 | https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5468749/ | Původní studie. L3 | A (autory doplnit) |
| `[NorfolkGrowth2021]` | Energy Requirements for Growth in the Norfolk Terrier. PMC8152034. | 2021 | https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8152034/ | Původní studie. L3 | A (autory a časopis doplnit) |
| `[PuppyIntake2019]` | Metabolisable energy intake and growth of privately owned growing dogs in comparison with official recommendations on the growth curve and energy supply. (493 štěňat) | 2019? | https://www.researchgate.net/publication/335872260 | Observační studie. L3 | A (bibliografii doplnit) |
| `[MDPI2025]` | Assessment of the Nutritional Impact of the 10% Snack Recommendation in Pet Diets. *Vet Sci.* 2025;12(3):282. | 2025 | https://www.mdpi.com/2306-7381/12/3/282 | Původní studie. L3 (pro energetické kategorie jde o sekundární citaci FEDIAF) | Kategorie aktivity psů podle FEDIAF (95 / 110 / 125 / 150–175, extrémní 860–1 240 kcal/kg^0,75) S. Autory doplnit |
| `[Wikivet]` | WikiVet: Energy Requirements, Cholecalciferol a další hesla. | – | https://en.wikivet.net/ | Sekundární. L6 | Rovnice pro koťata S. Tvrzení o nižší RER u obézních zvířat S |
| `[PNA-RER]` | Pet Nutrition Alliance. *Calculating Calories Based on Pet Needs* (leták). | 2023 | https://petnutritionalliance.org/wp-content/uploads/2023/03/MER.RER_.PNA_.pdf | Sekundární. L6 | Rovnice RER S |

## 3. Domácí a syrové (BARF) dávky: nutriční přiměřenost

| Klíč | Zdroj | DOI / URL | Typ, úroveň | Hlavní zjištění (ověřená úroveň) |
|---|---|---|---|---|
| `[Dillitzer2011]` | Dillitzer N, Becker N, Kienzle E. Intake of minerals, trace elements and vitamins in bone and raw food rations in adult dogs. *Br J Nutr.* 2011;106(Suppl 1):S53–S56. | https://www.cambridge.org/core/journals/british-journal-of-nutrition/article/intake-of-minerals-trace-elements-and-vitamins-in-bone-and-raw-food-rations-in-adult-dogs/7520574DA173F4DB29330A6F858DE0E0 | L3 | B. Sekundární přehled (Tierärztl Prax 2016) shrnuje, že bývají nevyvážené Ca, Cu, Zn, I, vitaminy A a D a poměr Ca:P. **Přesná procenta neověřena.** |
| `[Stockman2013]` | Stockman J, Fascetti AJ, Kass PH, Larsen JA. Evaluation of recipes of home-prepared maintenance diets for dogs. *JAVMA.* 2013;242(11):1500–1505. | https://doi.org/10.2460/javma.242.11.1500 | L3 | B, A. Hodnoceno 200 receptů z 34 zdrojů. Jen 9 splnilo všechna minima AAFCO pro dospělé psy a jen 5 minima NRC. |
| `[Wilson2019]` | Wilson SA, Villaverde C, Fascetti AJ, Larsen JA. Evaluation of the nutritional adequacy of recipes for home-prepared maintenance diets for cats. *JAVMA.* 2019;254(10):1172–1179. | https://doi.org/10.2460/javma.254.10.1172 | L3 | B, A. Hodnoceno 114 receptů. Žádný, ani recepty od veterinářů, nedodal všechny esenciální živiny na úrovni doporučení NRC. Některé obsahovaly pro kočky nevhodné suroviny (česnek, cibule, pórek). |
| `[SciRep2025]` | Assessment of mineral adequacy in preprepared raw dog foods labeled as complete. *Sci Rep.* 2025 (s41598-025-27388-w, PMC12690097). | https://www.nature.com/articles/s41598-025-27388-w | L3 | Existence ověřena (autory doplnit). Studie srovnává syrová krmiva s minimy FEDIAF a uvádí Ca 1,25 g a P 1,00 g / 1 000 kcal (dospělý pes). Jednotky mikroprvků v citované tabulce působí nekonzistentně, proto je nepřebírám. |
| `[Hamper2017]` | Hamper BA, Bartges JW, Kirk CA. Evaluation of two raw diets vs a commercial cooked diet on feline growth. *J Feline Med Surg.* 2017;19(4):424–434. | – | L3 | B, A. 24 koťat po 10 týdnů. Růst byl srovnatelný. Na syrových dietách nižší albumin a vyšší globuliny. Nález *Salmonella* Heidelberg a toxinu *C. difficile* v jedné syrové skupině. Autoři upozorňují, že krátký růstový test nevylučuje dlouhodobé deficity. |

## 4. Rizika syrového krmení

| Klíč | Zdroj | DOI / URL | Typ, úroveň | Hlavní zjištění |
|---|---|---|---|---|
| `[Freeman2013]` | Freeman LM, Chandler ML, Hamper BA, Weeth LP. Current knowledge about the risks and benefits of raw meat–based diets for dogs and cats. *JAVMA.* 2013;243(11):1549–1558. | https://doi.org/10.2460/javma.243.11.1549 | L2 (přehled) | B, A. Přínosy nejsou prokázané. Rizika jsou nutriční nevyváženost a infekční agens, a to i pro lidi v domácnosti. |
| `[Davies2019]` | Davies RH, Lawes JR, Wales AD. Raw diets for dogs and cats: a review, with particular reference to microbiological hazards. *J Small Anim Pract.* 2019;60(6):329–339. | https://doi.org/10.1111/jsap.13000 | L2 (přehled) | B, A. Doložené jsou změny mikrobiomu a subjektivně lepší kvalita stolice. U většiny tvrzených přínosů chybí důkazy. Hlavním tématem jsou mikrobiologická rizika. |
| `[vanBree2018]` | van Bree FPJ, Bokken GCAM, Mineur R, et al. Zoonotic bacteria and parasites found in raw meat-based diets for cats and dogs. *Vet Rec.* 2018;182(2):50. | https://doi.org/10.1136/vr.104535 (DOI neověřen) | L3 | B, A. Testováno 35 mražených komerčních syrových krmiv (8 značek, Nizozemsko). *E. coli* O157:H7 ve 23 %, ESBL *E. coli* v 80 %, *Listeria monocytogenes* v 54 %, *Salmonella* ve 20 %, *Toxoplasma gondii* v 6 %. |
| `[Broome2015]` | Broome MR, Peterson ME, Kemppainen RJ, Parker VJ, Richter KP. Exogenous thyrotoxicosis in dogs attributable to consumption of all-meat commercial dog food or treats. *JAVMA.* 2015;246(1):105–111. | https://pubmed.ncbi.nlm.nih.gov/25517332/ | L4 (série případů) | B, A. 14 psů. Tyreotoxikóza byla po vysazení krmiva s pravděpodobnou kontaminací tkání štítné žlázy reverzibilní. |
| `[Kohler2012]` | Köhler B, Stengel C, Neiger R. Dietary hyperthyroidism in dogs. *J Small Anim Pract.* 2012;53(3):182–184. | – | L4 | B (sekundárně), A. Psi krmení syrovou stravou nebo jícny (obsahují tkáň štítné žlázy). |
| `[Gianella2009]` | Gianella P, Pfammatter NS, Burgener IA. Oesophageal and gastric endoscopic foreign body removal: complications and follow-up of 102 dogs. *J Small Anim Pract.* 2009;50(12):649–654. | https://boris.unibe.ch/38321 | L3 (retrospektivní) | B, A. Komplikace u 13 ze 102 psů (12,7 %). Rizikové faktory byly **kostní cizí těleso**, hmotnost < 10 kg a doba > 3 dny. |
| `[Polizopoulou2005]` | Polizopoulou ZS, Kazakos G, Patsikas MN, Roubies N. Hypervitaminosis A in the cat: a case report and review of the literature. *J Feline Med Surg.* 2005;7(6):363–368. | https://pubmed.ncbi.nlm.nih.gov/15994105/ | L4 | B, A. Kočka krmená domácí dietou ze syrových vepřových jater. Paralýza končetiny, sérový vitamin A 3× nad horní hranicí normy. |
| `[Markovich2014]` | Markovich JE, et al. Thiamine concentrations in canned foods for cats. *JAVMA.* 2014;244(2):175–179. | https://doi.org/10.2460/javma.244.2.175 | L3 | B (spoluautory doplnit), A. Z 90 konzerv mělo 12 thiamin pod minimem AAFCO. Ukazuje ztráty thiaminu při zpracování. |
| `[Niza2003]` | Niza MMRE, Vilela CL, Ferreira LMA. Feline pansteatitis revisited: hazards of unbalanced home-made diets. *J Feline Med Surg.* 2003. | – | L4 | A (bibliografii doplnit). Pansteatitida u koček krmených převážně tučnými rybami. |

## 5. Druhově specifické živiny a růst

| Klíč | Zdroj | DOI / URL | Typ, úroveň | Hlavní zjištění |
|---|---|---|---|---|
| `[Pion1987]` | Pion PD, Kittleson MD, Rogers QR, Morris JG. Myocardial failure in cats associated with low plasma taurine: a reversible cardiomyopathy. *Science.* 1987;237(4816):764–768. | https://pubmed.ncbi.nlm.nih.gov/3616607/ | L3 | B, A. Nízký plazmatický taurin byl spojen s dilatační kardiomyopatií. Suplementace funkci normalizovala. |
| `[How1994]` | How KL, Hazewinkel HAW, Mol JA. Dietary vitamin D dependence of cat and dog due to inadequate cutaneous synthesis of vitamin D. *Gen Comp Endocrinol.* 1994;96:12–18. | – | L3 | B, A. Kůže psů a koček obsahuje málo 7-dehydrocholesterolu, který se navíc nedostatečně přeměňuje. Psi i kočky jsou proto závislí na vitaminu D z potravy. |
| `[Morris2002]` | Morris JG. Idiosyncratic nutrient requirements of cats appear to be diet-induced evolutionary adaptations. *Nutr Res Rev.* 2002;15:153–168. | – | L2 (přehled) | A (název a ročník ověřit). Kočky mají obligátní potřebu vitaminu D a niacinu z potravy. |
| `[Hazewinkel1985]` | Hazewinkel HAW, Goedegebuure SA, Poulos PW, Wolvekamp WTC. Influences of chronic calcium excess on the skeletal development of growing Great Danes. *J Am Anim Hosp Assoc.* 1985;21:377–391. | – | L3 | B, A. Nadbytek vápníku u rostoucích dog vedl k poruchám vývoje skeletu (osteochondróza). Studie je podkladem pro maxima Ca v krmivech pro štěňata. |

## 6. Databáze složení potravin

| Klíč | Zdroj | URL | Úroveň | Ověřeno |
|---|---|---|---|---|
| `[USDA-FDC]` | U.S. Department of Agriculture, Agricultural Research Service. *FoodData Central.* | https://fdc.nal.usda.gov/ | L5 | Pět datových typů: Foundation Foods, SR Legacy, Branded Foods, FNDDS, Experimental Foods. **SR Legacy** je uzavřený (poslední vydání duben 2018). **Foundation Foods** se aktualizuje v dubnu a říjnu a má rozsáhlá metadata o vzorkování a analýze. Licence (předpoklad CC0 / public domain) **neověřena**. |
| `[CIQUAL]` | ANSES. *Table de composition nutritionnelle des aliments Ciqual.* | https://www.anses.fr/en/node/79557 | L5 | Bezplatný zdroj, verze 2020 obsahuje 3 185 potravin. Podmínka: uvádět zdroj. Typ licence **neověřen**. |
| `[NutriDB-CZ]` | Centrum pro databázi složení potravin. *Databáze složení potravin ČR*, verze 10.25. Praha: ÚZEI, 2025. | http://www.nutridatabaze.cz/ | L5 | Existence a vydavatel ověřeny. Podmínky užití **neověřeny**. |

## 7. Zdroje, které je nutné doplnit (mezery v rešerši)

Tyto oblasti návrh potřebuje, ale v této fázi pro ně nebyl ověřen konkrétní primární zdroj:

1. **Rovnice energetické potřeby pro březost a laktaci** (konstanty NRC 2006, kap. 15). V MVP se nepoužijí.
2. **Rovnice NRC 2006 pro ME u koček** (koeficienty stravitelnosti a korekce na bílkoviny).
3. **NRC 2006 pro obézní kočky** (rovnice s exponentem 0,4, uváděná v literatuře): neověřeno.
4. **Složení masa s kostí** (krky, křídla, žebra): Ca a P z analytických dat. USDA pro tyto položky
   většinou neuvádí kost jako součást jedlého podílu. Jde o **kritickou datovou mezeru** pro BARF.
5. **Jód v mase a vnitřnostech**: běžné databáze ho většinou neobsahují.
6. **Obsah taurinu v syrových surovinách** a vliv mletí, mražení a tepelné úpravy.
7. **Zákonná maxima EU** pro doplňkové látky (vitamin D, Zn, Cu, I, Se) v nařízeních o doplňkových
   látkách. Týkají se komerčních krmiv, pro domácí dávku slouží jen jako orientace.
8. **Hodnocení svalové kondice (MCS)** podle WSAVA: přesná citace nástroje.
9. **Biologická dostupnost Ca z kostí vs. uhličitanu vápenatého** a interakce Ca–Zn, Zn–Cu.
