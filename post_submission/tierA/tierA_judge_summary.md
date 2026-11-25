# Tier A — judge agreement, per-profile rates, arm comparison, retention by type

Source of every number: `tierA_judge_compute.py` run over the released artifact (`tierA_judge_run.log`, `tierA_judge_results.json`). Nothing in the artifact's own scripts was executed. Line numbers refer to `paper/main.tex`.

## 0. Sanity checks against the paper (all reproduced)

| Quantity | Shipped arm (script) | URL-first arm (script) | Paper |
|---|---|---|---|
| retrieved chunks over 134 questions | 4024 | 3947 | 4,024 (L209–210) |
| chunks from URL-less stratum `hf_vi_mtue29_medical` | 2472 (share 0.6143) | 0 | 2,472 / 61.4 % (abstract L94) |
| extracted claims (`claims_total`) | 351 | 379 | 351 / 379 (L500–502) |
| uncitable claims = cited chunk in URL-less stratum + chunk id not resolvable | 156 = 154 + 2 | 1 = 0 + 1 | 156 (Table I footnote) |
| drop reasons | cited_record_not_citable 147, span_not_found 17, chunk_id_not_resolvable 2 | span_not_found 14, chunk_id_not_resolvable 1 | 147 / 19 (L468–469) |
| returned claims (`claims_displayed` = len(claim_attributions)) | 185 | 364 | 185 / 364 |
| answers with zero returned claims | 79 | 25 | 79 / 25 |
| out-of-corpus controls: claims returned | 25 | 41 | 25 / 41 (L523–524) |

Controls are identified in `probe_queries_v2.jsonl` by `source == "rivf_grid_v2:out_of_corpus_control/<type>"` (15 ids `rivf_051`–`rivf_065`). Judge controls are `key[item].kind == "control"` in the four `*_key_*.json` files (37 per instrument per arm). The mapping check passed: in every (arm, instrument) the real items map one-to-one onto the capture's returned claims by (query_id, claim text).

**Profile field.** `metadata.answer_mode` is `"standard"` for all 134 records in both arms, so it cannot split standard vs deep. The paper's standard/deep profile (L205–206: "of the 134, 67 ran a standard profile ... and 67 a deep profile") is `metadata.pipeline.retrieval_profile` (standard 67 / deep 67, identical per question in both arms). That field is used below wherever "answer_mode" was requested; the literal answer_mode split is a single group and is recorded in the JSON.

## 1. Judge agreement and Cohen's kappa (pass A vs pass B)

Formula: p_o = #(label_A = label_B)/n; p_e = Σ_k (n_Ak/n)(n_Bk/n); κ = (p_o − p_e)/(1 − p_e). Label sets: entailment {supported, overstated, not_supported, unintelligible}; relevance {relevant, partial, not_relevant}.

