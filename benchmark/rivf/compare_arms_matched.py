"""The between-arm contrast, with the instrument finally held fixed.

WHY THE OLD CONTRAST DOES NOT COUNT. The paper compared support 0.962 against 0.968 and
responsiveness 0.028 against 0.022 and reported no evidence of a difference. Two things were
not held between the arms, both recovered after the fact:

  MODEL     shipped entailment was served claude-opus-5, URL-first entailment
            claude-fable-5-1 (judge_model_provenance_v1.json). The support pair crossed two
            models. The responsiveness pair did not.

  CODEBOOK  the URL-first entailment codebook is 2591 characters against the shipped arm's
            3876, dropping the operational reading of `supported`, the instruction that kept
            `overstated` live, and the justification for `unintelligible`. The shipped
            relevance codebook separately told its judge that support was "already established
            at 96.8% of cases".

An unmeasured noise source does not make a null safe; it leaves it unfalsified. So
judging/matched-arm-rejudge.js re-judged the URL-first arm under the shipped arm's exact
configuration -- shipped codebook byte for byte, model pinned, the original adjudicator prompt
with confidence and rationale, batch size 28 -- and re-adjudicated the shipped arm's own
disagreements under that same prompt. This script computes the contrast from those two matched
label sets and prints the confounded one beside it.

WHY AN INTERVAL ON THE DIFFERENCE. "Both pairs of intervals overlap" is a weak argument: two
overlapping intervals can still admit a large difference, and the reader cannot tell how large
from the two intervals alone. A bound on the arm effect requires an interval on the difference.

WHICH INTERVAL, AND WHY THE FIRST ONE WAS WRONG. The first version of this file used
Newcombe's hybrid score, which is for two INDEPENDENT binomial proportions. Neither
independence assumption holds here: both arms answer the SAME 134 pre-registered questions
(paired), and claims are nested in questions (clustered). The paper already had the right
method two sections earlier -- Table II's CIs are a percentile cluster bootstrap over
questions -- and this file did not use it. It does now, and keeps Newcombe beside it to show
what the wrong assumption costs.

    python benchmark/rivf/compare_arms_matched.py --matched <workflow-output.json>
    python benchmark/rivf/compare_arms_matched.py --check
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "benchmark/rivf/arm_contrast_matched_v1.json"

PINNED_SHIPPED = REPO / "benchmark/rivf/judge_rerun_pinned_v1.json"
KEYS_SHIPPED = {
    "entailment": REPO / "benchmark/rivf/entailment_key_v1.json",
    "relevance": REPO / "benchmark/rivf/relevance_model_key_v1.json",
}
KEYS_URLFIRST = {
    "entailment": REPO / "benchmark/rivf/entailment_key_urlfirst_v1.json",
    "relevance": REPO / "benchmark/rivf/relevance_model_key_urlfirst_v1.json",
}
# the original, confounded contrast, for the side-by-side
ORIGINAL = {
    "entailment": (REPO / "benchmark/rivf/entailment_judgements_v1.json",
                   REPO / "benchmark/rivf/entailment_judgements_urlfirst_v1.json"),
    "relevance": (REPO / "benchmark/rivf/relevance_model_judgements_v1.json",
                  REPO / "benchmark/rivf/relevance_model_judgements_urlfirst_v1.json"),
}
POSITIVE = {"entailment": "supported", "relevance": "relevant"}
Z = 1.959963984540054  # two-sided 95%


def resolve(blob: dict, override: dict | None = None) -> dict:
    """Final label per item; `override` replaces the adjudication for the items it names."""
    a = {j["item_id"]: j["label"] for j in blob.get("pass_a", [])}
    b = {j["item_id"]: j["label"] for j in blob.get("pass_b", [])}
    adj = {j["item_id"]: j["label"] for j in blob.get("adjudication", [])}
    if override:
        adj.update(override)
    out = {}
    for i in a:
        if i not in b:
            continue
        out[i] = adj.get(i, a[i]) if a[i] != b[i] else a[i]
    return out


def real_ids(key_path: Path, labels: dict) -> list[str]:
    if not key_path.exists():
        return sorted(labels)
    key = json.loads(key_path.read_text(encoding="utf-8")).get("key", {})
    return sorted(i for i in labels
                  if not isinstance(key.get(i), dict) or key[i].get("kind") == "real")


def labels_by_question(key_path: Path, labels: dict, ids) -> dict:
    """query_id -> the labels of that question's real claims. The cluster structure."""
    key = json.loads(key_path.read_text(encoding="utf-8")).get("key", {})
    out: dict[str, list[str]] = {}
    for i in ids:
        q = (key.get(i) or {}).get("query_id")
        assert q, f"no query_id for {i}; the cluster structure would be silently wrong"
        out.setdefault(q, []).append(labels[i])
    return out


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + Z * Z / n
    centre = (p + Z * Z / (2 * n)) / d
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def newcombe(k1: int, n1: int, k2: int, n2: int) -> dict:
    """95% interval for p1 - p2, Newcombe's hybrid score (square-and-add).

    Built from the two Wilson intervals: the lower bound pairs p1's DOWNWARD excursion with
    p2's UPWARD one, and the upper bound the reverse. Pairing them the other way is the classic
    implementation slip, and the symmetry self-test below is what catches it.
    """
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wilson(k1, n1)
    l2, u2 = wilson(k2, n2)
    d = p1 - p2
    lo = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    hi = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return {
        "difference": round(d, 4),
        "ci95": [round(max(-1.0, lo), 4), round(min(1.0, hi), 4)],
        "method": "Newcombe hybrid score (square-and-add) on Wilson intervals",
        "arm_1": {"hits": k1, "n": n1, "rate": round(p1, 4), "wilson": [round(l1, 4), round(u1, 4)]},
        "arm_2": {"hits": k2, "n": n2, "rate": round(p2, 4), "wilson": [round(l2, 4), round(u2, 4)]},
    }


