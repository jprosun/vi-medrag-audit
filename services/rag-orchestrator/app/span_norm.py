"""Span normalisation and STRICT containment checking.

Purpose
-------
``answer_verifier`` validated a citation only by index range: ``int(citation) >
rag_source_count``. So ``[3]`` attached to a completely fabricated sentence passed
whenever three sources happened to be retrieved. The system therefore paid the full
cost of retrieval while providing the epistemic guarantee of no retrieval.

This module supplies the missing primitive: given a claim's ``supporting_span`` and
the chunk it cites, decide **by code** whether that span actually occurs in that
chunk. A claim whose span cannot be located is not evidence and must not be shown.

What "STRICT" means here
------------------------
Exact substring containment after a documented, reversible normalisation. It is a
deliberately narrow guarantee:

    it proves the cited string EXISTS in the cited document.
    it does NOT prove the string SUPPORTS the claim.

Those are different properties and conflating them is the most likely way for an
examiner to dismantle an attribution number. Entailment is measured separately, on a
sample, with agreement reported. Never report ``span_exists`` alone as "attribution".

Normalisation steps, in order
-----------------------------
1. Unicode NFC, so precomposed and decomposed Vietnamese compare equal.
2. Strip the rendered chunk context header (``Title:`` / ``Source:`` / ``Audience:``
   / ``Body:`` / ``Keywords:``) — it is retrieval scaffolding, not document text.
3. Lowercase.
4. Unify digit-group and decimal separators. Vietnamese writes ``96,18%`` and
   ``1.966``; the same figure may appear as ``96.18`` and ``1966`` elsewhere in the
   pipeline or in an LLM's rendering. Both forms collapse to a single canonical form
   so a real match is not lost to punctuation.
5. Normalise dash and quote variants, which OCR and copy-paste vary freely.
6. Collapse all whitespace runs to one space and trim.

Diacritics are NOT stripped. Two different Vietnamese words can differ only by tone,
so folding them would make the containment check accept spans that are not in the
document — the exact failure this gate exists to prevent.
"""

from __future__ import annotations

import re
import unicodedata

# Rendered context header that ingest prepends to each chunk.
_HEADER_RE = re.compile(
    r"(?is)\b(?:title|source|audience|updated|section|keywords?)\s*:\s*.*?(?=\n|$)"
)
_BODY_MARKER_RE = re.compile(r"(?is)\bbody\s*:\s*")

# 1.966 / 1,966 -> group separator between digit triples.
_GROUP_SEP_RE = re.compile(r"(?<=\d)[.,   ](?=\d{3}\b)")
# 96,18 -> decimal separator between digits.
_DECIMAL_SEP_RE = re.compile(r"(?<=\d)[,](?=\d)")
# "34,7 %" and "34,7%" are the same figure, and an LLM renders either. Only the
# percent sign is closed up; leaving other unit spacing alone keeps the
# normalisation narrow.
_PERCENT_SPACE_RE = re.compile(r"(?<=\d)\s+%")

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
_QUOTES = {
    **dict.fromkeys(map(ord, "‘’‚‛′"), "'"),
    **dict.fromkeys(map(ord, "“”„‟″"), '"'),
}
_SPACES = dict.fromkeys(map(ord, "     　"), " ")
_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍﻿"), None)

_TRANSLATIONS = {**_DASHES, **_QUOTES, **_SPACES, **_ZERO_WIDTH}


def strip_context_header(text: str) -> str:
    """Remove the rendered ``Title:/Source:/...`` scaffolding from chunk text."""
    if not text:
        return ""
    body_split = _BODY_MARKER_RE.split(text, maxsplit=1)
    if len(body_split) == 2:
        return body_split[1]
    return _HEADER_RE.sub(" ", text)


def normalise(text: str, *, drop_header: bool = False) -> str:
    """Canonical form used on BOTH sides of a containment check.

    ``drop_header`` is for chunk text; a span should never contain the header.
    """
    if not text:
        return ""
    out = text
    if drop_header:
        out = strip_context_header(out)
    out = unicodedata.normalize("NFC", out)
    out = out.translate(_TRANSLATIONS)
    out = out.lower()
    out = _GROUP_SEP_RE.sub("", out)
    out = _DECIMAL_SEP_RE.sub(".", out)
    out = _PERCENT_SPACE_RE.sub("%", out)
    return " ".join(out.split())


