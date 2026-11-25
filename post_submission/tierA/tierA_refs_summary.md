# Tier A: verified references and dataset card (EDAS 1571353709)

All bibliographic fields were read from Crossref, the ACL Anthology .bib export, the arXiv export API or Europe PMC; quotes were read from the raw abstract/full text (pdftotext for PDFs). Nothing is from memory.

## 1. BibTeX (IEEEtran-compatible; full author lists -- apply refs.bib's six-author truncation when merging)

```bibtex
@article{wu2025sourcecheckup,
  author  = {Kevin Wu and Eric Wu and Kevin Wei and Angela Zhang and Allison Casasola and Teresa Nguyen and Sith Riantawan and Patricia Shi and Daniel Ho and James Zou},
  title   = {An automated framework for assessing how well {LLMs} cite relevant medical references},
  journal = {Nature Commun.},
  volume  = {16},
  number  = {1},
  pages   = {3615},
  year    = {2025},
  doi     = {10.1038/s41467-025-58551-6}
}

@inproceedings{malaviya2024expertqa,
  author    = {Chaitanya Malaviya and Subin Lee and Sihao Chen and Elizabeth Sieber and Mark Yatskar and Dan Roth},
  title     = {{ExpertQA}: Expert-Curated Questions and Attributed Answers},
  booktitle = {Proc. Conf. Nations Amer. Chapter Assoc. Comput. Linguistics},
  year      = {2024},
  pages     = {3025--3045},
  note      = {doi:10.18653/v1/2024.naacl-long.167}
}

@inproceedings{ma2026vericite,
  author    = {Yixian Ma and Bohao Chu and Norbert Fuhr},
  title     = {{VERICITE}: Evaluating Sentence-Level Citation Faithfulness in Retrieval-Augmented Medical Question Answering},
  booktitle = {Proc. Workshop Biomed. Natural Lang. Process. (BioNLP)},
  year      = {2026},
  pages     = {753--759},
  note      = {doi:10.18653/v1/2026.bionlp-1.62}
}

@inproceedings{muller2023xorattriqa,
  author    = {Benjamin Muller and John Wieting and Jonathan H. Clark and Tom Kwiatkowski and Sebastian Ruder and Livio Baldini Soares and Roee Aharoni and Jonathan Herzig and Xinyi Wang},
  title     = {Evaluating and Modeling Attribution for Cross-Lingual Question Answering},
  booktitle = {Proc. Conf. Empirical Methods Natural Lang. Process.},
  year      = {2023},
  pages     = {144--157},
  note      = {doi:10.18653/v1/2023.emnlp-main.10}
}

@article{kim2025rethinkingmedrag,
  author  = {Hyunjae Kim and Jiwoong Sohn and Aidan Gilson and Nicholas Cochran-Caggiano and Serina Applebaum and Heeju Jin and Seihee Park and Yujin Park and Jiyeong Park and Seoyoung Choi and Brittany Alexandra Herrera Contreras and Thomas Huang and Jaehoon Yun and Ethan F. Wei and Roy Jiang and Leah Colucci and Eric Lai and Amisha Dave and Tuo Guo and Maxwell B. Singer and Yonghoe Koo and Ron A. Adelman and James Zou and Andrew Taylor and Arman Cohan and Hua Xu and Qingyu Chen},
  title   = {Rethinking Retrieval-Augmented Generation for Medicine: A Large-Scale, Systematic Expert Evaluation and Practical Insights},
  journal = {arXiv preprint arXiv:2511.06738},
  year    = {2025}
}
```

## 2. Positioning sentences for Sec. II (paper's voice)

