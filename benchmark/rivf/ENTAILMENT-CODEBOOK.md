# Entailment codebook — written before any item was judged

This defines the labels. It is committed before judgements are collected so that the
rubric cannot be adjusted once the distribution is known, in the same way the probe set was
hashed before any condition ran.

## What is being judged

The system displays a claim together with a citation to a chunk of a document. Span
containment already proves that the cited string **occurs** in that chunk. It proves
nothing about whether the chunk **supports** the assertion. That gap is what this
measurement closes.

**Unit of judgement:** the pair (claim, cited passage). Not (claim, supporting span): 183
of the 185 displayed claims have a span textually identical to the claim, so judging the
span against the claim would be judging a string against itself.

The judge sees the question the user asked, the claim, the span the system offered, and the
full cited passage. The judge does **not** see whether the item is a control, nor any
verdict the system produced.

## Labels — exactly one per item

| Label | Meaning |
|---|---|
| `supported` | The passage states the claim, or the claim is a faithful paraphrase, translation or direct consequence of what the passage states. A reader checking the citation would find what they were promised. |
| `overstated` | The passage supports a **weaker** version of the claim. The claim generalises beyond the passage's population, strengthens a hedge into a fact, drops a qualifier (dose, condition, subgroup, timeframe), or converts an association into a cause. The quotation is real; the claim is bigger than it. |
| `not_supported` | The passage does not support the claim. It may be topically related, mention the same entity, or contain the same numbers, and still make no assertion that establishes the claim. Also used when the passage contradicts the claim. |
| `unintelligible` | The passage is too corrupted to judge — interleaved columns, spliced sentences, truncation mid-word. This label exists because this corpus has a documented ingestion defect and a residual after repair; it must be counted, not silently folded into `not_supported`. |

`overstated` is the label the paper's own limitation predicts: *"an over-strong claim
attached to a real quotation passes every check we run."* It is deliberately separate from
`not_supported`, because the two call for different fixes.

## Secondary judgements

* `span_is_the_right_locus` (yes / no / n\_a) — whether the offered span is the part of the
  passage that does the supporting. `n_a` when the label is `not_supported` or
  `unintelligible`. This separates "the evidence is absent" from "the evidence is present
  but the system pointed at the wrong sentence".
* `confidence` (high / medium / low) — low confidence is the trigger for adjudication.

## Rules

1. Judge only from the text given. Do not use outside medical knowledge to fill a gap in
   the passage: the question is whether **this passage** supports the claim, not whether
   the claim is true.
2. A claim that is medically correct but not established by the passage is
   `not_supported`. Correctness is a different measurement and this paper makes no claim
   about it.
3. The claim and the passage are Vietnamese; some passages contain a bilingual abstract.
   Judge across languages — a Vietnamese claim supported by the English half of the same
   abstract is `supported`.
4. Numbers must match to be `supported`. A passage giving 96,18\% does not support a claim
   of 96\%, though it may support a claim of "about 96\%" — use `overstated` when the claim
   rounds or generalises, `not_supported` when the number is simply different.
5. Do not consult any file in the repository. Everything needed is in the item.

## Instrument
* Every item is judged **twice, independently** by judges that do not see each other's
  output. Raw agreement and the disagreement rate are reported.
* Disagreements are adjudicated by a third pass that sees both labels and both rationales
  but not which judge produced which.
* 37 of the 222 items are derangement controls: a real claim paired with a passage cited by
  a different question. They should be `not_supported`. The rate at which they are not is
  the instrument's false-support rate and is reported next to the headline.

## What this measurement is not

It is a **model-judged** entailment rate with a control arm, not a clinician's judgement of
clinical correctness. The paper must say so. A human-verified subsample remains the next
step, and the report names it as outstanding.
