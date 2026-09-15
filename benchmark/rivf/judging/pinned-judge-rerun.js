export const meta = {
  name: 'pinned-judge-rerun',
  description: 'Re-run both judgement instruments with an explicitly pinned model, so the judge behind the labels is finally recoverable',
  phases: [
    { title: 'Judge', detail: 'two blind passes per instrument, 8 batches each, model pinned', model: 'opus' },
    { title: 'Adjudicate', detail: 'third pass over disagreements only' },
  ],
}

// The ONE variable this run changes is the model. Everything else is held: the same frozen
// item files, the same batch size and order, the same two-blind-passes-then-adjudicate
// design, and prompts lifted byte-for-byte out of the scripts that produced the committed
// labels (benchmark/rivf/judging/*_prompt_v1.txt, hashed in the artifact).
//
// The original run pinned nothing, so its checkpoint is unrecoverable. Comparing the two
// label sets therefore measures something no one reports: how much of a headline rate is a
// property of the judge rather than of the system under test.
const MODEL = 'opus'

const ENT_SCHEMA = {
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

const REL_SCHEMA = {
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

const B = 'D:/CODE/DATN/LLM-MedQA-Assistant/benchmark/rivf/judging'
const INSTRUMENTS = [
  { key: 'entailment', schema: ENT_SCHEMA, prompt: `${B}/entailment_prompt_v1.txt`,
    fields: 'item_id, question, claim, supporting_span, cited_passage' },
  { key: 'relevance', schema: REL_SCHEMA, prompt: `${B}/relevance_prompt_v1.txt`,
    fields: 'item_id, question, claim, cited_passage' },
]

const BATCHES = []
for (const ins of INSTRUMENTS) {
  for (const pass of ['a', 'b']) {
    for (let n = 1; n <= 8; n++) {
      BATCHES.push({ ins, pass, n, path: `${B}/batches/${ins.key}_${pass}${n}.jsonl` })
    }
  }
}

phase('Judge')
log(`${BATCHES.length} blind batches across 2 instruments, model pinned to ${MODEL}`)

const judged = await parallel(
  BATCHES.map((b) => () =>
    agent(
      `First read this file in full and follow it exactly as your codebook:
${b.ins.prompt}

It is the same codebook, byte for byte, that produced this project's committed labels. Do not
substitute your own criteria for it.

YOUR TASK
Read this batch file, one JSON object per line:
${b.path}

Each line has: ${b.fields}.

Judge every item in the file. Return exactly one judgement per item_id in the file, no more
and no fewer. Do not skip an item because it is hard -- use "low" confidence instead.

FILE ACCESS
Read ONLY those two files. Do NOT open anything else in the repository -- in particular do not
look for a key file, an existing label file, a report, or the system's own verdicts. Some
items are deliberately mismatched controls and you are not told which; do not try to identify
them. Everything you need is in your batch file.`,
      { label: `judge:${b.ins.key}:${b.pass}${b.n}`, phase: 'Judge', schema: b.ins.schema, model: MODEL },
    ).then((r) => ({ instrument: b.ins.key, pass: b.pass, batch: b.n, expected: 28, judgements: (r && r.judgements) || [] })),
  ),
)

const ok = judged.filter(Boolean)
log(`${ok.length} batches returned, ${ok.reduce((s, p) => s + p.judgements.length, 0)} judgements`)

// Merge each instrument's two passes and find the disagreements.
const result = {}
for (const ins of INSTRUMENTS) {
  const mine = ok.filter((p) => p.instrument === ins.key)
  const A = {}, Bp = {}
  for (const p of mine) {
    const into = p.pass === 'a' ? A : Bp
    for (const j of p.judgements) into[j.item_id] = j
  }
  const ids = Object.keys(A).filter((i) => Bp[i])
  const disagree = ids.filter((i) => A[i].label !== Bp[i].label)
  result[ins.key] = { A, B: Bp, ids, disagree }
  log(`${ins.key}: ${ids.length} items judged twice, ${disagree.length} disagreements`)
}

phase('Adjudicate')

for (const ins of INSTRUMENTS) {
  const r = result[ins.key]
  if (!r.disagree.length) { r.adjudication = []; continue }
  const groups = []
  for (let i = 0; i < r.disagree.length; i += 10) groups.push(r.disagree.slice(i, i + 10))
  const adj = await parallel(
    groups.map((g, gi) => () =>
      agent(
        `First read this file in full and follow it exactly as your codebook:
${ins.prompt}

Two independent judges disagreed on the items below. You are the adjudicator. You see both
labels but NOT which judge produced which, and not which judge was first.

For each item, find it by its item_id in the batch files under ${B}/batches/ (the
${ins.key}_a*.jsonl files hold every item once), read the item, and decide the label yourself.
You are not voting between the two: if both are wrong, say so with your own label.

ITEMS AND THE TWO LABELS OFFERED:
${g.map((i) => `${i}: one judge said "${r.A[i].label}", the other said "${r.B[i].label}"`).join('\n')}

Return exactly ${g.length} judgements, one per item_id above.

FILE ACCESS: only the codebook and the batch files. Do not open a key, a label file or a
report.`,
        { label: `adjudicate:${ins.key}:${gi + 1}`, phase: 'Adjudicate', schema: ins.schema, model: MODEL },
      ).then((x) => (x && x.judgements) || []),
    ),
  )
  r.adjudication = adj.filter(Boolean).flat()
  log(`${ins.key}: ${r.adjudication.length} adjudicated`)
}

return {
  model_pinned: MODEL,
  instruments: Object.fromEntries(INSTRUMENTS.map((ins) => {
    const r = result[ins.key]
    return [ins.key, {
      counts: {
        items: r.ids.length,
        judged_pass_a: Object.keys(r.A).length,
        judged_pass_b: Object.keys(r.B).length,
        raw_agreement: r.ids.length - r.disagree.length,
        disagreements: r.disagree.length,
        adjudicated: r.adjudication.length,
      },
      pass_a: Object.values(r.A),
      pass_b: Object.values(r.B),
      adjudication: r.adjudication,
    }]
  })),
}
