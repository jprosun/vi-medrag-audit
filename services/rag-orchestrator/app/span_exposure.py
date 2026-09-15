"""``span_exposure_rate`` — definition, and the diagnostics that stop it being vacuous.

THE DEFINITION
==============
Gate G0 (``docs/project/FINAL-SPRINT-PLAN.md:228``) names ``span_exposure_rate == 1.00``
without defining it. The natural reading, and the one used here:

    span_exposure_rate =
        (# claims SHOWN TO THE USER whose supporting_span STRICT-verifies inside the
         chunk that claim cites)
        / (# claims SHOWN TO THE USER)

"Shown to the user" is the ``claim_attributions`` array of the response — the array the
UI source panel renders. "STRICT-verifies" is ``span_norm.span_is_contained``: exact
substring containment after documented normalisation, diacritics NOT folded.

The numerator is recomputed here from the response payload — span text vs. the text of
the cited chunk, both taken from the response — rather than read off the server's own
``span_verified`` flag. Trusting the flag would make the metric a tautology about a
boolean the server set; recomputing it can catch a serialisation or ordering bug where
the span that was checked is not the span that was shipped.

WHY 1.00 IS EXPECTED, AND WHY THAT ALONE IS WORTHLESS
=====================================================
``main.py`` populates ``claim_attributions`` from ``span_report.verified`` only, and
``span_gate.verify_claims`` puts a claim there only when containment already held. So the
rate is 1.00 **by construction**. The honest question is the DENOMINATOR, and there are
three ways this metric can be 1.00 while attribution is in fact absent:

1. **Empty denominator.** An answer that pins zero claims contributes 0/0. Pooling would
   hide it. ``answers_with_zero_exposed_claims`` is reported, and the pooled rate is
   ``None`` when the pool is empty — never 1.0.

2. **Structural containment.** ``evidence_extractor._select_direct_answer_spans`` and
   ``_select_query_focus_claims`` build every claim as
   ``ClaimEvidence(claim=sentence, supporting_span=sentence, chunk_id=chunk.id)`` — the
   span IS the claim, copied verbatim out of the chunk by code. Containment then holds
   for arithmetic reasons and tests nothing. ``structural_containment_share`` counts
   these (``claim.strip() == supporting_span.strip()``), and
   ``span_exposure_rate_independent`` restricts the metric to claims where claim and span
   DIFFER — the only claims where containment is a real test. This is the trap already
   recorded in this project: a claim-drop rate of 0.000 that only reflected the simple
   extractor path.

3. **Pinning almost nothing.** Two or three pinned spans next to a 7,000-character
   answer satisfies 1.00 while most of the answer is unattributed.
   ``mean_exposed_claims_per_answer``, ``answer_chars_per_exposed_claim`` and
   ``figure_attribution_rate`` (claim figures in the displayed answer that occur in some
   verified span) are reported alongside the headline for exactly this reason. The
   attribution gap this project measured — ~30 figures used against ~3 pinned spans — is
   invisible in ``span_exposure_rate`` and visible in ``figure_attribution_rate``.

``vacuity_flags`` names whichever of these applies to the run in hand.
"""

from __future__ import annotations

from typing import Any, Optional

from .span_gate import min_span_chars
from .span_norm import claim_numbers_in, normalise, numbers_in, span_is_contained

# A pooled rate over this few claims is not a rate. Reported as a flag, not enforced.
MIN_POOLED_CLAIMS_FOR_A_RATE = 20


