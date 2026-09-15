"""Support x relevance, and the question-level coverage, computed from ONE label version.

WHY THIS EXISTS. After the matched-arm re-judging the paper printed the new per-claim RATES
beside joint counts carried over from the ORIGINAL judging -- "95 supported-but-unrelated
against 49". Those two cannot both be current: under the matched labels the URL-first arm has
only 83 not_relevant claims in total, so 95 of them cannot also be supported. An independent
review caught it. Mixing label versions inside one comparison is the failure this file exists
to prevent, so every joint quantity here is derived from the same resolved label set and the
version is named in the output.

THE JOIN. Relevance items are built from entailment items, one per claim, but the two arms
record the link differently:

    shipped    the relevance key carries `source_item`, the entailment item id -- a direct link
    URL-first  it carries `query_id` + `chunk_id` only, so the join is on that pair

A (query_id, chunk_id) pair can cover more than one claim, so the pair join can be
many-to-many. Rather than assume it is not, every multi-match group is checked to carry a
single entailment label, and the count of such groups is reported. A group that disagreed
would make the joint counts ambiguous and is refused.

    python benchmark/rivf/joint_support_relevance.py
    python benchmark/rivf/joint_support_relevance.py --check
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "benchmark/rivf/joint_support_relevance_v1.json"
B = REPO / "benchmark/rivf"

MATCHED_URLFIRST = B / "arm_matched_rejudge_v1.json"
PINNED_SHIPPED = B / "judge_rerun_pinned_v1.json"

ORIGINAL = {
    ("shipped", "entailment"): B / "entailment_judgements_v1.json",
    ("shipped", "relevance"): B / "relevance_model_judgements_v1.json",
    ("url_first", "entailment"): B / "entailment_judgements_urlfirst_v1.json",
    ("url_first", "relevance"): B / "relevance_model_judgements_urlfirst_v1.json",
}
ENT_KEY = {"shipped": B / "entailment_key_v1.json", "url_first": B / "entailment_key_urlfirst_v1.json"}
REL_KEY = {"shipped": B / "relevance_model_key_v1.json", "url_first": B / "relevance_model_key_urlfirst_v1.json"}
ENT_ITEMS = {"shipped": B / "entailment_items_v1.jsonl",
             "url_first": B / "entailment_items_urlfirst_v1.jsonl"}
REL_ITEMS = {"shipped": B / "relevance_model_items_v1.jsonl",
             "url_first": B / "relevance_model_items_urlfirst_v1.jsonl"}


def unwrap(blob):
    while isinstance(blob, dict) and "instruments" not in blob:
        for k in ("result", "output"):
            if k in blob:
                blob = blob[k]
                break
        else:
            break
    return blob


def resolve(blob: dict, override: dict | None = None) -> dict:
    a = {j["item_id"]: j["label"] for j in blob.get("pass_a", [])}
    b = {j["item_id"]: j["label"] for j in blob.get("pass_b", [])}
    adj = {j["item_id"]: j["label"] for j in blob.get("adjudication", [])}
    if override:
        adj.update(override)
    return {i: (adj.get(i, a[i]) if a[i] != b[i] else a[i]) for i in a if i in b}


def key_of(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))["key"]


def items_of(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out[r["item_id"]] = r
    return out


def joint(arm: str, ent: dict, rel: dict) -> dict:
    """Pair each relevance label with its claim's entailment label, real items only."""
    ek, rk = key_of(ENT_KEY[arm]), key_of(REL_KEY[arm])
    ent_items, rel_items = items_of(ENT_ITEMS[arm]), items_of(REL_ITEMS[arm])

    # The arm without `source_item` needs a content join. (query_id, chunk_id) alone is NOT
    # enough -- one chunk can back several claims of the same question, and on this arm 14
    # such groups carry more than one entailment label. Adding the claim and the cited
    # passage makes the pairing one-to-one, which is why the review's join names four fields.
    def sig(item, meta):
        return (meta.get("query_id"), meta.get("chunk_id"),
                item.get("claim"), item.get("cited_passage"))

    by_sig: dict[tuple, list[str]] = defaultdict(list)
    for i, v in ek.items():
        if v.get("kind") == "real" and i in ent_items:
            by_sig[sig(ent_items[i], v)].append(i)

    pairs, unmatched, multi, multi_disagreed = [], 0, 0, 0
    by_question: dict[str, list[str]] = defaultdict(list)

    for ri, meta in rk.items():
        if meta.get("kind") != "real" or ri not in rel:
            continue
        src = meta.get("source_item")
        if src:
            cands = [src]
        else:
            cands = by_sig.get(sig(rel_items.get(ri, {}), meta), [])
        cands = [c for c in cands if c in ent]
        if not cands:
            unmatched += 1
            continue
        labels = {ent[c] for c in cands}
        if len(cands) > 1:
            multi += 1
            if len(labels) > 1:
                multi_disagreed += 1
        pairs.append((cands[0], ent[cands[0]], rel[ri]))
        by_question[meta.get("query_id")].append(rel[ri])

    assert multi_disagreed == 0, (
        f"{multi_disagreed} (query_id, chunk_id) groups carry more than one entailment label; "
        "the joint counts would be ambiguous"
    )

    cells = Counter(f"{e}|{r}" for _, e, r in pairs)
    return {
        "claims_joined": len(pairs),
        "unmatched_relevance_items": unmatched,
        "multi_match_groups": multi,
        "multi_match_groups_with_disagreeing_entailment": multi_disagreed,
        "cells": dict(sorted(cells.items())),
        "supported_and_not_relevant": cells.get("supported|not_relevant", 0),
        "supported_and_partial": cells.get("supported|partial", 0),
        "supported_and_relevant": cells.get("supported|relevant", 0),
        "questions_with_any_claim": len(by_question),
        "questions_with_at_least_one_relevant": sum(
            1 for v in by_question.values() if "relevant" in v),
        "questions_where_every_claim_is_not_relevant": sum(
            1 for v in by_question.values() if v and set(v) == {"not_relevant"}),
        "relevance_distribution": dict(Counter(r for _, _, r in pairs)),
    }


