"""Exhaustive corpus census: what the index actually holds, per stratum, with a SHA.

WHY THIS EXISTS
===============
The paper's first table asserts how much of the corpus can support a citation a reader
can open. Every number behind it currently lives in one of three places, none of which is
an artifact: a README that is stale by a full deduplication (619,247 chunks / 128,674
articles), a project memory file (the 256,415 figure for the URL-less stratum), and a
percentage computed against the stale base (41.4%). A claim of the form "43% of this
corpus is structurally untraceable" cannot rest on that.

So this scrolls the live collection and counts, exhaustively, payload only. No embedding
is read, no LLM is called, nothing is written to the collection. It is the cheapest
number in the paper and the one a reviewer is most likely to check.

WHAT IT COUNTS, AND WHY EACH COLUMN
===================================
Per ``source_id`` (the stratum key the retriever and the tier policy both use):

* ``chunks`` / ``share`` -- the denominator every other rate in the paper divides by.
* ``source_url`` coverage, split three ways: an ARTICLE-level URL, an ISSUE-level URL
  (the journal platform's ``/issue/view/N``, which resolves to a table of contents rather
  than to the cited article), and NONE. The gate's own citability test is binary
  (non-empty URL), and reporting only that binary would overstate traceability for a
  stratum where a reader lands on an issue index and still cannot find the sentence.
* ``published_at`` / ``updated_at`` coverage -- the paper states that no audited stratum
  carries a publication date. That sentence needs a corpus-wide count, not a sample.
* ``trust_tier`` and ``doc_type`` distributions -- to show the URL-less stratum is a
  single coherent block (patient education at tier 3) rather than scattered damage.
* distinct ``article_id`` -- the only defensible article count. "128,674 articles" has no
  derivation anywhere in the repository and the deduplication record itself calls it
  inflated.

Run (stack up, read-only, ~2-5 minutes):

    python benchmark/rivf/corpus_census.py
    python benchmark/rivf/corpus_census.py --qdrant http://localhost:6333 --limit 20000

Writes ``benchmark/rivf/corpus_census_<collection>.json``. Exit 0 on success, 2 if the
collection cannot be read or the scrolled total disagrees with the collection count --
a census that silently stops short would understate every share it reports.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "benchmark" / "rivf"

# The fields the count is defined on. Fetching only these keeps the scroll small: the
# chunk text is by far the biggest part of a payload and nothing here reads it.
PAYLOAD_FIELDS = [
    "source_id", "source_name", "source_url", "published_at", "updated_at",
    "trust_tier", "doc_type", "language", "article_id", "institution",
]

# The journal platform serves /index.php/vmj/issue/view/311 for a whole issue and
# /article/view/NNN for one article. A citation that lands on the first is weaker than
# the citability gate's non-empty test implies, so the two are counted apart.
_ISSUE_URL_RE = re.compile(r"/issue/(view|archive)/", re.IGNORECASE)
_ARTICLE_URL_RE = re.compile(r"/article/(view|download)/|/pmc/|/books/|doi\.org/", re.IGNORECASE)


def url_granularity(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return "none"
    if _ISSUE_URL_RE.search(u):
        return "issue"
    if _ARTICLE_URL_RE.search(u):
        return "article"
    # A bare landing page (a fact sheet, a topic page) is article-level for a reader's
    # purposes: it is one document, not an index of them.
    return "article_or_page"


def git_head() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--qdrant", default="http://localhost:6333")
    ap.add_argument("--collection", default="medqa_release_v4_all_bge_m3")
    ap.add_argument("--limit", type=int, default=10000, help="scroll batch size")
    ap.add_argument("--timeout", type=float, default=120.0)
    args = ap.parse_args(argv)

    base = args.qdrant.rstrip("/")
    try:
        info = requests.get(f"{base}/collections/{args.collection}", timeout=args.timeout)
        info.raise_for_status()
        declared = info.json()["result"]["points_count"]
    except Exception as exc:  # noqa: BLE001
        print(f"cannot read collection {args.collection}: {exc}", file=sys.stderr)
        return 2
    print(f"collection {args.collection}: points_count = {declared:,}")

    per_source = defaultdict(lambda: {
        "chunks": 0,
        "url_granularity": Counter(),
        "with_published_at": 0,
        "with_updated_at": 0,
        "trust_tier": Counter(),
        "doc_type": Counter(),
        "language": Counter(),
        "source_names": Counter(),
        "with_institution": 0,
        "article_ids": set(),
    })

    scrolled, offset = 0, None
    while True:
        body = {"limit": args.limit, "with_payload": PAYLOAD_FIELDS, "with_vector": False}
        if offset is not None:
            body["offset"] = offset
        try:
            r = requests.post(f"{base}/collections/{args.collection}/points/scroll",
                              json=body, timeout=args.timeout)
            r.raise_for_status()
            result = r.json()["result"]
        except Exception as exc:  # noqa: BLE001
            print(f"scroll failed after {scrolled:,} points: {exc}", file=sys.stderr)
            return 2

        for point in result.get("points", []):
            p = point.get("payload") or {}
            s = per_source[str(p.get("source_id") or "<missing>")]
            s["chunks"] += 1
            s["url_granularity"][url_granularity(p.get("source_url"))] += 1
            s["with_published_at"] += 1 if str(p.get("published_at") or "").strip() else 0
            s["with_updated_at"] += 1 if str(p.get("updated_at") or "").strip() else 0
            s["trust_tier"][str(p.get("trust_tier"))] += 1
            s["doc_type"][str(p.get("doc_type") or "<missing>")] += 1
            s["language"][str(p.get("language") or "<missing>")] += 1
            s["source_names"][str(p.get("source_name") or "<missing>")] += 1
            s["with_institution"] += 1 if str(p.get("institution") or "").strip() else 0
            aid = str(p.get("article_id") or "").strip()
            if aid:
                s["article_ids"].add(aid)

        scrolled += len(result.get("points", []))
        offset = result.get("next_page_offset")
        print(f"  scrolled {scrolled:,} / {declared:,}", end="\r", flush=True)
        if offset is None:
            break
    print()

    if scrolled != declared:
        # A short scroll silently understates every share in the table.
        print(f"REFUSING TO WRITE: scrolled {scrolled:,} but the collection reports "
              f"{declared:,}. A census that stopped short is not a census.", file=sys.stderr)
        return 2

    strata = {}
    for source_id, s in sorted(per_source.items(), key=lambda kv: -kv[1]["chunks"]):
        n = s["chunks"]
        g = s["url_granularity"]
        strata[source_id] = {
            "chunks": n,
            "share_of_collection": round(n / scrolled, 4),
            "distinct_article_ids": len(s["article_ids"]),
            "source_url": {
                "any": round((n - g["none"]) / n, 4),
                "article_or_page": g["article"] + g["article_or_page"],
                "issue_level_only": g["issue"],
                "none": g["none"],
            },
            "published_at_coverage": round(s["with_published_at"] / n, 4),
            "updated_at_coverage": round(s["with_updated_at"] / n, 4),
            "institution_coverage": round(s["with_institution"] / n, 4),
            "trust_tier": dict(s["trust_tier"]),
            "doc_type": dict(s["doc_type"].most_common(6)),
            "language": dict(s["language"].most_common(4)),
            "source_name": dict(s["source_names"].most_common(3)),
        }

    total_articles = len(set().union(*(s["article_ids"] for s in per_source.values())))
    no_url = sum(v["source_url"]["none"] for v in strata.values())
    issue_only = sum(v["source_url"]["issue_level_only"] for v in strata.values())
    dated = sum(int(v["published_at_coverage"] * v["chunks"]) for v in strata.values())

    artifact = {
        "schema": "rivf_corpus_census.v1",
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_sha": git_head(),
        "collection": args.collection,
        "qdrant": base,
        "points_count_declared": declared,
        "points_scrolled": scrolled,
        "totals": {
            "chunks": scrolled,
            "distinct_article_ids": total_articles,
            "chunks_with_no_source_url": no_url,
            "share_with_no_source_url": round(no_url / scrolled, 4),
            "chunks_with_issue_level_url_only": issue_only,
            "share_with_issue_level_url_only": round(issue_only / scrolled, 4),
            "chunks_with_a_publication_date": dated,
            "share_with_a_publication_date": round(dated / scrolled, 4),
        },
        "strata": strata,
        "definitions": {
            "citable": "the gate's test is a non-empty source_url; this census splits that into article-or-page level and issue level, because a citation resolving to a journal issue index does not let a reader find the cited sentence",
            "url_granularity": "issue = matches /issue/view|archive/; article = matches /article/view|download/, /pmc/, /books/ or doi.org; article_or_page = any other non-empty URL, i.e. a single landing page",
            "distinct_article_ids": "the only article count with a derivation. README's 128,674 has none and the deduplication record calls it inflated",
        },
        "limits": [
            "payload only: no chunk text is read, so nothing here says whether a chunk is USEFUL, only whether it could be cited",
            "counts points in the live collection, which is the object the served system retrieves from -- not the export files on disk",
            "url_granularity is a syntactic classification of the URL, not a fetch: it does not prove the URL resolves today",
        ],
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"corpus_census_{args.collection}.json"
    out.write_text(json.dumps(artifact, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\ntotal chunks        {scrolled:,}")
    print(f"distinct articles   {total_articles:,}")
    print(f"no source_url       {no_url:,}  ({no_url / scrolled:.1%})")
    print(f"issue-level URL only{issue_only:>8,}  ({issue_only / scrolled:.1%})")
    print(f"with a pub date     {dated:,}  ({dated / scrolled:.1%})")
    print(f"\nper stratum (chunks / share / no-URL / articles):")
    for sid, v in strata.items():
        print(f"  {sid:<34} {v['chunks']:>9,}  {v['share_of_collection']:>7.2%}  "
              f"{v['source_url']['none']:>9,}  {v['distinct_article_ids']:>7,}")
    print(f"\nwrote {out.relative_to(REPO_ROOT)}")
    print(f"file sha256 {hashlib.sha256(out.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
