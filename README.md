# Vietnamese Medical RAG Attribution Audit

Evaluation artifact for **Retrievable, Citable, Rarely Responsive: Auditing Attribution Coverage in a Vietnamese Medical RAG System**, a RIVF 2026 submission by Nguyen Duc Son.

This repository contains the evaluation code, frozen questions, model/human labels, redacted run records, and paper. It excludes the RAG application, chat UI, deployment stack, databases, and full medical corpus.

## Reproduce the results

Python **3.10+**, standard library only. No API keys, model calls, GPU, running server, or package installation.

~~~bash
git clone https://github.com/jprosun/vi-medrag-audit.git
cd vi-medrag-audit
python evaluate.py
~~~

The runner verifies file hashes, then checks both arms, the paired-question bootstrap, joint counts, human calibration, URL estimates, and paper. A failed supported check returns a nonzero exit code. Text-dependent attribution verification is explicitly excluded because source passages are withheld.

- [Paper PDF](paper/main.pdf)
- [Evaluation protocol and individual commands](EVALUATION.md)
- [Entailment codebook](benchmark/rivf/ENTAILMENT-CODEBOOK.md)
- [Responsiveness codebook](benchmark/rivf/RELEVANCE-CODEBOOK.md)

## Repository map

| Location | Purpose |
|---|---|
| evaluate.py | Single entry point for offline evaluation |
| benchmark/rivf/ | Analysis scripts, frozen labels, keys, reference results, URL sampling records |
| benchmark/rivf/build_*.py and judging/ | Item preparation and frozen judging protocols |
| benchmark/g2/ | Supporting extraction experiment: samples, prompt, outputs, per-article checks |
| benchmark/datasets/ | 134 questions, corpus census, two redacted captures |
| services/rag-orchestrator/app/ | Only three evaluation dependencies: normalization, gates, response measurements |
| paper/ | Manuscript, bibliography, PDF, build script and checkers |
| tests/ | Redacted-file integrity tests |
| MANIFEST.json | Published hashes, original input hashes, source snapshot provenance |

Historical IDs such as 13dc51f refer to the original system repository, not commits in this standalone repository. Historical server identity and judge-model provenance are recorded evidence, not recreated by the public runner.

## Interpret the results

The **matched** protocol gives support about 0.968/0.956 and responsiveness about 0.038/0.036 (shipped/URL-first). Intervals resample paired question clusters, not independent claims, and do not establish equivalence.

The URL-first human sheet has **95% agreement with original labels** and **92.5% with matched labels** (κ 0.8671/0.8131). Two matched-model relevant items were graded partial by the author. Both label versions and the human labels are preserved.

These are returned-claim measurements, not a clinical evaluation of the narrative answer.

## Redaction and reproducibility limits

Bulk retrieved text, cited_passage fields, and duplicate-text previews are replaced by SHA-256 fingerprints and character counts. Third-party email addresses and unrelated API account balances are removed from retained fields. Claims and supporting spans remain as measured units, with contact details removed.

The bundle reproduces label-based rates, contrasts, retention counts, configuration statistics, and URL estimates. It cannot independently re-judge support, verify containment/numeric membership against withheld passages, recreate the live corpus, or regenerate original model responses. [EVALUATION.md](EVALUATION.md) explains the data requirements.

The manifest separates original source-byte hashes from published-byte hashes. Verification checks the actual public bytes before using a recorded source fingerprint; a redaction marker never disables integrity checks.

## Build the PDF

With Docker and the TeX Live image:

~~~bash
sh paper/compile.sh
python paper/check_numbers.py
python paper/check_pdf.py
~~~

Rebuilding changes PDF bytes; the release manifest describes the published snapshot, not arbitrary local edits.

Please cite the manuscript and this artifact; see [CITATION.cff](CITATION.cff).
