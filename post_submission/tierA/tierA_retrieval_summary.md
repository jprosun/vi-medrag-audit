# Tier A (retrieval shares, claim-level shares, duplication, RQ1 bounds)

Source of every number: `tierA_analysis.py` run over the released artifact; printed values are in
`tierA_retrieval_run.log`, machine-readable values in `tierA_retrieval_results.json`. No artifact
script was executed. Line numbers refer to `paper/main.tex`.

Conventions. URL-less stratum = `metadata.source_id == "hf_vi_mtue29_medical"`. Bootstrap = percentile
cluster bootstrap over questions, 5,000 resamples, `numpy.random.default_rng(0)` fresh per group,
ratio of sums recomputed inside each resample, CI = 2.5th / 97.5th percentiles. Issue-level URL regex
copied from the artifact's `corpus_census.py`: `/issue/(view|archive)/`. The 67/67 standard/deep
split is `metadata.pipeline.retrieval_profile` (`metadata.answer_mode` is `standard` for all 134
records in both arms).

## 1. Sanity (shipped arm)

| Quantity | Value | Paper sentence |
|---|---|---|
| retrieved chunks, 134 questions | 4024 | L293 "supplied \num{2472} of \num{4024} retrieved chunks, 61.4%" — reproduced |
| chunks from URL-less stratum | 2472 | same |
| share = 2472/4024 | 0.6143 | same; abstract L94 "supplies 61.4% of what retrieval returns" |
| chunks with empty `source_url` | 2472; 0 outside the stratum | L295 "Every retrieved chunk lacking a source URL came from it" — reproduced |
| chunks per answer | min 22, max 57 | L209 "the answers carry 22–57 retrieved chunks each, 4024 in all" — reproduced |
| `pipeline.retrieval_profile` | standard 67 (top_k 12, extractor unused), deep 67 (top_k 20, extractor used) | L205–208 "67 ran a standard profile ... 67 a deep profile ... top-k 12 against 20" — reproduced |
| URL-first arm | 3947 retrieved chunks, 0 from URL-less stratum, 0 with empty URL, 20–54 per answer | supports L497–503 (URL-first design); no retrieved-chunk count is stated in the paper for this arm |

## 2. URL-less stratum share of retrieved chunks, by question type and by profile (shipped)

Formula: share_G = sum_{q in G} urlless_q / sum_{q in G} n_q.

| Group (controls separate) | n questions | urlless / total | share | 95% CI |
|---|---|---|---|---|
| all 134 | 134 | 2472 / 4024 | 0.6143 | [0.5688, 0.6598] |
| answerable 119 | 119 | 2244 / 3588 | 0.6254 | [0.5765, 0.6733] |
| clinical_explainer | 24 | 425 / 584 | 0.7277 | [0.6087, 0.8294] |
| study_result_numeric | 24 | 305 / 707 | 0.4314 | [0.3314, 0.5424] |
| guideline_comparison | 24 | 390 / 790 | 0.4937 | [0.4233, 0.5709] |
| patient_faq | 23 | 574 / 648 | 0.8858 | [0.8167, 0.9507] |
| differential_or_workup | 24 | 550 / 859 | 0.6403 | [0.5624, 0.7133] |
| out_of_corpus_control | 15 | 228 / 436 | 0.5229 | [0.4087, 0.6441] |

Same by question type with the controls folded into their type (controls carry a type too: 5 clinical_explainer, 4 study_result_numeric, 3 patient_faq, 2 guideline_comparison, 1 differential_or_workup):
clinical_explainer 29 q 502/729 = 0.6886 [0.5871, 0.7818]; study_result_numeric 28 q 358/816 = 0.4387 [0.3394, 0.5437]; guideline_comparison 26 q 410/848 = 0.4835 [0.4165, 0.5557]; patient_faq 26 q 635/729 = 0.8711 [0.8034, 0.9357]; differential_or_workup 25 q 567/902 = 0.6286 [0.549, 0.7016].