| Run | Items | n | agree | raw agreement | p_e | κ | pass-A distribution | pass-B distribution |
|---|---|---|---|---|---|---|---|---|
| shipped / entailment / original | all | 222 | 220 | 0.9910 | 0.6729 | 0.9725 | sup 177, over 0, not 38, unint 7 | sup 179, over 0, not 38, unint 5 |
| shipped / entailment / original | real only | 185 | 183 | 0.9892 | 0.9268 | 0.8524 | sup 177, not 1, unint 7 | sup 179, not 1, unint 5 |
| shipped / relevance / original | all | 222 | 217 | 0.9775 | 0.4963 | 0.9553 | rel 4, part 127, not 91 | rel 4, part 128, not 90 |
| shipped / relevance / original | real only | 185 | 180 | 0.9730 | 0.5591 | 0.9387 | rel 4, part 127, not 54 | rel 4, part 128, not 53 |
| URL-first / entailment / original | all | 401 | 397 | 0.9900 | 0.7682 | 0.9570 | sup 349, over 0, not 40, unint 12 | sup 349, over 1, not 40, unint 11 |
| URL-first / entailment / original | real only | 364 | 360 | 0.9890 | 0.9203 | 0.8620 | sup 349, not 3, unint 12 | sup 349, over 1, not 3, unint 11 |
| URL-first / relevance / original | all | 401 | 383 | 0.9551 | 0.5285 | 0.9048 | rel 10, part 260, not 131 | rel 9, part 260, not 132 |
| URL-first / relevance / original | real only | 364 | 346 | 0.9505 | 0.5758 | 0.8834 | rel 10, part 259, not 95 | rel 9, part 259, not 96 |
| URL-first / entailment / matched re-judge | all | 401 | 392 | 0.9776 | 0.7534 | 0.9090 | sup 344, over 0, not 40, unint 17 | sup 347, over 1, not 38, unint 15 |
| URL-first / entailment / matched re-judge | real only | 364 | 355 | 0.9753 | 0.9029 | 0.7455 | sup 344, not 3, unint 17 | sup 347, over 1, not 1, unint 15 |
| URL-first / relevance / matched re-judge | all | 401 | 395 | 0.9850 | 0.5384 | 0.9676 | rel 12, part 271, not 118 | rel 15, part 267, not 119 |
| URL-first / relevance / matched re-judge | real only | 364 | 358 | 0.9835 | 0.5948 | 0.9593 | rel 12, part 270, not 82 | rel 15, part 266, not 83 |
| shipped / entailment / pinned re-run (+rematch) | all / real | 222 / 185 | 220 / 184 | 0.9910 / 0.9946 | 0.6757 / 0.9319 | 0.9722 / 0.9207 | — | — |
| shipped / relevance / pinned re-run (+rematch) | all / real | 222 / 185 | 217 / 180 | 0.9775 / 0.9730 | 0.5015 / 0.5849 | 0.9548 / 0.9349 | — | — |

Paper sentences:
- L408–409 "Agreement was 99.1 % (κ = 0.973) and all 37 controls were rejected." → reproduced on all 222 items (220/222 = 0.9910, κ = 0.9725). On the 185 real claims the same two passes give 183/185 = 0.9892, κ = 0.8524 (p_e = 0.9268, because 177–179 of 185 are `supported`); the κ the paper quotes is inflated by the 37 easy-negative controls, as JUDGE-CONFIGURATION.md itself notes.
- L434–435 "Two blind passes agreed 97.8 % (κ = 0.955) and 37 of 37 controls were rejected." → reproduced (217/222 = 0.9775, κ = 0.9553); on real claims 180/185 = 0.9730, κ = 0.9387.
- Final-label control counts (all four runs): shipped entailment controls 37/37 `not_supported`; shipped relevance 37/37 `not_relevant`; URL-first original entailment 37/37 `not_supported`, relevance 37/37 `not_relevant`; URL-first matched entailment 37/37 `not_supported`, relevance 36 `not_relevant` + 1 `partial` (from `tierA_results.json → task1 → final_label_distribution_controls`).

## 2. Final (adjudicated) labels per returned claim

Final label = pass-A label if A = B, else the adjudicated label. Support rate = #supported / #returned claims; responsiveness = #relevant / #returned claims.

### 2a. Shipped arm, original labels (entailment judge `claude-opus-5`, relevance judge `claude-fable-5-1`)

| Subset | questions (with claims) | claims | supported | overstated | not_supported | unintelligible | support rate | relevant | partial | not_relevant | responsiveness |
|---|---|---|---|---|---|---|---|---|---|---|---|
| all 134 | 134 (55) | 185 | 179 | 0 | 1 | 5 | 0.9676 | 4 | 129 | 52 | 0.0216 |
| answerable 119 | 119 (47) | 160 | 155 | 0 | 1 | 4 | 0.9688 | 4 | 120 | 36 | 0.0250 |
| controls 15 | 15 (8) | 25 | 24 | 0 | 0 | 1 | 0.9600 | 0 | 9 | 16 | 0.0000 |
| profile standard (extractor unused) | 67 (32) | 107 | 102 | 0 | 0 | 5 | 0.9533 | 2 | 74 | 31 | 0.0187 |
| profile deep (extractor used) | 67 (23) | 78 | 77 | 0 | 1 | 0 | 0.9872 | 2 | 55 | 21 | 0.0256 |
| standard, answerable | 58 (27) | 92 | 88 | 0 | 0 | 4 | 0.9565 | 2 | 68 | 22 | 0.0217 |
| deep, answerable | 61 (20) | 68 | 67 | 0 | 1 | 0 | 0.9853 | 2 | 52 | 14 | 0.0294 |

