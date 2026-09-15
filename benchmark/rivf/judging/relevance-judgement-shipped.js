export const meta = {
  name: 'relevance-judgement-rivf134',
  description: 'Judge whether each displayed claim is RELEVANT to the question it was shown for: two independent blind passes over 222 frozen items (185 real + 37 question-derangement controls), then adjudication of disagreements',
  phases: [
    { title: 'Judge', detail: 'two independent passes, 8 blind batches each' },
    { title: 'Adjudicate', detail: 'third pass over items where the two passes disagree' },
  ],
}

const CODEBOOK = `
You are judging RELEVANCE for a research measurement. Work carefully; a careless label is
worse than no measurement.

WHAT YOU ARE JUDGING
A medical question-answering system displayed a CLAIM, with a citation, to a reader who had
asked a QUESTION. A separate measurement already established that the cited passage
SUPPORTS the claim in 96.8% of cases. That measurement cannot see whether the claim has
anything to do with the question -- and in at least one real case the question asked about
neonatal bilirubin neurotoxicity while the displayed claim was about MRI findings in
pesticide poisoning: perfectly supported, entirely irrelevant. You decide relevance.

Judge the pair (claim, question). The passage is shown for CONTEXT ONLY, so you can tell
what the claim is about; support is NOT what you are labelling.

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
1. Judge the claim AGAINST THE QUESTION, not the passage against the question. The passage
   tells you what the claim means; it does not vote.
2. Do not rescue a claim with outside knowledge. A claim that is medically true but does not
   answer THIS question is "partial" or "not_relevant".
3. A claim that states a study's objective, sample or method ("Nghiên cứu được tiến hành
   trên 34 bệnh nhân...") is at most "partial" unless the question asked about that study.
4. Question and claim are Vietnamese; some passages carry a bilingual abstract.
5. Some items deliberately pair a real claim with a question it was never generated for. You
   are not told which. Do not try to guess the design; if a claim has nothing to do with its
   question, that is "not_relevant", however fluent either one is.
6. Record "confidence": "high", "medium" or "low". Low confidence triggers a second look, so
   use it honestly rather than defensively.
7. Keep each "rationale" under 200 characters, naming what in the question the claim does or
   does not address.

FILE ACCESS
Read ONLY the one .jsonl file named in your task. Do NOT open any other file in the
repository -- in particular do not look for a key, a label file, or the system's verdicts.
Everything you need is in your batch file.
`

const SCHEMA = {
  type: 'object',
  properties: {
    judgements: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          item_id: { type: 'string' },
          label: { type: 'string', enum: ['relevant', 'partial', 'not_relevant'] },
          confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
          rationale: { type: 'string' },
        },
        required: ['item_id', 'label', 'confidence', 'rationale'],
      },
    },
  },
  required: ['judgements'],
}

const BATCHES = args

phase('Judge')
log(`${BATCHES.length} blind batches: two independent passes over 222 frozen items`)

const passes = await parallel(
  BATCHES.map((b) => () =>
    agent(
      `${CODEBOOK}

YOUR TASK
Read this file, which holds ${b.n} items, one JSON object per line:
${b.path}

Each line has: item_id, question (what the user asked), claim (what the system displayed),
cited_passage (the passage it cited -- context only).

Judge every one of the ${b.n} items. Return exactly ${b.n} judgements, one per item_id in
the file, no more and no fewer. Do not skip an item because it is hard -- use "low"
confidence instead.`,
      { label: `judge:${b.pass}${b.batch}`, phase: 'Judge', schema: SCHEMA },
    ).then((r) => ({ pass: b.pass, batch: b.batch, expected: b.n, judgements: (r && r.judgements) || [] })),
  ),
)

const ok = passes.filter(Boolean)
const byPass = { A: new Map(), B: new Map() }
for (const p of ok) {
  if (p.judgements.length !== p.expected) log(`batch ${p.pass}${p.batch}: returned ${p.judgements.length} of ${p.expected}`)
  for (const j of p.judgements) byPass[p.pass].set(j.item_id, j)
}

const allIds = Array.from(new Set([...byPass.A.keys(), ...byPass.B.keys()])).sort()
const disagreements = []
let agreed = 0
for (const id of allIds) {
  const a = byPass.A.get(id), b = byPass.B.get(id)
  if (!a || !b) { disagreements.push({ item_id: id, a: a || null, b: b || null }); continue }
  if (a.label === b.label) { agreed++; continue }
  disagreements.push({ item_id: id, a, b })
}
log(`raw agreement ${agreed}/${allIds.length}; ${disagreements.length} items go to adjudication`)

phase('Adjudicate')
const CHUNK = 25
const groups = []
for (let i = 0; i < disagreements.length; i += CHUNK) groups.push(disagreements.slice(i, i + CHUNK))

const adjudicated = groups.length
  ? (await parallel(
      groups.map((g, gi) => () =>
        agent(
          `${CODEBOOK}

YOU ARE ADJUDICATING
Two independent judges applied the codebook above and disagreed on the label for these
items. You decide. You are NOT told which judge is which; both may be wrong, and a third
label is allowed.

Read the items from this file (one JSON object per line, find the matching item_id):
D:/CODE/DATN/LLM-MedQA-Assistant/benchmark/rivf/relevance_model_items_v1.jsonl
Read ONLY that file. Do not open relevance_model_key_v1.json or any other file.

Items and the two verdicts:
${g.map((d) => `
- ${d.item_id}
    verdict 1: ${d.a ? `${d.a.label} (${d.a.confidence}) -- ${d.a.rationale}` : 'MISSING'}
    verdict 2: ${d.b ? `${d.b.label} (${d.b.confidence}) -- ${d.b.rationale}` : 'MISSING'}`).join('')}

Return one judgement per item_id listed above (${g.length} of them), in the same schema.
Your label is final, so re-read the question and claim yourself rather than picking the more
confident rationale.`,
          { label: `adjudicate:${gi + 1}`, phase: 'Adjudicate', schema: SCHEMA },
        ),
      ),
    )).filter(Boolean).flatMap((r) => r.judgements || [])
  : []

return {
  counts: { items: allIds.length, judged_pass_a: byPass.A.size, judged_pass_b: byPass.B.size, raw_agreement: agreed, disagreements: disagreements.length, adjudicated: adjudicated.length },
  pass_a: Array.from(byPass.A.values()),
  pass_b: Array.from(byPass.B.values()),
  adjudication: adjudicated,
}
