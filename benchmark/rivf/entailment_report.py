"""Score the frozen entailment judgements into the artifact the paper cites.

Inputs, all committed:
    benchmark/rivf/entailment_items_v1.jsonl        the frozen blind items
    benchmark/rivf/entailment_key_v1.json           which items are derangement controls
    benchmark/rivf/entailment_judgements_v1.json    two blind passes + adjudication

The final label for an item is the adjudicator's where the two passes disagreed, and the
agreed label otherwise. Nothing here re-judges anything.

Confidence intervals are percentile cluster bootstrap with the QUESTION as the cluster and
a fixed seed, the same instrument the paper's other intervals use: two claims from the same
answer are not independent observations.

Run:
    python benchmark/rivf/entailment_report.py
    python benchmark/rivf/entailment_report.py --check
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ITEMS = REPO / "benchmark/rivf/entailment_items_v1.jsonl"
KEY = REPO / "benchmark/rivf/entailment_key_v1.json"
JUDGEMENTS = REPO / "benchmark/rivf/entailment_judgements_v1.json"
PROBE = REPO / "benchmark/datasets/probe_queries_v2.jsonl"
HUMAN = REPO / "benchmark/rivf/entailment_human_v1.json"  # written by score_human_entailment.py

# The arm this run describes, and the script that produced its labels. Overwritten by --tag.
# These exist because the provenance block used to hard-code the shipped arm's paths, so the
# URL-first report claimed to be derived from files it had never opened.
ARM = "the shipped system (uncitable claims withheld after generation)"
JUDGE_SCRIPT = "benchmark/rivf/judging/entailment-judgement-shipped.js"
OUT = REPO / "benchmark/rivf/entailment_report_v1.json"

LABELS = ["supported", "overstated", "not_supported", "unintelligible"]
SEED = 20260905
RESAMPLES = 5000


def cluster_bootstrap(clusters: list, seed: int = SEED, resamples: int = RESAMPLES):
    """Percentile CI for a proportion, resampling whole clusters with replacement.

    Each cluster is (hits, n). Returns (point, lo, hi) or None when there is nothing to
    resample.
    """
    total_n = sum(n for _, n in clusters)
    if not clusters or total_n == 0:
        return None
    point = sum(h for h, _ in clusters) / total_n
    rng = random.Random(seed)
    draws = []
    k = len(clusters)
    for _ in range(resamples):
        h = n = 0
        for _ in range(k):
            ch, cn = clusters[rng.randrange(k)]
            h += ch
            n += cn
        if n:
            draws.append(h / n)
    draws.sort()
    lo = draws[int(0.025 * len(draws))]
    hi = draws[int(0.975 * len(draws)) - 1]
    return round(point, 4), round(lo, 4), round(hi, 4)


def by_cluster(rows, predicate) -> list:
    grouped = defaultdict(lambda: [0, 0])
    for r in rows:
        g = grouped[r["query_id"]]
        g[0] += 1 if predicate(r) else 0
        g[1] += 1
    return [(h, n) for h, n in grouped.values()]


def main() -> int:
    global ITEMS, KEY, JUDGEMENTS, HUMAN, OUT, ARM, JUDGE_SCRIPT
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument(
        "--tag",
        default="",
        help="arm tag; empty = the shipped arm's files, 'urlfirst' = the URL-first arm's "
        "(built by build_arm_judgement_sets.py). One code path for both arms on purpose.",
    )
    args = ap.parse_args()
    if args.tag:
        t = args.tag
        ITEMS = REPO / f"benchmark/rivf/entailment_items_{t}_v1.jsonl"
        KEY = REPO / f"benchmark/rivf/entailment_key_{t}_v1.json"
        JUDGEMENTS = REPO / f"benchmark/rivf/entailment_judgements_{t}_v1.json"
        HUMAN = REPO / f"benchmark/rivf/entailment_human_{t}_v1.json"
        OUT = REPO / f"benchmark/rivf/entailment_report_{t}_v1.json"
        ARM = "the URL-first arm (uncitable records excluded at retrieval)"
        JUDGE_SCRIPT = "benchmark/rivf/judging/entailment-judgement-urlfirst.js"

    key_blob = json.loads(KEY.read_text(encoding="utf-8"))
    key = key_blob["key"]
    judged = json.loads(JUDGEMENTS.read_text(encoding="utf-8"))
    items = {json.loads(line)["item_id"]: json.loads(line) for line in ITEMS.open(encoding="utf-8")}

    qtype = {}
    for line in PROBE.open(encoding="utf-8"):
        row = json.loads(line)
        qtype[row["query_id"]] = (row.get("source") or "").split("/")[-1] or "unknown"

    a = {j["item_id"]: j for j in judged["pass_a"]}
    b = {j["item_id"]: j for j in judged["pass_b"]}
    adj = {j["item_id"]: j for j in judged.get("adjudication", [])}

    rows = []
    agree = disagree = 0
    confusion: Counter = Counter()
    for item_id, meta in key.items():
        ja, jb = a.get(item_id), b.get(item_id)
        if not ja or not jb:
            raise SystemExit(f"{item_id} was not judged in both passes")
        confusion[(ja["label"], jb["label"])] += 1
        if ja["label"] == jb["label"]:
            agree += 1
            final, source = ja["label"], "both_passes"
            locus = ja["span_is_right_locus"]
        else:
            disagree += 1
            ruling = adj.get(item_id)
            if not ruling:
                raise SystemExit(f"{item_id} disagreed but was not adjudicated")
            final, source = ruling["label"], "adjudicated"
            locus = ruling["span_is_right_locus"]
        rows.append(
            {
                "item_id": item_id,
                "kind": meta["kind"],
                "query_id": meta["query_id"],
                "question_type": qtype.get(meta["query_id"], "unknown"),
                "span_equals_claim": meta["span_equals_claim"],
                "label": final,
                "label_source": source,
                "span_is_right_locus": locus,
                "pass_a": ja["label"],
                "pass_b": jb["label"],
            }
        )

    real = [r for r in rows if r["kind"] == "real"]
    ctrl = [r for r in rows if r["kind"] == "control"]

    # Cohen's kappa on the two blind passes, over every item.
    n = len(rows)
    pa = agree / n
    ca = Counter(a[r["item_id"]]["label"] for r in rows)
    cb = Counter(b[r["item_id"]]["label"] for r in rows)
    pe = sum((ca[l] / n) * (cb[l] / n) for l in LABELS)
    kappa = (pa - pe) / (1 - pe) if pe < 1 else None

    def dist(group):
        c = Counter(r["label"] for r in group)
        return {l: {"n": c[l], "rate": round(c[l] / len(group), 4)} for l in LABELS}

    supported = cluster_bootstrap(by_cluster(real, lambda r: r["label"] == "supported"))
    sup_or_over = cluster_bootstrap(
        by_cluster(real, lambda r: r["label"] in ("supported", "overstated"))
    )
    unsupported = cluster_bootstrap(
        by_cluster(real, lambda r: r["label"] in ("not_supported", "unintelligible"))
    )

    per_type = {}
    for t in sorted({r["question_type"] for r in real}):
        g = [r for r in real if r["question_type"] == t]
        per_type[t] = {
            "claims": len(g),
            "supported": round(sum(1 for r in g if r["label"] == "supported") / len(g), 4),
            "not_supported_or_unintelligible": round(
                sum(1 for r in g if r["label"] in ("not_supported", "unintelligible")) / len(g), 4
            ),
        }

    ctrl_correct = sum(1 for r in ctrl if r["label"] == "not_supported")
    human = None
    if HUMAN.exists():
        # Summary only; the per-item table lives in its own artifact.
        h = json.loads(HUMAN.read_text(encoding="utf-8"))
        human = {
            "source": str(HUMAN.relative_to(REPO)).replace("\\", "/"),
            "graded_by": h["provenance"]["graded_by"],
            "agreement": h["agreement"],
            "stratum_A_model_failures": h["stratum_A_model_failures"],
            "stratum_B_model_supported": h["stratum_B_model_supported"],
            "human_supported_rate": h["human_supported_rate"],
            "overstated": h["overstated"],
        }
    else:
        human = {"status": "not yet graded", "sheet": "benchmark/rivf/entailment_human_labels_v1.txt"}

    report = {
        "what_this_is": (
            f"Entailment of every claim {ARM} displayed on the frozen 134-question "
            "probe set, judged against the passage it cited. Model-judged, two blind passes "
            "plus adjudication, with a derangement control arm. NOT a clinician's judgement "
            "of clinical correctness."
        ),
        "provenance": {
            "arm": ARM,
            "items": str(ITEMS.relative_to(REPO)).replace("\\", "/"),
            "items_sha256": key_blob["items_sha256"],
            "codebook": "benchmark/rivf/ENTAILMENT-CODEBOOK.md",
            "codebook_written_before_judging": True,
            "judgements": str(JUDGEMENTS.relative_to(REPO)).replace("\\", "/"),
            "counts": key_blob["counts"],
            "judge": {
                "configuration": "benchmark/rivf/judging/JUDGE-CONFIGURATION.md",
                "script_as_run": JUDGE_SCRIPT,
                "decoding": "not set; harness defaults, so the passes are not bitwise reproducible",
                "model_checkpoint": (
                    "NOT RECOVERABLE: no script pins a model, so each judge subagent inherited "
                    "the session's model. Family is Anthropic Claude via Claude Code. See the "
                    "configuration file; the paper states this as a limitation rather than "
                    "naming a version it cannot prove."
                ),
            },

            "bootstrap": {"clusters": "question", "resamples": RESAMPLES, "seed": SEED},
        },
        "instrument": {
            "raw_agreement_two_blind_passes": round(pa, 4),
            "cohens_kappa": round(kappa, 4) if kappa is not None else None,
            "items_adjudicated": disagree,
            "control_items": len(ctrl),
            "controls_correctly_not_supported": ctrl_correct,
            "control_specificity": round(ctrl_correct / len(ctrl), 4),
            "false_support_rate_on_controls": round(1 - ctrl_correct / len(ctrl), 4),
            "control_label_distribution": dist(ctrl),
        },
        "headline": {
            "displayed_claims_judged": len(real),
            "label_distribution": dist(real),
            "supported_rate_ci": supported,
            "supported_or_overstated_rate_ci": sup_or_over,
            "not_supported_or_unintelligible_rate_ci": unsupported,
            "span_is_right_locus_among_supported": dict(
                Counter(r["span_is_right_locus"] for r in real if r["label"] == "supported")
            ),
        },
        "human_check": human,
        "by_question_type": per_type,
        "disagreement_matrix": {f"{x}|{y}": c for (x, y), c in sorted(confusion.items()) if x != y},
        "per_item": sorted(rows, key=lambda r: r["item_id"]),
    }

    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("report reproduces exactly" if same else "REPORT DIFFERS from a fresh run")
        return 0 if same else 1

    OUT.write_text(text, encoding="utf-8")
    d = report["headline"]["label_distribution"]
    print(f"wrote {OUT.relative_to(REPO)}")
    print(f"  displayed claims judged: {len(real)}")
    for l in LABELS:
        print(f"    {l:16} {d[l]['n']:4}  {d[l]['rate']:.3f}")
    print(f"  supported {supported[0]} [{supported[1]}, {supported[2]}]")
    print(f"  not supported or unintelligible {unsupported[0]} [{unsupported[1]}, {unsupported[2]}]")
    print(f"  controls correctly rejected {ctrl_correct}/{len(ctrl)} "
          f"= specificity {report['instrument']['control_specificity']}")
    print(f"  two blind passes: raw agreement {pa:.3f}, kappa "
          f"{report['instrument']['cohens_kappa']}, {disagree} adjudicated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
