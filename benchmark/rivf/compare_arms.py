"""Paired comparison of two retrieval arms on the same frozen 134 questions.

Arm A, "shipped": retrieve from every stratum, then WITHHOLD claims whose record has no
source URL (the citability gate). Capture at 13dc51f.
Arm B, "url-first": never retrieve the URL-less stratum at all, so a citable record takes
the seat. Same enforcement code, same gates, one env var. Capture at the image built from
47536e9 (services/ tree identical; only the flag differs, and every response records it).

The question this answers is the reviewer's sharpest one: is the traceability tax a property
of the corpus that any design pays, or of the post-hoc design that pays it late? The paired
design answers per question: same question, two generations, so the comparison is between
arms on identical inputs, with question-level clustering for the intervals.

What is compared, per arm, recomputed from the payloads through the server's own
definitions (app.span_exposure / app.span_norm), never from a summary file:
  * candidate claims extracted, claims shown, withheld by reason
  * answers with no displayed claim (the unit a reader feels)
  * stratum composition of what was retrieved
  * figures in the delivered answer inside a shown span (the attribution gap)
  * verifier verdicts, latency percentiles

What is NOT compared here, and must be judged separately before either arm is called
better: relevance of the displayed claims to the question, and support of claim by passage.
An arm that shows more claims has not helped anyone if the extra claims are off the question.
The report says so in its own text.

Run:
    python benchmark/rivf/compare_arms.py --url-first benchmark/datasets/test_results/pilot_span_exposure_urlfirst_<ts>_raw.jsonl
    python benchmark/rivf/compare_arms.py --url-first <same> --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

from artifact_provenance import source_sha256

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "services" / "rag-orchestrator"))
from app.span_exposure import evaluate_response  # noqa: E402

SHIPPED = REPO / "benchmark/datasets/test_results/pilot_span_exposure_rivf134_2026-09-05_091659_raw.jsonl"
PROBE = REPO / "benchmark/datasets/probe_queries_v2.jsonl"
OUT = REPO / "benchmark/rivf/arm_comparison_rivf134.json"
REMOVAL_NOTICE = "\n\n---\n**Ghi chú hệ thống"
EXCLUDED_ID = "hf_vi_mtue29_medical"
SEED = 20260907
RESAMPLES = 5000


def sha256_file(p: Path) -> str:
    return source_sha256(p)


def load(path: Path):
    rows = [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]
    return {r["query_id"]: r for r in rows}


def per_question(row):
    p = row["payload"]
    md = p.get("metadata") or {}
    shown = p.get("claim_attributions") or []
    dropped = p.get("dropped_claims") or []
    reasons = Counter(c.get("drop_reason") or "unrecorded" for c in dropped)
    answer = p.get("answer") or ""
    delivered = answer.split(REMOVAL_NOTICE)[0]
    ev = evaluate_response({**p, "answer": delivered})
    strata = Counter(
        str((c.get("metadata") or {}).get("source_id") or "?") for c in (p.get("retrieved_chunks") or [])
    )
    t = md.get("timings_ms") or {}
    return {
        "extracted": len(shown) + len(dropped),
        "shown": len(shown),
        "withheld_span": reasons["span_not_found_in_cited_chunk"] + reasons["chunk_id_not_resolvable"] + reasons["no_supporting_span"],
        "withheld_citability": reasons["cited_record_not_citable"],
        "zero_claim": int(len(shown) == 0),
        "uncitable_extracted": sum(1 for c in shown + dropped if not (c.get("source_url") or "").strip()),
        "figures": ev["answer_claim_figures"],
        "figures_in_span": ev["answer_claim_figures_in_a_verified_span"],
        "retrieved": sum(strata.values()),
        "retrieved_excluded_stratum": strata.get(EXCLUDED_ID, 0),
        "verifier": md.get("verification_status"),
        "arm_recorded": md.get("retrieval_excluded_source_ids"),
        "total_ms": t.get("total_ms"),
        "retrieval_ms": t.get("retrieval_ms"),
        "statements_removed": md.get("numeric_statements_removed") or 0,
    }


def boot_ratio(pairs, seed=SEED, resamples=RESAMPLES):
    """Cluster bootstrap for a ratio sum(num)/sum(den) with questions as clusters."""
    if not pairs or sum(d for _, d in pairs) == 0:
        return None
    point = sum(n for n, _ in pairs) / sum(d for _, d in pairs)
    rng = random.Random(seed)
    draws = []
    k = len(pairs)
    for _ in range(resamples):
        n = d = 0
        for _ in range(k):
            a, b = pairs[rng.randrange(k)]
            n += a
            d += b
        if d:
            draws.append(n / d)
    draws.sort()
    return round(point, 4), round(draws[int(0.025 * len(draws))], 4), round(draws[int(0.975 * len(draws)) - 1], 4)


def boot_paired_diff(diffs, seed=SEED, resamples=RESAMPLES):
    """Bootstrap CI for the mean of per-question differences (B - A)."""
    if not diffs:
        return None
    rng = random.Random(seed)
    k = len(diffs)
    means = sorted(statistics.fmean(rng.choice(diffs) for _ in range(k)) for _ in range(resamples))
    return round(statistics.fmean(diffs), 4), round(means[int(0.025 * len(means))], 4), round(means[int(0.975 * len(means)) - 1], 4)


def summarise(per, ids, label):
    rows = [per[q] for q in ids]
    n = len(rows)
    ext = sum(r["extracted"] for r in rows)
    shown = sum(r["shown"] for r in rows)
    ms_total = sorted(r["total_ms"] for r in rows if r["total_ms"] is not None)
    ms_retr = sorted(r["retrieval_ms"] for r in rows if r["retrieval_ms"] is not None)

    def pct(v, q):
        return round(v[min(len(v) - 1, int(q * len(v)))], 1) if v else None

    return {
        "label": label,
        "questions": n,
        "claims_extracted": ext,
        "claims_shown": shown,
        "retention_shown_over_extracted": boot_ratio([(r["shown"], r["extracted"]) for r in rows]),
        "withheld_span": sum(r["withheld_span"] for r in rows),
        "withheld_citability": sum(r["withheld_citability"] for r in rows),
        "uncitable_among_extracted": sum(r["uncitable_extracted"] for r in rows),
        "answers_with_zero_claims": sum(r["zero_claim"] for r in rows),
        "answers_with_zero_claims_rate": boot_ratio([(r["zero_claim"], 1) for r in rows]),
        "claims_shown_per_answer_mean": round(shown / n, 3) if n else None,
        "figures_in_delivered_answers": sum(r["figures"] for r in rows),
        "figures_inside_a_shown_span": sum(r["figures_in_span"] for r in rows),
        "figure_attribution_rate": boot_ratio([(r["figures_in_span"], r["figures"]) for r in rows]),
        "statements_removed_by_numeric_gate": sum(r["statements_removed"] for r in rows),
        "retrieved_chunks": sum(r["retrieved"] for r in rows),
        "retrieved_from_excluded_stratum": sum(r["retrieved_excluded_stratum"] for r in rows),
        "verifier_verdicts": dict(Counter(r["verifier"] for r in rows)),
        "latency_ms": {"total_p50": pct(ms_total, 0.5), "total_p95": pct(ms_total, 0.95),
                       "retrieval_p50": pct(ms_retr, 0.5), "retrieval_p95": pct(ms_retr, 0.95)},
        "arm_recorded_in_responses": sorted({json.dumps(r["arm_recorded"]) for r in rows}),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url-first", required=True, help="raw jsonl of the URL-first arm sweep")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    urlfirst_path = Path(args.url_first)

    A, B = load(SHIPPED), load(urlfirst_path)
    common = sorted(set(A) & set(B))
    only_a, only_b = sorted(set(A) - set(B)), sorted(set(B) - set(A))
    probe = {json.loads(l)["query_id"]: json.loads(l) for l in PROBE.open(encoding="utf-8")}
    qtype = {q: (probe[q].get("source") or "").split("/")[-1] for q in probe}
    controls = {q for q in probe if "out_of_corpus_control" in (probe[q].get("source") or "")}
    answerable = [q for q in common if q not in controls]

    pa = {q: per_question(A[q]) for q in common}
    pb = {q: per_question(B[q]) for q in common}

    # The arm must be what the responses say it is, not what the filename says.
    assert all(pa[q]["arm_recorded"] in (None, []) for q in common), "shipped capture reports an exclusion"
    assert all(pb[q]["arm_recorded"] == [EXCLUDED_ID] for q in common), "url-first capture does not report the exclusion"

    def block(ids, name):
        return {
            "shipped": summarise(pa, ids, "shipped (withhold after generation), 13dc51f"),
            "url_first": summarise(pb, ids, "url-first (exclude at retrieval), 47536e9 image"),
            "paired_differences_url_first_minus_shipped": {
                "claims_shown_per_answer": boot_paired_diff([pb[q]["shown"] - pa[q]["shown"] for q in ids]),
                "zero_claim_answer": boot_paired_diff([pb[q]["zero_claim"] - pa[q]["zero_claim"] for q in ids]),
                "figures_in_span_per_answer": boot_paired_diff([pb[q]["figures_in_span"] - pa[q]["figures_in_span"] for q in ids]),
                "total_ms": boot_paired_diff([
                    (pb[q]["total_ms"] or 0) - (pa[q]["total_ms"] or 0) for q in ids
                    if pb[q]["total_ms"] is not None and pa[q]["total_ms"] is not None
                ]),
            },
            "questions_where_url_first_shows_more": sum(1 for q in ids if pb[q]["shown"] > pa[q]["shown"]),
            "questions_where_url_first_shows_fewer": sum(1 for q in ids if pb[q]["shown"] < pa[q]["shown"]),
            "questions_tied": sum(1 for q in ids if pb[q]["shown"] == pa[q]["shown"]),
            "scope": name,
        }

    by_type = {}
    for t in sorted({qtype[q] for q in answerable}):
        ids = [q for q in answerable if qtype[q] == t]
        by_type[t] = {
            "questions": len(ids),
            "shipped_retention": boot_ratio([(pa[q]["shown"], pa[q]["extracted"]) for q in ids]),
            "url_first_retention": boot_ratio([(pb[q]["shown"], pb[q]["extracted"]) for q in ids]),
            "shipped_zero_claim": sum(pa[q]["zero_claim"] for q in ids),
            "url_first_zero_claim": sum(pb[q]["zero_claim"] for q in ids),
        }

    report = {
        "what_this_is": (
            "Paired comparison of two designs on the same 134 frozen questions: withhold "
            "uncitable claims after generation (shipped) vs exclude the uncitable stratum at "
            "retrieval (url-first). Same enforcement code; one env var; every response records "
            "its arm. Recomputed from payloads through the server's own definitions."
        ),
        "read_this_first": (
            "Coverage is not usefulness. Whether the extra claims the url-first arm shows are "
            "relevant to the question, and supported by their passage, is judged separately; "
            "no number here says which arm helps a reader more."
        ),
        "provenance": {
            "shipped_capture": {"path": str(SHIPPED.relative_to(REPO)).replace("\\", "/"), "sha256": sha256_file(SHIPPED), "code": "13dc51f"},
            "url_first_capture": {"path": str(urlfirst_path.resolve().relative_to(REPO)).replace("\\", "/"), "sha256": sha256_file(urlfirst_path), "code": "47536e9 image; services/ tree identical to 47536e9"},
            "questions_in_both": len(common), "only_in_shipped": only_a, "only_in_url_first": only_b,
            "excluded_source_id": EXCLUDED_ID,
            "bootstrap": {"clusters": "question", "resamples": RESAMPLES, "seed": SEED},
        },
        "all_questions": block(common, "all 134 (controls included, reported apart below)"),
        "answerable_only": block(answerable, "119 answerable; 15 out-of-corpus controls excluded"),
        "controls_only": block(sorted(controls & set(common)), "15 out-of-corpus controls"),
        "by_question_type_answerable": by_type,
    }

    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("report reproduces exactly" if same else "REPORT DIFFERS from a fresh run")
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8")

    for scope in ("all_questions", "answerable_only"):
        b = report[scope]
        s, u = b["shipped"], b["url_first"]
        print(f"\n== {b['scope']} ==")
        print(f"  {'':28}{'shipped':>14}{'url-first':>14}")
        print(f"  {'claims extracted':28}{s['claims_extracted']:>14}{u['claims_extracted']:>14}")
        print(f"  {'claims shown':28}{s['claims_shown']:>14}{u['claims_shown']:>14}")
        print(f"  {'retention':28}{str(s['retention_shown_over_extracted'][0]):>14}{str(u['retention_shown_over_extracted'][0]):>14}")
        print(f"  {'withheld: citability':28}{s['withheld_citability']:>14}{u['withheld_citability']:>14}")
        print(f"  {'answers with 0 claims':28}{s['answers_with_zero_claims']:>14}{u['answers_with_zero_claims']:>14}")
        print(f"  {'figures in a shown span':28}{str(s['figure_attribution_rate'][0]):>14}{str(u['figure_attribution_rate'][0]):>14}")
        print(f"  {'retrieved from HF stratum':28}{s['retrieved_from_excluded_stratum']:>14}{u['retrieved_from_excluded_stratum']:>14}")
        sl, ul = s["latency_ms"], u["latency_ms"]
        print(f"  {'total_ms p50':28}{str(sl['total_p50']):>14}{str(ul['total_p50']):>14}")
        print(f"  {'total_ms p95':28}{str(sl['total_p95']):>14}{str(ul['total_p95']):>14}")
        d = b["paired_differences_url_first_minus_shipped"]
        print(f"  paired diff shown/answer (B-A): {d['claims_shown_per_answer']}   more/fewer/tied: "
              f"{b['questions_where_url_first_shows_more']}/{b['questions_where_url_first_shows_fewer']}/{b['questions_tied']}")
    print(f"\nwrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
