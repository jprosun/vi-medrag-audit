// Historical workflow script (run id wf_fa3fa951-7e2, 2026-10-10/11); local scratchpad batch path
// normalised to relative `post_submission/tierB/batches`. Served model IDs per pass and per item
// are recorded in `./judge_provenance.json`.
export const meta = {
  name: 'tier-b-judging',
  description: 'Tier B for paper 1571353709: two blind relevance passes + adjudication over all C0 claims (both arms, returned and withheld) and over all narrative answers, with cross-specialty controls',
  phases: [
    { title: 'Pass A', detail: '20 claim batches + 36 answer batches' },
    { title: 'Pass B', detail: 'same batches, independent agents' },
    { title: 'Adjudicate', detail: 'disagreements only' },
  ],
}

const B = 'post_submission/tierB/batches'
const CLAIM_BATCHES = Array.from({ length: 20 }, (_, i) => `${B}/claims_${String(i).padStart(2, '0')}.jsonl`)
const ANSWER_BATCHES = Array.from({ length: 36 }, (_, i) => `${B}/answers_${String(i).padStart(2, '0')}.jsonl`)

// Codebook = relevance_prompt_v1.txt of the released artifact, with ONE change: the sentence carrying the
// 96.8 % support prior is replaced by the prior-free wording of the URL-first script, because withheld
// claims have no support measurement. The passage is withheld in the artifact, so it is not shown.
const CLAIM_CODEBOOK = `You are judging RELEVANCE for a research measurement. Work carefully; a careless label is
worse than no measurement.

WHAT YOU ARE JUDGING
A medical question-answering system proposed a CLAIM, with a citation, for a reader who had
asked a QUESTION. A separate measurement establishes whether the cited passage SUPPORTS the
claim. That measurement cannot see whether the claim has anything to do with the question --
and in at least one real case the question asked about neonatal bilirubin neurotoxicity while
the displayed claim was about MRI findings in pesticide poisoning: perfectly supported, entirely
irrelevant. You decide relevance.

Judge the pair (claim, question). The cited passage is not shown; the claim is in nearly every
case a verbatim sentence of that passage. Support is NOT what you are labelling.

LABELS -- choose exactly one per item:

* "relevant" -- the claim answers the question directly, or is a necessary part of a direct
  answer. A reader who asked this would want this sentence.

* "partial" -- the claim is about the question's topic but does not answer it: same disease,
  different aspect; background or a definition; a related population or setting; a study's
  objective, sample or method rather than its finding.

* "not_relevant" -- the claim is about something else: a different disease, population,
  intervention or subject. Sharing a word or a body system with the question does not make
  it relevant.

RULES
1. Judge the claim AGAINST THE QUESTION.
2. Do not rescue a claim with outside knowledge. A claim that is medically true but does not
   answer THIS question is "partial" or "not_relevant".
3. A claim that states a study's objective, sample or method ("Nghiên cứu được tiến hành
   trên 34 bệnh nhân...") is at most "partial" unless the question asked about that study.
4. Question and claim are Vietnamese.
5. Some items deliberately pair a real claim with a question it was never generated for. You
   are not told which. Do not try to guess the design; if a claim has nothing to do with its
   question, that is "not_relevant", however fluent either one is.
6. Record "confidence": "high", "medium" or "low". Low confidence triggers a second look, so
   use it honestly rather than defensively.
7. Keep each "rationale" under 200 characters, naming what in the question the claim does or
   does not address.

FILE ACCESS
Read ONLY the one .jsonl file named in your task. Do NOT open any other file -- in particular
do not look for a key, a label file, the paper, or the system's verdicts. Everything you need
is in your batch file. Label EVERY item in the file, in order, by item_id.`

