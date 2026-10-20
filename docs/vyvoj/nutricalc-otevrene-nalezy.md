# nutricalc – otevřené nálezy z nezávislé revize (říjen 2026)

Revize jádra `nutricalc` (commit `75cc8d1`) proběhla ze čtyř pohledů: výpočty, testy, odborná bezpečnost,
architektura a determinismus. Opravy a závěrečné ověření nedoběhly (limit relace) a práce na kalkulačce
je na přání odložena. Nálezy proto zůstávají **otevřené** a před použitím jádra je nutné je projít.

Rozpracované, neověřené a neúplné opravy jsou uložené jako patch
[`nutricalc-neuplne-opravy.patch`](nutricalc-neuplne-opravy.patch) (po jeho aplikaci testy neprocházejí).
Kód v repozitáři odpovídá stavu, kdy prochází všech 1276 testů.

Počet nálezů: 43 (high 7, medium 14, low 22). Texty nálezů jsou v angličtině, jak je vrátili revizoři.

## 1. [high] PARTIAL ration ME (missing NFE or fibre counted as 0) gives COMPLETE per-1000 values and can produce ALL_EVALUATED_MET

- Soubor: `nutricalc/analysis.py`:397
- Popis: When NFE or the method's fibre is missing, ration_me counts it as 0 and returns completeness PARTIAL (docs/06 6.3). analyze_recipe then uses this approximate ME as the exact denominator for every per-1000-kcal interval. per_1000kcal_interval copies the nutrient's own completeness (COMPLETE), so evaluate_nutrient compares exact-looking intervals against the minima. Missing NFE lowers ME, which inflates per-1000 nutrient densities, so minima look met. Missing fibre (CF method) usually raises ME, so maxima look met. The only trace is a NUTRITION_WARNING flag ME_PARTIAL. summarize ignores ME completeness, so the ration can get the green ALL_EVALUATED_MET summary. That breaks the hard rule that a missing value is never treated as 0 for evaluation, and the conservative summary (docs/06 6.6.4).
- Doklad: Reproduced with synthetic data. Profile SYN_X: PROTEIN 20, FAT 10, CRUDE_FIBRE 0 (ZERO_BY_DEFINITION), NFE absent, no WATER/ASH. Recipe 300 g. Profiles: PROTEIN MIN_RECOMMENDED 100.0 (high column) and 110.0 (low column), mandatory {PROTEIN}. Result: ME 506.688 PARTIAL, PROTEIN per_1000 COMPLETE, status ADEQUATE, coverage 118.416 %, summary ALL_EVALUATED_MET. The same ingredient with NFE = 20 g/100 g gives ME 731.040 COMPLETE, PROTEIN BELOW_MIN, coverage 82.07 %, summary DEFICITS_OR_EXCESSES. test_partial_ration_energy_is_flagged asserts P ADEQUATE in this situation and does not check the summary.
- Návrh opravy: Carry ME completeness into evaluation. For example, when me.completeness != COMPLETE, mark per-1000 intervals as non-COMPLETE (PARTIAL lower bound only, so the existing PARTIAL rules apply). Or keep the statuses but make summarize return INCOMPLETE (never ALL_EVALUATED_MET) and report evaluated_count accordingly. Add a test that PARTIAL ME can never yield ALL_EVALUATED_MET.

## 2. [high] Approximate (PARTIAL) ration ME, with missing NFE/fibre counted as 0, feeds evaluation and can give ALL_EVALUATED_MET

