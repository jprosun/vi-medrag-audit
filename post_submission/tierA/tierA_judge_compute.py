"""Tier A computations for the EDAS 1571353709 revision.

Usage:
    python -I -X utf8 tierA_compute.py <repo_root> <out_dir>

Everything is recomputed from the released artifact files (treated as data). Nothing from
the artifact's own scripts is executed. All formulas are stated in the printed output and in
the results JSON.
"""
from __future__ import annotations

import collections
import hashlib
import json
import math
import random
import re
import sys
from pathlib import Path

import numpy as np

REPO = Path(sys.argv[1])
OUT = Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)

RIVF = REPO / "benchmark/rivf"
TR = REPO / "benchmark/datasets/test_results"
CAP = {
    "shipped": TR / "pilot_span_exposure_rivf134_2026-09-05_091659_raw.jsonl",
    "url_first": TR / "pilot_span_exposure_urlfirst_2026-09-07_035612_raw.jsonl",
}
PROBES = REPO / "benchmark/datasets/probe_queries_v2.jsonl"
URLLESS = "hf_vi_mtue29_medical"
CONTROL_SPECIALTY = "out_of_corpus_control"
RESAMPLES = 5000
SEED = 0
POS = {"entailment": "supported", "relevance": "relevant"}
LABELS = {
    "entailment": ["supported", "overstated", "not_supported", "unintelligible"],
    "relevance": ["relevant", "partial", "not_relevant"],
}

R: dict = {"formulas": {}, "notes": []}


def say(*a):
    print(*a, flush=True)


