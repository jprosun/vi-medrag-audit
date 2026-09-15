"""The span gate: every displayed claim must have a span located in its cited chunk.

Why
---
``evidence_extractor`` already produces ``ClaimEvidence.supporting_span`` and
``chunk_id``, but nothing ever checked that the span was real and ``schemas.py`` never
exposed it. Meanwhile ``answer_verifier`` validated a citation only by index range,
so ``[3]`` on a fabricated sentence passed whenever three sources were retrieved.

This module closes that loop with a check done in CODE, not by a model:

    for each claim, take its ``supporting_span`` and the chunk it names, and test
    containment after documented normalisation. Unverified claims are dropped.

The drop rate is reported as a first-class metric, not hidden. It is the price of
the guarantee and it belongs in the results table: a high drop rate means the
extractor is producing spans that are not in the documents, which is itself the
finding.

Scope of the guarantee — say this out loud in any write-up
---------------------------------------------------------
``span_exists`` is mechanical and exhaustive. It proves the cited string is present
in the cited document. It does NOT prove the string supports the claim. Entailment
is a separate measurement on a sample with agreement reported. Reporting
``span_exists`` as "attribution" would be the single easiest thing for an examiner
to take apart.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .span_norm import (
    claim_numbers_in,
    normalise,
    numbers_are_grounded,
    numbers_in,
    span_is_contained,
)


def span_gate_enabled() -> bool:
    """Whether unverified claims are dropped from the response.

    Default True. Set SPAN_GATE_ENABLED=false to measure the drop rate without
    changing what is displayed — useful for one controlled arm, not for shipping.
    """
    return os.getenv("SPAN_GATE_ENABLED", "true").strip().lower() not in (
        "0", "false", "no", "n", "off",
    )


def citability_enforcement_enabled() -> bool:
    """Whether a claim citing a record with no resolvable source_url is DROPPED.

    Default True. Until this existed the citability gate only COUNTED such claims
    (``uncitable_verified_count``) while still displaying them, and the count was not
    small: measured over the 30-question G0 capture, 24 of 89 displayed claims (27.0%)
    across 8 of 30 questions cited a record the reader cannot open. Every one came from
    ``hf_vi_mtue29_medical`` — 256,415 chunks, 43% of the collection, trust_tier 3, and
    **0% of them carry a source_url**, so backfilling the field is not available: the
    upstream dataset has no URLs at all.

    A claim the reader cannot trace is not evidence in a system whose whole argument is
    traceability, so it is now withheld rather than tallied. The chunk is still retrieved
    and still reaches the model as context; what it may no longer do is carry a citation.

    Set CITABILITY_ENFORCEMENT=false to measure the rate without changing what is
    displayed. That is a controlled arm, not a shipping configuration.
    """
    return os.getenv("CITABILITY_ENFORCEMENT", "true").strip().lower() not in (
        "0", "false", "no", "n", "off",
    )


def min_span_chars() -> int:
    """Shortest span length that counts as evidence.

    A very short span matches almost any document, so allowing it would inflate the
    verification rate without evidencing anything. Unfitted; revisit on dev.
    """
    try:
        return max(0, int(os.getenv("SPAN_GATE_MIN_CHARS", "12")))
    except ValueError:
        return 12


@dataclass
class VerifiedClaim:
    claim: str
    supporting_span: str
    chunk_id: str
    section_title: str = ""
    source_url: str = ""
    source_name: str = ""
    title: str = ""
    span_verified: bool = False
    drop_reason: str = ""

    @property
    def citable(self) -> bool:
        """A record with no resolvable URL cannot be cited as evidence."""
        return bool((self.source_url or "").strip())


@dataclass
class SpanGateReport:
    """Outcome of the gate over one answer's claims."""

    verified: list = field(default_factory=list)   # VerifiedClaim, span located
    dropped: list = field(default_factory=list)    # VerifiedClaim, span not located
    # Every claim considered, in the order the extractor produced them, whatever the
    # gate decided. This is what the no-gate arm displays, and keeping it here means the
    # arm is a choice made at display time over ONE evaluation rather than a second,
    # differently-computed pass over the claims.
    all_claims: list = field(default_factory=list)
    total: int = 0

    @property
    def drop_rate(self) -> float:
        return round(len(self.dropped) / self.total, 4) if self.total else 0.0

    @property
    def verified_spans(self) -> list:
        return [c.supporting_span for c in self.verified if c.supporting_span]

    @property
    def uncitable_verified_count(self) -> int:
        """Uncitable claims that are still DISPLAYED.

        With ``citability_enforcement_enabled()`` on this is 0 by construction, and the
        G-CI check on it is therefore a build assertion rather than a measurement — the
        same status ``span_exposure`` gives its own ``== 1.000``. The quantity that still
        varies, and the one worth reading, is ``uncitable_dropped_count``.
        """
        return sum(1 for c in self.verified if not c.citable)

    @property
    def uncitable_dropped_count(self) -> int:
        """Claims withheld solely because their source cannot be cited."""
        return sum(1 for c in self.dropped if c.drop_reason == "cited_record_not_citable")

    @property
    def span_located_count(self) -> int:
        """Claims whose span WAS found in the cited chunk, citable or not.

        Kept separate so enforcing citability does not silently deflate the span
        measurement: a claim dropped for citability still had a real span, and folding
        the two together would misreport the span gate as having failed.
        """
        return sum(1 for c in list(self.verified) + list(self.dropped) if c.span_verified)

    @property
    def span_located_rate(self) -> float:
        return round(self.span_located_count / self.total, 4) if self.total else 0.0

    def as_metadata(self) -> dict:
        return {
            "claims_total": self.total,
            "claims_verified": len(self.verified),
            "claims_dropped": len(self.dropped),
            "claim_drop_rate": self.drop_rate,
            "uncitable_verified_claims": self.uncitable_verified_count,
            "uncitable_dropped_claims": self.uncitable_dropped_count,
            "span_located_claims": self.span_located_count,
            "span_located_rate": self.span_located_rate,
            "drop_reasons": sorted({c.drop_reason for c in self.dropped if c.drop_reason}),
            # The distinct-reason list above cannot answer "how much of the drop rate is
            # citability rather than a missing span", which is the decomposition the cost
            # table is made of. Counts, not a set.
            "drop_reason_counts": {
                reason: sum(1 for c in self.dropped if c.drop_reason == reason)
                for reason in sorted({c.drop_reason for c in self.dropped if c.drop_reason})
            },
        }


