"""What configuration the two captured runs actually ran under, read from their own metadata.

WHY THIS EXISTS. Section III described "an evidence extractor" and left the reader to picture
one configuration. An independent review pointed out that the capture metadata says otherwise,
and it is right: a router picks a retrieval profile per question, and the LLM extractor is
engaged on only half of them. That matters because it is the other half -- no LLM extraction --
that the paper's 183-of-185 verbatim-sentence finding partly describes.

It is NOT an arm confound: the profile, top-k and extractor state are identical per query ID
across the two arms, which this checks rather than assumes.

What the capture does NOT record is the generator or verifier model ID. That is a real gap and
it is reported as absent here, not filled in from the current default config, because a default
read today is not evidence about a run from 2026-09-05.

    python benchmark/rivf/run_configuration.py
    python benchmark/rivf/run_configuration.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from artifact_provenance import source_sha256

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "benchmark/rivf/run_configuration_v1.json"
TR = REPO / "benchmark/datasets/test_results"

CAPS = {
    "shipped": TR / "pilot_span_exposure_rivf134_2026-09-05_091659_raw.jsonl",
    "url_first": TR / "pilot_span_exposure_urlfirst_2026-09-07_035612_raw.jsonl",
}

# the pipeline fields that describe the SETTING, not the outcome. coverage_mode and
# retrieval_mode are deliberately excluded from the per-question equality test below: they are
# chosen from what retrieval returned, so they are expected to differ between arms.
SETTING = ("retrieval_profile", "retrieval_top_k", "llm_extractor_enabled",
           "llm_extractor_used", "router_needs_extractor")
OUTCOME = ("coverage_mode", "retrieval_mode")

# From services/rag-orchestrator/app/run_export.py: the served candidate pool is
# base_top_k x multiplier, so `retrieval_top_k` is a BASE and not the number of chunks that
# reach the answer. Recorded here because the paper prints the consequence.
SERVED_RAW_LIMIT_MULTIPLIERS = {"mechanistic_synthesis": 4, "topic_summary": 3}
SERVED_RAW_LIMIT_MULTIPLIER_DEFAULT = 2


def rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def pipeline_of(r: dict) -> dict:
    return ((r.get("payload") or {}).get("metadata") or {}).get("pipeline") or {}


def build() -> dict:
    out = {
        "what_this_is": (
            "The retrieval and extraction configuration of the two captured runs, read from "
            "each response's own metadata.pipeline. Not inferred from any config file."
        ),
        "arms": {},
    }
    settings_by_q = {}

    for arm, path in CAPS.items():
        rs = rows(path)
        pipes = {r.get("query_id"): pipeline_of(r) for r in rs}
        settings_by_q[arm] = {
            q: {k: p.get(k) for k in SETTING} for q, p in pipes.items()
        }
        # claims and the retrieved-chunk union, per profile. "half the questions" is not
        # "half the claims", and top_k is not the chunk count.
        per_profile = defaultdict(lambda: {"questions": 0, "claims_total": 0,
                                           "claims_displayed": 0, "chunks": []})
        for r in rs:
            pay = r.get("payload") or {}
            md = pay.get("metadata") or {}
            d = per_profile[(pipeline_of(r).get("retrieval_profile"))]
            d["questions"] += 1
            d["claims_total"] += md.get("claims_total") or 0
            d["claims_displayed"] += md.get("claims_displayed") or 0
            d["chunks"].append(len(pay.get("retrieved_chunks") or []))
        profiles = {}
        for prof, d in per_profile.items():
            ch = d["chunks"]
            profiles[str(prof)] = {
                "questions": d["questions"],
                "claims_total": d["claims_total"],
                "claims_displayed": d["claims_displayed"],
                "retrieved_chunks_sum": sum(ch),
                "retrieved_chunks_median": statistics.median(ch),
                "retrieved_chunks_range": [min(ch), max(ch)],
            }
        all_chunks = [c for d in per_profile.values() for c in d["chunks"]]
        claims_all = sum(d["claims_total"] for d in per_profile.values())
        no_extractor = profiles.get("standard", {}).get("claims_total", 0)

        out["arms"][arm] = {
            "capture": str(path.relative_to(REPO)).replace("\\", "/"),
            "by_profile": profiles,
            "claims_from_the_no_extractor_half": {
                "claims": no_extractor,
                "of_all_claims": claims_all,
                "share": round(no_extractor / claims_all, 4) if claims_all else None,
                "note": ("the standard profile does not use the LLM extractor and produced the "
                         "MAJORITY of claims, not half; half the QUESTIONS is not half the "
                         "claims"),
            },
            "retrieved_chunks": {
                "total": sum(all_chunks),
                "median_per_question": statistics.median(all_chunks),
                "range_per_question": [min(all_chunks), max(all_chunks)],
                "why_it_exceeds_top_k": (
                    "`retrieval_top_k` is a base; the served candidate pool is base x a "
                    "retrieval_mode multiplier (3 for topic_summary, which covers most "
                    "questions here, 4 for mechanistic_synthesis, else 2), and the response "
                    "records what survives deduplication. So 67x12 + 67x20 is not the "
                    "expected total."
                ),
                "served_pool_multipliers": SERVED_RAW_LIMIT_MULTIPLIERS,
                "served_pool_multiplier_default": SERVED_RAW_LIMIT_MULTIPLIER_DEFAULT,
            },
            "capture_sha256": source_sha256(path),
            "responses": len(rs),
            "settings": {k: dict(Counter(str(p.get(k)) for p in pipes.values()))
                         for k in SETTING},
            "outcomes_expected_to_differ": {
                k: dict(Counter(
                    str(((r.get("payload") or {}).get("metadata") or {}).get(k)) for r in rs))
                for k in OUTCOME
            },
            "generator_model_id": None,
            "verifier_model_id": None,
        }

    a, b = settings_by_q["shipped"], settings_by_q["url_first"]
    common = sorted(set(a) & set(b))
    identical = [q for q in common if a[q] == b[q]]
    out["cross_arm"] = {
        "questions_in_both": len(common),
        "identical_setting_per_question": len(identical),
        "differing": [q for q in common if a[q] != b[q]],
        "reading": (
            "the mixed configuration is chosen per question and matched across arms, so it is "
            "a Methods fact rather than a between-arm confound"
        ),
    }
    out["not_recorded_by_the_capture"] = {
        "fields": ["generator model id", "verifier model id", "decoding parameters"],
        "why_not_filled_in": (
            "the capture has no model field, and the current default config is evidence about "
            "today's checkout, not about a run captured on 2026-09-05"
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
            print("no run-configuration artifact committed yet")
            return 1
        stored = json.loads(OUT.read_text(encoding="utf-8"))
        checked = ("settings", "capture_sha256", "responses", "by_profile", "retrieved_chunks", "claims_from_the_no_extractor_half")
        bad = []
        for arm in fresh["arms"]:
            for field in checked:
                if stored["arms"].get(arm, {}).get(field) != fresh["arms"][arm][field]:
                    bad.append(f"{arm}.{field}")
        if stored.get("cross_arm") != fresh["cross_arm"]:
            bad.append("cross_arm")
        print("the run configuration re-derives from the captures" if not bad
              else f"MISMATCH: {bad}")
        return 1 if bad else 0

    OUT.write_text(json.dumps(fresh, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}\n")
    for arm, d in fresh["arms"].items():
        print(f"  {arm}: {d['responses']} responses")
        for k, v in d["settings"].items():
            print(f"    {k:24} {v}")
        for prof, pd in sorted(d["by_profile"].items()):
            print(f"    profile {prof:9} questions {pd['questions']:3} "
                  f"claims {pd['claims_total']:4}  chunks median "
                  f"{pd['retrieved_chunks_median']:.0f} range {pd['retrieved_chunks_range']}")
        n = d["claims_from_the_no_extractor_half"]
        print(f"    claims from the NO-extractor half: {n['claims']}/{n['of_all_claims']} "
              f"= {n['share']}")
        c = d["retrieved_chunks"]
        print(f"    retrieved chunks {c['total']}, median/question "
              f"{c['median_per_question']:.0f}, range {c['range_per_question']}")
    c = fresh["cross_arm"]
    print(f"\n  identical setting per question: {c['identical_setting_per_question']}"
          f"/{c['questions_in_both']}  differing: {c['differing']}")
    print(f"  NOT recorded: {', '.join(fresh['not_recorded_by_the_capture']['fields'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