def _rate(numerator: int, denominator: int) -> Optional[float]:
    """None when the denominator is empty. Never 1.0 for 0/0."""
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def evaluate_response(payload: dict, *, min_chars: Optional[int] = None) -> dict:
    """Per-response span exposure facts, recomputed from the payload alone."""
    min_chars = min_span_chars() if min_chars is None else min_chars
    exposed = list(payload.get("claim_attributions") or [])
    dropped = list(payload.get("dropped_claims") or [])
    chunks = {
        str(c.get("id") or ""): (c.get("text") or "")
        for c in (payload.get("retrieved_chunks") or [])
    }
    answer = payload.get("answer") or ""

    per_claim: list = []
    for claim in exposed:
        claim_text = (claim.get("claim") or "").strip()
        span = (claim.get("supporting_span") or "").strip()
        chunk_id = str(claim.get("chunk_id") or "")
        chunk_text = chunks.get(chunk_id)
        if not span:
            outcome = "no_span"
        elif chunk_text is None:
            # The cited chunk is not in the payload, so containment is UNCHECKABLE from
            # the response. Recorded as its own outcome: counting it as a pass would
            # assert something the artifact cannot support, and counting it as a
            # containment failure would blame the gate for a payload gap.
            outcome = "cited_chunk_absent_from_payload"
        elif span_is_contained(span, chunk_text, min_chars=min_chars):
            outcome = "strict_contained"
        else:
            outcome = "strict_not_contained"
        per_claim.append(
            {
                "chunk_id": chunk_id,
                "outcome": outcome,
                "server_span_verified": bool(claim.get("span_verified")),
                "citable": bool(claim.get("citable")),
                "claim_equals_span": bool(claim_text) and claim_text == span,
                "span_chars": len(span),
            }
        )

    contained = sum(1 for c in per_claim if c["outcome"] == "strict_contained")
    not_contained = sum(1 for c in per_claim if c["outcome"] == "strict_not_contained")
    unresolvable = sum(
        1 for c in per_claim if c["outcome"] == "cited_chunk_absent_from_payload"
    )
    no_span = sum(1 for c in per_claim if c["outcome"] == "no_span")
    structural = sum(1 for c in per_claim if c["claim_equals_span"])
    independent = [c for c in per_claim if not c["claim_equals_span"]]
    independent_contained = sum(
        1 for c in independent if c["outcome"] == "strict_contained"
    )
    flag_disagreements = sum(
        1
        for c in per_claim
        if c["server_span_verified"] != (c["outcome"] == "strict_contained")
    )

    # Figure-level attribution: every claim figure in the DISPLAYED answer against the
    # union of verified spans. This is the denominator span_exposure_rate cannot see.
    verified_span_text = " ".join(
        normalise((c.get("supporting_span") or "")) for c in exposed
    )
    grounded_numbers = set(numbers_in(verified_span_text))
    answer_figures = claim_numbers_in(normalise(answer), raw_text=answer)
    figures_grounded = [n for n in answer_figures if n in grounded_numbers]

    return {
        "exposed_claims": len(exposed),
        "dropped_claims": len(dropped),
        "strict_contained": contained,
        "strict_not_contained": not_contained,
        "cited_chunk_absent_from_payload": unresolvable,
        "no_span": no_span,
        "structural_containment_claims": structural,
        "independent_attribution_claims": len(independent),
        "independent_attribution_contained": independent_contained,
        "server_flag_disagreements": flag_disagreements,
        "answer_chars": len(answer),
        "answer_claim_figures": len(answer_figures),
        "answer_claim_figures_in_a_verified_span": len(figures_grounded),
        "span_exposure_rate": _rate(contained, len(exposed)),
        "per_claim": per_claim,
    }


