"""Score a G2 extraction run and project its cost. Works on the pilot or the full pass.

Emits, side by side, the three rates the gate turns on -- raw_fill, span_returned,
verified_fill -- plus the strict-numeric diagnostic, the four abstract views, and the
dollar accounting taken from DeepSeek's own ``usage`` object.

Usage:
    python benchmark/g2/g2_score.py --sample benchmark/g2/g2_sample_v1.jsonl \
        --texts <texts.jsonl> --results <results.json> --out <report.json>
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from g2_verify import (  # noqa: E402
    FIELDS,
    GATE_THRESHOLDS,
    abstract_field_content,
    abstract_views,
    verify_field,
)

# deepseek-v4-flash list prices, USD per 1M tokens.
PRICE_IN_MISS = 0.14
PRICE_IN_HIT = 0.014
PRICE_OUT = 0.28


def parse_content(raw: str | None) -> tuple[dict, str | None]:
    if not raw:
        return {}, "empty_content"
    try:
        d = json.loads(raw)
    except json.JSONDecodeError as e:
        return {}, f"json_decode: {e}"
    return (d, None) if isinstance(d, dict) else ({}, "not_an_object")


def _pair(obj, field):
    v = obj.get(field)
    if isinstance(v, dict):
        return v.get("value"), v.get("span")
    return v, None


def score(sample_path: Path, texts_path: Path, results_path: Path) -> dict:
    rows = [json.loads(l) for l in sample_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    manifest = rows[0]
    arts = {r["article_id"]: r for r in rows[1:]}
    texts = {}
    for line in texts_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            texts[d["article_id"]] = d

    run = json.loads(results_path.read_text(encoding="utf-8"))
    results = run["results"]

    per_article = []
    tally = defaultdict(Counter)
    parse_errors = Counter()
    abstract_tally = Counter()
    abs_content_num = 0
    abs_content_den = 0

    for r in results:
        aid = r["article_id"]
        art = arts[aid]
        text = texts[aid]["text"][: manifest["max_chars"]]
        obj, err = parse_content(r.get("content"))
        if err:
            parse_errors[err] += 1

        field_results = []
        spans = {}
        for f in FIELDS:
            value, span = _pair(obj, f)
            spans[f] = span
            fr = verify_field(f, value, span, text)
            field_results.append(fr)
            for k in (
                "raw_fill",
                "span_returned",
                "span_contained",
                "verified_fill",
                "verified_fill_strict_numeric",
            ):
                tally[f][k] += int(fr[k])
            tally[f]["n"] += 1

        av = abstract_views(text, texts[aid].get("abstract_by_label", ""), obj)
        for k, v in av.items():
            if isinstance(v, bool):
                abstract_tally[k] += int(v)
        abstract_tally["n"] += 1

        # abstract field content uses the LABEL region only when it is a plausible
        # abstract length; a 15,000-char "abstract" is the article, and scoring against
        # it would report ~100% for a reason that has nothing to do with abstracts.
        abs_text = (
            texts[aid].get("abstract_by_label", "")
            if av["abstract_label_plausible"]
            else ""
        )
        afc = abstract_field_content(field_results, spans, abs_text)
        if afc["rate"] is not None:
            abs_content_num += afc["n_in_abstract"]
            abs_content_den += afc["n_verified"]

        per_article.append(
            {
                "article_id": aid,
                "stratum": art["stratum"],
                "source_url_granularity": art["source_url_granularity"],
                "truncated": art["truncated"],
                "finish_reason": r.get("finish_reason"),
                "parse_error": err,
                "model_says_scrambled": bool(obj.get("text_is_scrambled")),
                "fields": field_results,
                "abstract": av,
                "abstract_field_content": afc,
                "usage": r.get("usage"),
            }
        )

    # --- cost, from the provider's own usage object -------------------------
    in_miss = sum((p["usage"] or {}).get("prompt_cache_miss_tokens", 0) for p in per_article)
    in_hit = sum((p["usage"] or {}).get("prompt_cache_hit_tokens", 0) for p in per_article)
    out_tok = sum((p["usage"] or {}).get("completion_tokens", 0) for p in per_article)
    cost = (
        in_miss * PRICE_IN_MISS + in_hit * PRICE_IN_HIT + out_tok * PRICE_OUT
    ) / 1_000_000

    def rate(f, k):
        return tally[f][k] / tally[f]["n"] if tally[f]["n"] else None

    n_or_numeric = sum(
        1
        for p in per_article
        if any(
            fr["verified_fill"]
            for fr in p["fields"]
            if fr["field"] in ("n", "primary_numeric_finding")
        )
    )
    pop = sum(
        1
        for p in per_article
        if any(fr["verified_fill"] for fr in p["fields"] if fr["field"] == "population_facet")
    )
    n_art = len(per_article)

    return {
        "n_articles_scored": n_art,
        "parse_errors": dict(parse_errors),
        "per_field": {
            f: {
                "raw_fill": rate(f, "raw_fill"),
                "span_returned": rate(f, "span_returned"),
                "span_contained": rate(f, "span_contained"),
                "verified_fill": rate(f, "verified_fill"),
                "verified_fill_strict_numeric": rate(f, "verified_fill_strict_numeric"),
                "counts": dict(tally[f]),
            }
            for f in FIELDS
        },
        "gate": {
            "verified_fill_n_or_primary_numeric": n_or_numeric / n_art if n_art else None,
            "threshold_n_or_primary_numeric": GATE_THRESHOLDS["n_or_primary_numeric"],
            "verified_fill_population_facet": pop / n_art if n_art else None,
            "threshold_population_facet": GATE_THRESHOLDS["population_facet"],
        },
        "abstract": {
            k: (v / abstract_tally["n"] if k != "n" else v)
            for k, v in abstract_tally.items()
        },
        "abstract_field_content": {
            "n_verified_in_articles_with_a_plausible_abstract": abs_content_den,
            "n_supported_from_inside_the_abstract": abs_content_num,
            "rate": (abs_content_num / abs_content_den) if abs_content_den else None,
        },
        "cost": {
            "prompt_cache_miss_tokens": in_miss,
            "prompt_cache_hit_tokens": in_hit,
            "completion_tokens": out_tok,
            "usd": round(cost, 6),
            "prices_usd_per_1m": {
                "input_miss": PRICE_IN_MISS,
                "input_hit": PRICE_IN_HIT,
                "output": PRICE_OUT,
            },
            "balance_before": run.get("balance_before"),
            "balance_after": run.get("balance_after"),
            "balance_note": (
                "the /user/balance endpoint reports 2 decimal places, so it cannot "
                "resolve a spend below $0.01; it bounds the run, the usage object "
                "measures it"
            ),
        },
        "per_article": per_article,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default=str(HERE / "g2_sample_v1.jsonl"))
    ap.add_argument("--texts", required=True)
    ap.add_argument("--results", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    rep = score(Path(args.sample), Path(args.texts), Path(args.results))
    Path(args.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in rep.items() if k != "per_article"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
