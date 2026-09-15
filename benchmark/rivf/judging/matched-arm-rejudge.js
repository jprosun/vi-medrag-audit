export const meta = {
  name: 'matched-arm-rejudge',
  description: 'Re-judge the URL-first arm under the exact instrument configuration of the shipped arm, so the between-arm contrast stops crossing two judge models and two codebooks',
  phases: [
    { title: 'Witness', detail: 'one agent under the same model setting reports the model ID it is actually running as' },
    { title: 'Judge', detail: '60 blind batches: 401 URL-first items, two instruments, two passes, shipped codebook, model pinned' },
    { title: 'Adjudicate', detail: 'third pass over URL-first disagreements, original adjudicator prompt' },
    { title: 'Rematch', detail: 're-adjudicate the shipped pinned re-run under the same adjudicator prompt, so both sides of the contrast match there too' },
  ],
}

// WHY THIS RUN EXISTS.
//
// The paper compares two designs on support and responsiveness. That contrast assumed one
// instrument measured both arms. It did not, in two ways, both recovered after the fact from
// the run transcripts and the committed scripts:
//
//   MODEL      entailment shipped claude-opus-5, URL-first claude-fable-5-1;
//              relevance both arms claude-fable-5-1.
//              So the support contrast crossed two models. The responsiveness contrast did not.
//
//   CODEBOOK   the URL-first entailment codebook is 2591 characters against the shipped arm's
//              3876, and what it dropped includes the operational reading of `supported`, the
//              anti-lenience nudge on `overstated`, and the justification for `unintelligible`
//              as a live label. The shipped relevance codebook additionally told its judge
//              that support was "already established at 96.8% of cases" -- a numeric prior
//              from the other instrument, present in one arm only.
//
// This run holds every instrument variable at the SHIPPED arm's value and changes only the
// arm: shipped codebook byte for byte (judging/*_prompt_v1.txt), model pinned, the original
// adjudicator prompt including confidence and rationale, batch size 28.
//
// The Rematch phase closes the last gap. The shipped arm's pinned re-run used a reduced
// adjudicator prompt -- bare labels, no confidence, no rationale. That touched at most 5 of
// its 185 relevance labels, but "at most 5" is not "none", so those 2 + 5 disagreements are
// re-adjudicated here under the same prompt the URL-first side gets.
const MODEL = 'opus'

// The shipped arm's pinned re-run sent these to a REDUCED adjudicator (bare labels only).
// They are embedded verbatim from that run's artifact so the Rematch phase is reproducible
// from the committed script alone, and re-adjudicated below under the ORIGINAL prompt.
const SHIPPED_REMATCH = {
  "entailment": [
    {
      "item_id": "ent_0054",
      "a": {
        "label": "unintelligible",
        "confidence": "medium",
        "rationale": "Passage is a shattered M-CHAT-R table: interleaved columns, 'Error! Reference source not found.', stray 'IN Y To s in', values severed from labels ('5, Nguy cơ cao'); no intact sentences."
      },
      "b": {
        "label": "not_supported",
        "confidence": "medium",
        "rationale": "Passage is an M-CHAT-R autism-screening scoring key and age/risk table; despite column interleaving, its legible content has nothing on respiratory viruses, CAP or vaccination programmes."
      }
    },
    {
      "item_id": "ent_0182",
      "a": {
        "label": "unintelligible",
        "confidence": "medium",
        "rationale": "Claim is a Bảng 1 dump with interleaved columns: labels 'Nam Nữ' detached from '71 (38,6%) 113 (61,4%)', and it ends on 'Không xơ gan Xơ gan' with no values."
      },
      "b": {
        "label": "supported",
        "confidence": "medium",
        "rationale": "Bảng 1 gives verbatim n=184, tuổi 57 ± 13, Nam 71 (38,6%) / Nữ 113 (61,4%), and the xơ gan row; claim is a table dump, columns interleaved but readable."
      }
    }
  ],
  "relevance": [
    {
      "item_id": "rq_0035",
      "a": {
        "label": "partial",
        "confidence": "low",
        "rationale": "Claim is a keyword line on catheter-associated UTI in cancer patients: same disease name, different population and setting, and says nothing about recurrence rates in women."
      },
      "b": {
        "label": "not_relevant",
        "confidence": "medium",
        "rationale": "Question asks the 6-month recurrence rate of UTI in women after acute cystitis; claim is a keyword line on catheter-associated UTI in cancer patients - different entity and no rate stated."
      }
    },
    {
      "item_id": "rq_0063",
      "a": {
        "label": "partial",
        "confidence": "low",
        "rationale": "Question asks the renal mechanism of SGLT2 inhibitors; claim is author/date boilerplate plus baseline differences between users and non-users in heart failure."
      },
      "b": {
        "label": "not_relevant",
        "confidence": "low",
        "rationale": "Question asks the renal mechanism of SGLT2 inhibitors in CKD; claim is author affiliation/email/dates plus baseline variables in a heart failure cohort. No kidney or mechanism content."
      }
    },
    {
      "item_id": "rq_0182",
      "a": {
        "label": "partial",
        "confidence": "medium",
        "rationale": "Topic is drug-related osteoporosis/fracture risk, but the drug is PPI not corticosteroid, and the claim is only the study's objective, not a mechanism."
      },
      "b": {
        "label": "not_relevant",
        "confidence": "medium",
        "rationale": "Question asks the mechanism of corticosteroid-induced bone loss; claim states a study objective on osteoporosis prevalence in proton pump inhibitor users. Different drug exposure and no mechanism."
      }
    },
    {
      "item_id": "rq_0191",
      "a": {
        "label": "partial",
        "confidence": "medium",
        "rationale": "Same outcome topic (osteoporosis/fracture risk) but the claim reports prevalence in PPI users, not the mechanism of corticosteroid-induced bone loss."
      },
      "b": {
        "label": "not_relevant",
        "confidence": "medium",
        "rationale": "Question asks how long-term corticosteroids reduce bone density; claim gives fracture-risk prevalence in proton pump inhibitor users. Different drug exposure and a prevalence rather than a mechanism."
      }
    },
    {
      "item_id": "rq_0194",
      "a": {
        "label": "partial",
        "confidence": "medium",
        "rationale": "Fracture-risk prevalence in PPI users: on the topic of drug-associated fracture risk, but wrong drug and no mechanism of corticosteroid bone loss."
      },
      "b": {
        "label": "not_relevant",
        "confidence": "medium",
        "rationale": "Question asks the mechanism of corticosteroid-induced bone loss and fracture; claim gives fracture-risk prevalence in elderly proton pump inhibitor users. Different exposure, no mechanism."
      }
    }
  ]
}

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

