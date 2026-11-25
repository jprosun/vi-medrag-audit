"""Every number in the paper, checked against the artifact that produced it.

The paper's own rule is that a number without an artifact and a commit does not enter it.
This is what enforces the rule: an assertion per printed figure, joining it to the JSON it came
from, plus the structural checks a missing TeX toolchain cannot do for us -- unresolved
references, duplicate labels, orphaned citations, control characters, dashes broken across
lines, and wording the review retired.

It does NOT check the page count; nothing here can, without a compiler. See
paper/estimate_pages.py for a word model of that, and its own warning about it.

Exit code 0 when everything agrees, 1 otherwise, so it can gate a commit.

    python paper/check_numbers.py
"""
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
tex = (REPO / "paper/main.tex").read_text(encoding="utf-8")
bib = (REPO / "paper/refs.bib").read_text(encoding="utf-8")
B = REPO / "benchmark/rivf"
TR = REPO / "benchmark/datasets/test_results"

facts = json.loads((B / "attribution_facts_rivf134.json").read_text(encoding="utf-8"))
arms = json.loads((B / "arm_comparison_rivf134.json").read_text(encoding="utf-8"))
ent_s = json.loads((B / "entailment_report_v1.json").read_text(encoding="utf-8"))
ent_h = json.loads((B / "entailment_human_v1.json").read_text(encoding="utf-8"))
rel_h = json.loads((B / "relevance_human_v1.json").read_text(encoding="utf-8"))
ent_u = json.loads((B / "entailment_report_urlfirst_v1.json").read_text(encoding="utf-8"))
rel_s = json.loads((B / "relevance_report_v1.json").read_text(encoding="utf-8"))
rel_u = json.loads((B / "relevance_report_urlfirst_v1.json").read_text(encoding="utf-8"))
census = json.loads((TR / "corpus_census_medqa_release_v4_all_bge_m3.json").read_text(encoding="utf-8"))
deref = json.loads((B / "url_audit_report_v1.json").read_text(encoding="utf-8"))
ptype = json.loads((B / "page_type_v1.json").read_text(encoding="utf-8"))
conf = json.loads((B / "url_confirmatory_estimate_v1.json").read_text(encoding="utf-8"))
jrr = json.loads((B / "judge_rerun_comparison_v1.json").read_text(encoding="utf-8"))
jprov = json.loads((B / "judge_model_provenance_v1.json").read_text(encoding="utf-8"))
rel_hu = json.loads((B / "relevance_human_urlfirst_v1.json").read_text(encoding="utf-8"))
arm = json.loads((B / "arm_contrast_matched_v1.json").read_text(encoding="utf-8"))
joint = json.loads((B / "joint_support_relevance_v1.json").read_text(encoding="utf-8"))
runcfg = json.loads((B / "run_configuration_v1.json").read_text(encoding="utf-8"))
pprov = json.loads((B / "probe_authoring_provenance_v1.json").read_text(encoding="utf-8"))
tb_deref = json.loads((REPO / "post_submission/tierB/deref_stats.json").read_text(encoding="utf-8"))
tb_judge = json.loads((REPO / "post_submission/tierB/judge_stats.json").read_text(encoding="utf-8"))
tb_cross = json.loads((REPO / "post_submission/tierB/crossmodel_stats.json").read_text(encoding="utf-8"))
tb_strat = json.loads((REPO / "post_submission/tierB/stratify_v4.json").read_text(encoding="utf-8"))
tb_prov = json.loads((REPO / "post_submission/tierB/judge_provenance.json").read_text(encoding="utf-8"))
tc_rec = json.loads((REPO / "post_submission/tierC/claims_on_recovered_pages.json").read_text(encoding="utf-8"))
_rc = runcfg["arms"]["shipped"]["settings"]
_jm, _ju = joint["arms"]["shipped_matched"], joint["arms"]["url_first_matched"]
_ae, _ar = arm["instruments"]["entailment"], arm["instruments"]["relevance"]
_je, _jr = jrr["instruments"]["entailment"], jrr["instruments"]["relevance"]
_dead = [r for r in deref["by_host"] if r["measurable"] and r["reachability"] == 0.0]
_rare = [r for r in deref["by_host"] if r["host"] == "rarediseases.info.nih.gov"][0]
_locators = sum(v for k, v in deref["1_stored_locator_availability"]["chunks_by_granularity"].items() if k != "none")
_allchunks = sum(deref["1_stored_locator_availability"]["chunks_by_granularity"].values())

A, U = arms["all_questions"]["shipped"], arms["all_questions"]["url_first"]
body = re.sub(r"(?m)^%.*$", "", tex)

