export const meta = {
  name: 'entailment-judgement-rivf134',
  description: 'Judge whether each displayed claim is supported by the passage it cites: two independent blind passes over 222 frozen items, then adjudication of disagreements',
  phases: [
    { title: 'Judge', detail: 'two independent passes, 8 blind batches each' },
    { title: 'Adjudicate', detail: 'third pass over items where the two passes disagree' },
  ],
}

const CODEBOOK = `
You are judging ENTAILMENT for a research measurement. Work carefully; this is the paper's
headline number and a careless label is worse than no measurement.

WHAT YOU ARE JUDGING
A medical question-answering system displayed a CLAIM to a reader together with a citation
to a passage. A separate mechanical check already proved that the offered span occurs
verbatim inside that passage. It proved nothing about whether the passage SUPPORTS the
claim. That is what you decide.

Judge the pair (claim, cited passage). The "supporting_span" field is the fragment the
system offered as its pointer; for most items it is textually identical to the claim, which
is exactly why the span cannot be the unit of judgement.

LABELS -- choose exactly one per item:

* "supported" -- the passage states the claim, or the claim is a faithful paraphrase,
  translation, or direct consequence of what the passage states. A reader who followed the
  citation would find what they were promised.

* "overstated" -- the passage supports a WEAKER version. The claim generalises beyond the
  passage's population, turns a hedge into a fact, drops a qualifier (dose, condition,
  subgroup, timeframe), or converts an association into a cause. The quotation is real; the
  claim is bigger than it. This label matters: use it rather than stretching "supported".

* "not_supported" -- the passage does not support the claim. It may be on the same topic,
  mention the same entity, or contain similar numbers and still assert nothing that
  establishes the claim. Also use it when the passage contradicts the claim.

* "unintelligible" -- the passage is too corrupted to judge: interleaved columns, sentences
  spliced together, text starting or ending mid-word to the point that meaning is lost.
  This corpus has a documented ingestion defect, so this label is real and must not be
  folded into "not_supported". Only use it when corruption actually prevents judgement --
  a passage that merely starts mid-word but is still readable is judgeable.

RULES
1. Judge ONLY from the text in the item. Do NOT use outside medical knowledge to fill a gap
   in the passage. The question is whether THIS passage supports the claim, not whether the
   claim is true in general.
2. A claim that is medically correct but not established by the passage is "not_supported".
3. The text is Vietnamese; some passages carry a bilingual abstract. Judge across languages
   -- a Vietnamese claim supported by the English half of the same abstract is "supported".
4. Numbers must match. A passage giving 96,18% does not support a claim of "96%" unless the
   claim is explicitly approximate; use "overstated" when the claim rounds or generalises,
   "not_supported" when the number is simply different. Vietnamese uses a comma as the
   decimal separator: 96,18 means 96.18.
5. Some items are deliberately mismatched controls -- a real claim paired with a passage
   from an unrelated question. You are not told which. Do not try to guess the design; just
   apply the labels honestly. If a passage is unrelated to its claim, that is
   "not_supported", however fluent the passage is.
6. Also record "span_is_right_locus": "yes" if the offered span is the part of the passage
   that does the supporting, "no" if the passage supports the claim somewhere else, "n_a"
   when the label is "not_supported" or "unintelligible".
7. Record "confidence": "high", "medium" or "low". Low confidence triggers a second look by
   another judge, so use it honestly rather than defensively.
8. Keep each "rationale" under 200 characters, naming the specific part of the passage that
   decided it.

FILE ACCESS
Read ONLY the one .jsonl file named in your task. Do NOT open any other file in the
repository -- in particular do not look for a key, a label file, or the system's own
verdicts. Everything you need is in your batch file.
`

const JUDGEMENT_SCHEMA = {
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
log(`${BATCHES.length} blind batches: two independent passes over 222 frozen items`)

const passes = await parallel(
  BATCHES.map((b) => () =>
    agent(
      `${CODEBOOK}

YOUR TASK
Read this file, which holds ${b.n} items, one JSON object per line:
${b.path}

Each line has: item_id, question (what the user asked), claim (what the system displayed),
supporting_span (the fragment it offered), cited_passage (the full passage it cited).

Judge every one of the ${b.n} items. Return exactly ${b.n} judgements, one per item_id in
the file, no more and no fewer. Do not skip an item because it is hard -- use "low"
confidence instead.`,
      { label: `judge:${b.pass}${b.batch}`, phase: 'Judge', schema: JUDGEMENT_SCHEMA },
    ).then((r) => ({ pass: b.pass, batch: b.batch, expected: b.n, judgements: (r && r.judgements) || [] })),
  ),
)

const ok = passes.filter(Boolean)
const byPass = { A: new Map(), B: new Map() }
for (const p of ok) {
  if (p.judgements.length !== p.expected) {
    log(`batch ${p.pass}${p.batch}: returned ${p.judgements.length} of ${p.expected}`)
  }
  for (const j of p.judgements) byPass[p.pass].set(j.item_id, j)
}

const allIds = Array.from(new Set([...byPass.A.keys(), ...byPass.B.keys()])).sort()
const disagreements = []
let agreed = 0
for (const id of allIds) {
  const a = byPass.A.get(id)
  const b = byPass.B.get(id)
  if (!a || !b) { disagreements.push({ item_id: id, a: a || null, b: b || null, why: 'missing' }); continue }
  if (a.label === b.label) { agreed++; continue }
  disagreements.push({ item_id: id, a, b, why: 'label' })
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
Two independent judges applied the codebook above to these items and disagreed on the
label. You decide. You are NOT told which judge is which, and you should not assume either
is right: both may be wrong, and a third label is allowed.

Read the items you are adjudicating from this file (one JSON object per line, find the
matching item_id):
D:/CODE/DATN/LLM-MedQA-Assistant/benchmark/rivf/entailment_items_v1.jsonl
Read ONLY that file. Do not open entailment_key_v1.json or any other file.

Items and the two verdicts:
${g.map((d) => `
- ${d.item_id}
    verdict 1: ${d.a ? `${d.a.label} (${d.a.confidence}) -- ${d.a.rationale}` : 'MISSING'}
    verdict 2: ${d.b ? `${d.b.label} (${d.b.confidence}) -- ${d.b.rationale}` : 'MISSING'}`).join('')}

Return one judgement per item_id listed above (${g.length} of them), in the same schema.
Your label is final, so re-read the passage yourself rather than picking the more confident
rationale.`,
          { label: `adjudicate:${gi + 1}`, phase: 'Adjudicate', schema: JUDGEMENT_SCHEMA },
        ),
      ),
    ))
      .filter(Boolean)
      .flatMap((r) => r.judgements || [])
  : []

return {
  counts: {
    items: allIds.length,
    judged_pass_a: byPass.A.size,
    judged_pass_b: byPass.B.size,
    raw_agreement: agreed,
    disagreements: disagreements.length,
    adjudicated: adjudicated.length,
  },
  pass_a: Array.from(byPass.A.values()),
  pass_b: Array.from(byPass.B.values()),
  adjudication: adjudicated,
}
