export const meta = {
  name: 'tier-b2-answer-crossmodel',
  description: 'Cross-model answer judging (claude-sonnet-5-5 vs claude-opus-5-5; Fable quota exhausted) with same-specialty sibling controls, plus verification of new related-work references',
  phases: [
    { title: 'Sonnet pass', detail: '36 answer batches + 5 sibling batches' },
    { title: 'Opus siblings', detail: '5 sibling batches' },
    { title: 'Refs', detail: 'verify MedCite, Wallat et al., others' },
  ],
}

const B = 'post_submission/tierB/batches'
const BS = 'post_submission/tierB/batches_siblings'
const ANSWER_BATCHES = Array.from({ length: 36 }, (_, i) => `${B}/answers_${String(i).padStart(2, '0')}.jsonl`)
const SIB_BATCHES = Array.from({ length: 5 }, (_, i) => `${BS}/siblings_${String(i).padStart(2, '0')}.jsonl`)

const ANSWER_CODEBOOK = `You are judging RELEVANCE for a research measurement. Work carefully; a careless label is
worse than no measurement.

WHAT YOU ARE JUDGING
A medical question-answering system returned a NARRATIVE ANSWER (Vietnamese, often long,
Markdown) to a reader who had asked a QUESTION. Separate measurements cover whether the
answer's citations are supported. You decide only whether the ANSWER AS A WHOLE answers the
question that was asked.

LABELS -- choose exactly one per item:

* "relevant" -- the answer directly answers the question asked (the specific mechanism,
  comparison, figure, work-up or recommendation requested), even if it also contains
  background. A reader who asked this would find their answer in it.

* "partial" -- the answer is about the question's topic but does not actually answer it: it
  gives background, definitions, a related aspect, a different population or setting, generic
  advice, or says the evidence is insufficient without answering what was asked.

* "not_relevant" -- the answer is about something else: a different disease, population,
  intervention or subject. Sharing a word or a body system with the question does not make
  it relevant.

RULES
1. Judge the answer AGAINST THE QUESTION. Do not grade medical correctness; a wrong but direct
   answer is still "relevant" for this measurement, a correct essay on a neighbouring topic is
   "partial".
2. Do not rescue an answer with outside knowledge.
3. An answer that only restates the question, lists what it cannot determine, or abstains is
   "partial" (it is on topic but does not answer), unless it is about something else entirely.
4. Some items deliberately pair a real answer with a question it was never generated for. You
   are not told which. Do not try to guess the design; if the answer has nothing to do with its
   question, that is "not_relevant", however fluent either one is.
5. Record "confidence": "high", "medium" or "low".
6. Keep each "rationale" under 200 characters, naming what in the question the answer does or
   does not address.

FILE ACCESS
Read ONLY the one .jsonl file named in your task. Do NOT open any other file. Label EVERY item
in the file, in order, by item_id.`

const LABEL_SCHEMA = {
  type: 'object',
  properties: { labels: { type: 'array', items: { type: 'object', properties: {
    item_id: { type: 'string' }, label: { type: 'string', enum: ['relevant', 'partial', 'not_relevant'] },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] }, rationale: { type: 'string' },
  }, required: ['item_id', 'label', 'confidence', 'rationale'] } } },
  required: ['labels'],
}
const prompt = (path, tag) => `${ANSWER_CODEBOOK}

YOUR TASK (pass ${tag}): read the file ${path} (JSON Lines; each line has item_id, question, answer). Label every item. Return the labels via the StructuredOutput tool as {labels: [...]}, one entry per item_id, in file order. Do not write any file.`

const REF_SCHEMA = { type: 'object', properties: { bibtex: { type: 'string' }, findings: { type: 'array', items: { type: 'object', properties: { key: { type: 'string' }, verified: { type: 'boolean' }, source_checked: { type: 'string' }, finding_to_cite: { type: 'string' }, positioning_sentence: { type: 'string' } }, required: ['key', 'verified', 'source_checked', 'finding_to_cite', 'positioning_sentence'] } }, notes: { type: 'string' } }, required: ['bibtex', 'findings', 'notes'] }

const [sonnetRes, opusSib, refs] = await parallel([
  () => parallel(ANSWER_BATCHES.concat(SIB_BATCHES).map((p, i) => () =>
    agent(prompt(p, 'C'), { label: `sonnet:${p.split('/').pop()}`, phase: 'Sonnet pass', schema: LABEL_SCHEMA, model: 'sonnet' }))),
  () => parallel(SIB_BATCHES.map((p, i) => () =>
    agent(prompt(p, 'S'), { label: `opus:${p.split('/').pop()}`, phase: 'Opus siblings', schema: LABEL_SCHEMA }))),
  () => agent(`Verify and produce IEEEtran-compatible BibTeX for references to add to a paper on attribution in a Vietnamese medical RAG system. Load web tools first with ToolSearch "select:WebSearch,WebFetch". Verify every field via Crossref (https://api.crossref.org/works?query.bibliographic=... or /works/<DOI>), the ACL Anthology, or arXiv (export.arxiv.org/api/query?id_list=...). Use curl through Bash if WebFetch is blocked. Quote the specific finding we would cite. Works:
(a) MedCite (Findings of ACL 2025) on citation generation/evaluation for medical LLMs: confirm title, authors, anthology id, and its finding about citation quality vs answer quality.
(b) Wallat et al., arXiv:2412.18004 (attribution correctness vs faithfulness / post-rationalisation in RAG): confirm exact title, authors, venue if published, and the finding that citations can be correct yet not what the model actually used (post-rationalised).
(c) Any well-established work reporting that answer quality and citation quality diverge or are anti-correlated (besides Liu et al. 2023 EMNLP Findings and ExpertQA NAACL 2024, which are already cited) -- e.g. ALCE citation recall vs correctness; search and report at most two strongest, verified.
For each: key (suggest e.g. wang2025medcite, wallat2024correctness), verified true/false, which source you checked, the finding, and one positioning sentence in the paper's voice (neutral, concise) for a sentence like "The divergence between answer quality and citation quality is documented [..]; our contribution is the provenance census and the gate's interaction with provenance loss." Use six-author truncation with "and others" in BibTeX. Output via StructuredOutput.`, { label: 'refs', phase: 'Refs', schema: REF_SCHEMA }),
])
const C = {}; for (const r of sonnetRes) if (r) for (const l of r.labels) C[l.item_id] = l
const S = {}; for (const r of opusSib) if (r) for (const l of r.labels) S[l.item_id] = l
log(`sonnet labels ${Object.keys(C).length}, opus sibling labels ${Object.keys(S).length}`)
return { sonnet: C, opusSiblings: S, refs }