QUESTIONS = REPO / "benchmark/datasets/probe_queries_v2.jsonl"
BOOT_SEED = 20260907      # compare_arms.py's seed, so the paper has one bootstrap convention
BOOT_ALT_SEED = 20260905  # a second seed, reported to show the interval is not seed-fragile
RESAMPLES = 5000


def question_order() -> list[str]:
    """The 134 pre-registered questions, in file order. The resampling unit."""
    return [json.loads(l)["query_id"]
            for l in QUESTIONS.read_text(encoding="utf-8").splitlines() if l.strip()]


def _pooled(sel, by_q, positive):
    num = den = 0
    for q in sel:
        labs = by_q.get(q, ())
        den += len(labs)
        num += sum(1 for x in labs if x == positive)
    return (num / den) if den else None


def paired_question_bootstrap(by_q_1, by_q_2, positive, seed=BOOT_SEED,
                              resamples=RESAMPLES, clusters=None):
    """Percentile cluster bootstrap for (rate_1 - rate_2), questions as the resampling unit.

    by_q_* map query_id -> list of labels for that arm. The SAME drawn question is used for
    both arms, which is what makes this paired; all of its claims travel together, which is
    what makes it clustered. A question absent from a map contributes 0/0.
    """
    qs = list(clusters) if clusters is not None else question_order()
    k = len(qs)
    p1, p2 = _pooled(qs, by_q_1, positive), _pooled(qs, by_q_2, positive)
    point = None if p1 is None or p2 is None else p1 - p2

    rng = random.Random(seed)
    draws = []
    for _ in range(resamples):
        sel = [qs[rng.randrange(k)] for _ in range(k)]
        a, b = _pooled(sel, by_q_1, positive), _pooled(sel, by_q_2, positive)
        if a is not None and b is not None:
            draws.append(a - b)
    draws.sort()
    return {
        "difference": round(point, 10) if point is not None else None,
        "ci95": [round(draws[int(0.025 * len(draws))], 10),
                 round(draws[int(0.975 * len(draws)) - 1], 10)],
        "resamples_used": len(draws),
        "clusters": k,
        "seed": seed,
        "method": (
            "percentile paired-question cluster bootstrap; clusters are the 134 questions, "
            "both arms resampled on the same draw, all claims of a question move together"
        ),
        "conditional_on": (
            "the observed labels and the one captured generation per arm; the question set is "
            "authored, not a probability sample, so this is not a statement about "
            "representativeness, judge error or generation variance"
        ),
    }


