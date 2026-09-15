"""Estimate reachability and destination on the confirmatory PPS sample, with a design-based
interval.

WHY THIS FILE IS SEPARATE. The exploratory pass had three defects, and each one is fixed by a
different thing:

  the estimator      -- fixed by Horvitz-Thompson / Hajek over real per-URL weights
  the sample         -- fixed by THIS sample: host-stratified, chunk-PPS, frozen and hashed
                        before a single request, drawn only from URLs never touched
  the predicate      -- fixed by the 40-item page-type sheet, which measured the destination
                        regex at precision 0.967 and recall 1.000 against a person's reading

Only with all three does a corpus-level number mean anything, so the estimate lives here
rather than being folded into the exploratory report, where a reader could mistake it for a
continuation of the withdrawn figure.

THE INTERVAL. Systematic PPS has no unbiased variance estimator; the standard practical choice
is to treat the draw as with-replacement PPS and use the Hansen-Hurwitz form, which is
CONSERVATIVE for systematic sampling. Certainty units (pi = 1) contribute no variance -- they
are a census of themselves. Strata combine additively.

    z_i = y_i * c_i / pi_i          (the HT contribution of unit i)
    var_hat(T) = n/(n-1) * sum_i (z_i - z_bar)^2     within each non-certainty stratum

and the ratio's interval is formed on T and divided by the known population total, which is
not estimated.

    python benchmark/rivf/url_confirmatory_estimate.py
    python benchmark/rivf/url_confirmatory_estimate.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

from artifact_provenance import source_sha256
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from survey_ci import clopper_pearson  # noqa: E402

POP = REPO / "benchmark/rivf/url_population_v4.json"
SAMPLE = REPO / "benchmark/rivf/url_confirmatory_sample_v1.json"
PROBED = REPO / "benchmark/rivf/url_confirmatory_probed_v1.jsonl"
PAGETYPE = REPO / "benchmark/rivf/page_type_v1.json"
OUT = REPO / "benchmark/rivf/url_confirmatory_estimate_v1.json"

Z = 1.959963984540054  # two-sided 95 %

_ISSUE_RE = re.compile(r"/issue/(view|archive)/", re.IGNORECASE)


def landed_issue_index(final_url: str) -> bool:
    return bool(_ISSUE_RE.search(final_url or ""))


def pps_ratio(units, population_total, z=Z, denominator_is_estimated=False):
    """Horvitz-Thompson total over a KNOWN denominator, with a with-replacement PPS variance.

    `units` are dicts with `w` (population weight, here the URL's chunk count), `pi`
    (inclusion probability), `y` (0/1) and `stratum`. The denominator is known from the
    census, so all the variance sits in the numerator.

    For with-replacement PPS with per-draw probability p_i = pi_i / n, the Hansen-Hurwitz
    total is T = (1/n) * sum(w_i y_i / p_i) = sum(z_i) with z_i = w_i y_i / pi_i, and

        v(T) = 1/(n(n-1)) * sum_i (w_i y_i / p_i - T)^2 = n/(n-1) * sum_i (z_i - z_bar)^2

    which is CONSERVATIVE for the systematic PPS actually drawn -- systematic sampling has no
    unbiased variance estimator, and treating it as with-replacement is the standard practical
    choice. Certainty units (pi = 1) are observed exactly: they add to the total and nothing to
    the variance.

    `denominator_is_estimated` matters more than it looks. When the denominator comes from the
    SAME sample -- as it does for "of the mass we could measure, how much answers" -- numerator
    and denominator are strongly correlated, and treating the denominator as fixed makes the
    sampling error cancel itself. The first run of this file did exactly that and produced
    0.9321 [0.9312, 0.9331] from 144 units. With the flag set, the variance is taken on the
    LINEARISED residual total, sum w_i (y_i - R) / pi_i, which is the standard treatment for a
    ratio of two estimated totals.
    """
    by_stratum: dict[str, list] = defaultdict(list)
    for u in units:
        by_stratum[u["stratum"]].append(u)

    total = 0.0
    certainty = 0
    for us in by_stratum.values():
        for u in us:
            if u["pi"] >= 1.0 - 1e-12:
                certainty += 1
                total += u["w"] * u["y"]
            else:
                total += u["w"] * u["y"] / u["pi"]

    R = total / population_total

    def contribution(u):
        """What this unit contributes to the variance: the raw HT term, or the residual."""
        y = (u["y"] - R) if denominator_is_estimated else u["y"]
        return u["w"] * y / u["pi"]

    var = 0.0
    for us in by_stratum.values():
        rand = [u for u in us if u["pi"] < 1.0 - 1e-12]
        if len(rand) < 2:
            continue
        zs = [contribution(u) for u in rand]
        n = len(zs)
        zbar = sum(zs) / n
        var += n / (n - 1) * sum((v - zbar) ** 2 for v in zs)

    se = math.sqrt(var) if var > 0 else 0.0
    point = R
    half = z * se / population_total
    return {
        "point": round(point, 4),
        "ci95": [round(max(0.0, point - half), 4), round(min(1.0, point + half), 4)],
        "se_of_the_share": round(se / population_total, 4),
        "certainty_units": certainty,
        "sampled_units": len(units) - certainty,
        "strata_with_one_sampled_unit": sum(
            1 for us in by_stratum.values()
            if len([u for u in us if u["pi"] < 1.0 - 1e-12]) == 1),
        "method": (
            "Horvitz-Thompson total over the known population denominator; variance by the "
            "with-replacement (Hansen-Hurwitz) form n/(n-1) * sum (z_i - z_bar)^2, which is "
            "CONSERVATIVE for the systematic PPS actually used. Certainty units contribute no "
            "variance. A stratum with a single sampled unit contributes none either, so its "
            "uncertainty is UNDERSTATED -- the count is reported above."
        ),
        "denominator": "estimated from the same sample (linearised)" if denominator_is_estimated
                       else "known from the census",
    }


def exact_envelope(units, z=None):
    """Per-host Clopper-Pearson bounds, combined under the hosts' population weights.

    The design-based variance collapses wherever a host's sampled units all agree, because a
    sample variance of identical numbers is zero. This does not: 25 of 25 reachable gives
    [0.863, 1.000], not [1.000, 1.000].

    Weights are each host's share of the sampled population's chunk mass. Like every other
    envelope in this repository it is a PROJECTION of marginal intervals -- no joint coverage
    guarantee -- and the caller must not present it as a confidence interval.
    """
    by_host: dict[str, list] = defaultdict(list)
    for u in units:
        by_host[u["stratum"]].append(u)

    W = sum(sum(u["w"] for u in us) for us in by_host.values())
    if not W:
        return None
    point = lo = hi = 0.0
    detail = {}
    for host, us in sorted(by_host.items()):
        w = sum(u["w"] for u in us) / W
        k = sum(u["y"] for u in us)
        n = len(us)
        a, b = clopper_pearson(k, n)
        point += w * (k / n)
        lo += w * a
        hi += w * b
        detail[host] = {"k": k, "n": n, "weight": round(w, 4),
                        "exact": [round(a, 4), round(b, 4)]}
    return {
        "point": round(point, 4),
        "envelope": [round(lo, 4), round(hi, 4)],
        "no_joint_coverage_guarantee": (
            "Per-host Clopper-Pearson bounds combined under chunk-mass weights: a projection "
            "of marginal intervals, not a simultaneous interval and not a confidence interval "
            "for the weighted total."
        ),
        "why_this_is_reported_beside_the_design_based_interval": (
            "The design-based variance is a SAMPLE variance, and 17 of 18 hosts are unanimous "
            "-- all reachable or all dead -- so it reports almost no uncertainty. Observing 25 "
            "of 25 on a host of 6,429 URLs does not make its rate 1.0 exactly; the exact bound "
            "is [0.863, 1.000]. Quoting only the design-based interval would repeat the error "
            "the relevance sheet's bootstrap made."
        ),
        "by_host": detail,
    }


def _self_test_pps():
    """A case with a known answer, and a check that the variance is not the /(n-1) form."""
    # 4 units, weights 10 each, two of them successes, sampled with pi = 0.5 each.
    units = [{"w": 10, "pi": 0.5, "y": y, "stratum": "h"} for y in (1, 1, 0, 0)]
    r = pps_ratio(units, 80.0)            # population total 80 = 8 units x 10
    # T = sum(10*y/0.5) = 20 + 20 = 40 ; point = 40/80 = 0.5
    assert abs(r["point"] - 0.5) < 1e-12, r
    zs = [20.0, 20.0, 0.0, 0.0]
    zbar = sum(zs) / 4
    expect_var = 4 / 3 * sum((v - zbar) ** 2 for v in zs)
    # se_of_the_share is rounded to 4 dp by the caller, so compare at that resolution.
    assert abs(r["se_of_the_share"] - round(math.sqrt(expect_var) / 80.0, 4)) < 1e-9, r
    wrong = math.sqrt(sum((v - zbar) ** 2 for v in zs) / 3) / 80.0
    assert abs(r["se_of_the_share"] - wrong) > 1e-6, "the /(n-1) form must NOT match"
    print(f"  pps_ratio self-test: point {r['point']}, se {r['se_of_the_share']:.4f} "
          f"(the wrong /(n-1) form would give {wrong:.4f}) PASS")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    _self_test_pps()

    samp = json.loads(SAMPLE.read_text(encoding="utf-8"))
    meta = {r["url"]: r for r in samp["urls"]}
    recs = [json.loads(l) for l in PROBED.open(encoding="utf-8") if l.strip()]

    reach, dest = [], []
    blocked_urls = blocked_chunks = 0
    for rec in recs:
        m = meta.get(rec["url"])
        if not m:
            continue
        if rec.get("outcome") == "skipped_by_robots":
            blocked_urls += 1
            blocked_chunks += m["chunks"]
            continue
        st = rec.get("status")
        ok = rec.get("outcome") == "ok" and isinstance(st, int) and 200 <= st < 300
        base = {"w": m["chunks"], "pi": m["inclusion_probability"], "stratum": m["host"]}
        reach.append({**base, "y": 1 if ok else 0})
        if ok:
            dest.append({**base, "y": 0 if landed_issue_index(rec.get("final_url") or "") else 1})

    # The denominator is ESTIMATED from this same sample, so the ratio must be linearised.
    measurable_chunks = sum(u["w"] / u["pi"] for u in reach)

    pt = json.loads(PAGETYPE.read_text(encoding="utf-8")) if PAGETYPE.exists() else None
    validation = None
    if pt:
        t = pt["the_regex_under_test"]
        validation = {
            "source": "benchmark/rivf/page_type_v1.json",
            "precision_of_not_an_index": t["precision_of_not_an_index"]["naive"],
            "precision_exact_ci": t["precision_of_not_an_index"]["exact"],
            "recall_on_indexes": t["recall_on_indexes"]["naive"],
            "recall_exact_ci": t["recall_on_indexes"]["exact"],
            "pages_that_were_homepage_search_or_soft404": (
                pt["headline"]["share_the_regex_cannot_see_WEIGHTED_TO_THE_PROBE_POOL"]["post_stratified"]
            ),
            "reading": (
                "The destination regex was checked against a person's reading of 40 pages. It "
                "did NOT turn out to be the blunt instrument feared: no probed page was a "
                "homepage, a search page or a soft 404. But the precision interval's lower "
                "bound is 0.83, so up to about one in six pages it passes could still be "
                "something other than a document page, and any corpus figure built on it "
                "inherits that."
            ),
        }

    out = {
        "what_this_is": (
            "Reachability and destination on the CONFIRMATORY sample: host-stratified, "
            "chunk-PPS, frozen and hashed before any request, drawn only from URLs the "
            "exploratory pass never touched."
        ),
        "why_it_is_separate_from_the_exploratory_report": (
            "The exploratory pass had three defects and each needed a different fix: the "
            "estimator (Horvitz-Thompson over real per-URL weights), the sample (this one), "
            "and the destination predicate (the 40-item page-type sheet). Keeping this apart "
            "stops a reader taking it for a continuation of the withdrawn figure."
        ),
        "provenance": {
            "sample": str(SAMPLE.relative_to(REPO)).replace("\\", "/"),
            "sample_sha256": source_sha256(SAMPLE),
            "frozen_before_any_request": True,
            "probe_log": str(PROBED.relative_to(REPO)).replace("\\", "/"),
            "design": samp["provenance"]["design"],
            "n_selected": samp["n"],
            "n_probed": len(recs),
            "robots_blocked_urls": blocked_urls,
            "robots_blocked_chunks": blocked_chunks,
        },
        "2_http_reachability_chunk_weighted": {
            "design_based": pps_ratio(reach, measurable_chunks, denominator_is_estimated=True),
            "exact_envelope_per_host": exact_envelope(reach),
            "READ_THE_ENVELOPE": (
                "The design-based interval collapses because 17 of 18 hosts are unanimous and "
                "a sample variance of identical observations is zero. The envelope beside it "
                "does not make that assumption. Quote the envelope."
            ),
        },
        "3a_not_an_issue_index_given_it_answered": {
            "value": "NOT APPLICABLE on this sample, by construction",
            "why": (
                "This sample was drawn only from URLs the exploratory pass never touched, and "
                "that pass CENSUSED all 143 issue-level URLs. No issue URL can be in this "
                "sample, so the quantity is 1.0 by construction rather than by measurement. "
                "Reporting it would be exactly the kind of by-construction number this paper "
                "exists to flag. The issue stratum's result is the census, not an estimate."
            ),
            "issue_urls_in_this_sample": sum(
                1 for r in samp["urls"] if r["granularity"] == "issue"),
        },
        "destination_predicate_validation": validation,
        "what_this_still_does_not_license": (
            "A single corpus-level composite. This sample covers the URLs the exploratory pass "
            "had not touched, not the whole corpus, and it excludes the robots.txt hosts "
            "entirely. Combining it with the exploratory pass would mix a frozen design with an "
            "adaptive one. The paper therefore still reports the issue CENSUS as its claim."
        ),
    }

    text = json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("estimate reproduces exactly" if same else "ESTIMATE DIFFERS from a fresh run")
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8")

    print(f"wrote {OUT.relative_to(REPO)}")
    rr = out["2_http_reachability_chunk_weighted"]
    r, e = rr["design_based"], rr["exact_envelope_per_host"]
    print(f"\n  reachability, chunk-weighted: {r['point']}")
    print(f"    design-based 95 % CI {r['ci95']}  <- COLLAPSED: 17 of 18 hosts are unanimous")
    print(f"    per-host exact envelope {e['envelope']}  <- quote this one")
    print(f"    {r['certainty_units']} certainty units, {r['sampled_units']} PPS-sampled")
    d = out["3a_not_an_issue_index_given_it_answered"]
    print(f"  not an issue index | answered : {d['value']}")
    print(f"    ({d['issue_urls_in_this_sample']} issue URLs in this sample -- all 143 were "
          f"censused by the earlier pass)")
    if validation:
        print(f"\n  the predicate behind that second number, checked by a person:")
        print(f"    precision {validation['precision_of_not_an_index']} {validation['precision_exact_ci']}"
              f" | recall {validation['recall_on_indexes']} {validation['recall_exact_ci']}")
        print(f"    homepage/search/soft-404 among 40 probed pages: "
              f"{validation['pages_that_were_homepage_search_or_soft404']}")
    print(f"\n  robots.txt excluded {blocked_urls} URLs / {blocked_chunks:,} chunks from this sample")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