Joint labels per claim (shipped original): supported|relevant 4, supported|partial 126, supported|not_relevant 49, unintelligible|partial 3, unintelligible|not_relevant 2, not_supported|not_relevant 1.

Paper sentences: L411 "179 of 185 claims are supported: 0.968" → 179/185 = 0.9676. L437–440 "4 of the 185 returned claims answer their question: 0.022 ... 129 are partial ... and 52 are unrelated, 49 of them supported" → 4 / 129 / 52 / 49 reproduced. L564 "Support (0.968) and responsiveness (0.022)" → same. New per-profile sentence the paper could add after L206: "Support is 0.953 (102/107) in the standard profile and 0.987 (77/78) in the deep profile; responsiveness 0.019 (2/107) and 0.026 (2/78); on answerable questions the 160 claims give 0.969 support and 0.025 responsiveness."

### 2b. Shipped arm, pinned re-run + matched re-adjudication (secondary; `claude-opus-5` both instruments)

| Subset | claims | supported | support rate | relevant | partial | not_relevant | responsiveness |
|---|---|---|---|---|---|---|---|
| all 134 | 185 | 179 | 0.9676 | 7 | 137 | 41 | 0.0378 |
| answerable 119 | 160 | 155 | 0.9688 | 7 | 125 | 28 | 0.0437 |
| standard / deep | 107 / 78 | 102 / 77 | 0.9533 / 0.9872 | 4 / 3 | 80 / 57 | 23 / 18 | 0.0374 / 0.0385 |

Joint: supported|not_relevant 40. Answer level: 5 of 55 answers with claims carry a `relevant` claim, 12 carry only `not_relevant` ones. → L440–442 "under the matched labels, 5 of 55 answers with any claim carry one that answers and 12 only unrelated ones" reproduced; L511 "responsiveness 0.038" reproduced (7/185 = 0.0378); L523 "against 40" reproduced.

### 2c. URL-first arm — PRIMARY = matched re-judge labels (`arm_matched_rejudge_v1.json`, present; shipped codebook, `claude-opus-5`)

| Subset | questions (with claims) | claims | supported | overstated | not_supported | unintelligible | support rate | relevant | partial | not_relevant | responsiveness |
|---|---|---|---|---|---|---|---|---|---|---|---|
| all 134 | 134 (109) | 364 | 348 | 1 | 3 | 12 | 0.9560 | 13 | 268 | 83 | 0.0357 |
| answerable 119 | 119 (96) | 323 | 308 | 1 | 3 | 11 | 0.9536 | 12 | 252 | 59 | 0.0372 |
| controls 15 | 15 (13) | 41 | 40 | 0 | 0 | 1 | 0.9756 | 1 | 16 | 24 | 0.0244 |
| profile standard | 67 (65) | 219 | 210 | 0 | 1 | 8 | 0.9589 | 9 | 162 | 48 | 0.0411 |
| profile deep | 67 (44) | 145 | 138 | 1 | 2 | 4 | 0.9517 | 4 | 106 | 35 | 0.0276 |
| standard, answerable | 58 (56) | 191 | 182 | 0 | 1 | 8 | 0.9529 | 8 | 149 | 34 | 0.0419 |
| deep, answerable | 61 (40) | 132 | 126 | 1 | 2 | 3 | 0.9545 | 4 | 103 | 25 | 0.0303 |

