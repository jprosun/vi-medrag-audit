"""Build the population of distinct source URLs in the audited collection, for the
dereference audit.

WHY THIS EXISTS. Section IV of the paper counts how many chunks carry a `source_url` and at
what granularity, and is careful to say we read the stored field and never dereference it.
That care is necessary but it leaves the paper's central promise -- a citation a reader can
open -- measured only at the level of "a string is present". A stored locator that 404s, or
that redirects to a journal's front page, is exactly as useless to a reader as an empty
field, and the census cannot see the difference.

This script builds the sampling frame. `url_dereference_audit.py` samples from it and does
the probing, so that the expensive scroll happens once and the sample is reproducible from a
committed file.

The unit here is the DISTINCT URL, not the chunk. 595,663 chunks share far fewer URLs, and a
reader following a citation follows a URL: sampling chunks would over-weight whichever
articles happen to be split into many chunks, which is a property of the ingester, not of
the corpus's traceability.

    python benchmark/rivf/url_population.py
    python benchmark/rivf/url_population.py --check
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
QDRANT = "http://localhost:6333"
COLLECTION = "medqa_release_v4_all_bge_m3"
OUT = REPO / "benchmark/rivf/url_population_v4.json"

PAYLOAD_FIELDS = ["source_id", "source_name", "source_url", "title", "canonical_title", "article_id"]

# Identical to benchmark/rivf/corpus_census.py, deliberately: the audit must classify a URL
# the same way the census did, or the two tables cannot be read side by side.
_ISSUE_URL_RE = re.compile(r"/issue/(view|archive)/", re.IGNORECASE)
_ARTICLE_URL_RE = re.compile(r"/article/(view|download)/|/pmc/|/books/|doi\.org/", re.IGNORECASE)


def url_granularity(u: str | None) -> str:
    u = (u or "").strip()
    if not u:
        return "none"
    if _ISSUE_URL_RE.search(u):
        return "issue"
    if _ARTICLE_URL_RE.search(u):
        return "article"
    return "article_or_page"


def scroll():
    offset = None
    seen = 0
    while True:
        body = {"limit": 4096, "with_payload": PAYLOAD_FIELDS, "with_vector": False}
        if offset is not None:
            body["offset"] = offset
        req = urllib.request.Request(
            f"{QDRANT}/collections/{COLLECTION}/points/scroll",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            res = json.load(r)["result"]
        pts = res.get("points") or []
        if not pts:
            break
        for p in pts:
            yield p.get("payload") or {}
        seen += len(pts)
        if seen % 40960 == 0:
            print(f"  scrolled {seen:,}", flush=True)
        offset = res.get("next_page_offset")
        if offset is None:
            break


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    urls: dict[str, dict] = {}
    chunks_total = 0
    chunks_by_granularity: defaultdict[str, int] = defaultdict(int)

    for pay in scroll():
        chunks_total += 1
        u = (pay.get("source_url") or "").strip()
        g = url_granularity(u)
        chunks_by_granularity[g] += 1
        if not u:
            continue
        e = urls.get(u)
        if e is None:
            e = urls[u] = {
                "url": u,
                "granularity": g,
                "source_id": pay.get("source_id") or "unknown",
                "source_name": pay.get("source_name") or "",
                "chunks": 0,
                "article_ids": set(),
                "titles": set(),
            }
        e["chunks"] += 1
        if pay.get("article_id"):
            e["article_ids"].add(pay["article_id"])
        t = (pay.get("canonical_title") or pay.get("title") or "").strip()
        if t:
            e["titles"].add(t)

    rows = []
    for e in urls.values():
        rows.append(
            {
                "url": e["url"],
                "granularity": e["granularity"],
                "source_id": e["source_id"],
                "source_name": e["source_name"],
                "chunks": e["chunks"],
                "distinct_article_ids": len(e["article_ids"]),
                # One representative title, for the destination-accuracy check. Sorted so the
                # choice is deterministic rather than dict-order.
                "titles": sorted(e["titles"])[:3],
            }
        )
    rows.sort(key=lambda r: r["url"])

    by_g: defaultdict[str, int] = defaultdict(int)
    by_src: defaultdict[str, int] = defaultdict(int)
    for r in rows:
        by_g[r["granularity"]] += 1
        by_src[r["source_id"]] += 1

    out = {
        "what_this_is": (
            "Every distinct non-empty source_url in the audited collection, with the stratum "
            "and representative titles needed to check whether dereferencing it lands on the "
            "cited article. The sampling frame for url_dereference_audit.py."
        ),
        "provenance": {
            "collection": COLLECTION,
            "qdrant": QDRANT,
            "chunks_scrolled": chunks_total,
            "granularity_rule": "identical to corpus_census.py, so the two tables compose",
        },
        "chunks_by_granularity": dict(sorted(chunks_by_granularity.items())),
        "distinct_urls": len(rows),
        "distinct_urls_by_granularity": dict(sorted(by_g.items())),
        "distinct_urls_by_source": dict(sorted(by_src.items(), key=lambda kv: -kv[1])),
        "urls": rows,
    }

    text = json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("population reproduces exactly" if same else "POPULATION DIFFERS from a fresh scroll")
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}")
    print(f"  chunks scrolled {chunks_total:,}")
    print(f"  chunks by granularity {dict(sorted(chunks_by_granularity.items()))}")
    print(f"  distinct URLs {len(rows):,} -> {dict(sorted(by_g.items()))}")
    for s, n in sorted(by_src.items(), key=lambda kv: -kv[1])[:10]:
        print(f"    {n:>7,}  {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