// Adapted codebook: same labels and rules, unit = the whole narrative answer (adaptation made
// after the answers were collected; reported as such).
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
  properties: {
    labels: { type: 'array', items: { type: 'object', properties: {
      item_id: { type: 'string' },
      label: { type: 'string', enum: ['relevant', 'partial', 'not_relevant'] },
      confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
      rationale: { type: 'string' },
    }, required: ['item_id', 'label', 'confidence', 'rationale'] } },
  },
  required: ['labels'],
}

function judgePrompt(codebook, path, passTag) {
  return `${codebook}

YOUR TASK (pass ${passTag}): read the file ${path} (JSON Lines; each line has item_id, question, and claim or answer). Label every item. Return the labels via the StructuredOutput tool as {labels: [...]}, one entry per item_id, in file order. Do not write any file.`
}

async function runPass(tag) {
  const claimRes = await parallel(CLAIM_BATCHES.map((p, i) => () =>
    agent(judgePrompt(CLAIM_CODEBOOK, p, tag), { label: `pass${tag}:claims:${i}`, phase: `Pass ${tag}`, schema: LABEL_SCHEMA })))
  const answerRes = await parallel(ANSWER_BATCHES.map((p, i) => () =>
    agent(judgePrompt(ANSWER_CODEBOOK, p, tag), { label: `pass${tag}:answers:${i}`, phase: `Pass ${tag}`, schema: LABEL_SCHEMA })))
  const out = {}
  for (const r of claimRes.concat(answerRes)) if (r) for (const l of r.labels) out[l.item_id] = l
  return out
}

phase('Pass A')
const A = await runPass('A')
log(`pass A labelled ${Object.keys(A).length} items`)
phase('Pass B')
const Bp = await runPass('B')
log(`pass B labelled ${Object.keys(Bp).length} items`)

// adjudication on disagreements only, both prior labels shown unattributed
phase('Adjudicate')
const ids = Object.keys(A).filter(id => Bp[id] && A[id].label !== Bp[id].label)
log(`disagreements: ${ids.length}`)
const claimIdx = {}
CLAIM_BATCHES.forEach(p => { claimIdx[p] = true })
function batchOf(id) { return id.startsWith('tbC') ? 'claims' : 'answers' }
const groups = {}
for (const id of ids) { const g = batchOf(id); (groups[g] = groups[g] || []).push(id) }
const ADJ = {}
for (const g of Object.keys(groups)) {
  const codebook = g === 'claims' ? CLAIM_CODEBOOK : ANSWER_CODEBOOK
  const chunks = []; for (let i = 0; i < groups[g].length; i += 15) chunks.push(groups[g].slice(i, i + 15))
  const res = await parallel(chunks.map((ch, ci) => () => agent(`${codebook}

YOUR TASK (adjudication): the items below received two different labels from two blind passes; both labels are shown, unattributed. Decide the final label for each. The items live in the .jsonl batch files under ${B}/ (files named ${g}_NN.jsonl); find each item_id by grepping those files only, read the item in full, and decide. Items:
${ch.map(id => `- ${id}: labels given = ${A[id].label} | ${Bp[id].label}`).join('\n')}
Return {labels: [...]} via StructuredOutput with one entry per item_id above. Do not write any file.`, { label: `adjudicate:${g}:${ci}`, phase: 'Adjudicate', schema: LABEL_SCHEMA })))
  for (const r of res) if (r) for (const l of r.labels) ADJ[l.item_id] = l
}
const final = {}
for (const id of Object.keys(A)) {
  const a = A[id], b = Bp[id]
  if (!b) { final[id] = { label: a.label, source: 'A_only' }; continue }
  if (a.label === b.label) { final[id] = { label: a.label, source: 'agree' }; continue }
  final[id] = { label: (ADJ[id] || {}).label || null, source: ADJ[id] ? 'adjudicated' : 'unresolved' }
}
log(`final labels: ${Object.keys(final).length}, adjudicated ${Object.values(final).filter(f => f.source === 'adjudicated').length}, unresolved ${Object.values(final).filter(f => f.source === 'unresolved').length}`)
return { passA: A, passB: Bp, adjudicated: ADJ, final }