- **wu2025sourcecheckup**: In medicine, an automated audit of seven LLMs over 800 questions found that between 50% and 90% of responses were not fully supported by the sources they cited and that models without web access produced a valid URL only 40--70% of the time \cite{wu2025sourcecheckup}; it tests whether a cited page opens and whether it supports the statement, not whether the statement answers the question.
- **malaviya2024expertqa**: ExpertQA had domain experts rate each claim separately for attribution support, informativeness to the question and source reliability, finding 35% incomplete attributions and 51% not-reliable sources among medical claims \cite{malaviya2024expertqa}; we measure the first two at the claim level on a deployed non-English system and replace the third with a mechanical citability test.
- **ma2026vericite**: On PubMed-grounded medical QA, sentence-level NLI finds only 27--41% of citation pairs supported at retrieval depths of 3 and 5, and an oracle retriever does not substantially raise it \cite{ma2026vericite}; our extractor copies passage sentences rather than authoring claims, which is why support here is near-ceiling and is reported as a design bound, not a result.
- **muller2023xorattriqa**: Outside English, attribution has been measured for cross-lingual QA in Bengali, Finnish, Japanese, Russian and Telugu, where up to half of the answers that exactly match the gold reference are attributable to no retrieved passage \cite{muller2023xorattriqa}; the corpus there is Wikipedia, assembled to be cited, so whether a record can be cited at all does not arise.
- **kim2025rethinkingmedrag**: An expert evaluation of medical RAG that scores retrieval, evidence selection and generation separately found only 22% of top-16 retrieved passages relevant \cite{kim2025rethinkingmedrag}; we ask the narrower question of whether each claim that survives enforcement answers the question asked.
- **liu2023verifiability**: Generative search engines produce citations that often fail to support the sentence they are attached to, and citation precision is inversely correlated with perceived utility ($r=-0.96$), which the authors attribute to systems copying or closely paraphrasing their cited pages \cite{liu2023verifiability}; our extractor is that mechanism in its simplest form, and the responsiveness rate of Section~V is what it costs.
- **longpre2024provenance**: Keep the existing sentence; optionally change ``mis-stated'' to ``with error rates above 50%'' to track the source wording: an audit of more than 1,800 text datasets found licence omission rates above 70% and error rates above 50% on popular hosting platforms \cite{longpre2024provenance}.

## 3. Figures to cite and the Sec. II sentence each attaches to

| Work | Figure (verbatim source) | Where it goes in main.tex |
|---|---|---|
| wu2025sourcecheckup | "between 50% and 90% of LLM responses are not fully supported"; "approximately 30% of individual statements are unsupported" (GPT-4o w/ Web Search); "valid URLs between 40% to 70% of the time" (no-web models) | Sec. II para 1, after the \cite{onweller2026citednotverified} sentence "a citation that resolves is not one that supports" |
| malaviya2024expertqa | Table 3 properties: Attribution, Informativeness ("Is the claim relevant to answering the question?"), Source Reliability; "35% ... incomplete attributions" (medicine); "51% of medical claims have attributions from sources that are not Reliable" | Sec. II para 1, beside \cite{xie2025subquestion} ("Nor is a supported claim a responsive one") |
| ma2026vericite | "Only 27-41% of citation pairs are supported at the sentence level at retrieval depths of 3 and 5" | Sec. II para 2 (Verifiable by construction) or para 4 (Medical), next to \cite{qian2025vericite}; name both author groups |
| muller2023xorattriqa | 5 languages: Bengali, Finnish, Japanese, Russian, Telugu; ACL abstract: "up to 50% of answers exactly matching a gold reference" not attributable (arXiv v2 PDF: 47%); ~10,000 examples | Sec. I para 3 ("a setting, English corpora assembled so that they can be cited") or Sec. II para 4 (Medical and Vietnamese resources) |
| kim2025rethinkingmedrag | "only 22% of top-16 passages were relevant"; evidence selection "precision 41-43%, recall 27-49%"; 18 experts, 80,502 annotations, 800 outputs | Sec. II para 4, after \cite{xiong2024mirage} ("Medical RAG is benchmarked for answer quality") |
| liu2023verifiability | "citation precision is inversely correlated with perceived utility (r = -0.96)"; "often copy or closely paraphrase from their cited webpages"; 51.5% recall / 74.5% precision | Sec. II para 1, first sentence (already cited); Sec. V-B "183 of the 185 claims are verbatim sentences" |
| longpre2024provenance | "licence omission rates of more than 70% and error rates of more than 50%"; "more than 1,800 text datasets" | Sec. II para 4, existing sentence -- figures confirmed |

## 4. Dataset card: mtue29/vietnamese-medical-dataset (Hugging Face API reachable, HTTP 200)