| Profile | n | urlless / total | share | 95% CI | mean chunks / answer |
|---|---|---|---|---|---|
| deep | 67 | 1404 / 2222 | 0.6319 | [0.5746, 0.6886] | 33.1642 |
| standard | 67 | 1068 / 1802 | 0.5927 | [0.5228, 0.6687] | 26.8955 |

Profile x group counts (no CI, cells small): deep|differential_or_workup 24 q 550/859 = 0.6403; deep|guideline_comparison 17 q 273/610 = 0.4475; deep|out_of_corpus_control 6 q 95/181 = 0.5249; deep|patient_faq 19 q 479/543 = 0.8821; deep|study_result_numeric 1 q 7/29 = 0.2414; standard|clinical_explainer 24 q 425/584 = 0.7277; standard|guideline_comparison 7 q 117/180 = 0.65; standard|out_of_corpus_control 9 q 133/255 = 0.5216; standard|patient_faq 4 q 95/105 = 0.9048; standard|study_result_numeric 23 q 298/678 = 0.4395. The router's profile is almost a function of question type (all 24 clinical_explainer are standard, all 24 differential_or_workup are deep), so profile and type are confounded in this sweep.

Paper sentences these support/replace: L293–294 (the 61.4% headline gets a CI: 0.614 [0.569, 0.660]); L472–475 "retention by question type runs from 0.122 for patient-FAQ questions to 0.687 for guideline-comparison" — the retrieval-side mechanism behind that spread is the stratum share, 0.886 for patient_faq vs 0.494 for guideline_comparison and 0.431 for study_result_numeric; probe README's claim that "a question phrased as a patient FAQ pulls patient-education chunks" is confirmed quantitatively.

URL-first arm, retrieved chunks by source stratum (total 3947): vmj_ojs 2487 (0.6301), cantho_med_journal 773 (0.1958), mil_med_pharm_journal 244 (0.0618), dav_gov 122 (0.0309), hue_jmp_ojs 117 (0.0296), vien_dinh_duong 93 (0.0236), trad_med_pharm_journal 55 (0.0139), kcb_moh 19 (0.0048), mayo_diseases_conditions 11 (0.0028), hf_medquad 6 (0.0015), nci_pdq 6 (0.0015), ncbi_bookshelf 5 (0.0013), nhs_health_a_z 3 (0.0008), who 3 (0.0008), uspstf_recommendations 2 (0.0005), msd_manual_professional 1 (0.0003). By profile: deep 2150, standard 1797. Supports L498–503 ("retrieval refilled rather than returning less"): the seats go overwhelmingly to the two largest journals; issue-level-only strata (cantho, mil, hue, trad) take 773+244+117+55 = 1189 chunks, 0.3012 of the URL-first pool (Section 7).

## 3. Language-matched lift

Census `language` field sums to 595663 = total, so it is complete: vi 471225, en 109239, es 14293, mixed 906.

| Quantity | Formula | Value |
|---|---|---|
| corpus share of URL-less stratum, all chunks | 256415 / 595663 | 0.4305 |
| corpus share of URL-less stratum among Vietnamese chunks | 256415 / 471225 | 0.5441 |
| retrieved Vietnamese chunks (shipped) | language == vi | 3918 of 4024 (en 106) |
| retrieved share of URL-less stratum among Vietnamese retrieved | 2472 / 3918 | 0.6309 [0.5848, 0.6774] |
| raw lift | (2472/4024) / (256415/595663) | 1.4271 [1.3213, 1.5326] |
| language-matched lift | (2472/3918) / (256415/471225) | 1.1595 [1.0748, 1.2448] |

(Lift CIs: bootstrap over questions with the corpus denominator held fixed.)

Replaces/qualifies L292–298 ("The untraceable stratum wins retrieval ... Its share of what is retrieved exceeds its share of the index"): the 1.43x raw lift is 1.16x once the comparison is restricted to Vietnamese-language chunks on both sides; the CI excludes 1 but most of the raw lift is the language filter, not a preference for the stratum among Vietnamese material.

