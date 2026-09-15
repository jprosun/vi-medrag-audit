"""Freeze the entailment and relevance judgement sets for a SECOND arm's capture.

The shipped arm's displayed claims were judged twice: (claim, cited passage) for support and
(claim, question) for relevance, each blind, each with a derangement control arm, each under
a codebook committed before judging. Comparing a second arm on coverage alone would be
comparing the wrong thing -- an arm that shows more claims has helped nobody if the extra
claims are off the question -- so its displayed claims get the same two instruments, built
by the same rules:

  * entailment items: every displayed claim with its cited passage; controls pair a real
    claim with a passage cited by a DIFFERENT question, rejected if that passage was retrieved
    for the claim's own question (as build_entailment_set.py);
  * relevance items: every displayed claim with its question; controls pair a real claim with
    a question from a DIFFERENT specialty (as build_relevance_model_set.py);
  * blind files carry no control flag; keys are written beside them; both are hashed.

Codebooks are unchanged and are NOT copied: ENTAILMENT-CODEBOOK.md and RELEVANCE-CODEBOOK.md
apply verbatim, so the two arms are judged under literally the same text.

Run:
    python benchmark/rivf/build_arm_judgement_sets.py --capture <raw.jsonl> --tag urlfirst
Out:
    benchmark/rivf/entailment_items_<tag>_v1.jsonl / entailment_key_<tag>_v1.json
    benchmark/rivf/relevance_model_items_<tag>_v1.jsonl / relevance_model_key_<tag>_v1.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROBE = REPO / "benchmark/datasets/probe_queries_v2.jsonl"
SEED = 20260907


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_jsonl(path: Path, rows) -> str:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    return sha256_file(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", required=True)
    ap.add_argument("--tag", required=True, help="arm tag used in output filenames, e.g. urlfirst")
    ap.add_argument("--controls", type=int, default=0, help="0 = 20 %% of displayed claims, as before")
    args = ap.parse_args()

    capture = Path(args.capture)
    rows = [json.loads(l) for l in capture.open(encoding="utf-8") if l.strip()]
    probe = {json.loads(l)["query_id"]: json.loads(l) for l in PROBE.open(encoding="utf-8")}

    def specialty(qid):
        return (probe[qid].get("source") or "").split(":")[-1].split("/")[0]

    # ── displayed claims, with their own passage and question ────────────────────────
    real = []
    chunks_by_query = {}
    for row in rows:
        payload = row["payload"]
        qid = row["query_id"]
        question = (row.get("question") or payload.get("question") or probe[qid]["question"]).strip()
        chunks = {str(c.get("id") or ""): (c.get("text") or "") for c in (payload.get("retrieved_chunks") or [])}
        chunks_by_query[qid] = chunks
        for claim in payload.get("claim_attributions") or []:
            cid = str(claim.get("chunk_id") or "")
            real.append(
                {
                    "query_id": qid,
                    "question": question,
                    "claim": (claim.get("claim") or "").strip(),
                    "supporting_span": (claim.get("supporting_span") or "").strip(),
                    "chunk_id": cid,
                    "chunk_text": chunks.get(cid, ""),
                    "source_url": (claim.get("source_url") or "").strip(),
                }
            )
    missing = sum(1 for r in real if not r["chunk_text"])
    assert missing == 0, f"{missing} displayed claims cite a chunk absent from the payload"

    n_controls = args.controls or max(1, round(0.2 * len(real)))
    rng = random.Random(SEED)

    # ── entailment set: passage-derangement controls ─────────────────────────────────
    donors = [(q, cid, t) for q, cs in chunks_by_query.items() for cid, t in cs.items() if t]
    ent_controls = []
    for src in rng.sample(real, min(n_controls, len(real))):
        own = set(chunks_by_query[src["query_id"]])
        for _ in range(10_000):
            q, cid, text = donors[rng.randrange(len(donors))]
            if q != src["query_id"] and cid not in own:
                break
        else:
            raise SystemExit("could not find a foreign passage")
        ent_controls.append({**src, "chunk_id": cid, "chunk_text": text, "source_url": "", "control_donor_query": q})

    ent_rows = [{**r, "_kind": "real"} for r in real] + [{**r, "_kind": "control"} for r in ent_controls]
    rng.shuffle(ent_rows)
    ent_blind, ent_key = [], {}
    for i, r in enumerate(ent_rows, start=1):
        iid = f"ent_{args.tag}_{i:04d}"
        ent_key[iid] = {
            "kind": r["_kind"], "query_id": r["query_id"], "chunk_id": r["chunk_id"],
            "span_equals_claim": r["claim"] == r["supporting_span"],
            "control_donor_query": r.get("control_donor_query"),
        }
        ent_blind.append({"item_id": iid, "question": r["question"], "claim": r["claim"],
                          "supporting_span": r["supporting_span"], "cited_passage": r["chunk_text"]})

    # ── relevance set: question-derangement controls from a different specialty ─────
    by_spec = defaultdict(list)
    for q in probe:
        by_spec[specialty(q)].append(q)
    rel_controls = []
    for src in rng.sample(real, min(n_controls, len(real))):
        own_spec = specialty(src["query_id"])
        pool = [q for s, qs in by_spec.items() if s not in (own_spec, "out_of_corpus_control") for q in qs]
        foreign = rng.choice(pool)
        rel_controls.append({**src, "question": probe[foreign]["question"], "control_question_query": foreign})

    rel_rows = [{**r, "_kind": "real"} for r in real] + [{**r, "_kind": "control"} for r in rel_controls]
    rng.shuffle(rel_rows)
    rel_blind, rel_key = [], {}
    for i, r in enumerate(rel_rows, start=1):
        iid = f"rq_{args.tag}_{i:04d}"
        rel_key[iid] = {"kind": r["_kind"], "query_id": r["query_id"], "chunk_id": r["chunk_id"],
                        "control_question_query": r.get("control_question_query")}
        rel_blind.append({"item_id": iid, "question": r["question"], "claim": r["claim"], "cited_passage": r["chunk_text"]})

    out = REPO / "benchmark/rivf"
    ent_items = out / f"entailment_items_{args.tag}_v1.jsonl"
    rel_items = out / f"relevance_model_items_{args.tag}_v1.jsonl"
    ent_sha = write_jsonl(ent_items, ent_blind)
    rel_sha = write_jsonl(rel_items, rel_blind)
    common = {
        "capture": str(capture.resolve().relative_to(REPO)).replace("\\", "/"),
        "capture_sha256": sha256_file(capture),
        "seed": SEED,
        "displayed_claims": len(real),
        "questions_with_displayed_claims": len({r["query_id"] for r in real}),
    }
    (out / f"entailment_key_{args.tag}_v1.json").write_text(json.dumps({
        "what_this_is": "Which entailment items for this arm are passage-derangement controls. Judges never see this.",
        "codebook": "benchmark/rivf/ENTAILMENT-CODEBOOK.md", "items_file": str(ent_items.relative_to(REPO)).replace("\\", "/"),
        "items_sha256": ent_sha, **common, "counts": {"total": len(ent_rows), "real": len(real), "control": len(ent_controls)},
        "key": ent_key}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / f"relevance_model_key_{args.tag}_v1.json").write_text(json.dumps({
        "what_this_is": "Which relevance items for this arm are question-derangement controls. Judges never see this.",
        "codebook": "benchmark/rivf/RELEVANCE-CODEBOOK.md", "items_file": str(rel_items.relative_to(REPO)).replace("\\", "/"),
        "items_sha256": rel_sha, **common, "counts": {"total": len(rel_rows), "real": len(real), "control": len(rel_controls)},
        "key": rel_key}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"arm {args.tag}: {len(real)} displayed claims over {common['questions_with_displayed_claims']} questions; "
          f"{len(ent_controls)} entailment controls, {len(rel_controls)} relevance controls")
    print(f"  entailment items sha256 {ent_sha}")
    print(f"  relevance  items sha256 {rel_sha}")
    print(f"  span identical to claim: {sum(1 for r in real if r['claim'] == r['supporting_span'])} of {len(real)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