checks = {
    # audit
    "595663 chunks": ("595663", census["points_scrolled"] == 595663),
    "43.05 % no URL": ("43.05", round(census["totals"]["share_with_no_source_url"] * 100, 2) == 43.05),
    "256415": ("256415", census["totals"]["chunks_with_no_source_url"] == 256415),
    "13.4 % issue-only": ("13.4", round(census["totals"]["share_with_issue_level_url_only"] * 100, 1) == 13.4),
    "61.4 % of retrieval": ("61.4", round(A["retrieved_from_excluded_stratum"] / A["retrieved_chunks"] * 100, 1) == 61.4),
    "2472 of 4024": ("2472", A["retrieved_from_excluded_stratum"] == 2472 and A["retrieved_chunks"] == 4024),
    # This used to assert only that the TOTAL was 156, so the sentence's actual content --
    # that the URL-less stratum supplied 154 of them -- went unchecked. Now both halves are
    # read off the recomputation, which groups each uncitable claim by the stratum it cites.
    "154 from the stratum": ("154", facts["claims"]["uncitable_by_stratum_of_the_cited_chunk"]["hf_vi_mtue29_medical"] == 154),
    "156 uncitable in all": ("156", facts["claims"]["uncitable_over_every_claim_no_gate_arm"] == 156),
    "the other two do not resolve": ("two", facts["claims"]["uncitable_by_stratum_of_the_cited_chunk"]["chunk_id_not_in_retrieved_set"] == 2),
    # Article-level is the residual of the two the census counts directly, so this is read
    # off the census's own totals rather than assembled from named strata.
    "43.6 % article-level": (
        "43.6",
        round((census["points_scrolled"]
               - census["totals"]["chunks_with_no_source_url"]
               - census["totals"]["chunks_with_issue_level_url_only"])
              / census["points_scrolled"] * 100, 1) == 43.6,
    ),
    # the dereference audit. The corpus-level composite was WITHDRAWN 2026-09-08: it rested
    # on a destination test that only checks the final URL against known issue-index patterns
    # and on a chunk-weighted estimator this sample cannot stabilise (Horvitz-Thompson
    # returned a rate above one). What is asserted here is the census, which needs neither.
    "143 issue URLs censused": ("143", deref["THE_RESULT_THAT_NEEDS_NO_ESTIMATOR"]["distinct_issue_urls"] == 143),
    "142 land on an index": ("142", deref["THE_RESULT_THAT_NEEDS_NO_ESTIMATOR"]["landed_on_an_issue_index"] == 142),
    "79678 chunks behind them": ("79678", deref["THE_RESULT_THAT_NEEDS_NO_ESTIMATOR"]["chunks_behind_them"] == 79678),
    "557 chunks per issue URL": ("557", round(deref["THE_RESULT_THAT_NEEDS_NO_ESTIMATOR"]["chunks_per_url"]) == 557),
    "367 probed": ("367", sum(r["selected"] for r in deref["by_host"]) == 367),
    "289 frozen before any request": ("289", deref["provenance"]["primary_sample"]["n"] == 289),
    "78 added afterwards": ("78", deref["provenance"]["adaptive_topup"]["n"] == 78),
    "the top-up is NOT frozen": ("exploratory", deref["provenance"]["adaptive_topup"]["frozen_before_any_request"] is False),
    "19 of 19 on the dead host": (
        "19",
        [r for r in deref["by_host"] if r["host"] == "rarediseases.info.nih.gov"][0]["reached_2xx"] == 0,
    ),
    "16 probes on the two smaller dead hosts": (
        "16",
        sum(r["measurable"] for r in deref["by_host"]
            if r["measurable"] and r["reachability"] == 0.0 and r["host"] != "rarediseases.info.nih.gov") == 16,
    ),
    "2880 dead URLs": ("2880", sum(r["population_urls"] for r in deref["by_host"] if r["measurable"] and r["reachability"] == 0.0) == 2880),
    "16045 dead chunks": ("16045", sum(r["population_chunks"] for r in deref["by_host"] if r["measurable"] and r["reachability"] == 0.0) == 16045),
    "0.95 reachability": ("0.95", round(deref["2_http_reachability_by_chunks"]["all_probes_including_adaptive_topup"]["point"], 2) == 0.95),
    "reachability joint interval 0.72-0.97": (
        "0.72",
        [round(x, 2) for x in deref["2_http_reachability_by_chunks"]["all_probes_including_adaptive_topup"]["bonferroni_joint"]] == [0.72, 0.97],
    ),
    "24209 chunks unmeasurable": ("24209", deref["unmeasurable_by_robots_txt"]["chunks"] == 24209),
    "five hosts blocked": ("five", sum(1 for r in deref["by_host"] if r["measurable"] == 0) == 5),
    # the estimator that showed the sample cannot carry a chunk-weighted composite
    "HT returns a rate above one": (
        "exceeds one",
        deref["2_http_reachability_by_chunks"]["primary_frozen_sample"]["point_horvitz_thompson"] > 1.0,
    ),
    # the author's blind page-type labelling, which validated the destination test
    "40 pages labelled": ("40", sum(ptype["headline"]["page_types"].values()) == 40),
    "agreed on 39": (
        "39",
        sum(ptype["headline"]["page_types"].values()) - len(ptype["the_regex_under_test"]["misses"]) == 39,
    ),
    "no homepage, search or soft 404": (
        "destination test",
        ptype["headline"]["share_the_regex_cannot_see_WEIGHTED_TO_THE_PROBE_POOL"]["post_stratified"] == 0.0,
    ),
    "zero landed on a different document": (
        "document",
        ptype["is_it_the_cited_document"]["among_document_pages"].get("different_document", 0) == 0,
    ),
    # the confirmatory PPS sample
    "0.93 confirmatory reachability": (
        "0.93",
        round(conf["2_http_reachability_chunk_weighted"]["design_based"]["point"], 2) == 0.93,
    ),
    # The per-host envelope is no longer printed: it weights within-host proportions
    # unadjusted and carries its own point of 0.973, so it is a different estimand from the
    # w/pi-weighted 0.93 and was never an interval for it. Asserted in the artifact only.
    "the envelope is a different estimand from the point": (
        "0.93",
        [round(x, 2) for x in conf["2_http_reachability_chunk_weighted"]["exact_envelope_per_host"]["envelope"]] == [0.65, 0.99],
    ),
    # the judge re-run: what part of a headline rate belongs to the judge, and what the
    # recovered provenance says the re-run actually varied
    "the recovered judge models": (
        "transcript",
        jprov["runs"]["entailment_shipped"]["model_id"] == "claude-opus-5"
        and jprov["runs"]["relevance_shipped"]["model_id"] == "claude-fable-5-1"
        and jprov["runs"]["entailment_urlfirst"]["model_id"] == "claude-fable-5-1"
        and jprov["runs"]["pinned_rerun"]["model_id"] == "claude-opus-5",
    ),
    "every recovered label matches its artifact": (
        "100",
        all(r["label_crosscheck"]["fraction"] == 1.0 for r in jprov["runs"].values()),
    ),
    "entailment was NOT a cross-model comparison": (
        "repeatability",
        _je["comparison_type"] == "within-model repeatability",
    ),
    "relevance WAS a cross-model comparison": ("crossed models", _jr["comparison_type"] == "cross-model"),
    "entailment survives re-judging": (
        "0.968",
        _je["quote_these"]["headline_rate_original"]["rate"]
        == _je["quote_these"]["headline_rate_rerun"]["rate"] == 0.9676,
    ),
    # on the 185 REAL claims, not the 222 that include 37 easy-negative controls
    "entailment agreement 98.9 on real claims": (
        "98.9",
        round(_je["quote_these"]["stability_on_real_claims"]["agreement"] * 100, 1) == 98.9,
    ),
    "entailment kappa on real claims": (
        "0.85",
        round(_je["quote_these"]["stability_on_real_claims"]["agreement"] * 100, 1) == 98.9,
    ),
    "relevance does not: 0.022 -> 0.038": (
        "0.038",
        _jr["quote_these"]["headline_rate_original"]["rate"] == 0.0216
        and _jr["quote_these"]["headline_rate_rerun"]["rate"] == 0.0378,
    ),
    "11 real claims went unrelated -> partial": (
        "11",
        _jr["transitions_real_claims"].get("not_relevant|partial") == 11,
    ),
    "and one CONTROL did the same": (
        "36",
        _jr["transitions_controls"].get("not_relevant|partial") == 1
        and _jr["control_gate"]["held_the_expected_label_rerun"] == 36
        and _jr["control_gate"]["avoided_the_positive_label_rerun"] == 37,
    ),
    "3 partial became answering": ("3", _jr["transitions_real_claims"].get("partial|relevant") == 3),
    "at most 5 of 15 changes are the adjudicator": (
        "5",
        _jr["adjudicator_confound"]["labels_that_changed"] == 15
        and _jr["adjudicator_confound"]["of_those_that_passed_through_either_adjudicator"] == 5,
    ),
    # From COUNTS. Dividing rounded rates gave 2.7; 3/185 over (10/364 - 4/185) is 2.77.
    # `relevant_rate_ci` is [point, lower, upper], so index 0 is the estimate.
    "the judge shift is 2.8x the arm gap": (
        "2.8",
        round((7 / 185 - 4 / 185) / (10 / 364 - 4 / 185), 1) == 2.8
        and _jr["quote_these"]["headline_rate_rerun"]["hits"] == 7
        and _jr["quote_these"]["headline_rate_original"]["hits"] == 4
        and rel_u["headline"]["label_distribution"]["relevant"]["n"] == 10,
    ),
    "three estimates of responsiveness": (
        "0.028",
        rel_h["human_relevant_rate"]["post_stratified_to_the_185"] == 0.0284,
    ),
    # the arm contrast with the instrument held fixed: shipped codebook byte for byte, model
    # pinned, original adjudicator prompt, batch size 28, and the shipped side re-adjudicated
    # under that same prompt. Intervals are on the DIFFERENCE (Newcombe hybrid score).
    "the matched run witnessed its own model": (
        "claude-opus-5",
        arm["model_id_witnessed"]["model_id"] == "claude-opus-5"
        and arm["model_alias_requested"] == "opus",
    ),
    "both sides re-adjudicated alike": (
        "adjudicator",
        arm["shipped_side_readjudicated"] == {"entailment": 2, "relevance": 5},
    ),
    "matched support 0.968 against 0.956": (
        "0.956",
        _ae["matched_contrast"]["arm_1"]["rate"] == 0.9676
        and _ae["matched_contrast"]["arm_2"]["rate"] == 0.956,
    ),
    # From the artifact's integer hits and n. Rounding a field that was already rounded to
    # four places gives 0.011 here, which is how 2.7 happened; the exact value is 0.011524.
    # The PRIMARY interval is the paired-question cluster bootstrap: both arms answer the same
    # 134 questions and claims nest in questions, so a two-independent-sample formula does not
    # apply. Newcombe is still computed, and asserted to be the WIDER of the two, which is the
    # cost of the assumption it makes.
    "matched support difference 0.012": (
        "0.012",
        round(_ae["matched_contrast"]["arm_1"]["hits"] / _ae["matched_contrast"]["arm_1"]["n"]
              - _ae["matched_contrast"]["arm_2"]["hits"] / _ae["matched_contrast"]["arm_2"]["n"],
              3) == 0.012,
    ),
    "support interval, paired-question bootstrap": (
        "0.039",
        [round(x, 3) for x in
         _ae["PRIMARY_matched_contrast_paired_question_bootstrap"]["ci95"]] == [-0.016, 0.039],
    ),
    "matched responsiveness 0.038 against 0.036": (
        "0.036",
        _ar["matched_contrast"]["arm_1"]["rate"] == 0.0378
        and _ar["matched_contrast"]["arm_2"]["rate"] == 0.0357,
    ),
    "matched responsiveness difference 0.002": (
        "0.002",
        round(_ar["matched_contrast"]["arm_1"]["hits"] / _ar["matched_contrast"]["arm_1"]["n"]
              - _ar["matched_contrast"]["arm_2"]["hits"] / _ar["matched_contrast"]["arm_2"]["n"],
              3) == 0.002,
    ),
    # The upper bound is 0.0265492, which sits within 5e-5 of the 3-decimal rounding boundary:
    # it prints 0.027 at the paper's seed and 0.026 at the alternate seed. The ledger says so.
    "responsiveness interval, paired-question bootstrap": (
        "0.027",
        [round(x, 3) for x in
         _ar["PRIMARY_matched_contrast_paired_question_bootstrap"]["ci95"]] == [-0.020, 0.027],
    ),
    "the bootstrap is narrower than Newcombe, on both instruments": (
        "0.039",
        all(d["interval_widths"]["newcombe_independent"]
            > d["interval_widths"]["paired_question_bootstrap"] for d in (_ae, _ar)),
    ),
    "the bootstrap design is the paper's": (
        "0.027",
        all(d["PRIMARY_matched_contrast_paired_question_bootstrap"]["seed"] == 20260907
            and d["PRIMARY_matched_contrast_paired_question_bootstrap"]["clusters"] == 134
            for d in (_ae, _ar)),
    ),
    # the mixed retrieval configuration, from the captures' own metadata.pipeline
    "67 standard and 67 deep": (
        "67",
        _rc["retrieval_profile"] == {"standard": 67, "deep": 67},
    ),
    "top-12 and top-20": (
        "20",
        _rc["retrieval_top_k"] == {"12": 67, "20": 67},
    ),
    "the extractor ran on half the QUESTIONS": (
        "67",
        _rc["llm_extractor_used"] == {"False": 67, "True": 67},
    ),
    # but NOT half the claims. The no-extractor half produced the majority, 208 of 351; the
    # paper claimed "half the claims" for a day, which was half the QUESTIONS.
    "208 of 351 claims from the no-extractor half": (
        "208",
        runcfg["arms"]["shipped"]["claims_from_the_no_extractor_half"]["claims"] == 208
        and runcfg["arms"]["shipped"]["claims_from_the_no_extractor_half"]["of_all_claims"] == 351,
    ),
    # 4024 is NOT 67*12 + 67*20 = 2144. top_k is a base; the served pool is base x a
    # retrieval_mode multiplier, and the answer records what survives deduplication.
    "4024 retrieved chunks, 22 to 57 per answer": (
        "4024",
        runcfg["arms"]["shipped"]["retrieved_chunks"]["total"] == 4024
        and runcfg["arms"]["shipped"]["retrieved_chunks"]["range_per_question"] == [22, 57],
    ),
    "and top-k is a base, not a delivered count": (
        "22",
        runcfg["arms"]["shipped"]["retrieved_chunks"]["served_pool_multipliers"]["topic_summary"] == 3
        and 67 * 12 + 67 * 20 != runcfg["arms"]["shipped"]["retrieved_chunks"]["total"],
    ),
    "and the split is matched across arms, so it is not an arm confound": (
        "confound",
        runcfg["cross_arm"]["identical_setting_per_question"] == 134
        and runcfg["cross_arm"]["differing"] == [],
    ),
    # one label version for every joint quantity: "95 against 49" were original-judging counts
    # printed beside matched rates, and 95 exceeds the matched not_relevant total of 83
    # the answer level, which is the unit a reader actually receives. Same matched labels.
    # 5/55 = 0.0909 and 10/109 = 0.0917, so 0.09 in both arms -- the arm null holding one
    # level up from the per-claim rates.
    "5 of 55 answers carry a responsive claim": (
        "5",
        _jm["questions_with_any_claim"] == 55
        and _jm["questions_with_at_least_one_relevant"] == 5
        and _jm["questions_where_every_claim_is_not_relevant"] == 12,
    ),
    "10 of 109 in the URL-first arm": (
        "109",
        _ju["questions_with_any_claim"] == 109
        and _ju["questions_with_at_least_one_relevant"] == 10
        and _ju["questions_where_every_claim_is_not_relevant"] == 26,
    ),
    "exploratory answerable rates 0.773 and 0.815": (
        "0.773",
        tb_strat["answers_shipped"]["answerable"]["rate"] == 0.7731
        and tb_strat["answers_urlfirst"]["answerable"]["rate"] == 0.8151,
    ),
    # citability is 147 of the 166 withheld claims, not all of them: the span gate takes 19.
    "citability withholds 147 of the 166": (
        "147",
        facts["claims"]["withheld_by_reason"]["cited_record_not_citable"] == 147
        and facts["claims"]["withheld"] == 166,
    ),
    "78 supported-but-unrelated against 40": (
        "78",
        _ju["supported_and_not_relevant"] == 78 and _jm["supported_and_not_relevant"] == 40,
    ),
    "and 95 is impossible under matched labels": (
        "40",
        _ju["relevance_distribution"]["not_relevant"] == 83
        and _ju["supported_and_not_relevant"] < 95,
    ),
    "matching moved responsiveness 0.008 and flipped its sign": (
        "0.008",
        round(_ar["moved_by_matching"], 3) == 0.008
        and _ar["confounded_contrast_as_first_reported"]["difference"] < 0
        < _ar["matched_contrast"]["difference"],
    ),
    "the judge shift moves BOTH arms the same way": (
        "reversed the sign",
        _ar["url_first_label_distribution_matched"]["relevant"]
        > _ar["url_first_label_distribution_as_first_judged"]["relevant"],
    ),
    # my inference that the shortened codebook drove `overstated` -- tested and refuted
    "restoring the codebook did not move overstated": (
        "0.956",
        _ae["url_first_label_distribution_matched"].get("overstated")
        == _ae["url_first_label_distribution_as_first_judged"].get("overstated") == 1,
    ),
    "URL-first controls hold under the matched instrument": (
        "37",
        _ae["url_first_controls"]["avoided_the_positive_label"] == 37
        and _ar["url_first_controls"]["avoided_the_positive_label"] == 37,
    ),
    # the four gate configurations
    "351 extracted": ("351", A["claims_extracted"] == 351),
    "185 returned": ("185", A["claims_shown"] == 185),
    "0.527 retention": ("0.527", A["retention_shown_over_extracted"][0] == 0.5271),
    "147 citability": ("147", A["withheld_citability"] == 147),
    "79 zero-claim": ("79", A["answers_with_zero_claims"] == 79),
    "157 of 708 figures": ("157", facts["figures_in_delivered_answers"]["inside_a_verified_span"] == 157),
    "77.8 % unpinned": ("77.8", facts["figures_in_delivered_answers"]["rate_outside"] == 0.7782),
    "19 span failures": ("19", facts["claims"]["span_gate_failures"] == 19),
    "29 independent": ("29", facts["containment_is_non_trivial_only_here"]["independent_span_claims"] == 29),
    # support
    "0.968 supported": ("0.968", ent_s["headline"]["supported_rate_ci"][0] == 0.9676),
    "179 of 185": ("179", ent_s["headline"]["label_distribution"]["supported"]["n"] == 179),
    "kappa 0.973": ("0.973", ent_s["instrument"]["cohens_kappa"] == 0.9725),
    # the author's blind grading -- the review found an impossible interval here, so the
    # numbers the paper prints for it are now joined to the scorer's output like any other
    "human 0.984": ("0.984", ent_h["human_supported_rate"]["post_stratified_to_the_185"][0] == 0.9838),
    "human lower 0.846": ("0.846", ent_h["human_supported_rate"]["post_stratified_to_the_185"][1] == 0.8459),
    "precision lower 0.858": ("0.858", ent_h["stratum_B_model_supported"]["precision_ci_clopper_pearson"][0] == 0.8575),
    "the point estimate is the design's ceiling": (
        "0.984",
        ent_h["human_supported_rate"]["post_stratified_to_the_185"][0]
        == ent_h["human_supported_rate"]["feasible_bounds_of_the_design"][1]
        == ent_h["human_supported_rate"]["post_stratified_to_the_185"][2],
    ),
    "human relevance 0.028": ("0.028", rel_h["human_relevant_rate"]["post_stratified_to_the_185"] == 0.0284),
    # The conservative envelope [0.001, 0.405] is still COMPUTED and still in the artifact and
    # the ledger, where it documents why no interval is quoted. It is no longer asserted here
    # because the paper no longer prints it: a simultaneous interval over five strata was
    # never computed, and an envelope is not one. The paper reports 0.028 as a descriptive
    # calibration estimate and stops, so there is nothing for these assertions to join to.
    "only two positive cases": (
        "two positives",
        sum(1 for r in rel_h["per_item"] if r["human"] == "relevant") == 2,
    ),
    # Three sheets now: 30 + 40 on the shipped arm, overlapping on 9, plus 40 on the
    # URL-first arm, which shares nothing with them. 110 judgements over 101 distinct claims.
    # The 9-item overlap is still asserted -- it is why the shipped pair is 61 and not 70 --
    # but the paper no longer prints the word, so the token is the number it does print.
    "110 judgements over 101 distinct claims": (
        "110",
        ent_h["cross_sheet"]["judgements"] + rel_hu["agreement"]["items"] == 110
        and ent_h["cross_sheet"]["distinct_claims"] + rel_hu["agreement"]["items"] == 101
        and len(ent_h["cross_sheet"]["shared_by_both_sheets"]) == 9,
    ),
    # the URL-first arm is human-graded now, which retires two sentences
    "URL-first agreement 0.95, kappa 0.87": (
        "0.95",
        rel_hu["agreement"]["exact_three_way"] == 0.95
        and round(rel_hu["agreement"]["cohens_kappa"], 2) == 0.87
        and rel_hu["agreement"]["items"] == 40,
    ),
    "URL-first matched human agreement 92.5 percent": (
        "92.5", rel_hu["matched_agreement"]["exact_three_way"] == 0.925
        and rel_hu["matched_agreement"]["items"] == 40,
    ),
    "URL-first matched human kappa 0.81": (
        "0.81", round(rel_hu["matched_agreement"]["cohens_kappa"], 2) == 0.81,
    ),
    "matched relevant items both human partial": (
        "92.5",
        rel_hu["matched_agreement"]["model_distribution_on_these_40"].get("relevant", 0) == 2
        and rel_hu["matched_agreement"]["confusion_human_by_model"].get("partial|relevant") == 2
        and rel_hu["matched_agreement"]["human_distribution"].get("relevant", 0) == 0,
    ),
    "original and matched calibration explicitly distinguished": (
        "0.81", rel_hu["agreement_label_version"] == "original",
    ),
    # the 156 decomposed: 154 cite a URL-less record, 2 cite an EMPTY chunk id
    "two cite nothing": ("two", facts["claims"]["withheld_by_reason"]["chunk_id_not_resolvable"] == 2),
    # latency, decomposed: the paper used to print 3.1 s, which its own table contradicted
    "question authoring and auditing model": (
        "claude-opus-5",
        pprov["authoring_model_id"] == "claude-opus-5" and pprov["auditor_model_id"] == "claude-opus-5",
    ),
    "returned URLs opening on cited article": (
        "0.903",
        round(tb_deref["shipped/returned"]["share_article_match"], 3) == 0.903
        and round(tb_deref["urlfirst/returned"]["share_article_match"], 3) == 0.777,
    ),
    "article-only strict retention": (
        "0.476",
        round(tb_deref["shipped/strict_retention"]["retention_strict"], 3) == 0.476
        and round(tb_deref["urlfirst/strict_retention"]["retention_strict"], 3) == 0.747,
    ),
    "recovered span on page 133 of 147 and 0.906 retention": (
        "0.906",
        tc_rec["summary"]["span_on_page"] == 133
        and tc_rec["summary"]["projected_C3_retention_span_on_page"] == 0.906
        and tc_rec["summary"]["responsive_withheld_span_on_page"] == 10,
    ),
    "third judge sonnet kappa 0.93 and 218 of 268 same-model": (
        "claude-sonnet-5-5",
        round(tb_cross["kappa_sonnet_vs_final_real"]["kappa"], 2) == 0.93
        and tb_prov["workflows"]["tier_b_primary"]["real_answer_pairs_same_model"] == 218,
    ),
    # responsiveness
    "4 relevant": ("4", rel_s["headline"]["label_distribution"]["relevant"]["n"] == 4),
    "0.022": ("0.022", rel_s["headline"]["relevant_rate_ci"][0] == 0.0216),
    "129 partial": ("129", rel_s["headline"]["label_distribution"]["partial"]["n"] == 129),
    "52 unrelated": ("52", rel_s["headline"]["label_distribution"]["not_relevant"]["n"] == 52),
    "49 supported-unrelated": ("49", rel_s["support_x_relevance"]["supported_but_not_relevant"] == 49),
    "kappa 0.955": ("0.955", rel_s["instrument"]["cohens_kappa"] == 0.9553),
    "55 answers with claims": ("55", rel_s["answer_level"]["answers_with_at_least_one_displayed_claim"] == 55),
    "15 only-unrelated": ("15", rel_s["answer_level"]["answers_where_every_displayed_claim_is_not_relevant"] == 15),
    # the second design
    "364 returned": ("364", U["claims_shown"] == 364),
    "0.960 retention": ("0.960", U["retention_shown_over_extracted"][0] == 0.9604),
    "25 zero-claim": ("25", U["answers_with_zero_claims"] == 25),
    "379 extracted": ("379", U["claims_extracted"] == 379),
    # the paper now prints the MATCHED URL-first support rate; 0.9615 was the confounded one
    # and lives in the ledger, not in the paper
    "0.956 supported, matched": (
        "0.956",
        _ae["matched_contrast"]["arm_2"]["rate"] == 0.956
        and ent_u["headline"]["supported_rate_ci"][0] == 0.9615,
    ),
    "0.028 relevant": ("0.028", rel_u["headline"]["relevant_rate_ci"][0] == 0.0275),
    "95 supported-unrelated": ("95", rel_u["support_x_relevance"]["supported_but_not_relevant"] == 95),
    "41 on controls": ("41", arms["controls_only"]["url_first"]["claims_shown"] == 41),
    "25 on controls": ("25", arms["controls_only"]["shipped"]["claims_shown"] == 25),
}
bad_artifact = [k for k, (_, ok) in checks.items() if not ok]
missing = [k for k, (needle, _) in checks.items() if needle not in body]
print("artifact disagrees with the paper:", bad_artifact or "none")
print("printed in no visible line:", missing or "none")

