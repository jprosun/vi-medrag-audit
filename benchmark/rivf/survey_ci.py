"""Exact intervals for the two human calibration sheets, and the bounds they must respect.

WHY THIS FILE EXISTS. The first version of the entailment scorer bootstrapped BOTH strata and
reported 0.984 [0.973, 0.995]. An external review pointed out that the upper bound is
arithmetically impossible, and it is: stratum A is a CENSUS of all six model failures, of
which the author called exactly three supported, so stratum A's contribution to the rate is
the constant 3/185. The largest rate consistent with what was observed is therefore

    (3 + 179) / 185 = 0.9838

and any interval whose upper end exceeds that describes states of the world that cannot
exist. Resampling a census is what produced it: bootstrapping 6 observed items with
replacement lets stratum A appear as 6/6 supported, which it is not and cannot be.

WHAT REPLACES IT. A census contributes exactly. Only the sampled stratum carries sampling
uncertainty, and for 24 of 24 successes the honest interval is Clopper-Pearson, which is
exact for a binomial and conservative here because the sample is drawn without replacement
from 179 rather than from an infinite population.

    rate = 3/185 + (179/185) * p_B,      p_B in Clopper-Pearson(24, 24)

`feasible_bounds` is exported so a caller can assert that whatever it reports lies inside
what the design can express. That assertion is the guard the first version did not have.
"""

from __future__ import annotations

from math import comb


def _binom_tail_ge(x: int, n: int, p: float) -> float:
    """P(X >= x) for X ~ Binomial(n, p). Exact summation; n is small here."""
    return sum(comb(n, k) * p**k * (1 - p) ** (n - k) for k in range(x, n + 1))


def _binom_tail_le(x: int, n: int, p: float) -> float:
    return sum(comb(n, k) * p**k * (1 - p) ** (n - k) for k in range(0, x + 1))


