"""Score the author's 30-item entailment sheet against the model labels on the same items.

The sheet is two strata with very different weights, so the arithmetic matters more than it
did for relevance:

  A  census of all 6 items the model did not call supported,  weight 6/185
  B  sample of 24 of the 179 it did,                          weight 179/185

  supported_rate = (6/185) x (supported share of A, KNOWN) + (179/185) x p_B

Read naively -- 27 of 30 -- the sheet would say 0.90 and be wrong in the alarming direction,
because stratum A is over-represented about thirtyfold on purpose.

THE INTERVAL WAS WRONG ONCE AND THE FIX IS THE POINT. The first version bootstrapped both
strata and reported [0.973, 0.995]. Stratum A is a CENSUS: the author judged all six and
called exactly three supported, so its contribution is the constant 3/185 and resampling it
is meaningless -- worse, it let A appear as 6/6 and pushed the upper bound above 0.9838,
which is the largest rate the design can express. Only stratum B carries sampling
uncertainty; with 24 of 24 successes the honest interval is exact Clopper-Pearson, and
survey_ci.post_stratified_two_strata asserts the result lies inside the feasible bounds.

Run:  python benchmark/rivf/score_human_entailment.py
      python benchmark/rivf/score_human_entailment.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

from artifact_provenance import source_sha256

sys.path.insert(0, str(Path(__file__).resolve().parent))
from survey_ci import clopper_pearson, post_stratified_two_strata  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SHEET = REPO / "benchmark/rivf/entailment_human_labels_v1.txt"
KEY = REPO / "benchmark/rivf/entailment_human_key_v1.json"
MODEL = REPO / "benchmark/rivf/entailment_report_v1.json"
ITEMS = REPO / "benchmark/rivf/entailment_items_v1.jsonl"
OUT = REPO / "benchmark/rivf/entailment_human_v1.json"

LETTER = {"S": "supported", "O": "overstated", "N": "not_supported", "U": "unintelligible"}
LABELS_4 = ["supported", "overstated", "not_supported", "unintelligible"]
ALPHA = 0.05


def parse_sheet(path: Path):
    raw = path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"(?m)^## (ent_h_\d{2})\s*$", raw)
    out, blank, bad = {}, [], []
    for i in range(1, len(blocks), 2):
        hid, body = blocks[i], blocks[i + 1]
        m = re.search(r"(?m)^=>\s*(.*)$", body)
        if not m:
            bad.append((hid, "no => line"))
            continue
        v = m.group(1).strip().upper()
        if not v:
            blank.append(hid)
            continue
        tok = v.replace(",", " ").split()[0]
        if tok not in LETTER:
            bad.append((hid, v))
            continue
        out[hid] = LETTER[tok]
    if blank or bad:
        raise SystemExit(f"sheet not ready: blank {blank}, malformed {bad}")
    return out


def kappa(pairs, categories):
    n = len(pairs)
    po = sum(1 for a, b in pairs if a == b) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum((ca[c] / n) * (cb[c] / n) for c in categories)
    return None if pe >= 1 else round((po - pe) / (1 - pe), 4)



def cross_sheet(rows) -> dict:
    """How many DISTINCT claims the two human sheets cover between them.

    The entailment and relevance sheets were drawn independently from the same 185 displayed
    claims, so they overlap. Reporting "70 items" implies 70 claims and overstates coverage;
    the sheets share nine, so it is 70 judgements over 61 distinct claims. The paper says the
    latter, and this is where that number comes from.
    """
    rel = REPO / "benchmark/rivf/relevance_human_v1.json"
    if not rel.exists():
        return {"status": "relevance sheet not scored yet"}
    other = {r["entailment_item"] for r in json.loads(rel.read_text(encoding="utf-8"))["per_item"]}
    mine = {r["entailment_item"] for r in rows}
    return {
        "judgements": len(mine) + len(other),
        "distinct_claims": len(mine | other),
        "shared_by_both_sheets": sorted(mine & other),
        "why_it_matters": (
            "70 judgements is not 70 claims. Quoting the judgement count as a claim count "
            "overstates how much of the 185 was read by a person."
        ),
    }

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    human = parse_sheet(SHEET)
    keyblob = json.loads(KEY.read_text(encoding="utf-8"))
    key = keyblob["key"]
    design = keyblob["design"]
    model_report = json.loads(MODEL.read_text(encoding="utf-8"))
    model = {r["item_id"]: r["label"] for r in model_report["per_item"] if r["kind"] == "real"}
    items = {json.loads(l)["item_id"]: json.loads(l) for l in ITEMS.open(encoding="utf-8")}

    rows = []
    for hid, h in sorted(human.items()):
        meta = key[hid]
        rows.append(
            {
                "item_id": hid,
                "entailment_item": meta["entailment_item"],
                "stratum": meta["stratum"],
                "query_id": meta["query_id"],
                "question_type": meta["question_type"],
                "span_equals_claim": meta["span_equals_claim"],
                "human": h,
                "model": model[meta["entailment_item"]],
                "agree": h == model[meta["entailment_item"]],
            }
        )

    A = [r for r in rows if r["stratum"] == "A_model_failure"]
    B = [r for r in rows if r["stratum"] == "B_model_supported"]
    nA_pop = design["A_model_failure"]["population"]
    nB_pop = design["B_model_supported"]["population"]
    supA = sum(1 for r in A if r["human"] == "supported")
    supB = sum(1 for r in B if r["human"] == "supported")
    assert len(A) == nA_pop, "stratum A must be the census it claims to be"

    est = post_stratified_two_strata(supA, nA_pop, supB, len(B), nB_pop, ALPHA)
    precision_lo, precision_hi = clopper_pearson(supB, len(B), ALPHA)

    pairs = [(r["human"], r["model"]) for r in rows]
    report = {
        "what_this_is": (
            "The author's 30-item entailment sheet, scored against the model labels on the same "
            "items. Two strata with weights 179/185 and 6/185, so the naive 27/30 is not the "
            "estimate."
        ),
        "provenance": {
            "sheet": str(SHEET.relative_to(REPO)).replace("\\", "/"),
            "blank_sheet_sha256": keyblob.get("blank_sheet_sha256") or keyblob["sheet_sha256"],
            "filled_sheet_sha256": source_sha256(SHEET),
            "what_the_two_hashes_are": (
                "blank = the sheet as issued, which proves the items were frozen before any "
                "label existed; filled = the bytes actually scored, which identifies THIS "
                "grading. Recording only the blank hash, as an earlier version did, leaves two "
                "different sets of labels indistinguishable in the provenance."
            ),
            "frozen_before_grading": True,
            "graded_by": "the author, blind to the model labels and to the strata",
            "model_labels": str(MODEL.relative_to(REPO)).replace("\\", "/"),
            "design": design,
            "interval_method": "census exact + Clopper-Pearson on the sampled stratum; see survey_ci.py",
        },
        "cross_sheet": cross_sheet(rows),
        "agreement": {
            "items": len(rows),
            "exact_four_way": round(sum(1 for r in rows if r["agree"]) / len(rows), 4),
            "cohens_kappa": kappa(pairs, LABELS_4),
            "human_distribution": dict(Counter(r["human"] for r in rows)),
            "model_distribution_on_these_30": dict(Counter(r["model"] for r in rows)),
            "confusion_human_by_model": {f"{h}|{m}": c for (h, m), c in sorted(Counter(pairs).items())},
        },
        "stratum_A_model_failures": {
            "items": len(A),
            "kind": "census of all 6",
            "human_labels": dict(Counter(r["human"] for r in A)),
            "confirmed_as_a_failure": sum(1 for r in A if r["human"] != "supported"),
            "overturned_to_supported": sum(1 for r in A if r["human"] == "supported"),
            "detail": [
                {"item": r["item_id"], "model": r["model"], "human": r["human"]} for r in A
            ],
        },
        "stratum_B_model_supported": {
            "items": len(B),
            "kind": "sample of 24 of 179, allocated by question type",
            "human_labels": dict(Counter(r["human"] for r in B)),
            "precision_of_the_model_supported_label": round(supB / len(B), 4),
            "precision_ci_clopper_pearson": [round(precision_lo, 4), round(precision_hi, 4)],
            "precision_note": (
                "Measured on the 24 sampled claims, not on all 179. With 24 of 24 the exact "
                "lower bound is 0.86, so the sample is consistent with as many as 14 % of the "
                "179 being claims a reader would not call supported."
            ),
            "downgraded_by_the_author": [
                {"item": r["item_id"], "human": r["human"], "question_type": r["question_type"]}
                for r in B if r["human"] != "supported"
            ],
        },
        "overstated": {
            "found_by_the_author": sum(1 for r in rows if r["human"] == "overstated"),
            "found_by_the_model_over_all_185": model_report["headline"]["label_distribution"]["overstated"]["n"],
            "why_it_matters": (
                "An over-strong claim wearing a real quotation is the failure mode this paper "
                "predicts. Neither judge found one at the claim layer, which is consistent with "
                "the extractor copying passage sentences rather than authoring claims."
            ),
        },
        "human_supported_rate": {
            "naive_on_the_sheet": round(sum(1 for r in rows if r["human"] == "supported") / len(rows), 4),
            "post_stratified_to_the_185": [est["point"], est["ci"][0], est["ci"][1]],
            "method": est["method"],
            "sampled_stratum_proportion_and_ci": est["sampled_proportion"],
            "census_stratum_proportion": est["census_proportion"],
            "feasible_bounds_of_the_design": est["feasible_bounds_of_the_design"],
            "why_post_stratified": (
                "Stratum A is 6 of 185 claims but 6 of 30 sheet items, so it is over-represented "
                "about thirtyfold by design; read naively the sheet understates the rate."
            ),
            "why_not_a_bootstrap": (
                "An earlier version bootstrapped both strata and reported [0.973, 0.995]. "
                "Stratum A is a census, so resampling it invents states that cannot occur, and "
                "the upper bound exceeded 0.9838, the maximum the design can express."
            ),
            "model_rate_on_the_same_185": model_report["headline"]["supported_rate_ci"],
        },
        "per_item": rows,
    }

    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("report reproduces exactly" if same else "REPORT DIFFERS from a fresh run")
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8")

    a, hs = report["agreement"], report["human_supported_rate"]
    print(f"wrote {OUT.relative_to(REPO)}")
    print(f"  items {a['items']} | exact agreement {a['exact_four_way']} | kappa {a['cohens_kappa']}")
    print(f"  human {a['human_distribution']}")
    print(f"  model {a['model_distribution_on_these_30']}")
    print(f"\n  stratum A (all 6 model failures): {report['stratum_A_model_failures']['human_labels']}")
    for d in report["stratum_A_model_failures"]["detail"]:
        mark = "CONFIRMED" if d["human"] != "supported" else "OVERTURNED -> supported"
        print(f"    {d['item']}  model {d['model']:16} human {d['human']:16} {mark}")
    sb = report["stratum_B_model_supported"]
    print(f"\n  stratum B (24 of 179 supported): precision {sb['precision_of_the_model_supported_label']} "
          f"CI {sb['precision_ci_clopper_pearson']}")
    for d in report["stratum_B_model_supported"]["downgraded_by_the_author"]:
        print(f"    downgraded {d['item']} -> {d['human']} [{d['question_type']}]")
    print(f"\n  overstated found: author {report['overstated']['found_by_the_author']}, "
          f"model over all 185 {report['overstated']['found_by_the_model_over_all_185']}")
    print(f"  human supported rate: naive {hs['naive_on_the_sheet']} | post-stratified "
          f"{hs['post_stratified_to_the_185']}")
    print(f"    design can only express {hs['feasible_bounds_of_the_design']}")
    print(f"  model rate on the same 185: {hs['model_rate_on_the_same_185']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