def _self_test_bootstrap() -> None:
    """The properties that separate this from treating claims as independent draws."""
    qs = [f"q{i:02d}" for i in range(20)]

    # identical arms: difference exactly 0, and every resample cancels, so the interval
    # collapses to [0, 0]. Correct here, and the degenerate case to recognise in real data.
    a = {q: (["relevant"] * 5 if i < 4 else ["not_relevant"] * 5) for i, q in enumerate(qs)}
    r = paired_question_bootstrap(a, dict(a), "relevant", resamples=400, clusters=qs)
    assert r["difference"] == 0.0 and r["ci95"] == [0.0, 0.0], r

    # arms differing on whole clusters: positive difference, non-degenerate interval
    b = {q: ["not_relevant"] * 5 for q in qs}
    r2 = paired_question_bootstrap(a, b, "relevant", resamples=400, clusters=qs)
    assert r2["difference"] == 0.2 and r2["ci95"][1] > r2["ci95"][0] > -1, r2

    # CLUSTERING MUST WIDEN. Same 100 labels, but as 20 clusters of 5 rather than 100 clusters
    # of 1. If the resampling unit were the claim the interval would be ~sqrt(5) too narrow.
    flat = {f"f{i:03d}": [lab] for i, lab in enumerate(
        [x for q in qs for x in a[q]])}
    flat_qs = list(flat)
    wide = paired_question_bootstrap(a, b, "relevant", resamples=2000, clusters=qs)
    narrow = paired_question_bootstrap(
        flat, {q: ["not_relevant"] for q in flat_qs}, "relevant",
        resamples=2000, clusters=flat_qs)
    w = wide["ci95"][1] - wide["ci95"][0]
    n = narrow["ci95"][1] - narrow["ci95"][0]
    assert w > 1.5 * n, f"clustered interval {w:.4f} is not wider than unclustered {n:.4f}"

    # a question with no claims must be drawable and contribute nothing
    with_empty = dict(a)
    with_empty["q_empty"] = []
    r3 = paired_question_bootstrap(with_empty, b, "relevant", resamples=400,
                                   clusters=qs + ["q_empty"])
    assert abs(r3["difference"] - 0.2) < 1e-12, r3


def _self_test() -> None:
    # containment: the interval must contain the point difference
    r = newcombe(7, 185, 10, 364)
    assert r["ci95"][0] <= r["difference"] <= r["ci95"][1], r

    # symmetry: swapping the arms must negate and reverse the interval. This is the test that
    # fails if the excursions are paired the wrong way round.
    a = newcombe(179, 185, 350, 364)
    b = newcombe(350, 364, 179, 185)
    assert abs(a["ci95"][0] + b["ci95"][1]) < 1e-9, (a["ci95"], b["ci95"])
    assert abs(a["ci95"][1] + b["ci95"][0]) < 1e-9, (a["ci95"], b["ci95"])

    # identical proportions: the interval must straddle zero
    z = newcombe(4, 185, 8, 370)
    assert z["difference"] == 0.0 and z["ci95"][0] < 0 < z["ci95"][1], z

    # boundary: 0 of n against 0 of m stays inside [-1, 1] and contains 0
    e = newcombe(0, 185, 0, 364)
    assert e["ci95"][0] <= 0 <= e["ci95"][1] and e["ci95"][0] >= -1 and e["ci95"][1] <= 1, e

    # a Wald interval would run below -1 here; Wilson must not
    lo, hi = wilson(0, 10)
    assert lo == 0.0 and 0 < hi < 1, (lo, hi)