# Digits, optional decimal part, optional trailing percent.
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?\s*%?")

# Inline citation markers: "[1]", "[e2]", "[1, 3]". Their indices are not claims.
_CITATION_MARKER_RE = re.compile(r"\[[^\[\]]{0,20}?\]")

# 1900-2099 read as a year. See the note in claim_numbers_in.
_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")


def numbers_in(text: str) -> list[str]:
    """Every numeric token in canonical form. Run ``normalise`` first.

    Includes citation indices and years. For grounding checks use
    ``claim_numbers_in`` instead.
    """
    return [re.sub(r"\s+", "", m.group(0)) for m in _NUMBER_RE.finditer(text or "")]


_GROUPED_COUNT_RE = re.compile(r"\d{1,3}(?:[.,   ]\d{3})+")


def grouped_counts_in(raw_text: str) -> set[str]:
    """Numbers written WITH a digit-group separator in the raw text, canonicalised.

    A year is never written "1.966"; a count is. Reading this off the raw text
    recovers sample sizes that the year heuristic in ``claim_numbers_in`` would
    otherwise discard, and it is the only place the separator survives — the
    normaliser strips it so that "1.966" and "1966" compare equal.
    """
    out = set()
    for m in _GROUPED_COUNT_RE.finditer(raw_text or ""):
        out.add(re.sub(r"[.,   ]", "", m.group(0)))
    return out


def claim_numbers_in(text: str, raw_text: str | None = None) -> list[str]:
    """Numeric tokens that could carry a quantitative CLAIM.

    Measured live, a naive "every digit run" definition made the numeric gate
    useless: it flagged the indices of inline citation markers ("[1]", "[3]"),
    publication years, and section numbers, so ``numbers_grounded`` was False for
    every answer regardless of content.

    A claim number is therefore one of:
      * a percentage        — 34.7%
      * a decimal          — 96.18
      * an integer >= 3 digits — 1966 (sample sizes, counts)

    A bare 4-digit value in 1900-2099 is treated as a year and excluded, UNLESS
    ``raw_text`` shows it was written with a digit-group separator ("1.966"), which a
    year never is. Pass ``raw_text`` whenever it is available; without it a sample
    size in the year range is not checked, which is a false negative and is stated
    rather than hidden. The alternative — flagging every publication year as an
    ungrounded claim — is the failure this replaces, measured live.
    """
    stripped = _CITATION_MARKER_RE.sub(" ", text or "")
    counts = grouped_counts_in(raw_text) if raw_text else set()
    out: list = []
    for token in numbers_in(stripped):
        core = token.rstrip("%")
        if token.endswith("%"):
            out.append(token)
        elif "." in core:
            out.append(token)
        elif len(core) >= 3 and (core in counts or not _YEAR_RE.match(core)):
            out.append(token)
    return out


def span_is_contained(span: str, chunk_text: str, *, min_chars: int = 12) -> bool:
    """Whether ``span`` occurs verbatim in ``chunk_text`` after normalisation.

    ``min_chars`` guards against a span so short that containment is meaningless —
    a three-character span matches almost any document and would inflate the
    verification rate without evidencing anything.
    """
    span_n = normalise(span)
    if len(span_n) < min_chars:
        return False
    return span_n in normalise(chunk_text, drop_header=True)


def numbers_are_grounded(text: str, verified_spans: list) -> tuple[bool, list]:
    """Whether every number in ``text`` appears in at least one verified span.

    Returns ``(ok, ungrounded_numbers)``. This is the numeric gate: a figure the
    model produced that appears in no verified span was not read off any document.
    """
    haystack = " ".join(normalise(s) for s in (verified_spans or []) if s)
    # Grounding uses ALL numbers on the evidence side — a figure is grounded if it
    # appears anywhere in a verified span — but only CLAIM numbers on the answer
    # side, so citation indices and years are not treated as claims.
    grounded = set(numbers_in(haystack))
    ungrounded = [
        n for n in claim_numbers_in(normalise(text), raw_text=text) if n not in grounded
    ]
    return (not ungrounded), ungrounded