def pool(evaluations: list, *, context: Optional[dict] = None) -> dict:
    """Pool per-response facts into the gate-level metric plus its vacuity diagnostics."""
    total = lambda key: sum(int(e.get(key) or 0) for e in evaluations)  # noqa: E731

    exposed = total("exposed_claims")
    contained = total("strict_contained")
    not_contained = total("strict_not_contained")
    unresolvable = total("cited_chunk_absent_from_payload")
    no_span = total("no_span")
    dropped = total("dropped_claims")
    structural = total("structural_containment_claims")
    independent = total("independent_attribution_claims")
    independent_contained = total("independent_attribution_contained")
    disagreements = total("server_flag_disagreements")
    figures = total("answer_claim_figures")
    figures_grounded = total("answer_claim_figures_in_a_verified_span")
    answer_chars = total("answer_chars")
    zero_claim_answers = sum(1 for e in evaluations if not e.get("exposed_claims"))
    n = len(evaluations)

    rate = _rate(contained, exposed)
    rate_independent = _rate(independent_contained, independent)

    flags: list = []
    if exposed == 0:
        flags.append(
            "EMPTY_DENOMINATOR: no claim was exposed in any response, so "
            "span_exposure_rate is undefined (reported as null, not 1.0)"
        )
    if zero_claim_answers:
        flags.append(
            f"ZERO_CLAIM_ANSWERS: {zero_claim_answers}/{n} answers pinned no claim at all "
            "and contribute nothing to the denominator while still being shown to the user"
        )
    if exposed and structural == exposed:
        flags.append(
            "STRUCTURAL_CONTAINMENT_ONLY: every exposed claim has claim == supporting_span, "
            "i.e. the span was copied verbatim out of the chunk by "
            "evidence_extractor._select_* . Containment holds for arithmetic reasons and "
            "span_exposure_rate == 1.00 is VACUOUS for this run"
        )
    elif exposed and structural:
        flags.append(
            f"PARTIAL_STRUCTURAL_CONTAINMENT: {structural}/{exposed} exposed claims have "
            "claim == supporting_span; only span_exposure_rate_independent is a real test"
        )
    if independent == 0:
        flags.append(
            "NO_INDEPENDENT_ATTRIBUTION: not one exposed claim had a span DIFFERENT from "
            "the claim text, so nothing in this run tested containment non-trivially"
        )
    if 0 < exposed < MIN_POOLED_CLAIMS_FOR_A_RATE:
        flags.append(
            f"THIN_POOL: only {exposed} exposed claims across {n} responses "
            f"(< {MIN_POOLED_CLAIMS_FOR_A_RATE}); the pooled rate is a count, not a rate"
        )
    if figures and figures_grounded < figures:
        flags.append(
            f"ATTRIBUTION_GAP: the displayed answers use {figures} claim figures and only "
            f"{figures_grounded} of them occur in any verified span. span_exposure_rate "
            "cannot see this and must never be reported as 'attribution'"
        )
    if disagreements:
        flags.append(
            f"SERVER_FLAG_DISAGREEMENT: {disagreements} exposed claim(s) where the "
            "server's span_verified flag differs from independent recomputation"
        )

    out = {
        "responses": n,
        "exposed_claims": exposed,
        "dropped_claims": dropped,
        "strict_contained": contained,
        "strict_not_contained": not_contained,
        "cited_chunk_absent_from_payload": unresolvable,
        "no_span": no_span,
        # ── the gate metric ──
        "span_exposure_rate": rate,
        "span_exposure_rate_definition": (
            "claims shown to the user (response.claim_attributions) whose supporting_span "
            "STRICT-verifies (span_norm.span_is_contained, min_chars="
            f"{min_span_chars()}) inside the chunk they cite, divided by claims shown to "
            "the user. Recomputed from the payload, not read off span_verified."
        ),
        "gate_met": rate == 1.0,
        # ── the diagnostics that decide whether the 1.00 means anything ──
        "structural_containment_claims": structural,
        "structural_containment_share": _rate(structural, exposed),
        "independent_attribution_claims": independent,
        "span_exposure_rate_independent": rate_independent,
        "claim_retention_rate": _rate(exposed, exposed + dropped),
        "answers_with_zero_exposed_claims": zero_claim_answers,
        "mean_exposed_claims_per_answer": round(exposed / n, 3) if n else None,
        "answer_chars_per_exposed_claim": round(answer_chars / exposed, 1) if exposed else None,
        "answer_claim_figures": figures,
        "answer_claim_figures_in_a_verified_span": figures_grounded,
        "figure_attribution_rate": _rate(figures_grounded, figures),
        "server_flag_disagreements": disagreements,
        "vacuity_flags": flags,
    }
    if context:
        out["context"] = context
    return out


def evaluate_run(payloads: list, *, context: Optional[dict] = None) -> dict:
    """Convenience: per-response evaluation plus the pooled metric."""
    evaluations = [evaluate_response(p) for p in payloads]
    pooled: dict[str, Any] = pool(evaluations, context=context)
    return {"pooled": pooled, "per_response": evaluations}
