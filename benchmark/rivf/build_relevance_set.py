"""Freeze the HUMAN relevance judgement set: 40 displayed claims, 8 per question type.

Why this exists
---------------
The entailment measurement judged (claim, cited passage) and found 0.968 supported. It was
designed to see exactly that and nothing else, and an independent review showed what it
cannot see: item ent_0001 (rivf_031) asks about neonatal bilirubin neurotoxicity and the
displayed claim is about MRI findings in pesticide poisoning. The passage supports the
claim; the claim has nothing to do with the question. Both judges were right and the
system was wrong, and no number in the paper recorded it.

So the missing measurement is (claim, QUESTION): is the claim the reader was shown relevant
to what they asked? That is a judgement a person can make quickly and a model cannot be
trusted to make alone for this paper, whose own standard says model judgements are not
human validation. The author grades these 40; a model pass over all 185 is reported
separately, with this sheet as its human check.

Design
------
* Population: the 185 real items of entailment_items_v1.jsonl (every claim the shipped
  system displayed on the frozen probe set). Controls are excluded: relevance of a claim to
  a question it was never generated for is not the quantity.
* Stratified: 8 items from each of the 5 question types, drawn with a fixed seed. Types are
  read from the probe set's grid label, not guessed from the text.
* Blind to the system's verdicts and to the entailment labels. The grader sees the question,
  the claim, and the cited passage (so "relevant but unsupported" can be told from
  "supported but irrelevant").
* Frozen before grading: items hashed, key committed, same discipline as the probe set.

Run:  python benchmark/rivf/build_relevance_set.py
Out:  benchmark/rivf/relevance_items_v1.jsonl   (blind, what the grader sees)
      benchmark/rivf/relevance_sheet_v1.md      (the sheet to fill in, Vietnamese)
      benchmark/rivf/relevance_key_v1.json      (item -> entailment item, query, type)
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ITEMS = REPO / "benchmark/rivf/entailment_items_v1.jsonl"
KEY_IN = REPO / "benchmark/rivf/entailment_key_v1.json"
PROBE = REPO / "benchmark/datasets/probe_queries_v2.jsonl"

OUT_ITEMS = REPO / "benchmark/rivf/relevance_items_v1.jsonl"
OUT_SHEET = REPO / "benchmark/rivf/relevance_sheet_v1.md"
OUT_KEY = REPO / "benchmark/rivf/relevance_key_v1.json"

SEED = 20260906
PER_TYPE = 8

CODEBOOK_VI = """# Phiếu chấm liên quan (relevance) — 40 claim, 8 mỗi loại câu hỏi

**Bạn đang chấm gì.** Hệ thống hiển thị một *claim* kèm trích dẫn cho một *câu hỏi*. Phép đo
entailment đã kiểm rằng đoạn văn được trích **có đỡ** claim (96,8%). Nó *không* kiểm claim có
liên quan gì tới câu hỏi không. Phiếu này đo đúng khoảng trống đó.

**Mỗi item, trả lời hai câu, điền vào hai cột cuối:**

| Cột | Nhãn | Nghĩa |
|---|---|---|
| **R** (relevance) | `R` | Claim trả lời trực tiếp câu hỏi, hoặc là một phần cần thiết của câu trả lời. |
| | `P` | Claim liên quan tới chủ đề nhưng không trả lời câu hỏi (cùng bệnh nhưng khác khía cạnh; bối cảnh; định nghĩa chung). |
| | `N` | Claim không liên quan tới câu hỏi (khác bệnh, khác đối tượng, khác chủ đề). |
| **S** (support, tuỳ chọn) | `Y` / `N` | Đoạn văn được trích có thật sự nói điều claim nói không. Chỉ điền khi bạn thấy chắc; để trống nếu không kiểm. |