"English reference material fell from 16.7% of the index to 0.3% of what was retrieved" (L294–295): no derivation exists in the artifact. Candidate definitions, index share -> retrieved share:
A language==en, all strata: 109239 (0.1834) -> 106 (0.0263);
B 14 English-majority strata, all chunks: 111782 (0.1877) -> 36 (0.0089);
C English-majority strata excluding vien_dinh_duong: 109237 (0.1834) -> 11 (0.0027);
D language==en within "Reference and other" strata: 98538 (0.1654) -> 105 (0.0261);
E "Reference and other" strata, all chunks: 127345 (0.2138) -> 110 (0.0273);
F language==en within English-majority strata: 96475 (0.1620) -> 36 (0.0089).
No single definition gives both 16.7% and 0.3%; C reproduces the 0.3% retrieved and D/F come closest to 16.7% at the index. The sentence should be rewritten with one explicit definition, e.g. definition B: "the fourteen English-language strata fell from 18.8% of the index to 0.9% of what was retrieved (36 of 4024 chunks)".

## 4. Retrieved share by stratum vs index share (shipped arm, 4024 chunks)

| stratum | index chunks | index share | retrieved | retrieved share | lift | URL granularity |
|---|---|---|---|---|---|---|
| hf_vi_mtue29_medical | 256415 | 43.05% | 2472 | 61.43% | 1.427 | none |
| vmj_ojs | 132225 | 22.20% | 997 | 24.78% | 1.116 | article |
| cantho_med_journal | 45804 | 7.69% | 298 | 7.41% | 0.963 | issue |
| nci_pdq | 35763 | 6.00% | 0 | 0.00% | 0.000 | article |
| hf_medquad | 34400 | 5.78% | 2 | 0.05% | 0.009 | article |
| mil_med_pharm_journal | 19810 | 3.33% | 88 | 2.19% | 0.658 | issue |
| who_vietnam | 19617 | 3.29% | 0 | 0.00% | 0.000 | article |
| hue_jmp_ojs | 9132 | 1.53% | 39 | 0.97% | 0.632 | issue |
| kcb_moh | 8043 | 1.35% | 13 | 0.32% | 0.239 | article |
| dav_gov | 7520 | 1.26% | 61 | 1.52% | 1.201 | article |
| trad_med_pharm_journal | 4932 | 0.83% | 20 | 0.50% | 0.600 | issue |
| ncbi_bookshelf | 3449 | 0.58% | 0 | 0.00% | 0.000 | article |
| msd_manual_professional | 3366 | 0.57% | 0 | 0.00% | 0.000 | article |
| msd_manual_consumer | 3061 | 0.51% | 0 | 0.00% | 0.000 | article |
| nhs_health_a_z | 2958 | 0.50% | 2 | 0.05% | 0.100 | article |
| vien_dinh_duong | 2545 | 0.43% | 25 | 0.62% | 1.454 | article |
| mayo_diseases_conditions | 2376 | 0.40% | 7 | 0.17% | 0.436 | article |
| nccih_health | 2028 | 0.34% | 0 | 0.00% | 0.000 | article |
| uspstf_recommendations | 776 | 0.13% | 0 | 0.00% | 0.000 | article |
| who | 766 | 0.13% | 0 | 0.00% | 0.000 | article |
| medlineplus | 636 | 0.11% | 0 | 0.00% | 0.000 | article |
| cdc_health_topics | 41 | 0.01% | 0 | 0.00% | 0.000 | article |

Retrieved source x language (shipped): hf_vi_mtue29_medical/vi 2472; vmj_ojs/vi 996, en 1; cantho/vi 298; mil/vi 88; dav_gov/en 58, vi 3; hue/vi 39; vien_dinh_duong/en 25; trad/vi 20; kcb_moh/en 11, vi 2; mayo/en 7; hf_medquad/en 2; nhs/en 2.

