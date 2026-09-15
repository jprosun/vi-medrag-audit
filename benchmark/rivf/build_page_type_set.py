"""Freeze the 40-item page-type sheet: what kind of page a stored URL actually reaches.

WHY. The audit's destination test is a regex on the final URL. It cannot see a homepage, a
search page, or a soft 404 served with status 200 -- all three pass as "not an issue index".
That is one of the three reasons the corpus-level composite was withdrawn. This sheet gets a
person to look at the pages so the rule's error rate can be measured instead of assumed.

DESIGN. Items are drawn from every probe that answered 2xx, across BOTH logs -- the
exploratory pass and the confirmatory PPS sample -- stratified by the audit's own
classification of the final URL:

    issue            the regex says: an issue index          (it should be right; this is the
                                                              stratum that anchors the sheet)
    article          the regex says: an article page
    article_or_page  THE CATCH-ALL -- everything the regex did not recognise

The catch-all is deliberately OVER-SAMPLED, because that is where the doubt lives and where a
soft 404 would hide. Weights are recorded in the key so the scorer post-stratifies rather than
reading 40 items as one urn.

BLINDING. The sheet carries the URL, the HTTP status and the title the server returned. It
does NOT carry the audit's classification, the URL's stored granularity, the chunk count, or
whether the stored title was flagged unusable. Those are what the sheet exists to check.

The grader is told to OPEN each URL. That is the point: the whole exercise is that
machine-visible signals were not enough.

    python benchmark/rivf/build_page_type_set.py
    python benchmark/rivf/build_page_type_set.py --force   # only after saving any labels
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

POP = REPO / "benchmark/rivf/url_population_v4.json"
LOGS = [
    ("exploratory", REPO / "benchmark/rivf/url_audit_probed_v1.jsonl"),
    ("confirmatory", REPO / "benchmark/rivf/url_confirmatory_probed_v1.jsonl"),
]
OUT_TXT = REPO / "benchmark/rivf/page_type_labels_v1.txt"
OUT_KEY = REPO / "benchmark/rivf/page_type_key_v1.json"

SEED = 20260908
N_TOTAL = 40
# The catch-all gets half the sheet regardless of its share: it is the stratum the regex
# cannot see into, so it is the stratum worth spending items on.
ALLOC = {"article_or_page": 20, "issue": 10, "article": 10}

_ISSUE_RE = re.compile(r"/issue/(view|archive)/", re.IGNORECASE)
_ARTICLE_RE = re.compile(r"/article/(view|download)/|/pmc/|/books/|doi\.org/", re.IGNORECASE)


def granularity(u: str) -> str:
    if not (u or "").strip():
        return "none"
    if _ISSUE_RE.search(u):
        return "issue"
    if _ARTICLE_RE.search(u):
        return "article"
    return "article_or_page"


def filled_slots(path: Path) -> list[str]:
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"(?m)^## (pt_\d{2})\s*$", raw)
    out = []
    for i in range(1, len(blocks), 2):
        m = re.search(r"(?m)^=>\s*(.*)$", blocks[i + 1])
        if m and m.group(1).strip():
            out.append(blocks[i])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="overwrite a sheet that already carries labels. Refused otherwise: "
                         "hand-entered labels are not regenerable from anything here.")
    args = ap.parse_args()

    already = filled_slots(OUT_TXT)
    if already and not args.force:
        raise SystemExit(
            f"REFUSING to overwrite {OUT_TXT.relative_to(REPO)}: {len(already)} slots already "
            f"graded ({', '.join(already[:4])}...). Those labels were entered by hand and "
            f"cannot be rebuilt.\n"
            f"  to score them:  python benchmark/rivf/score_page_type.py\n"
            f"  to start over, having saved them elsewhere:  --force"
        )

    pop = {u["url"]: u for u in json.loads(POP.read_text(encoding="utf-8"))["urls"]}

    pool: dict[str, dict] = {}
    per_log = Counter()
    for label, path in LOGS:
        if not path.exists():
            print(f"  note: {path.name} absent, skipping")
            continue
        for line in path.open(encoding="utf-8"):
            if not line.strip():
                continue
            rec = json.loads(line)
            st = rec.get("status")
            if rec.get("outcome") != "ok" or not (isinstance(st, int) and 200 <= st < 300):
                continue
            if rec["url"] in pool:
                continue
            pool[rec["url"]] = {"rec": rec, "log": label}
            per_log[label] += 1

    strata: defaultdict[str, list] = defaultdict(list)
    for url, e in pool.items():
        strata[granularity(e["rec"].get("final_url") or url)].append(url)
    for v in strata.values():
        v.sort()

    rng = random.Random(SEED)
    picked = []
    for stratum, want in ALLOC.items():
        avail = strata.get(stratum, [])
        take = min(want, len(avail))
        picked.extend((stratum, u) for u in rng.sample(avail, take))
        if take < want:
            print(f"  note: {stratum} had only {len(avail)}, wanted {want}")
    # If a stratum ran short, top the sheet back up to 40 from the catch-all.
    if len(picked) < N_TOTAL:
        chosen = {u for _, u in picked}
        spare = [u for u in strata.get("article_or_page", []) if u not in chosen]
        extra = rng.sample(spare, min(N_TOTAL - len(picked), len(spare)))
        picked.extend(("article_or_page", u) for u in extra)
    rng.shuffle(picked)

    lines, key = [], {}
    lines.append(
        "PHIẾU GÁN NHÃN LOẠI TRANG — 40 mục\n"
        "==================================\n\n"
        "Đọc codebook trước: benchmark/rivf/PAGE-TYPE-CODEBOOK.md\n\n"
        "MỞ TỪNG URL. Tiêu đề bên dưới là tiêu đề máy chủ trả về lúc probe (2026-09), có thể\n"
        "đã khác bây giờ — nếu trang rõ ràng đã đổi, dùng M.\n\n"
        "Câu 1 — trang thuộc loại gì:\n"
        "   D = trang một tài liệu cụ thể      I = mục lục / danh sách nhiều tài liệu\n"
        "   H = trang chủ hoặc trang mục lớn   S = trang tìm kiếm / duyệt\n"
        "   E = báo lỗi nhưng trả 200 (soft 404)   M = đã đổi, không phán được\n"
        "   O = khác (ghi một dòng)\n\n"
        "Câu 2 — có đúng là tài liệu được trích không (chỉ có nghĩa khi Câu 1 = D):\n"
        "   Y = đúng tài liệu   N = tài liệu KHÁC\n"
        "   ? = KHÔNG BIẾT vì tiêu đề lưu trong corpus là rác (breadcrumb, mảnh tên file,\n"
        "       nhãn điều hướng, mất dấu) — đây là lỗi corpus, KHÔNG được chấm là N\n"
        "   - = Câu 1 không phải D\n\n"
        "Điền vào dòng '=>' theo dạng:  <Câu1> <Câu2>      ví dụ:  D Y   /   I -   /   E -\n\n"
        + "=" * 78 + "\n\n"
    )

    for i, (stratum, url) in enumerate(picked, 1):
        pid = f"pt_{i:02d}"
        e = pool[url]
        rec = e["rec"]
        meta = pop.get(url, {})
        stored = (meta.get("titles") or [""])[0]
        key[pid] = {
            "url": url,
            "final_url": rec.get("final_url"),
            "audit_stratum": stratum,
            "stored_granularity": meta.get("granularity"),
            "chunks": meta.get("chunks"),
            "source_id": meta.get("source_id"),
            "host": urlparse(url).netloc,
            "from_log": e["log"],
            "stored_title": stored,
            "page_title_at_probe": rec.get("page_title"),
            "status": rec.get("status"),
            "redirects": len(rec.get("redirects") or []),
        }
        redir = ""
        if rec.get("final_url") and rec["final_url"] != url:
            redir = f"CHUYỂN HƯỚNG TỚI: {rec['final_url']}\n"
        lines.append(
            f"## {pid}\n"
            f"URL: {url}\n"
            f"{redir}"
            f"HTTP: {rec.get('status')}\n"
            f"TIÊU ĐỀ MÁY CHỦ TRẢ VỀ LÚC PROBE: {rec.get('page_title') or '(trống)'}\n"
            f"TIÊU ĐỀ CORPUS LƯU CHO BẢN GHI NÀY: {stored or '(trống)'}\n"
            f"=> \n\n"
        )

    OUT_TXT.write_text("".join(lines), encoding="utf-8", newline="\r\n")
    digest = hashlib.sha256(OUT_TXT.read_bytes()).hexdigest()

    counts = Counter(s for s, _ in picked)
    design = {}
    for stratum in ALLOC:
        design[stratum] = {
            "population_of_2xx_probes": len(strata.get(stratum, [])),
            "sampled": counts.get(stratum, 0),
            "weight": round(len(strata.get(stratum, [])) / max(len(pool), 1), 4),
        }

    OUT_KEY.write_text(
        json.dumps(
            {
                "what_this_is": (
                    "Key for the 40-item page-type sheet. NOT for the grader: it carries the "
                    "audit's own classification, which is the thing the sheet checks."
                ),
                "codebook": "benchmark/rivf/PAGE-TYPE-CODEBOOK.md",
                "codebook_committed_before_items_existed": "a1f1126",
                "sheet": str(OUT_TXT.relative_to(REPO)).replace("\\", "/"),
                "blank_sheet_sha256": digest,
                "what_that_hash_is": (
                    "the sheet AS ISSUED, before any label. It proves the items were frozen "
                    "before grading. The scorer records filled_sheet_sha256 separately."
                ),
                "seed": SEED,
                "allocation": ALLOC,
                "design": design,
                "why_the_catch_all_is_over_sampled": (
                    "article_or_page is everything granularity() failed to recognise, so it is "
                    "where a homepage, a search page or a soft 404 would be hiding. Half the "
                    "sheet goes there on purpose; the key's weights let the scorer "
                    "post-stratify back to the 2xx population."
                ),
                "probes_available": dict(per_log),
                "total_2xx_pool": len(pool),
                "key": key,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"wrote {OUT_TXT.relative_to(REPO)}  ({OUT_TXT.stat().st_size:,} bytes, {len(picked)} slots)")
    print(f"wrote {OUT_KEY.relative_to(REPO)}")
    print(f"  blank sheet sha256 {digest[:32]}...")
    print(f"  2xx pool {len(pool)} from {dict(per_log)}")
    for stratum, d in design.items():
        print(f"    {stratum:16} population {d['population_of_2xx_probes']:>4} "
              f"weight {d['weight']:.3f} -> sampled {d['sampled']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
