"""Freeze the (claim, question) relevance set for the model pass: 185 real + 37 controls.

Population: every claim the shipped system displayed on the frozen probe set -- the 185
real items of entailment_items_v1.jsonl, same text, same ids carried in the key.

Controls: question DERANGEMENT, not passage derangement. Swapping the passage (the
entailment control) leaves claim-to-question relevance unchanged, so it tests nothing here.
A control pairs a real claim with the text of a DIFFERENT question, drawn with a fixed seed
from a different specialty so that the expected label is unambiguously `not_relevant`.
The passage shown is the claim's own, so a judge cannot spot a control by a mismatched
passage; only the question is foreign.

Blind file: item_id, question, claim, cited_passage. Key: kind, source entailment item,
query ids. Hashed and committed before judging, as the probe set and the entailment set
were. A claim and its deranged twin are kept apart at batching time, downstream.

Run:  python benchmark/rivf/build_relevance_model_set.py
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ITEMS = REPO / "benchmark/rivf/entailment_items_v1.jsonl"
KEY_IN = REPO / "benchmark/rivf/entailment_key_v1.json"
PROBE = REPO / "benchmark/datasets/probe_queries_v2.jsonl"
OUT_ITEMS = REPO / "benchmark/rivf/relevance_model_items_v1.jsonl"
OUT_KEY = REPO / "benchmark/rivf/relevance_model_key_v1.json"

SEED = 20260906
N_CONTROLS = 37


def main() -> int:
    key = json.loads(KEY_IN.read_text(encoding="utf-8"))["key"]
    items = {json.loads(l)["item_id"]: json.loads(l) for l in ITEMS.open(encoding="utf-8")}
    probe = {json.loads(l)["query_id"]: json.loads(l) for l in PROBE.open(encoding="utf-8")}

    def specialty(qid):
        return (probe[qid].get("source") or "").split(":")[-1].split("/")[0]

    real = [(iid, meta) for iid, meta in key.items() if meta["kind"] == "real"]
    rng = random.Random(SEED)

    by_specialty = defaultdict(list)
    for qid in probe:
        by_specialty[specialty(qid)].append(qid)

    rows = []
    for iid, meta in real:
        it = items[iid]
        rows.append(
            {
                "kind": "real",
                "source_item": iid,
                "query_id": meta["query_id"],
                "question": it["question"],
                "claim": it["claim"],
                "cited_passage": it["cited_passage"],
                "control_question_query": None,
            }
        )

    for iid, meta in rng.sample(real, N_CONTROLS):
        it = items[iid]
        own_spec = specialty(meta["query_id"])
        # A foreign question from a DIFFERENT specialty, never a control question.
        pool = [
            q for s, qs in by_specialty.items() if s not in (own_spec, "out_of_corpus_control")
            for q in qs
        ]
        foreign = rng.choice(pool)
        rows.append(
            {
                "kind": "control",
                "source_item": iid,
                "query_id": meta["query_id"],
                "question": probe[foreign]["question"],
                "claim": it["claim"],
                "cited_passage": it["cited_passage"],
                "control_question_query": foreign,
            }
        )

    rng.shuffle(rows)
    blind, out_key = [], {}
    for n, r in enumerate(rows, start=1):
        rid = f"rq_{n:04d}"
        out_key[rid] = {
            "kind": r["kind"],
            "source_item": r["source_item"],
            "query_id": r["query_id"],
            "control_question_query": r["control_question_query"],
        }
        blind.append(
            {
                "item_id": rid,
                "question": r["question"],
                "claim": r["claim"],
                "cited_passage": r["cited_passage"],
            }
        )

    with OUT_ITEMS.open("w", encoding="utf-8", newline="\n") as fh:
        for b in blind:
            fh.write(json.dumps(b, ensure_ascii=False, sort_keys=True) + "\n")
    digest = hashlib.sha256(OUT_ITEMS.read_bytes()).hexdigest()
    OUT_KEY.write_text(
        json.dumps(
            {
                "what_this_is": (
                    "Which relevance-model items are question-derangement controls, and "
                    "which entailment item / query each comes from. Judges never see this."
                ),
                "items_file": str(OUT_ITEMS.relative_to(REPO)).replace("\\", "/"),
                "items_sha256": digest,
                "seed": SEED,
                "counts": {"total": len(rows), "real": len(real), "control": N_CONTROLS},
                "key": out_key,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(blind)} items ({len(real)} real + {N_CONTROLS} controls); sha256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