Joint: supported|not_relevant 78. Answer level: 10 of 109 answers with claims carry a `relevant` claim, 26 only `not_relevant`. → L511 "support ... against 0.956 and responsiveness ... against 0.036" reproduced (348/364 = 0.9560; 13/364 = 0.0357); L442 "10 of 109 and 26" reproduced; L522–523 "78 supported-but-unrelated ones" reproduced.

Secondary, URL-first original labels (`claude-fable-5-1`, shorter codebook): support 350/364 = 0.9615 (answerable 310/323 = 0.9598; standard 210/219 = 0.9589, deep 140/145 = 0.9655); responsiveness 10/364 = 0.0275 (answerable 9/323 = 0.0279; standard 6/219 = 0.0274, deep 4/145 = 0.0276); partial 254, not_relevant 100; supported|not_relevant 95; answer level 10 of 109 and 29.

## 3. Retention by question type and by profile, both arms

retention = Σ_q claims_displayed(q) / Σ_q claims_total(q) (ratio of sums). CI: percentile cluster bootstrap over questions in the group, 5,000 resamples, `random.Random(0)`, [2.5th, 97.5th] percentile (numpy linear interpolation).

### Shipped arm

| Group | n questions (134 / 119) | displayed/total (134) | retention (134) [CI] | displayed/total (119) | retention (119) [CI] |
|---|---|---|---|---|---|
| overall | 134 / 119 | 185/351 | 0.5271 [0.4307, 0.6203] | 160/312 | 0.5128 [0.4094, 0.6134] |
| clinical_explainer | 29 / 24 | 65/94 | 0.6915 [0.5000, 0.8684] | 56/82 | 0.6829 [0.4750, 0.8675] |
| differential_or_workup | 25 / 24 | 14/28 | 0.5000 [0.1667, 0.7857] | 14/28 | 0.5000 [0.1739, 0.7778] |
| guideline_comparison | 26 / 24 | 64/90 | 0.7111 [0.5227, 0.8721] | 57/83 | 0.6867 [0.4868, 0.8539] |
| patient_faq | 26 / 23 | 9/57 | 0.1579 [0.0000, 0.3333] | 6/49 | 0.1224 [0.0000, 0.3125] |
| study_result_numeric | 28 / 24 | 33/82 | 0.4024 [0.2195, 0.5854] | 27/70 | 0.3857 [0.1818, 0.5833] |
| max/min type ratio | | guideline 0.7111 / patient_faq 0.1579 | **4.503** | guideline 0.6867 / patient_faq 0.1224 | **5.61** |
| profile standard | 67 / 58 | 107/208 | 0.5144 [0.3883, 0.6377] | 92/184 | 0.5000 [0.3646, 0.6296] |
| profile deep | 67 / 61 | 78/143 | 0.5455 [0.3969, 0.6860] | 68/128 | 0.5312 [0.3684, 0.6853] |

### URL-first arm

| Group | n questions (134 / 119) | displayed/total (134) | retention (134) [CI] | displayed/total (119) | retention (119) [CI] |
|---|---|---|---|---|---|
| overall | 134 / 119 | 364/379 | 0.9604 [0.9310, 0.9839] | 323/334 | 0.9671 [0.9396, 0.9886] |
| clinical_explainer | 29 / 24 | 101/101 | 1.0000 [1.0, 1.0] | 85/85 | 1.0000 [1.0, 1.0] |
| differential_or_workup | 25 / 24 | 16/22 | 0.7273 [0.4286, 0.9167] | 16/22 | 0.7273 [0.4286, 0.9200] |
| guideline_comparison | 26 / 24 | 96/99 | 0.9697 [0.9043, 1.0] | 89/92 | 0.9674 [0.8966, 1.0] |
| patient_faq | 26 / 23 | 67/71 | 0.9437 [0.8727, 1.0] | 61/63 | 0.9683 [0.9152, 1.0] |
| study_result_numeric | 28 / 24 | 84/86 | 0.9767 [0.9333, 1.0] | 72/72 | 1.0000 [1.0, 1.0] |
| max/min type ratio | | clinical 1.0 / differential 0.7273 | **1.375** | clinical 1.0 / differential 0.7273 | **1.375** |
| profile standard | 67 / 58 | 219/219 | 1.0000 [1.0, 1.0] | 191/191 | 1.0000 [1.0, 1.0] |
| profile deep | 67 / 61 | 145/160 | 0.9062 [0.8397, 0.9605] | 132/143 | 0.9231 [0.8548, 0.9744] |