def _chunk_lookup(chunks) -> dict:
    out = {}
    for chunk in chunks or []:
        cid = str(getattr(chunk, "id", "") or "")
        if cid:
            out[cid] = chunk
    return out


def verify_claims(claims, chunks) -> SpanGateReport:
    """Check every claim's span against the chunk it names.

    ``claims`` are ``ClaimEvidence``-shaped (claim, supporting_span, chunk_id,
    section_title). ``chunks`` are ``RetrievedChunk``-shaped (id, text, metadata).
    """
    by_id = _chunk_lookup(chunks)
    min_chars = min_span_chars()
    report = SpanGateReport()

    for claim in claims or []:
        text = (getattr(claim, "claim", "") or "").strip()
        span = (getattr(claim, "supporting_span", "") or "").strip()
        chunk_id = str(getattr(claim, "chunk_id", "") or "")
        if not text:
            continue
        report.total += 1

        chunk = by_id.get(chunk_id)
        md = getattr(chunk, "metadata", {}) or {} if chunk else {}
        vc = VerifiedClaim(
            claim=text,
            supporting_span=span,
            chunk_id=chunk_id,
            section_title=(getattr(claim, "section_title", "") or ""),
            source_url=str(md.get("source_url", "") or ""),
            source_name=str(md.get("source_name", "") or ""),
            title=str(md.get("title", "") or ""),
        )

        if not span:
            vc.drop_reason = "no_supporting_span"
        elif chunk is None:
            # The claim names a chunk that is not in the response. Nothing can be
            # checked against, so it cannot be shown as evidence.
            vc.drop_reason = "chunk_id_not_resolvable"
        elif not span_is_contained(span, getattr(chunk, "text", "") or "", min_chars=min_chars):
            vc.drop_reason = "span_not_found_in_cited_chunk"
        else:
            vc.span_verified = True
            # The span is real. Whether it may be SHOWN is a second question: a record
            # with no resolvable source_url cannot be opened by the reader, so a claim
            # resting on it is not traceable evidence. span_verified stays True either
            # way, so the span measurement is unaffected by this decision.
            if not vc.citable and citability_enforcement_enabled():
                vc.drop_reason = "cited_record_not_citable"

        shown = vc.span_verified and not vc.drop_reason
        (report.verified if shown else report.dropped).append(vc)
        report.all_claims.append(vc)

    return report