def build(matched_path: Path) -> dict:
    blob = json.loads(matched_path.read_text(encoding="utf-8"))
    while isinstance(blob, dict) and "instruments" not in blob:
        for k in ("result", "output"):
            if k in blob:
                blob = blob[k]
                break
        else:
            break
    assert "instruments" in blob, "no instruments in the matched-arm output"

    pinned = json.loads(PINNED_SHIPPED.read_text(encoding="utf-8"))
    while isinstance(pinned, dict) and "instruments" not in pinned:
        for k in ("result", "output"):
            if k in pinned:
                pinned = pinned[k]
                break
        else:
            break

    rematch = blob.get("shipped_rematch") or {}
    report = {
        "what_this_is": (
            "The between-arm contrast with the instrument held fixed: both arms judged under "
            "the shipped codebook, the same pinned model, the same adjudicator prompt and the "
            "same batch size. The confounded contrast the paper first reported is printed "
            "beside it."
        ),
        "why_newcombe": (
            "An interval for the DIFFERENCE, not two intervals that happen to overlap. Built "
            "from Wilson intervals so it behaves where responsiveness lives, near 0.02."
        ),
        "matched_output": str(matched_path).replace("\\", "/"),
        "model_alias_requested": blob.get("model_alias_requested"),
        "model_id_witnessed": blob.get("model_id_witnessed"),
        "codebook_source": blob.get("codebook_source"),
        "batch_size": blob.get("batch_size"),
        "shipped_side_readjudicated": {
            ins: len(v) for ins, v in rematch.items()
        },
        "instruments": {},
    }

    for ins in ("entailment", "relevance"):
        pos = POSITIVE[ins]

        # shipped side: the pinned re-run, with its bare-label adjudications replaced by the
        # rematch verdicts, so both sides share the adjudicator design
        override = {j["item_id"]: j["label"] for j in rematch.get(ins, [])}
        ship = resolve(pinned["instruments"][ins], override)
        ship_ids = real_ids(KEYS_SHIPPED[ins], ship)

        url = resolve(blob["instruments"][ins])
        url_ids = real_ids(KEYS_URLFIRST[ins], url)

        k1 = sum(1 for i in ship_ids if ship[i] == pos)
        k2 = sum(1 for i in url_ids if url[i] == pos)
        matched = newcombe(k1, len(ship_ids), k2, len(url_ids))

        # the primary interval: paired on question, clustered within it
        ship_by_q = labels_by_question(KEYS_SHIPPED[ins], ship, ship_ids)
        url_by_q = labels_by_question(KEYS_URLFIRST[ins], url, url_ids)
        boot = paired_question_bootstrap(ship_by_q, url_by_q, pos)
        boot_alt = paired_question_bootstrap(ship_by_q, url_by_q, pos, seed=BOOT_ALT_SEED)
        # 1e-9, not 1e-12: `difference` is stored rounded to 10 places, which is itself a
        # ~2e-11 perturbation. A tighter tolerance fails on the rounding, not on the data.
        assert abs(boot["difference"] - (k1 / len(ship_ids) - k2 / len(url_ids))) < 1e-9, \
            "the bootstrap point estimate disagrees with the pooled counts"
        widths = {
            "paired_question_bootstrap": round(boot["ci95"][1] - boot["ci95"][0], 6),
            "newcombe_independent": round(matched["ci95"][1] - matched["ci95"][0], 6),
        }

        # the confounded contrast, for comparison
        o_ship_blob = json.loads(ORIGINAL[ins][0].read_text(encoding="utf-8"))
        o_url_blob = json.loads(ORIGINAL[ins][1].read_text(encoding="utf-8"))
        o_ship, o_url = resolve(o_ship_blob), resolve(o_url_blob)
        o_ship_ids = real_ids(KEYS_SHIPPED[ins], o_ship)
        o_url_ids = real_ids(KEYS_URLFIRST[ins], o_url)
        confounded = newcombe(
            sum(1 for i in o_ship_ids if o_ship[i] == pos), len(o_ship_ids),
            sum(1 for i in o_url_ids if o_url[i] == pos), len(o_url_ids),
        )

        ctrl_ids = [i for i in url if i not in set(url_ids)]
        report["instruments"][ins] = {
            "PRIMARY_matched_contrast_paired_question_bootstrap": boot,
            "same_at_a_second_seed": {"seed": boot_alt["seed"], "ci95": boot_alt["ci95"]},
            "interval_widths": widths,
            "why_not_newcombe": (
                "Newcombe's hybrid score is for two INDEPENDENT binomial proportions. Both arms "
                "answer the same 134 questions (paired) and claims are nested in questions "
                "(clustered), so neither assumption holds. It is retained below to show what "
                "the wrong assumption costs."
            ),
            "matched_contrast": matched,
            "confounded_contrast_as_first_reported": confounded,
            "moved_by_matching": round(matched["difference"] - confounded["difference"], 4),
            "url_first_label_distribution_matched": dict(Counter(url[i] for i in url_ids)),
            "url_first_label_distribution_as_first_judged": dict(
                Counter(o_url[i] for i in o_url_ids)),
            "url_first_controls": {
                "n": len(ctrl_ids),
                "labels": dict(Counter(url[i] for i in ctrl_ids)),
                "avoided_the_positive_label": sum(1 for i in ctrl_ids if url[i] != pos),
            },
            "url_first_internal_agreement": blob["instruments"][ins].get("counts"),
        }

    return report