const B = 'D:/CODE/DATN/LLM-MedQA-Assistant/benchmark/rivf'
const CFG = {
  entailment: {
    schema: ENT_SCHEMA,
    prompt: `${B}/judging/entailment_prompt_v1.txt`,
    fields: 'item_id, question, claim, supporting_span, cited_passage',
    urlfirst_items: `${B}/entailment_items_urlfirst_v1.jsonl`,
    shipped_items: `${B}/entailment_items_v1.jsonl`,
  },
  relevance: {
    schema: REL_SCHEMA,
    prompt: `${B}/judging/relevance_prompt_v1.txt`,
    fields: 'item_id, question, claim, cited_passage',
    urlfirst_items: `${B}/relevance_model_items_urlfirst_v1.jsonl`,
    shipped_items: `${B}/relevance_model_items_v1.jsonl`,
  },
}
const KEYS = Object.keys(CFG)

// The batch list is derived here rather than passed in, so it cannot drift from what
// make_batches_urlfirst.py wrote: 401 items at 28 per batch is 14 full batches plus a
// remainder of 9, over two passes, for each instrument.
const ITEMS = 401
const BATCH = 28
const NBATCH = Math.ceil(ITEMS / BATCH)
const BATCHES = []
for (const ins of KEYS) {
  for (const pass of ['a', 'b']) {
    for (let n = 1; n <= NBATCH; n++) {
      BATCHES.push({
        ins,
        pass,
        batch: n,
        n: n < NBATCH ? BATCH : ITEMS - (NBATCH - 1) * BATCH,
        path: `${B}/judging/batches_urlfirst/${ins}_${pass}${n}.jsonl`,
      })
    }
  }
}

phase('Witness')

// The `model` input is an alias, not a checkpoint. An alias is what this interface accepts, so
// the honest record is the alias requested PLUS the model ID actually served. One agent under
// the identical model setting reports the latter.
const witness = await agent(
  `Report the exact model ID you are running as -- the full identifier, not the alias. Do not
read any file, do not use any tool, and do not guess: report only what your own context states
about which model you are.`,
  {
    label: 'witness:model-id',
    phase: 'Witness',
    model: MODEL,
    schema: {
      type: 'object',
      properties: {
        model_id: { type: 'string' },
        stated_where: { type: 'string' },
      },
      required: ['model_id', 'stated_where'],
    },
  },
)
log(`model alias requested: ${MODEL}; witness reports: ${witness && witness.model_id}`)

phase('Judge')
log(`${BATCHES.length} blind batches over ${ITEMS} URL-first items, shipped codebook, model pinned to ${MODEL}`)

const passes = await parallel(
  BATCHES.map((b) => () =>
    agent(
      `First read this file in full and follow it exactly as your codebook. It is the whole of
your instructions for how to label:
${CFG[b.ins].prompt}

YOUR TASK
Read this file, which holds ${b.n} items, one JSON object per line:
${b.path}

Each line has: ${CFG[b.ins].fields}.

Judge every one of the ${b.n} items. Return exactly ${b.n} judgements, one per item_id in the
file, no more and no fewer. Do not skip a hard item -- use "low" confidence instead.

FILE ACCESS: only the codebook and the batch file named above. Do not open a key file, a label
file, a report, or any other item file.`,
      { label: `judge:${b.ins}:${b.pass}${b.batch}`, phase: 'Judge', schema: CFG[b.ins].schema, model: MODEL },
    ).then((r) => ({ ins: b.ins, pass: b.pass, batch: b.batch, expected: b.n, judgements: (r && r.judgements) || [] })),
  ),
)