Supports L293–298 and Table I (L358–375): the two Vietnamese strata with lift > 1 are the URL-less stratum (1.43) and VMJ (1.12); every English-language stratum is at or near zero. Ten of 22 strata were never retrieved.

## 5. Claim level (claim_attributions + dropped_claims over all 134 records)

Shipped arm:

| Quantity | Value | Paper sentence |
|---|---|---|
| total claims | 351 (185 returned + 166 dropped) | L112, L388, Table II C0 — reproduced |
| claims with empty `source_url` | 156 | L112–113 "156 ... uncitable" — reproduced |
| claims with empty `chunk_id` | 2 (both also have empty URL) | L113 "two naming no record at all" — reproduced |
| empty URL with a non-empty chunk_id (URL-less record cited) | 154 | L112 "154 citing a record that carries no source URL" — reproduced |
| the 154 resolve to a retrieved chunk in the URL-less stratum | 154 of 154 (0 other stratum, 0 unresolved) | L296 "it supplied 154 of the 156 uncitable claims" — reproduced |
| URL-less share of all claims | 154/351 = 0.4387 | L486–488 "44.4% overall" uses 156/351 = 0.4444 (uncitable incl. the 2 empty-id claims); state which numerator is meant |
| drop reasons | cited_record_not_citable 147, span_not_found_in_cited_chunk 17, chunk_id_not_resolvable 2 | L466–467 "19 failures ... citability withholds 147 of the 166" — reproduced (17 + 2 = 19) |
| answers with zero returned claims | 79 | L469 "rises from 29 to 79 of 134" — reproduced |

By question type (shipped; share = URL-less claims / all claims in the group, CI = cluster bootstrap over questions):

| group | claims | URL-less | share | 95% CI | uncitable (incl. empty id) |
|---|---|---|---|---|---|
| clinical_explainer | 82 | 26 | 0.3171 | [0.1333, 0.519] | 26 |
| study_result_numeric | 70 | 43 | 0.6143 | [0.4085, 0.7917] | 43 |
| guideline_comparison | 83 | 21 | 0.253 | [0.093, 0.4444] | 21 |
| patient_faq | 49 | 43 | 0.8776 | [0.6923, 1.0] | 43 |
| differential_or_workup | 28 | 9 | 0.3214 | [0.0, 0.6429] | 10 |
| out_of_corpus_control | 39 | 12 | 0.3077 | [0.0732, 0.6] | 13 |

Supports L472–475 (retention 0.122 patient-FAQ vs 0.687 guideline-comparison): the claim-level URL-less share is 0.878 vs 0.253. Note the ordering differs from the retrieval-side share in Section 2 for clinical_explainer (0.728 of retrieved chunks but only 0.317 of claims URL-less) and study_result_numeric (0.431 of chunks, 0.614 of claims): the extractor does not cite the stratum in proportion to its presence in the pool.

By profile (shipped): standard 67 q, 208 claims, 107 returned, 101 URL-less (0.4856), 0 empty chunk_id; deep 67 q, 143 claims, 78 returned, 53 URL-less (0.3706), 2 empty chunk_id. Reproduces L207 "The no-extractor half produced the majority of claims, 208 of 351".

URL-first arm: 379 claims (364 returned + 15 dropped); empty `source_url` 1, empty `chunk_id` 1 (the same claim), URL-less record cited 0; drop reasons span_not_found_in_cited_chunk 14, chunk_id_not_resolvable 1; 25 answers with zero returned claims. By group: clinical_explainer 85, study_result_numeric 72, guideline_comparison 92, patient_faq 63, differential_or_workup 22 (1 uncitable), controls 45. By profile: standard 219 claims / 219 returned, deep 160 / 145. Reproduces L498–503 (185 -> 364 returned, 351 -> 379 extracted, 79 -> 25 empty) and L515 (41 claims on controls).

## 6. Duplication in the URL-less stratum as retrieved (shipped)

