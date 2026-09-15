export const meta = {
  name: 'entailment-judgement-urlfirst',
  description: 'Judge entailment (claim vs cited passage) for the URL-first arm: two blind passes over 401 frozen items (364 displayed claims + 37 passage-derangement controls), then adjudication -- same codebook as the shipped arm',
  phases: [
    { title: 'Judge', detail: 'two independent passes, 8 blind batches each' },
    { title: 'Adjudicate', detail: 'third pass over disagreements' },
  ],
}

const CODEBOOK = `
You are judging ENTAILMENT for a research measurement. Work carefully; a careless label is
worse than no measurement. Batches are ~50 items: keep the same standard on item 50 as on
item 1.

WHAT YOU ARE JUDGING
A medical question-answering system displayed a CLAIM to a reader together with a citation
to a passage. A mechanical check already proved the offered span occurs verbatim inside that
passage. It proved nothing about whether the passage SUPPORTS the claim. You decide that.

Judge the pair (claim, cited passage). The "supporting_span" is the fragment the system
offered as its pointer; for most items it is textually identical to the claim, which is why
the span cannot be the unit of judgement.

LABELS -- choose exactly one per item:

* "supported" -- the passage states the claim, or the claim is a faithful paraphrase,
  translation, or direct consequence of what the passage states.

* "overstated" -- the passage supports a WEAKER version: the claim generalises beyond the
  passage's population, turns a hedge into a fact, drops a qualifier (dose, condition,
  subgroup, timeframe), or converts an association into a cause.

* "not_supported" -- the passage does not support the claim: on the topic, perhaps, but it
  asserts nothing that establishes the claim; or it contradicts the claim.

* "unintelligible" -- the passage is too corrupted to judge: interleaved columns, spliced
  sentences, text cut mid-word so that meaning is lost. Only when corruption actually
  prevents judgement; a passage that merely starts mid-word but is readable is judgeable.

RULES
1. Judge ONLY from the text in the item; no outside medical knowledge to fill gaps.
2. A claim that is medically correct but not established by the passage is "not_supported".
3. Vietnamese text; some passages carry a bilingual abstract -- judge across languages.
4. Numbers must match. 96,18 % does not support "96 %" unless the claim is explicitly
   approximate; Vietnamese uses a comma as the decimal separator.
5. Some items are deliberately mismatched controls (a real claim, an unrelated passage). You
   are not told which; an unrelated passage is "not_supported", however fluent.
6. "span_is_right_locus": "yes" if the offered span is the supporting part of the passage,
   "no" if the passage supports the claim elsewhere, "n_a" for not_supported/unintelligible.
7. "confidence": high / medium / low, honestly. Rationale under 160 characters.

FILE ACCESS
Read ONLY the one .jsonl file named in your task. Do NOT open any other file in the
repository -- no key, no label file, no system verdicts.
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
          label: { type: 'string', enum: ['supported', 'overstated', 'not_supported', 'unintelligible'] },
          span_is_right_locus: { type: 'string', enum: ['yes', 'no', 'n_a'] },
          confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
          rationale: { type: 'string' },
        },
        required: ['item_id', 'label', 'span_is_right_locus', 'confidence', 'rationale'],
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

Each line has: item_id, question, claim, supporting_span, cited_passage.

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
D:/CODE/DATN/LLM-MedQA-Assistant/benchmark/rivf/entailment_items_urlfirst_v1.jsonl
Read ONLY that file. Do not open any key file.

Items and the two verdicts:
${g.map((d) => `
- ${d.item_id}
    verdict 1: ${d.a ? `${d.a.label} (${d.a.confidence}) -- ${d.a.rationale}` : 'MISSING'}
    verdict 2: ${d.b ? `${d.b.label} (${d.b.confidence}) -- ${d.b.rationale}` : 'MISSING'}`).join('')}

Return one judgement per item_id listed above (${g.length}), same schema. Re-read the passage
yourself rather than picking the more confident rationale.`,
        { label: `adjudicate:${gi + 1}`, phase: 'Adjudicate', schema: SCHEMA },
      )))).filter(Boolean).flatMap((r) => r.judgements || [])
  : []

return {
  counts: { items: allIds.length, judged_pass_a: byPass.A.size, judged_pass_b: byPass.B.size, raw_agreement: agreed, disagreements: disagreements.length, adjudicated: adjudicated.length },
  pass_a: Array.from(byPass.A.values()),
  pass_b: Array.from(byPass.B.values()),
  adjudication: adjudicated,
}