- Soubor: `nutricalc/analysis.py`:397
- Popis: When NFE (or the method's fibre) is MISSING, me.ration_me counts it as 0 and returns completeness PARTIAL. analyze_recipe still uses that ME as the per-1000-kcal denominator (usable_kcal only excludes UNKNOWN or <= 0). Nutrient intervals stay COMPLETE, statuses are computed as if exact, and only a NUTRITION_WARNING flag ME_PARTIAL is added. With NFE missing, ME is a lower bound, so every density per 1000 kcal is inflated and minima look met. With CF/TDF missing, the bias can go either way, so maxima can also be missed. Missing data is therefore treated as zero for evaluation. Nothing caps the summary below ALL_EVALUATED_MET. tests/nutricalc/test_analysis.py:359 (test_partial_ration_energy_is_flagged) asserts ADEQUATE in exactly this situation.
- Doklad: Reproduced in scratchpad repro2.py. Synthetic SYN_C (PROTEIN 20, FAT 10, CRUDE_FIBRE 0 (ZERO_BY_DEFINITION), ZN 0.020 g/100 g), 600 g, synthetic ZN minimum 0.100/0.117 g/1000 kcal. With NFE MISSING: ME 1013.376 PARTIAL, ZN 0.1184 g/1000 kcal -> ADEQUATE, summary ALL_EVALUATED_MET, flags ['ME_PARTIAL']. Same item with true NFE 30 g/100 g: ME 1686.432 COMPLETE, ZN 0.0712 -> BELOW_MIN, summary DEFICITS_OR_EXCESSES.
- Návrh opravy: When me.completeness is PARTIAL, do not let the evaluation look exact. Simplest: treat the summary as INCOMPLETE, or never ALL_EVALUATED_MET, and allow only lower-bound statuses that stay valid under the bias. ABOVE_MAX/ABOVE_SUL are still safe to report when ME is a known lower bound (NFE-only case). Alternatively give per-1000-kcal intervals at least PARTIAL completeness when ME is PARTIAL. Update test_partial_ration_energy_is_flagged accordingly and add a test that a PARTIAL ME can never yield ALL_EVALUATED_MET.

## 3. [high] PARTIAL ration ME (missing NFE counted as 0) feeds definitive nutrient statuses and a green summary

- Soubor: `nutricalc/analysis.py`:397
- Popis: analyze_recipe uses me.kcal as the per-1000-kcal denominator whenever it is > 0, including when MeResult.completeness is PARTIAL because NFE or fibre was missing and treated as 0. Nutrient intervals keep the completeness of the nutrient total (COMPLETE), so evaluate_nutrient returns definitive ADEQUATE / BELOW_MIN statuses and summarize can return ALL_EVALUATED_MET. The only signal is a NUTRITION_WARNING flag ME_PARTIAL, which nothing downstream reads. That is a missing value treated as zero inside the evaluation, against the rule that unknown is never zero. With NFE missing, the true ME is at least the computed ME, so the per-1000 densities are upper bounds. Minimum checks therefore become non-conservative and can hide BELOW_MIN. The test test_partial_ration_energy_is_flagged locks this behaviour in by asserting P == ADEQUATE.
- Doklad: SYN_A = PROTEIN 20, FAT 10, CRUDE_FIBRE ZERO_BY_DEFINITION, P 0.200, CA 0.3, with no NFE and no ASH; SYN_B as in docs/06 6.10. Synthetic TESTSTD profiles with only P MIN_RECOMMENDED 1.234, mandatory {P}. analyze_recipe gives: ME 506.6880 PARTIAL; P ADEQUATE (per_1000 COMPLETE); summary ALL_EVALUATED_MET with the sentence 'Všechny vyhodnocené požadavky standardu TESTSTD 1 … jsou splněny'; flags ['ME_PARTIAL'].
- Návrh opravy: Carry the ME completeness into the per-1000 intervals. If me.completeness != COMPLETE, downgrade each NutrientInterval to at most PARTIAL (or UNKNOWN), or treat the denominator as an interval with an unknown bound, so minima cannot be ADEQUATE / MIN_MET from an under-estimated ME. At the least, make summarize return INCOMPLETE (never ALL_EVALUATED_MET) when ME is PARTIAL. Update test_partial_ration_energy_is_flagged to match.

## 4. [high] A minimum scaled above a maximum crashes analyze_recipe with ValidationError

- Soubor: `nutricalc/evaluation.py`:258
- Popis: select_requirements multiplies minima by low.reference_k / k_actual and leaves maxima as they are. It never checks whether the scaled minimum is still below the maxima. evaluate_nutrient -> _applicable then re-runs check_requirement_set on these already-scaled requirements. That function treats 'minimum < every maximum (NUTRITIONAL_MAX, SUL, LEGAL_MAX_EU)' as a hard error. So a low energy coefficient makes analyze_recipe raise. This is a data situation, and analyze_recipe should never raise for one (docs/06 6.9, task: 'Never raises for data situations'). It even happens for LEGAL_MAX_EU, which the evaluation itself treats only as informational (ABOVE_LEGAL_MAX_INFO). A scaled minimum above a maximum is clinically important: no ration can meet both. The result should say so instead of crashing.
- Doklad: Reproduced. (1) analysis_input(energy_factor=dog_factor('60')) with the default TESTSTD fixtures raises ValidationError: 'Živina P: minimum MIN_RECOMMENDED 7.921416666666666666666666665 g musí být menší než NUTRITIONAL_MAX 7.777 g.' (2) k = 80, the docs/11 example value (factor 1.1875), plus a synthetic PROTEIN LEGAL_MAX_EU 73.97 in both columns (low-column min 64.321) raises 'minimum MIN_RECOMMENDED 76.3811875 g musí být menší než LEGAL_MAX_EU 73.97 g.' Path: analyze_recipe -> select_requirements -> scale_minima (requirements.py:566) -> evaluate_nutrient -> _applicable -> check_requirement_set. The tests use k = 80 only with the default fixtures, whose max/min ratio is large, so this path is never hit.
- Návrh opravy: Validate the requirement set before scaling (StandardProfile already does). In _applicable, check only structure for scaled requirements: same nutrient, no duplicate types, ratio vs non-ratio. Drop the min<max value check there. In select_requirements or evaluate_nutrient, detect a scaled minimum >= a NUTRITIONAL_MAX or SUL and emit a flag or gate reason (e.g. REQUIREMENT_SCALED_MIN_ABOVE_MAX at EXPERT_REQUIRED). For LEGAL_MAX_EU at most an INFO flag. Add a parametrized test with k low enough to push a scaled minimum past each maximum type.

## 5. [high] Scaled minimum above a maximum makes analyze_recipe raise ValidationError for a legitimate low-energy animal

- Soubor: `nutricalc/evaluation.py`:258
- Popis: select_requirements multiplies minima by low.reference_k / k_actual through scale_minima (requirements.py:510). The result is never checked against the maxima. evaluate_nutrient then calls _applicable -> check_requirement_set, which enforces min < every maximum (NUTRITIONAL_MAX, SUL and even the informational LEGAL_MAX_EU). Any animal whose k is low enough that the scaled minimum crosses a maximum therefore crashes the whole analysis. This breaks the contract that analyze_recipe never raises for data situations (docs/06 §6.9). The error text also blames the standard data ('minimum ... musí být menší než LEGAL_MAX_EU'), which may push a curator to 'fix' correct data. In domain terms, a scaled minimum above a nutritional maximum or SUL means no ration can satisfy the column, and the specialist must review. Crossing only LEGAL_MAX_EU is irrelevant to evaluation.
- Doklad: Reproduced in scratchpad repro6.py (b): default synthetic TESTSTD fixture, analysis_input(energy_factor=dog_factor('60')) -> ValidationError 'Živina P: minimum MIN_RECOMMENDED 7.9214... g musí být menší než NUTRITIONAL_MAX 7.777 g.' Also repro1.py: synthetic P min 4.5 (low column) with LEGAL_MAX_EU 5.0 and k = 70 -> ValidationError mentioning LEGAL_MAX_EU. No existing test covers k below about 61 with the default fixture.
- Návrh opravy: Validate the profile set (check_requirement_set) only on the unscaled profile, and have evaluate_nutrient skip that check for already-scaled requirements, or split it out. In select_requirements, detect scaled minima >= NUTRITIONAL_MAX or SUL and emit an EXPERT_REQUIRED flag such as SCALED_MINIMUM_ABOVE_MAXIMUM naming the nutrients. Feed that flag into the gate, or at least prevent ALL_EVALUATED_MET. Ignore LEGAL_MAX_EU for this check. Add a test with k well below low.reference_k.

## 6. [high] Scaled minima that cross a maximum make analyze_recipe raise ValidationError for valid data

- Soubor: `nutricalc/evaluation.py`:258
- Popis: select_requirements multiplies minimum-type requirements by low.reference_k / k_actual and never multiplies maxima. evaluate_nutrient and no_data_evaluation then call _applicable, which re-runs check_requirement_set on the scaled set. That function enforces the profile-level rule that the minimum must be below every maximum. When the scaling factor exceeds max/min for any nutrient, analyze_recipe raises ValidationError instead of returning a result. This breaks the contract 'never raises for data situations, only for invalid input (docs/06 6.9)'. It also hits exactly the case where scaling matters: animals with low energy intake, and cats with a low reference_k.
- Doklad: Golden synthetic input analysis_input() with energy_factor=dog_factor(k): k=80 and k=62 are fine. k=60 gives ValidationError: 'Živina P: minimum MIN_RECOMMENDED 7.921416666666666666666666665 g musí být menší než NUTRITIONAL_MAX 7.777 g.' k=55 raises the same way. The profile pair itself is valid (low column P min 5.003 < max 7.777, both synthetic).
- Návrh opravy: Validate the min<max rule only when building a StandardProfile. In _applicable, check only nutrient code, ratio/non-ratio and unit. Detect a scaled minimum that is >= a maximum explicitly and report it in the result, for example as NOT_EVALUABLE plus an EXPERT_REQUIRED flag such as REQUIREMENT_SCALED_MIN_ABOVE_MAX that feeds the gate. Add an analyze_recipe test with a low k that pushes the factor above max/min.

## 7. [high] Summary is green (ALL_EVALUATED_MET) when the profile's Ca:P requirement cannot be evaluated because Ca data is missing for 86 % of the mass

- Soubor: `nutricalc/evaluation.py`:791
- Popis: summarize treats MIN_MET_PARTIAL as 'evaluated' unless the nutrient has its own maximum type (with_maximum only looks at NUTRITIONAL_MAX, SUL and LEGAL_MAX_EU of the same nutrient code). A RATIO_MAX on CA_P is effectively an upper limit on Ca, but it is not considered. CA_P counts towards INCOMPLETE only if the data lists it as mandatory. For the docs/06 §6.10 reference example ('referenční test chybějících dat', where docs stress 'Ca:P nelze vyhodnotit'), the profile has RATIO_MIN/RATIO_MAX for CA_P, Ca is PARTIAL and Ca:P is NOT_EVALUABLE, yet the result is ALL_EVALUATED_MET with the green sentence. This contradicts docs/09 R1 ('žádná zelená při chybějících datech'), and tests/nutricalc/test_analysis.py:181 (test_golden_example_summary_and_metadata) locks it in.
- Doklad: Reproduced in scratchpad repro5.py with the default synthetic analysis_input(): CA PARTIAL MIN_MET_PARTIAL, P ADEQUATE, PROTEIN ADEQUATE, CA_P NOT_EVALUABLE -> summary ALL_EVALUATED_MET 3/3, message 'Všechny vyhodnocené požadavky standardu TESTSTD 1 ... jsou splněny.'
- Návrh opravy: Treat a nutrient as having an unverifiable maximum when it is a component of a ratio with RATIO_MAX (or RATIO_MIN for the denominator) and that ratio is NOT_EVALUABLE. Also treat any ratio requirement in the used profile as mandatory when both components are mandatory. More generally, do not allow ALL_EVALUATED_MET when any requirement present in the used profile is NOT_EVALUABLE because data is missing (use BORDERLINE or INCOMPLETE). Update the golden summary test to expect INCOMPLETE and assert not_evaluated contains CA_P.

## 8. [medium] Analysis fixtures always pair profiles with identical nutrient codes and mandatory sets

- Soubor: `/home/user/pet_app/tests/nutricalc/synthetic.py`:236
- Popis: std_pair builds high/low TESTSTD columns that differ only in minimum values; with_requirements in test_analysis.py:79 passes the same mandatory set to both. So analysis logic that unions or orders codes across the two columns is never exercised: _nutrient_units iterating both profiles, sorting results by code, which mandatory set summarize uses, and check_profile_pair's unit check for a nutrient present in only one column.
- Doklad: Mutations that survived (887 passed): analysis.py:248 iterating only `(inp.high_profile,)`, which would silently drop a nutrient required only by the low column even when that column is selected for k < 110; analysis.py:399 `for code in units` instead of `sorted(units)`; analysis.py:499 using `mandatory_all` instead of `selected.profile_used.mandatory_nutrients`; the BLOCKED summary using only high_profile.mandatory_nutrients. The branch tracer shows the `known is not None` False side at requirements.py:483 is never taken.
- Návrh opravy: Add analysis tests with asymmetric synthetic profiles. Put a nutrient (code sorting first, e.g. 'AAA_SYN') only in the low column: with energy_factor k=80 it must be evaluated with a scaled minimum; with k=120 it must still appear as a result (NO_REFERENCE under the high column). Assert result order is by code. Give the columns different mandatory sets and assert which one drives summary.not_evaluated.

## 9. [medium] Determinism tests run in one process; no pinned golden hash or PYTHONHASHSEED check

- Soubor: `/home/user/pet_app/tests/nutricalc/test_analysis.py`:632
- Popis: All determinism tests (test_same_input_gives_identical_result_and_hashes, test_permuted_items_give_same_hashes, the hypothesis order tests) compare two results from the same interpreter. Any output order derived from set/frozenset iteration would therefore look stable. docs/11 §11.2 requires the same result_hash on another machine, and §11.1 calls for golden JSON fixtures with bit-exact results. Neither is implemented: no expected input_hash, result_hash or canonical JSON is pinned anywhere.
- Doklad: I injected a hash-seed-dependent order into summarize (`mandatory = sorted({...})` -> `list({...})`) in a scratchpad copy. tests/nutricalc gave `887 passed` under PYTHONHASHSEED 0, 1 and 7. For a synthetic input with 4 not-evaluated mandatory nutrients, result_hash differed for each of 5 seeds. The original code gives one result_hash (1c9d99bd…) for all 5 seeds, so the code is fine today but unguarded.
- Návrh opravy: Commit golden fixtures (canonical JSON plus input_hash/result_hash) for the §6.10 example and a richer synthetic scenario (several not-evaluated mandatory nutrients, multiple safety flags, rules, health conditions), and assert bit-exact equality. Add a test that runs a small analysis in subprocesses with 2-3 PYTHONHASHSEED values and compares the hashes.

## 10. [medium] confidence_threshold from AnalysisInput never affects any asserted result

- Soubor: `/home/user/pet_app/tests/nutricalc/test_analysis.py`:689
- Popis: The spec makes the confidence threshold data passed via AnalysisInput. analyze_recipe forwards inp.confidence_threshold (analysis.py:302), but every analysis test either has all contributors of equal quality or a dominant low-quality contributor. So the asserted grade is the same for any threshold, and the plumbing is untested.
- Doklad: Replacing `inp.confidence_threshold` at analysis.py:302 with `Decimal(0)` -> 887 passed; with `Decimal(1)` -> 887 passed (both SURVIVED). The real code is sensitive to it: SYN_A with P quality D (0.6 g of 3.1 g) plus SYN_B quality B gives P confidence D with confidence_threshold=0.1 and B with 0.5.
- Návrh opravy: Add an analyze_recipe test using that synthetic pair at two thresholds (e.g. 0.1 -> D, 0.5 -> B). Optionally add a third case where no contributor reaches the threshold, to pin the documented fallback to all contributors.

## 11. [medium] Ca:P ratio boundaries are untested; all four comparison operators can be flipped

- Soubor: `/home/user/pet_app/tests/nutricalc/test_evaluation.py`:537
- Popis: evaluate_ratio compares the interval with RATIO_MIN/RATIO_MAX using strict `<`/`>` (evaluation.py:615-622). test_ratio_statuses only uses the irrational interval [5/3.1, 5.015/3.1] with limits clearly inside or outside it, so equality at a limit is never checked. docs/11 §11.2 requires boundary tests (value = limit -> ADEQUATE), and these exist for nutrients (test_minimum_boundary) but not for the ratio.
- Doklad: Mutation run on a scratchpad copy. Each of `interval.upper < req.value` -> `<=`, `interval.lower < req.value` -> `<=`, `interval.lower > req.value` -> `>=` and `interval.upper > req.value` -> `>=` gave `887 passed` (SURVIVED). The unmutated code gives Ca 3.0 g / P 2.0 g = 1.5 vs RATIO_MIN 1.5 -> ADEQUATE and vs RATIO_MAX 1.5 -> ADEQUATE; the first mutant turns the RATIO_MIN case into BELOW_MIN with no test failing.
- Návrh opravy: Add a parametrized test with an exact synthetic ratio (SYN item with Ca 3.0 and P 2.0 -> 1.5, plus an interval variant using value_min/value_max). Cover: point == RATIO_MIN -> ADEQUATE; point == RATIO_MAX -> ADEQUATE; interval lo == RATIO_MAX < hi -> BORDERLINE_MAX; interval lo < RATIO_MIN == hi -> BORDERLINE_MIN; plus values 1e-9 either side of each limit.

## 12. [medium] Global-context independence is tested only for a fixed subset of functions

- Soubor: `/home/user/pet_app/tests/nutricalc/test_properties.py`:209
- Popis: The hard rule says all arithmetic runs in the local context, independent of the global decimal context. test_results_do_not_depend_on_global_decimal_context (via _results(), line 162) and test_analysis_does_not_depend_on_global_decimal_context (test_analysis.py:677) run only a fixed list of calls, and analyze_recipe without warning rules. Functions outside that list can do arithmetic in the caller's context with no test noticing.
- Doklad: In a scratchpad copy I replaced `with calc_context():` by `contextlib.nullcontext()` in units.per_1000kcal_to_per_day, units.per_mj_to_per_1000kcal, units.per_day_to_per_kg_metabolic, Quantity.__add__, rules._matches (CategoryMassShareAbove share) and evaluation._round_for_display (format_coverage/format_decimal_cs). All 6 SURVIVED (`788 passed, 99 deselected`; the static test was deselected only to keep the injected import from tripping it).
- Návrh opravy: Parametrize the hostile-context check (prec 3, ROUND_DOWN, traps off) over every public numeric function: all units converters and Quantity operators, daily_requirement, actual_k, select_requirements, evaluate_nutrient, evaluate_ratio, confidence, format_coverage, format_decimal_cs, and evaluate_rules with CategoryMassShareAbove. Compare against results under the default context, using inputs with enough significant digits that prec 3 would change them. Also run analyze_recipe with warning rules under that context.

## 13. [medium] Static purity test is a denylist and misses realistic float and I/O paths

- Soubor: `/home/user/pet_app/tests/static_checks.py`:27
- Popis: The AST checks (float_offenders, import_offenders, name_offenders with FORBIDDEN_* in tests/nutricalc/test_static_nutricalc.py:21-64) only catch the obvious forms: float literals, the name `float`, math imports, `open`, and a fixed module denylist. Int/int true division is flagged only when both operands are int literals or len()/int() calls (INT_CALLS, line 14). nutricalc already imports `json`, so a future `json.loads(...)` without parse_float would bring in floats silently. `import decimal; decimal.localcontext()/decimal.DefaultContext` also gets past test_only_decimal_ctx_touches_decimal_contexts, which inspects only `from decimal import` names. SOURCES uses a non-recursive glob (line 19), so a subpackage would never be scanned.
- Doklad: I fed the shared checkers plus the nutricalc FORBIDDEN_MODULES/NAMES/ATTRIBUTES these snippets. All were MISSED: `share = sum(1 for x in xs if x) / len(xs)`, `r = count / total`, `y = 2 ** -1`, `y = pow(2, -1)`, `import operator; operator.truediv(1, 2)`, `import json; json.loads('1.5')`, `import codecs; codecs.open('x')`, `__builtins__['open']('x')`, `getattr(__builtins__, 'open')('x')`, `import fileinput`, `import posix; posix.open(...)`, `import _io`, `import ctypes`, `import mmap`, `import zipfile`, `hash('x')`, `id(x)`, `import locale`, `import decimal; decimal.DefaultContext.prec = 5`. Caught: `__import__('math')`, `import importlib`, `exec`, `import sys`, `import os`, `datetime.now()`.
- Návrh opravy: Replace the module denylist with an allowlist of what nutricalc actually imports: collections, collections.abc, contextlib, dataclasses, decimal (only via `from decimal import`), enum, functools, hashlib, json, re, types, typing, nutricalc.*. Ban the names `__builtins__`, `vars`, `locals`, `pow`, `hash`, `id`. Flag `**` with a negative int exponent. Flag `json.load`/`json.loads` calls without `parse_float=Decimal`. Flag `/` whose operands are int-returning calls (sum, len, count, round, abs, max, min) or int literals. Flag the attributes `localcontext`, `DefaultContext`, `Context` outside decimal_ctx.py. Use rglob. Add each bypass above to the known-bad snippet tables.

## 14. [medium] Gate-BLOCKED result (blocking health condition or toxic rule) still carries an energy estimate with status OK, DER numbers and energy deviation

- Soubor: `nutricalc/analysis.py`:469
- Popis: When the gate blocks because of a HealthConditionRef in BLOCKED mode or a BLOCKED rule, only the requirement evaluations are removed. result.energy keeps status OK with kcal_point/kcal_low/kcal_high and rer_kcal, and energy_deviation_pct is still computed. For BCS 1-2 and growth the energy module deliberately returns no numbers, but for CKD, pancreatitis, etc. (docs/09 §9.2 '⛔ Automatický výpočet nelze doporučit') a per-day energy need is still produced, and the result even says 'OK'. A consumer rendering result.energy will show an automatic energy recommendation for an animal that must not get one.
- Doklad: Reproduced in scratchpad repro7.py (a): animal with HealthConditionRef('CKD', BLOCKED) -> gate BLOCKED, energy.status OK, kcal_point/low/high 1040.3157..., energy_deviation_pct -51.29.
- Návrh opravy: When gate.status is BLOCKED, return an energy estimate without numbers (status BLOCKED, kcal_* and rer None) and energy_deviation_pct None, mirroring the BCS 1-2 policy. Alternatively add an explicit result-level field stating that the energy numbers are suppressed, plus a test.

## 15. [medium] Circular gate: a NutrientStatusIn rule can block the gate, after which the statuses and the rule warning that justify the block are removed

- Soubor: `nutricalc/analysis.py`:469
- Popis: Rules are evaluated against the nutrient statuses, and the gate consumes the rule warnings. If a NutrientStatusIn rule has level BLOCKED (or the gate is blocked for any reason), analyze_recipe then strips every evaluation and re-evaluates the rules without statuses. The final result has gate.reasons pointing to the rule, while `warnings` no longer contains it and no nutrient status explains it. The stored result cannot justify its own BLOCKED state, and the gate depends on an evaluation that the result is designed to hide. WarningRule does not restrict which levels a status-based condition may use.
- Doklad: WarningRule(code='SYN_RULE', level=BLOCKED, condition=NutrientStatusIn('P', {ADEQUATE})) on the synthetic recipe gives gate BLOCKED ['SYN_RULE'], warnings [], P status None.
- Návrh opravy: Split the gate into two phases. The pre-evaluation gate uses the animal, health conditions, energy and ingredient/category rules; status-based rules may only add NUTRITION_WARNING or EXPERT_REQUIRED and keep the statuses visible. Alternatively, reject BLOCKED on NutrientStatusIn rules in WarningRule.__post_init__. Add a test for this combination.

## 16. [medium] No warning when the ration supplies far less (or more) energy than the estimated need; per-1000-kcal 'all met' is then misleading

- Soubor: `nutricalc/analysis.py`:505
- Popis: The evaluation compares nutrient density per 1000 kcal. That only means the daily needs are covered if the animal actually gets about its DER from the ration. analyze_recipe computes energy_deviation_pct but never flags it, and summarize ignores it. A ration giving a quarter of the DER, and therefore roughly a quarter of the daily nutrients, gets ALL_EVALUATED_MET with no flag. The column and scaling choice also assumes the DER intake. A check needs no invented threshold: the energy estimate already carries data-driven kcal_low/kcal_high.
- Doklad: Reproduced in scratchpad repro3.py. Synthetic SYN_D (P 20, F 10, NFE 0, CF 0), 150 g, dog 20 kg, k 110: ME 253.344 vs DER 1040.32 (deviation -75.6 %), protein 30 g/day against a scaled synthetic requirement of about 57.8 g/day. Summary ALL_EVALUATED_MET, flags [], warnings []. Golden example: deviation -51.3 %, also ALL_EVALUATED_MET.
- Návrh opravy: When ration ME lies outside [energy.kcal_low, energy.kcal_high], add a NUTRITION_WARNING flag (e.g. RATION_ENERGY_OUTSIDE_NEED) explaining that the per-1000-kcal evaluation assumes the ration covers the energy need, and show daily totals vs daily_requirement. Consider capping the summary at BORDERLINE in that case. Any tolerance beyond the k_low/k_high range must come from data passed by the caller.

## 17. [medium] Confidence grade ignores ingredients without data, so a PARTIAL nutrient with 86 % of the mass missing can show grade A

- Soubor: `nutricalc/evaluation.py`:683
- Popis: analysis._confidence passes only total.contributors (items with a known upper bound) to confidence(). For a PARTIAL total, the missing items (quality D by MISSING_VALUE) are excluded, and the grade reflects only the minority of the mass that has data. Showing 'Spolehlivost A' next to a nutrient whose value is mostly unknown overstates data quality (docs/08 §8.1 principle 3). docs/06 §6.6.5 defines the grade relative to the upper bound of the total, which does not exist for PARTIAL.
- Doklad: Reproduced in scratchpad repro4.py (a): docs/06 §6.10 recipe with SYN_B values of quality A: CA completeness PARTIAL, missing_mass_share 0.857..., confidence A, status MIN_MET_PARTIAL.
- Návrh opravy: For PARTIAL or UNKNOWN totals, return the worst grade including D for items without data (or None plus an explicit 'not applicable'). Alternatively weight by mass share so that missing items above the threshold force D. Add a test for the §6.10 example.

## 18. [medium] INCOMPLETE summary message hides detected deficits and excesses (BELOW_MIN, ABOVE_MAX, ABOVE_SUL)

- Soubor: `nutricalc/evaluation.py`:824
- Popis: Rule order puts INCOMPLETE before DEFICITS_OR_EXCESSES. The INCOMPLETE message_cs only says 'Neúplné vyhodnocení ... Nelze plně vyhodnotit: CA' and says nothing about nutrients found below the minimum or above a maximum or SUL. The counts exist in status_counts, but the single Czech sentence that a UI or PDF is most likely to show omits a confirmed excess such as ABOVE_SUL. docs/08 §8.4 shows the incomplete card together with '▼ 2 pod minimem'.
- Doklad: Reproduced in scratchpad repro6.py (a): synthetic PROTEIN min 222.222 (BELOW_MIN) and CA min 12.345 (NOT_EVALUABLE) -> summary INCOMPLETE, message 'Neúplné vyhodnocení (vyhodnoceno 2 z 3 povinných živin). Nelze plně vyhodnotit: CA. Chybějící údaj nelze nahradit nulou.' The protein deficit is not mentioned.
- Návrh opravy: When the status is INCOMPLETE and any DEFICIT_OR_EXCESS or BORDERLINE status is present, append e.g. 'Zjištěno: 1 pod minimem, 0 nad maximem.' Consider a secondary field such as has_deficits_or_excesses so a UI can still use the red style. Add a test.

## 19. [medium] Toxic or other safety-flagged ingredients block only if the caller remembers to pass a matching rule; there is no fail-safe

- Soubor: `nutricalc/rules.py`:197
- Popis: Safety flags on IngredientProfile (e.g. TOXIC_FOR_SPECIES / TOXIC_FOR_DOG) affect the gate only through a WarningRule with IngredientFlagPresent. If warning_rules is empty, incomplete, or uses a different flag spelling, a recipe containing a species-toxic ingredient passes the gate as OK and can end ALL_EVALUATED_MET. Keeping rules as data is intended (docs/06 §6.7), but nothing detects a safety flag that no rule handles. The lens requirement that toxic ingredients really block therefore depends on the snapshot builder.
- Doklad: Reproduced in scratchpad repro4.py (b): synthetic SYN_TOX with safety_flags={'TOXIC_FOR_SPECIES'}, 600 g, warning_rules=() -> gate OK, summary ALL_EVALUATED_MET, warnings (), flags []. test_toxic_ingredient_rule_blocks covers only the case where the rule is supplied.
- Návrh opravy: In analyze_recipe, collect every safety flag present on recipe items that no IngredientFlagPresent rule (for the animal's species) references. Emit a gate reason UNHANDLED_SAFETY_FLAG at EXPERT_REQUIRED, or BLOCKED for a data-declared blocking vocabulary, naming the ingredients. Add a test with an unreferenced flag.

## 20. [medium] Equal inputs (== and the same Python hash) give different input_hash and result_hash because of the Decimal exponent

- Soubor: `nutricalc/snapshot.py`:243
- Popis: canonical_json keeps the Decimal string exactly as stored. As a result, AnalysisInput objects that compare equal and have the same __hash__ hash differently when a number differs only in trailing zeros ('300' vs '300.0'). The exponent also propagates into every computed output (P total '3.100' vs '3.1000', missing_mass_share '0' vs '0E+2'), so result_hash differs as well. The spec chose 'exactly as stored', but nothing in the code, tests or docs states the consequence. If the Django layer ever rebuilds a snapshot from DecimalField columns (fixed decimal_places) instead of the stored JSON, verify_analysis will report a mismatch for an identical calculation. Output values such as '0E+2' also leak into the stored result and the UI.
- Doklad: a = analysis_input(); b = analysis_input(items=(item(syn_a(), '300.0'), item(syn_b(), '50'))). a == b is True and hash(a) == hash(b) is True, yet input_hash(a) != input_hash(b) and analyze_recipe(a).result_hash != analyze_recipe(b).result_hash. P totals are Decimal('3.100') vs Decimal('3.1000').
- Návrh opravy: Choose one explicit canonical-number policy. Either normalize numeric inputs when the snapshot is built (for example strip trailing zeros or quantize to a documented scale per field) and normalize zero results, or keep 'as stored' and document it as a hard contract for the application layer: the snapshot must be persisted and re-read as canonical JSON, never rebuilt from relational columns. In both cases add a test that pins the chosen behaviour (equal-valued inputs give equal hashes, or are documented to differ).

## 21. [medium] Canonical JSON (and therefore input_hash and result_hash) depends on the caller's global decimal context

- Soubor: `nutricalc/snapshot.py`:246
- Popis: to_canonical serializes a Decimal with str(obj). CPython's Decimal.__str__ takes the 'E'/'e' exponent letter from the current thread's global context (Context.capitals). Any value that str() prints in scientific notation therefore produces a different JSON string, and a different hash, when the caller's context has capitals=0. Such values occur in practice: zero results whose ideal exponent is positive (for example missing_mass_share = Decimal('0E+2') when grams are given as '300.0' and '50.00', which is the usual shape coming from a Django DecimalField) and values below 1e-6. All arithmetic is correctly confined to calc_context (a hostile prec=3 global context with Inexact/Rounded/FloatOperation trapped gives the same hash). Serialization is the one remaining dependency on the global context. test_analysis_does_not_depend_on_global_decimal_context compares results with ==, not hashes, and does not change capitals.
- Doklad: b = analysis_input(items=(item(syn_a(), '300.0'), item(syn_b(), '50.00'))). analyze_recipe(b).nutrient('P').total.missing_mass_share == Decimal('0E+2'). Setting decimal.getcontext().capitals = 0 and re-running gives a different result_hash. For an input containing a value of 0.0000001, input_hash also changes.
- Návrh opravy: Make Decimal serialization independent of the context. Either run str() inside calc_context() (which sets capitals=1 explicitly), or build the string from obj.as_tuple() or format(obj, 'f') under a fixed policy. Add a test that computes canonical_json, input_hash and result_hash under a local context with capitals=0 and asserts the hashes are unchanged.

## 22. [low] docs/11 coverage target is not enforced; no coverage tool in the dev extra

- Soubor: `/home/user/pet_app/pyproject.toml`:12
- Popis: docs/11 §11.1 requires 100 % line and branch coverage in units, composition and evaluation, enforced in CI. The dev extra has only pytest and hypothesis, and there is no coverage configuration or fail-under, so a future untested branch would pass CI.
- Doklad: `pip list` in .venv: no coverage or pytest-cov. I measured with a sys.monitoring tracer in the scratchpad: line coverage of every nutricalc module is 100 % under tests/nutricalc. Approximate branch coverage finds real one-sided gaps, e.g. analysis.py:260/434 (needs_ratio False never taken) and requirements.py:483 (known is None never taken).
- Návrh opravy: Add pinned coverage (or pytest-cov) to the dev extra. Configure `[tool.coverage.run] branch = true, source = ['nutricalc']` and `fail_under = 100` (at least for units, composition, evaluation), and document the command in README 'Nástroje'.

## 23. [low] No property test for 'analyze_recipe never raises for data situations'

- Soubor: `/home/user/pet_app/tests/nutricalc/test_analysis.py`:282
- Popis: The spec says analyze_recipe raises only for invalid input, never for missing data or blocked states. The analysis-level hypothesis strategies (recipes, line 282) always use measured PROTEIN/FAT and ZERO_BY_DEFINITION NFE/CRUDE_FIBRE and never vary WATER/ASH/TDF, state or BCS. So missing macronutrients, NFE derivation, missing water with fibre and equation-out-of-range are never fuzzed end to end.
- Doklad: A scratchpad hypothesis fuzz (3000 derandomized examples) found no unexpected exception. It used random ValueKind or absence for PROTEIN, FAT, NFE, CRUDE_FIBRE, TDF, WATER, ASH, P and CA; 1-4 items; all three supported ME methods; every PhysiologicalState; and BCS None or 1-9. The only exceptions were the documented ValidationError for water > 100 g or fibre without dry matter. The implementation holds; the contract is just unguarded.
- Návrh opravy: Add that property test to tests/nutricalc/test_analysis.py. Assert analyze_recipe either returns a result with a 64-character result_hash or raises only the documented ValidationError for inconsistent composition. Also assert that NOT_EVALUABLE/UNKNOWN nutrients never carry coverage numbers.

## 24. [low] Rule for when Ca:P is computed is tested only when a CA_P requirement exists

- Soubor: `/home/user/pet_app/tests/nutricalc/test_analysis.py`:733
- Popis: The spec computes Ca:P when CA and P both appear in requirements or a CA_P ratio requirement exists (analysis.py:259). Every analysis fixture includes CA_P, so neither the 'CA and P but no CA_P' path nor the 'no ratio at all' path is tested.
- Doklad: Mutating analysis.py:259 to `needs_ratio = CA_P in ratios` -> 887 passed (SURVIVED). The branch tracer shows the False side of `if needs_ratio` (lines 260 and 434) is never taken. The real code with CA and P minima but no CA_P returns ratios [('CA_P', NO_REFERENCE)].
- Návrh opravy: Add two tests: (a) profiles with CA and P requirements but no CA_P -> one RatioResult with an interval and status NO_REFERENCE; (b) profiles with no CA, P or CA_P -> result.ratios == () and no CA/P NutrientResult.

## 25. [low] LEGAL_MAX_EU equality and PARTIAL lower == NUTRITIONAL_MAX boundaries untested

- Soubor: `/home/user/pet_app/tests/nutricalc/test_evaluation.py`:235
- Popis: ABOVE_LEGAL_MAX_INFO requires lower > L (strict). Tests use only 45 vs 40 and a crossing interval (35-45), so lower == L is never checked. Likewise test_partial_rules has no PARTIAL case with lower exactly equal to the nutritional max (expected NOT_EVALUABLE, not ABOVE_MAX).
- Doklad: Mutating evaluation.py:370 `low > legal.value` -> `low >= legal.value` gives 887 passed (SURVIVED). The real code gives interval [40, 40] vs LEGAL_MAX_EU 40 -> (ADEQUATE,).
- Návrh opravy: Add cases: COMPLETE interval('40') with LEGAL_MAX_EU 40 -> (ADEQUATE,); PARTIAL lower '50' with NUTRITIONAL_MAX 50 -> (NOT_EVALUABLE,); PARTIAL lower '80' with SUL 80 -> (NOT_EVALUABLE,).

## 26. [low] Some codes and paths are never asserted, and there is no every-code meta test like refdata's

- Soubor: `/home/user/pet_app/tests/nutricalc/test_gate.py`:87
- Popis: The gate reason code HEALTH_CONDITION never appears in any test; test_health_conditions checks only level and subject. summarize treats MIN_MET_PARTIAL with only a LEGAL_MAX_EU maximum as INCOMPLETE, but the test uses SUL only. Unlike tests/refdata/test_static_rules.py::test_every_finding_code_has_a_positive_and_negative_case, nutricalc has no meta test that every Flag/GateReason code has a positive and a negative case.
- Doklad: Renaming 'HEALTH_CONDITION' to 'CONDITION' in gate.py gives 887 passed (SURVIVED). Restricting evaluation.py:794 to {NUTRITIONAL_MAX, SUL} (dropping LEGAL_MAX_EU) gives 887 passed (SURVIVED). An AST scan of nutricalc's Flag/GateReason constructors found HEALTH_CONDITION with 0 occurrences in tests/nutricalc.
- Návrh opravy: Assert reason.code == 'HEALTH_CONDITION' in test_health_conditions. Add a summarize case with MIN_MET_PARTIAL and maxima {'CA': (LEGAL_MAX_EU,)} -> INCOMPLETE. Add a meta test that collects every literal code passed to Flag(...)/GateReason(...)/resolver.flag(...) in nutricalc and requires it in a *_CASES table with positive and negative inputs, mirroring refdata.

## 27. [low] ME edge paths untested: NFE difference exactly 0, and negative item ME with positive digestibility

- Soubor: `/home/user/pet_app/tests/nutricalc/test_me.py`:244
- Popis: The spec says only a negative NFE result is clamped with ME_NFE_NEGATIVE_CLAMPED, but no test computes an NFE of exactly 0. _out_of_range (me.py:499) also has an `me_kcal < 0` clause that no test reaches: SYN_F only exercises negative digestibility.
- Doklad: Mutating me.py:347 `computed < 0` -> `<= 0` gives 887 passed (SURVIVED); a real NFE of 0 would then wrongly get the clamp flag. Removing `or energy.me_kcal < 0` from me.py:499 also gives 887 passed (SURVIVED). A synthetic item with PROTEIN 37, FAT 0, NFE 0, CRUDE_FIBRE 63, WATER 0 has digestibility ≈ 1.11 % but ME ≈ -33 kcal/100 g.
- Návrh opravy: Add a case where WATER+PROTEIN+FAT+ASH+CRUDE_FIBRE = 100 exactly, asserting codes == ['ME_NFE_CALCULATED']. Add a case with the synthetic negative-ME item mixed with SYN_W, asserting per_item None for that item, the INFO ME_EQUATION_OUT_OF_RANGE flag with its subject, and a positive ration ME.

## 28. [low] 'Thresholds and rules are data' is only enforced against 95/110/75 literals

- Soubor: `/home/user/pet_app/tests/nutricalc/test_static_nutricalc.py`:90
- Popis: test_no_reference_energy_literals rejects only 95/110/75, and the hundred check covers only requirements.py. Nothing stops a hard-coded threshold such as `Decimal("0.05")` or a liver share `Decimal("0.15")` in evaluation.py, rules.py, gate.py or analysis.py, or a default value for confidence(threshold). The spec explicitly says confidence has no default literal.
- Doklad: Adding `threshold: Decimal = Decimal("0.05")` as a default to evaluation.confidence gives 887 passed (SURVIVED). The data-driven modules today contain only the structural literals 0, 1, 100, 1000 (plus ints 4, 12, 20), so an allowlist would pass now.
- Návrh opravy: In requirements.py, evaluation.py, rules.py, gate.py and analysis.py, allowlist numeric/Decimal literals to the structural set {0, 1, 100, 1000} plus explicitly named technical constants. Add `assert inspect.signature(confidence).parameters['threshold'].default is inspect.Parameter.empty`.

## 29. [low] Float rejection is not tested for 10 public numeric functions

- Soubor: `/home/user/pet_app/tests/nutricalc/test_units.py`:241
- Popis: The hard rule says public functions reject float with TypeError. All of them do, through to_decimal, but ten public functions have no `pytest.raises(TypeError)` test with a float argument. A refactor that bypassed to_decimal (e.g. `Decimal(str(x))`) in one of them would go unnoticed.
- Doklad: An AST scan of tests/nutricalc for pytest.raises(TypeError) blocks found no float test for: per_100g_as_fed_to_per_day, per_day_to_per_1000kcal, per_1000kcal_to_per_day, nrc_kitten_me_kcal, energy_digestibility_pct, fibre_percent_of_dm, nrc2006_dog_energy, daily_requirement, per_1000kcal_interval, format_decimal_cs. Calling each with a float raises TypeError today.
- Návrh opravy: Add one parametrized test listing every public function and numeric parameter (a table of lambdas), asserting TypeError for a float (e.g. 1.5) and for bool. Keep the table next to the static test so new public functions are added to it.

## 30. [low] Confidence ignores ingredients with missing values, so PARTIAL nutrients can report good confidence

- Soubor: `nutricalc/analysis.py`:291
- Popis: _confidence only considers total.contributors, which are the items with a known upper bound. Items whose value is MISSING are skipped, even though MISSING_VALUE is defined with QualityGrade.D. A nutrient where most of the ration mass has no data can therefore show confidence A or B. Completeness is still reported separately, but the API invites reading confidence as data quality for the whole nutrient.
- Doklad: Golden docs/06 6.10 example: CA completeness PARTIAL, missing_mass_share 0.857…, confidence B (from SYN_B only).
- Návrh opravy: Either include unknown-upper items as the worst grade (D) when computing confidence for non-COMPLETE totals, or document in NutrientResult that confidence covers only the known contributors and must always be shown together with completeness.

## 31. [low] Skipped conditional requirements are only INFO and do not affect the summary

- Soubor: `nutricalc/analysis.py`:320
- Popis: Requirements with a non-empty condition_note are never evaluated, and REQUIREMENT_CONDITION_NOT_APPLIED is emitted at INFO level. Conditional requirements in standards are often stricter, e.g. a higher minimum under a dietary condition. The summary can still say all evaluated requirements are met, and the gate is unaffected. The message itself says an expert must assess whether the condition applies, which is at odds with the INFO level.
- Doklad: analysis._split keeps only condition_note == ''. _condition_flag uses WarningLevel.INFO. test_conditional_requirements_are_flagged_not_applied shows no effect on summary or gate.
- Návrh opravy: Raise the flag to NUTRITION_WARNING or EXPERT_REQUIRED (feeding the gate if EXPERT_REQUIRED), or treat a nutrient with unapplied conditional requirements as not fully evaluated so the summary cannot be ALL_EVALUATED_MET. At minimum, mention the skipped conditions in the summary message.

## 32. [low] Summary required_count is computed from different mandatory sets depending on the gate

- Soubor: `nutricalc/analysis.py`:468
- Popis: In the BLOCKED path, summarize receives the union of both profiles' mandatory_nutrients. In the normal path it receives only selected.profile_used.mandatory_nutrients. 'Vyhodnoceno X z Y' and not_evaluated therefore change meaning with the gate status for the same input data.
- Doklad: analysis.py:468 builds mandatory_all = high | low for the blocked branch; analysis.py:499 passes selected.profile_used.mandatory_nutrients. When the two profiles have different mandatory sets, required_count differs between a BLOCKED and an OK run of the same recipe.
- Návrh opravy: Use one definition in both branches: the profile that would be used when selected is available, otherwise the high profile (or the union). Document the choice in the Summary docstring.

## 33. [low] BLOCKED result can list gate reasons from status-based rules whose warnings and evaluations were removed

- Soubor: `nutricalc/analysis.py`:473
- Popis: The gate is computed from warnings evaluated with nutrient statuses. When the gate blocks, warnings are re-evaluated without statuses and evaluations are set to None, but gate.reasons is not recomputed. A NutrientStatusIn rule of EXPERT_REQUIRED or BLOCKED level can therefore appear in gate.reasons while its warning and the nutrient status that triggered it are absent from the result. A status-based BLOCKED rule also hides the very evaluation that caused the block.
- Doklad: analysis.py:463-479: gate = evaluate_gate(..., warnings) is computed before warnings is replaced by evaluate_rules(inp.warning_rules, RuleContext(species, items)) in the BLOCKED branch; gate is not recomputed.
- Návrh opravy: Either keep the status-based warnings and evaluation that caused a block in the result, or recompute gate.reasons from the final warnings. Document which option is chosen and add a test with a NutrientStatusIn BLOCKED rule.

## 34. [low] Frozen IngredientProfile reads lookups from a mutable cache that is outside eq, hash and canonical JSON

- Soubor: `nutricalc/composition.py`:190
- Popis: IngredientProfile.get() and values_map read the cached_property _index, a plain dict that is not a dataclass field. Mutating it (profile._index['CA'] = ...) silently changes every calculation, while equality, the Python hash and input_hash are unchanged, so the snapshot no longer describes what was computed. RuleContext similarly stores a MappingProxyType in a frozen, eq=True dataclass, so hash(RuleContext(...)) raises TypeError.
- Doklad: composition.py:189-197: @cached_property _index returns dict(self.values); get() uses self._index.get(...). rules.py:161 nutrient_statuses is a MappingProxyType field of a frozen dataclass.
- Návrh opravy: Store the index as an immutable MappingProxyType (or look values up in the sorted tuple) and set it in __init__ via object.__setattr__ under a non-field name. For RuleContext, store nutrient_statuses as a sorted tuple of pairs, or set eq=False / unsafe_hash appropriately.

## 35. [low] Rules duplicated from refdata have no parity tests

- Soubor: `nutricalc/decimal_ctx.py`:134
- Popis: Enum values, KJ_PER_KCAL and METABOLIC_EXPONENT are checked against refdata in tests (test_vocab_flags.py). The strict number pattern in to_decimal (a copy of refdata.decimal_utils._DECIMAL_PATTERN) and the min<max rule in requirements.check_requirement_set (a copy of refdata's E_MIN_NOT_BELOW_MAX after the part A change) are re-implemented with no test that keeps them aligned. A later change to refdata, such as the recent nutritional-vs-legal relaxation, could silently diverge from the core.
- Doklad: grep finds no refdata import in tests/nutricalc/test_decimal_ctx.py or test_requirements.py; refdata/decimal_utils.py:56 and nutricalc/decimal_ctx.py:134 define the same regex independently.
- Návrh opravy: Add parity tests (tests may import refdata). Run one shared list of accepted and rejected strings through both parse_decimal and to_decimal, and one shared set of synthetic requirement rows through refdata.validate and nutricalc.requirements.check_requirement_set, asserting the same accept/reject outcome.

## 36. [low] Czech user-facing messages contain raw enum codes and an internal doc reference

- Soubor: `nutricalc/energy.py`:378
- Popis: Messages interpolate enum values instead of Czech labels: 'Pro stav GROWTH nelze automatický výpočet energie doporučit' (also gate.py PHYSIOLOGICAL_STATE_NOT_SUPPORTED), 'pro druh DOG' (energy._check_input, requirements, analysis._validate), 'Zdravotní stav CKD'. gate.py:185 appends '(bezpečnostní brána, docs/09 §9.2)' to an owner-facing message. SPECIES_LABELS and LIFE_STAGE_LABELS exist but are not used here.
- Doklad: scratchpad repro7.py (c) output: 'Pro stav GROWTH nelze automatický výpočet energie doporučit (růst, březost a laktace nejsou v této verzi podporovány)...'. Gate message: 'Zdravotní stav CKD: automatický výpočet nelze doporučit (bezpečnostní brána, docs/09 §9.2).'
- Návrh opravy: Add a PHYSIOLOGICAL_STATE_LABELS mapping and use SPECIES_LABELS and LIFE_STAGE_LABELS in messages. Drop the docs reference from message_cs (keep it in docstrings). Let the app layer supply Czech health-condition names, or keep the code but phrase it as 'zdravotní stav (kód CKD)'.

## 37. [low] No display guard for maxima: an exceeded maximum can be shown as '100 %'

- Soubor: `nutricalc/evaluation.py`:487
- Popis: format_coverage protects only the minimum case (true value < 100 that rounds to 100 is shown as '< 100 %'). There is no counterpart for percent of maximum, so pct_of_max_low = 100.04 (status ABOVE_MAX) is displayed as '100 %'. Next to the red 'nad maximem' label, the number then looks compliant (docs/09 T5: rounding must not change the perceived state).
- Doklad: format_coverage(Decimal('100.04')) -> '100 %' while evaluate_nutrient gives ABOVE_MAX for lower 100.04 % of NUTRITIONAL_MAX.
- Návrh opravy: Add format_pct_of_max (or a parameter) that shows '> 100 %' when the true value is > 100 but rounds to 100. Test it alongside the '< 100 %' rule.

## 38. [low] ratio_interval and evaluate_ratio accept float-valued NutrientTotal and compute in float

- Soubor: `nutricalc/evaluation.py`:573
- Popis: NutrientTotal is a plain frozen dataclass with no __post_init__ validation. ratio_interval only checks the type, codes, units and basis, then divides numerator.lower / denominator.upper directly. A float-valued NutrientTotal built by a caller is therefore silently computed in binary float. That violates the hard rule that public functions reject float inputs with TypeError. per_1000kcal_interval does reject floats, because it goes through Quantity.
- Doklad: Reproduced: NutrientTotal(nutrient_code='CA', unit=Unit.G, basis=Basis.PER_DAY, lower=5.0, upper=5.015, point=None, completeness=COMPLETE, missing_mass_share=0, contributors=()) with P lower=upper=point=3.1. ratio_interval returns RatioInterval(lower=1.6129032258064515, upper=1.617741935483871) as floats. per_1000kcal_interval(p, Decimal('506.688')) on the same input raises TypeError.
- Návrh opravy: Add __post_init__ to NutrientTotal (and Contributor, if public) that runs to_decimal on lower/upper/point/missing_mass_share and checks the completeness invariants. Or call to_decimal on the bounds in _check_ratio_totals. Add a TypeError test for evaluate_ratio with float totals.

## 39. [low] Inconsistent input and error conventions between part 1 and part 2 APIs

- Soubor: `nutricalc/evaluation.py`:666
- Popis: Part 1 functions accept Decimal | int | str through to_decimal, but confidence(threshold), AnalysisInput.confidence_threshold and scale_minima(factor) accept only Decimal. The same bad method string raises InvalidInputError from AnalysisInput.me_method but UnsupportedMethodError from ration_me (_check_method converts it). UnsupportedMethodError and MissingDataError are not ValidationError subclasses, yet analyze_recipe can raise UnsupportedMethodError for an input choice (NRC2006_CAT); docs/06 6.9 does not list it. A caller that catches ValidationError as 'invalid input' will miss it.
- Doklad: confidence([...], 1) gives TypeError while rer_kcal(1) works. AnalysisInput(me_method='X') gives InvalidInputError, while ration_me(items, 'X', 'DOG') gives UnsupportedMethodError. analyze_recipe(analysis_input(me_method=MeMethod.NRC2006_CAT)) raises UnsupportedMethodError, which is not a ValidationError.
- Návrh opravy: Choose one numeric-input policy (either Decimal-only everywhere or to_decimal everywhere) and one error type for unknown or unsupported methods. List UnsupportedMethodError in the analyze_recipe docstring and in docs/06 6.9, or make it a ValidationError subclass.

## 40. [low] Ca MIN_MET_PARTIAL with an unverifiable Ca:P RATIO_MAX still allows ALL_EVALUATED_MET (the docs/06 6.10 golden case)

- Soubor: `nutricalc/evaluation.py`:791
- Popis: summarize treats a mandatory MIN_MET_PARTIAL nutrient as unevaluated only if that nutrient has its own NUTRITIONAL_MAX, SUL or LEGAL_MAX_EU. In the golden example Ca is PARTIAL (85.7 % of mass without data). It meets the synthetic minimum by its lower bound alone. Its upper bound is unknown, so the profile's CA_P RATIO_MAX cannot be checked (ratio NOT_EVALUABLE). Because CA_P itself is not mandatory and Ca has no direct maximum, the summary is ALL_EVALUATED_MET. This follows the letter of the listed rules. But it misses the intent of 'MIN_MET_PARTIAL while it has a maximum': a ratio maximum that depends on Ca's unknown upper bound cannot be verified. test_missing_calcium_never_becomes_deficit explicitly accepts this outcome.
- Doklad: analyze_recipe(analysis_input()) on the docs/06 6.10 example gives CA MIN_MET_PARTIAL, CA_P interval None and status NOT_EVALUABLE, summary ALL_EVALUATED_MET ('Všechny vyhodnocené požadavky standardu TESTSTD 1 ... jsou splněny'). test_golden_example_summary_and_metadata asserts ALL_EVALUATED_MET.
- Návrh opravy: In summarize, also count a nutrient as having a maximum when it is a component (RATIO_COMPONENTS) of a ratio with a RATIO_MAX requirement. Or treat any ratio with requirements that is NOT_EVALUABLE as blocking ALL_EVALUATED_MET (e.g. INCOMPLETE or BORDERLINE). Otherwise, document in docs/06 6.6.4 that Ca:P must be listed as mandatory for this protection to apply.

## 41. [low] Duplicated near-identical types and helpers across modules

- Soubor: `nutricalc/gate.py`:71
- Popis: GateReason repeats the fields of Flag (level, code, message_cs, subject) but has no validation and has its own sort key (_reason_key). RuleWarning has a third, almost identical sort key (_warning_key). GateReason.subject is a lossy ', '.join of ingredient codes. _positive is copied in energy, units and requirements and raises InvalidInputError in two of them and ValidationError in the third. BCS range validation is repeated in energy._check_input, gate._check_bcs and AnimalSnapshot.
- Doklad: gate.py:71 GateReason vs flags.py Flag; gate.py _reason_key vs flags._sort_key vs rules._warning_key; energy.py:83, units.py:202, requirements.py:346 _positive.
- Návrh opravy: Reuse Flag for gate reasons, or derive them from one validated base. Share a single severity sort key and one positive-number helper in decimal_ctx with a documented exception type. Keep BCS validation in one function that the other modules import.

## 42. [low] Ration-level ME_EQUATION_OUT_OF_RANGE has level EXPERT_REQUIRED but never reaches the gate

- Soubor: `nutricalc/me.py`:590
- Popis: When the NRC equation gives negative digestibility or negative ME for the whole ration, ration_me returns kcal None. It also emits a Flag at level EXPERT_REQUIRED ('Dávku musí posoudit odborník'). evaluate_gate only reads the energy-estimate status, health conditions and rule warnings, so the gate stays OK while a flag at expert-review level exists. Nutrients become NOT_EVALUABLE, so no false green results. But the flag level and the gate disagree, and the UI cannot rely on gate.status for expert review.
- Doklad: Reproduced: SYN_G with PROTEIN 1, FAT 1, NFE 0, CRUDE_FIBRE 80, WATER 10, 100 g. Result: me.kcal None, me.flags include (EXPERT_REQUIRED, ME_EQUATION_OUT_OF_RANGE), gate.status OK, summary INCOMPLETE.
- Návrh opravy: Either pass ME flags at EXPERT_REQUIRED or BLOCKED level into evaluate_gate as reasons, or lower this flag to NUTRITION_WARNING so the levels agree. Document the choice in docs/06 6.3.

## 43. [low] Ration-level ME_EQUATION_OUT_OF_RANGE has EXPERT_REQUIRED level but never reaches the gate

- Soubor: `nutricalc/me.py`:590
- Popis: _ration_kcal emits a Flag with level EXPERT_REQUIRED and the text 'Dávku musí posoudit odborník', but me.flags are not passed to evaluate_gate (only the energy estimate and rule warnings are). The gate stays OK, which contradicts the flag's own level and wording.
- Doklad: Reproduced in scratchpad repro7.py (b): synthetic SYN_F with CRUDE_FIBRE 60 and WATER 10 -> me.kcal None, me.flags include ('EXPERT_REQUIRED','ME_EQUATION_OUT_OF_RANGE'), gate OK, summary INCOMPLETE.
- Návrh opravy: Pass flags of EXPERT_REQUIRED or BLOCKED level from me (and from selected requirements) into evaluate_gate as reasons, or lower this flag to NUTRITION_WARNING and reword it.
