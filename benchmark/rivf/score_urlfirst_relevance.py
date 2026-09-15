"""Score the URL-first arm's 40-item human relevance sheet.

Report the same human sheet against two explicitly named label versions: original
and matched. The original labels contain no relevant item in this sample; the
matched labels contain two, both graded partial by the author. Human labels are
never changed to fit either model. Rates on this small sample are descriptive;
we do not use a zero-event bootstrap as a population confidence interval.

    python benchmark/rivf/score_urlfirst_relevance.py
    python benchmark/rivf/score_urlfirst_relevance.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from artifact_provenance import source_sha256
from joint_support_relevance import unwrap, resolve

REPO = Path(__file__).resolve().parents[2]
SHEET = REPO / "benchmark/rivf/relevance_human_labels_urlfirst_v1.txt"
KEY = REPO / "benchmark/rivf/relevance_human_key_urlfirst_v1.json"
MODEL = REPO / "benchmark/rivf/relevance_report_urlfirst_v1.json"
OUT = REPO / "benchmark/rivf/relevance_human_urlfirst_v1.json"
MATCHED = REPO / "benchmark/rivf/arm_matched_rejudge_v1.json"

LETTER = {"R": "relevant", "P": "partial", "N": "not_relevant"}
LABELS = list(LETTER.values())


def parse_sheet(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"(?m)^## (relu_\d{2})\s*$", raw)
    out, blank, bad = {}, [], []
    for i in range(1, len(blocks), 2):
        rid, body = blocks[i], blocks[i + 1]
        m = re.search(r"(?m)^=>\s*(.*)$", body)
        if not m:
            bad.append((rid, "no => line"))
            continue
        v = m.group(1).strip()
        if not v:
            blank.append(rid)
            continue
        toks = v.replace(",", " ").split()
        r = toks[0].upper()
        s = toks[1].upper() if len(toks) > 1 else ""
        if r not in LETTER or s not in ("", "Y", "N"):
            bad.append((rid, v))
            continue
        out[rid] = (LETTER[r], s or None)
    if blank or bad:
        raise SystemExit(f"sheet not ready: blank {blank}, malformed {bad}")
    return out


def kappa(pairs, categories):
    n = len(pairs)
    if not n:
        return None
    po = sum(1 for a, b in pairs if a == b) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum((ca[c] / n) * (cb[c] / n) for c in categories)
    return None if pe >= 1 else round((po - pe) / (1 - pe), 4)


def agreement_stats(rows):
    pairs = [(r["human"], r["model"]) for r in rows]
    binary = [(a == "relevant", b == "relevant") for a, b in pairs]
    return {
        "items": len(rows),
        "exact_three_way": round(sum(a == b for a, b in pairs) / len(rows), 4),
        "cohens_kappa": kappa(pairs, LABELS),
        "relevant_vs_other": round(sum(a == b for a, b in binary) / len(rows), 4),
        "relevant_vs_other_kappa": kappa(binary, [True, False]),
        "human_distribution": dict(Counter(a for a, b in pairs)),
        "model_distribution_on_these_40": dict(Counter(b for a, b in pairs)),
        "confusion_human_by_model": {f"{a}|{b}": c for (a, b), c in sorted(Counter(pairs).items())},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    human = parse_sheet(SHEET)
    kb = json.loads(KEY.read_text(encoding="utf-8"))
    key, design = kb["key"], kb["design"]
    model_report = json.loads(MODEL.read_text(encoding="utf-8"))

    rows = []
    for rid, (label, support) in sorted(human.items()):
        k = key[rid]
        rows.append({
            "item_id": rid,
            "relevance_item": k["relevance_item"],
            "query_id": k["query_id"],
            "question_type": k["question_type"],
            "human": label,
            "human_support": support,
            "model": k["model_label"],
            "model_entailment": k.get("entailment_label"),
            "agree": label == k["model_label"],
        })

    if set(human) != set(key):
        raise ValueError("Human sheet must contain exactly the frozen 40 items")
    matched_blob = unwrap(json.loads(MATCHED.read_text(encoding="utf-8")))["instruments"]["relevance"]
    pa = {r["item_id"]: r["label"] for r in matched_blob["pass_a"]}
    pb = {r["item_id"]: r["label"] for r in matched_blob["pass_b"]}
    adj = {r["item_id"]: r["label"] for r in matched_blob["adjudication"]}
    if set(pa) != set(pb) or any(i not in adj for i in pa if pa[i] != pb[i]):
        raise ValueError("Incomplete matched judging passes/adjudications")
    matched = resolve(matched_blob)
    matched_rows = [dict(r, model=matched[r["relevance_item"]],
                         agree=r["human"] == matched[r["relevance_item"]]) for r in rows]

    per_type: dict[str, dict] = {}
    grouped: defaultdict[str, list] = defaultdict(list)
    for r in rows:
        grouped[r["question_type"]].append(r)
    for t, g in sorted(grouped.items()):
        per_type[t] = {
            "items": len(g),
            "human_relevant": sum(1 for r in g if r["human"] == "relevant"),
            "human_relevant_rate": round(sum(1 for r in g if r["human"] == "relevant") / len(g), 4),
            "model_relevant": sum(1 for r in g if r["model"] == "relevant"),
            "exact_agreement": round(sum(1 for r in g if r["agree"]) / len(g), 4),
            "population_weight": design[t]["weight"],
        }

    ps = sum(design[t]["weight"] * per_type[t]["human_relevant_rate"] for t in per_type)
    wsum = sum(design[t]["weight"] for t in per_type)
    ps = ps / wsum if wsum else 0.0

    pairs = [(r["human"], r["model"]) for r in rows]
    binary = [(("relevant" if a == "relevant" else "other"),
               ("relevant" if b == "relevant" else "other")) for a, b in pairs]

    report = {
        "what_this_is": (
            "The author's blind relevance grading of 40 claims the URL-FIRST arm displayed, "
            "scored against the model labels on the same items. This is the calibration the "
            "paper had for the shipped arm and not for this one."
        ),
        "arm": kb["arm"],
        "provenance": {
            "sheet": str(SHEET.relative_to(REPO)).replace("\\", "/"),
            "blank_sheet_sha256": kb["blank_sheet_sha256"],
            "filled_sheet_sha256": source_sha256(SHEET),
            "codebook": kb["codebook"],
            "graded_by": "the author, with model labels hidden on the sheet",
            "design": design,
            "matched_labels": str(MATCHED.relative_to(REPO)).replace("\\", "/"),
            "matched_labels_sha256": source_sha256(MATCHED),
            "interval_method": (
                "No population interval quoted: this is a small question-type-stratified "
                "calibration sample with zero human-relevant observations. Matched model "
                "labels include two relevant items, both human partial."
            ),
        },
        "agreement_label_version": "original",
        "agreement": agreement_stats(rows),
        "matched_agreement": agreement_stats(matched_rows),
        "matched_disagreements": [r for r in matched_rows if not r["agree"]],
        "matched_per_item": matched_rows,
        "human_relevant_rate": {
            "naive_on_the_sheet": round(sum(1 for r in rows if r["human"] == "relevant") / len(rows), 4),
            "post_stratified_to_the_364": round(ps, 4),
            "no_interval_quoted": (
                "See interval_method. A descriptive calibration estimate, not population "
                "inference."
            ),
            "model_rate_on_the_364": model_report["headline"]["relevant_rate_ci"],
        },
        "comparison_with_the_shipped_arm": (
            "Calibration is sparse and arm-dependent. Report the label version explicitly; "
            "human agreement alone does not establish accuracy of the rare relevant class "
            "or equivalence between designs."
        ),
        "disagreements": [
            {"item": r["item_id"], "type": r["question_type"], "human": r["human"], "model": r["model"]}
            for r in rows if not r["agree"]
        ],
        "by_question_type": per_type,
        "per_item": rows,
    }

    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("report reproduces exactly" if same else "REPORT DIFFERS from a fresh run")
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8")

    a, h = report["agreement"], report["human_relevant_rate"]
    print(f"wrote {OUT.relative_to(REPO)}")
    print(f"  items {a['items']} | exact agreement {a['exact_three_way']} | kappa {a['cohens_kappa']}")
    print(f"  relevant-vs-other agreement {a['relevant_vs_other']} | kappa {a['relevant_vs_other_kappa']}")
    print(f"  matched agreement: {report['matched_agreement']}")
    print(f"  human {a['human_distribution']}")
    print(f"  model {a['model_distribution_on_these_40']}")
    print(f"  human relevant: naive {h['naive_on_the_sheet']} | post-stratified "
          f"{h['post_stratified_to_the_364']} (no interval)")
    print(f"  model on all 364: {h['model_rate_on_the_364']}")
    for d in report["disagreements"]:
        print(f"    {d['item']} [{d['type']:22}] human {d['human']:<13} model {d['model']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
