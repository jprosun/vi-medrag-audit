export const meta = {
  name: 'relevance-judgement-urlfirst',
  description: 'Judge relevance (claim vs question) for the URL-first arm: two blind passes over 401 frozen items (364 displayed claims + 37 question-derangement controls), then adjudication -- same codebook as the shipped arm',
  phases: [
    { title: 'Judge', detail: 'two independent passes, 8 blind batches each' },
    { title: 'Adjudicate', detail: 'third pass over disagreements' },
  ],
}

const CODEBOOK = `
You are judging RELEVANCE for a research measurement. Work carefully; a careless label is
worse than no measurement. Batches are ~50 items: keep the same standard on item 50 as on
item 1.

WHAT YOU ARE JUDGING
A medical question-answering system displayed a CLAIM, with a citation, to a reader who had
asked a QUESTION. A separate measurement establishes whether the cited passage SUPPORTS the
claim. That measurement cannot see whether the claim has anything to do with the question --
in one real case the question asked about neonatal bilirubin neurotoxicity while the
displayed claim was about MRI findings in pesticide poisoning: perfectly supported,
entirely irrelevant. You decide relevance.

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
7. Keep each "rationale" under 160 characters, naming what in the question the claim does or
   does not address.

FILE ACCESS
Read ONLY the one .jsonl file named in your task. Do NOT open any other file in the
repository -- in particular do not look for a key, a label file, or the system's verdicts.
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
log(`${BATCHES.length} blind batches: two independent passes over 401 frozen items (URL-first arm)`)

const passes = await parallel(
  BATCHES.map((b) => () =>
    agent(
      `${CODEBOOK}

YOUR TASK
Read this file, which holds ${b.n} items, one JSON object per line:
${b.path}

Each line has: item_id, question, claim, cited_passage (context only).

Judge every one of the ${b.n} items. Return exactly ${b.n} judgements, one per item_id in
the file, no more and no fewer. Do not skip a hard item -- use "low" confidence instead.`,
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
log(`raw agreement ${agreed}/${allIds.length}; ${disagreements.length} to adjudication`)

phase('Adjudicate')
const CHUNK = 25
const groups = []
for (let i = 0; i < disagreements.length; i += CHUNK) groups.push(disagreements.slice(i, i + CHUNK))
const adjudicated = groups.length
  ? (await parallel(groups.map((g, gi) => () =>
      agent(
        `${CODEBOOK}

YOU ARE ADJUDICATING
Two independent judges applied the codebook above and disagreed on these items. You decide;
you are not told which judge is which, both may be wrong, and a third label is allowed.

Read the items from this file (one JSON object per line, match item_id):
D:/CODE/DATN/LLM-MedQA-Assistant/benchmark/rivf/relevance_model_items_urlfirst_v1.jsonl
Read ONLY that file. Do not open any key file.

Items and the two verdicts:
${g.map((d) => `
- ${d.item_id}
    verdict 1: ${d.a ? `${d.a.label} (${d.a.confidence}) -- ${d.a.rationale}` : 'MISSING'}
    verdict 2: ${d.b ? `${d.b.label} (${d.b.confidence}) -- ${d.b.rationale}` : 'MISSING'}`).join('')}

Return one judgement per item_id listed above (${g.length}), same schema. Re-read the question
and claim yourself rather than picking the more confident rationale.`,
        { label: `adjudicate:${gi + 1}`, phase: 'Adjudicate', schema: SCHEMA },
      )))).filter(Boolean).flatMap((r) => r.judgements || [])
  : []

return {
  counts: { items: allIds.length, judged_pass_a: byPass.A.size, judged_pass_b: byPass.B.size, raw_agreement: agreed, disagreements: disagreements.length, adjudicated: adjudicated.length },
  pass_a: Array.from(byPass.A.values()),
  pass_b: Array.from(byPass.B.values()),
  adjudication: adjudicated,
}