**Quy tắc.**
1. Chấm **claim so với câu hỏi**, không phải đoạn văn so với câu hỏi. Đoạn văn chỉ để bạn hiểu claim nói về gì.
2. Không dùng kiến thức ngoài để "cứu" một claim: nếu claim đúng về y khoa nhưng không trả lời câu hỏi này, đó là `P` hoặc `N`.
3. Câu hỏi và claim đều tiếng Việt; một số đoạn văn có tóm tắt song ngữ.
4. Đừng xem file `relevance_key_v1.json` trước khi chấm xong — nó ghi item nào thuộc câu hỏi/loại nào.
5. Điền thẳng vào bảng dưới, rồi báo tôi. Không cần ghi lý do, nhưng nếu một ca khó thì một câu ghi chú ở cột cuối rất hữu ích.

Thời gian ước tính: 40 item × ~1 phút.

---
"""


def main() -> int:
    key = json.loads(KEY_IN.read_text(encoding="utf-8"))["key"]
    items = {json.loads(l)["item_id"]: json.loads(l) for l in ITEMS.open(encoding="utf-8")}
    qtype = {}
    for line in PROBE.open(encoding="utf-8"):
        r = json.loads(line)
        qtype[r["query_id"]] = (r.get("source") or "").split("/")[-1] or "unknown"

    by_type = defaultdict(list)
    for item_id, meta in key.items():
        if meta["kind"] != "real":
            continue
        by_type[qtype.get(meta["query_id"], "unknown")].append(item_id)

    rng = random.Random(SEED)
    chosen = []
    for t in sorted(by_type):
        pool = sorted(by_type[t])
        take = rng.sample(pool, min(PER_TYPE, len(pool)))
        chosen.extend((t, iid) for iid in take)
    rng.shuffle(chosen)

    blind, out_key, sheet_rows = [], {}, []
    for n, (t, iid) in enumerate(chosen, start=1):
        it = items[iid]
        rid = f"rel_{n:02d}"
        out_key[rid] = {"entailment_item": iid, "query_id": key[iid]["query_id"], "question_type": t}
        blind.append(
            {
                "item_id": rid,
                "question": it["question"],
                "claim": it["claim"],
                "cited_passage": it["cited_passage"],
            }
        )
        passage = " ".join(it["cited_passage"].split())
        if len(passage) > 700:
            passage = passage[:700] + " […]"
        sheet_rows.append(
            f"### {rid}\n\n"
            f"**Câu hỏi:** {it['question'].strip()}\n\n"
            f"**Claim hệ thống hiển thị:** {it['claim'].strip()}\n\n"
            f"<details><summary>Đoạn văn được trích (bấm để mở)</summary>\n\n{passage}\n\n</details>\n\n"
            f"| R (R/P/N) | S (Y/N, tuỳ chọn) | Ghi chú |\n|---|---|---|\n|  |  |  |\n"
        )

    with OUT_ITEMS.open("w", encoding="utf-8", newline="\n") as fh:
        for b in blind:
            fh.write(json.dumps(b, ensure_ascii=False, sort_keys=True) + "\n")
    digest = hashlib.sha256(OUT_ITEMS.read_bytes()).hexdigest()

    OUT_SHEET.write_text(CODEBOOK_VI + "\n".join(sheet_rows), encoding="utf-8", newline="\n")
    OUT_KEY.write_text(
        json.dumps(
            {
                "what_this_is": "Which relevance item maps to which entailment item, query and question type. Not for the grader until grading is done.",
                "items_file": str(OUT_ITEMS.relative_to(REPO)).replace("\\", "/"),
                "items_sha256": digest,
                "seed": SEED,
                "per_type": PER_TYPE,
                "counts_by_type": {t: sum(1 for x in chosen if x[0] == t) for t in sorted(by_type)},
                "key": out_key,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(blind)} items; sha256 {digest}")
    for t in sorted(by_type):
        print(f"  {t:24} pool {len(by_type[t]):3}  drawn {sum(1 for x in chosen if x[0] == t)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