def summarise(r: dict) -> None:
    print(f"  model alias {r.get('model_alias_requested')}, witnessed "
          f"{(r.get('model_id_witnessed') or {}).get('model_id')}")
    print(f"  shipped side re-adjudicated: {r.get('shipped_side_readjudicated')}")
    for ins, d in r["instruments"].items():
        m, c = d["matched_contrast"], d["confounded_contrast_as_first_reported"]
        print(f"\n  {ins}")
        print(f"    matched     shipped {m['arm_1']['hits']}/{m['arm_1']['n']} = "
              f"{m['arm_1']['rate']}   URL-first {m['arm_2']['hits']}/{m['arm_2']['n']} = "
              f"{m['arm_2']['rate']}")
        b = d["PRIMARY_matched_contrast_paired_question_bootstrap"]
        print(f"                difference {b['difference']:+.4f}")
        print(f"      PRIMARY paired-question cluster bootstrap  95% CI "
              f"[{b['ci95'][0]:+.4f}, {b['ci95'][1]:+.4f}]  (seed {b['seed']}, "
              f"{b['clusters']} clusters)")
        print(f"              second seed {d['same_at_a_second_seed']['seed']}          "
              f"[{d['same_at_a_second_seed']['ci95'][0]:+.4f}, "
              f"{d['same_at_a_second_seed']['ci95'][1]:+.4f}]")
        print(f"              Newcombe, wrongly assuming independence  {m['ci95']}  "
              f"({d['interval_widths']['newcombe_independent'] / d['interval_widths']['paired_question_bootstrap']:.2f}x wider)")
        print(f"    confounded  {c['arm_1']['rate']} vs {c['arm_2']['rate']}, "
              f"difference {c['difference']:+.4f}  95% CI {c['ci95']}")
        print(f"    matching moved the difference by {d['moved_by_matching']:+.4f}")
        u = d["url_first_controls"]
        print(f"    URL-first controls: {u['avoided_the_positive_label']}/{u['n']} avoided "
              f"`{POSITIVE[ins]}`  {u['labels']}")


def main() -> int:
    _self_test()
    _self_test_bootstrap()
    ap = argparse.ArgumentParser()
    ap.add_argument("--matched", type=Path, help="matched-arm-rejudge.js output JSON")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    if a.check:
        if not OUT.exists():
            print("no matched arm contrast committed yet")
            return 1
        stored = json.loads(OUT.read_text(encoding="utf-8"))
        src = Path(stored["matched_output"])
        if not src.exists():
            print("the matched output named in the report is not on disk; cannot re-derive")
            return 1
        fresh = build(src)
        bad = []
        for ins, f in fresh["instruments"].items():
            s = stored["instruments"].get(ins, {})
            for field in ("difference", "ci95"):
                if (s.get("matched_contrast") or {}).get(field) != f["matched_contrast"][field]:
                    bad.append(f"{ins}.matched_contrast.{field}")
            k = "PRIMARY_matched_contrast_paired_question_bootstrap"
            for field in ("difference", "ci95", "seed", "clusters"):
                if (s.get(k) or {}).get(field) != f[k][field]:
                    bad.append(f"{ins}.{k}.{field}")
        print("the matched arm contrast re-derives from the artifacts" if not bad else "MISMATCH")
        for b in bad:
            print("  " + b)
        return 1 if bad else 0

    if not a.matched:
        raise SystemExit("--matched is required; pass the workflow's output JSON")

    report = build(a.matched)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}")
    summarise(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
