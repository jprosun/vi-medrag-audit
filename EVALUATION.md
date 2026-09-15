# Evaluation protocol

## Study design and units

The fixed set contains 134 questions: 119 designated answerable questions and 15 out-of-corpus controls. Questions were committed before the first run; there was no registered analysis plan. Both captures share the same question IDs.

Each response contains payload.claim_attributions, payload.dropped_claims, payload.retrieved_chunks, and payload.metadata. Proposed claims are the union of returned and dropped claims. The measured attribution layer is distinct from the narrative answer and from UI cards.

- **Shipped:** retrieve normally, then withhold claims lacking a located span or source URL.
- **URL-first:** exclude the URL-less source stratum during retrieval, refilling the retrieval pool.

The same questions use standard/deep profiles across arms: 67 each. This is half the questions, not half the claims. Recorded top-k is a base pool size, not the returned chunk count.

## Mechanical measurements

The three modules under services/rag-orchestrator/app define normalization, span/citability/numeric gates, and response-level measurements. They have no dependency on the full serving application.

Containment is normalized exact substring membership, preserving Vietnamese diacritics. Citability is a nonempty URL, not a guarantee that a URL opens or reaches the correct article. Numeric membership checks values as tokens; it does not establish the semantic correctness of quantities or units.

C0–C3 replay configurations on one captured generation. The numeric gate removes statements, never claim records, so C1 and C2 have identical claim retention. Span removes 19 claims; citability a further 147. Empty claim lists progress 20 → 29 → 29 → 79. This replay does not measure generation variability.

The attribution_facts.py text check exits 2 with an explanation on redacted captures. Its source is included. With legitimately available original captures, use a separate copy, restore them at their documented paths, verify source hashes against the manifest, and run the text checker directly. The release-manifest check intentionally rejects changes to public files. Original server Git identity remains outside this repository.

## Model judging

- Entailment: supported, overstated, not_supported, unintelligible.
- Responsiveness: relevant, partial, not_relevant.
- Two blinded passes label real items and negative controls; a third pass adjudicates disagreements.
- Original and matched versions are retained separately. Matched judging holds codebook, served model, adjudicator prompt, and batch size fixed across arms.
- Item files and keys retain the link to question, claim, and control status.
- The joint-label join uses explicit item IDs or claim/passage-aware keys; question/chunk IDs alone need not be unique.

The judging directory preserves frozen prompts and historical JS orchestration. The JS records the original agent environment; it is not a portable model SDK and is not required by evaluate.py.

For a new judging run, supply unredacted passages, prepare item files with the build scripts, follow the codebooks, perform two blind passes, adjudicate disagreements, and preserve the pass_a/pass_b/adjudication schema. Never treat a WITHHELD placeholder as the source passage.

## Statistics and human calibration

Rates pool positive labels over returned claims. Answer coverage counts questions with at least one relevant returned claim. The conditional shares 5/55 and 10/109 exclude empty claim lists; unconditional counts are 5/134 and 10/134.

The primary matched contrast uses 5,000 paired-question bootstrap resamples, seed 20260907. All claims from a question move together; both arms use the same sampled questions. This describes uncertainty conditional on this question set and these runs, not equivalence or between-generation variability.

Human calibration comprises 30 entailment and 40 relevance judgments on shipped, plus 40 relevance judgments on URL-first: 110 judgments over 101 distinct claims. All were graded by the author, not an independent human rater or clinician. Both URL-first model versions are compared against the same unmodified human sheet.

## Corpus URL audit

The census snapshot contains 595,663 chunks. The URL frame, selections, probe logs, and reports are included. The exploratory audit covers 367 URLs total: 143 issue URLs censused, 146 other URLs frozen initially, and 78 adaptive additions. A separate confirmatory sample uses previously unprobed URLs.

Scripts distinguish URL-field availability, HTTP reachability, issue-index landing, and page-type calibration. Frozen logs support offline calculations. Live URL acquisition can change and requires network access; it is not part of evaluate.py. Live collection scripts must honor robots.txt and host delays. Recreating the corpus census additionally requires the original collection.

## Supporting extraction and ingestion measurements

The g2 directory includes the 150-article samples, extraction prompt, model outputs,
per-article verification records, and scorer. background_checks.py recomputes the
0.573 / 0.933 / 0.940 extraction rates from the three reports and the canonical
Vietnamese field rates (136 to 139 of 145); the five English articles have no verified fields.
Repeating span verification with g2_score.py additionally requires the original article texts.
These are span-verified model extractions; no human field-precision validation was performed.

The deduplication audit and analysis script distinguish two frames: 60,906 of 162,681
export rows belong to duplicate groups (37.4%, counting every member); the final live
replacement census has 152,275 source points before and 132,225 after. These are not
interchangeable denominators. The final verification records a failed text-cleanliness
check, one of 32 sampled chunks, which the manuscript discloses. The extractor's
116/150 scrambled flags are unvalidated and do not demonstrate an unchanged defect rate.

The corpus_census.py live collector additionally requires requests and a reachable Qdrant
collection. These acquisition dependencies are not needed by the offline runner.

## Individual commands

From the repository root:

~~~bash
python paper/check_numbers.py
python benchmark/rivf/compare_arms_matched.py --check
python benchmark/rivf/joint_support_relevance.py --check
python benchmark/rivf/compare_arms.py --url-first benchmark/datasets/test_results/pilot_span_exposure_urlfirst_2026-09-07_035612_raw.jsonl --check
python benchmark/rivf/score_urlfirst_relevance.py --check
python benchmark/rivf/url_confirmatory_estimate.py --check
python benchmark/rivf/run_configuration.py --check
python -m unittest discover -s tests
~~~

The evaluate.py entry point covers both arms and all completed human sheets. Results distinguish completed checks from unavailable text-dependent measurements.

## Scope

The full RAG service, production environment, vector database, original source passages, and private agent transcripts are excluded. Generator/verifier model IDs and decoding parameters were not recorded in captures. The frozen provenance audit records judge-model IDs, but no immutable checkpoints were pinned.

This artifact does not establish clinical safety. High citation support and low claim responsiveness describe the measured attribution layer of one system, corpus, and question set.