| Quantity | Value |
|---|---|
| URL-less retrieved chunks | 2472 |
| distinct sha256 among them | 2371 |
| mean copies per distinct sha256 | 2472/2371 = 1.0426 |
| distinct chunk ids among them | 2400 (29 more ids than texts: identical text under different ids) |
| sha256 values seen more than once across the sweep | 95 (max 3 copies) |
| answers in which the same URL-less sha256 appears more than once | 4 of 134 (11 extra occurrences in total) |
| answers in which any sha256 repeats within the answer | 5 of 134 |
| all 4024 retrieved chunks | 3841 distinct sha256, mean copies 1.0476 |
| per stratum (retrieved / distinct / mean copies) | hf 2472/2371/1.043; vmj 997/970/1.028; cantho 298/292/1.021; mil 88/83/1.060; dav_gov 61/35/1.743; hue 39/39/1.000; vdd 25/23/1.087; trad 20/14/1.429; kcb 13/5/2.600; mayo 7/5/1.400; hf_medquad 2/2; nhs 2/2 |
| URL-less claims (154): distinct claim strings after whitespace normalisation | 148 (148 also after NFC + casefold); 4 strings occur more than once, max 3 repeats |
| all 351 claims: distinct after whitespace normalisation | 341 |

Interpretation for the paper: the 2472 figure is not inflated by repeated retrieval of a few duplicated chunks — within-answer repeats touch 4 answers and 11 chunk slots (0.4% of 2472), and 95.9% of the URL-less chunks are distinct texts. This supports the use of 2472/4024 as a count of distinct evidence in L293 and defends against the objection that the 37.4% exact-duplicate rate reported for the journal stratum (L337–340) might also drive the URL-less share. The 29 chunk-ids-with-identical-text is the only duplication signal inside the retrieved URL-less stratum and could be stated in the deduplication paragraph.

## 7. RQ1 bounds (census + URL audit)

Census arithmetic (no estimator): article-level 259570 + issue-level 79678 + none 256415 = 595663.

| Bound | Formula | Value | Paper sentence |
|---|---|---|---|
| stored any-URL share | 339248/595663 | 0.5695 | abstract L91 "43.1% carry no source URL" (1 - 0.4305) |
| stored article-level share | 259570/595663 | 0.4358 | Table I total row "43.6%" — reproduced |
| stored issue-level share | 79678/595663 | 0.1338 | Table I "13.4%" — reproduced |
| hosts with every measurable probe failing | nihseniorhealth.gov 1869, rarediseases.info.nih.gov 11300, www.niddk.nih.gov 2876 = 16045 chunks; all hf_medquad, all article_or_page granularity | L320–321 "three hosts holding 2880 URLs behind 16045 chunks" — chunk total reproduced; stratum identified as MedQuAD |
| hosts refused by robots.txt | cdn.who.int 20, www.emro.who.int 105, www.mayoclinic.org 2376, www.ninds.nih.gov 1462, www.who.int 20246 = 24209 chunks; by stratum who_vietnam 19605, mayo 2376, hf_medquad 1462, who 766; all article_or_page | L310 "refused five hosts covering 24209 chunks" — reproduced; strata identified |
| partial-failure host | www.cdc.gov 7 of 8 reached | not in paper |
| article-level share minus failed hosts | (259570 - 16045)/595663 | 0.4088 | new: lower bound after the only hosts observed dead |
| article-level share minus failed + robots hosts | (259570 - 16045 - 24209)/595663 | 0.3682 | new: lower bound treating unmeasurable as unavailable |
| any-URL share minus failed; minus failed + robots | (339248-16045)/595663; (339248-16045-24209)/595663 | 0.5426; 0.5020 | new |

Retrieval level (shipped, 4024 chunks):

