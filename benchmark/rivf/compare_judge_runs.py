"""Compare the pinned-model judge re-run against the committed labels.

WHAT THIS MEASURES -- stated more carefully than the first version of this file, which claimed
more than the data supports.

Two label sets over the same 222 frozen items, same codebook byte for byte, same batching. The
first version said "the only thing that differs is the model". Two corrections:

  1. FOR ENTAILMENT, THE MODEL DID NOT DIFFER. The original run pinned nothing, but
     judge_model_provenance_v1.json recovers what it was served: claude-opus-5, which is what
     the re-run requested. So the entailment comparison is a WITHIN-model repeatability test.
     Its agreement licenses "0.968 reproduces", not "0.968 is judge-independent".
     The relevance comparison did cross models -- claude-fable-5-1 to claude-opus-5 -- and it
     is the one that moved.

  2. THE ADJUDICATOR PROMPT DIFFERED. Both original scripts handed the adjudicator each blind
     verdict WITH its confidence and rationale; the re-run handed it two bare labels. That is
     a second changed variable. It is bounded rather than waved away: adjudication only fires
     on a disagreement between the two blind passes, so the report below counts how many of the
     changed labels passed through either adjudicator at all. For relevance the answer is 5 of
     15, which leaves 10 changes arising inside the blind passes, where the prompt was
     byte-identical and the model was the only difference.

WHAT TO QUOTE. Agreement and kappa are reported twice: over all 222 items and over the 185 real
claims. Quote the real-claim figures. The controls are 37 deliberately deranged items that both
runs label negative, so including them inflates agreement and inflates kappa further by
stretching the marginal distribution -- entailment kappa is 0.972 over 222 items and 0.829 over
the 185 that are actually measurements.

The controls are still reported, under an explicit criterion, because "36 of 37" and "37 of 37"
are both true of the same run and mean different things: one control moved from `not_relevant`
to `partial`, so every control still avoided the positive label while not every control held its
expected label.

    python benchmark/rivf/compare_judge_runs.py --rerun <workflow-output.json>
    python benchmark/rivf/compare_judge_runs.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "benchmark/rivf/judge_rerun_comparison_v1.json"
PROVENANCE = REPO / "benchmark/rivf/judge_model_provenance_v1.json"

COMMITTED = {
    "entailment": REPO / "benchmark/rivf/entailment_judgements_v1.json",
    "relevance": REPO / "benchmark/rivf/relevance_model_judgements_v1.json",
}
PROMPTS = {
    "entailment": REPO / "benchmark/rivf/judging/entailment_prompt_v1.txt",
    "relevance": REPO / "benchmark/rivf/judging/relevance_prompt_v1.txt",
}
LABELS = {
    "entailment": ["supported", "overstated", "not_supported", "unintelligible"],
    "relevance": ["relevant", "partial", "not_relevant"],
}
KEYS = {
    "entailment": REPO / "benchmark/rivf/entailment_key_v1.json",
    "relevance": REPO / "benchmark/rivf/relevance_model_key_v1.json",
}
POSITIVE = {"entailment": "supported", "relevance": "relevant"}
# What a control is supposed to be labelled: a deranged pairing supports nothing and answers
# nothing.
CONTROL_EXPECTED = {"entailment": "not_supported", "relevance": "not_relevant"}
PROVENANCE_RUNS = {"entailment": "entailment_shipped", "relevance": "relevance_shipped"}


def resolve(blob: dict) -> dict:
    """Final label per item: pass A and B when they agree, the adjudication when they do not."""
    a = {j["item_id"]: j["label"] for j in blob.get("pass_a", [])}
    b = {j["item_id"]: j["label"] for j in blob.get("pass_b", [])}
    adj = {j["item_id"]: j["label"] for j in blob.get("adjudication", [])}
    out = {}
    for i in a:
        if i not in b:
            continue
        out[i] = adj.get(i, a[i]) if a[i] != b[i] else a[i]
    return out


def adjudicated_ids(blob: dict) -> set[str]:
    return {j["item_id"] for j in blob.get("adjudication", [])}


def kappa(pairs, categories):
    n = len(pairs)
    if not n:
        return None
    po = sum(1 for x, y in pairs if x == y) / n
    ca, cb = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
    pe = sum((ca[c] / n) * (cb[c] / n) for c in categories)
    return None if pe >= 1 else round((po - pe) / (1 - pe), 4)


def agreement_block(pairs, categories) -> dict:
    if not pairs:
        return {"n": 0, "agreement": None, "kappa": None}
    agree = sum(1 for x, y in pairs if x == y)
    return {
        "n": len(pairs),
        "agree": agree,
        "agreement": round(agree / len(pairs), 4),
        "kappa": kappa(pairs, categories),
    }


def load_rerun(path: Path) -> dict:
    """The workflow's own output file, or the bare result object.

    Returns the object that still carries BOTH `model_pinned` and `instruments`. An earlier
    version unwrapped one level too far and reported the pinned model as None -- the whole
    point of the re-run, lost to a convenience loop.
    """
    blob = json.loads(path.read_text(encoding="utf-8"))
    while isinstance(blob, dict) and "instruments" not in blob:
        for key in ("result", "output"):
            if key in blob:
                blob = blob[key]
                break
        else:
            break
    assert isinstance(blob, dict) and "instruments" in blob, "no instruments in the re-run output"
    return blob


def judge_models() -> dict:
    if not PROVENANCE.exists():
        return {}
    runs = json.loads(PROVENANCE.read_text(encoding="utf-8")).get("runs", {})
    return {k: (runs.get(v) or {}).get("model_id") for k, v in PROVENANCE_RUNS.items()}


def build(rerun_path: Path) -> dict:
    rerun = load_rerun(rerun_path)
    models = judge_models()
    pinned = rerun.get("model_pinned")

    report = {
        "what_this_is": (
            "The pinned-model judge re-run against the committed labels, over the same frozen "
            "items with the same codebook and batching."
        ),
        "what_it_does_not_show": (
            "For entailment this is not a cross-model comparison: the original run was served "
            "claude-opus-5 and the re-run requested the same family, so its agreement measures "
            "repeatability, not judge-independence. Only the relevance comparison crosses "
            "models."
        ),
        "provenance": {
            "rerun_output": str(rerun_path).replace("\\", "/"),
            "model_alias_requested_by_the_rerun": pinned,
            "model_ids_recovered_for_the_original_runs": models,
            "how_recovered": (
                "benchmark/rivf/judging/recover_judge_models.py, from the `message.model` field "
                "of the run transcripts, with every emitted label cross-checked against the "
                "committed artifact"
            ),
            "alias_is_not_a_checkpoint": (
                "The re-run could only request the alias `opus`; that names a family, so "
                "pinning it does not by itself make the run reproducible."
            ),
            "prompts_held_constant": {
                k: hashlib.sha256(p.read_text(encoding="utf-8").encode()).hexdigest()
                for k, p in PROMPTS.items() if p.exists()
            },
            "prompt_provenance": (
                "Extracted byte-for-byte from the committed scripts that produced the original "
                "labels, so a difference between the runs cannot be a blind-pass prompt "
                "difference."
            ),
            "adjudicator_prompt_NOT_held_constant": (
                "The original scripts gave the adjudicator each verdict with its confidence and "
                "rationale; the re-run gave it two bare labels. Bounded per instrument below."
            ),
        },
        "instruments": {},
    }

    ins_blobs = rerun.get("instruments", {})
    for name, path in COMMITTED.items():
        if name not in ins_blobs:
            report["instruments"][name] = {"status": "absent from the re-run output"}
            continue

        old_blob = json.loads(path.read_text(encoding="utf-8"))
        new_blob = ins_blobs[name]
        old, new = resolve(old_blob), resolve(new_blob)
        shared = sorted(set(old) & set(new))

        controls = set()
        if KEYS[name].exists():
            k = json.loads(KEYS[name].read_text(encoding="utf-8")).get("key", {})
            controls = {i for i, v in k.items()
                        if isinstance(v, dict) and v.get("kind") not in (None, "real")}
        real = [i for i in shared if i not in controls]
        ctrl = [i for i in shared if i in controls]

        pos, exp = POSITIVE[name], CONTROL_EXPECTED[name]

        def rate(labels, ids):
            xs = [labels[i] for i in ids]
            return {
                "n": len(xs),
                "hits": sum(1 for x in xs if x == pos),
                "rate": round(sum(1 for x in xs if x == pos) / len(xs), 4) if xs else None,
            }

        changed = [i for i in shared if old[i] != new[i]]
        touched = [i for i in changed
                   if i in adjudicated_ids(old_blob) or i in adjudicated_ids(new_blob)]

        cross_model = models.get(name) is not None and pinned is not None and \
            not str(models[name]).startswith(f"claude-{pinned}")

        report["instruments"][name] = {
            "judge_model_original": models.get(name),
            "judge_model_rerun_alias": pinned,
            "comparison_type": (
                "cross-model" if cross_model else "within-model repeatability"
            ),
            "quote_these": {
                "note": "the 185 real claims -- controls excluded",
                "stability_on_real_claims": agreement_block(
                    [(old[i], new[i]) for i in real], LABELS[name]),
                "headline_rate_original": rate(old, real),
                "headline_rate_rerun": rate(new, real),
            },
            "all_items_including_controls": {
                "note": (
                    "inflated by 37 deranged controls that both runs label negative; reported "
                    "for completeness, not for quotation"
                ),
                "stability": agreement_block(
                    [(old[i], new[i]) for i in shared], LABELS[name]),
            },
            "control_gate": {
                "controls": len(ctrl),
                "expected_label": exp,
                "held_the_expected_label_original": sum(1 for i in ctrl if old[i] == exp),
                "held_the_expected_label_rerun": sum(1 for i in ctrl if new[i] == exp),
                "avoided_the_positive_label_original": sum(1 for i in ctrl if old[i] != pos),
                "avoided_the_positive_label_rerun": sum(1 for i in ctrl if new[i] != pos),
                "criterion_matters": (
                    "these two counts can differ: a control that drifts to an intermediate "
                    "label fails the first and passes the second"
                ),
                "control_labels_original": dict(Counter(old[i] for i in ctrl)),
                "control_labels_rerun": dict(Counter(new[i] for i in ctrl)),
            },
            "transitions_real_claims": dict(Counter(
                f"{old[i]}|{new[i]}" for i in real if old[i] != new[i])),
            "transitions_controls": dict(Counter(
                f"{old[i]}|{new[i]}" for i in ctrl if old[i] != new[i])),
            "adjudicator_confound": {
                "labels_that_changed": len(changed),
                "of_those_that_passed_through_either_adjudicator": len(touched),
                "items": sorted(touched),
                "reading": (
                    f"at most {len(touched)} of {len(changed)} changes can be attributed to the "
                    f"adjudicator-prompt difference; the remaining "
                    f"{len(changed) - len(touched)} arose inside the blind passes, where the "
                    f"prompt was byte-identical"
                ),
            },
            "label_distribution_original": dict(Counter(old[i] for i in real)),
            "label_distribution_rerun": dict(Counter(new[i] for i in real)),
            "items_that_moved": [
                {"item": i, "original": old[i], "rerun": new[i],
                 "is_control": i in controls,
                 "adjudicated_in_either_run": i in touched}
                for i in changed
            ],
            "internal_agreement_of_the_rerun": new_blob.get("counts"),
        }

    return report


def summarise(report: dict) -> None:
    print(f"  model alias requested by the re-run: "
          f"{report['provenance']['model_alias_requested_by_the_rerun']}")
    print(f"  models recovered for the originals: "
          f"{report['provenance']['model_ids_recovered_for_the_original_runs']}")
    for name, d in report["instruments"].items():
        if "status" in d:
            print(f"\n  {name}: {d['status']}")
            continue
        q, g = d["quote_these"], d["control_gate"]
        print(f"\n  {name}  [{d['comparison_type']}: "
              f"{d['judge_model_original']} -> alias {d['judge_model_rerun_alias']}]")
        s = q["stability_on_real_claims"]
        print(f"    on {s['n']} REAL claims: agreement {s['agreement']} "
              f"({s['agree']}/{s['n']})  kappa {s['kappa']}")
        a = d["all_items_including_controls"]["stability"]
        print(f"    on all {a['n']} items (control-inflated): agreement {a['agreement']}  "
              f"kappa {a['kappa']}")
        print(f"    headline rate: {q['headline_rate_original']['hits']}/"
              f"{q['headline_rate_original']['n']} = {q['headline_rate_original']['rate']}"
              f"  ->  {q['headline_rate_rerun']['hits']}/{q['headline_rate_rerun']['n']} = "
              f"{q['headline_rate_rerun']['rate']}")
        print(f"    controls: {g['held_the_expected_label_rerun']}/{g['controls']} held "
              f"`{g['expected_label']}`, {g['avoided_the_positive_label_rerun']}/{g['controls']} "
              f"avoided `{POSITIVE[name]}`")
        if d["transitions_real_claims"]:
            print(f"    real-claim transitions: {d['transitions_real_claims']}")
        if d["transitions_controls"]:
            print(f"    control transitions:    {d['transitions_controls']}")
        print(f"    {d['adjudicator_confound']['reading']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rerun", type=Path, help="the pinned-model workflow's output JSON")
    ap.add_argument("--check", action="store_true",
                    help="recompute from the artifacts and fail if the committed report differs")
    a = ap.parse_args()

    if a.check:
        # A real gate. The old version only checked that the file existed, which tests nothing
        # about whether the numbers in it are still the numbers the artifacts imply.
        if not OUT.exists():
            print("no comparison artifact committed yet")
            return 1
        stored = json.loads(OUT.read_text(encoding="utf-8"))
        src = Path(stored["provenance"]["rerun_output"])
        if not src.exists():
            src = REPO / "benchmark/rivf/judge_rerun_pinned_v1.json"
        if not src.exists():
            print("the re-run output named in the report is not on disk; cannot re-derive")
            return 1

        fresh = build(src)
        bad = []
        for name, f in fresh["instruments"].items():
            s = stored["instruments"].get(name, {})
            for field in ("comparison_type", "judge_model_original"):
                if s.get(field) != f.get(field):
                    bad.append(f"{name}.{field}: {s.get(field)!r} != {f.get(field)!r}")
            for path in (("quote_these", "stability_on_real_claims", "agreement"),
                         ("quote_these", "stability_on_real_claims", "kappa"),
                         ("quote_these", "headline_rate_original", "rate"),
                         ("quote_these", "headline_rate_rerun", "rate")):
                sv, fv = s, f
                for k in path:
                    sv = (sv or {}).get(k)
                    fv = (fv or {}).get(k)
                if sv != fv:
                    bad.append(f"{name}.{'.'.join(path)}: {sv} != {fv}")
            if s.get("transitions_real_claims") != f.get("transitions_real_claims"):
                bad.append(f"{name}.transitions_real_claims differs")
        print("the committed comparison re-derives from the artifacts"
              if not bad else "MISMATCH between the committed report and the artifacts")
        for b in bad:
            print("  " + b)
        return 1 if bad else 0

    if not a.rerun:
        raise SystemExit("--rerun is required; pass the workflow's output JSON")

    report = build(a.rerun)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}")
    summarise(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