def claims_for_display(report: SpanGateReport) -> tuple[list, list]:
    """``(shown, withheld)`` for the CURRENT arm. The gate's verdicts are unchanged.

    With the gate on (the shipped configuration) this is exactly ``verified`` /
    ``dropped``. With ``SPAN_GATE_ENABLED=false`` every claim the extractor produced is
    shown, unchecked and in extractor order, and nothing is withheld — which is how a RAG
    system that does not verify attribution behaves, and therefore what the no-gate
    baseline condition has to be.

    Why the toggle lives HERE and not inside ``verify_claims``: the report is a
    MEASUREMENT and must be identical in every arm, so the same response can be replayed
    offline into all four conditions. Only the display decision differs. Before this,
    ``span_gate_enabled()`` was defined and never called anywhere in the serving path —
    a flag that documented an arm the code could not actually run.
    """
    if span_gate_enabled():
        return list(report.verified), list(report.dropped)
    return list(report.all_claims), []


def enforcement_flags() -> dict:
    """Which gates were acting when this response was produced.

    Recorded in the response so an artifact says which arm produced it. A measurement
    whose configuration is only known from the operator's shell is not reproducible, and
    ``effective_config.pipeline_flags`` does not cover these three: they are read here,
    on every call, straight from the environment.
    """
    return {
        "span_gate_enabled": span_gate_enabled(),
        "numeric_enforcement_enabled": numeric_enforcement_enabled(),
        "citability_enforcement_enabled": citability_enforcement_enabled(),
    }


def numeric_gate(answer: str, report: SpanGateReport) -> tuple[bool, list]:
    """Whether every claim figure in the answer appears in some verified span.

    Reported rather than enforced: enforcement means rewriting an answer, which
    belongs to the verifier, not to a measurement primitive.
    """
    return numbers_are_grounded(answer, report.verified_spans)


def numeric_enforcement_enabled() -> bool:
    """Whether statements carrying a fabricated figure are removed from the answer.

    Default True. Prompt instruction was measured NOT to work: the old prompt already
    forbade inventing figures and was violated, and a rewritten block adding verbatim
    copyability, a ban on deriving, and an explicit "omitting a figure is correct"
    clause moved the fabricated count from 18 to 21 over the same five questions —
    i.e. no detectable effect, dominated by run-to-run noise.

    So the guarantee has to be enforced in code rather than requested from the model.
    Set NUMERIC_ENFORCEMENT=false to measure without changing the answer, which is a
    controlled arm and not a shipping configuration.
    """
    return os.getenv("NUMERIC_ENFORCEMENT", "true").strip().lower() not in (
        "0", "false", "no", "n", "off",
    )


# Sentence boundary inside a single line. Markdown structure (line breaks, bullet
# prefixes, headings) is preserved by never splitting across lines.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")
_LIST_PREFIX_RE = re.compile(r"^(\s*(?:[-*+]|\d+[.)])\s+)")


def strip_fabricated_numbers(answer: str, fabricated: list) -> tuple[str, list]:
    """Remove every statement containing a fabricated figure. Returns (answer, removed).

    Deterministic, so the hard zero does not depend on the model complying. Operates
    per line so headings and list structure survive; a list item whose text is wholly
    removed drops with its bullet.

    A removal note is appended by the caller, not here: silently deleting content
    from a medical answer would be worse than the fabrication it removes.
    """
    if not answer or not fabricated:
        return answer, []

    targets = set(fabricated)
    removed: list = []
    out_lines: list = []

    for line in answer.split("\n"):
        if not line.strip() or _HEADING_RE.match(line):
            out_lines.append(line)
            continue

        prefix_match = _LIST_PREFIX_RE.match(line)
        prefix = prefix_match.group(1) if prefix_match else ""
        body = line[len(prefix):]

        kept: list = []
        for sentence in _SENTENCE_SPLIT.split(body):
            if not sentence.strip():
                continue
            hits = set(claim_numbers_in(normalise(sentence), raw_text=sentence)) & targets
            if hits:
                removed.append({"text": sentence.strip()[:300], "numbers": sorted(hits)})
            else:
                kept.append(sentence)

        if kept:
            out_lines.append(prefix + " ".join(kept))
        elif not prefix:
            # Whole paragraph line removed; keep the gap rather than joining
            # neighbouring paragraphs together.
            out_lines.append("")

    cleaned = "\n".join(out_lines)
    # Collapse the blank runs the removals may have created.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, removed


