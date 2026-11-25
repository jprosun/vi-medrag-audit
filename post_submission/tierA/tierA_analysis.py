"""Tier A analysis for EDAS 1571353709 revision.

Retrieval shares, claim-level shares, duplication and RQ1 bounds, computed from the
released artifact (treated as read-only data). Every number printed here is derived
from the files passed on the command line; nothing is typed in by hand except the
stratum identifier of the URL-less stratum and the regexes copied from the artifact's
corpus_census.py (quoted in the output).

Usage:
  python -I -X utf8 tierA_analysis.py <shipped.jsonl> <urlfirst.jsonl> <probe.jsonl>
         <census.json> <url_audit_report.json> <url_population.json>
         <url_confirmatory_estimate.json> <out_dir>
"""
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from urllib.parse import urlparse

import numpy as np

URLLESS_SOURCE_ID = "hf_vi_mtue29_medical"
# Copied verbatim from benchmark/rivf/corpus_census.py lines 71-72 of the artifact.
ISSUE_URL_RE = re.compile(r"/issue/(view|archive)/", re.IGNORECASE)
ARTICLE_URL_RE = re.compile(r"/article/(view|download)/|/pmc/|/books/|doi\.org/", re.IGNORECASE)
SHA_RE = re.compile(r"sha256:([0-9a-f]+)")
B_RESAMPLES = 5000
SEED = 0
QTYPES = ["clinical_explainer", "study_result_numeric", "guideline_comparison",
          "patient_faq", "differential_or_workup"]
CONTROL = "out_of_corpus_control"


def load_jsonl(path):
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def r4(x):
    return None if x is None else round(float(x), 4)


def boot_ratio(pairs, B=B_RESAMPLES, seed=SEED):
    """Percentile cluster bootstrap over questions for sum(num)/sum(den).

    pairs: list of (num_i, den_i), one per question (cluster). Each resample draws n
    questions with replacement and recomputes sum(num)/sum(den). CI = 2.5th and 97.5th
    percentiles of the B resampled ratios (numpy.percentile, linear interpolation).
    A fresh Generator seeded with `seed` is used for every call.
    """
    u = np.array([p[0] for p in pairs], dtype=float)
    t = np.array([p[1] for p in pairs], dtype=float)
    n = len(u)
    point = u.sum() / t.sum() if t.sum() > 0 else float("nan")
    if n == 0:
        return {"n_questions": 0, "num": 0, "den": 0, "point": None, "ci95": None}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(B, n))
    num = u[idx].sum(axis=1)
    den = t[idx].sum(axis=1)
    ratios = num / den
    lo, hi = np.percentile(ratios, [2.5, 97.5])
    return {"n_questions": int(n), "num": int(u.sum()), "den": int(t.sum()),
            "point": r4(point), "ci95": [r4(lo), r4(hi)],
            "resamples": B, "seed": seed}


def host_of(url):
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def norm_ws(s):
    return " ".join((s or "").split())


def norm_strong(s):
    return unicodedata.normalize("NFC", norm_ws(s)).casefold()


