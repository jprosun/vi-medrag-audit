"""Freeze the 30-item HUMAN entailment sheet, stratified by the model's own label.

WHY NOT A SIMPLE RANDOM 30
The model labelled 179 of 185 claims `supported`. A proportional sample of 30 would contain
about one failure, so it could neither confirm the six failures nor estimate the precision of
the `supported` label -- and those are the only two things that can move 0.968. It would
also be nearly blind to `overstated`, the failure mode this paper predicted and the model
never once fired on.

THE DESIGN, therefore, is two declared strata:

  A. CENSUS of all 6 items the model did not call `supported` (1 not_supported,
     5 unintelligible). Not a sample: if the author confirms them the failures are real, and
     if the author overturns them the supported rate rises.
  B. SAMPLE of 24 of the 179 `supported`, drawn with a fixed seed and allocated across the
     five question types in proportion to where those claims are. This estimates the
     PRECISION of the model's `supported` label, which is the quantity that decides whether
     0.968 is too high, and it is the only stratum where the author can discover an
     `overstated` claim the model missed.

The estimate is post-stratified: 179/185 times the precision measured in B, plus 6/185 times
whatever share of A the author calls supported. Both weights are printed in the sheet, so
the reader can see that a stratified sheet must not be read as 30 draws from one urn.

The grader sees the question, the claim, the offered span and the FULL cited passage, and
never the model's label. Unlike the relevance sheet the passage is mandatory here: it is what
the judgement is about.

Run:  python benchmark/rivf/build_entailment_human_set.py
Out:  benchmark/rivf/entailment_human_labels_v1.txt   (fill this in)
      benchmark/rivf/entailment_human_key_v1.json     (strata and weights; not for the grader)
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
ITEMS = REPO / "benchmark/rivf/entailment_items_v1.jsonl"
KEY = REPO / "benchmark/rivf/entailment_key_v1.json"
REPORT = REPO / "benchmark/rivf/entailment_report_v1.json"
PROBE = REPO / "benchmark/datasets/probe_queries_v2.jsonl"
OUT_TXT = REPO / "benchmark/rivf/entailment_human_labels_v1.txt"
OUT_KEY = REPO / "benchmark/rivf/entailment_human_key_v1.json"

SEED = 20260907
N_SUPPORTED = 24

HEAD = """# PHIẾU CHẤM ENTAILMENT — 30 item, điền một chữ sau mỗi dấu "=>"
#
# CÂU HỎI BẠN ĐANG TRẢ LỜI: ĐOẠN VĂN ĐƯỢC TRÍCH có đỡ cho claim không.
# KHÔNG phải "claim có trả lời câu hỏi không" — cái đó bạn đã chấm ở phiếu trước.
# Câu hỏi chỉ hiển thị để bạn hiểu ngữ cảnh; nó KHÔNG tham gia vào phán quyết.
#
#   S  supported      — đoạn văn nói đúng điều claim nói, hoặc claim là diễn giải trung
#                       thực / dịch / hệ quả trực tiếp của điều đoạn văn nói
#   O  overstated     — đoạn văn chỉ đỡ một phiên bản YẾU HƠN: claim mở rộng ra ngoài
#                       quần thể của đoạn văn, biến một dè dặt thành sự thật, bỏ mất một
#                       điều kiện (liều, đối tượng, mốc thời gian), hoặc biến liên quan
#                       thành nhân quả. Trích dẫn thật, nhưng claim to hơn nó.
#   N  not_supported  — đoạn văn không đỡ claim: có thể cùng chủ đề, cùng thực thể, cùng
#                       con số, mà vẫn không khẳng định điều gì xác lập được claim; hoặc
#                       nó nói ngược lại
#   U  unintelligible — đoạn văn hỏng tới mức không chấm được: hai cột trộn vào nhau, câu
#                       bị ghép, chữ bị cắt giữa từ tới mức mất nghĩa. CHỈ dùng khi sự hỏng
#                       thật sự ngăn việc phán quyết; đoạn bắt đầu từ giữa một chữ nhưng
#                       vẫn đọc được thì vẫn chấm được.
#
# BỐN QUY TẮC
#   1. Chỉ dùng chữ trong item. ĐỪNG dùng kiến thức y khoa ngoài để bù chỗ đoạn văn thiếu.
#      Câu hỏi là "ĐOẠN VĂN NÀY có đỡ claim không", không phải "claim có đúng không".
#   2. Claim đúng về y khoa nhưng đoạn văn không xác lập nó thì là N.
#   3. Con số phải khớp. Đoạn văn ghi 96,18% thì không đỡ claim "96%" trừ khi claim nói rõ
#      là xấp xỉ; dùng O nếu claim làm tròn hoặc tổng quát hoá, N nếu con số khác hẳn.
#   4. Vài đoạn có tóm tắt song ngữ — chấm được qua cả hai thứ tiếng: claim tiếng Việt được
#      nửa tiếng Anh của cùng tóm tắt đỡ thì vẫn là S.
#
# CHỖ Ý KIẾN CỦA BẠN CÓ GIÁ TRỊ NHẤT: nhãn **O**. Mô hình chưa từng gán O lần nào trên cả
# 185 claim, và đó chính là kiểu hỏng mà bài báo dự đoán ("claim nói quá đeo một trích dẫn
# có thật"). Nếu bạn thấy một O, nó là phát hiện.
#
# Không sửa dòng "## ent_h_NN". Xong thì bảo tôi; tôi đọc đúng file này.
"""


def filled_slots(path: Path) -> list[str]:
    """Item ids whose `=>` line already carries a label. Empty for a blank sheet."""
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"(?m)^## (ent_h_\d{2})\s*$", raw)
    out = []
    for i in range(1, len(blocks), 2):
        m = re.search(r"(?m)^=>\s*(.*)$", blocks[i + 1])
        if m and m.group(1).strip():
            out.append(blocks[i])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--force",
        action="store_true",
        help="overwrite a sheet that already carries labels. Without this the script refuses, "
        "because the labels are hand-entered and are not regenerable from anything.",
    )
    args = ap.parse_args()

    already = filled_slots(OUT_TXT)
    if already and not args.force:
        raise SystemExit(
            f"REFUSING to overwrite {OUT_TXT.relative_to(REPO)}: {len(already)} of its slots are "
            f"already graded ({', '.join(already[:4])}...). Those labels were entered by hand and "
            f"cannot be rebuilt from any artifact in this repository -- rebuilding the sheet would "
            f"destroy the measurement, not reproduce it.\n"
            f"  to re-score the existing labels:  python benchmark/rivf/score_human_entailment.py\n"
            f"  to verify the sheet is the one that was issued:  compare its sha256 against\n"
            f"    entailment_human_key_v1.json -> blank_sheet_sha256\n"
            f"  to genuinely start over, having saved the labels elsewhere:  --force"
        )

    items = {json.loads(l)["item_id"]: json.loads(l) for l in ITEMS.open(encoding="utf-8")}
    key = json.loads(KEY.read_text(encoding="utf-8"))["key"]
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    model = {r["item_id"]: r for r in report["per_item"] if r["kind"] == "real"}
    qtype = {}
    for line in PROBE.open(encoding="utf-8"):
        row = json.loads(line)
        qtype[row["query_id"]] = (row.get("source") or "").split("/")[-1] or "unknown"

    failures = sorted(i for i, r in model.items() if r["label"] != "supported")
    supported = sorted(i for i, r in model.items() if r["label"] == "supported")
    assert len(failures) == 6 and len(supported) == 179, (len(failures), len(supported))

    # allocate the 24 across question types in proportion to the supported population
    by_type = defaultdict(list)
    for i in supported:
        by_type[qtype[key[i]["query_id"]]].append(i)
    pop = {t: len(v) for t, v in by_type.items()}
    total = sum(pop.values())
    quota = {t: N_SUPPORTED * n / total for t, n in pop.items()}
    alloc = {t: int(q) for t, q in quota.items()}
    # hand out the remainder to the largest fractional parts, deterministically
    for t in sorted(quota, key=lambda x: (-(quota[x] - alloc[x]), x))[: N_SUPPORTED - sum(alloc.values())]:
        alloc[t] += 1
    assert sum(alloc.values()) == N_SUPPORTED, alloc

    rng = random.Random(SEED)
    drawn = []
    for t in sorted(by_type):
        drawn += rng.sample(sorted(by_type[t]), alloc[t])

    chosen = [("A_model_failure", i) for i in failures] + [("B_model_supported", i) for i in drawn]
    rng.shuffle(chosen)

    lines, out_key = [HEAD], {}
    for n, (stratum, iid) in enumerate(chosen, start=1):
        hid = f"ent_h_{n:02d}"
        it = items[iid]
        out_key[hid] = {
            "entailment_item": iid,
            "stratum": stratum,
            "query_id": key[iid]["query_id"],
            "question_type": qtype[key[iid]["query_id"]],
            "model_label": model[iid]["label"],
            "span_equals_claim": key[iid]["span_equals_claim"],
        }
        q = " ".join(it["question"].split())
        c = " ".join(it["claim"].split())
        s = " ".join(it["supporting_span"].split())
        passage = "\n".join("   " + ln for ln in it["cited_passage"].splitlines())
        span_line = "" if s == c else f"SPAN hệ thống trỏ tới: {s}\n"
        lines.append(
            f"\n## {hid}\n"
            f"Câu hỏi (chỉ để hiểu ngữ cảnh): {q}\n"
            f"CLAIM: {c}\n"
            f"{span_line}"
            f"ĐOẠN VĂN ĐƯỢC TRÍCH:\n{passage}\n"
            f"=> \n"
        )
    OUT_TXT.write_text("".join(lines), encoding="utf-8", newline="\r\n")

    digest = hashlib.sha256(OUT_TXT.read_bytes()).hexdigest()
    OUT_KEY.write_text(
        json.dumps(
            {
                "what_this_is": (
                    "Strata, weights and the model's label for each item of the 30-item human "
                    "entailment sheet. The grader must not read this file before grading."
                ),
                "sheet": str(OUT_TXT.relative_to(REPO)).replace("\\", "/"),
                "blank_sheet_sha256": digest,
                "what_that_hash_is": (
                    "the sheet AS ISSUED, before any label was entered. It proves the items were "
                    "frozen before grading. It does NOT identify the grading: the scorer records "
                    "filled_sheet_sha256 for that."
                ),
                "seed": SEED,
                "design": {
                    "A_model_failure": {
                        "kind": "census",
                        "items": len(failures),
                        "population": len(failures),
                        "weight": round(len(failures) / len(model), 6),
                        "why": "all 6 of them; a sample could not confirm or overturn six events",
                    },
                    "B_model_supported": {
                        "kind": "sample, allocated across question type in proportion to the population",
                        "items": N_SUPPORTED,
                        "population": len(supported),
                        "weight": round(len(supported) / len(model), 6),
                        "allocation": alloc,
                        "population_by_type": pop,
                        "why": "estimates the precision of the model's `supported` label, and is "
                               "the only stratum where an `overstated` claim can be discovered",
                    },
                },
                "post_stratified_estimator": (
                    "supported_rate = (179/185) * (share of stratum B the author calls supported) "
                    "+ (6/185) * (share of stratum A the author calls supported)"
                ),
                "key": out_key,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"wrote {OUT_TXT.relative_to(REPO)}  ({OUT_TXT.stat().st_size} bytes, 30 slots)")
    print(f"  sha256 {digest}")
    print(f"  stratum A, census of model failures : {len(failures)} items, weight {len(failures)/len(model):.4f}")
    print(f"  stratum B, sample of model supported: {N_SUPPORTED} of {len(supported)}, weight {len(supported)/len(model):.4f}")
    print(f"    allocation by question type: {alloc}")
    print(f"    population by question type : {pop}")
    print(f"  model labels in the sheet: {dict(Counter(v['model_label'] for v in out_key.values()))}")
    print(f"  items whose span differs from the claim: {sum(1 for v in out_key.values() if not v['span_equals_claim'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
