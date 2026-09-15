"""Score the (claim, question) relevance judgements into the artifact the paper cites.

Inputs, all committed:
    benchmark/rivf/relevance_model_items_v1.jsonl       the frozen blind items
    benchmark/rivf/relevance_model_key_v1.json          which items are question-derangement controls
    benchmark/rivf/relevance_model_judgements_v1.json   two blind passes + adjudication
    benchmark/rivf/entailment_report_v1.json            to cross-tab relevance with support

Final label: the adjudicator's where the two passes disagreed, the agreed label otherwise.

Confidence intervals are percentile cluster bootstrap with the QUESTION as the cluster and a
fixed seed -- the paper's one instrument for every interval, because two claims from the
same answer are not independent observations.

The human 40-item sheet (relevance_sheet_v1.md) is scored separately once graded; this
report reserves a slot for the human-vs-model agreement on those 40 and says "not yet" until
then. The model pass is not human validation and nothing here calls it that.

Run:
    python benchmark/rivf/relevance_report.py
    python benchmark/rivf/relevance_report.py --check
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ITEMS = REPO / "benchmark/rivf/relevance_model_items_v1.jsonl"
KEY = REPO / "benchmark/rivf/relevance_model_key_v1.json"
JUDGEMENTS = REPO / "benchmark/rivf/relevance_model_judgements_v1.json"
ENTAIL = REPO / "benchmark/rivf/entailment_report_v1.json"
PROBE = REPO / "benchmark/datasets/probe_queries_v2.jsonl"
HUMAN = REPO / "benchmark/rivf/relevance_human_v1.json"  # written by score_human_relevance.py
OUT = REPO / "benchmark/rivf/relevance_report_v1.json"

# See the note in entailment_report.py: the arm is data, not a hard-coded string.
ARM = "the shipped system (uncitable claims withheld after generation)"
JUDGE_SCRIPT = "benchmark/rivf/judging/relevance-judgement-shipped.js"

LABELS = ["relevant", "partial", "not_relevant"]
SEED = 20260906
RESAMPLES = 5000


def cluster_bootstrap(clusters, seed=SEED, resamples=RESAMPLES):
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
    return round(point, 4), round(draws[int(0.025 * len(draws))], 4), round(draws[int(0.975 * len(draws)) - 1], 4)


def by_cluster(rows, predicate):
    g = defaultdict(lambda: [0, 0])
    for r in rows:
        c = g[r["query_id"]]
        c[0] += 1 if predicate(r) else 0
        c[1] += 1
    return [(h, n) for h, n in g.values()]


def main() -> int:
    global ITEMS, KEY, JUDGEMENTS, ENTAIL, HUMAN, OUT, ARM, JUDGE_SCRIPT
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument(
        "--tag",
        default="",
        help="arm tag; empty = the shipped arm's files, 'urlfirst' = the URL-first arm's "
        "(built by build_arm_judgement_sets.py). One code path for both arms on purpose. The "
        "support x relevance cross-tab reads that arm's entailment report, so run "
        "entailment_report.py --tag first. The human sheet exists for the shipped arm only.",
    )
    args = ap.parse_args()
    if args.tag:
        t = args.tag
        ITEMS = REPO / f"benchmark/rivf/relevance_model_items_{t}_v1.jsonl"
        KEY = REPO / f"benchmark/rivf/relevance_model_key_{t}_v1.json"
        JUDGEMENTS = REPO / f"benchmark/rivf/relevance_model_judgements_{t}_v1.json"
        ENTAIL = REPO / f"benchmark/rivf/entailment_report_{t}_v1.json"
        HUMAN = REPO / f"benchmark/rivf/relevance_human_{t}_v1.json"
        OUT = REPO / f"benchmark/rivf/relevance_report_{t}_v1.json"
        ARM = "the URL-first arm (uncitable records excluded at retrieval)"
        JUDGE_SCRIPT = "benchmark/rivf/judging/relevance-judgement-urlfirst.js"

    key_blob = json.loads(KEY.read_text(encoding="utf-8"))
    key = key_blob["key"]
    judged = json.loads(JUDGEMENTS.read_text(encoding="utf-8"))
    entail = json.loads(ENTAIL.read_text(encoding="utf-8"))
    entail_label = {r["item_id"]: r["label"] for r in entail["per_item"]}
    # The shipped arm's relevance key names its entailment item directly (source_item). An
    # arm built by build_arm_judgement_sets.py has no such link, so the cross-tab joins on
    # (query_id, claim text) instead -- the same displayed claim under both instruments.
    items_text = {json.loads(l)["item_id"]: json.loads(l) for l in ITEMS.open(encoding="utf-8")}
    entail_items_path = ITEMS.with_name(ITEMS.name.replace("relevance_model_items", "entailment_items"))
    entail_by_claim = {}
    if entail_items_path.exists():
        e_items = {json.loads(l)["item_id"]: json.loads(l) for l in entail_items_path.open(encoding="utf-8")}
        e_key = json.loads(entail_items_path.with_name(entail_items_path.name.replace("_items_", "_key_").replace(".jsonl", ".json")).read_text(encoding="utf-8"))["key"]
        for iid, lab in entail_label.items():
            if iid in e_items and e_key.get(iid, {}).get("kind") == "real":
                entail_by_claim[(e_key[iid]["query_id"], e_items[iid]["claim"].strip())] = lab

    def support_label(item_id, meta):
        if meta.get("source_item") in entail_label:
            return entail_label[meta["source_item"]]
        return entail_by_claim.get((meta["query_id"], items_text[item_id]["claim"].strip()))
    qtype = {}
    for line in PROBE.open(encoding="utf-8"):
        row = json.loads(line)
        qtype[row["query_id"]] = (row.get("source") or "").split("/")[-1] or "unknown"

    a = {j["item_id"]: j for j in judged["pass_a"]}
    b = {j["item_id"]: j for j in judged["pass_b"]}
    adj = {j["item_id"]: j for j in judged.get("adjudication", [])}

    rows, agree = [], 0
    for item_id, meta in key.items():
        ja, jb = a.get(item_id), b.get(item_id)
        if not ja or not jb:
            raise SystemExit(f"{item_id} was not judged in both passes")
        if ja["label"] == jb["label"]:
            agree += 1
            final, source = ja["label"], "both_passes"
        else:
            ruling = adj.get(item_id)
            if not ruling:
                raise SystemExit(f"{item_id} disagreed but was not adjudicated")
            final, source = ruling["label"], "adjudicated"
        rows.append(
            {
                "item_id": item_id,
                "kind": meta["kind"],
                "source_item": meta.get("source_item"),
                "query_id": meta["query_id"],
                "question_type": qtype.get(meta["query_id"], "unknown"),
                "label": final,
                "label_source": source,
                "pass_a": ja["label"],
                "pass_b": jb["label"],
                "entailment_label": support_label(item_id, meta),
            }
        )

    real = [r for r in rows if r["kind"] == "real"]
    ctrl = [r for r in rows if r["kind"] == "control"]

    n = len(rows)
    pa = agree / n
    ca = Counter(a[r["item_id"]]["label"] for r in rows)
    cb = Counter(b[r["item_id"]]["label"] for r in rows)
    pe = sum((ca[l] / n) * (cb[l] / n) for l in LABELS)
    kappa = (pa - pe) / (1 - pe) if pe < 1 else None

    def dist(group):
        c = Counter(r["label"] for r in group)
        return {l: {"n": c[l], "rate": round(c[l] / max(len(group), 1), 4)} for l in LABELS}

    # The cross-tab the paper needs: supported-by-passage x relevant-to-question.
    cross = Counter((r["entailment_label"], r["label"]) for r in real)
    supported_and_irrelevant = sum(
        1 for r in real if r["entailment_label"] == "supported" and r["label"] == "not_relevant"
    )
    supported_and_partial = sum(
        1 for r in real if r["entailment_label"] == "supported" and r["label"] == "partial"
    )

    per_type = {}
    for t in sorted({r["question_type"] for r in real}):
        g = [r for r in real if r["question_type"] == t]
        per_type[t] = {
            "claims": len(g),
            "relevant": round(sum(1 for r in g if r["label"] == "relevant") / len(g), 4),
            "not_relevant": round(sum(1 for r in g if r["label"] == "not_relevant") / len(g), 4),
        }

    # Answers whose displayed claims are ALL irrelevant: the reader-level unit.
    by_q = defaultdict(list)
    for r in real:
        by_q[r["query_id"]].append(r["label"])
    answers_with_claims = len(by_q)
    answers_all_irrelevant = sum(1 for labs in by_q.values() if all(l == "not_relevant" for l in labs))
    answers_with_any_relevant = sum(1 for labs in by_q.values() if any(l == "relevant" for l in labs))

    ctrl_correct = sum(1 for r in ctrl if r["label"] == "not_relevant")

    human = None
    if HUMAN.exists():
        # Summary only: the per-item table lives in its own artifact and duplicating it here
        # would give two copies to keep in step.
        h = json.loads(HUMAN.read_text(encoding="utf-8"))
        human = {
            "source": str(HUMAN.relative_to(REPO)).replace("\\", "/"),
            "graded_by": h["provenance"]["graded_by"],
            "agreement": h["agreement"],
            "human_relevant_rate": h["human_relevant_rate"],
            "by_question_type": h["by_question_type"],
        }

    report = {
        "what_this_is": (
            f"Relevance of every claim {ARM} displayed on the frozen 134-question "
            "probe set, judged against the QUESTION it was shown for. Model-judged, two blind "
            "passes plus adjudication, with a question-derangement control arm. NOT human "
            "validation; the 40-item author-graded sheet is, and its agreement is reported "
            "under human_check when available."
        ),
        "provenance": {
            "arm": ARM,
            "items": str(ITEMS.relative_to(REPO)).replace("\\", "/"),
            "items_sha256": key_blob["items_sha256"],
            "codebook": "benchmark/rivf/RELEVANCE-CODEBOOK.md",
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
            "items_adjudicated": n - agree,
            "control_items": len(ctrl),
            "controls_correctly_not_relevant": ctrl_correct,
            "control_specificity": round(ctrl_correct / len(ctrl), 4),
            "false_relevance_rate_on_controls": round(1 - ctrl_correct / len(ctrl), 4),
            "control_label_distribution": dist(ctrl),
        },
        "headline": {
            "displayed_claims_judged": len(real),
            "label_distribution": dist(real),
            "relevant_rate_ci": cluster_bootstrap(by_cluster(real, lambda r: r["label"] == "relevant")),
            "not_relevant_rate_ci": cluster_bootstrap(by_cluster(real, lambda r: r["label"] == "not_relevant")),
            "relevant_or_partial_rate_ci": cluster_bootstrap(
                by_cluster(real, lambda r: r["label"] in ("relevant", "partial"))
            ),
        },
        "support_x_relevance": {
            "note": (
                "Rows are the entailment label of the same displayed claim (claim vs cited "
                "passage); columns are relevance (claim vs question). The paper's point sits in "
                "supported x not_relevant: well-cited, well-supported, and beside the question."
            ),
            "cells": {f"{s}|{r}": c for (s, r), c in sorted(cross.items(), key=lambda kv: (str(kv[0][0]), kv[0][1]))},
            "supported_but_not_relevant": supported_and_irrelevant,
            "supported_but_only_partial": supported_and_partial,
            "supported_but_not_relevant_rate_ci": cluster_bootstrap(
                by_cluster(real, lambda r: r["entailment_label"] == "supported" and r["label"] == "not_relevant")
            ),
        },
        "answer_level": {
            "answers_with_at_least_one_displayed_claim": answers_with_claims,
            "answers_where_every_displayed_claim_is_not_relevant": answers_all_irrelevant,
            "answers_with_at_least_one_relevant_claim": answers_with_any_relevant,
        },
        "by_question_type": per_type,
        "human_check": human if human else {"status": "not yet graded", "sheet": "benchmark/rivf/relevance_sheet_v1.md"},
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
        print(f"    {l:14} {d[l]['n']:4}  {d[l]['rate']:.3f}")
    h = report["headline"]
    print(f"  relevant      {h['relevant_rate_ci']}")
    print(f"  not_relevant  {h['not_relevant_rate_ci']}")
    sx = report["support_x_relevance"]
    print(f"  supported-by-passage AND not relevant to question: {sx['supported_but_not_relevant']}  "
          f"{sx['supported_but_not_relevant_rate_ci']}")
    al = report["answer_level"]
    print(f"  answers with claims {al['answers_with_at_least_one_displayed_claim']} | all claims irrelevant "
          f"{al['answers_where_every_displayed_claim_is_not_relevant']} | any relevant {al['answers_with_at_least_one_relevant_claim']}")
    i = report["instrument"]
    print(f"  controls correctly not_relevant {i['controls_correctly_not_relevant']}/{i['control_items']} "
          f"= specificity {i['control_specificity']}")
    print(f"  two blind passes: agreement {i['raw_agreement_two_blind_passes']}, kappa {i['cohens_kappa']}, "
          f"{i['items_adjudicated']} adjudicated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
