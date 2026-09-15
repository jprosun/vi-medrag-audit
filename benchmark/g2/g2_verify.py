"""G2 verification: what makes a Study-Card field COUNT as filled.

The whole gate turns on this file. If "filled" means "the model wrote something", G2
measures DeepSeek's willingness to answer, not the corpus's attributability, and the
kill decision would be made on a number that cannot fail. So a field counts as FILLED
only when all three hold:

    (a) a non-empty value came back, AND
    (b) a supporting span came back, AND
    (c) that span is ACTUALLY PRESENT in the article text under the project's
        normalisation.

(c) is delegated to ``app.span_norm`` -- ``normalise`` / ``span_is_contained`` -- rather
than reimplemented. The project fixed that normalisation once (NFC, digit-separator
unification, dash/quote folding, whitespace collapse, diacritics deliberately NOT
folded) and a second copy would drift away from the answer-verifier that ships.

Three rates are reported side by side because the GAP between them is the finding:

    raw_fill      -- model returned a value
    span_returned -- model also returned a span
    verified_fill -- that span is in the document

A verified_fill far below raw_fill does not mean the extractor is badly configured. It
means the model is producing values it cannot point at, i.e. guessing.

NUMERIC GATE AND ITS KNOWN HOLE
-------------------------------
For ``n`` and ``primary_numeric_finding`` the value's figures must also appear in the
span, via ``claim_numbers_in`` / ``numbers_are_grounded``. Those functions deliberately
ignore integers of fewer than 3 digits and bare 1900-2099 years (documented in
span_norm: treating every citation index and publication year as a claim made the gate
useless in production). The consequence here must be stated rather than discovered
later: **a sample size below 100 is not number-checked by the project function.** Most
Vietnamese single-centre studies have exactly that kind of n. So a second, stricter
column ``numeric_exact`` is reported alongside: every numeric token of the value must
occur among the numeric tokens of the span. It uses ``numbers_in`` from the same module
-- still no second matcher -- and it is a DIAGNOSTIC, not the headline definition.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = REPO_ROOT / "services" / "rag-orchestrator"
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.span_norm import (  # noqa: E402
    claim_numbers_in,
    normalise,
    numbers_are_grounded,
    numbers_in,
    span_is_contained,
)

FIELDS = (
    "n",
    "primary_numeric_finding",
    "population_facet",
    "study_design",
    "primary_outcome",
)

NUMERIC_FIELDS = frozenset({"n", "primary_numeric_finding"})

# Gate thresholds from FINAL-SPRINT-PLAN 3.2.
GATE_THRESHOLDS = {
    "n_or_primary_numeric": 0.60,
    "population_facet": 0.50,
    "human_macro_field_precision": 0.85,
}


def _as_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        return str(v)
    return str(v).strip()


def verify_field(
    field: str, value, span, article_text: str, *, min_chars: int = 20
) -> dict:
    """One field's verdict. ``min_chars`` matches the prompt's 20-char span floor."""
    v = _as_text(value)
    s = _as_text(span)
    raw_fill = bool(v) and v.lower() not in {"null", "none", "n/a", "na", "-"}
    span_returned = raw_fill and bool(s)
    contained = span_returned and span_is_contained(s, article_text, min_chars=min_chars)

    numeric_ok = True
    numeric_exact = True
    ungrounded: list[str] = []
    if field in NUMERIC_FIELDS and contained:
        numeric_ok, ungrounded = numbers_are_grounded(v, [s])
        span_tokens = set(numbers_in(normalise(s)))
        value_tokens = [t for t in numbers_in(normalise(v))]
        numeric_exact = all(t in span_tokens for t in value_tokens) if value_tokens else False

    return {
        "field": field,
        "raw_fill": raw_fill,
        "span_returned": span_returned,
        "span_contained": bool(contained),
        "numeric_checked": field in NUMERIC_FIELDS,
        "numeric_claim_tokens": claim_numbers_in(normalise(v), raw_text=v)
        if field in NUMERIC_FIELDS
        else [],
        "numeric_grounded": bool(numeric_ok),
        "numeric_ungrounded": ungrounded,
        "numeric_exact": bool(numeric_exact),
        # headline definition: value + span + span really in the document + project
        # numeric gate for the two numeric fields
        "verified_fill": bool(contained and numeric_ok),
        # diagnostic: same, but every digit of the value must be in the span
        "verified_fill_strict_numeric": bool(contained and numeric_ok and numeric_exact),
    }


# --- abstract detection -------------------------------------------------------
# section_type="abstract" was measured to mislabel ~69% of body text, so the label is
# never used alone. Three independent views are reported and their disagreement IS the
# abstract-availability finding.

_ABSTRACT_HEADING_RE = re.compile(
    r"(?:^|[\s\n>|])(?:TÓM\s*TẮT|TOM\s*TAT|TÓM\s*LƯỢC|ABSTRACT|SUMMARY)(?:[\s\n:.\-]|$)"
)

# The heading regex above is a WEAK instrument on this corpus and is reported only as
# such: the "TÓM TẮT" / "SUMMARY" heading lives in the rendered chunk header
# (``Section: TÓM TẮT``), which strip_context_header removes, so it survives in the body
# of only 11 of the 150 sampled articles. The real signal is structural -- a Vietnamese
# journal abstract opens with the Đặt vấn đề / Mục tiêu / Phương pháp / Kết quả / Kết
# luận beats (or their English equivalents) inside the first few thousand characters.
_ABSTRACT_BEATS = (
    re.compile(r"(mục\s*tiêu|đặt\s*vấn\s*đề|objectiv|background|introduction|\baims?\b)", re.I),
    re.compile(r"(đối\s*tượng\s*và\s*phương\s*pháp|phương\s*pháp\s*nghiên\s*cứu|method|materials)", re.I),
    re.compile(r"(kết\s*quả|results?)", re.I),
    re.compile(r"(kết\s*luận|conclusions?)", re.I),
)

# Head window for the structural check. Calibrated on the drawn sample: 2,000 chars ->
# 100/150 reach 3 beats, 3,000 -> 117/150, 4,000 -> 125/150. 3,000 is used because
# beyond it the window starts swallowing the paper's own section headings, at which
# point the detector stops measuring "has an abstract" and starts measuring "is an
# IMRaD paper". The sensitivity of the choice is reported rather than hidden.
ABSTRACT_HEAD_WINDOW = 3000

# A real abstract is a few hundred to a few thousand characters. The label region on
# this corpus routinely runs to 9,000+ chars, which is a body, not an abstract.
ABSTRACT_PLAUSIBLE_MIN = 300
ABSTRACT_PLAUSIBLE_MAX = 4000


def head_beats(article_text: str, window: int = ABSTRACT_HEAD_WINDOW) -> int:
    head = (article_text or "")[:window]
    return sum(1 for r in _ABSTRACT_BEATS if r.search(head))


def abstract_views(article_text: str, abstract_by_label: str, model_result: dict) -> dict:
    label_len = len(abstract_by_label or "")
    heading = bool(_ABSTRACT_HEADING_RE.search(article_text or ""))
    beats = head_beats(article_text)
    model_says = bool(model_result.get("has_abstract"))
    model_span = _as_text(model_result.get("abstract_span"))
    model_span_ok = bool(model_span) and span_is_contained(
        model_span, article_text, min_chars=20
    )
    return {
        "abstract_label_present": label_len > 0,
        "abstract_label_chars": label_len,
        "abstract_label_plausible": ABSTRACT_PLAUSIBLE_MIN
        <= label_len
        <= ABSTRACT_PLAUSIBLE_MAX,
        "abstract_heading_regex": heading,
        "abstract_head_beats": beats,
        "abstract_beats_ge3": beats >= 3,
        "abstract_model_says": model_says,
        "abstract_model_span_verified": model_says and model_span_ok,
    }


def abstract_field_content(
    field_results: list[dict], spans: dict, abstract_text: str
) -> dict:
    """Of the VERIFIED fields, how many are supported from inside the abstract.

    This is a LOWER BOUND on "recoverable from the abstract alone": the model was shown
    the whole article and may have cited a body occurrence of a fact that also appears
    in the abstract. The unbiased alternative is a second extraction pass over the
    abstract text only; its cost is reported separately so the choice is explicit.
    """
    if not abstract_text:
        return {"n_verified": 0, "n_in_abstract": 0, "rate": None}
    n_ver = 0
    n_in = 0
    for fr in field_results:
        if not fr["verified_fill"]:
            continue
        n_ver += 1
        s = _as_text(spans.get(fr["field"]))
        if s and span_is_contained(s, abstract_text, min_chars=20):
            n_in += 1
    return {
        "n_verified": n_ver,
        "n_in_abstract": n_in,
        "rate": (n_in / n_ver) if n_ver else None,
    }
