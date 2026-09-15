# Judge configuration — what produced the entailment and relevance labels

An external review asked, correctly, where the judge is recorded: *"model id, version, prompt
and decoding config recorded nowhere; judging prompts live only in gitignored `tmp/workflows/`."*
This directory answers as much of that as the artifacts can actually support, and states
plainly the part they cannot.

## The four runs

| script | arm | instrument | items |
|---|---|---|---|
| `entailment-judgement-shipped.js`  | withhold after generation | entailment | 222 = 185 displayed claims + 37 derangement controls |
| `relevance-judgement-shipped.js`   | withhold after generation | relevance  | 222 = 185 displayed claims + 37 cross-specialty controls |
| `entailment-judgement-urlfirst.js` | exclude at retrieval      | entailment | 401 = 364 displayed claims + 37 derangement controls |
| `relevance-judgement-urlfirst.js`  | exclude at retrieval      | relevance  | 401 = 364 displayed claims + 37 cross-specialty controls |

These are the scripts as run, copied byte-for-byte out of the harness's own run directory,
renamed only to drop the run id. Each contains the complete judging prompt, the JSON schema
the judge had to fill, the batching, and the adjudication pass. The two codebooks the prompts
implement are `../ENTAILMENT-CODEBOOK.md` and `../RELEVANCE-CODEBOOK.md`, both committed
before any item was judged.

## Harness

Claude Code's `Workflow` tool. Each batch is one subagent invocation with no conversation
history and no access to the other batches: a pass is 8 batches of up to 28 items for the shipped
arm, and the two passes are separate invocations over the same frozen item file. Items reach
the judge through a per-batch file containing only the fields the codebook allows it to see;
the prompt names that file and instructs the judge to read nothing else — in particular not
the key file that records which items are controls.

Blinding, therefore, is by construction rather than by instruction: the judge cannot see the
other pass's labels, the system's own verdicts, or the control flags, because they are not in
its context.

Adjudication is a third invocation over the disagreements only — 2 items for shipped
entailment, 5 for shipped relevance — with both prior labels shown but not which pass
produced which.

## Decoding

Not set. No script passes a temperature, top-p, or seed, so each pass ran at the harness
defaults. The runs are therefore **not bitwise reproducible**, and the artifacts do not claim
to be: what is frozen and hashed is the item set, not the labels. The reproducibility claim in
this repository is that `entailment_report.py` and `relevance_report.py` recompute every
reported figure from the committed label files, which they do exactly (`--check`).

## The model ID IS recoverable. The checkpoint is not. The runs did not share a judge.

**Correction, 2026-09-10.** This section previously said the model "cannot be read off any
artifact in this repository". That was true of the artifacts and false of the evidence: none of
the four scripts passes a `model` option, but every assistant message in a subagent transcript
records `message.model`. `recover_judge_models.py` reads it and cross-checks every emitted
label against the committed artifact — 100 % match on all five runs, so each transcript is
demonstrably the transcript of its artifact. See `../judge_model_provenance_v1.json`.

| Run | Model served |
|---|---|
| Entailment, shipped arm | `claude-opus-5` |
| Relevance, shipped arm | `claude-fable-5-1` |
| Entailment, URL-first arm | `claude-fable-5-1` |
| Relevance, URL-first arm | `claude-fable-5-1` |
| The pinned re-run, both instruments | `claude-opus-5` (alias `opus` requested) |

Two consequences, and the second is the serious one:

1. **The pinned re-run's entailment half compared `claude-opus-5` with `claude-opus-5`.** It
   measures within-model repeatability. Only the relevance half crossed models, and only that
   half moved.
2. **The four runs did not share a judge.** The between-arm *support* contrast crossed two
   models — shipped `claude-opus-5` against URL-first `claude-fable-5-1`. The between-arm
   *responsiveness* contrast did not: `claude-fable-5-1` on both sides.

**And the codebooks differed by arm**, which is a second between-arm confound with no bearing
on the model. The URL-first entailment codebook is 2591 characters against the shipped arm's
3876; what it drops includes the operational reading of `supported` ("a reader who followed the
citation would find what they were promised"), the anti-lenience instruction on `overstated`
("use it rather than stretching supported"), and the justification for `unintelligible` as a
live label. The shipped *relevance* codebook additionally told its judge that support was
"already established at 96.8 % of cases" — a numeric prior from the other instrument, present
in one arm only. In the labels, `overstated` moves 0.000 → 0.003 and `not_supported`
0.005 → 0.008 between arms, which is the direction removing that nudge predicts.

`matched-arm-rejudge.js` re-judges the URL-first arm under the shipped arm's exact
configuration — shipped codebook byte for byte, model pinned, original adjudicator prompt,
batch size 28 — so the measured judging configuration is matched across arms. This does not eliminate
between-generation variation or establish a causal arm effect.

**What remains a real defect.** A model ID is not a checkpoint, and this interface accepts only
an alias (`opus`), which names a family. Exact reproduction is out of reach for the original
runs *and* for the re-run. Anyone repeating this should record the served model ID beside the
labels at write time rather than recovering it afterwards.

## What the labels are checked against, given that

Because the judge cannot be pinned, the load falls on the checks that do not depend on it:

* **37 controls per instrument per arm**, each pairing a real claim with a passage or question
  it cannot match. All 37 were rejected in all four runs; a judge that passed controls would
  invalidate its own run regardless of which checkpoint produced it.
* **Two independent passes plus adjudication.** Shipped entailment: 99.1 % raw agreement,
  κ = 0.973; shipped relevance 97.8 %, κ = 0.955. Both figures are over all 222 items and are
  inflated by the 37 controls, which are easy negatives — see the ledger's judge-stability
  section, where the between-run figures are given on the 185 real claims instead.
* **One author's blind grading** of a stratified subsample — 30 entailment items, 40 relevance
  items — scored by `../score_human_entailment.py` and `../score_human_relevance.py`. This is
  the only check that does not share a failure mode with the judge, and it is the reason the
  paper reports the two instruments as calibrated rather than as validated. The author also graded 40 URL-first items: 95% agreement with the original labels and
  92.5% with matched labels (kappa 0.8671 and 0.8131); see
  `../score_urlfirst_relevance.py`. Neither sheet is an independent-human validation.
