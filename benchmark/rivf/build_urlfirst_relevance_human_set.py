"""Freeze a 40-item human relevance sheet for the URL-FIRST arm.

WHY. Both external reviews made the same point and the paper concedes it: the URL-first arm's
support and responsiveness rates are model judgements with no human calibration at all, while
the shipped arm has some. Comparing a calibrated rate against an uncalibrated one and saying
"no evidence of a difference" is weaker than it looks, because one side's instrument has been
checked against a person and the other's has not.

This sheet closes that asymmetry for relevance, which is the rate the paper leans on hardest
(0.028 against 0.022) and the one where the shipped-arm sheet found the author disagreeing with
the model on six of forty items.

DESIGN, deliberately identical to the shipped arm's sheet so the two are comparable:
  * 8 items per question type, 5 types, drawn from the 364 displayed claims;
  * population weights recorded in the key so the scorer post-stratifies rather than reading
    40 items as one urn;
  * blind -- the sheet carries the question and the claim and nothing else. No model label, no
    entailment verdict, no arm, no confidence.

WHAT IT WILL AND WILL NOT SUPPORT. The shipped-arm sheet had two positive cases in forty and
therefore could not estimate a rate; this one will almost certainly be the same, since the
model found 10 relevant in 364. It calibrates the judge. It does not estimate a rate, and the
scorer says so rather than quoting an interval.

    python benchmark/rivf/build_urlfirst_relevance_human_set.py
    python benchmark/rivf/build_urlfirst_relevance_human_set.py --force
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ITEMS = REPO / "benchmark/rivf/relevance_model_items_urlfirst_v1.jsonl"
REPORT = REPO / "benchmark/rivf/relevance_report_urlfirst_v1.json"
OUT_TXT = REPO / "benchmark/rivf/relevance_human_labels_urlfirst_v1.txt"
OUT_KEY = REPO / "benchmark/rivf/relevance_human_key_urlfirst_v1.json"

SEED = 20260910
PER_TYPE = 8


def filled_slots(path: Path) -> list[str]:
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"(?m)^## (relu_\d{2})\s*$", raw)
    return [blocks[i] for i in range(1, len(blocks), 2)
            if (m := re.search(r"(?m)^=>\s*(.*)$", blocks[i + 1])) and m.group(1).strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="overwrite a sheet that already carries labels; refused otherwise")
    args = ap.parse_args()

    already = filled_slots(OUT_TXT)
    if already and not args.force:
        raise SystemExit(
            f"REFUSING to overwrite {OUT_TXT.relative_to(REPO)}: {len(already)} slots are "
            f"already graded. Hand-entered labels are not regenerable.\n"
            f"  to score them:  python benchmark/rivf/score_urlfirst_relevance.py")

    items = {json.loads(l)["item_id"]: json.loads(l) for l in ITEMS.open(encoding="utf-8")}
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    real = [r for r in report["per_item"] if r["kind"] == "real"]

    by_type: defaultdict[str, list] = defaultdict(list)
    for r in real:
        by_type[r["question_type"]].append(r)
    for v in by_type.values():
        v.sort(key=lambda r: r["item_id"])

    population = {t: len(v) for t, v in by_type.items()}
    total = sum(population.values())

    rng = random.Random(SEED)
    picked = []
    for t in sorted(by_type):
        pool = by_type[t]
        picked.extend(rng.sample(pool, min(PER_TYPE, len(pool))))
    rng.shuffle(picked)

    lines = [
        "PHIẾU CHẤM RELEVANCE — 40 mục\n"
        "=============================\n\n"
        "Codebook: benchmark/rivf/RELEVANCE-CODEBOOK.md (giống hệt phiếu trước)\n\n"
        "Câu hỏi: CLAIM này có trả lời CÂU HỎI không?\n"
        "   R = relevant     — trả lời câu hỏi, hoặc là một phần cần thiết của câu trả lời\n"
        "   P = partial      — đúng chủ đề nhưng KHÔNG trả lời (mục tiêu nghiên cứu, cỡ mẫu,\n"
        "                      định nghĩa sách giáo khoa, mô tả quần thể…)\n"
        "   N = not_relevant — không liên quan\n\n"
        "Tuỳ chọn thứ hai: đoạn văn được trích có ĐỠ claim không —  Y / N  (bỏ trống nếu\n"
        "không muốn chấm; phần này không vào tỷ lệ headline).\n\n"
        "Điền vào dòng '=>' dạng:  R    /   P Y   /   N\n\n"
        "QUY TẮC SỐ 1: chấm CLAIM so với CÂU HỎI, không phải đoạn văn so với câu hỏi.\n"
        "Đoạn văn chỉ để bạn hiểu claim đang nói về cái gì. Nguyên văn từ phiếu trước,\n"
        "đặt lại ở đây để hai phiếu được chấm trong cùng một điều kiện.\n\n"
        "PHIẾU NÀY MÙ: không có nhãn của mô hình, không có phán quyết entailment, không có\n"
        "thông tin về thiết kế nào đã sinh ra các mục này. Đó là chủ ý.\n\n" + "=" * 78 + "\n\n"
    ]
    key = {}
    for i, r in enumerate(picked, 1):
        rid = f"relu_{i:02d}"
        it = items[r["item_id"]]
        key[rid] = {
            "relevance_item": r["item_id"],
            "query_id": r["query_id"],
            "question_type": r["question_type"],
            "model_label": r["label"],
            "entailment_label": r.get("entailment_label"),
        }
        lines.append(
            f"## {rid}\n"
            f"CÂU HỎI: {it['question']}\n\n"
            f"CLAIM: {it['claim']}\n\n"
            f"ĐOẠN VĂN ĐƯỢC TRÍCH:\n{it['cited_passage']}\n\n"
            f"=> \n\n"
        )

    OUT_TXT.write_text("".join(lines), encoding="utf-8", newline="\r\n")
    digest = hashlib.sha256(OUT_TXT.read_bytes()).hexdigest()

    counts = Counter(r["question_type"] for r in picked)
    design = {t: {"population": population[t],
                  "weight": round(population[t] / total, 4),
                  "sampled": counts.get(t, 0)} for t in sorted(population)}

    OUT_KEY.write_text(json.dumps({
        "what_this_is": (
            "Key for the URL-first arm's 40-item human relevance sheet. NOT for the grader: it "
            "carries the model's label, which is what the sheet exists to check."
        ),
        "arm": "URL-first (uncitable records excluded at retrieval)",
        "codebook": "benchmark/rivf/RELEVANCE-CODEBOOK.md",
        "sheet": str(OUT_TXT.relative_to(REPO)).replace("\\", "/"),
        "blank_sheet_sha256": digest,
        "what_that_hash_is": (
            "the sheet AS ISSUED, before any label. The scorer records filled_sheet_sha256."
        ),
        "seed": SEED,
        "per_type": PER_TYPE,
        "design": design,
        "population_total": total,
        "why_post_stratify": (
            "8 per type against a population of "
            + ", ".join(f"{t} {n}" for t, n in sorted(population.items()))
            + " -- reading 40 items as one urn would weight the small types far too heavily."
        ),
        "what_it_will_not_support": (
            "A rate. The model found 10 relevant in 364, so this sheet will hold very few "
            "positive cases and no interval from it will be informative -- the same situation "
            "as the shipped arm's sheet, which had two. It calibrates the judge."
        ),
        "key": key,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"wrote {OUT_TXT.relative_to(REPO)}  ({OUT_TXT.stat().st_size:,} bytes, {len(picked)} slots)")
    print(f"wrote {OUT_KEY.relative_to(REPO)}")
    print(f"  blank sheet sha256 {digest[:32]}...")
    for t, d in design.items():
        print(f"    {t:24} population {d['population']:>3}  weight {d['weight']:.3f}  sampled {d['sampled']}")
    print(f"  model labels on these 40: {dict(Counter(k['model_label'] for k in key.values()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
