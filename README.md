# Vietnamese Medical RAG Attribution Audit

Evaluation artifact for **Retrievable, Citable, Rarely Responsive: Auditing Attribution Coverage in a Vietnamese Medical RAG System**, accepted at IEEE RIVF 2026 by Nguyen Duc Son.

This repository contains the evaluation code, frozen 134-question probe set and builder, model/human labels, judging prompts and provenance records, redacted run records, post-submission analyses (`post_submission/tierA`, `tierB`, `tierC`), and the camera-ready six-page manuscript. It excludes the RAG application, chat UI, deployment stack, databases, and full medical corpus.

## Reproduce the results

Python **3.10+**, standard library only. No API keys, model calls, GPU, running server, or package installation.

~~~bash
git clone https://github.com/jprosun/vi-medrag-audit.git
cd vi-medrag-audit
python evaluate.py
~~~

The runner verifies every file hash in `MANIFEST.json`, then checks both arms, the paired-question bootstrap, joint counts, human calibration, URL estimates, probe-set integrity, all post-submission analyses (`tierA/B/C`), and the camera-ready manuscript and PDF. A failed supported check returns a nonzero exit code. Text-dependent attribution verification is explicitly excluded because source passages are withheld.

- [Camera-ready Paper PDF](paper/main.pdf)
- [Evaluation protocol and individual commands](EVALUATION.md)
- [Entailment codebook](benchmark/rivf/ENTAILMENT-CODEBOOK.md)
- [Responsiveness codebook](benchmark/rivf/RELEVANCE-CODEBOOK.md)

## Repository map

| Location | Purpose |
|---|---|
| `evaluate.py` | Single entry point for offline evaluation (19 automated checks) |
| `benchmark/rivf/` | Analysis scripts, `build_probe_set.py`, frozen labels, keys, provenance JSONs, URL sampling records |
| `benchmark/rivf/judging/` | Frozen judging & question-authoring workflow scripts and codebooks |
| `post_submission/tierA/` | Post-submission retrieval/stratum stratifications and reference checks |
| `post_submission/tierB/` | Returned-URL dereference audit, exploratory answer/withheld-claim judging (`claude-fable-5-1`, `claude-opus-5-5`, `claude-sonnet-5-5`), sibling controls, and model provenance |
| `post_submission/tierC/` | Source-sitemap URL recovery and span-on-page counterfactual verification |
| `benchmark/g2/` | Supporting extraction experiment: samples, prompt, outputs, per-article checks |
| `benchmark/datasets/` | 134 questions (`probe_queries_v2.jsonl`), corpus census, two redacted captures |
| `services/rag-orchestrator/app/` | Three evaluation dependencies: normalization, gates, response measurements |
| `paper/` | Camera-ready manuscript (`main.tex`), bibliography (`refs.bib`), PDF (`main.pdf`), build script and checkers |
| `tests/` | Redacted-file integrity tests |
| `MANIFEST.json` | Published hashes, original input hashes, source snapshot provenance |

Historical commit IDs printed in the manuscript and capture metadata refer to the private system repository before an October 2026 `git filter-repo` author/secret scrub (`13dc51f` -> `9ce3392`; `47536e9` -> `db7347b`; `a1f1126` -> `d2b4c31`; `c504823` -> `8b91901`; `ee5ee01` -> `f21cd4f`), not commits in this standalone repository.

## Interpret the results

The **matched** protocol gives support about 0.968/0.956 and responsiveness about 0.038/0.036 (shipped/URL-first). Intervals resample paired question clusters, not independent claims, and do not establish equivalence.

The URL-first human sheet has **95% agreement with original labels** and **92.5% with matched labels** (κ 0.8671/0.8131). Two matched-model relevant items were graded partial by the author. Both label versions and the human labels are preserved.

Exploratory post-submission judging (`post_submission/tierB/`) evaluates narrative answers and withheld claims under an adapted prior-free codebook without passages shown; these rates ignore clinical correctness and have no human calibration.

## Redaction and reproducibility limits

Bulk retrieved text, `cited_passage` fields, and duplicate-text previews are replaced by SHA-256 fingerprints and character counts. Third-party email addresses and unrelated API account balances are removed from retained fields. Claims and supporting spans remain as measured units, with contact details removed.

The manifest separates original source-byte hashes from published-byte hashes. Verification checks the actual public bytes before using a recorded source fingerprint; a redaction marker never disables integrity checks.

## Build the PDF

With Docker and the TeX Live image:

~~~bash
sh paper/compile.sh
python paper/check_numbers.py
python paper/check_pdf.py
~~~

Please cite the manuscript and this artifact; see [CITATION.cff](CITATION.cff).
