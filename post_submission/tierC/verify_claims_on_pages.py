"""For every URL-less claim whose source title was recovered to a verified page, fetch that page once
and test whether the claim sentence and its supporting_span occur in the page text (same normalisation
spirit as the span gate: NFC, lowercase, whitespace and punctuation-variant collapse; diacritics kept).
Then project the shipped arm's retention and the fate of the 11 responsive withheld claims under recovery.

Usage:
    python -I -X utf8 verify_claims_on_pages.py <tierC dir> <tierB dir> <repo dir> [--check]
With --check, recomputes the summary figures offline from claims_on_recovered_pages.json + Tier-B labels
without performing live HTTP requests.
"""
import collections
import html
import json
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

check_mode = "--check" in sys.argv
args = [a for a in sys.argv[1:] if a != "--check"]
C = Path(args[0])
B = Path(args[1])
R = Path(args[2])
UA = "vi-medrag-audit-research/1.0 (title-to-URL recovery; low rate)"


def fetch(url):
    p = subprocess.run(
        ["curl", "-s", "-L", "--compressed", "--max-time", "40", "-A", UA, "-w", "\n__STATUS__%{http_code}", url],
        capture_output=True,
    )
    body, _, st = p.stdout.rpartition(b"\n__STATUS__")
    return st.strip().decode(), body.decode("utf-8", "ignore")


def text_of(page):
    page = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", page)
    page = re.sub(r"(?s)<[^>]+>", " ", page)
    return html.unescape(page)


def norm(s):
    s = unicodedata.normalize("NFC", s or "").lower()
    s = s.replace("–", "-").replace("—", "-").replace("“", '"').replace("”", '"').replace("’", "'")
    s = re.sub(r"[\s\xa0]+", " ", s)
    s = re.sub(r"\s*([,.;:!?()\"'-])\s*", r"\1", s)
    return s.strip()


def compute_summary(rows, pages_fetched, pages_ok):
    cnt = collections.Counter(
        (o["drop_reason"], o["recovered"], o["claim_on_page"], o.get("claim_core_on_page", False)) for o in rows
    )
    keyC = json.loads((B / "key_claims.json").read_text(encoding="utf-8"))
    final = json.loads((B / "judge_result.json").read_text(encoding="utf-8"))["final"]
    resp = [
        k
        for k in keyC
        if k.get("kind") == "real"
        and k["arm"] == "shipped"
        and k["status"] == "withheld"
        and k["drop_reason"] == "cited_record_not_citable"
        and final.get(k["item_id"], {}).get("label") == "relevant"
    ]
    by_key = {(o["query_id"], o["claim"].strip()): o for o in rows}
    resp_rows = [by_key.get((k["query_id"], k["claim"].strip())) for k in resp]

    cit = [o for o in rows if o["drop_reason"] == "cited_record_not_citable"]
    n_rec = sum(bool(o["recovered"]) for o in cit)
    n_on = sum(bool(o["recovered"] and o["claim_on_page"]) for o in cit)
    n_core = sum(bool(o["recovered"] and (o["claim_on_page"] or o.get("claim_core_on_page"))) for o in cit)
    n_span = sum(bool(o["recovered"] and o.get("span_on_page")) for o in cit)
    n_span_eq = sum(bool(o.get("span_equals_claim")) for o in cit)
    return {
        "pages_fetched": pages_fetched,
        "pages_ok": pages_ok,
        "citability_withheld": len(cit),
        "recovered_url": n_rec,
        "claim_verbatim_on_page": n_on,
        "claim_core_on_page": n_core,
        "projected_C3_returned_if_recovered_url": 185 + n_rec,
        "projected_C3_retention_url": round((185 + n_rec) / 351, 4),
        "projected_C3_returned_if_claim_on_page": 185 + n_core,
        "projected_C3_retention_on_page": round((185 + n_core) / 351, 4),
        "responsive_withheld": len(resp),
        "responsive_withheld_recovered": sum(1 for r in resp_rows if r and r["recovered"]),
        "responsive_withheld_on_page": sum(
            1 for r in resp_rows if r and r["recovered"] and (r["claim_on_page"] or r.get("claim_core_on_page"))
        ),
        "breakdown": {str(k): v for k, v in cnt.items()},
        "span_on_page": n_span,
        "projected_C3_returned_if_span_on_page": 185 + n_span,
        "projected_C3_retention_span_on_page": round((185 + n_span) / 351, 4),
        "span_equals_claim": n_span_eq,
        "responsive_withheld_span_on_page": sum(
            1 for r in resp_rows if r and r["recovered"] and r.get("span_on_page")
        ),
    }


target = C / "claims_on_recovered_pages.json"
if check_mode:
    saved = json.loads(target.read_text(encoding="utf-8"))
    recomp = compute_summary(saved["rows"], saved["summary"]["pages_fetched"], saved["summary"]["pages_ok"])
    if recomp != saved["summary"]:
        raise SystemExit(f"claims_on_recovered_pages summary mismatch:\nexpected={saved['summary']}\nactual={recomp}")
    print("PASS claims_on_recovered_pages.json")
    raise SystemExit(0)

# Build span lookup from shipped capture
cap_path = R / "benchmark/datasets/test_results/pilot_span_exposure_rivf134_2026-09-05_091659_raw.jsonl"
span_map = {}
for line in cap_path.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    row = json.loads(line)
    pl = row["payload"]
    for lst in (pl["claim_attributions"], pl["dropped_claims"]):
        for c in lst:
            span_map[(row["query_id"], (c.get("claim") or "").strip())] = c.get("supporting_span") or ""

rec = json.loads((C / "url_recovery.json").read_text(encoding="utf-8"))
pages = {}
for t, v in rec["titles"].items():
    if v.get("verified") and v.get("url") and v["url"] not in pages:
        st, body = fetch(v["url"])
        pages[v["url"]] = norm(text_of(body)) if st == "200" else None
        time.sleep(1.5)

out = []
for r in rec["claim_rows"]:
    v = rec["titles"].get(r["title"], {})
    sp_raw = span_map.get((r["query_id"], r["claim"].strip()), "")
    sp_eq = norm(sp_raw) == norm(r["claim"])
    if not v.get("verified"):
        out.append({
            **r,
            "recovered": False,
            "claim_on_page": False,
            "span": sp_raw,
            "span_equals_claim": sp_eq,
            "span_on_page": False,
        })
        continue
    page = pages.get(v["url"])
    c = norm(r["claim"])
    sp = norm(sp_raw)
    on = bool(page) and len(c) >= 12 and c in page
    core = c[:60] if len(c) > 60 else c
    on_core = bool(page) and len(core) >= 12 and core in page
    sp_on = bool(page) and len(sp) >= 12 and sp in page
    out.append({
        **r,
        "recovered": True,
        "url": v["url"],
        "claim_on_page": on,
        "claim_core_on_page": on_core,
        "span": sp_raw,
        "span_equals_claim": sp_eq,
        "span_on_page": sp_on,
    })

summary = compute_summary(out, len(pages), sum(1 for p in pages.values() if p))
target.write_text(json.dumps({"summary": summary, "rows": out}, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=1))
