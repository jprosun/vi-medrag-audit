"""Split the URL-first item sets into blind batches that MATCH the shipped arm's batching.

WHY THIS EXISTS, and it is not a convenience.

The paper compares two designs on support and responsiveness. That comparison assumed the two
arms were measured by the same instrument. They were not. Two differences, both recovered
after the fact:

  1. THE JUDGE MODEL DIFFERED BY ARM. Recovered from the run transcripts:
       entailment shipped    claude-opus-5
       entailment URL-first  claude-fable-5-1
       relevance  shipped    claude-fable-5-1
       relevance  URL-first  claude-fable-5-1
     So the support contrast (0.968 vs 0.962) crossed two models; the responsiveness contrast
     (0.022 vs 0.028) did not.

  2. THE CODEBOOK DIFFERED BY ARM. The URL-first entailment codebook is 2591 characters
     against the shipped arm's 3876 -- a third shorter. What it dropped is not cosmetic:
       - "A reader who followed the citation would find what they were promised" (the
         operational reading of `supported`)
       - "This label matters: use it rather than stretching `supported`" (the whole anti-
         lenience nudge on `overstated`)
       - "this corpus has a documented ingestion defect, so this label is real and must not be
         folded into not_supported" (the justification for `unintelligible` as a live category)
       - rule 4's instruction on when a number mismatch is `overstated` and when it is
         `not_supported`
     And the shipped RELEVANCE codebook told its judge that support "is already established at
     96.8% of cases" -- a numeric prior from the other instrument, injected into one arm only.
     In the labels, `overstated` moves 0.000 -> 0.003 and `not_supported` 0.005 -> 0.008,
     which is the direction removing that nudge predicts.

Either difference alone makes the between-arm contrast uninterpretable as an arm effect. So
this re-judges the URL-first items under the SHIPPED arm's configuration exactly: the shipped
codebook byte for byte (judging/*_prompt_v1.txt, extracted by extract_prompts.py), the model
pinned, the original adjudicator prompt, and -- here -- the shipped arm's batch size of 28.

Batch size is the last instrument variable, so it is matched rather than argued about: 401
items at 28 gives 15 batches per pass against the original run's 8 of ~50.

    python benchmark/rivf/judging/make_batches_urlfirst.py --instrument entailment
    python benchmark/rivf/judging/make_batches_urlfirst.py --instrument relevance
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUTDIR = HERE / "batches_urlfirst"

SETS = {
    "entailment": REPO / "benchmark/rivf/entailment_items_urlfirst_v1.jsonl",
    "relevance": REPO / "benchmark/rivf/relevance_model_items_urlfirst_v1.jsonl",
}
BATCH = 28  # the shipped arm's size, matched deliberately -- see the module docstring


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", choices=sorted(SETS), required=True)
    a = ap.parse_args()

    src = SETS[a.instrument]
    lines = [l for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
    ids = [json.loads(l)["item_id"] for l in lines]
    assert len(set(ids)) == len(ids), "duplicate item_id in the frozen set"
    OUTDIR.mkdir(parents=True, exist_ok=True)

    manifest = []
    for pass_name in ("a", "b"):
        for i in range(0, len(lines), BATCH):
            n = i // BATCH + 1
            chunk = lines[i:i + BATCH]
            path = OUTDIR / f"{a.instrument}_{pass_name}{n}.jsonl"
            path.write_text("\n".join(chunk) + "\n", encoding="utf-8")
            manifest.append({
                "pass": pass_name,
                "batch": n,
                "n": len(chunk),
                "path": str(path).replace("\\", "/"),
            })

    covered = sum(m["n"] for m in manifest if m["pass"] == "a")
    assert covered == len(lines), f"batches cover {covered} of {len(lines)} items"

    (OUTDIR / f"{a.instrument}_manifest.json").write_text(json.dumps({
        "instrument": a.instrument,
        "arm": "url_first",
        "items_file": str(src).replace("\\", "/"),
        "items_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
        "items": len(lines),
        "batch_size": BATCH,
        "batch_size_matches": "the shipped arm's run, so batch size is not a between-arm variable",
        "batches": manifest,
    }, indent=2) + "\n", encoding="utf-8")

    print(f"{a.instrument} (URL-first): {len(lines)} items -> {len(manifest)} batches "
          f"({len(manifest) // 2} per pass), batch size {BATCH}")
    print(f"  every item covered once per pass: {covered} == {len(lines)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
