# Relevance codebook — written before any item was judged

This defines the labels for the (claim, QUESTION) judgement. Committed before judgements
are collected, so the rubric cannot be tuned once the distribution is known.

## What is being judged, and why it is a separate measurement

The entailment measurement judged (claim, cited passage): does the passage support the
claim? It found 0.968 supported. It was designed to see exactly that and nothing else, and
an independent review showed what it cannot see with one real item: the question asks about
neonatal bilirubin neurotoxicity, the displayed claim is about MRI findings in pesticide
poisoning, the passage supports the claim perfectly, and both judges were right to say so.
The system had shown the reader a well-supported, cited, irrelevant claim, and no number in
the paper recorded it.

**Unit of judgement:** the pair (claim, question). The passage is shown for context only,
so that "relevant but unsupported" and "supported but irrelevant" remain distinguishable;
support is NOT what is being labelled here.

## Labels — exactly one per item

| Label | Meaning |
|---|---|
| `relevant` | The claim answers the question directly, or is a necessary part of a direct answer. A reader who asked this would want this sentence. |
| `partial` | The claim is about the question's topic but does not answer it: same disease, different aspect; background or definition; a related population or setting; a study's method or objective rather than its finding. |
| `not_relevant` | The claim is about something else: a different disease, population, intervention or subject. Sharing a word or a body system with the question does not make it relevant. |

## Rules

1. Judge the claim **against the question**, not the passage against the question. The
   passage tells you what the claim is about; it does not vote.
2. Do not rescue a claim with outside knowledge. A claim that is medically true but does not
   answer this question is `partial` or `not_relevant`.
3. A claim that states a study's objective, sample, or method ("Nghiên cứu được tiến hành
   trên 34 bệnh nhân...") is `partial` at most unless the question asked about that study.
4. Bilingual passages are normal; the claim and question are Vietnamese.
5. Some items pair a real claim with a question it was never generated for. You are not told
   which. If a claim has nothing to do with its question, that is `not_relevant`, however
   fluent either one is.
6. Do not consult any file in the repository. Everything needed is in the item.
7. Record `confidence` (high / medium / low) honestly; low triggers adjudication.

## Instrument

* Two independent blind passes; disagreements adjudicated by a third pass that sees both
  labels and rationales but not which judge produced which.
* 37 question-derangement controls (a real claim, a different question's text) mixed in.
  They should be `not_relevant`; the rate at which they are not is the instrument's
  false-relevance rate and is reported next to the headline.
* A 40-item human sheet (`relevance_sheet_v1.md`, 8 per question type) is graded by the
  author independently; agreement between the human labels and the model labels on those
  40 is reported. **The model pass is not human validation and the paper must not call it
  that.**

## What this measurement is not

Not a judgement of answer correctness, of the narrative answer, or of clinical usefulness.
It measures one thing: whether the claims a reader is shown with citations are about what
they asked.