| Item | Value (from API / README / datasets-server) |
|---|---|
| Licence | `apache-2.0` (cardData.license; README front matter `license: apache-2.0`) |
| Declared source / credit | README: `- Source: [Long Châu Pharmacy](https://nhathuoclongchau.com.vn/)`; citation block author `Tue Phan Vo Minh`, year 2025; "Domain: Healthcare / Patient education". No statement of the source site's own licence or of permission to redistribute. |
| Rows | 463,422 train examples (datasets-server `num_examples`), shards [230839, 232583]; size_categories ['100K<n<1M'] |
| Files | ['.gitattributes', 'README.md', 'vietnamese-medical-dataset.json']; data file `vietnamese-medical-dataset.json` = 1,043,065,539 bytes (LFS); dataset_size 1,006,163,292 bytes |
| Row fields | ['anchor', 'meta', 'negative', 'positive']; `meta` = ['article_id', 'category', 'title'] (article_id int64, category string, title string) |
| URL field | **False** -- no field name contains 'url' |
| Title field | True (`meta.title`, full article headline) |
| article_id field | True, but in the first 89 rows it takes 45 distinct values over 10 distinct titles and 44 distinct anchors (range [0, 44]); e.g. one title carries article_ids [0, 1, 2, 3, 4, 5]. It increments per anchor/section, not per article, so it is not a site article identifier and cannot be mapped to a URL. |
| category field | path-like slug, e.g. phong_benh_song_khoe/kien_thuc_y_khoa (60 of 89 sample rows) -- resembles a site section path, not a URL |
| Metadata | id mtue29/vietnamese-medical-dataset, author mtue29, createdAt 2025-09-25T04:11:23.000Z, lastModified 2025-09-25T04:35:40.000Z, sha 5dedcb22d80295e6e645d10eff5cdc42e66a9487, private=False, gated=False, downloads 35, likes 4 |

**URL recovery verdict.** The card carries no URL and no site-side identifier. `meta.title` (and `meta.category`) are the only handles; recovering a URL would mean searching nhathuoclongchau.com.vn by title, which the card neither documents nor guarantees. This matches the manuscript's "ingested with its text and without its links" and "Recovering the URLs is future work".

## 5. Artifact cross-check (script output)

| Quantity | Value |
|---|---|
| Census stratum `hf_vi_mtue29_medical` chunks / share | 256,415 / 0.4305 (points declared 595,663, scrolled 595,663) |
| Census distinct (system-hashed) article_ids in stratum | 109,816 |
| Census source_url for stratum | {'any': 0.0, 'article_or_page': 0, 'issue_level_only': 0, 'none': 256415} |
| Shipped capture: records / chunks / HF chunks | 134 / 4,024 / 2,472 (share 0.6143) -- matches paper 134 / 4,024 / 2,472 (61.4%) |
| Shipped capture: HF chunks with non-empty title / tags / source_url | 2,472 / 2,472 / 0 ; chunks whose tags carry `hf_article_id:N` = 2,472 |
| URL-first capture: records / chunks / HF chunks | 134 / 3,947 / 0 |

The index kept the card's `title` and a per-row `hf_article_id` tag for every retrieved HF chunk, so a title-based URL recovery is feasible from the artifact's own metadata; it is not feasible from the card alone.

## 6. Caveats

- Nature's page for SourceCheckup 303-redirects to idp.nature.com; metadata is from Crossref and the full text from Europe PMC (PMC12003634), which is the open-access copy of the same DOI.
- XOR-AttriQA's headline figure differs by version: the ACL Anthology abstract (read from the page HTML) says 'up to 50%', the arXiv v2 PDF says 'up to 47%' (abstract and Section 4.1). The positioning sentence says 'up to half'; if a number is printed, use 50% with the Anthology DOI.
- VERICITE figures come from the Anthology abstract; the PDF was not opened. The BioNLP workshop ordinal was not verified, so the booktitle carries none.
- Kim et al. is a preprint with no DOI or venue as of 2026-10-11; the '22%' is over top-16 passages.
- Liu et al.'s coefficient (r = -0.96) is citation precision vs perceived utility; the paper gives none for recall or fluency.
- HF row count comes from the datasets-server `/info` endpoint (parquet conversion), not from downloading the 1.04 GB JSON; the first-rows analysis covers only the 89 rows the `/first-rows` endpoint returns.