# Every structural check below is a GATE, not a printout. It used to be a printout: the exit
# code keyed on the artifact checks alone, so a retired phrase or an unresolved \ref would be
# reported and the script would still exit 0. "and is faster" survived a whole commit that
# way, in a paper whose subject is checks that do not check.
structural = {}
print("\nstructure")
cited = {k.strip() for m in re.findall(r"\\cite\{([^}]*)\}", tex) for k in m.split(",")}
keys = set(re.findall(r"@\w+\{([^,]+),", bib))
structural["unbalanced braces"] = [] if tex.count("{") - tex.count("}") == 0 else ["unbalanced"]
structural["unresolved ref"] = [r for r in re.findall(r"\\ref\{([^}]*)\}", tex) if ("\\label{" + r + "}") not in tex]
structural["duplicate label"] = [l for l in set(re.findall(r"\\label\{([^}]*)\}", tex)) if tex.count("\\label{" + l + "}") > 1]
structural["cited but absent from bib"] = sorted(cited - keys)
structural["in bib but uncited"] = sorted(keys - cited)
print("  braces balanced      :", not structural["unbalanced braces"])
print("  unresolved \\ref      :", structural["unresolved ref"] or "none")
print("  duplicate \\label     :", structural["duplicate label"] or "none")
print("  cited but absent     :", structural["cited but absent from bib"] or "none")
print("  in bib but uncited   :", structural["in bib but uncited"] or "none")

