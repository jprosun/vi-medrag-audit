"""Score the 40-item page-type sheet, and say how wrong the destination regex is.

WHAT THIS DECIDES. The dereference audit classified a destination by matching the final URL
against `/issue/(view|archive)/`; everything else that answered 2xx counted as "not an issue
index". That rule cannot see a homepage, a search page, or a soft 404 served with status 200,
and the corpus-level composite was withdrawn partly because of it. This scorer measures the
rule against a person's reading of the same pages.

Two numbers matter, and they are different questions:

  PRECISION of "not an issue index" -- of the pages the rule passed, how many are really a
      single document page. Low precision means the audit's 3a over-counted, which is the
      direction that would have flattered the corpus.
  RECALL on indexes -- of the pages a person calls an index, how many the rule caught. The
      regex only knows one URL shape, so an index served at any other path is invisible to it.

Both are post-stratified: the sheet spends half its items on the catch-all stratum on purpose,
so reading 40 items as one urn would be the same mistake the relevance sheet's naive 2/40
would have been.

    python benchmark/rivf/score_page_type.py
    python benchmark/rivf/score_page_type.py --check
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

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from survey_ci import clopper_pearson  # noqa: E402

SHEET = REPO / "benchmark/rivf/page_type_labels_v1.txt"
KEY = REPO / "benchmark/rivf/page_type_key_v1.json"
OUT = REPO / "benchmark/rivf/page_type_v1.json"

Q1 = {
    "D": "document_page",
    "I": "index_of_many",
    "H": "homepage_or_section",
    "S": "search_or_browse",
    "E": "error_served_as_success",
    "M": "moved_beyond_judgement",
    "O": "other",
}
Q2 = {"Y": "cited_document", "N": "different_document", "?": "stored_title_unusable", "-": "not_applicable"}

# The three the regex is structurally blind to: it sees a URL, not a page.
INVISIBLE_TO_THE_REGEX = ("homepage_or_section", "search_or_browse", "error_served_as_success")


def parse_sheet(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"(?m)^## (pt_\d{2})\s*$", raw)
    out, blank, bad = {}, [], []
    for i in range(1, len(blocks), 2):
        pid, body = blocks[i], blocks[i + 1]
        m = re.search(r"(?m)^=>\s*(.*)$", body)
        if not m:
            bad.append((pid, "no => line"))
            continue
        v = m.group(1).strip()
        if not v:
            blank.append(pid)
            continue
        toks = v.replace(",", " ").split()
        a = toks[0].upper()
        b = toks[1] if len(toks) > 1 else "-"
        b = b.upper() if b != "?" else "?"
        if a not in Q1 or b not in Q2:
            bad.append((pid, v))
            continue
        out[pid] = (Q1[a], Q2[b])
    if blank or bad:
        raise SystemExit(f"sheet not ready: blank {blank}, malformed {bad}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    human = parse_sheet(SHEET)
    kb = json.loads(KEY.read_text(encoding="utf-8"))
    POP = REPO / "benchmark/rivf/url_population_v4.json"
    if POP.exists():
        g = json.loads(POP.read_text(encoding="utf-8"))["distinct_urls_by_granularity"]
        tot = sum(g.values())
        POPULATION_WEIGHTS = {k: v / tot for k, v in g.items()}
    else:
        POPULATION_WEIGHTS = None
    key, design = kb["key"], kb["design"]

    rows = []
    for pid, (q1, q2) in sorted(human.items()):
        k = key[pid]
        rows.append({
            "item": pid, "url": k["url"], "host": k["host"],
            "audit_stratum": k["audit_stratum"],
            "regex_says_not_an_index": k["audit_stratum"] != "issue",
            "human_page_type": q1, "human_is_cited_document": q2,
            "chunks": k["chunks"], "from_log": k["from_log"],
            "stored_title": k["stored_title"], "page_title_at_probe": k["page_title_at_probe"],
        })

    by_stratum: defaultdict[str, list] = defaultdict(list)
    for r in rows:
        by_stratum[r["audit_stratum"]].append(r)

    def post_stratified(pred, universe=None, weights=None):
        """Weighted share, with the conservative projection of per-stratum exact bounds.

        `weights` defaults to the design's probe-pool shares. Pass POPULATION_WEIGHTS to
        reweight to the corpus instead; the two differ by a factor of thirty-nine on the
        censused issue stratum, which is why the caller must choose explicitly.
        """
        num = lo = hi = wsum = 0.0
        detail = {}
        for stratum, items in by_stratum.items():
            pool = [r for r in items if universe is None or universe(r)]
            if not pool:
                continue
            w = (weights or {}).get(stratum) if weights else design[stratum]["weight"]
            if w is None:
                continue
            k = sum(1 for r in pool if pred(r))
            a, b = clopper_pearson(k, len(pool))
            num += w * (k / len(pool)); lo += w * a; hi += w * b; wsum += w
            detail[stratum] = {"k": k, "n": len(pool), "weight": w,
                               "rate": round(k / len(pool), 4), "exact": [round(a, 4), round(b, 4)]}
        if not wsum:
            return None
        return {
            "post_stratified": round(num / wsum, 4),
            "projection_of_exact_bounds": [round(lo / wsum, 4), round(hi / wsum, 4)],
            "projection_carries_no_joint_coverage": (
                "Per-stratum Clopper-Pearson bounds combined under population weights. NOT a "
                "simultaneous interval and NOT a confidence interval for the weighted total."
            ),
            "by_stratum": detail,
        }

    passed = [r for r in rows if r["regex_says_not_an_index"]]
    human_index = [r for r in rows if r["human_page_type"] == "index_of_many"]
    prec_k = sum(1 for r in passed if r["human_page_type"] == "document_page")
    rec_k = sum(1 for r in human_index if not r["regex_says_not_an_index"])

    report = {
        "what_this_is": (
            "The author's blind page-type labelling of 40 pages that answered 2xx, scored "
            "against the destination regex the dereference audit used. This is what decides "
            "whether a corrected corpus-level estimate can be restored or whether the rule's "
            "error rate must be reported as a limitation."
        ),
        "provenance": {
            "sheet": str(SHEET.relative_to(REPO)).replace("\\", "/"),
            "blank_sheet_sha256": kb["blank_sheet_sha256"],
            "filled_sheet_sha256": source_sha256(SHEET),
            "what_the_two_hashes_are": (
                "blank = the sheet as issued, proving the items were frozen before any label; "
                "filled = the bytes actually scored, identifying THIS grading."
            ),
            "codebook": kb["codebook"],
            "codebook_committed_before_items_existed": kb["codebook_committed_before_items_existed"],
            "graded_by": "the author, blind to the audit's classification of every item",
            "design": design,
            "total_2xx_pool": kb["total_2xx_pool"],
        },
        "headline": {
            "what_this_sheet_measures": (
                "The INSTRUMENT, not the corpus. The regex's precision and recall below are "
                "the result. The shares are descriptive of the probed pages only -- see the "
                "denominator warning."
            ),
            "page_types": dict(Counter(r["human_page_type"] for r in rows)),
            "share_that_is_a_document_page_WEIGHTED_TO_THE_PROBE_POOL":
                post_stratified(lambda r: r["human_page_type"] == "document_page"),
            "share_the_regex_cannot_see_WEIGHTED_TO_THE_PROBE_POOL":
                post_stratified(lambda r: r["human_page_type"] in INVISIBLE_TO_THE_REGEX),
            "DENOMINATOR_WARNING": (
                "Those two shares are weighted by each stratum's share of the 2xx PROBE POOL, "
                "not of the corpus. The issue stratum is 33.7 % of the pool and 0.87 % of the "
                "16,478 distinct URLs, because it was deliberately censused -- it is "
                "over-represented about thirty-ninefold. Reading either share as a corpus "
                "figure is the same error as reading the relevance sheet's naive 2/40 as a "
                "rate. Neither is quoted in the paper."
            ),
            "share_that_is_a_document_page_WEIGHTED_TO_THE_POPULATION":
                post_stratified(lambda r: r["human_page_type"] == "document_page",
                                weights=POPULATION_WEIGHTS),
            "population_weighted_still_conditions_on_2xx": (
                "Even this one is the share among pages that ANSWERED. The population's 2xx "
                "composition is not known exactly, because reachability differs by stratum, so "
                "it is an approximation and is not quoted in the paper either."
            ),
        },
        "the_regex_under_test": {
            "rule": "final URL matched /issue/(view|archive)/ -> index; anything else -> not an index",
            "precision_of_not_an_index": {
                "naive": round(prec_k / len(passed), 4) if passed else None,
                "naive_counts": f"{prec_k} of {len(passed)}",
                "exact": [round(x, 4) for x in clopper_pearson(prec_k, len(passed))] if passed else None,
                "post_stratified": post_stratified(
                    lambda r: r["human_page_type"] == "document_page",
                    universe=lambda r: r["regex_says_not_an_index"]),
                "reading": (
                    "Of the pages the rule passed as 'not an index', how many are really a "
                    "single document page. Anything below 1.00 means quantity 3a over-counted."
                ),
            },
            "recall_on_indexes": {
                "naive": round(rec_k / len(human_index), 4) if human_index else None,
                "naive_counts": f"{rec_k} of {len(human_index)}",
                "exact": [round(x, 4) for x in clopper_pearson(rec_k, len(human_index))] if human_index else None,
                "reading": (
                    "Of the pages a person calls an index, how many the rule caught. The regex "
                    "knows one URL shape, so an index served at any other path is invisible."
                ),
            },
            "misses": [
                {"item": r["item"], "url": r["url"], "human": r["human_page_type"],
                 "regex_passed_it": r["regex_says_not_an_index"], "chunks": r["chunks"]}
                for r in rows
                if (r["regex_says_not_an_index"] and r["human_page_type"] != "document_page")
                or (not r["regex_says_not_an_index"] and r["human_page_type"] != "index_of_many")
            ],
        },
        "is_it_the_cited_document": {
            "among_document_pages": dict(Counter(
                r["human_is_cited_document"] for r in rows if r["human_page_type"] == "document_page")),
            "note": (
                "'stored_title_unusable' is a CORPUS defect, not a destination failure, and is "
                "counted apart. Scoring it as 'different_document' would blame the destination "
                "for an ingestion bug."
            ),
        },
        "per_item": rows,
    }

    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("report reproduces exactly" if same else "REPORT DIFFERS from a fresh run")
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8")

    h = report["headline"]
    t = report["the_regex_under_test"]
    print(f"wrote {OUT.relative_to(REPO)}")
    print(f"  page types: {h['page_types']}")
    d = h["share_that_is_a_document_page_WEIGHTED_TO_THE_PROBE_POOL"]
    dp = h.get("share_that_is_a_document_page_WEIGHTED_TO_THE_POPULATION")
    print(f"  document pages: {d['post_stratified']} weighted to the PROBE POOL "
          f"(not a corpus figure)")
    if dp:
        print(f"                  {dp['post_stratified']} weighted to the population, "
              f"still conditional on 2xx")
    b = h["share_the_regex_cannot_see_WEIGHTED_TO_THE_PROBE_POOL"]
    print(f"  homepage / search / soft-404 (invisible to the regex): {b['post_stratified']} "
          f"{b['projection_of_exact_bounds']}")
    print(f"\n  regex precision on 'not an index': {t['precision_of_not_an_index']['naive_counts']} "
          f"= {t['precision_of_not_an_index']['naive']} {t['precision_of_not_an_index']['exact']}")
    print(f"  regex recall on indexes         : {t['recall_on_indexes']['naive_counts']} "
          f"= {t['recall_on_indexes']['naive']} {t['recall_on_indexes']['exact']}")
    if t["misses"]:
        print(f"\n  {len(t['misses'])} disagreements with the rule:")
        for m in t["misses"]:
            print(f"    {m['item']}  human {m['human']:<24} regex passed {m['regex_passed_it']}  "
                  f"{m['chunks']:>6,} chunks")
    print(f"\n  is it the cited document (among D): {report['is_it_the_cited_document']['among_document_pages']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