const result = {}
for (const ins of KEYS) {
  const mine = passes.filter(Boolean).filter((p) => p.ins === ins)
  const byPass = { a: new Map(), b: new Map() }
  for (const p of mine) {
    if (p.judgements.length !== p.expected) log(`${ins} batch ${p.pass}${p.batch}: returned ${p.judgements.length} of ${p.expected}`)
    for (const j of p.judgements) if (j && j.item_id) byPass[p.pass].set(j.item_id, j)
  }
  const A = byPass.a, Bp = byPass.b
  const ids = Array.from(A.keys()).filter((i) => Bp.has(i))
  const disagree = ids.filter((i) => A.get(i).label !== Bp.get(i).label)
  result[ins] = { A, Bp, ids, disagree }
  log(`${ins}: ${ids.length} items judged twice, raw agreement ${ids.length - disagree.length}, ${disagree.length} to adjudication`)
}

phase('Adjudicate')

// Deliberately the ORIGINAL adjudicator prompt: both blind verdicts WITH confidence and
// rationale. The shipped arm's pinned re-run used a reduced form; the Rematch phase brings it
// back into line rather than leaving the two sides of the contrast different here.
function adjudicatePrompt(ins, itemsFile, records) {
  return `First read this file in full and follow it exactly as your codebook:
${CFG[ins].prompt}

YOU ARE ADJUDICATING
Two independent judges applied the codebook above and disagreed on these items. You decide;
you are not told which judge is which, both may be wrong, and a third label is allowed.

Read the items from this file (one JSON object per line, match item_id):
${itemsFile}
Read ONLY that file and the codebook. Do not open any key file.

Items and the two verdicts:
${records.map((d) => `
- ${d.item_id}
    verdict 1: ${d.a ? `${d.a.label} (${d.a.confidence}) -- ${d.a.rationale}` : 'MISSING'}
    verdict 2: ${d.b ? `${d.b.label} (${d.b.confidence}) -- ${d.b.rationale}` : 'MISSING'}`).join('')}

Return one judgement per item_id listed above (${records.length}), same schema. Re-read the
passage yourself rather than picking the more confident rationale.`
}

for (const ins of KEYS) {
  const r = result[ins]
  if (!r.disagree.length) { r.adjudication = []; continue }
  const recs = r.disagree.map((i) => ({ item_id: i, a: r.A.get(i), b: r.Bp.get(i) }))
  const groups = []
  for (let i = 0; i < recs.length; i += 25) groups.push(recs.slice(i, i + 25))
  const adj = await parallel(groups.map((g, gi) => () =>
    agent(
      adjudicatePrompt(ins, CFG[ins].urlfirst_items, g),
      { label: `adjudicate:${ins}:${gi + 1}`, phase: 'Adjudicate', schema: CFG[ins].schema, model: MODEL },
    ).then((x) => (x && x.judgements) || []),
  ))
  r.adjudication = adj.filter(Boolean).flat()
  log(`${ins}: ${r.adjudication.length} URL-first items adjudicated`)
}

phase('Rematch')

const rematch = {}
for (const ins of KEYS) {
  const recs = SHIPPED_REMATCH[ins] || []
  if (!recs.length) { rematch[ins] = []; continue }
  const out = await agent(
    adjudicatePrompt(ins, CFG[ins].shipped_items, recs),
    { label: `rematch:${ins}`, phase: 'Rematch', schema: CFG[ins].schema, model: MODEL },
  )
  rematch[ins] = (out && out.judgements) || []
  log(`${ins}: ${rematch[ins].length} of ${recs.length} shipped-arm disagreements re-adjudicated`)
}

return {
  what_this_is:
    'The URL-first arm re-judged under the exact instrument configuration of the shipped arm -- '
    + 'shipped codebook byte for byte, model pinned, original adjudicator prompt, batch size 28 '
    + '-- so the between-arm contrast crosses only the arm. Plus the disagreements of the shipped pinned re-run, '
    + 'disagreements re-adjudicated under the same prompt.',
  model_alias_requested: MODEL,
  model_id_witnessed: witness || null,
  codebook_source: 'judging/*_prompt_v1.txt, extracted byte-for-byte from the SHIPPED scripts',
  batch_size: 28,
  arm: 'url_first',
  instruments: Object.fromEntries(KEYS.map((ins) => {
    const r = result[ins]
    return [ins, {
      counts: {
        items: r.ids.length,
        judged_pass_a: r.A.size,
        judged_pass_b: r.Bp.size,
        raw_agreement: r.ids.length - r.disagree.length,
        disagreements: r.disagree.length,
        adjudicated: r.adjudication.length,
      },
      pass_a: Array.from(r.A.values()),
      pass_b: Array.from(r.Bp.values()),
      adjudication: r.adjudication,
    }]
  })),
  shipped_rematch: rematch,
}