def main(argv):
    (shipped_p, urlfirst_p, probe_p, census_p, audit_p, pop_p, conf_p, out_dir) = argv[1:9]
    results = {"inputs": {"shipped": shipped_p, "urlfirst": urlfirst_p, "probe": probe_p,
                          "census": census_p, "url_audit_report": audit_p,
                          "url_population": pop_p, "url_confirmatory": conf_p},
               "conventions": {
                   "urlless_stratum": URLLESS_SOURCE_ID,
                   "issue_url_regex": ISSUE_URL_RE.pattern,
                   "article_url_regex": ARTICLE_URL_RE.pattern,
                   "bootstrap": "percentile cluster bootstrap over questions, "
                                f"{B_RESAMPLES} resamples, numpy default_rng(seed={SEED}) "
                                "fresh per group, ratio of sums within each resample, "
                                "CI = 2.5/97.5 percentiles"}}

    # ------------------------------------------------------------------ questions
    probes = load_jsonl(probe_p)
    qinfo = {}
    for q in probes:
        spec, qtype = q["source"].split(":", 1)[1].split("/", 1)
        qinfo[q["query_id"]] = {"specialty": spec, "qtype": qtype,
                                "is_control": spec == CONTROL,
                                "group": CONTROL if spec == CONTROL else qtype}
    print(f"[probe] questions={len(qinfo)} controls={sum(v['is_control'] for v in qinfo.values())}")
    print("[probe] group sizes:", dict(Counter(v["group"] for v in qinfo.values())))
    print("[probe] controls by qtype:", dict(Counter(v["qtype"] for v in qinfo.values() if v["is_control"])))
    results["probe"] = {"n": len(qinfo),
                        "group_sizes": dict(Counter(v["group"] for v in qinfo.values())),
                        "controls_by_qtype": dict(Counter(v["qtype"] for v in qinfo.values() if v["is_control"]))}

    # ------------------------------------------------------------------ captures
    def load_arm(path, name):
        recs = load_jsonl(path)
        ids = [r["query_id"] for r in recs]
        assert len(recs) == 134, (name, len(recs))
        assert len(set(ids)) == 134, name
        assert set(ids) == set(qinfo), name
        bad = [r["query_id"] for r in recs if r.get("http_status") != 200 or not r.get("payload")]
        print(f"[{name}] records={len(recs)} non-200/empty payload={len(bad)}")
        return recs
    shipped = load_arm(shipped_p, "shipped")
    urlfirst = load_arm(urlfirst_p, "urlfirst")

    def chunks_of(r):
        return r["payload"].get("retrieved_chunks") or []

    def claims_of(r):
        p = r["payload"]
        return (p.get("claim_attributions") or []) + (p.get("dropped_claims") or [])

    # ------------------------------------------------------------------ 1. sanity
    def per_q_counts(recs):
        rows = []
        for r in recs:
            ch = chunks_of(r)
            n = len(ch)
            n_url_less_stratum = sum(1 for c in ch if c["metadata"].get("source_id") == URLLESS_SOURCE_ID)
            n_no_url = sum(1 for c in ch if not (c["metadata"].get("source_url") or "").strip())
            n_no_url_other = sum(1 for c in ch if not (c["metadata"].get("source_url") or "").strip()
                                 and c["metadata"].get("source_id") != URLLESS_SOURCE_ID)
            n_vi = sum(1 for c in ch if c["metadata"].get("language") == "vi")
            n_vi_urlless = sum(1 for c in ch if c["metadata"].get("language") == "vi"
                               and c["metadata"].get("source_id") == URLLESS_SOURCE_ID)
            pl = r["payload"]["metadata"].get("pipeline") or {}
            rows.append({"query_id": r["query_id"], "n": n, "urlless": n_url_less_stratum,
                         "no_url": n_no_url, "no_url_other": n_no_url_other,
                         "vi": n_vi, "vi_urlless": n_vi_urlless,
                         "answer_mode": r["payload"]["metadata"].get("answer_mode"),
                         "profile": pl.get("retrieval_profile"),
                         "top_k": pl.get("retrieval_top_k"),
                         "extractor_used": pl.get("llm_extractor_used"),
                         "group": qinfo[r["query_id"]]["group"],
                         "qtype": qinfo[r["query_id"]]["qtype"],
                         "is_control": qinfo[r["query_id"]]["is_control"]})
        return rows

    rows_s = per_q_counts(shipped)
    rows_u = per_q_counts(urlfirst)
    tot = sum(x["n"] for x in rows_s)
    tot_urlless = sum(x["urlless"] for x in rows_s)
    tot_no_url = sum(x["no_url"] for x in rows_s)
    tot_no_url_other = sum(x["no_url_other"] for x in rows_s)
    print("\n=== 1. SANITY (shipped arm) ===")
    print(f"total retrieved chunks = {tot}")
    print(f"chunks from URL-less stratum ({URLLESS_SOURCE_ID}) = {tot_urlless}")
    print(f"share = {tot_urlless}/{tot} = {tot_urlless/tot:.4f}")
    print(f"chunks with empty source_url = {tot_no_url}; of which NOT in URL-less stratum = {tot_no_url_other}")
    print(f"chunks per answer: min={min(x['n'] for x in rows_s)} max={max(x['n'] for x in rows_s)}")
    print(f"answer_mode counts: {dict(Counter(x['answer_mode'] for x in rows_s))}")
    print(f"pipeline.retrieval_profile counts: {dict(Counter(x['profile'] for x in rows_s))}; "
          f"(profile, top_k, extractor_used): {dict(Counter((x['profile'], x['top_k'], x['extractor_used']) for x in rows_s))}")
    tot_u = sum(x["n"] for x in rows_u)
    tot_u_urlless = sum(x["urlless"] for x in rows_u)
    print(f"[urlfirst] total retrieved chunks = {tot_u}; URL-less stratum = {tot_u_urlless}; "
          f"empty source_url = {sum(x['no_url'] for x in rows_u)}; "
          f"chunks per answer min={min(x['n'] for x in rows_u)} max={max(x['n'] for x in rows_u)}")
    results["1_sanity"] = {
        "shipped": {"total_retrieved_chunks": tot, "urlless_stratum_chunks": tot_urlless,
                    "share": r4(tot_urlless / tot), "chunks_with_empty_source_url": tot_no_url,
                    "empty_source_url_outside_urlless_stratum": tot_no_url_other,
                    "chunks_per_answer_min": min(x["n"] for x in rows_s),
                    "chunks_per_answer_max": max(x["n"] for x in rows_s),
                    "answer_mode_counts": dict(Counter(x["answer_mode"] for x in rows_s)),
                    "retrieval_profile_counts": dict(Counter(x["profile"] for x in rows_s)),
                    "profile_topk_extractor_counts": {str(k): v for k, v in Counter(
                        (x["profile"], x["top_k"], x["extractor_used"]) for x in rows_s).items()},
                    "note": "metadata.answer_mode is 'standard' for all 134 records; the 67/67 "
                            "standard/deep split the paper describes is metadata.pipeline.retrieval_profile"},
        "urlfirst": {"total_retrieved_chunks": tot_u, "urlless_stratum_chunks": tot_u_urlless,
                     "chunks_with_empty_source_url": sum(x["no_url"] for x in rows_u),
                     "chunks_per_answer_min": min(x["n"] for x in rows_u),
                     "chunks_per_answer_max": max(x["n"] for x in rows_u),
                     "answer_mode_counts": dict(Counter(x["answer_mode"] for x in rows_u))}}

    # ------------------------------------------------------------------ 2. by type / mode
    print("\n=== 2. URL-less stratum share of retrieved chunks, shipped arm, cluster bootstrap CI ===")
    print("formula: share_G = sum_{q in G} urlless_q / sum_{q in G} n_q ; CI = percentile bootstrap over questions in G")
    sec2 = {}
    sec2["overall_134"] = boot_ratio([(x["urlless"], x["n"]) for x in rows_s])
    sec2["answerable_119"] = boot_ratio([(x["urlless"], x["n"]) for x in rows_s if not x["is_control"]])
    print(f"overall (134 q): {sec2['overall_134']}")
    print(f"answerable (119 q): {sec2['answerable_119']}")
    by_group = {}
    for g in QTYPES + [CONTROL]:
        sub = [(x["urlless"], x["n"]) for x in rows_s if x["group"] == g]
        by_group[g] = boot_ratio(sub)
        print(f"  group={g:24s} {by_group[g]}")
    sec2["by_group_controls_separate"] = by_group
    by_qtype_incl_controls = {}
    for g in QTYPES:
        sub = [(x["urlless"], x["n"]) for x in rows_s if x["qtype"] == g]
        by_qtype_incl_controls[g] = boot_ratio(sub)
        print(f"  qtype(incl. controls)={g:24s} {by_qtype_incl_controls[g]}")
    sec2["by_qtype_including_controls"] = by_qtype_incl_controls
    by_mode = {}
    for m in sorted(set(x["answer_mode"] for x in rows_s)):
        sub = [(x["urlless"], x["n"]) for x in rows_s if x["answer_mode"] == m]
        by_mode[m] = boot_ratio(sub)
        print(f"  metadata.answer_mode={m:10s} {by_mode[m]}")
    sec2["by_answer_mode_field"] = by_mode
    by_prof = {}
    for m in sorted(set(x["profile"] for x in rows_s)):
        sub = [(x["urlless"], x["n"]) for x in rows_s if x["profile"] == m]
        by_prof[m] = boot_ratio(sub)
        by_prof[m]["mean_chunks_per_answer"] = r4(sum(x["n"] for x in rows_s if x["profile"] == m) / len(sub))
        print(f"  pipeline.retrieval_profile={m:10s} {by_prof[m]}")
    sec2["by_retrieval_profile"] = by_prof
    # profile x group cross-tab (counts only, no CI -- cells are small)
    cross = defaultdict(lambda: [0, 0, 0])
    for x in rows_s:
        c = cross[(x["profile"], x["group"])]
        c[0] += 1; c[1] += x["urlless"]; c[2] += x["n"]
    sec2["profile_x_group_counts"] = {f"{m}|{g}": {"n_questions": v[0], "urlless": v[1], "total": v[2],
                                                 "share": r4(v[1] / v[2]) if v[2] else None}
                                     for (m, g), v in sorted(cross.items())}
    for k, v in sec2["profile_x_group_counts"].items():
        print(f"    {k:45s} {v}")
    # URL-first arm, same breakdowns (share of URL-less stratum is 0 by construction; report totals)
    uf_prof = {m: {"n_questions": sum(1 for x in rows_u if x["profile"] == m),
                   "retrieved": sum(x["n"] for x in rows_u if x["profile"] == m)}
               for m in sorted(set(x["profile"] for x in rows_u))}
    print(f"[urlfirst] retrieved chunks by retrieval_profile: {uf_prof}")
    sec2["urlfirst_by_retrieval_profile"] = uf_prof
    # URL-first arm: share by source stratum
    uf_strata = Counter()
    for r in urlfirst:
        for c in chunks_of(r):
            uf_strata[c["metadata"].get("source_id")] += 1
    sec2["urlfirst_retrieved_by_source_id"] = {k: {"chunks": v, "share": r4(v / tot_u)}
                                               for k, v in uf_strata.most_common()}
    print(f"[urlfirst] retrieved chunks by source_id (total {tot_u}):")
    for k, v in uf_strata.most_common():
        print(f"    {k:28s} {v:6d} {v/tot_u:.4f}")
    results["2_share_by_type_and_mode"] = sec2

    # ------------------------------------------------------------------ 3. language-matched lift
    print("\n=== 3. LANGUAGE-MATCHED LIFT ===")
    census = json.load(open(census_p, encoding="utf-8"))
    strata = census["strata"]
    N = census["totals"]["chunks"]
    lang_tot = Counter()
    lang_by_stratum = {}
    for sid, s in strata.items():
        lang_by_stratum[sid] = s["language"]
        for lang, n in s["language"].items():
            lang_tot[lang] += n
    lang_sum = sum(lang_tot.values())
    print(f"census: total chunks={N}; sum of per-stratum language counts={lang_sum} (equal -> language field complete)")
    print(f"census language totals: {dict(lang_tot)}")
    vi_total = lang_tot["vi"]
    vi_urlless = strata[URLLESS_SOURCE_ID]["language"].get("vi", 0)
    en_total = lang_tot["en"]
    # English *strata*: majority language en
    en_strata = [sid for sid, s in strata.items() if max(s["language"], key=s["language"].get) == "en"]
    en_strata_chunks = sum(strata[s]["chunks"] for s in en_strata)
    print(f"corpus share of URL-less stratum, all chunks  = {strata[URLLESS_SOURCE_ID]['chunks']}/{N} = {strata[URLLESS_SOURCE_ID]['chunks']/N:.4f}")
    print(f"corpus share of URL-less stratum among language=='vi' chunks = {vi_urlless}/{vi_total} = {vi_urlless/vi_total:.4f}")
    print(f"corpus share of language=='en' chunks = {en_total}/{N} = {en_total/N:.4f}")
    print(f"corpus share of English-majority strata ({len(en_strata)} strata: {en_strata}) = {en_strata_chunks}/{N} = {en_strata_chunks/N:.4f}")
    # retrieved side
    ret_lang = Counter()
    ret_vi_urlless = 0
    ret_en_strata = 0
    for r in shipped:
        for c in chunks_of(r):
            ret_lang[c["metadata"].get("language")] += 1
            if c["metadata"].get("language") == "vi" and c["metadata"].get("source_id") == URLLESS_SOURCE_ID:
                ret_vi_urlless += 1
            if c["metadata"].get("source_id") in en_strata:
                ret_en_strata += 1
    ret_vi = ret_lang["vi"]
    print(f"retrieved language counts (shipped): {dict(ret_lang)}")
    print(f"retrieved share of URL-less stratum among language=='vi' retrieved chunks = {ret_vi_urlless}/{ret_vi} = {ret_vi_urlless/ret_vi:.4f}")
    print(f"retrieved share language=='en' = {ret_lang['en']}/{tot} = {ret_lang['en']/tot:.4f}; "
          f"retrieved share of English-majority strata = {ret_en_strata}/{tot} = {ret_en_strata/tot:.4f}")
    # Candidate definitions of "English reference material" (paper: 16.7% of index, 0.3% retrieved).
    # None is derived in the artifact; we enumerate the plausible ones and report each.
    vn_journal_strata = {"vmj_ojs", "cantho_med_journal", "mil_med_pharm_journal", "hue_jmp_ojs", "trad_med_pharm_journal"}
    ref_other_strata = [sid for sid in strata if sid != URLLESS_SOURCE_ID and sid not in vn_journal_strata]
    ref_other_chunks = sum(strata[s]["chunks"] for s in ref_other_strata)
    ref_other_en = sum(strata[s]["language"].get("en", 0) for s in ref_other_strata)
    en_strata_no_vdd = [s for s in en_strata if s != "vien_dinh_duong"]
    en_strata_no_vdd_chunks = sum(strata[s]["chunks"] for s in en_strata_no_vdd)
    ret_ref_other_en = 0; ret_ref_other = 0; ret_en_strata_no_vdd = 0; ret_en_strata_en = 0
    for r in shipped:
        for c in chunks_of(r):
            sid = c["metadata"].get("source_id"); lang = c["metadata"].get("language")
            if sid in ref_other_strata:
                ret_ref_other += 1
                if lang == "en": ret_ref_other_en += 1
            if sid in en_strata_no_vdd: ret_en_strata_no_vdd += 1
            if sid in en_strata and lang == "en": ret_en_strata_en += 1
    en_candidates = {
        "A_language_en_all_strata": {"index": en_total, "index_share": r4(en_total / N),
                                     "retrieved": ret_lang["en"], "retrieved_share": r4(ret_lang["en"] / tot)},
        "B_english_majority_strata_all_chunks": {"index": en_strata_chunks, "index_share": r4(en_strata_chunks / N),
                                                 "retrieved": ret_en_strata, "retrieved_share": r4(ret_en_strata / tot)},
        "C_english_majority_strata_excluding_vien_dinh_duong": {"index": en_strata_no_vdd_chunks, "index_share": r4(en_strata_no_vdd_chunks / N),
                                                                "retrieved": ret_en_strata_no_vdd, "retrieved_share": r4(ret_en_strata_no_vdd / tot)},
        "D_language_en_within_reference_and_other_strata": {"index": ref_other_en, "index_share": r4(ref_other_en / N),
                                                            "retrieved": ret_ref_other_en, "retrieved_share": r4(ret_ref_other_en / tot)},
        "E_reference_and_other_strata_all_chunks": {"index": ref_other_chunks, "index_share": r4(ref_other_chunks / N),
                                                    "retrieved": ret_ref_other, "retrieved_share": r4(ret_ref_other / tot)},
        "F_language_en_within_english_majority_strata": {"index": sum(strata[s]["language"].get("en", 0) for s in en_strata),
                                                         "index_share": r4(sum(strata[s]["language"].get("en", 0) for s in en_strata) / N),
                                                         "retrieved": ret_en_strata_en, "retrieved_share": r4(ret_en_strata_en / tot)},
    }
    print("candidate definitions of 'English reference material' (paper says 16.7% index -> 0.3% retrieved):")
    for k, v in en_candidates.items():
        print(f"   {k:55s} index {v['index']:7d} ({v['index_share']:.4f})  retrieved {v['retrieved']:4d} ({v['retrieved_share']:.4f})")
    raw_lift = (tot_urlless / tot) / (strata[URLLESS_SOURCE_ID]["chunks"] / N)
    lm_lift = (ret_vi_urlless / ret_vi) / (vi_urlless / vi_total)
    print(f"raw lift = ({tot_urlless}/{tot}) / ({strata[URLLESS_SOURCE_ID]['chunks']}/{N}) = {raw_lift:.4f}")
    print(f"language-matched lift = ({ret_vi_urlless}/{ret_vi}) / ({vi_urlless}/{vi_total}) = {lm_lift:.4f}")
    # bootstrap CI for the vi-only retrieved share, and for both lifts (corpus denominators fixed)
    vi_boot = boot_ratio([(x["vi_urlless"], x["vi"]) for x in rows_s if x["vi"] > 0])
    print(f"vi-only retrieved share bootstrap: {vi_boot}")
    rng = np.random.default_rng(SEED)
    u_all = np.array([x["urlless"] for x in rows_s], float); n_all = np.array([x["n"] for x in rows_s], float)
    uv = np.array([x["vi_urlless"] for x in rows_s], float); nv = np.array([x["vi"] for x in rows_s], float)
    idx = rng.integers(0, len(rows_s), size=(B_RESAMPLES, len(rows_s)))
    raw_l = (u_all[idx].sum(1) / n_all[idx].sum(1)) / (strata[URLLESS_SOURCE_ID]["chunks"] / N)
    lm_l = (uv[idx].sum(1) / nv[idx].sum(1)) / (vi_urlless / vi_total)
    raw_ci = [r4(v) for v in np.percentile(raw_l, [2.5, 97.5])]
    lm_ci = [r4(v) for v in np.percentile(lm_l, [2.5, 97.5])]
    print(f"raw lift CI95 (bootstrap over questions, corpus denominator fixed) = {raw_ci}")
    print(f"language-matched lift CI95 = {lm_ci}")
    results["3_language_matched_lift"] = {
        "census_total_chunks": N, "census_language_totals": dict(lang_tot),
        "census_language_field_complete": lang_sum == N,
        "corpus_share_urlless_all": r4(strata[URLLESS_SOURCE_ID]["chunks"] / N),
        "corpus_vi_chunks": vi_total, "corpus_vi_urlless_chunks": vi_urlless,
        "corpus_share_urlless_among_vi": r4(vi_urlless / vi_total),
        "corpus_share_language_en": r4(en_total / N), "corpus_en_chunks": en_total,
        "english_majority_strata": en_strata, "english_majority_strata_chunks": en_strata_chunks,
        "corpus_share_english_majority_strata": r4(en_strata_chunks / N),
        "retrieved_language_counts": dict(ret_lang),
        "retrieved_vi_chunks": ret_vi, "retrieved_vi_urlless_chunks": ret_vi_urlless,
        "retrieved_share_urlless_among_vi": r4(ret_vi_urlless / ret_vi),
        "retrieved_share_urlless_among_vi_ci95": vi_boot["ci95"],
        "retrieved_share_language_en": r4(ret_lang["en"] / tot),
        "retrieved_share_english_majority_strata": r4(ret_en_strata / tot),
        "raw_lift": r4(raw_lift), "raw_lift_ci95": raw_ci,
        "language_matched_lift": r4(lm_lift), "language_matched_lift_ci95": lm_ci,
        "english_reference_candidates": en_candidates,
        "english_reference_note": "the paper's 16.7% / 0.3% has no derivation in the artifact; "
                                  "none of the candidate definitions above reproduces 16.7% exactly",
        "formula": "raw_lift = (retrieved urlless / retrieved all) / (index urlless / index all); "
                   "language_matched_lift = (retrieved urlless & vi / retrieved vi) / (index urlless & vi / index vi)"}

    # ------------------------------------------------------------------ 4. per-stratum table
    print("\n=== 4. RETRIEVED SHARE BY STRATUM vs INDEX SHARE (shipped arm) ===")
    ret_strata = Counter()
    for r in shipped:
        for c in chunks_of(r):
            ret_strata[c["metadata"].get("source_id")] += 1
    unknown = [k for k in ret_strata if k not in strata]
    print(f"retrieved source_ids not in census: {unknown}")
    table = []
    print(f"{'stratum':26s} {'index':>8s} {'idx%':>7s} {'retr':>6s} {'ret%':>7s} {'lift':>7s} {'url_gran':>12s}")
    for sid, s in sorted(strata.items(), key=lambda kv: -kv[1]["chunks"]):
        idx_share = s["chunks"] / N
        rc = ret_strata.get(sid, 0)
        rshare = rc / tot
        lift = rshare / idx_share if idx_share else None
        gran = ("none" if s["source_url"]["none"] == s["chunks"] else
                "issue" if s["source_url"]["issue_level_only"] == s["chunks"] else
                "article" if s["source_url"]["article_or_page"] == s["chunks"] else "mixed")
        table.append({"stratum": sid, "index_chunks": s["chunks"], "index_share": r4(idx_share),
                      "retrieved_chunks": rc, "retrieved_share": r4(rshare), "lift": r4(lift),
                      "url_granularity": gran, "languages": s["language"]})
        print(f"{sid:26s} {s['chunks']:8d} {idx_share*100:6.2f}% {rc:6d} {rshare*100:6.2f}% {lift:7.3f} {gran:>12s}")
    # also the URL-first arm per stratum
    for row in table:
        rc = uf_strata.get(row["stratum"], 0)
        row["urlfirst_retrieved_chunks"] = rc
        row["urlfirst_retrieved_share"] = r4(rc / tot_u)
    # retrieved source_id x language cross-tab (shipped), for the language-matching argument
    xt = Counter()
    for r in shipped:
        for c in chunks_of(r):
            xt[(c["metadata"].get("source_id"), c["metadata"].get("language"))] += 1
    print("retrieved source_id x language (shipped):")
    for (sid, lang), n in sorted(xt.items(), key=lambda kv: -kv[1]):
        print(f"    {sid:26s} {str(lang):6s} {n:5d}")
    results["4_stratum_table"] = {"total_retrieved_shipped": tot, "total_retrieved_urlfirst": tot_u,
                                  "rows": table,
                                  "retrieved_source_x_language": {f"{sid}|{lang}": n for (sid, lang), n in sorted(xt.items(), key=lambda kv: -kv[1])}}

    # ------------------------------------------------------------------ 5. claims
    print("\n=== 5. CLAIM-LEVEL (claim_attributions + dropped_claims) ===")

    def claim_stats(recs, name):
        total = 0; no_url = 0; no_chunk = 0; no_url_and_chunk_present = 0; no_url_and_no_chunk = 0
        returned = 0; dropped = 0
        resolve_hf = 0; resolve_other = 0; resolve_missing = 0
        by_group = defaultdict(lambda: Counter())
        per_q = []
        drop_reasons = Counter()
        for r in recs:
            ch_index = {c["id"]: c["metadata"].get("source_id") for c in chunks_of(r)}
            p = r["payload"]
            ca = p.get("claim_attributions") or []; dc = p.get("dropped_claims") or []
            returned += len(ca); dropped += len(dc)
            for d in dc:
                drop_reasons[d.get("drop_reason") or ""] += 1
            g = qinfo[r["query_id"]]["group"]
            q_tot = 0; q_nourl = 0
            for cl in ca + dc:
                total += 1; q_tot += 1
                by_group[g]["total"] += 1
                url_empty = not (cl.get("source_url") or "").strip()
                cid_empty = not (cl.get("chunk_id") or "").strip()
                if url_empty: no_url += 1
                if cid_empty: no_chunk += 1
                if url_empty and cid_empty: no_url_and_no_chunk += 1
                if url_empty and not cid_empty:
                    no_url_and_chunk_present += 1; q_nourl += 1
                    by_group[g]["urlless"] += 1
                    sid = ch_index.get(cl["chunk_id"])
                    if sid is None: resolve_missing += 1
                    elif sid == URLLESS_SOURCE_ID: resolve_hf += 1
                    else: resolve_other += 1
                if url_empty or cid_empty:
                    by_group[g]["uncitable"] += 1
            per_q.append((q_nourl, q_tot, g))
        print(f"[{name}] total claims = {total} (returned {returned} + dropped {dropped})")
        print(f"[{name}] claims with empty source_url = {no_url}; empty chunk_id = {no_chunk}; "
              f"empty URL AND empty chunk_id = {no_url_and_no_chunk}; empty URL with a chunk_id = {no_url_and_chunk_present}")
        print(f"[{name}] uncitable (empty URL or empty chunk_id) = {no_url + no_chunk - no_url_and_no_chunk}")
        print(f"[{name}] URL-less claims whose chunk_id resolves to a retrieved chunk in the URL-less stratum = {resolve_hf}; "
              f"other stratum = {resolve_other}; not found among retrieved chunks = {resolve_missing}")
        print(f"[{name}] drop_reason counts: {dict(drop_reasons)}")
        print(f"[{name}] answers with zero returned claims = {sum(1 for r in recs if not (r['payload'].get('claim_attributions') or []))}")
        # by retrieval profile (standard = extractor unused, deep = extractor engaged)
        by_prof = defaultdict(Counter)
        for r in recs:
            prof = (r["payload"]["metadata"].get("pipeline") or {}).get("retrieval_profile")
            p = r["payload"]
            ca = p.get("claim_attributions") or []; dc = p.get("dropped_claims") or []
            by_prof[prof]["questions"] += 1
            by_prof[prof]["claims"] += len(ca) + len(dc)
            by_prof[prof]["returned"] += len(ca)
            for cl in ca + dc:
                if not (cl.get("source_url") or "").strip() and (cl.get("chunk_id") or "").strip():
                    by_prof[prof]["urlless"] += 1
                if not (cl.get("chunk_id") or "").strip():
                    by_prof[prof]["empty_chunk_id"] += 1
        for prof, c in sorted(by_prof.items()):
            print(f"  [{name}] retrieval_profile={prof:9s} questions={c['questions']} claims={c['claims']} returned={c['returned']} "
                  f"urlless={c['urlless']} empty_chunk_id={c['empty_chunk_id']} "
                  f"urlless_share={c['urlless']/c['claims'] if c['claims'] else float('nan'):.4f}")
        out = {"total_claims": total, "returned": returned, "dropped": dropped,
               "by_retrieval_profile": {prof: dict(c) | {"urlless_share": r4(c["urlless"] / c["claims"]) if c["claims"] else None}
                                        for prof, c in sorted(by_prof.items())},
               "empty_source_url": no_url, "empty_chunk_id": no_chunk,
               "empty_url_and_empty_chunk_id": no_url_and_no_chunk,
               "urlless_record_cited": no_url_and_chunk_present,
               "uncitable_any": no_url + no_chunk - no_url_and_no_chunk,
               "urlless_share_of_all_claims": r4(no_url_and_chunk_present / total) if total else None,
               "uncitable_share_of_all_claims": r4((no_url + no_chunk - no_url_and_no_chunk) / total) if total else None,
               "urlless_resolve_to_urlless_stratum": resolve_hf,
               "urlless_resolve_to_other_stratum": resolve_other,
               "urlless_chunk_id_not_in_retrieved": resolve_missing,
               "drop_reason_counts": dict(drop_reasons),
               "answers_with_zero_returned_claims": sum(1 for r in recs if not (r["payload"].get("claim_attributions") or [])),
               "by_group": {}}
        for g in QTYPES + [CONTROL]:
            c = by_group[g]
            pairs = [(a, b) for a, b, gg in per_q if gg == g]
            bt = boot_ratio(pairs)
            out["by_group"][g] = {"claims": c["total"], "urlless": c["urlless"], "uncitable": c["uncitable"],
                                  "urlless_share": r4(c["urlless"] / c["total"]) if c["total"] else None,
                                  "urlless_share_ci95": bt["ci95"],
                                  "uncitable_share": r4(c["uncitable"] / c["total"]) if c["total"] else None}
            print(f"  [{name}] {g:24s} claims={c['total']:4d} urlless={c['urlless']:4d} "
                  f"share={out['by_group'][g]['urlless_share']} CI={bt['ci95']} uncitable={c['uncitable']}")
        return out
    results["5_claims"] = {"shipped": claim_stats(shipped, "shipped"),
                           "urlfirst": claim_stats(urlfirst, "urlfirst")}

    # ------------------------------------------------------------------ 6. duplication
    print("\n=== 6. DUPLICATION ===")
    hf_sha = Counter(); all_sha = Counter()
    hf_chunk_ids = Counter()
    ans_dup_hf = 0; ans_dup_any = 0; ans_dup_hf_pairs = 0
    n_hf = 0; n_unparsed = 0
    stratum_sha = defaultdict(Counter)
    for r in shipped:
        seen_hf = Counter(); seen_all = Counter()
        for c in chunks_of(r):
            m = SHA_RE.search(c.get("text") or "")
            if not m:
                n_unparsed += 1; continue
            h = m.group(1)
            all_sha[h] += 1; seen_all[h] += 1
            stratum_sha[c["metadata"].get("source_id")][h] += 1
            if c["metadata"].get("source_id") == URLLESS_SOURCE_ID:
                n_hf += 1; hf_sha[h] += 1; seen_hf[h] += 1; hf_chunk_ids[c["id"]] += 1
        if any(v > 1 for v in seen_hf.values()): ans_dup_hf += 1
        if any(v > 1 for v in seen_all.values()): ans_dup_any += 1
        ans_dup_hf_pairs += sum(v - 1 for v in seen_hf.values())
    print(f"chunks whose text field carries no sha256 = {n_unparsed}")
    print(f"URL-less retrieved chunks = {n_hf}; distinct sha256 = {len(hf_sha)}; "
          f"mean copies per distinct = {n_hf}/{len(hf_sha)} = {n_hf/len(hf_sha):.4f}; "
          f"distinct chunk ids = {len(hf_chunk_ids)}")
    print(f"URL-less sha256 seen >1 times across the sweep = {sum(1 for v in hf_sha.values() if v > 1)}; "
          f"max copies of one sha = {max(hf_sha.values())}")
    print(f"answers in which the same URL-less sha256 appears more than once = {ans_dup_hf} (of 134); "
          f"within-answer duplicate URL-less chunk occurrences (sum of copies-1) = {ans_dup_hf_pairs}")
    print(f"answers in which the same sha256 (any stratum) appears more than once = {ans_dup_any}")
    print(f"all retrieved chunks: {sum(all_sha.values())}; distinct sha256 = {len(all_sha)}; "
          f"mean copies = {sum(all_sha.values())/len(all_sha):.4f}")
    strat_dup = {}
    for sid, cnt in sorted(stratum_sha.items(), key=lambda kv: -sum(kv[1].values())):
        n = sum(cnt.values())
        strat_dup[sid] = {"retrieved": n, "distinct_sha256": len(cnt), "mean_copies": r4(n / len(cnt))}
        print(f"    {sid:26s} retrieved={n:5d} distinct={len(cnt):5d} mean_copies={n/len(cnt):.3f}")
    # URL-less claims: distinct claim strings
    hf_claims = []
    for r in shipped:
        for cl in claims_of(r):
            if not (cl.get("source_url") or "").strip() and (cl.get("chunk_id") or "").strip():
                hf_claims.append(cl.get("claim") or "")
    d_ws = len(set(norm_ws(s) for s in hf_claims))
    d_strong = len(set(norm_strong(s) for s in hf_claims))
    rep = Counter(norm_ws(s) for s in hf_claims)
    rep_n = sum(1 for v in rep.values() if v > 1)
    print(f"URL-less claims = {len(hf_claims)}; distinct after whitespace normalisation = {d_ws}; "
          f"distinct after NFC+casefold+whitespace = {d_strong}; claim strings occurring >1 = {rep_n}; "
          f"max repeats = {max(rep.values())}")
    # same for all claims, for context
    all_claims = [cl.get("claim") or "" for r in shipped for cl in claims_of(r)]
    print(f"all claims = {len(all_claims)}; distinct after whitespace normalisation = {len(set(norm_ws(s) for s in all_claims))}")
    results["6_duplication"] = {
        "chunks_without_sha": n_unparsed,
        "urlless_retrieved_chunks": n_hf, "urlless_distinct_sha256": len(hf_sha),
        "urlless_mean_copies_per_distinct": r4(n_hf / len(hf_sha)),
        "urlless_distinct_chunk_ids": len(hf_chunk_ids),
        "urlless_sha_seen_more_than_once": sum(1 for v in hf_sha.values() if v > 1),
        "urlless_max_copies_one_sha": max(hf_sha.values()),
        "answers_with_repeated_urlless_sha_within_answer": ans_dup_hf,
        "within_answer_duplicate_urlless_occurrences": ans_dup_hf_pairs,
        "answers_with_repeated_sha_any_stratum_within_answer": ans_dup_any,
        "all_retrieved_chunks": sum(all_sha.values()), "all_distinct_sha256": len(all_sha),
        "all_mean_copies": r4(sum(all_sha.values()) / len(all_sha)),
        "by_stratum": strat_dup,
        "urlless_claims": len(hf_claims), "urlless_claims_distinct_ws": d_ws,
        "urlless_claims_distinct_nfc_casefold_ws": d_strong,
        "urlless_claim_strings_repeated": rep_n, "urlless_claim_max_repeats": max(rep.values()),
        "all_claims": len(all_claims), "all_claims_distinct_ws": len(set(norm_ws(s) for s in all_claims))}

    # ------------------------------------------------------------------ 7. RQ1 bounds
    print("\n=== 7. RQ1 BOUNDS ===")
    art = sum(s["source_url"]["article_or_page"] for s in strata.values())
    iss = sum(s["source_url"]["issue_level_only"] for s in strata.values())
    none_ = sum(s["source_url"]["none"] for s in strata.values())
    print(f"census: article-level {art} + issue-level {iss} + none {none_} = {art+iss+none_} (N={N})")
    print(f"stored any-URL share = {art+iss}/{N} = {(art+iss)/N:.4f}")
    print(f"stored article-level share = {art}/{N} = {art/N:.4f}")
    print(f"stored issue-level share = {iss}/{N} = {iss/N:.4f}")
    audit = json.load(open(audit_p, encoding="utf-8"))
    pop = json.load(open(pop_p, encoding="utf-8"))
    host_rows = {h["host"]: h for h in audit["by_host"]}
    failed_hosts = sorted(h for h, v in host_rows.items() if v["measurable"] > 0 and v["reached_2xx"] == 0)
    robots_hosts = sorted(h for h, v in host_rows.items() if v["measurable"] == 0 and v["robots_blocked_unmeasurable"] > 0)
    partial_hosts = sorted((h, v["reached_2xx"], v["measurable"]) for h, v in host_rows.items()
                           if 0 < v["reached_2xx"] < v["measurable"])
    print(f"hosts with every measurable probe failing: {failed_hosts} -> population_chunks sum = "
          f"{sum(host_rows[h]['population_chunks'] for h in failed_hosts)}")
    print(f"hosts refused by robots.txt (no measurable probe): {robots_hosts} -> population_chunks sum = "
          f"{sum(host_rows[h]['population_chunks'] for h in robots_hosts)}")
    print(f"hosts with partial failure: {partial_hosts}")
    # map hosts -> strata/granularity via url_population
    host_strat = defaultdict(lambda: defaultdict(int))
    host_gran = defaultdict(lambda: defaultdict(int))
    for u in pop["urls"]:
        h = host_of(u["url"])
        host_strat[h][u["source_id"]] += u["chunks"]
        host_gran[h][u["granularity"]] += u["chunks"]
    failed_strata = Counter(); failed_gran = Counter(); robots_strata = Counter(); robots_gran = Counter()
    for h in failed_hosts:
        for sid, n in host_strat[h].items(): failed_strata[sid] += n
        for g, n in host_gran[h].items(): failed_gran[g] += n
    for h in robots_hosts:
        for sid, n in host_strat[h].items(): robots_strata[sid] += n
        for g, n in host_gran[h].items(): robots_gran[g] += n
    print(f"failed-host chunks by stratum (url_population): {dict(failed_strata)}; by granularity: {dict(failed_gran)}")
    print(f"robots-host chunks by stratum (url_population): {dict(robots_strata)}; by granularity: {dict(robots_gran)}")
    per_host_detail = {h: {"population_chunks": host_rows[h]["population_chunks"],
                           "strata": dict(host_strat[h]), "granularity": dict(host_gran[h]),
                           "probes": host_rows[h]["selected"], "reached_2xx": host_rows[h]["reached_2xx"],
                           "status_codes": host_rows[h]["status_codes"]}
                       for h in failed_hosts + robots_hosts}
    for h, v in per_host_detail.items():
        print(f"    {h:32s} {v}")
    f_art = sum(n for g, n in failed_gran.items() if g != "issue")
    r_art = sum(n for g, n in robots_gran.items() if g != "issue")
    f_tot = sum(failed_gran.values()); r_tot = sum(robots_gran.values())
    print(f"article-level share after removing failed hosts = ({art}-{f_art})/{N} = {(art-f_art)/N:.4f}")
    print(f"article-level share after removing failed + robots hosts = ({art}-{f_art}-{r_art})/{N} = {(art-f_art-r_art)/N:.4f}")
    print(f"any-URL share after removing failed hosts = ({art+iss}-{f_tot})/{N} = {(art+iss-f_tot)/N:.4f}; "
          f"after failed + robots = ({art+iss}-{f_tot}-{r_tot})/{N} = {(art+iss-f_tot-r_tot)/N:.4f}")
    # partial-failure host (cdc) contribution, for completeness
    # retrieval level
    ret_any = 0; ret_issue = 0; ret_article = 0; ret_failed = 0; ret_robots = 0; ret_partial = 0
    ret_hosts = Counter()
    per_q_any = []; per_q_art = []
    for r in shipped:
        qa = 0; qart = 0; qn = 0
        for c in chunks_of(r):
            qn += 1
            u = (c["metadata"].get("source_url") or "").strip()
            if not u: continue
            ret_any += 1; qa += 1
            h = host_of(u); ret_hosts[h] += 1
            if ISSUE_URL_RE.search(u): ret_issue += 1
            else: ret_article += 1; qart += 1
            if h in failed_hosts: ret_failed += 1
            if h in robots_hosts: ret_robots += 1
            if h in [p[0] for p in partial_hosts]: ret_partial += 1
        per_q_any.append((qa, qn)); per_q_art.append((qart, qn))
    b_any = boot_ratio(per_q_any); b_art = boot_ratio(per_q_art)
    print(f"retrieved chunks carrying any URL = {ret_any}/{tot} = {ret_any/tot:.4f} CI95 {b_any['ci95']}")
    print(f"retrieved chunks carrying an issue-pattern URL = {ret_issue}/{tot} = {ret_issue/tot:.4f}")
    print(f"retrieved chunks carrying a non-issue (article-level) URL = {ret_article}/{tot} = {ret_article/tot:.4f} CI95 {b_art['ci95']}")
    print(f"retrieved chunks whose URL host is a failed host = {ret_failed}; robots host = {ret_robots}; partial host = {ret_partial}")
    print(f"article-level retrieved share after removing failed + robots hosts = {ret_article-ret_failed-ret_robots}/{tot} = {(ret_article-ret_failed-ret_robots)/tot:.4f}")
    print(f"retrieved URL hosts (top 12): {ret_hosts.most_common(12)}")
    # same at URL-first for completeness
    uf_any = 0; uf_issue = 0
    for r in urlfirst:
        for c in chunks_of(r):
            u = (c["metadata"].get("source_url") or "").strip()
            if not u: continue
            uf_any += 1
            if ISSUE_URL_RE.search(u): uf_issue += 1
    print(f"[urlfirst] retrieved chunks with any URL = {uf_any}/{tot_u} = {uf_any/tot_u:.4f}; issue-pattern = {uf_issue} ({uf_issue/tot_u:.4f}); article-level = {uf_any-uf_issue} ({(uf_any-uf_issue)/tot_u:.4f})")
    # reachability estimates as recorded in the artifact
    reach = audit["2_http_reachability_by_chunks"]
    conf = json.load(open(conf_p, encoding="utf-8"))
    cr = conf["2_http_reachability_chunk_weighted"]
    fr = reach["primary_frozen_sample"]; ad = reach["all_probes_including_adaptive_topup"]
    print("reachability (chunk-weighted) as recorded in url_audit_report_v1.json:")
    print(f"  frozen primary sample (n={audit['provenance']['primary_sample']['n']}): Hajek point {fr['point']}, HT {fr['point_horvitz_thompson']}, "
          f"marginal projection {fr['marginal_projection']}, Bonferroni joint {fr['bonferroni_joint']}, hosts {fr['hosts']}, pop covered {fr['population_covered']}")
    print(f"  all probes incl. adaptive top-up (n={audit['provenance']['primary_sample']['n']+audit['provenance']['adaptive_topup']['n']}): Hajek point {ad['point']}, HT {ad['point_horvitz_thompson']}, "
          f"marginal projection {ad['marginal_projection']}, Bonferroni joint {ad['bonferroni_joint']}, hosts {ad['hosts']}, pop covered {ad['population_covered']}")
    print(f"  confirmatory PPS sample (url_confirmatory_estimate_v1.json, n={conf['provenance']['n_probed']}): design-based {cr['design_based']['point']} CI {cr['design_based']['ci95']}; "
          f"per-host envelope point {cr['exact_envelope_per_host']['point']} envelope {cr['exact_envelope_per_host']['envelope']}; robots-blocked chunks {conf['provenance']['robots_blocked_chunks']}")
    print(f"  robots.txt unmeasurable: {audit['unmeasurable_by_robots_txt']}")
    issue_census = audit["THE_RESULT_THAT_NEEDS_NO_ESTIMATOR"]
    print(f"  issue census: {issue_census['distinct_issue_urls']} URLs, {issue_census['chunks_behind_them']} chunks, answered {issue_census['answered_2xx']}, landed on index {issue_census['landed_on_an_issue_index']}")
    # a simple chained bound ladder (census arithmetic, no estimator)
    ladder = {
        "L0_stored_any_url": r4((art + iss) / N),
        "L1_stored_article_level": r4(art / N),
        "L2_article_level_minus_failed_hosts": r4((art - f_art) / N),
        "L3_article_level_minus_failed_and_robots_hosts": r4((art - f_art - r_art) / N),
        "L2_applied_point_reachability_adaptive": r4(art / N * ad["point"]),
        "L2_applied_point_reachability_frozen": r4(art / N * fr["point"]),
        "L2_applied_bonferroni_low_adaptive": r4(art / N * ad["bonferroni_joint"][0]),
        "L2_applied_bonferroni_high_adaptive": r4(art / N * ad["bonferroni_joint"][1]),
        "L2_applied_confirmatory_point": r4(art / N * cr["design_based"]["point"]),
    }
    print(f"bound ladder: {ladder}")
    results["7_rq1_bounds"] = {
        "census_article_level": art, "census_issue_level": iss, "census_none": none_, "N": N,
        "stored_any_url_share": r4((art + iss) / N), "stored_article_level_share": r4(art / N),
        "stored_issue_level_share": r4(iss / N),
        "failed_hosts": failed_hosts, "failed_hosts_chunks": sum(host_rows[h]["population_chunks"] for h in failed_hosts),
        "failed_hosts_by_stratum": dict(failed_strata), "failed_hosts_by_granularity": dict(failed_gran),
        "robots_hosts": robots_hosts, "robots_hosts_chunks": sum(host_rows[h]["population_chunks"] for h in robots_hosts),
        "robots_hosts_by_stratum": dict(robots_strata), "robots_hosts_by_granularity": dict(robots_gran),
        "partial_failure_hosts": [{"host": h, "reached": a, "measurable": b} for h, a, b in partial_hosts],
        "per_host_detail": per_host_detail,
        "article_share_minus_failed": r4((art - f_art) / N),
        "article_share_minus_failed_and_robots": r4((art - f_art - r_art) / N),
        "any_url_share_minus_failed": r4((art + iss - f_tot) / N),
        "any_url_share_minus_failed_and_robots": r4((art + iss - f_tot - r_tot) / N),
        "retrieval_level_shipped": {
            "any_url": ret_any, "any_url_share": r4(ret_any / tot), "any_url_ci95": b_any["ci95"],
            "issue_pattern_url": ret_issue, "issue_share": r4(ret_issue / tot),
            "article_level_url": ret_article, "article_share": r4(ret_article / tot), "article_ci95": b_art["ci95"],
            "url_on_failed_host": ret_failed, "url_on_robots_host": ret_robots, "url_on_partial_host": ret_partial,
            "article_share_minus_failed_and_robots": r4((ret_article - ret_failed - ret_robots) / tot),
            "top_hosts": ret_hosts.most_common(12)},
        "retrieval_level_urlfirst": {"any_url": uf_any, "any_url_share": r4(uf_any / tot_u),
                                     "issue_pattern_url": uf_issue, "issue_share": r4(uf_issue / tot_u),
                                     "article_level_url": uf_any - uf_issue, "article_share": r4((uf_any - uf_issue) / tot_u)},
        "reachability_recorded_in_artifact": {
            "frozen_primary": {"n": audit["provenance"]["primary_sample"]["n"], "hajek_point": fr["point"],
                               "ht_point": fr["point_horvitz_thompson"], "marginal_projection": fr["marginal_projection"],
                               "bonferroni_joint": fr["bonferroni_joint"], "hosts": fr["hosts"]},
            "all_probes_adaptive": {"n": audit["provenance"]["primary_sample"]["n"] + audit["provenance"]["adaptive_topup"]["n"],
                                    "hajek_point": ad["point"], "ht_point": ad["point_horvitz_thompson"],
                                    "marginal_projection": ad["marginal_projection"],
                                    "bonferroni_joint": ad["bonferroni_joint"], "hosts": ad["hosts"]},
            "confirmatory_pps": {"n": conf["provenance"]["n_probed"], "design_based_point": cr["design_based"]["point"],
                                 "design_based_ci95": cr["design_based"]["ci95"],
                                 "envelope_point": cr["exact_envelope_per_host"]["point"],
                                 "envelope": cr["exact_envelope_per_host"]["envelope"],
                                 "robots_blocked_chunks": conf["provenance"]["robots_blocked_chunks"]},
            "robots_unmeasurable": audit["unmeasurable_by_robots_txt"],
            "issue_census": {k: issue_census[k] for k in ["distinct_issue_urls", "chunks_behind_them", "answered_2xx", "landed_on_an_issue_index"]}},
        "bound_ladder": ladder}

    with open(f"{out_dir}/tierA_retrieval_results.json", "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)
    print(f"\nwrote {out_dir}/tierA_retrieval_results.json")


if __name__ == "__main__":
    main(sys.argv)