def build() -> dict:
    matched = unwrap(json.loads(MATCHED_URLFIRST.read_text(encoding="utf-8")))
    pinned = unwrap(json.loads(PINNED_SHIPPED.read_text(encoding="utf-8")))
    rematch = matched.get("shipped_rematch") or {}

    out = {"label_versions": {}, "arms": {}}

    # --- the matched label version: what the paper's arm comparison must use -------------
    ship = {ins: resolve(pinned["instruments"][ins],
                         {j["item_id"]: j["label"] for j in rematch.get(ins, [])})
            for ins in ("entailment", "relevance")}
    url = {ins: resolve(matched["instruments"][ins]) for ins in ("entailment", "relevance")}

    out["label_versions"]["matched"] = (
        "shipped = the pinned re-run with its adjudications replaced by the Rematch verdicts; "
        "URL-first = matched-arm-rejudge.js. Same codebook, model, adjudicator prompt and "
        "batch size on both sides."
    )
    out["arms"]["shipped_matched"] = joint("shipped", ship["entailment"], ship["relevance"])
    out["arms"]["url_first_matched"] = joint("url_first", url["entailment"], url["relevance"])

    # --- the original label version, kept for the record, NOT for the comparison ---------
    o = {}
    for (arm, ins), path in ORIGINAL.items():
        o[(arm, ins)] = resolve(json.loads(path.read_text(encoding="utf-8")))
    out["label_versions"]["original"] = (
        "the first judging passes: shipped entailment claude-opus-5, everything else "
        "claude-fable-5-1, and two different codebooks. Reported for the record; the paper "
        "must not mix these counts with matched rates."
    )
    out["arms"]["shipped_original"] = joint("shipped", o[("shipped", "entailment")], o[("shipped", "relevance")])
    out["arms"]["url_first_original"] = joint("url_first", o[("url_first", "entailment")], o[("url_first", "relevance")])

    m_u = out["arms"]["url_first_matched"]
    o_u = out["arms"]["url_first_original"]
    out["the_error_this_file_prevents"] = {
        "what_the_paper_printed": "95 supported-but-unrelated against 49",
        "those_are_original_labels": {
            "url_first": o_u["supported_and_not_relevant"],
            "shipped": out["arms"]["shipped_original"]["supported_and_not_relevant"],
        },
        "matched_labels_give": {
            "url_first": m_u["supported_and_not_relevant"],
            "shipped": out["arms"]["shipped_matched"]["supported_and_not_relevant"],
        },
        "why_95_is_impossible_under_matched_labels": (
            f"the URL-first arm has {m_u['relevance_distribution'].get('not_relevant', 0)} "
            f"not_relevant claims in total under the matched labels, so 95 of them cannot also "
            f"be supported"
        ),
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    fresh = build()

    if a.check:
        if not OUT.exists():
            print("no joint artifact committed yet")
            return 1
        stored = json.loads(OUT.read_text(encoding="utf-8"))
        bad = [k for k in fresh["arms"] if stored["arms"].get(k) != fresh["arms"][k]]
        print("the joint counts re-derive from the labels" if not bad else f"MISMATCH: {bad}")
        return 1 if bad else 0

    OUT.write_text(json.dumps(fresh, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}\n")
    for name, d in fresh["arms"].items():
        print(f"  {name}")
        print(f"    joined {d['claims_joined']} claims"
              f"  (unmatched {d['unmatched_relevance_items']}, multi-match groups "
              f"{d['multi_match_groups']})")
        print(f"    supported & not_relevant {d['supported_and_not_relevant']}"
              f"   & partial {d['supported_and_partial']}"
              f"   & relevant {d['supported_and_relevant']}")
        print(f"    questions with a claim {d['questions_with_any_claim']}, "
              f"with >=1 relevant {d['questions_with_at_least_one_relevant']}, "
              f"all-unrelated {d['questions_where_every_claim_is_not_relevant']}")
    e = fresh["the_error_this_file_prevents"]
    print(f"\n  paper printed: {e['what_the_paper_printed']}")
    print(f"  original labels: {e['those_are_original_labels']}")
    print(f"  matched labels : {e['matched_labels_give']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