bib_clean = re.sub(r"(?m)^%.*$", "", bib)
entry_spans = []
for match in re.finditer(r"@\w+\s*\{", bib_clean):
    if entry_spans and match.start() < entry_spans[-1][1]:
        continue
    depth, pos = 1, match.end()
    while pos < len(bib_clean) and depth:
        if pos == 0 or bib_clean[pos - 1] != "\\":
            depth += (bib_clean[pos] == "{") - (bib_clean[pos] == "}")
        pos += 1
    entry_spans.append((match.start(), pos))
for start, end in reversed(entry_spans):
    bib_clean = bib_clean[:start] + bib_clean[end:]
structural["orphan BibTeX fields"] = [bib_clean.strip()[:120]] if bib_clean.strip() else []
print("  orphan BibTeX fields :", structural["orphan BibTeX fields"] or "none")

print("  \\TBD remaining       :", sorted(set(re.findall(r"\\TBD\{([^{}]*)\}", tex))))
print("  tables / figures     :", len(re.findall(r"\\begin\{table\*?\}", tex)), "/", len(re.findall(r"\\begin\{figure\}", tex)))
structural["control chars"] = sorted({hex(ord(c)) for c in tex + bib if ord(c) < 32 and c not in "\n\t"})
structural["line-broken dashes"] = [l[-32:] for l in tex.splitlines() if l.rstrip().endswith("-") and not l.strip().startswith("%")]
# Every \includegraphics must resolve. The old check asked whether one specific PDF
# existed, which stayed True after the figure was removed from the document -- a check
# that cannot fail. This one holds for zero figures and for ten.
structural["figure file missing"] = [
    g for g in re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", tex)
    if not (REPO / "paper" / g).exists() and not (REPO / "paper" / (g + ".pdf")).exists()
]
print("  control chars        :", structural["control chars"] or "none")
print("  line-broken dashes   :", structural["line-broken dashes"] or "none")
print("  includegraphics resolve:", not structural["figure file missing"])
banned = [
    "Beyond the census we probed",
    "Whole hosts are dead",
    "What did not change is the per-claim rates",
    "not the attribution mechanism",
    "rises from 20 to 79",
    "Claims citing a URL-less record: 156",
    "which moved both rates slightly upward",
    "nor any in the model's labels",

    "53.6", "sub-second", "Two judges", "claim-free by design", "future work",
    "entire population", "reached the reader", "0.223", "158 of 708", "unopenable",
    # retired in the 2026-09-07 review round, each for a stated reason
    "0.995",            # an interval the two-stratum design cannot express
    "0.075",            # an interval from three strata that observed nothing
    "no resolvable",    # we read the URL field; we never dereferenced it
    "resolvable only",  # same
    "43.5",             # the article-level total is 43.58 -> 43.6
    r"3.1}\,s",         # the end-to-end drop is 2.5 s, and its own table said so
    "changes nothing a reader would notice",  # overlapping CIs are not equivalence
    "same quality",     # same
    "Irrelevant:",      # 69.7 % of claims are partial, not unrelated
    "never called a claim supported that a reader would not",  # 24/24 is not 179
    "and is faster",    # 1.7 s of the 2.5 s is a cross-day confound
    # retired 2026-09-07, second revision round
    "0.405",            # a simultaneous interval was never computed; do not quote the envelope
    "Neither improves", # no equivalence margin was pre-specified
    "no longer resolves",  # the two claims cite an EMPTY chunk id; they cite nothing
    "errs towards over-flagging",  # a conclusion three overturned items cannot carry
    # retired 2026-09-08, once the URLs were actually dereferenced
    "we did not dereference it",
    "never dereference it",
    "tab:g2",           # Table II was cut to make room for the dereference audit
    # retired 2026-09-08 by the adversarial pass; each was verified against the artifact
    "56.9",             # 339,248/595,663 = 56.95 -> 57, and Table I's own total says 57
    "Five of the six",  # four stricter, two looser (rel_04, rel_14)
    "reaches the cited document",  # 3a is title-free; it cannot establish WHICH document
    "forbids three hosts",         # five host rows are blocked
    "sec:deref",        # a label inside a section resolved to that section
    "not yet labelled by a person",   # it is labelled: page_type_v1.json
    # withdrawn 2026-09-08: the composite and everything that depended on it
    "naming a different article",   # an issue index lists many, one may be the cited one
    "of measurable chunks do both",
    # retired 2026-09-10: pre-registration means a public timestamped protocol with an
    # analysis plan. What happened is precommitment -- the 134 questions were committed
    # and hashed 2026-09-04, the sweep captured 2026-09-05, in a repo with no registry.
    "pre-registered",
    "pre-registration",
    # retired 2026-09-10: "fabricated" asserts invention where the test shows only that
    # the numeric token is absent from the evidence. We never check the value is wrong.
    "fabricated figure",
    "lie inside a verified span",  # membership is by numeric token, not by meaning
    # retired 2026-09-10 by the RIVF-rubric review
    "the entire tax is citability",   # 147 of 166; the span gate takes the other 19
    "returned only unrelated ones",  # that sentence gave ORIGINAL-judging counts
    # retired 2026-09-11: the URL-first arm is human-graded now
    "URL-first has no human calibration",
    "never human-graded at all",     # same
    # retired 2026-09-11: my own Methods sentence, wrong twice
    "so half the claims come from",   # 208 of 351 came from it -- the majority
    "profile at top-",                # invites 67*12 + 67*20 = 2144 against 4024
    "landed_article_level",
    # retired 2026-09-10, once the served judge models were recovered from the run
    # transcripts (benchmark/rivf/judge_model_provenance_v1.json)
    "Support is a property of the system",  # entailment was re-judged by the SAME model
    "everything else held",     # the adjudicator prompt changed, and for entailment so did nothing
    "the model \\emph{pinned}",  # an alias names a family, not a checkpoint
    "pinned judge",             # ditto: it is the re-run judge, not a pinned one
    "checkpoint is unrecoverable",  # the model ID is recoverable; the checkpoint is not
    "\\num{2.7} times",         # 3/185 over (10/364 - 4/185) is 2.77 -> 2.8
    "\\num{12} claims cross",   # 11 real claims, plus one control that moved the same way
    "the null there safer",     # a shift in one arm is not a variance estimate for the contrast
    "$\\kappa = \\num{0.97}$",  # that kappa is inflated by 37 easy-negative controls
    # retired 2026-09-10 by the independent LaTeX/matched-arm review
    r"\\num{95}",                # original-judging joint count printed beside matched rates
    "point at nothing",          # asserted of 2880 URLs; 35 were sampled
    "what the reader is given",  # claims shown go 185 -> 364; only the RATES were unchanged
    "same pinned model",         # Section VII says no run pinned a checkpoint
    r"\\num{-0.029}",            # a Newcombe bound; the design is paired and clustered
    r"\\numrange{0.65}{0.99}",   # not an interval for the 0.93 it sat beside
    # retired 2026-09-10 by the matched-arm re-judge, which measured what the confounded
    # contrast could only disclose
    "both pairs of intervals overlap",   # overlap admits a large difference; report the difference
    "Neither pair is a clean contrast",  # they are matched now
    "losing the instruction that kept",  # MY over-inference: restoring it left overstated at 1
    r"\\num{0.962} against",             # the matched URL-first support rate is 0.956
]
structural["retired wording"] = [s for s in banned if s in body]
print("  retired wording      :", structural["retired wording"] or "none")

# \TBD is NOT a gate: the author's own details and the artifact URL are legitimately open
# until submission. It is printed above so it cannot be forgotten.
failures = {k: v for k, v in structural.items() if v}
if bad_artifact:
    failures["artifact disagrees with the paper"] = bad_artifact
if missing:
    failures["printed in no visible line"] = missing

print()
if failures:
    print("FAIL")
    for k, v in failures.items():
        print(f"  {k}: {v}")
else:
    print(f"PASS: {len(checks)} artifact assertions and "
          f"{len(structural)} structural checks, all clean")
raise SystemExit(1 if failures else 0)