def clopper_pearson(x: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Exact two-sided binomial interval, by bisection on the tail probabilities.

    Degenerate ends are handled in closed form: x = 0 has lower bound 0, x = n has upper
    bound 1, which is where the entailment sheet sits.
    """
    assert 0 <= x <= n and n > 0
    half = alpha / 2

    if x == 0:
        lo = 0.0
    else:
        a, b = 0.0, 1.0
        for _ in range(200):
            m = (a + b) / 2
            if _binom_tail_ge(x, n, m) < half:
                a = m
            else:
                b = m
        lo = (a + b) / 2

    if x == n:
        hi = 1.0
    else:
        a, b = 0.0, 1.0
        for _ in range(200):
            m = (a + b) / 2
            if _binom_tail_le(x, n, m) > half:
                a = m
            else:
                b = m
        hi = (a + b) / 2

    return lo, hi


def feasible_bounds(census_supported: int, census_n: int, sampled_n: int, population_n: int):
    """(min, max) rate the design can express, given a census and a partly sampled stratum.

    Everything unobserved in the sampled stratum could be a success or a failure; the census
    is fixed. Any reported interval must lie inside this.
    """
    total = census_n + population_n
    lo = (census_supported + 0) / total
    hi = (census_supported + population_n) / total
    return lo, hi, sampled_n


def post_stratified_two_strata(
    census_supported: int, census_n: int, sampled_successes: int, sampled_n: int,
    population_n: int, alpha: float = 0.05,
):
    """Point estimate and interval for a census stratum plus one sampled stratum.

    Returns a dict, and asserts the interval lies inside `feasible_bounds`.
    """
    total = census_n + population_n
    w_census = census_n / total
    w_pop = population_n / total
    p_census = census_supported / census_n
    p_hat = sampled_successes / sampled_n
    lo_p, hi_p = clopper_pearson(sampled_successes, sampled_n, alpha)

    point = w_census * p_census + w_pop * p_hat
    lo = w_census * p_census + w_pop * lo_p
    hi = w_census * p_census + w_pop * hi_p

    f_lo, f_hi, _ = feasible_bounds(census_supported, census_n, sampled_n, population_n)
    assert f_lo - 1e-9 <= lo <= hi <= f_hi + 1e-9, (
        f"interval [{lo:.4f}, {hi:.4f}] escapes what the design can express "
        f"[{f_lo:.4f}, {f_hi:.4f}] -- this is the defect the review caught"
    )

    return {
        "point": round(point, 4),
        "ci": [round(lo, 4), round(hi, 4)],
        "method": (
            "census stratum contributes exactly; sampled stratum by exact Clopper-Pearson, "
            "conservative because the draw is without replacement from a finite population"
        ),
        "alpha": alpha,
        "sampled_proportion": [round(p_hat, 4), round(lo_p, 4), round(hi_p, 4)],
        "census_proportion": round(p_census, 4),
        "weights": {"census": round(w_census, 6), "sampled_population": round(w_pop, 6)},
        "feasible_bounds_of_the_design": [round(f_lo, 4), round(f_hi, 4)],
    }


def conservative_envelope(counts, weights, alpha: float = 0.05):
    """A valid but usually useless bound for a many-strata sheet: sum the per-stratum
    Clopper-Pearson ends, weighted.

    Reported for the relevance sheet so a reader can see WHY no interval is quoted for it:
    with 8 items per stratum and three strata observing zero successes, the envelope is so
    wide that it carries no information, and a bootstrap that returns something narrow is
    reporting the sample's own degeneracy rather than uncertainty about the population.
    """
    lo = hi = 0.0
    per = {}
    for stratum, (x, n) in counts.items():
        l, h = clopper_pearson(x, n, alpha)
        w = weights[stratum]
        lo += w * l
        hi += w * h
        per[stratum] = {"x": x, "n": n, "weight": round(w, 4), "ci": [round(l, 4), round(h, 4)]}
    return {"envelope": [round(lo, 4), round(hi, 4)], "per_stratum": per}


if __name__ == "__main__":
    print("entailment sheet, as designed: census 3/6 supported, sample 24/24 of 179")
    r = post_stratified_two_strata(3, 6, 24, 24, 179)
    for k, v in r.items():
        print(f"  {k}: {v}")
    print("\nwhat the first version reported: 0.984 [0.973, 0.995]")
    print(f"  max the design can express: {r['feasible_bounds_of_the_design'][1]}"
          f"  -> 0.995 was impossible")


# ──────────────────────────────────────────────────────────────────────────────────────────
# Horvitz-Thompson for the URL dereference audit.
#
# WHY IT IS HERE. The audit first estimated a chunk-weighted rate as
#
#     sum_h (C_h / C) * (k_h / n_h)
#
# -- weight each host by its chunk mass, but estimate the host's success rate as the
# UNWEIGHTED mean over sampled URLs. That is unbiased for the chunk-weighted quantity only if,
# inside every host, a URL's chunk count is independent of whether it resolves. Nobody stated
# that assumption and it is false here: correcting it moved reachability 0.9488 -> 0.9365 and
# the joint quantity 0.6977 -> 0.6837, both in the optimistic direction.
#
# The estimand is a ratio of totals over URLs, so the estimator is Horvitz-Thompson on the
# numerator over the KNOWN population denominator.


def horvitz_thompson_ratio(strata, population_weight_total):
    """Ratio estimate of sum_i w_i y_i / sum_i w_i from a stratified sample.

    `strata` is an iterable of dicts, one per stratum (here: per host), each with

        N            population size of the stratum (number of URLs)
        n            number sampled AND measurable
        weight_hits  sum of w_i * y_i over the sampled units   <- REAL per-unit weights
        W            population weight total for the stratum (its chunk count)

    A stratum with n == N is a census: its inclusion probability is 1 and it contributes
    `weight_hits` exactly, with no inflation.

    Returns the point estimate. The caller supplies `population_weight_total` because it is
    known from the census and must not be estimated.
    """
    total = 0.0
    for st in strata:
        N, n = st["N"], st["n"]
        assert 0 < n <= N, f"bad stratum {st}"
        total += (N / n) * st["weight_hits"]
    return total / population_weight_total


def _self_test_ht():
    # A stratum where weight and outcome are perfectly correlated: the naive rate-weighted
    # estimator gets this badly wrong and HT gets it right.
    #   population: 4 URLs, chunks 100, 1, 1, 1; only the 100-chunk one resolves.
    #   truth = 100 / 103 = 0.9709
    #   sample the 100-chunk URL and one 1-chunk URL: n=2, N=4
    #   HT numerator = (4/2) * (100*1 + 1*0) = 200 ; over 103 -> 1.94, clipped by design
    # HT is unbiased in expectation, not per-draw, so test the EXPECTATION over all draws.
    from itertools import combinations
    chunks = [100, 1, 1, 1]
    y = [1, 0, 0, 0]
    truth = sum(c * v for c, v in zip(chunks, y)) / sum(chunks)
    est = []
    for idx in combinations(range(4), 2):
        wh = sum(chunks[i] * y[i] for i in idx)
        est.append(horvitz_thompson_ratio([{"N": 4, "n": 2, "weight_hits": wh, "W": sum(chunks)}], sum(chunks)))
    mean_ht = sum(est) / len(est)
    # the naive rate-weighted estimator, same draws
    naive = []
    for idx in combinations(range(4), 2):
        naive.append(sum(y[i] for i in idx) / 2)
    mean_naive = sum(naive) / len(naive)
    print(f"  truth            {truth:.4f}")
    print(f"  E[HT]            {mean_ht:.4f}   (unbiased)")
    print(f"  E[naive rate]    {mean_naive:.4f}   (biased: it ignores that the winner carries 100 chunks)")
    assert abs(mean_ht - truth) < 1e-9, "HT must be unbiased for the ratio of totals"
    assert abs(mean_naive - truth) > 0.5, "the naive estimator should be visibly wrong here"

    # A census must reproduce the exact value.
    exact = horvitz_thompson_ratio(
        [{"N": 4, "n": 4, "weight_hits": sum(c * v for c, v in zip(chunks, y)), "W": sum(chunks)}],
        sum(chunks))
    assert abs(exact - truth) < 1e-12, "a census must be exact"
    print(f"  census           {exact:.4f}   (exact, no inflation)")


def hajek_ratio(strata):
    """Hajek ratio estimate: HT numerator over the HT-ESTIMATED denominator.

    Horvitz-Thompson divided by the KNOWN population total is unbiased for the total but is
    not bounded: in one sample it can exceed 1, and on this audit's chunk-weighted
    reachability it returned 1.0047. That is not a coding error, it is what an HT ratio does
    when the sampled units' weights happen to over-represent the stratum -- and it is a signal
    that the sample is too small or too unbalanced for a weighted estimate at that resolution.

    Hajek divides by the estimated denominator instead:

        p_hat = sum_i (w_i y_i / pi_i) / sum_i (w_i / pi_i)

    which is bounded in [0, 1] and consistent, at the price of a small bias. Both are reported
    so a reader can see the instability rather than be handed whichever looked better.

    Each stratum needs `N`, `n`, `weight_hits` (sum of w_i*y_i over sampled units) and
    `weight_total` (sum of w_i over sampled units).
    """
    num = den = 0.0
    for st in strata:
        f = st["N"] / st["n"]
        num += f * st["weight_hits"]
        den += f * st["weight_total"]
    return num / den if den else None