| Quantity | Value | 95% CI | Paper sentence |
|---|---|---|---|
| chunks carrying any URL | 1552/4024 = 0.3857 | [0.3402, 0.4312] | complement of L293 (61.4% URL-less) |
| chunks carrying an issue-pattern URL | 445/4024 = 0.1106 | — | new: retrieval-level analogue of Table I's 13.4% |
| chunks carrying a non-issue (article-level) URL | 1107/4024 = 0.2751 | [0.2399, 0.3103] | new: at serving time only 27.5% of what retrieval returns could carry an article-level citation, vs 43.6% of the index |
| URL host among failed hosts / robots hosts / partial host | 2 / 7 / 0 | — | new |
| article-level minus failed + robots hosts | 1098/4024 = 0.2729 | — | new |

URL-first arm: 3947/3947 chunks carry a URL (1.0000); issue-pattern 1189 (0.3012); article-level 2758 (0.6988). New: under the URL-first design 30.1% of retrieved chunks carry an issue-level locator that resolves to a table of contents (Section 7 census: 142 of 143 such URLs), so "citable" in that arm is not "article-locatable" for nearly a third of the pool.

Reachability, chunk-weighted, as recorded in the artifact (not recomputed):

| Sample | n | point (Hajek) | HT | marginal projection | Bonferroni joint | Paper sentence |
|---|---|---|---|---|---|---|
| frozen primary | 289 | 0.955 | 1.0047 | [0.7789, 0.9688] | [0.6935, 0.9744] | L318–323: paper reports 0.95 and 0.72–0.97, which are the adaptive values below; the frozen-only figures should be stated separately |
| all probes incl. adaptive top-up | 367 | 0.9486 | 0.9365 | [0.8106, 0.961] | [0.7236, 0.9687] | L322–323 "0.95 ... 0.72–0.97" — reproduced (rounded) |
| confirmatory PPS | 174 | 0.9321 (design-based, CI [0.9312, 0.9331]) | — | per-host envelope 0.973 [0.6521, 0.9864] | — | L329–331 "0.93 ... no matching interval" — reproduced; the envelope exists in the artifact and could be cited as the honest interval |

robots.txt unmeasurable: 1361 URLs, 24209 chunks (excluded from every denominator). Issue census: 143 URLs, 79678 chunks, 143 answered, 142 landed on an issue index (L312–316 reproduced).

Bound ladder for RQ1 (share of the index that can support a citation a reader can open): stored any URL 0.5695 -> stored article-level 0.4358 -> minus hosts observed dead 0.4088 -> minus robots-refused as well 0.3682. Multiplicative alternatives (article-level share x reachability point): x adaptive 0.9486 = 0.4134; x frozen 0.955 = 0.4162; x confirmatory 0.9321 = 0.4062; x adaptive Bonferroni bounds [0.7236, 0.9687] = [0.3153, 0.4221]. Proposed replacement for the RQ1 answer in Section IV / conclusion: "between 0.37 and 0.44 of the index carries an article-level locator that was not observed dead; the stored article-level share is 0.436, 0.409 after removing the three NIH hosts on which every probe failed, and 0.368 if the five robots-refused hosts are also excluded."

## Discrepancies and items that cannot be computed

1. L294–295 "English reference material 16.7% -> 0.3%": not derivable from the census file under any definition tried (Section 3); needs a definition and, with it, 18.3%/18.8% -> 2.6%/0.9% (or 0.3% under definition C only).
2. L486–488 "44.4% overall" is 156/351 (uncitable incl. the 2 empty-chunk-id claims), while the surrounding text defines the comparison as "cite a URL-less record"; 154/351 = 43.9%.
3. The task's "by answer_mode (standard/deep)" field: `metadata.answer_mode` is constant; the split is `metadata.pipeline.retrieval_profile`, and it is confounded with question type (Section 2).
4. 2880 URLs on the three failed hosts (L321) was not recomputed here (per-host URL counts are in `url_audit_report_v1.json → by_host`, not re-summed by this script).
5. The frozen-sample reachability interval is reported separately above; the paper's 0.95 / 0.72–0.97 are the adaptive values.
