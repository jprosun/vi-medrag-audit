"""Score the author's 40-item relevance sheet against the model labels on the same items.

Two things are computed and they answer different questions.

AGREEMENT tells us whether the model judge was reading the codebook the way a person does:
exact three-way agreement, Cohen's kappa, and the confusion matrix, on the 40 items both
judged.

THE HUMAN RATE tells us what the headline should say. It cannot be read off as 2/40: the
sheet was drawn 8 per question type, and the population is not 8 per type (65 clinical
explainer, 64 guideline, 33 study-result, 14 differential, 9 patient FAQ). A stratified
sample scored as if it were simple would weight patient-FAQ claims seven times too heavily.
So the human estimate is POST-STRATIFIED -- each stratum's rate weighted by that stratum's
share of the 185 -- and the naive figure is printed next to it so the difference is visible.

NO INTERVAL IS QUOTED FOR IT, deliberately. Three of the five strata observed zero relevant
items out of eight, so a bootstrap that resamples within them returns zero every time and
produces a narrow interval that describes the sample's degeneracy rather than uncertainty
about the population; an earlier version reported [0.000, 0.075] on exactly that basis. The
valid conservative alternative -- summing per-stratum Clopper-Pearson ends -- is computed and
reported as `conservative_envelope`, and it is [0.001, 0.405], which carries no information.
Forty items stratified five ways calibrate a judge; they do not estimate a rate. The
informative outputs here are the agreement statistics.

Run:  python benchmark/rivf/score_human_relevance.py
      python benchmark/rivf/score_human_relevance.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from artifact_provenance import source_sha256

sys.path.insert(0, str(Path(__file__).resolve().parent))
from survey_ci import conservative_envelope  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
LABELS = REPO / "benchmark/rivf/relevance_human_labels_v1.txt"
KEY = REPO / "benchmark/rivf/relevance_key_v1.json"
MODEL = REPO / "benchmark/rivf/relevance_report_v1.json"
OUT = REPO / "benchmark/rivf/relevance_human_v1.json"

LETTER = {"R": "relevant", "P": "partial", "N": "not_relevant"}
LABELS_3 = ["relevant", "partial", "not_relevant"]
ALPHA = 0.05


def parse_sheet(path: Path):
    """rel_NN -> (relevance, support). Refuses a partly filled sheet rather than scoring it."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"(?m)^## (rel_\d{2})\s*$", raw)
    out, blank, bad = {}, [], []
    for i in range(1, len(blocks), 2):
        rid, body = blocks[i], blocks[i + 1]
        m = re.search(r"(?m)^=>\s*(.*)$", body)
        if not m:
            bad.append((rid, "no => line"))
            continue
        val = m.group(1).strip()
        if not val:
            blank.append(rid)
            continue
        toks = val.replace(",", " ").split()
        r = toks[0].upper()
        s = toks[1].upper() if len(toks) > 1 else ""
        if r not in LETTER or s not in ("", "Y", "N"):
            bad.append((rid, val))
            continue
        out[rid] = (LETTER[r], s)
    if blank or bad:
        raise SystemExit(f"sheet not ready: {len(blank)} blank {blank}, malformed {bad}")
    return out


def kappa(pairs, categories):
    n = len(pairs)
    if not n:
        return None
    po = sum(1 for a, b in pairs if a == b) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum((ca[c] / n) * (cb[c] / n) for c in categories)
    return None if pe >= 1 else round((po - pe) / (1 - pe), 4)


