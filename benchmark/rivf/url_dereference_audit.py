"""Dereference the stored source URLs and report what a reader following one actually gets.

WHY. The paper's promise is a citation a reader can open, but every number in Section IV
measures the stored FIELD: present or absent, article-shaped or issue-shaped. A locator that
404s, or that redirects to a journal's front page, is exactly as useless to a reader as an
empty field, and the census cannot tell them apart. Until this ran, "citable" in this
repository meant "a non-empty string is present", and the paper was careful to say so -- but
being careful about a gap is not the same as closing it.

THREE QUANTITIES, REPORTED SEPARATELY, because collapsing them is the error the paper is
about:

  1. stored locator availability -- does the record carry a URL at all (the census; here
     only for context)
  2. HTTP reachability            -- does that URL answer, and with what
  3. destination accuracy         -- does the page you land on correspond to the CITED
                                     ARTICLE, or merely to the journal, or to something else

DESIGN. The unit is the distinct URL, not the chunk: a reader follows a URL, and sampling
chunks would over-weight whichever articles the ingester happened to split into many pieces.
The issue-level stratum is a CENSUS -- all 143 of its distinct URLs -- which is possible only
because 79,678 chunks share just 143 destinations, itself a finding worth reporting. The
article-level stratum is sampled, allocated across sources so that a small Vietnamese
stratum is not drowned out by a large English one.

POLITENESS. robots.txt is honoured per host; requests to one host are spaced by at least
MIN_INTERVAL seconds and hosts are visited round-robin so no server sees a burst. Roughly 300
requests total, one pass, no retries beyond one. Nothing is downloaded but the response head
and enough body to read a title.

    python benchmark/rivf/url_dereference_audit.py --sample     # freeze the sample
    python benchmark/rivf/url_dereference_audit.py --probe      # do the network pass
    python benchmark/rivf/url_dereference_audit.py --report     # write the artifact
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
import urllib.robotparser
from collections import Counter, defaultdict
from html import unescape
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from survey_ci import clopper_pearson, hajek_ratio, horvitz_thompson_ratio  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
POP = REPO / "benchmark/rivf/url_population_v4.json"
SAMPLE = REPO / "benchmark/rivf/url_audit_sample_v1.json"
PROBED = REPO / "benchmark/rivf/url_audit_probed_v1.jsonl"
OUT = REPO / "benchmark/rivf/url_audit_report_v1.json"
CONF_SAMPLE = REPO / "benchmark/rivf/url_confirmatory_sample_v1.json"
CONF_PROBED = REPO / "benchmark/rivf/url_confirmatory_probed_v1.jsonl"

SEED = 20260907
N_ARTICLE = 160
PER_SOURCE_MIN, PER_SOURCE_MAX = 4, 40

MIN_INTERVAL = 2.0          # seconds between two requests to the SAME host
TIMEOUT = 25
MAX_BODY = 300_000          # enough for <title>; we are not mirroring anyone's content
UA = ("Mozilla/5.0 (compatible; academic-citation-audit/1.0; "
      "one-pass research audit of stored source URLs; low volume, robots.txt honoured)")

_ISSUE_RE = re.compile(r"/issue/(view|archive)/", re.IGNORECASE)
_ARTICLE_RE = re.compile(r"/article/(view|download)/|/pmc/|/books/|doi\.org/", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def granularity(u: str) -> str:
    if not (u or "").strip():
        return "none"
    if _ISSUE_RE.search(u):
        return "issue"
    if _ARTICLE_RE.search(u):
        return "article"
    return "article_or_page"



_PCT_RE = re.compile(r"%[0-9A-Fa-f]{2}")


def unusable_stored_titles(pop_urls) -> tuple[set, dict]:
    """URLs whose stored title cannot identify a document, and why.

    Shared-title detection is per HOST: the same string appearing on two different URLs of one
    site is a navigation label or a breadcrumb, not a document title. On this corpus that rule
    catches 80 URLs sharing "Gii thiu chung Chc nng nhim v" (diacritics stripped) and 20
    sharing "Qld vp signed" (a filename fragment), and leaves genuine journal titles alone --
    tapchiyhocvietnam.vn has 6,412 distinct titles across 6,429 URLs.
    """
    by_host_title: defaultdict[tuple, int] = defaultdict(int)
    for u in pop_urls:
        t = (u["titles"] or [""])[0].strip()
        by_host_title[(urlparse(u["url"]).netloc, t)] += 1

    bad, why = set(), {}
    for u in pop_urls:
        t = (u["titles"] or [""])[0].strip()
        host = urlparse(u["url"]).netloc
        if not t:
            bad.add(u["url"]); why[u["url"]] = "no stored title"
        elif _PCT_RE.search(t):
            bad.add(u["url"]); why[u["url"]] = "percent-encoded filename fragment"
        elif by_host_title[(host, t)] >= 2:
            bad.add(u["url"])
            why[u["url"]] = f"shared by {by_host_title[(host, t)]} URLs on this host: a nav label"
    return bad, why

# ────────────────────────────────────────────────────────────── sampling
def build_sample() -> dict:
    pop = json.loads(POP.read_text(encoding="utf-8"))
    rows = pop["urls"]
    rng = random.Random(SEED)

    issue = sorted([r for r in rows if r["granularity"] == "issue"], key=lambda r: r["url"])
    art = [r for r in rows if r["granularity"] in ("article", "article_or_page")]

    by_src: defaultdict[str, list] = defaultdict(list)
    for r in art:
        by_src[r["source_id"]].append(r)
    for v in by_src.values():
        v.sort(key=lambda r: r["url"])

    total = sum(len(v) for v in by_src.values())
    alloc = {}
    for src, v in by_src.items():
        want = round(N_ARTICLE * len(v) / total)
        alloc[src] = max(PER_SOURCE_MIN, min(PER_SOURCE_MAX, want, len(v)))

    picked = []
    for src in sorted(alloc):
        picked.extend(rng.sample(by_src[src], alloc[src]))
    picked.sort(key=lambda r: r["url"])

    sample = {
        "what_this_is": (
            "The frozen sample for the URL dereference audit. Issue-level is a CENSUS of all "
            "143 distinct issue URLs; article-level is a stratified sample allocated across "
            "sources with a floor, so small Vietnamese strata are represented."
        ),
        "provenance": {
            "population": str(POP.relative_to(REPO)).replace("\\", "/"),
            "population_sha256": hashlib.sha256(POP.read_bytes()).hexdigest(),
            "seed": SEED,
            "n_article_target": N_ARTICLE,
            "per_source_min_max": [PER_SOURCE_MIN, PER_SOURCE_MAX],
            "frozen_before_any_request": True,
        },
        "issue_census": {"n": len(issue), "of_population": len(issue), "is_census": True},
        "article_sample": {"n": len(picked), "of_population": total, "allocation": alloc},
        "urls": issue + picked,
    }
    SAMPLE.write_text(json.dumps(sample, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {SAMPLE.relative_to(REPO)}")
    print(f"  issue census   {len(issue)} of {len(issue)} (all of them)")
    print(f"  article sample {len(picked)} of {total}")
    print(f"  TOTAL to probe {len(issue) + len(picked)}")
    return sample


# ────────────────────────────────────────────────────────────── probing
class Politeness:
    def __init__(self) -> None:
        self.last: dict[str, float] = {}
        self.robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool | None:
        host = urlparse(url).netloc
        if host not in self.robots:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(f"{urlparse(url).scheme}://{host}/robots.txt")
            try:
                rp.read()
                self.robots[host] = rp
            except Exception:
                self.robots[host] = None      # unreadable robots.txt: proceed, but record it
            time.sleep(1.0)
        rp = self.robots[host]
        if rp is None:
            return None
        try:
            return rp.can_fetch(UA, url)
        except Exception:
            return None

    def wait(self, url: str) -> None:
        host = urlparse(url).netloc
        prev = self.last.get(host)
        if prev is not None:
            gap = MIN_INTERVAL - (time.time() - prev)
            if gap > 0:
                time.sleep(gap)
        self.last[host] = time.time()


def read_title(body: bytes, charset: str | None) -> str:
    for enc in (charset, "utf-8", "latin-1"):
        if not enc:
            continue
        try:
            text = body.decode(enc, errors="replace")
            break
        except Exception:
            continue
    else:
        return ""
    m = _TITLE_RE.search(text)
    if not m:
        return ""
    return " ".join(unescape(_TAG_RE.sub(" ", m.group(1))).split())[:300]


class Tracker(urllib.request.HTTPRedirectHandler):
    """Records the redirect chain rather than silently following it."""

    def __init__(self) -> None:
        self.chain: list[dict] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.chain.append({"from": req.full_url, "status": code, "to": newurl})
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def probe(url: str, pol: Politeness) -> dict:
    rec: dict = {"url": url, "requested_at_host": urlparse(url).netloc}
    rec["robots_allowed"] = pol.allowed(url)
    if rec["robots_allowed"] is False:
        rec["outcome"] = "skipped_by_robots"
        return rec
    pol.wait(url)
    tracker = Tracker()
    opener = urllib.request.build_opener(tracker)
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "gzip",
            "Accept-Language": "vi,en;q=0.8",
        })
        with opener.open(req, timeout=TIMEOUT) as r:
            raw = r.read(MAX_BODY)
            if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
                try:
                    raw = gzip.decompress(raw)
                except Exception:
                    pass
            rec.update({
                "status": r.status,
                "final_url": r.url,
                "content_type": r.headers.get("Content-Type", ""),
                "page_title": read_title(raw, r.headers.get_content_charset()),
                "outcome": "ok",
            })
    except urllib.error.HTTPError as e:
        rec.update({"status": e.code, "final_url": e.url if hasattr(e, "url") else url,
                    "outcome": "http_error", "error": f"HTTP {e.code} {e.reason}"})
    except urllib.error.URLError as e:
        rec.update({"status": None, "final_url": None, "outcome": "unreachable",
                    "error": f"{type(e.reason).__name__}: {e.reason}"})
    except Exception as e:  # timeouts, malformed responses, TLS failures
        rec.update({"status": None, "final_url": None, "outcome": "error",
                    "error": f"{type(e).__name__}: {e}"})
    rec["elapsed_s"] = round(time.time() - t0, 2)
    rec["redirects"] = tracker.chain
    return rec


def topup_urls(per_host: int) -> list[str]:
    """Bring every host up to `per_host` probes.

    The first pass allocated by SOURCE, which is the wrong axis: the failures are not spread
    across a source's URLs, they are whole HOSTS that no longer serve the paths MedQuAD
    recorded. rarediseases.info.nih.gov answered 404 nineteen times out of nineteen. Under a
    source-allocated sample that host's 2,684 URLs are represented by whatever share of 40
    the draw happened to give it; under a host-allocated one, eight probes settle whether the
    host serves anything at all, and 2,684 URLs inherit that verdict with far less
    extrapolation. So this tops up rather than re-draws: the frozen first pass is kept, and
    every host reaches a floor.
    """
    pop = json.loads(POP.read_text(encoding="utf-8"))
    rng = random.Random(SEED + 1)
    done: dict[str, int] = defaultdict(int)
    seen: set[str] = set()
    if PROBED.exists():
        for line in PROBED.open(encoding="utf-8"):
            if line.strip():
                rec = json.loads(line)
                seen.add(rec["url"])
                done[urlparse(rec["url"]).netloc] += 1

    by_host: defaultdict[str, list] = defaultdict(list)
    for r in pop["urls"]:
        if r["url"] not in seen:
            by_host[urlparse(r["url"]).netloc].append(r["url"])

    extra: list[str] = []
    for host in sorted(by_host):
        need = per_host - done.get(host, 0)
        if need > 0:
            pool = sorted(by_host[host])
            extra.extend(rng.sample(pool, min(need, len(pool))))
    return extra


def run_probe(extra: list[str] | None = None, log: Path | None = None) -> None:
    if extra is not None:
        todo = extra
    else:
        sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
        todo = [r["url"] for r in sample["urls"]]

    log = log or PROBED
    done = set()
    if log.exists():
        for line in log.open(encoding="utf-8"):
            if line.strip():
                done.add(json.loads(line)["url"])
        print(f"resuming: {len(done)} already probed")

    # Round-robin by host so no server sees a burst even before the interval kicks in.
    by_host: defaultdict[str, list[str]] = defaultdict(list)
    for u in todo:
        if u not in done:
            by_host[urlparse(u).netloc].append(u)
    order: list[str] = []
    while any(by_host.values()):
        for h in sorted(by_host):
            if by_host[h]:
                order.append(by_host[h].pop(0))

    pol = Politeness()
    with log.open("a", encoding="utf-8") as f:
        for i, u in enumerate(order, 1):
            rec = probe(u, pol)
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            if i % 20 == 0 or i == len(order):
                print(f"  probed {i}/{len(order)}", flush=True)
    print(f"wrote {log.relative_to(REPO)}")


# ────────────────────────────────────────────────────────────── reporting
_WORD = re.compile(r"[0-9\w]+", re.UNICODE)


def tokens(s: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(s or "") if len(w) > 2}


def title_match(stored: list[str], page: str) -> tuple[str, float]:
    """Does the page we landed on correspond to the cited article?

    Containment, not Jaccard: a journal page title is usually "ARTICLE TITLE | Journal Name",
    so the stored title is a SUBSET of the page title and Jaccard would punish that. We ask
    what fraction of the stored title's words appear on the page.
    """
    p = tokens(page)
    if not p:
        return ("no_page_title", 0.0)
    best = 0.0
    for t in stored or []:
        st = tokens(t)
        if st:
            best = max(best, len(st & p) / len(st))
    if not stored:
        return ("no_stored_title", 0.0)
    if best >= 0.70:
        return ("article_confirmed", round(best, 3))
    if best >= 0.35:
        return ("partial", round(best, 3))
    return ("mismatch", round(best, 3))


def report() -> int:
    """Three quantities, kept apart, estimated by Horvitz-Thompson over per-URL weights.

    Denominators, stated because they are the whole argument:

      selected     URLs chosen for probing
      measurable   selected MINUS the ones robots.txt told us not to fetch
      reached      measurable that answered 2xx
      destination  assessed only on `reached`
    """
    pop = json.loads(POP.read_text(encoding="utf-8"))
    meta = {r["url"]: r for r in pop["urls"]}
    recs = [json.loads(l) for l in PROBED.open(encoding="utf-8") if l.strip()]
    unusable, _ = unusable_stored_titles(pop["urls"])

    # Which URLs were in the sample frozen BEFORE any request, and which were added after
    # seeing that the failures clustered by host. The distinction is not cosmetic: the top-up
    # is an adaptive design chosen in response to observed outcomes, so it is exploratory and
    # is reported apart from the primary sample rather than blended into it.
    frozen = {r["url"] for r in json.loads(SAMPLE.read_text(encoding="utf-8"))["urls"]}

    pop_by_host: defaultdict[str, dict] = defaultdict(lambda: {"urls": 0, "chunks": 0})
    for r in pop["urls"]:
        h = pop_by_host[urlparse(r["url"]).netloc]
        h["urls"] += 1
        h["chunks"] += r["chunks"]

    OUTCOMES = ("reached", "not_issue_index", "cited_document")

    def score(rec, m):
        """The three yes/no outcomes for one probe, and whether each is even askable."""
        out, st = rec.get("outcome"), rec.get("status")
        reached = out == "ok" and isinstance(st, int) and 200 <= st < 300
        y = {"reached": 1 if reached else 0}
        if reached:
            fg = granularity(rec.get("final_url") or "")
            y["not_issue_index"] = 0 if fg == "issue" else 1
            if rec["url"] in unusable:
                y["cited_document"] = None          # the stored title cannot name a document
            else:
                v, _ = title_match(m.get("titles") or [], rec.get("page_title") or "")
                y["cited_document"] = 1 if v == "article_confirmed" else 0
        else:
            y["not_issue_index"] = None
            y["cited_document"] = None
        return y, reached

    def build(subset_urls):
        """Per-host tallies over a subset of the probe log, carrying REAL per-URL weights."""
        hosts: defaultdict[str, dict] = defaultdict(lambda: {
            "selected": 0, "robots_blocked": 0, "measurable": 0, "reached": 0,
            "http_error": 0, "unreachable": 0, "status": Counter(),
            "title_usable": 0, "title_unusable": 0, "landed_issue_index": 0,
            "hits_urls": {k: 0 for k in OUTCOMES},
            "hits_chunks": {k: 0 for k in OUTCOMES},
            "askable": {k: 0 for k in OUTCOMES},
            "askable_chunks": {k: 0 for k in OUTCOMES},
        })
        for rec in recs:
            if rec["url"] not in subset_urls:
                continue
            m = meta.get(rec["url"])
            if not m:
                continue
            h = hosts[urlparse(rec["url"]).netloc]
            c = m["chunks"]
            h["selected"] += 1
            out, st = rec.get("outcome"), rec.get("status")
            if st is not None:
                h["status"][str(st)] += 1
            if out == "skipped_by_robots":
                h["robots_blocked"] += 1
                continue
            h["measurable"] += 1
            y, reached = score(rec, m)
            if reached:
                h["reached"] += 1
                if granularity(rec.get("final_url") or "") == "issue":
                    h["landed_issue_index"] += 1
                if rec["url"] in unusable:
                    h["title_unusable"] += 1
                else:
                    h["title_usable"] += 1
            elif out == "http_error":
                h["http_error"] += 1
            else:
                h["unreachable"] += 1
            for k in OUTCOMES:
                if y[k] is None:
                    continue
                h["askable"][k] += 1
                h["askable_chunks"][k] += c
                h["hits_urls"][k] += y[k]
                h["hits_chunks"][k] += c * y[k]
        return hosts

    def estimate(hosts, key, weight):
        """Horvitz-Thompson over the hosts where `key` was askable at all."""
        strata, excluded = [], []
        W_pop = 0.0
        for host, h in hosts.items():
            n = h["askable"][key]
            P = pop_by_host[host]
            if not n:
                excluded.append(host)
                continue
            W_h = P["chunks"] if weight == "chunks" else P["urls"]
            W_pop += W_h
            strata.append({
                "host": host, "N": P["urls"], "n": n, "W": W_h,
                "weight_hits": h["hits_chunks"][key] if weight == "chunks" else h["hits_urls"][key],
                "weight_total": h["askable_chunks"][key] if weight == "chunks" else n,
                "k": h["hits_urls"][key],
                "is_census": h["selected"] >= P["urls"],
            })
        if not strata:
            return None
        point_ht = horvitz_thompson_ratio(strata, W_pop)
        point_hajek = hajek_ratio(strata)

        def env(alpha):
            lo = hi = 0.0
            for st in strata:
                w = st["W"] / W_pop
                if st["is_census"]:
                    r = st["k"] / st["n"]
                    lo += w * r; hi += w * r
                else:
                    a, b = clopper_pearson(st["k"], st["n"], alpha)
                    lo += w * a; hi += w * b
            return [round(lo, 4), round(hi, 4)]

        H = len(strata)
        return {
            "point": round(point_hajek, 4),
            "point_hajek_bounded": round(point_hajek, 4),
            "point_horvitz_thompson": round(point_ht, 4),
            "the_two_estimators_disagree_and_that_matters": (
                "Hajek divides by the ESTIMATED denominator and is bounded in [0,1]; HT "
                "divides by the known population total, is unbiased for the total, and is NOT "
                "bounded -- on chunk-weighted reachability it returned 1.0047, a probability "
                "above one. That is not a bug: it is what an HT ratio does when the sampled "
                "units' weights over-represent their stratum, and it is direct evidence that "
                "this sample is too small and too unbalanced to carry a chunk-weighted "
                "estimate. The headline is Hajek; HT is shown so the instability is visible."
            ),
            "estimator": (
                "Horvitz-Thompson ratio of totals; pi_i = n_h/N_h inside each host, census "
                "hosts pi=1 and contribute exactly. Replaces an earlier estimator that used "
                "each host's UNWEIGHTED sampled rate under chunk weights, which is unbiased "
                "only if chunk count and outcome are independent inside a host -- they are "
                "not, and the error was ~1.3 points in the optimistic direction."
            ),
            "marginal_projection": env(0.05),
            "marginal_projection_carries_no_joint_coverage": (
                "Per-host Clopper-Pearson bounds combined under population weights. A "
                "projection of marginal intervals, NOT a simultaneous interval, and NOT a "
                "confidence interval for the weighted total. An earlier version called this "
                "'valid but conservative'; the two descriptions are incompatible."
            ),
            "bonferroni_joint": env(0.05 / max(H, 1)),
            "bonferroni_note": f"alpha/{H} per host: conservative, and does carry >=95 % joint coverage",
            "not_covered_by_either": (
                "Both hold the weight-outcome relationship inside a host fixed, and neither "
                "reflects the adaptive top-up. A design-based variance for a ratio estimator "
                "under this design is not attempted."
            ),
            "weight": weight,
            "hosts": H,
            "hosts_with_nothing_askable": sorted(excluded),
            "population_covered": W_pop,
        }

    primary = build(frozen)
    allp = build({r["url"] for r in recs})
    exploratory_n = len(recs) - sum(h["selected"] for h in primary.values())

    LABEL = {
        "reached": "2_http_reachability",
        "not_issue_index": "3a_final_url_is_not_a_known_issue_index",
        "cited_document": "3b_page_title_matches_the_stored_title",
    }
    quantities = {}
    for key, name in LABEL.items():
        for weight in ("chunks", "distinct_url"):
            w = "chunks" if weight == "chunks" else "urls"
            quantities[f"{name}_by_{weight}"] = {
                "primary_frozen_sample": estimate(primary, key, w),
                "all_probes_including_adaptive_topup": estimate(allp, key, w),
            }

    host_rows = []
    for host, h in sorted(allp.items()):
        P = pop_by_host[host]
        host_rows.append({
            "host": host, "population_urls": P["urls"], "population_chunks": P["chunks"],
            "selected": h["selected"], "robots_blocked_unmeasurable": h["robots_blocked"],
            "measurable": h["measurable"], "reached_2xx": h["reached"],
            "http_error": h["http_error"], "unreachable": h["unreachable"],
            "status_codes": dict(h["status"]),
            "landed_issue_index": h["landed_issue_index"],
            "stored_title_usable": h["title_usable"],
            "stored_title_unusable": h["title_unusable"],
            "is_census": h["selected"] >= P["urls"],
            "reachability": round(h["hits_urls"]["reached"] / h["measurable"], 4) if h["measurable"] else None,
            "chunks_behind_sampled_urls": h["askable_chunks"]["reached"],
        })

    robots_urls = sum(r["population_urls"] for r in host_rows if r["measurable"] == 0)
    robots_chunks = sum(r["population_chunks"] for r in host_rows if r["measurable"] == 0)

    out = {
        "what_this_is": (
            "What a reader following a stored source URL actually gets. Three quantities kept "
            "apart because collapsing them is the error this paper is about."
        ),
        "READ_THIS_FIRST": (
            "The composite 'share of the corpus reachable to a document page' has been "
            "WITHDRAWN from the paper's abstract and contributions. It rests on quantity 3a, "
            "which proves only that the final URL did not match a known issue-index pattern -- "
            "a homepage, a search page or a soft 404 all pass it -- and on an adaptively "
            "topped-up sample. The result that stands without any of that machinery is the "
            "ISSUE CENSUS below."
        ),
        "provenance": {
            "population": str(POP.relative_to(REPO)).replace("\\", "/"),
            "population_sha256": hashlib.sha256(POP.read_bytes()).hexdigest(),
            "sample": str(SAMPLE.relative_to(REPO)).replace("\\", "/"),
            "sample_sha256": hashlib.sha256(SAMPLE.read_bytes()).hexdigest(),
            "probe_log": str(PROBED.relative_to(REPO)).replace("\\", "/"),
            "primary_sample": {
                "n": len(frozen),
                "frozen_before_any_request": True,
                "design": "143 issue URLs censused + 146 article-level allocated per SOURCE",
            },
            "adaptive_topup": {
                "n": exploratory_n,
                "frozen_before_any_request": False,
                "why": (
                    "Added AFTER observing that failures clustered by host, to bring every "
                    "host to 8 probes. This is an adaptive design chosen in response to "
                    "outcomes, so it is EXPLORATORY. Every quantity is reported on the "
                    "primary frozen sample and on all probes, separately, and the two must "
                    "be read as confirmatory and exploratory respectively."
                ),
            },
            "politeness": {
                "robots_txt": "honoured per host; a disallowed URL is skipped, never fetched",
                "min_seconds_between_requests_to_one_host": MIN_INTERVAL,
                "order": "round-robin across hosts",
                "timeout_s": TIMEOUT, "retries": 0,
            },
            "what_3a_does_and_does_not_prove": (
                "granularity() recognises /issue/(view|archive)/ and a few article patterns. "
                "Every other 2xx URL -- including a homepage, a search page, or a soft 404 "
                "served with status 200 -- falls through to 'article_or_page' and counts as "
                "NOT an issue index. So 3a proves only: the final URL did not match a known "
                "issue-index pattern. It does NOT establish that the page is a document page, "
                "and it certainly does not establish WHICH document. Page type has not been "
                "labelled by a person."
            ),
        },
        "1_stored_locator_availability": {
            "chunks_by_granularity": pop["chunks_by_granularity"],
            "distinct_urls_by_granularity": pop["distinct_urls_by_granularity"],
        },
        "THE_RESULT_THAT_NEEDS_NO_ESTIMATOR": {
            "what": (
                "The issue-level stratum is a CENSUS: all 143 of its distinct URLs were "
                "probed, so there is no sampling, no weighting and no inference here."
            ),
            "distinct_issue_urls": 143,
            "chunks_behind_them": pop["chunks_by_granularity"]["issue"],
            "chunks_per_url": round(pop["chunks_by_granularity"]["issue"] / 143, 1),
            "answered_2xx": sum(r["reached_2xx"] for r in host_rows if r["landed_issue_index"]),
            "landed_on_an_issue_index": sum(r["landed_issue_index"] for r in host_rows),
            "statement_the_census_supports": (
                "142 of the 143 distinct issue-level URLs answer and land on an issue index, "
                "which does not uniquely identify the cited article. Note the careful wording: "
                "an issue index lists many articles, one of which may well be the cited one, "
                "so 'names a different article' would be wrong."
            ),
        },
        **quantities,
        "0_stored_title_quality": {
            "urls_whose_stored_title_cannot_identify_a_document": len(unusable),
            "of_distinct_urls": pop["distinct_urls"],
            "share": round(len(unusable) / pop["distinct_urls"], 4),
            "rule": "empty, percent-encoded, or shared by >=2 distinct URLs on the same host",
            "MEASURED_RECALL_OF_THIS_RULE": (
                "0.20. The author's 40-item page-type sheet found 5 pages whose stored title "
                "cannot identify the document; this rule flags 1 of them, and flags 2 pages "
                "the author could read fine. It misses bare dates ('(March 2009)'), "
                "OCR-mangled headers, diacritic-stripped filenames, and breadcrumbs unique per "
                "URL. So the share above is a FLOOR: the sheet's own rate among document pages "
                "is 5 of 29, about 17 %. The rule was deliberately NOT widened to fit the five "
                "that defeated it -- tuning it on the items that beat it would make its next "
                "number meaningless."
            ),
            "why_separate": (
                "A page reached correctly whose stored title is a breadcrumb is an INGESTION "
                "defect, not a traceability failure. 3b is therefore a LOWER BOUND, and the "
                "rule was not widened to fit the hosts that failed."
            ),
        },
        "unmeasurable_by_robots_txt": {
            "distinct_urls": robots_urls, "chunks": robots_chunks,
            "note": "Excluded from every denominator; not counted as reachable or as broken.",
        },
        "by_host": host_rows,
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"wrote {OUT.relative_to(REPO)}")
    print(f"  primary frozen sample {len(frozen)} | adaptive top-up {exploratory_n} | total {len(recs)}")
    cen = out["THE_RESULT_THAT_NEEDS_NO_ESTIMATOR"]
    print(f"\n  CENSUS, no estimator: {cen['landed_on_an_issue_index']} of {cen['distinct_issue_urls']} "
          f"issue URLs land on an issue index ({cen['chunks_behind_them']:,} chunks)")
    print("\n  estimated quantities -- primary (frozen) vs all probes (adaptive):")
    for k, v in quantities.items():
        pr, al = v["primary_frozen_sample"], v["all_probes_including_adaptive_topup"]
        if pr and al:
            print(f"    {k}")
            print(f"       primary {pr['point']:<8} marginal {pr['marginal_projection']}  bonferroni {pr['bonferroni_joint']}")
            print(f"       all     {al['point']:<8} marginal {al['marginal_projection']}  bonferroni {al['bonferroni_joint']}")
    print(f"\n  robots.txt unmeasurable: {robots_urls:,} URLs / {robots_chunks:,} chunks")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--confirmatory", action="store_true",
                    help="probe the frozen confirmatory host-stratified PPS sample into its "
                         "own log, keeping it independent of the exploratory pass")
    ap.add_argument("--topup", type=int, default=0,
                    help="bring every host up to N probes; the failures are host-level, so "
                         "this is the axis that matters")
    a = ap.parse_args()
    if a.sample:
        build_sample()
    if a.confirmatory:
        conf = json.loads(CONF_SAMPLE.read_text(encoding="utf-8"))
        print(f"confirmatory sample: {conf['n']} URLs across {conf['hosts']} hosts, frozen")
        run_probe([r["url"] for r in conf["urls"]], log=CONF_PROBED)
    if a.topup:
        extra = topup_urls(a.topup)
        print(f"top-up: {len(extra)} more URLs so every host reaches {a.topup} probes")
        if extra:
            run_probe(extra)
    if a.probe:
        run_probe()
    if a.report:
        return report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
