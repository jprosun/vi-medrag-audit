"""Freeze the entailment judgement set, before any judging happens.

Why the unit is the CHUNK and not the span
------------------------------------------
The obvious design -- "does the supporting span entail the claim?" -- is vacuous here.
183 of the 185 shown claims have a span textually identical to the claim, because the
extractor's deterministic path selects a chunk sentence as both. Asking whether a string
entails itself measures nothing.

What the paper actually concedes is the gap between containment and support: span
containment proves the cited string OCCURS in the cited document, not that the document
SUPPORTS the assertion. So the judgement unit is (claim, cited chunk): given the whole
cited passage, is the claim the reader was shown actually supported by it?

Design
------
* Population: every claim the shipped system displayed on the 134-question probe set, all
  185 of them. Exhaustive, not sampled -- there is no sampling error to report.
* Controls: 37 derangement items. A real claim is paired with a chunk cited by a DIFFERENT
  question, drawn with a fixed seed and rejected if that chunk was retrieved for the
  claim's own question. A judge who marks these supported is not discriminating, and the
  control rate bounds how much of the headline rate is rubber-stamping. The same device is
  used in this repo's ingestion diagnostic (Sec. VI).
* Blinding: the file handed to judges carries no control flag and no system verdict. The
  key is written separately. A claim and its deranged twin are forced into different
  batches at judging time so the repetition is not visible.
* Frozen: the item file is hashed and committed before any judgement is collected, in the
  same way the probe set was.

Run:
    python benchmark/rivf/build_entailment_set.py
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CAPTURE = (
    REPO
    / "benchmark/datasets/test_results"
    / "pilot_span_exposure_rivf134_2026-09-05_091659_raw.jsonl"
)
ITEMS = REPO / "benchmark/rivf/entailment_items_v1.jsonl"
KEY = REPO / "benchmark/rivf/entailment_key_v1.json"

SEED = 20260905
N_CONTROLS = 37


def main() -> int:
    rows = [json.loads(line) for line in CAPTURE.open(encoding="utf-8") if line.strip()]

    real = []
    chunks_by_query: dict[str, dict[str, str]] = {}
    for row in rows:
        payload = row["payload"]
        qid = row.get("query_id")
        question = (row.get("question") or payload.get("question") or "").strip()
        chunks = {
            str(c.get("id") or ""): (c.get("text") or "")
            for c in (payload.get("retrieved_chunks") or [])
        }
        chunks_by_query[qid] = chunks
        for claim in payload.get("claim_attributions") or []:
            chunk_id = str(claim.get("chunk_id") or "")
            claim_text = (claim.get("claim") or "").strip()
            span = (claim.get("supporting_span") or "").strip()
            real.append(
                {
                    "query_id": qid,
                    "question": question,
                    "claim": claim_text,
                    "supporting_span": span,
                    "span_equals_claim": claim_text == span,
                    "chunk_id": chunk_id,
                    "chunk_text": chunks.get(chunk_id, ""),
                    "source_url": (claim.get("source_url") or "").strip(),
                }
            )

    assert all(item["chunk_text"] for item in real), "a cited chunk is missing from the payload"

    rng = random.Random(SEED)
    controls = []
    donors = [(qid, cid, text) for qid, cs in chunks_by_query.items() for cid, text in cs.items() if text]
    for source in rng.sample(real, N_CONTROLS):
        own = set(chunks_by_query[source["query_id"]])
        while True:
            qid, cid, text = donors[rng.randrange(len(donors))]
            # A control must cite a chunk that was NOT available to the claim's own
            # question: otherwise "unrelated" is not what the item tests.
            if qid != source["query_id"] and cid not in own:
                break
        controls.append({**source, "chunk_id": cid, "chunk_text": text, "source_url": "", "control_donor_query": qid})

    items = []
    for kind, group in (("real", real), ("control", controls)):
        for it in group:
            items.append({**it, "_kind": kind})
    rng.shuffle(items)

    blind, key = [], {}
    for i, it in enumerate(items, start=1):
        item_id = f"ent_{i:04d}"
        key[item_id] = {
            "kind": it["_kind"],
            "query_id": it["query_id"],
            "chunk_id": it["chunk_id"],
            "span_equals_claim": it["span_equals_claim"],
            "control_donor_query": it.get("control_donor_query"),
        }
        blind.append(
            {
                "item_id": item_id,
                "question": it["question"],
                "claim": it["claim"],
                "supporting_span": it["supporting_span"],
                "cited_passage": it["chunk_text"],
            }
        )

    with ITEMS.open("w", encoding="utf-8", newline="\n") as fh:
        for item in blind:
            fh.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

    digest = hashlib.sha256(ITEMS.read_bytes()).hexdigest()
    KEY.write_text(
        json.dumps(
            {
                "what_this_is": (
                    "Which frozen entailment items are derangement controls. Judges never "
                    "see this file; it is committed before judging so the split cannot be "
                    "chosen after the fact."
                ),
                "items_file": "benchmark/rivf/entailment_items_v1.jsonl",
                "items_sha256": digest,
                "seed": SEED,
                "counts": {"total": len(items), "real": len(real), "control": len(controls)},
                "key": key,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"wrote {len(blind)} items ({len(real)} real + {len(controls)} controls)")
    print(f"  items sha256 {digest}")
    print(f"  span identical to claim: {sum(1 for it in real if it['span_equals_claim'])} of {len(real)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
