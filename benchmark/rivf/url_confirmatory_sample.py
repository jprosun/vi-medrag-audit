"""Freeze a confirmatory, host-stratified, chunk-PPS sample of source URLs.

WHY A SECOND SAMPLE. The first pass mixed two designs. 289 URLs were frozen before any
request; 78 more were added afterwards, once the failures had been seen to cluster by host.
That top-up is an adaptive design chosen in response to outcomes, so it is exploratory, and
blending it into one "367 URLs, frozen before any request" was wrong. This file draws a clean
confirmatory sample and freezes it before a single request is made.

WHY PPS BY CHUNK COUNT. The estimand for the paper is chunk-weighted: of the corpus mass that
carries a locator, how much of it carries one that works. Under equal-probability sampling the
Horvitz-Thompson estimator of that quantity was unstable to the point of returning 1.0047 --
a probability above one -- because a URL standing behind 300 chunks and one standing behind 1
entered with the same inclusion probability but wildly different weights.

Sampling with probability proportional to chunk count fixes that at the design stage rather
than patching it in the estimator: with pi_i proportional to c_i, the ratio c_i / pi_i is
constant, and the HT numerator stops being dominated by whichever heavy URL happened to be
drawn. This is the textbook reason to use PPS, and it is why the right response to the earlier
instability is a better design rather than a better formula.

DESIGN
  * Stratify by HOST, because the observed failures are host-level and near-total.
  * Allocate across hosts proportional to host chunk mass, floor 5, cap 25, so a small
    Vietnamese stratum is represented and one large English host cannot dominate.
  * Within a host, systematic PPS by chunk count with a random start -- exact inclusion
    probabilities, recorded per URL so the estimator does not have to assume them.
  * Draw ONLY from URLs never probed, so this sample is independent of everything the
    exploratory pass saw.
  * A host whose allocation reaches its remaining population is a census; recorded as such.

    python benchmark/rivf/url_confirmatory_sample.py
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[2]
POP = REPO / "benchmark/rivf/url_population_v4.json"
PROBED = REPO / "benchmark/rivf/url_audit_probed_v1.jsonl"
OUT = REPO / "benchmark/rivf/url_confirmatory_sample_v1.json"

SEED = 20260908
TARGET = 250
PER_HOST_MIN, PER_HOST_MAX = 5, 25


def systematic_pps(units, n, rng):
    """Systematic PPS by weight; returns (unit, inclusion_probability) pairs.

    Inclusion probability for unit i is n * c_i / C, capped at 1. Units heavy enough to be
    certain are removed first and taken with pi = 1 -- the standard treatment, and it keeps
    every pi_i exactly known rather than nominally proportional.
    """
    units = sorted(units, key=lambda u: u["url"])
    certain: list = []
    rest = list(units)
    while rest:
        C = sum(u["chunks"] for u in rest)
        k = n - len(certain)
        if k <= 0 or C == 0:
            break
        over = [u for u in rest if (k * u["chunks"] / C) >= 1.0]
        if not over:
            break
        certain.extend(over)
        keep = {u["url"] for u in over}
        rest = [u for u in rest if u["url"] not in keep]

    picked = [(u, 1.0) for u in certain]
    k = n - len(certain)
    if k > 0 and rest:
        C = sum(u["chunks"] for u in rest)
        if C > 0:
            step = C / k
            targets = [rng.uniform(0, step) + i * step for i in range(k)]
            cum = 0.0
            j = 0
            for u in rest:
                cum += u["chunks"]
                while j < k and targets[j] <= cum:
                    picked.append((u, min(1.0, k * u["chunks"] / C)))
                    j += 1
    return picked


def main() -> int:
    pop = json.loads(POP.read_text(encoding="utf-8"))
    already = set()
    if PROBED.exists():
        for line in PROBED.open(encoding="utf-8"):
            if line.strip():
                already.add(json.loads(line)["url"])

    by_host: defaultdict[str, list] = defaultdict(list)
    for u in pop["urls"]:
        if u["url"] not in already:
            by_host[urlparse(u["url"]).netloc].append(u)

    mass = {h: sum(u["chunks"] for u in v) for h, v in by_host.items()}
    total_mass = sum(mass.values())
    alloc = {}
    for h, v in by_host.items():
        want = round(TARGET * mass[h] / total_mass) if total_mass else 0
        alloc[h] = max(PER_HOST_MIN, min(PER_HOST_MAX, want, len(v)))

    rng = random.Random(SEED)
    rows = []
    for h in sorted(alloc):
        n = alloc[h]
        pool = by_host[h]
        is_census = n >= len(pool)
        chosen = [(u, 1.0) for u in pool] if is_census else systematic_pps(pool, n, rng)
        for u, pi in chosen:
            rows.append(
                {
                    "url": u["url"],
                    "host": h,
                    "granularity": u["granularity"],
                    "source_id": u["source_id"],
                    "chunks": u["chunks"],
                    "titles": u["titles"],
                    "inclusion_probability": round(pi, 8),
                    "host_population_urls": len(pool),
                    "host_population_chunks": mass[h],
                    "host_allocation": n,
                    "is_census_of_the_unprobed_remainder": is_census,
                }
            )
    rows.sort(key=lambda r: r["url"])

    out = {
        "what_this_is": (
            "A CONFIRMATORY sample: host-stratified, chunk-PPS, drawn only from URLs never "
            "probed, frozen before any request. It exists because the first pass blended a "
            "frozen 289 with an adaptive 78 chosen after seeing outcomes, and because "
            "equal-probability sampling made the chunk-weighted estimator unstable."
        ),
        "provenance": {
            "population": str(POP.relative_to(REPO)).replace("\\", "/"),
            "population_sha256": hashlib.sha256(POP.read_bytes()).hexdigest(),
            "excluded_because_already_probed": len(already),
            "seed": SEED,
            "target": TARGET,
            "per_host_min_max": [PER_HOST_MIN, PER_HOST_MAX],
            "frozen_before_any_request": True,
            "design": (
                "Stratified by host; allocation proportional to host chunk mass with a floor "
                "and a cap; within host, systematic PPS by chunk count with a random start, "
                "certainty units removed first. Every inclusion probability is recorded per "
                "URL, so the estimator need not assume the design."
            ),
            "why_pps": (
                "The estimand is chunk-weighted. Under equal-probability sampling the HT "
                "estimator returned 1.0047 on the exploratory data -- a probability above "
                "one -- because weight and inclusion probability were unrelated. With pi_i "
                "proportional to c_i the ratio c_i/pi_i is constant, removing that "
                "instability at the design stage rather than patching it in the formula."
            ),
        },
        "n": len(rows),
        "hosts": len(alloc),
        "allocation": alloc,
        "urls": rows,
    }
    text = json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}")
    print(f"  {len(rows)} URLs across {len(alloc)} hosts, drawn from "
          f"{sum(len(v) for v in by_host.values()):,} never-probed URLs")
    print(f"  sha256 {hashlib.sha256(text.encode()).hexdigest()[:32]}...")
    cert = sum(1 for r in rows if r["inclusion_probability"] >= 1.0)
    print(f"  {cert} certainty units (pi = 1), {len(rows) - cert} by systematic PPS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