def removal_notice(removed: list) -> str:
    """Visible, standard note about what enforcement took out."""
    if not removed:
        return ""
    numbers = sorted({n for item in removed for n in item.get("numbers", [])})
    return (
        "\n\n---\n"
        f"**Ghi chú hệ thống — kiểm chứng số liệu:** đã loại bỏ {len(removed)} phát biểu "
        f"chứa con số không truy nguyên được về evidence đã truy hồi "
        f"({', '.join(numbers[:10])}). Hệ thống chỉ hiển thị con số copy được nguyên văn "
        "từ tài liệu; phần bị loại không đồng nghĩa với việc thông tin đó sai, mà là "
        "hệ thống không tìm được nguồn cho nó."
    )


def evidence_text_seen_by_model(evidence_pack, chunks) -> str:
    """Everything the generator could have read a figure off.

    Must include the evidence pack's ``raw_text``, not just the chunks returned to
    the client: ``prompt._format_evidence_context`` builds the context from the
    pack, and the response carries an ordered SUBSET of chunks. Checking only the
    subset made figures the model legitimately read look fabricated — a false
    accusation, and the exact mistake this function exists to prevent.
    """
    parts: list = []
    primary = getattr(evidence_pack, "primary_source", None)
    for source in [primary] + list(getattr(evidence_pack, "secondary_sources", []) or []):
        if source is None:
            continue
        parts.append(getattr(source, "raw_text", "") or "")
        for bucket in ("direct_answer_spans", "key_findings", "limitations"):
            for claim in getattr(source, bucket, []) or []:
                parts.append(getattr(claim, "supporting_span", "") or "")
                parts.append(getattr(claim, "support_text", "") or "")
        for number in getattr(source, "numbers", []) or []:
            parts.append(f"{getattr(number, 'value', '')} {getattr(number, 'unit', '')}")
    for chunk in chunks or []:
        parts.append(getattr(chunk, "text", "") or "")
    return " ".join(p for p in parts if p)


def numeric_provenance(answer: str, report: SpanGateReport, chunks, evidence_pack=None) -> dict:
    """Split ungrounded figures into FABRICATED and merely UNATTRIBUTED.

    These are different defects and collapsing them would be misleading:

      * **fabricated** — the figure appears in no verified span AND nowhere in the
        retrieved chunk text. Nothing the system read contains it. This is the hard
        zero that belongs in a results table.
      * **unattributed** — the figure IS in the retrieved text but in no pinned
        span. The number is probably real; the ATTRIBUTION is missing. Measured live
        this is the common case: an answer used eight figures while the extractor
        had pinned three spans, none containing them.

    The second is the attribution gap the task contract is about. The first is a
    fabrication. A single "numbers_grounded=False" cannot tell them apart.

    An earlier caveat here said this split was unvalidated because a live answer's
    20.1% / 79.9% were classified fabricated while a separate check found them in the
    chunk text. That caveat was wrong: the two observations came from two DIFFERENT
    requests, whose retrieved chunk sets differ. Reproduced against a single captured
    response, the classification is correct — those figures appear in none of the 29
    retrieved chunks (29,401 characters, 210 distinct numbers). Cross-request
    comparison was the error, not the gate.

    ``numeric_haystack_inconsistency`` is returned so that the failure mode the
    caveat imagined stays observable rather than assumed absent: it lists any figure
    called fabricated that is nevertheless present in the chunk text.
    """
    _, ungrounded = numbers_are_grounded(answer, report.verified_spans)
    if not ungrounded:
        return {
            "numeric_fabricated": [],
            "numeric_unattributed": [],
            "numeric_fabricated_count": 0,
            "numeric_unattributed_count": 0,
        }

    chunk_only_text = " ".join((getattr(c, "text", "") or "") for c in (chunks or []))
    corpus_text = (
        evidence_text_seen_by_model(evidence_pack, chunks)
        if evidence_pack is not None
        else chunk_only_text
    )

    # Direct set membership against the corpus's numbers.
    #
    # Two bugs were fixed here, both found by reading the code after a live
    # measurement looked wrong:
    #
    # 1. A bulk pre-check asked "are ALL the ungrounded figures in the corpus?" and,
    #    on a hit, marked EVERY figure unattributed — so one grounded number vouched
    #    for the rest.
    # 2. The per-figure re-check ran the figure back through
    #    ``numbers_are_grounded``, which filters the ANSWER side with
    #    ``claim_numbers_in``. Passed a lone token, that filter drops a bare 4-digit
    #    value in the year range: ``claim_numbers_in("1966")`` is ``[]`` with no raw
    #    text to show a digit-group separator. An empty list means "nothing
    #    ungrounded", so such a figure was silently classified unattributed — not
    #    because it was found, but because it was filtered out.
    #
    # These figures already passed ``claim_numbers_in`` on the answer side, so no
    # further filtering is correct: compare them directly.
    corpus_numbers = set(numbers_in(normalise(corpus_text)))
    chunk_numbers = set(numbers_in(normalise(chunk_only_text)))

    fabricated = [n for n in ungrounded if n not in corpus_numbers]
    unattributed = [n for n in ungrounded if n in corpus_numbers]

    # FULL lists, not truncated. Truncation belongs to the metadata layer: reading a
    # display-truncated list back for enforcement silently left every figure past the
    # eighth in the answer. Measured live — pre=8, 5 statements removed, and 3 figures
    # still present that were never in the truncated list.
    return {
        "numeric_fabricated": fabricated,
        "numeric_unattributed": unattributed,
        "numeric_fabricated_count": len(fabricated),
        "numeric_unattributed_count": len(unattributed),
        # Diagnostics. A figure absent from the full evidence haystack but present in
        # the chunk text alone would mean the haystack is assembled wrong; this stays
        # so that failure mode is visible rather than inferred.
        "numeric_evidence_chars": len(corpus_text),
        "numeric_haystack_inconsistency": [
            n for n in fabricated if n in chunk_numbers
        ][:8],
    }


