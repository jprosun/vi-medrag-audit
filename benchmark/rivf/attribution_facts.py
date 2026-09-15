"""Recompute, from the committed capture alone, the attribution facts the paper prints.

Why this exists
---------------
Two blocks of the paper had no artifact behind them:

* the figure-attribution pair (how many claim figures in a delivered answer sit inside a
  verified span), because the 134-question runner crashed before writing its summary JSON;
* the independent-span breakdown, which is the evidence for the paper's claim that
  composing the span and citability gates removes most of the population on which
  containment is a non-trivial test.

Both were computed by throwaway scripts. One of them used a substring test where the
server uses set membership of parsed numbers, and printed 158 where the server's own
definition gives 157. A number the repo cannot reproduce does not belong in the paper, so
the computation lives here and writes an artifact.

Everything is recomputed from ``payload`` alone through the server's own
``app.span_exposure.evaluate_response`` and ``app.span_norm``. No server, no API, no
network, no Qdrant. Deterministic: run it twice and the artifact is byte-identical apart
from ``generated_by``.

Provenance
----------
The paper attributes every measurement to code ``13dc51f``. The capture's own summary JSON
was never written, so the artifact cannot carry the running server's SHA. Instead this
script proves the equivalent and stronger fact directly: it hashes the four enforcement
modules in the working tree and compares them byte for byte against the same paths at
``13dc51f``. If they match, the code that produced the capture is the certified code, and
a reader can re-run that check.

Usage
-----
    python benchmark/rivf/attribution_facts.py                    # writes the artifact
    python benchmark/rivf/attribution_facts.py --check            # verifies, writes nothing
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "services" / "rag-orchestrator"))

from app.span_exposure import evaluate_response  # noqa: E402
from app.span_norm import claim_numbers_in, normalise, numbers_in  # noqa: E402

CERTIFIED_SHA = "13dc51f"
CAPTURE = (
    REPO
    / "benchmark/datasets/test_results"
    / "pilot_span_exposure_rivf134_2026-09-05_091659_raw.jsonl"
)
PROBE_SET = REPO / "benchmark/datasets/probe_queries_v2.jsonl"
FROZEN_QUERY_SET_SHA = (
    "7f6b97e512d31a77aab6f22b1eeb6d84700f66e08a4068a5bdab357d5c3fddc9"
)
OUT = REPO / "benchmark/rivf/attribution_facts_rivf134.json"

# The numeric gate appends a notice listing the figures it removed. Counting figures in the
# answer as served therefore counts removed figures in the denominator, which inflates it.
REMOVAL_NOTICE = "\n\n---\n**Ghi chú hệ thống"

ENFORCEMENT_MODULES = [
    "services/rag-orchestrator/app/span_gate.py",
    "services/rag-orchestrator/app/span_norm.py",
    "services/rag-orchestrator/app/answer_verifier.py",
    "services/rag-orchestrator/app/main.py",
    "services/rag-orchestrator/app/schemas.py",
    "services/rag-orchestrator/app/span_exposure.py",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sha256_query_set(path: Path) -> str:
    """The frozen probe set's hash.

    Imported rather than re-implemented: the hash is only meaningful if it is the same
    function the runners and the gates used, and an independent re-implementation of it
    silently disagreed on the first attempt.
    """
    sys.path.insert(0, str(REPO / "benchmark" / "rivf"))
    from build_probe_set import sha256_of_query_set  # noqa: PLC0415

    rows = [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]
    return sha256_of_query_set(rows)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout.strip()


def code_provenance() -> dict:
    """Prove the enforcement code is identical to the certified commit.

    Compared as git blob ids, not as bytes on disk: this repo is checked out on Windows, so
    a working file carries CRLF while the stored blob carries LF, and a raw sha256 of the
    two differs on every file even when the content is identical. ``git hash-object``
    applies the same filters git applied on check-in, so the two ids are comparable.
    """
    if (REPO / "REDACTED").exists():
        return {"certified_commit": CERTIFIED_SHA,
                "status": "historical server source is outside this evaluation-only bundle",
                "all_enforcement_code_identical_to_certified_commit": False,
                "why_not_identical": {}}
    modules = {}
    for rel in ENFORCEMENT_MODULES:
        working_blob = git("hash-object", "--", rel)
        certified_blob = git("rev-parse", f"{CERTIFIED_SHA}:{rel}")
        modules[rel] = {
            "working_tree_blob": working_blob,
            "certified_blob": certified_blob,
            "file_sha256_on_disk": sha256_file(REPO / rel),
            "identical": bool(working_blob) and working_blob == certified_blob,
        }
    return {
        "certified_commit": CERTIFIED_SHA,
        "certified_commit_full": git("rev-parse", CERTIFIED_SHA),
        # The tree this identity check was run against. The block is a statement about
        # THAT tree, not about the capture: a later commit that touches main.py (as the
        # URL-first arm did, in the cache key and response metadata) flips main.py to
        # non-identical here without changing one byte of what produced the capture.
        "checked_at_commit": git("rev-parse", "HEAD"),
        "modules": modules,
        "all_enforcement_code_identical_to_certified_commit": all(
            m["identical"] for m in modules.values()
        ),
        "why_not_identical": {
            rel: classify_drift(rel) for rel, v in modules.items() if not v["identical"]
        } or "every module is blob-identical to the certified commit",
        "tracked_app_files_changed_since_certified_commit": git(
            "diff",
            "--name-only",
            f"{CERTIFIED_SHA}..HEAD",
            "--",
            "services/rag-orchestrator/app/",
        ).splitlines(),
    }


def claim_is_uncitable(claim: dict) -> bool:
    """Citability as the gate defines it: a non-empty source URL, nothing more.

    Counted over EVERY claim, including ones the span gate withheld first. A span-failed
    claim never reaches the citability check, so counting only what the citability gate
    rejected undercounts what a no-gate arm would have shown.
    """
    return not (claim.get("source_url") or "").strip()



# The one module that drifts, and the test that shows the drift is inert.
ARM_FLAG_TOKENS = ("RAG_EXCLUDE_SOURCE_IDS", "exclude_source_ids", "retrieval_excluded_source_ids")


def classify_drift(path: str) -> dict:
    """Is this module's difference from the certified commit confined to the arm flag?

    A module whose every changed line is an ADDITION mentioning the URL-first flag cannot
    have altered gate behaviour on the certified path: nothing was removed, and nothing else
    was added. Anything else -- a deletion, or an addition that mentions no flag -- comes back
    UNCLASSIFIED, which is the case a reader should stop and look at.
    """
    out = subprocess.run(
        ["git", "diff", "-U0", CERTIFIED_SHA, "--", path],
        cwd=REPO, capture_output=True, text=True,
    )
    changed = [
        line for line in out.stdout.splitlines()
        if line[:1] in "+-" and line[:2] not in ("++", "--")
    ]
    additions = [line for line in changed if line.startswith("+")]
    deletions = [line for line in changed if line.startswith("-")]
    arm_only = (
        bool(changed)
        and not deletions
        and all(
            any(t in line for t in ARM_FLAG_TOKENS) or line.lstrip("+ ").startswith("#")
            for line in additions
        )
    )
    return {
        "changed_lines": len(changed),
        "additions": len(additions),
        "deletions": len(deletions),
        "every_change_is_an_addition_mentioning_the_arm_flag": arm_only,
        "verdict": (
            "inert for the certified path: pure insertions of URL-first arm plumbing (an "
            "import, two cache-key entries, one recorded field and its comment). No gate "
            "logic was added, removed or altered."
            if arm_only else
            "UNCLASSIFIED -- inspect this diff before trusting any number derived from it"
        ),
    }

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="verify against the committed artifact")
    args = ap.parse_args()

    if (REPO / "REDACTED").exists() and "[WITHHELD sha256:" in CAPTURE.read_text(encoding="utf-8"):
        print("REQUIRES ORIGINAL CORPUS TEXT: span containment and numeric-token membership "
              "cannot be recomputed from redacted passages. See EVALUATION.md. "
              "No text-dependent result has been verified by this command.")
        return 2
    rows = [json.loads(line) for line in CAPTURE.open(encoding="utf-8") if line.strip()]

    shown = dropped = 0
    figures = figures_grounded = 0
    figures_as_served = figures_grounded_as_served = 0
    statements_removed = fabricated_pre = unattributed = 0
    drop_reasons: Counter = Counter()
    verdicts: Counter = Counter()

    independent = {"shown_contained": 0, "shown_not_contained": 0}
    independent_dropped: Counter = Counter()
    independent_uncitable = 0
    all_uncitable = 0
    uncitable_by_stratum: Counter = Counter()
    delivered_with_fabricated_figure = []
    answers_that_are_raw_verifier_json = []

    for row in rows:
        payload = row["payload"]
        meta = payload.get("metadata") or {}
        qid = row.get("query_id")
        answer = payload.get("answer") or ""
        delivered = answer.split(REMOVAL_NOTICE)[0]

        exposed = payload.get("claim_attributions") or []
        withheld = payload.get("dropped_claims") or []

        # Which stratum does each uncitable claim's citation point into? The paper's
        # "154 of the 156" turns on this, and it was previously unmeasured. A claim whose
        # chunk_id is absent from the response's own retrieved set is counted apart: that is
        # the span gate's `chunk_id_not_resolvable`, a different defect from a missing URL.
        chunk_stratum = {
            str(ch.get("id")): ((ch.get("metadata") or {}).get("source_id") or "unknown")
            for ch in (payload.get("retrieved_chunks") or [])
        }
        for claim in exposed + withheld:
            if claim_is_uncitable(claim):
                uncitable_by_stratum[
                    chunk_stratum.get(str(claim.get("chunk_id")), "chunk_id_not_in_retrieved_set")
                ] += 1
        shown += len(exposed)
        dropped += len(withheld)

        # Figures, by the server's own definition, on the text the reader is left with.
        ev = evaluate_response({**payload, "answer": delivered})
        figures += ev["answer_claim_figures"]
        figures_grounded += ev["answer_claim_figures_in_a_verified_span"]
        ev_served = evaluate_response(payload)
        figures_as_served += ev_served["answer_claim_figures"]
        figures_grounded_as_served += ev_served["answer_claim_figures_in_a_verified_span"]

        # Containment is a non-trivial test only where the span differs from the claim.
        # `claim_equals_span` is the server's own flag (span_exposure.py), raw equality
        # after stripping -- not the normalised comparison the gate itself uses.
        for claim, per in zip(exposed, ev["per_claim"]):
            if not per["claim_equals_span"]:
                key = (
                    "shown_contained"
                    if per["outcome"] == "strict_contained"
                    else "shown_not_contained"
                )
                independent[key] += 1
                independent_uncitable += claim_is_uncitable(claim)
            all_uncitable += claim_is_uncitable(claim)

        for claim in withheld:
            reason = claim.get("drop_reason") or "unrecorded"
            drop_reasons[reason] += 1
            all_uncitable += claim_is_uncitable(claim)
            claim_text = (claim.get("claim") or "").strip()
            span = (claim.get("supporting_span") or "").strip()
            if claim_text and claim_text != span:
                independent_dropped[reason] += 1
                independent_uncitable += claim_is_uncitable(claim)

        verdicts[meta.get("verification_status") or "unrecorded"] += 1

        # The numeric gate's own counters. They are answer-level, not claim-level: it
        # removes statements from the text rather than withholding claims, and reading
        # them as claims is the easiest way to misread the conditions table.
        statements_removed += meta.get("numeric_statements_removed") or 0
        fabricated_pre += meta.get("numeric_fabricated_pre_count") or 0
        unattributed += meta.get("numeric_unattributed_count") or 0

        # The gates run BEFORE the verifier, and main.py replaces the answer with the
        # verifier's revision afterwards without re-running them. So the zero the paper
        # reports has to be measured on what was actually delivered, not assumed.
        evidence_numbers = set(
            numbers_in(
                normalise(" ".join((c.get("text") or "") for c in (payload.get("retrieved_chunks") or [])))
            )
        )
        fabricated = [
            n
            for n in claim_numbers_in(normalise(delivered), raw_text=delivered)
            if n not in evidence_numbers
        ]
        if fabricated:
            delivered_with_fabricated_figure.append({"query_id": qid, "figures": fabricated[:8]})
        stripped = delivered.lstrip()
        if stripped.startswith("{") and '"status"' in stripped[:200]:
            answers_that_are_raw_verifier_json.append(
                {"query_id": qid, "chars": len(delivered), "prefix": delivered[:120]}
            )

    span_failures = drop_reasons["span_not_found_in_cited_chunk"] + drop_reasons["chunk_id_not_resolvable"]
    independent_span_failed = (
        independent_dropped["span_not_found_in_cited_chunk"]
        + independent_dropped["chunk_id_not_resolvable"]
    )
    independent_total = (
        independent["shown_contained"]
        + independent["shown_not_contained"]
        + sum(independent_dropped.values())
    )
    total_claims = shown + dropped

    facts = {
        "what_this_is": (
            "Attribution facts recomputed from the committed 134-question capture alone, "
            "through the server's own span_exposure/span_norm definitions. Offline and "
            "deterministic."
        ),
        "provenance": {
            "capture": {
                "path": str(CAPTURE.relative_to(REPO)).replace("\\", "/"),
                "sha256": sha256_file(CAPTURE),
                "records": len(rows),
            },
            "probe_set": {
                "path": str(PROBE_SET.relative_to(REPO)).replace("\\", "/"),
                "query_set_sha256": sha256_query_set(PROBE_SET),
                "matches_frozen_hash": sha256_query_set(PROBE_SET) == FROZEN_QUERY_SET_SHA,
                "every_capture_question_is_in_the_probe_set": None,  # filled below
            },
            "code": code_provenance(),
        },
        "claims": {
            "total": total_claims,
            "shown": shown,
            "withheld": dropped,
            "withheld_by_reason": dict(sorted(drop_reasons.items())),
            "span_gate_failures": span_failures,
            "uncitable_over_every_claim_no_gate_arm": all_uncitable,
            "uncitable_by_stratum_of_the_cited_chunk": dict(uncitable_by_stratum.most_common()),
        },
        "containment_is_non_trivial_only_here": {
            "definition": (
                "A claim whose supporting span is textually distinct from the claim. Where "
                "span == claim, containment reduces to string identity and can only fail if "
                "the claim itself is absent from the cited chunk."
            ),
            "independent_span_claims": independent_total,
            "shown_and_contained": independent["shown_contained"],
            "shown_and_not_contained": independent["shown_not_contained"],
            "withheld_by_reason": dict(sorted(independent_dropped.items())),
            "failed_containment": independent_span_failed,
            "verified_then_withheld_for_citability": independent_dropped["cited_record_not_citable"],
            "reached_the_reader": independent["shown_contained"] + independent["shown_not_contained"],
            "structural_share_of_shown_claims": round((shown - independent["shown_contained"] - independent["shown_not_contained"]) / shown, 4),
            "uncitable_share_of_independent_span_claims": round(independent_uncitable / independent_total, 4),
            "uncitable_share_of_all_claims": round(all_uncitable / total_claims, 4),
        },
        "figures_in_delivered_answers": {
            "definition": (
                "Claim figures per app.span_norm.claim_numbers_in, tested for membership in "
                "the union of the verified spans shown with the answer, per "
                "app.span_exposure.evaluate_response. The numeric gate's removal notice is "
                "stripped first: it lists the figures that were removed, so leaving it in "
                "counts them in the denominator."
            ),
            "claim_figures": figures,
            "inside_a_verified_span": figures_grounded,
            "rate_inside": round(figures_grounded / figures, 4),
            "rate_outside": round(1 - figures_grounded / figures, 4),
            "with_the_removal_notice_left_in": {
                "claim_figures": figures_as_served,
                "inside_a_verified_span": figures_grounded_as_served,
            },
            "numeric_gate_counters": {
                "note": (
                    "Answer-level, not claim-level: the numeric gate removes statements "
                    "from the text rather than withholding claims."
                ),
                "statements_removed": statements_removed,
                "fabricated_figures_pre_enforcement": fabricated_pre,
                "unattributed_figures_server_counter": unattributed,
            },
        },
        "delivered_answer_checks": {
            "why": (
                "The four gates run before verification (main.py), and a 'revise' verdict "
                "replaces the answer with the verifier's revision afterwards without "
                "re-running them. The absence of fabricated figures in what was delivered "
                "is therefore a measured fact, not a structural guarantee."
            ),
            "verifier_verdicts": dict(sorted(verdicts.items())),
            "answers_retaining_a_figure_absent_from_all_evidence": len(delivered_with_fabricated_figure),
            "which": delivered_with_fabricated_figure,
            "answers_that_are_a_raw_verifier_json_object": answers_that_are_raw_verifier_json,
        },
    }

    probe_questions = {
        json.loads(line)["question"].strip()
        for line in PROBE_SET.open(encoding="utf-8")
        if line.strip()
    }
    facts["provenance"]["probe_set"]["every_capture_question_is_in_the_probe_set"] = all(
        (r.get("question") or r["payload"].get("question") or "").strip() in probe_questions
        for r in rows
    )

    text = json.dumps(facts, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    if args.check:
        if not OUT.exists():
            print(f"MISSING {OUT}")
            return 1
        stored = json.loads(OUT.read_text(encoding="utf-8"))
        # The code-identity block describes the tree the check ran on, and that tree moves
        # with every later commit while the capture does not. It is kept in the artifact as
        # a dated statement and excluded from the reproducibility comparison; everything
        # that is a MEASUREMENT of the capture must reproduce exactly.
        for blob in (stored, facts):
            blob["provenance"].pop("code", None)
        same = stored == facts
        if same:
            print("artifact reproduces exactly")
        elif (REPO / "REDACTED").exists():
            # The public bundle withholds the chunk text, and this check recomputes span
            # containment FROM that text. It cannot reproduce here, and it must not pretend
            # to: a check that reports success without verifying anything is worse than one
            # that goes red and explains itself.
            print("CANNOT VERIFY IN THE REDACTED BUNDLE. This recomputes span containment "
                  "from the chunk text, which is withheld here, so a fresh run cannot match "
                  "the committed artifact. Re-run it against the corpus to check it.")
        else:
            print("ARTIFACT DIFFERS from a fresh run")
        return 0 if same else 1

    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}")
    c = facts["containment_is_non_trivial_only_here"]
    f = facts["figures_in_delivered_answers"]
    print(
        f"  claims {facts['claims']['total']} = {shown} shown + {dropped} withheld; "
        f"span failures {span_failures}"
    )
    print(
        f"  independent-span claims {c['independent_span_claims']}: "
        f"{c['failed_containment']} failed containment, "
        f"{c['verified_then_withheld_for_citability']} verified then withheld for citability, "
        f"{c['reached_the_reader']} reached the reader"
    )
    print(f"  figures {f['inside_a_verified_span']} of {f['claim_figures']} inside a span "
          f"= {f['rate_inside']} in, {f['rate_outside']} out")
    code = facts["provenance"]["code"]
    if code["all_enforcement_code_identical_to_certified_commit"]:
        print(f"  enforcement code blob-identical to {CERTIFIED_SHA}: all "
              f"{len(ENFORCEMENT_MODULES)} modules")
    else:
        for rel, d in code["why_not_identical"].items():
            print(f"  {rel.split('/')[-1]} differs from {CERTIFIED_SHA}: "
                  f"+{d['additions']}/-{d['deletions']} lines -> {d['verdict'].split(':')[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