Paper sentences: L473–475 "Over the 119 answerable questions, retention by question type runs from 0.122 for patient-FAQ questions to 0.687 for guideline-comparison questions---a factor of 5.6" → reproduced exactly (6/49 = 0.1224; 57/83 = 0.6867; 5.61); question counts per type on the 119 are 24/24/24/23/24 and could be stated. Over all 134 the spread is 0.158 to 0.711 (4.50×). L469–470 "retention ... falls from 0.946 to 0.527" → 185/351 = 0.5271 [0.4307, 0.6203] (Table I prints [0.433, 0.621] with the artifact's seed). L500–502 "retention from 0.527 to 0.960 ... and the 5.6-fold spread across question types collapsed" → 364/379 = 0.9604 [0.9310, 0.9839]; the spread on the 119 is 1.375× (0.727 differential-or-workup to 1.000 clinical-explainer), so "collapsed" can be replaced by "fell to 1.4-fold". Table I footnote "On the 119 answerable questions C3 retention is 0.513, 72 empty" → 160/312 = 0.5128; 72 reproduced. New: in the URL-first arm all 15 withheld claims are in the deep profile (standard 219/219 = 1.000, deep 145/160 = 0.906), i.e. every remaining withholding is a span-gate failure on LLM-extracted claims.

## 4. Answers with zero returned claims

proportion = #questions with claims_displayed = 0 / #questions; paired difference = proportion(URL-first) − proportion(shipped) on the same drawn questions; same bootstrap as §3.

| Scope | shipped | URL-first | difference URL-first − shipped |
|---|---|---|---|
| all 134 | 79/134 = 0.5896 [0.5075, 0.6716] | 25/134 = 0.1866 [0.1194, 0.2537] | −54 questions; −0.4030 [−0.4925, −0.3134] (SE 0.0438) |
| answerable 119 | 72/119 = 0.6050 [0.5210, 0.6891] | 23/119 = 0.1933 [0.1261, 0.2689] | −49; −0.4118 [−0.5042, −0.3193] |
| cross-tab (134) | zero in both 24; zero shipped only 55; zero URL-first only 1; claims in both 54 | | |

Paper: L471 "the number of answers carrying no returned claim rises from 29 to 79 of 134" and L501 "answers with no claim fell from 79 to 25" → reproduced, with the interval on the paired difference −0.403 [−0.493, −0.313] available to quote. Abstract L96/L98 (79 and 25) → reproduced.

## 5. Within-question comparison (paired on the same questions)

both-set = questions with ≥ 1 returned claim in BOTH arms: **54 questions** (URL-first-only 55, shipped-only 1, neither 24). On the both-set the two arms return almost the same number of claims (shipped 184, URL-first 185); the 55 URL-first-only questions carry 179 claims. Pooled difference = (Σ pos_UF / Σ n_UF) − (Σ pos_shipped / Σ n_shipped); mean per-question difference = mean_q [pos_UF(q)/n_UF(q) − pos_shipped(q)/n_shipped(q)]; both with the paired cluster bootstrap over the 54 questions (seed 0, 5,000 resamples).

### Primary pairing: shipped original labels vs URL-first matched labels

| Instrument | shipped on both-set | URL-first on both-set | pooled diff [CI] | mean per-q diff [CI] | signs UF>/</= | URL-first-only questions (179 claims) |
|---|---|---|---|---|---|---|
| support | 179/184 = 0.9728 | 178/185 = 0.9622 | −0.0107 [−0.0329, 0.0107] | −0.0123 [−0.0355, 0.0077] | 1 / 3 / 50 | 170/179 = 0.9497 (supported 170, overstated 1, not_supported 3, unintelligible 5) |
| responsiveness | 4/184 = 0.0217 | 7/185 = 0.0378 | +0.0161 [−0.0004, 0.0503] | +0.0139 [0.0000, 0.0417] | 1 / 0 / 53 | 6/179 = 0.0335 (relevant 6, partial 138, not_relevant 35) |

The shipped-only question has 1 claim: not_supported / not_relevant. All-134 paired pooled difference (the paper's convention, UF − shipped): support −0.0115 [−0.0367, 0.0142]; responsiveness +0.0141 [−0.0079, 0.0406].

### Secondary pairing: shipped pinned+rematch vs URL-first matched (the artifact's fully matched contrast, `claude-opus-5` both sides)

| Instrument | shipped both-set | URL-first both-set | pooled diff [CI] | mean per-q diff [CI] | all-134 pooled diff [CI] |
|---|---|---|---|---|---|
| support | 179/184 = 0.9728 | 178/185 = 0.9622 | −0.0107 [−0.0332, 0.0108] | −0.0139 [−0.0370, 0.0077] | −0.0115 [−0.0391, 0.0154] |
| responsiveness | 7/184 = 0.0380 | 7/185 = 0.0378 | −0.0002 [−0.0163, 0.0159] | 0.0000 [−0.0139, 0.0139] | −0.0021 [−0.0267, 0.0209] |

Reproduction of `arm_contrast_matched_v1.json` with the artifact's own seed (20260907) and percentile convention, sign shipped − URL-first: entailment [−0.0164, 0.0386] vs file [−0.0164, 0.0386]; relevance [−0.0198, 0.0265] vs file [−0.0198, 0.0265] — exact. Confounded pairing (both original label sets): all-134 support −0.0060 [−0.0298, 0.0195]; responsiveness +0.0059 [−0.0101, 0.0221]; on the both-set the responsiveness difference is −0.0001 [−0.0005, 0.0000] because the same 4 claims are `relevant` in both arms.

Paper: L508–514 "Matched, support is 0.968 against 0.956 and responsiveness 0.038 against 0.036. As intervals on the difference ...: 0.012 [−0.016, 0.039] and 0.002 [−0.020, 0.027]" → reproduced exactly. A within-question sentence that could be added: "On the 54 questions that return at least one claim in both arms, the arms return 184 and 185 claims; the paired difference in support is −0.011 [−0.033, 0.011] and in responsiveness −0.000 [−0.016, 0.016] under the matched judge. The 179 claims on the 55 questions that only the URL-first arm answers are supported at 0.950 and responsive at 0.034."

## 6. Minimum detectable difference for the responsiveness comparison

MDD = (z_{0.975} + z_{0.80}) × SE = (1.960 + 0.842) × SE = 2.80 × SE; SE = sample SD (ddof = 1) of the 5,000 paired-question bootstrap draws of the difference; relative = MDD / 0.036.

| Pairing | Bootstrap scope | SE | MDD (2.80 × SE) | MDD / 0.036 |
|---|---|---|---|---|
| primary (shipped original vs URL-first matched) | all 134 questions | 0.01227 | 0.0344 | 0.954 |
| primary | 54 both-set questions | 0.01616 | 0.0452 | 1.257 |
| artifact's matched contrast (pinned+rematch vs matched) | all 134 | 0.01194 | 0.0334 | 0.929 |
| artifact's matched contrast | 54 both-set | 0.00770 | 0.0216 | 0.599 |
| confounded (original vs original) | all 134 | 0.00817 | 0.0229 | 0.635 |
| support, primary / matched | all 134 | 0.01291 / 0.01396 | 0.0361 / 0.0391 | — |

Paper: L515–516 "No equivalence margin was pre-specified, so these bound the observed difference rather than establish equivalence." → can be strengthened with: "The bootstrap SE of the responsiveness difference is 0.012, so the smallest difference this comparison could detect with 80 % power at α = 0.05 is 0.033–0.034, about 0.93–0.95 of the 0.036 base rate; the design could only have detected a near-doubling or elimination of responsiveness."

## 7. Verifier verdicts (`metadata.verification_status`) × has returned claims

| Arm | verdicts | has claims | zero claims |
|---|---|---|---|
| shipped | pass 55, revise 79, block 0 | pass 38, revise 17 | pass 17, revise 62 |
| URL-first | pass 88, revise 45, block 1 | pass 76, revise 32, block 1 | pass 12, revise 13 |

Answerable 119 / controls 15: shipped pass 46 revise 73 / pass 9 revise 6; URL-first pass 80 revise 39 / pass 8 revise 6 block 1. The single `block` is `rivf_065` (an out-of-corpus control, study_result_numeric) which nevertheless displays 3 of 5 claims.

Paper: L527–528 "The fail-closed verifier blocked no answer in 134 questions (55 pass, 79 revise)." → true for the shipped arm only; in the URL-first arm the verifier returned pass 88, revise 45 and **block 1**, so the sentence should be scoped to the shipped arm. Also quotable: 17 shipped answers passed the verifier with zero returned claims and 17 were sent to revise despite carrying returned claims, so the verdict and the claim count are not redundant.

## 8. The "96.8 %" prior and the matched re-judge prompt

- `judging/JUDGE-CONFIGURATION.md` (line 80): "The shipped *relevance* codebook additionally told its judge that support was "already established at 96.8 % of cases" — a numeric prior from the other instrument, present in one arm only."
- `judging/relevance_prompt_v1.txt` (lines 6–7) and the `CODEBOOK` literal of `judging/relevance-judgement-shipped.js` (line 17), identical sentence: "A separate measurement already established that the cited passage SUPPORTS the claim in 96.8% of cases."
- The URL-first ORIGINAL codebook (`relevance-judgement-urlfirst.js`) instead reads "A separate measurement establishes whether the cited passage SUPPORTS the claim." and contains no "96.8".
- Byte check: `relevance_prompt_v1.txt` sha256 `d621532e5daea31f64ec49f96ee27a06a31f14aca4cbb1e988ebfc75db88bfed` (2755 bytes, LF) equals the hash recorded in `judge_rerun_comparison_v1.json → provenance.prompts_held_constant.relevance`. The file equals the shipped script's `CODEBOOK` template literal after stripping the literal's leading and trailing newline (sha256 of both stripped forms `1b123055907f…258f2f`); it is not byte-equal to the raw literal only because of those two outer newlines.
- Matched re-judge evidence: `matched-arm-rejudge.js` sets ``prompt: `${B}/judging/relevance_prompt_v1.txt` `` and tells each judge "First read this file in full and follow it exactly as your codebook. It is the whole of your instructions for how to label"; `arm_matched_rejudge_v1.json → result.codebook_source` = "judging/*_prompt_v1.txt, extracted byte-for-byte from the SHIPPED scripts". Therefore the URL-first MATCHED relevance labels were produced under a codebook that contains the 96.8 % prior — the prior was equalised across arms, not removed. Two things are not identical: delivery (shipped run inlined the codebook in the prompt; matched run had the judge read the file) and served model (shipped relevance `claude-fable-5-1`; matched re-judge `claude-opus-5`, per the JUDGE-CONFIGURATION table).

Paper: L509–510 "we re-judged the URL-first arm under the shipped arm's codebook byte for byte, served model, adjudicator prompt and batch size" → supported for the codebook text, with the delivery caveat; and the "served model" matched is that of the shipped *pinned re-run* (`claude-opus-5`), not of the shipped original relevance run (`claude-fable-5-1`).