def _numeric_issues(numeric_provenance, numeric_removed) -> list:
    """The numeric half of the mechanical findings, governed by NUMERIC_ENFORCEMENT.

    Split out so the no-gate arm can drop the span/citability findings without dropping
    these: the two gates are independently switchable, and an arm that silenced both from
    one flag would not be the arm it says it is.
    """
    issues: list = []
    if numeric_removed:
        numbers = sorted({n for item in numeric_removed for n in item.get("numbers", [])})
        issues.append(
            f"numeric_enforcement: removed {len(numeric_removed)} statement(s) carrying "
            f"figures absent from the evidence ({','.join(numbers[:8])})"
        )

    # After enforcement this must be empty. If it is not, enforcement failed to reach
    # the figure and the answer still shows an ungrounded number — a hard-zero breach
    # that the verifier must see rather than a metric nobody reads.
    residual = list((numeric_provenance or {}).get("numeric_fabricated") or [])
    if residual:
        issues.append(
            f"numeric_gate: {len(residual)} fabricated figure(s) STILL PRESENT after "
            f"enforcement ({','.join(residual[:8])})"
        )
    return issues


def mechanical_verifier_issues(span_report, numeric_provenance, numeric_removed) -> list:
    """Findings decided in code, handed to the verifier so they affect its verdict.

    Before this, the span gate and numeric gate ran AFTER verification, so a response
    could report ``verification_status="pass"`` next to a dropped claim or a
    fabricated figure. A mechanical finding must reach the one component whose job is
    to decide pass / revise / block.
    """
    issues: list = []

    # With the span gate off, no claim is withheld and no citability decision is taken,
    # so there is no mechanical finding to hand over. Reporting one anyway would make the
    # no-gate arm differ from a plain RAG system by the VERIFIER's reaction to a gate that
    # did not act — the arm would then measure two things at once. The numeric findings
    # below are governed by their own flag and are unaffected.
    if not span_gate_enabled():
        return _numeric_issues(numeric_provenance, numeric_removed)

    dropped = len(getattr(span_report, "dropped", []) or [])
    if dropped:
        reasons = ",".join(sorted({c.drop_reason for c in span_report.dropped if c.drop_reason}))
        issues.append(
            f"span_gate: {dropped} claim(s) dropped, span not located in the cited chunk ({reasons})"
        )

    uncitable_shown = getattr(span_report, "uncitable_verified_count", 0)
    if uncitable_shown:
        issues.append(
            f"citability_gate: {uncitable_shown} DISPLAYED claim(s) cite a record with no "
            f"resolvable source_url (enforcement is off)"
        )

    # Withheld claims must reach the verifier too. Without this the verifier would see a
    # thinner answer than the extractor produced and no reason for it, which is exactly
    # the blind spot mechanical findings exist to close.
    uncitable_dropped = getattr(span_report, "uncitable_dropped_count", 0)
    if uncitable_dropped:
        issues.append(
            f"citability_gate: {uncitable_dropped} claim(s) withheld — span verified but the "
            f"cited record has no resolvable source_url, so it cannot be shown as evidence"
        )

    issues.extend(_numeric_issues(numeric_provenance, numeric_removed))
    return issues