def poststratified(rate_by_stratum, weights):
    return sum(weights[s] * r for s, r in rate_by_stratum.items())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    human = parse_sheet(LABELS)
    key = json.loads(KEY.read_text(encoding="utf-8"))
    model_report = json.loads(MODEL.read_text(encoding="utf-8"))

    by_source = {r["source_item"]: r for r in model_report["per_item"] if r["kind"] == "real"}
    pop = {t: v["claims"] for t, v in model_report["by_question_type"].items()}
    total_pop = sum(pop.values())
    weights = {t: n / total_pop for t, n in pop.items()}

    rows = []
    for rid, (h, s) in sorted(human.items()):
        meta = key["key"][rid]
        m = by_source.get(meta["entailment_item"])
        if m is None:
            raise SystemExit(f"{rid}: no model label for {meta['entailment_item']}")
        rows.append(
            {
                "item_id": rid,
                "entailment_item": meta["entailment_item"],
                "query_id": meta["query_id"],
                "question_type": meta["question_type"],
                "human": h,
                "human_support": s,
                "model": m["label"],
                "model_source": m["label_source"],
                "agree": h == m["label"],
            }
        )

    pairs = [(r["human"], r["model"]) for r in rows]
    agree = sum(1 for r in rows if r["agree"])
    confusion = Counter((r["human"], r["model"]) for r in rows)

    # binary collapse: the headline is a "relevant" rate, so this is the agreement that
    # matters for it
    bin_pairs = [(("relevant" if h == "relevant" else "other"),
                  ("relevant" if m == "relevant" else "other")) for h, m in pairs]
    bin_agree = sum(1 for a, b in bin_pairs if a == b)

    per_type = {}
    for t in sorted({r["question_type"] for r in rows}):
        g = [r for r in rows if r["question_type"] == t]
        per_type[t] = {
            "items": len(g),
            "human_relevant": sum(1 for r in g if r["human"] == "relevant"),
            "model_relevant": sum(1 for r in g if r["model"] == "relevant"),
            "agree": sum(1 for r in g if r["agree"]),
            "human_relevant_rate": round(sum(1 for r in g if r["human"] == "relevant") / len(g), 4),
            "population_claims": pop.get(t),
            "population_weight": round(weights.get(t, 0), 4),
        }

    h_rate_by_t = {t: v["human_relevant_rate"] for t, v in per_type.items()}
    ps = poststratified(h_rate_by_t, weights)

    envelope = conservative_envelope(
        {t: (v["human_relevant"], v["items"]) for t, v in per_type.items()},
        {t: weights[t] for t in per_type},
    )
    assert abs(sum(weights[t] for t in per_type) - 1.0) < 1e-9, (
        "the five question types must exhaust the 185; a missing stratum would silently "
        "shrink both the point estimate and the envelope")

    m_head = model_report["headline"]
    report = {
        "what_this_is": (
            "The author's 40-item relevance sheet, scored against the model labels on the same "
            "items. The sheet is stratified 8 per question type, so the human rate is "
            "post-stratified to the 185-claim population; the naive rate is given beside it."
        ),
        "provenance": {
            "sheet": str(LABELS.relative_to(REPO)).replace("\\", "/"),
            "filled_sheet_sha256": source_sha256(LABELS),
            "what_that_hash_is": (
                "the bytes actually scored, which identifies THIS grading. items_sha256 below "
                "proves the items were frozen before any label existed; the two answer "
                "different questions and an earlier version recorded only the second."
            ),
            "items": key["items_file"],
            "items_sha256": key["items_sha256"],
            "frozen_before_grading": True,
            "graded_by": "the author, blind to the model labels and to the system's verdicts",
            "model_labels": str(MODEL.relative_to(REPO)).replace("\\", "/"),
            "interval_method": (
                "none quoted: three of five strata observed zero relevant items, so no interval "
                "from this sheet is informative. See conservative_envelope and survey_ci.py."
            ),
        },
        "agreement": {
            "items": len(rows),
            "exact_three_way": round(agree / len(rows), 4),
            "cohens_kappa": kappa(pairs, LABELS_3),
            "relevant_vs_other": round(bin_agree / len(rows), 4),
            "relevant_vs_other_kappa": kappa(bin_pairs, ["relevant", "other"]),
            "confusion_human_by_model": {f"{h}|{m}": c for (h, m), c in sorted(confusion.items())},
            "human_distribution": dict(Counter(r["human"] for r in rows)),
            "model_distribution_on_these_40": dict(Counter(r["model"] for r in rows)),
        },
        "human_relevant_rate": {
            "naive_on_the_sheet": round(sum(1 for r in rows if r["human"] == "relevant") / len(rows), 4),
            "post_stratified_to_the_185": round(ps, 4),
            "no_interval_quoted": (
                "Three of five strata observed 0 of 8. An earlier version reported [0.000, "
                "0.075] from a bootstrap that could only return 0 in those strata."
            ),
            "conservative_envelope": envelope["envelope"],
            "conservative_envelope_per_stratum": envelope["per_stratum"],
            "why_post_stratified": (
                "8 items were drawn per question type, but the population is 65/64/33/14/9 "
                "across the five types; scoring the sheet naively would weight patient-FAQ "
                "claims about seven times too heavily."
            ),
            "model_rate_on_the_same_185": m_head["relevant_rate_ci"],
            "model_relevant_on_these_40": sum(1 for r in rows if r["model"] == "relevant"),
        },
        "by_question_type": per_type,
        "support_column": {
            "filled": sum(1 for r in rows if r["human_support"]),
            "note": "Optional column; left blank means the author did not open the passage for that item.",
        },
        "per_item": rows,
    }

    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("report reproduces exactly" if same else "REPORT DIFFERS from a fresh run")
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8")

    a = report["agreement"]
    hr = report["human_relevant_rate"]
    print(f"wrote {OUT.relative_to(REPO)}")
    print(f"  items {a['items']} | exact agreement {a['exact_three_way']} | kappa {a['cohens_kappa']}")
    print(f"  relevant-vs-other agreement {a['relevant_vs_other']} | kappa {a['relevant_vs_other_kappa']}")
    print(f"  human   {a['human_distribution']}")
    print(f"  model   {a['model_distribution_on_these_40']}")
    print(f"  human relevant: naive {hr['naive_on_the_sheet']} | post-stratified "
          f"{hr['post_stratified_to_the_185']} (no interval; envelope {hr['conservative_envelope']})")
    print(f"  model relevant on the same 185: {hr['model_rate_on_the_same_185']}")
    print("  disagreements:")
    for r in rows:
        if not r["agree"]:
            print(f"    {r['item_id']} [{r['question_type']:22}] human {r['human']:13} model {r['model']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