def jload(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def jsonl(p: Path):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ----------------------------------------------------------------------------- questions
probes = jsonl(PROBES)
Q = {}
for r in probes:
    spec, qtype = r["source"].split(":", 1)[1].split("/")
    Q[r["query_id"]] = {"specialty": spec, "type": qtype, "is_control": spec == CONTROL_SPECIALTY}
QIDS = [r["query_id"] for r in probes]
assert len(QIDS) == 134 and len(set(QIDS)) == 134
CONTROLS = sorted(q for q in QIDS if Q[q]["is_control"])
ANSWERABLE = [q for q in QIDS if not Q[q]["is_control"]]
R["questions"] = {
    "n": len(QIDS),
    "controls_marked_by": "probe_queries_v2.jsonl: source == 'rivf_grid_v2:out_of_corpus_control/<type>'",
    "n_controls": len(CONTROLS),
    "n_answerable": len(ANSWERABLE),
    "control_query_ids": CONTROLS,
    "n_per_type_all134": dict(collections.Counter(Q[q]["type"] for q in QIDS)),
    "n_per_type_controls": dict(collections.Counter(Q[q]["type"] for q in CONTROLS)),
    "n_per_type_answerable119": dict(collections.Counter(Q[q]["type"] for q in ANSWERABLE)),
}
say("== questions:", json.dumps(R["questions"], ensure_ascii=False))

# ----------------------------------------------------------------------------- captures
CAPS = {}
for arm, p in CAP.items():
    rows = jsonl(p)
    assert len(rows) == 134
    d = {}
    for r in rows:
        pl = r["payload"]
        md = pl["metadata"]
        chunks = pl["retrieved_chunks"]
        cmap = {c["id"]: c["metadata"].get("source_id") for c in chunks}
        attrs = pl.get("claim_attributions") or []
        dropped = pl.get("dropped_claims") or []
        d[r["query_id"]] = {
            "answer_mode": md.get("answer_mode"),
            "retrieval_profile": md["pipeline"].get("retrieval_profile"),
            "llm_extractor_used": md["pipeline"].get("llm_extractor_used"),
            "retrieval_top_k": md["pipeline"].get("retrieval_top_k"),
            "claims_total": md["claims_total"],
            "claims_displayed": md["claims_displayed"],
            "claims_dropped": md["claims_dropped"],
            "verification_status": md.get("verification_status"),
            "n_chunks": len(chunks),
            "n_chunks_urlless": sum(1 for c in chunks if c["metadata"].get("source_id") == URLLESS),
            "returned_claims": [c["claim"] for c in attrs],
            "all_claims": [(c, cmap) for c in attrs + dropped],
            "drop_reasons": collections.Counter(c.get("drop_reason") for c in dropped),
        }
        assert md["claims_displayed"] == len(attrs), (arm, r["query_id"])
        assert md["claims_total"] == len(attrs) + len(dropped), (arm, r["query_id"])
        assert len(set(c["claim"] for c in attrs)) == len(attrs), "duplicate claim text in one answer"
    CAPS[arm] = d
    assert set(d) == set(QIDS)

# sanity checks against the paper
san = {}
for arm, d in CAPS.items():
    tot_chunks = sum(v["n_chunks"] for v in d.values())
    urlless = sum(v["n_chunks_urlless"] for v in d.values())
    n_claims = sum(v["claims_total"] for v in d.values())
    n_ret = sum(v["claims_displayed"] for v in d.values())
    zero = sum(1 for v in d.values() if v["claims_displayed"] == 0)
    unc_urlless = unc_unres = 0
    for v in d.values():
        for c, cmap in v["all_claims"]:
            cid = c.get("chunk_id")
            if not cid or cid not in cmap:
                unc_unres += 1
            elif cmap[cid] == URLLESS:
                unc_urlless += 1
    san[arm] = {
        "retrieved_chunks": tot_chunks,
        "retrieved_from_urlless_stratum": urlless,
        "share_urlless": round(urlless / tot_chunks, 4),
        "claims_extracted": n_claims,
        "claims_returned": n_ret,
        "answers_with_zero_returned_claims": zero,
        "uncitable_claims": unc_urlless + unc_unres,
        "uncitable_urlless": unc_urlless,
        "uncitable_chunk_unresolvable": unc_unres,
        "drop_reason_counts": dict(sum((v["drop_reasons"] for v in d.values()), collections.Counter())),
        "answer_mode_values": dict(collections.Counter(v["answer_mode"] for v in d.values())),
        "retrieval_profile_values": dict(collections.Counter(v["retrieval_profile"] for v in d.values())),
    }
R["sanity_vs_paper"] = san
say("== sanity:", json.dumps(san, ensure_ascii=False, indent=1))
# profiles identical per question across arms?
same_prof = all(CAPS["shipped"][q]["retrieval_profile"] == CAPS["url_first"][q]["retrieval_profile"] for q in QIDS)
R["profile_identical_per_question_across_arms"] = same_prof
PROFILE = {q: CAPS["shipped"][q]["retrieval_profile"] for q in QIDS}
R["notes"].append(
    "metadata.answer_mode is 'standard' for all 134 records in both arms, so it cannot split "
    "standard vs deep. The paper's standard/deep profile is metadata.pipeline.retrieval_profile "
    "(67/67, identical per question in both arms); that field is used wherever 'answer_mode' "
    "was requested, and the literal answer_mode split is reported beside it."
)

# ----------------------------------------------------------------------------- judgements
def resolve(blob: dict, override: dict | None = None) -> dict:
    """Final label: pass A when A == B, otherwise the adjudicated label (override replaces it)."""
    a = {j["item_id"]: j["label"] for j in blob["pass_a"]}
    b = {j["item_id"]: j["label"] for j in blob["pass_b"]}
    adj = {j["item_id"]: j["label"] for j in blob.get("adjudication", [])}
    if override:
        adj.update(override)
    out = {}
    for i in a:
        if i not in b:
            continue
        if a[i] == b[i]:
            out[i] = a[i]
        else:
            assert i in adj, f"disagreement without adjudication: {i}"
            out[i] = adj[i]
    return out


def kappa(blob: dict, ids, labels):
    a = {j["item_id"]: j["label"] for j in blob["pass_a"]}
    b = {j["item_id"]: j["label"] for j in blob["pass_b"]}
    ids = [i for i in ids if i in a and i in b]
    n = len(ids)
    agree = sum(1 for i in ids if a[i] == b[i])
    ca = collections.Counter(a[i] for i in ids)
    cb = collections.Counter(b[i] for i in ids)
    po = agree / n
    pe = sum((ca[l] / n) * (cb[l] / n) for l in labels)
    k = (po - pe) / (1 - pe) if pe < 1 else float("nan")
    conf = {la: {lb: sum(1 for i in ids if a[i] == la and b[i] == lb) for lb in labels} for la in labels}
    return {
        "n": n, "agree": agree, "raw_agreement": round(po, 4), "p_e": round(pe, 4), "kappa": round(k, 4),
        "pass_a_distribution": {l: ca[l] for l in labels}, "pass_b_distribution": {l: cb[l] for l in labels},
        "confusion_a_rows_b_cols": conf,
    }


R["formulas"]["cohen_kappa"] = (
    "p_o = (#items with label_A == label_B)/n; p_e = sum_k (n_Ak/n)(n_Bk/n) over the label set; "
    "kappa = (p_o - p_e)/(1 - p_e). Label sets: entailment {supported, overstated, not_supported, "
    "unintelligible}; relevance {relevant, partial, not_relevant}."
)

KEY = {
    ("shipped", "entailment"): jload(RIVF / "entailment_key_v1.json")["key"],
    ("shipped", "relevance"): jload(RIVF / "relevance_model_key_v1.json")["key"],
    ("url_first", "entailment"): jload(RIVF / "entailment_key_urlfirst_v1.json")["key"],
    ("url_first", "relevance"): jload(RIVF / "relevance_model_key_urlfirst_v1.json")["key"],
}
ITEMS = {
    ("shipped", "entailment"): {r["item_id"]: r for r in jsonl(RIVF / "entailment_items_v1.jsonl")},
    ("shipped", "relevance"): {r["item_id"]: r for r in jsonl(RIVF / "relevance_model_items_v1.jsonl")},
    ("url_first", "entailment"): {r["item_id"]: r for r in jsonl(RIVF / "entailment_items_urlfirst_v1.jsonl")},
    ("url_first", "relevance"): {r["item_id"]: r for r in jsonl(RIVF / "relevance_model_items_urlfirst_v1.jsonl")},
}
JUDGE = {
    ("shipped", "entailment", "original"): jload(RIVF / "entailment_judgements_v1.json"),
    ("shipped", "relevance", "original"): jload(RIVF / "relevance_model_judgements_v1.json"),
    ("url_first", "entailment", "original"): jload(RIVF / "entailment_judgements_urlfirst_v1.json"),
    ("url_first", "relevance", "original"): jload(RIVF / "relevance_model_judgements_urlfirst_v1.json"),
}
MATCHED = jload(RIVF / "arm_matched_rejudge_v1.json")["result"]
for ins in ("entailment", "relevance"):
    JUDGE[("url_first", ins, "matched")] = MATCHED["instruments"][ins]
PINNED = jload(RIVF / "judge_rerun_pinned_v1.json")["instruments"]
REMATCH = {ins: {j["item_id"]: j["label"] for j in MATCHED["shipped_rematch"][ins]} for ins in ("entailment", "relevance")}
for ins in ("entailment", "relevance"):
    JUDGE[("shipped", ins, "pinned_rematch")] = PINNED[ins]

# item -> (query_id, claim) for the REAL items; verify the mapping against the captures
ITEM_CLAIM = {}
for (arm, ins), key in KEY.items():
    items = ITEMS[(arm, ins)]
    m = {}
    for iid, k in key.items():
        if k["kind"] != "real":
            continue
        q = k["query_id"]
        claim = items[iid]["claim"]
        assert claim in CAPS[arm][q]["returned_claims"], (arm, ins, iid)
        assert items[iid]["question"] == next(r["question"] for r in probes if r["query_id"] == q)
        m[iid] = (q, claim)
    # one real item per returned claim
    pairs = collections.Counter(m.values())
    assert all(v == 1 for v in pairs.values())
    assert sorted(pairs) == sorted((q, c) for q in QIDS for c in CAPS[arm][q]["returned_claims"])
    ITEM_CLAIM[(arm, ins)] = m
R["notes"].append(
    "Mapping check passed: in every (arm, instrument) the real items map one-to-one onto the "
    "capture's returned claims by (query_id, claim text); control items are identified by "
    "key[item].kind == 'control'."
)

# ----------------------------------------------------------------------------- task 1
T1 = {}
for (arm, ins, src), blob in JUDGE.items():
    key = KEY[(arm, ins)]
    all_ids = sorted(j["item_id"] for j in blob["pass_a"])
    real_ids = [i for i in all_ids if key[i]["kind"] == "real"]
    ctrl_ids = [i for i in all_ids if key[i]["kind"] == "control"]
    T1[f"{arm}/{ins}/{src}"] = {
        "all_items": kappa(blob, all_ids, LABELS[ins]),
        "real_claims_only": kappa(blob, real_ids, LABELS[ins]),
        "controls_only": kappa(blob, ctrl_ids, LABELS[ins]),
        "counts_recorded_in_file": blob.get("counts"),
    }
R["task1_agreement_kappa"] = T1
say("== TASK 1 agreement/kappa")
for k, v in T1.items():
    say(f"  {k}: ALL n={v['all_items']['n']} agree={v['all_items']['agree']} raw={v['all_items']['raw_agreement']} "
        f"pe={v['all_items']['p_e']} kappa={v['all_items']['kappa']} | REAL n={v['real_claims_only']['n']} "
        f"agree={v['real_claims_only']['agree']} raw={v['real_claims_only']['raw_agreement']} "
        f"pe={v['real_claims_only']['p_e']} kappa={v['real_claims_only']['kappa']}")
    say(f"     A dist all: {v['all_items']['pass_a_distribution']}  B dist all: {v['all_items']['pass_b_distribution']}")
    say(f"     A dist real: {v['real_claims_only']['pass_a_distribution']}  B dist real: {v['real_claims_only']['pass_b_distribution']}")

# ----------------------------------------------------------------------------- final labels per claim
# FINAL[(arm, ins, src)] = {query_id: {claim: label}}
FINAL = {}
for (arm, ins, src), blob in JUDGE.items():
    override = REMATCH[ins] if src == "pinned_rematch" else None
    fl = resolve(blob, override)
    m = ITEM_CLAIM[(arm, ins)]
    per_q = collections.defaultdict(dict)
    for iid, (q, claim) in m.items():
        per_q[q][claim] = fl[iid]
    FINAL[(arm, ins, src)] = per_q
    # control labels for the record
    key = KEY[(arm, ins)]
    ctrl = collections.Counter(fl[i] for i in fl if key[i]["kind"] == "control")
    T1[f"{arm}/{ins}/{src}"]["final_label_distribution_controls"] = dict(ctrl)
    T1[f"{arm}/{ins}/{src}"]["final_label_distribution_real"] = dict(
        collections.Counter(fl[i] for i in fl if key[i]["kind"] == "real"))


def rate_block(arm, ins, src, qs):
    per_q = FINAL[(arm, ins, src)]
    labs = [l for q in qs for l in per_q.get(q, {}).values()]
    n = len(labs)
    c = collections.Counter(labs)
    out = {"n_claims": n, "n_questions": len(qs), "n_questions_with_claims": sum(1 for q in qs if per_q.get(q))}
    for l in LABELS[ins]:
        out[l] = c[l]
        out[f"rate_{l}"] = round(c[l] / n, 4) if n else None
    return out


# ----------------------------------------------------------------------------- task 2
T2 = {}
SRC_SETS = {
    "shipped_original": ("shipped", "original"),
    "shipped_pinned_rematch(secondary)": ("shipped", "pinned_rematch"),
    "url_first_matched(primary for URL-first)": ("url_first", "matched"),
    "url_first_original(secondary)": ("url_first", "original"),
}
for name, (arm, src) in SRC_SETS.items():
    block = {}
    for ins in ("entailment", "relevance"):
        b = {
            "all_134": rate_block(arm, ins, src, QIDS),
            "answerable_119": rate_block(arm, ins, src, ANSWERABLE),
            "controls_15": rate_block(arm, ins, src, CONTROLS),
            "by_retrieval_profile": {
                p: rate_block(arm, ins, src, [q for q in QIDS if PROFILE[q] == p]) for p in ("standard", "deep")},
            "by_retrieval_profile_answerable": {
                p: rate_block(arm, ins, src, [q for q in ANSWERABLE if PROFILE[q] == p]) for p in ("standard", "deep")},
            "by_answer_mode_literal": {
                m: rate_block(arm, ins, src, [q for q in QIDS if CAPS[arm][q]["answer_mode"] == m])
                for m in sorted(set(CAPS[arm][q]["answer_mode"] for q in QIDS))},
        }
        block[ins] = b
    T2[name] = block
R["task2_final_label_rates"] = T2
R["formulas"]["final_label"] = "label = pass_a label if pass_a == pass_b else the adjudicated label (for shipped pinned_rematch the matched-run re-adjudication replaces the pinned run's adjudication)."
R["formulas"]["rates"] = "support rate = #supported / #returned claims in the subset; responsiveness = #relevant / #returned claims; partial and not_relevant likewise."
say("== TASK 2 final-label rates")
for name, block in T2.items():
    for ins in ("entailment", "relevance"):
        b = block[ins]
        say(f"  {name} / {ins}: all134 {json.dumps(b['all_134'])}")
        say(f"      answerable119 {json.dumps(b['answerable_119'])}")
        say(f"      controls15 {json.dumps(b['controls_15'])}")
        for p in ("standard", "deep"):
            say(f"      profile={p} {json.dumps(b['by_retrieval_profile'][p])}")
            say(f"      profile={p} answerable {json.dumps(b['by_retrieval_profile_answerable'][p])}")
        say(f"      answer_mode literal {json.dumps(b['by_answer_mode_literal'])}")

# answer-level counts (paper: '5 of 55 answers ... carry one that answers and 12 only unrelated')
ANS = {}
for name, (arm, src) in SRC_SETS.items():
    per_q = FINAL[(arm, "relevance", src)]
    with_claims = [q for q in QIDS if per_q.get(q)]
    any_rel = sum(1 for q in with_claims if any(l == "relevant" for l in per_q[q].values()))
    only_unrel = sum(1 for q in with_claims if all(l == "not_relevant" for l in per_q[q].values()))
    ANS[name] = {"answers_with_claims": len(with_claims), "answers_with_a_relevant_claim": any_rel,
                 "answers_with_only_not_relevant_claims": only_unrel}
R["task2_answer_level_relevance"] = ANS
say("  answer-level:", json.dumps(ANS))

# joint entailment x relevance per claim (paper: '52 unrelated, 49 of them supported'; '78 ... against 40')
JOINT = {}
for name, (arm, src) in SRC_SETS.items():
    pe = FINAL[(arm, "entailment", src)]
    pr = FINAL[(arm, "relevance", src)]
    ct = collections.Counter()
    for q in QIDS:
        for claim, el in pe.get(q, {}).items():
            ct[(el, pr[q][claim])] += 1
    JOINT[name] = {f"{e}|{r}": n for (e, r), n in sorted(ct.items())}
    JOINT[name]["supported_and_not_relevant"] = ct[("supported", "not_relevant")]
R["task2_joint_entailment_x_relevance"] = JOINT
say("  joint ent x rel:", json.dumps(JOINT))

# ----------------------------------------------------------------------------- bootstrap helpers
R["formulas"]["cluster_bootstrap"] = (
    f"Percentile cluster bootstrap: the resampling unit is the question. For B={RESAMPLES} resamples "
    f"(random.Random({SEED}), questions drawn with replacement, k = number of questions in the group), "
    "the statistic is recomputed as a RATIO OF SUMS over the drawn questions (all claims of a drawn "
    "question move together). CI95 = [2.5th, 97.5th] percentile of the B draws (numpy.percentile, "
    "linear interpolation). Paired statistics draw the SAME questions for both arms. "
    "SE = sample standard deviation (ddof=1) of the B draws."
)


def boot(qs, stat, seed=SEED, resamples=RESAMPLES):
    """stat(list_of_qids) -> float or None. Returns point, ci, se, draws used."""
    qs = list(qs)
    k = len(qs)
    rng = random.Random(seed)
    point = stat(qs)
    draws = []
    for _ in range(resamples):
        sel = [qs[rng.randrange(k)] for _ in range(k)]
        v = stat(sel)
        if v is not None:
            draws.append(v)
    arr = np.array(draws, dtype=float)
    lo, hi = np.percentile(arr, [2.5, 97.5])
    return {"point": round(point, 4) if point is not None else None,
            "ci95": [round(float(lo), 4), round(float(hi), 4)],
            "se_bootstrap": round(float(arr.std(ddof=1)), 5),
            "draws_used": int(len(arr)), "clusters": k, "seed": seed}


def ratio_of_sums(num, den):
    def f(sel):
        d = sum(den[q] for q in sel)
        return (sum(num[q] for q in sel) / d) if d else None
    return f


# ----------------------------------------------------------------------------- task 3 retention
T3 = {}
for arm, d in CAPS.items():
    num = {q: d[q]["claims_displayed"] for q in QIDS}
    den = {q: d[q]["claims_total"] for q in QIDS}
    arm_out = {}
    for scope, qs in (("all_134", QIDS), ("answerable_119", ANSWERABLE)):
        sc = {"overall": boot(qs, ratio_of_sums(num, den))}
        sc["overall"].update({"claims_displayed": sum(num[q] for q in qs), "claims_total": sum(den[q] for q in qs)})
        by_type = {}
        for t in sorted(set(Q[q]["type"] for q in qs)):
            g = [q for q in qs if Q[q]["type"] == t]
            b = boot(g, ratio_of_sums(num, den))
            b.update({"n_questions": len(g), "claims_displayed": sum(num[q] for q in g), "claims_total": sum(den[q] for q in g)})
            by_type[t] = b
        pts = {t: v["point"] for t, v in by_type.items()}
        tmax = max(pts, key=pts.get)
        tmin = min(pts, key=pts.get)
        sc["by_type"] = by_type
        sc["type_max"] = {"type": tmax, "retention": pts[tmax]}
        sc["type_min"] = {"type": tmin, "retention": pts[tmin]}
        sc["max_over_min_ratio"] = round(pts[tmax] / pts[tmin], 3) if pts[tmin] else None
        by_prof = {}
        for p in ("standard", "deep"):
            g = [q for q in qs if PROFILE[q] == p]
            b = boot(g, ratio_of_sums(num, den))
            b.update({"n_questions": len(g), "claims_displayed": sum(num[q] for q in g), "claims_total": sum(den[q] for q in g)})
            by_prof[p] = b
        sc["by_retrieval_profile"] = by_prof
        arm_out[scope] = sc
    T3[arm] = arm_out
R["task3_retention"] = T3
R["formulas"]["retention"] = "retention = sum_q claims_displayed(q) / sum_q claims_total(q) over the questions in the group (ratio of sums); max/min ratio = highest type retention / lowest type retention."
say("== TASK 3 retention")
for arm, ao in T3.items():
    for scope, sc in ao.items():
        say(f"  {arm} {scope} overall {sc['overall']['claims_displayed']}/{sc['overall']['claims_total']} = {sc['overall']['point']} CI {sc['overall']['ci95']}")
        for t, b in sc["by_type"].items():
            say(f"      type {t:24} nq={b['n_questions']:3} {b['claims_displayed']:3}/{b['claims_total']:3} = {b['point']} CI {b['ci95']}")
        say(f"      max {sc['type_max']} min {sc['type_min']} ratio {sc['max_over_min_ratio']}")
        for p, b in sc["by_retrieval_profile"].items():
            say(f"      profile {p:8} nq={b['n_questions']:3} {b['claims_displayed']:3}/{b['claims_total']:3} = {b['point']} CI {b['ci95']}")

# ----------------------------------------------------------------------------- task 4 zero-claim answers
T4 = {}
zero = {arm: {q: int(CAPS[arm][q]["claims_displayed"] == 0) for q in QIDS} for arm in CAPS}
one = {q: 1 for q in QIDS}
for scope, qs in (("all_134", QIDS), ("answerable_119", ANSWERABLE)):
    sc = {}
    for arm in CAPS:
        b = boot(qs, ratio_of_sums(zero[arm], one))
        b["count"] = sum(zero[arm][q] for q in qs)
        sc[arm] = b
    diff = boot(qs, lambda sel: (sum(zero["url_first"][q] for q in sel) - sum(zero["shipped"][q] for q in sel)) / len(sel))
    diff["count_difference"] = sc["url_first"]["count"] - sc["shipped"]["count"]
    sc["difference_url_first_minus_shipped"] = diff
    sc["crosstab"] = {
        "zero_in_both": sum(1 for q in qs if zero["shipped"][q] and zero["url_first"][q]),
        "zero_shipped_only": sum(1 for q in qs if zero["shipped"][q] and not zero["url_first"][q]),
        "zero_url_first_only": sum(1 for q in qs if not zero["shipped"][q] and zero["url_first"][q]),
        "claims_in_both": sum(1 for q in qs if not zero["shipped"][q] and not zero["url_first"][q]),
    }
    T4[scope] = sc
R["task4_zero_claim_answers"] = T4
R["formulas"]["zero_claim"] = "proportion = #questions with claims_displayed == 0 / #questions; paired difference = proportion(URL-first) - proportion(shipped) on the same drawn questions."
say("== TASK 4 zero-claim answers")
say(json.dumps(T4, indent=1))

# ----------------------------------------------------------------------------- task 5 within-question comparison
def per_q_counts(arm, ins, src):
    per_q = FINAL[(arm, ins, src)]
    n = {q: len(per_q.get(q, {})) for q in QIDS}
    pos = {q: sum(1 for l in per_q.get(q, {}).values() if l == POS[ins]) for q in QIDS}
    return n, pos


T5 = {}
PAIRINGS = {
    "primary: shipped_original vs url_first_matched": (("shipped", "original"), ("url_first", "matched")),
    "secondary: shipped_pinned_rematch vs url_first_matched (artifact's matched contrast)": (("shipped", "pinned_rematch"), ("url_first", "matched")),
    "secondary: shipped_original vs url_first_original (confounded)": (("shipped", "original"), ("url_first", "original")),
}
for pname, ((sa, ss), (ua, us)) in PAIRINGS.items():
    pb = {}
    for ins in ("entailment", "relevance"):
        n_s, p_s = per_q_counts(sa, ins, ss)
        n_u, p_u = per_q_counts(ua, ins, us)
        both = [q for q in QIDS if n_s[q] > 0 and n_u[q] > 0]
        uf_only = [q for q in QIDS if n_s[q] == 0 and n_u[q] > 0]
        sh_only = [q for q in QIDS if n_s[q] > 0 and n_u[q] == 0]
        neither = [q for q in QIDS if n_s[q] == 0 and n_u[q] == 0]

        def pooled_diff(sel):
            ds, du = sum(n_s[q] for q in sel), sum(n_u[q] for q in sel)
            if not ds or not du:
                return None
            return sum(p_u[q] for q in sel) / du - sum(p_s[q] for q in sel) / ds

        def mean_perq_diff(sel):
            return float(np.mean([p_u[q] / n_u[q] - p_s[q] / n_s[q] for q in sel]))

        def rates(qs, n, p):
            d = sum(n[q] for q in qs)
            return {"n_claims": d, "positives": sum(p[q] for q in qs), "rate": round(sum(p[q] for q in qs) / d, 4) if d else None}

        block = {
            "set_sizes": {"claims_in_both_arms": len(both), "url_first_only": len(uf_only), "shipped_only": len(sh_only), "neither": len(neither)},
            "on_both_set": {
                "shipped": rates(both, n_s, p_s), "url_first": rates(both, n_u, p_u),
                "pooled_difference_uf_minus_shipped_paired_bootstrap": boot(both, pooled_diff),
                "mean_per_question_difference_paired_bootstrap": boot(both, mean_perq_diff),
                "per_question_sign": {
                    "uf_higher": sum(1 for q in both if p_u[q] / n_u[q] > p_s[q] / n_s[q]),
                    "shipped_higher": sum(1 for q in both if p_u[q] / n_u[q] < p_s[q] / n_s[q]),
                    "tied": sum(1 for q in both if p_u[q] / n_u[q] == p_s[q] / n_s[q]),
                },
            },
            "url_first_only_questions": {"url_first": rates(uf_only, n_u, p_u)},
            "shipped_only_questions": {"shipped": rates(sh_only, n_s, p_s)},
            "all_134_pooled_difference_paired_bootstrap": boot(QIDS, pooled_diff),
        }
        # label breakdown on the UF-only questions
        per_q_u = FINAL[(ua, ins, us)]
        block["url_first_only_questions"]["label_counts"] = dict(collections.Counter(l for q in uf_only for l in per_q_u.get(q, {}).values()))
        per_q_s = FINAL[(sa, ins, ss)]
        block["shipped_only_questions"]["label_counts"] = dict(collections.Counter(l for q in sh_only for l in per_q_s.get(q, {}).values()))
        pb[ins] = block
    T5[pname] = pb
R["task5_within_question"] = T5
R["formulas"]["task5"] = (
    "both-set = questions with >=1 returned claim in BOTH arms. Pooled difference = "
    "(sum positives_UF / sum n_UF) - (sum positives_shipped / sum n_shipped) over the drawn questions; "
    "mean per-question difference = mean_q [positives_UF(q)/n_UF(q) - positives_shipped(q)/n_shipped(q)]. "
    "Both use the paired cluster bootstrap (same drawn questions in both arms)."
)
say("== TASK 5 within-question")
for pname, pb in T5.items():
    for ins, block in pb.items():
        say(f"  {pname} / {ins}: sets {block['set_sizes']}")
        ob = block["on_both_set"]
        say(f"      both-set shipped {ob['shipped']} UF {ob['url_first']}")
        say(f"      pooled diff {ob['pooled_difference_uf_minus_shipped_paired_bootstrap']}")
        say(f"      mean per-q diff {ob['mean_per_question_difference_paired_bootstrap']} signs {ob['per_question_sign']}")
        say(f"      UF-only {block['url_first_only_questions']}  shipped-only {block['shipped_only_questions']}")
        say(f"      all-134 pooled diff {block['all_134_pooled_difference_paired_bootstrap']}")

# ----------------------------------------------------------------------------- task 6 MDD
Z = 1.959963984540054 + 0.8416212335729143  # z_{0.975} + z_{0.80}
T6 = {"multiplier": round(Z, 4), "formula": "MDD = (z_{1-alpha/2} + z_{power}) x SE = (1.960 + 0.842) x SE = 2.80 x SE; relative = MDD / 0.036"}
for pname, pb in T5.items():
    e = {}
    for ins in ("entailment", "relevance"):
        for which, key in (("all_134", "all_134_pooled_difference_paired_bootstrap"),):
            se = pb[ins][key]["se_bootstrap"]
            e[f"{ins}/{which}"] = {"se": se, "mdd_2.80se": round(2.80 * se, 4), "mdd_exact_z": round(Z * se, 4),
                                   "relative_to_0.036": round(2.80 * se / 0.036, 3) if ins == "relevance" else None}
        se = pb[ins]["on_both_set"]["pooled_difference_uf_minus_shipped_paired_bootstrap"]["se_bootstrap"]
        e[f"{ins}/both_set"] = {"se": se, "mdd_2.80se": round(2.80 * se, 4), "mdd_exact_z": round(Z * se, 4),
                                "relative_to_0.036": round(2.80 * se / 0.036, 3) if ins == "relevance" else None}
    T6[pname] = e
R["task6_mdd"] = T6
say("== TASK 6 MDD")
say(json.dumps(T6, indent=1))

# ----------------------------------------------------------------------------- task 7 verifier verdicts
T7 = {}
for arm, d in CAPS.items():
    vs = collections.Counter(v["verification_status"] for v in d.values())
    ct = collections.Counter((v["verification_status"], "has_claims" if v["claims_displayed"] > 0 else "zero_claims") for v in d.values())
    T7[arm] = {"verdicts": dict(vs), "crosstab_verdict_x_has_returned_claims": {f"{a}|{b}": n for (a, b), n in sorted(ct.items())},
               "verdicts_answerable_119": dict(collections.Counter(d[q]["verification_status"] for q in ANSWERABLE)),
               "verdicts_controls_15": dict(collections.Counter(d[q]["verification_status"] for q in CONTROLS))}
    blocked = [q for q in QIDS if d[q]["verification_status"] == "block"]
    if blocked:
        T7[arm]["blocked_query_ids"] = {q: {"claims_displayed": d[q]["claims_displayed"], "claims_total": d[q]["claims_total"], "type": Q[q]["type"], "is_control": Q[q]["is_control"]} for q in blocked}
R["task7_verifier"] = T7
say("== TASK 7 verifier", json.dumps(T7, indent=1))

# ----------------------------------------------------------------------------- task 8 prompt provenance
def norm_ws(s):
    return re.sub(r"\s+", " ", s)


def sentence_with(text, needle):
    flat = norm_ws(text)
    m = re.search(r"[^.]*" + re.escape(needle) + r"[^.]*\.", flat)
    return m.group(0).strip() if m else None


jc = (RIVF / "judging/JUDGE-CONFIGURATION.md").read_text(encoding="utf-8")
prompt_txt_p = RIVF / "judging/relevance_prompt_v1.txt"
prompt_txt = prompt_txt_p.read_text(encoding="utf-8")
prompt_bytes = prompt_txt_p.read_bytes()
shipped_js = (RIVF / "judging/relevance-judgement-shipped.js").read_text(encoding="utf-8")
uf_js = (RIVF / "judging/relevance-judgement-urlfirst.js").read_text(encoding="utf-8")
rej_js = (RIVF / "judging/matched-arm-rejudge.js").read_text(encoding="utf-8")
m = re.search(r"const CODEBOOK = `(.*?)`\n", shipped_js, re.S)
codebook_js = m.group(1)
m2 = re.search(r"const CODEBOOK = `(.*?)`\n", uf_js, re.S)
codebook_uf_js = m2.group(1)
rerun_cmp = jload(RIVF / "judge_rerun_comparison_v1.json")
T8 = {
    "judge_configuration_md_sentence": sentence_with(jc, "96.8"),
    "relevance_prompt_v1_txt_sentence": sentence_with(prompt_txt, "96.8%"),
    "relevance_judgement_shipped_js_sentence": sentence_with(codebook_js, "96.8%"),
    "relevance_judgement_urlfirst_js_counterpart_sentence": sentence_with(codebook_uf_js, "A separate measurement"),
    "urlfirst_original_codebook_contains_96.8": "96.8" in codebook_uf_js,
    "byte_check": {
        "prompt_file_sha256": sha256(prompt_txt_p),
        "prompt_file_bytes": len(prompt_bytes),
        "prompt_file_has_crlf": b"\r\n" in prompt_bytes,
        "shipped_js_CODEBOOK_literal_sha256_raw": hashlib.sha256(codebook_js.encode("utf-8")).hexdigest(),
        "shipped_js_CODEBOOK_literal_sha256_stripped_outer_newlines": hashlib.sha256(codebook_js.strip("\n").encode("utf-8")).hexdigest(),
        "prompt_file_sha256_stripped_outer_newlines": hashlib.sha256(prompt_txt.strip("\n").encode("utf-8")).hexdigest(),
        "prompt_txt_equals_js_literal_raw": prompt_txt == codebook_js,
        "prompt_txt_equals_js_literal_modulo_outer_newlines": prompt_txt.strip("\n") == codebook_js.strip("\n"),
        "prompt_txt_equals_js_literal_modulo_outer_newlines_and_crlf": prompt_txt.replace("\r\n", "\n").strip("\n") == codebook_js.replace("\r\n", "\n").strip("\n"),
        "hash_recorded_in_judge_rerun_comparison_v1.prompts_held_constant.relevance": rerun_cmp["provenance"]["prompts_held_constant"]["relevance"],
    },
    "matched_rejudge_js_evidence": {
        "cfg_prompt_line": next(l.strip() for l in rej_js.splitlines() if "relevance_prompt_v1.txt" in l),
        "instruction_line": next(l.strip() for l in rej_js.splitlines() if "follow it exactly as your codebook" in l),
        "header_comment_lines": [l.strip() for l in rej_js.splitlines() if "96.8" in l or "byte for byte" in l],
    },
    "arm_matched_rejudge_v1_json_codebook_source": MATCHED["codebook_source"],
    "arm_matched_rejudge_v1_json_what_this_is": MATCHED["what_this_is"],
    "delivery_difference": (
        "In the shipped run the codebook text was inlined into each judge's prompt (template literal CODEBOOK); "
        "in the matched re-judge each judge was told to read judging/relevance_prompt_v1.txt and follow it. "
        "The codebook TEXT is byte-identical modulo the template literal's outer newlines (see byte_check); "
        "the surrounding task wording and the served model (claude-fable-5-1 for the shipped relevance run, "
        "claude-opus-5 for the matched re-judge) are not identical."
    ),
}
# model served per run from JUDGE-CONFIGURATION table
T8["served_models_quoted_from_JUDGE_CONFIGURATION"] = [l.strip() for l in jc.splitlines() if l.strip().startswith("| Relevance") or l.strip().startswith("| The pinned") or l.strip().startswith("| Entailment")]
R["task8_prompt_provenance"] = T8
say("== TASK 8", json.dumps(T8, indent=1, ensure_ascii=False))

# ----------------------------------------------------------------------------- artifact bootstrap reproduction (sanity)
def artifact_percentile_boot(by_q_1, by_q_2, positive_1, positive_2, seed, resamples=5000):
    """Exact re-implementation of the artifact's paired_question_bootstrap percentile convention
    (draws[int(0.025*B)], draws[int(0.975*B)-1]) for a sanity check against arm_contrast_matched_v1.json."""
    qs = QIDS
    k = len(qs)
    rng = random.Random(seed)

    def pooled(sel, by_q, pos):
        num = den = 0
        for q in sel:
            labs = by_q.get(q, ())
            den += len(labs)
            num += sum(1 for x in labs if x == pos)
        return (num / den) if den else None

    draws = []
    for _ in range(resamples):
        sel = [qs[rng.randrange(k)] for _ in range(k)]
        a, b = pooled(sel, by_q_1, positive_1), pooled(sel, by_q_2, positive_2)
        if a is not None and b is not None:
            draws.append(a - b)
    draws.sort()
    return [round(draws[int(0.025 * len(draws))], 4), round(draws[int(0.975 * len(draws)) - 1], 4)]


rep = {}
for ins in ("entailment", "relevance"):
    by1 = {q: list(FINAL[("shipped", ins, "pinned_rematch")].get(q, {}).values()) for q in QIDS}
    by2 = {q: list(FINAL[("url_first", ins, "matched")].get(q, {}).values()) for q in QIDS}
    rep[ins] = {"sign_convention": "shipped(pinned_rematch) minus url_first(matched), as in the artifact",
                "ci95_artifact_convention_seed_20260907": artifact_percentile_boot(by1, by2, POS[ins], POS[ins], 20260907),
                "artifact_file_value": jload(RIVF / "arm_contrast_matched_v1.json")["instruments"][ins]["PRIMARY_matched_contrast_paired_question_bootstrap"]["ci95"]}
R["sanity_reproduce_artifact_matched_contrast"] = rep
say("== reproduce artifact matched contrast:", json.dumps(rep))

(OUT / "tierA_judge_results.json").write_text(json.dumps(R, ensure_ascii=False, indent=1), encoding="utf-8")
say("WROTE", OUT / "tierA_judge_results.json")
