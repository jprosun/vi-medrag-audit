// Historical workflow script (run id wf_24989b5a-8b4, 2026-09-04) that authored and audited
// the 134-question probe grid; served model recovered in ../probe_authoring_provenance_v1.json.
export const meta = {
  name: 'rivf-probe-grid',
  description: 'Author a 135-question Vietnamese medical probe grid, source-agnostic, one agent per specialty',
  phases: [
    { title: 'Author', detail: '12 specialties in parallel + one out-of-corpus control set' },
    { title: 'Audit', detail: 'three independent checks over the assembled grid' },
  ],
}

const RULES = `You are authoring evaluation questions for a Vietnamese medical question-answering system.

ABSOLUTE RULES — a violation invalidates the whole question set:
1. Write from your own general medical knowledge ONLY. Do NOT read any file in the repository, do NOT search the web, do NOT run any tool. Author blind. If you use a tool at all you have broken the protocol.
2. Never phrase a question so it targets a specific known document, journal article, author, institution or dataset. No article titles, no journal names, no "theo nghiên cứu tại bệnh viện X".
3. Questions must be in NATURAL VIETNAMESE, the way a real person would type them. Use ordinary Vietnamese medical vocabulary with correct diacritics.
4. No question may contain the answer, an answer key, or a hint about which source should be retrieved.
5. Vary length and register. Some short and blunt, some longer with context.
6. No two questions may be paraphrases of each other.

WHY THIS MATTERS: every metric computed on these questions is a label-free mechanical count (was a claim's span located, was its source openable, was a figure inside a verified span). No relevance judgement is ever made, so the ONLY way this set can bias a result is through its topic mix. That is why the grid is fixed in advance, published, and hashed before a single question is run.`

const TYPES = `The five question types, with what each is for:

- "patient_faq": a lay person's question, consumer phrasing, no jargon. ("Bị tiểu đường có ăn được chuối không?")
- "clinical_explainer": a clinician or student asking about mechanism, pathophysiology or clinical reasoning. Professional register.
- "study_result_numeric": asks for a quantity — a rate, a proportion, a sample size, an effect size, a threshold. Must be answerable in principle by a number, and must NOT name a specific study.
- "guideline_comparison": asks to compare two options, two drugs, two approaches, or asks what the recommended approach is.
- "differential_or_workup": asks how to distinguish conditions, or what to assess/order in a presentation.`

const SCHEMA = {
  type: 'object',
  required: ['questions'],
  properties: {
    questions: {
      type: 'array',
      items: {
        type: 'object',
        required: ['question', 'question_type', 'specialty', 'rationale'],
        properties: {
          question: { type: 'string', description: 'The Vietnamese question, exactly as a user would type it. No trailing whitespace.' },
          question_type: { type: 'string', enum: ['patient_faq', 'clinical_explainer', 'study_result_numeric', 'guideline_comparison', 'differential_or_workup'] },
          specialty: { type: 'string' },
          rationale: { type: 'string', description: 'One short English clause: what this question is in the grid for. NOT an answer, NOT an expected source.' },
        },
      },
    },
  },
}

const SPECIALTIES = [
  { key: 'tim_mach', vi: 'Tim mạch (tăng huyết áp, suy tim, bệnh mạch vành, rối loạn nhịp, rối loạn lipid máu)' },
  { key: 'ung_buou', vi: 'Ung bướu (ung thư vú, phổi, đại trực tràng, gan, dạ dày; hoá trị, xạ trị, chăm sóc giảm nhẹ)' },
  { key: 'noi_tiet', vi: 'Nội tiết - chuyển hoá (đái tháo đường type 1 và 2, bệnh tuyến giáp, béo phì, loãng xương)' },
  { key: 'ho_hap', vi: 'Hô hấp (COPD, hen phế quản, viêm phổi, lao, ung thư phổi, ngưng thở khi ngủ)' },
  { key: 'tieu_hoa', vi: 'Tiêu hoá - gan mật (viêm gan B và C, xơ gan, loét dạ dày tá tràng, H. pylori, viêm tuỵ, bệnh viêm ruột)' },
  { key: 'than_kinh', vi: 'Thần kinh (đột quỵ, động kinh, Parkinson, sa sút trí tuệ, đau đầu, bệnh thần kinh ngoại biên)' },
  { key: 'than_tiet_nieu', vi: 'Thận - tiết niệu (bệnh thận mạn, lọc máu, sỏi tiết niệu, nhiễm khuẩn tiết niệu, ghép thận)' },
  { key: 'san_phu_khoa', vi: 'Sản phụ khoa (thai kỳ, tiền sản giật, đái tháo đường thai kỳ, ung thư cổ tử cung, vô sinh)' },
  { key: 'nhi', vi: 'Nhi khoa (sơ sinh, tiêm chủng, suy dinh dưỡng, tiêu chảy cấp, viêm phổi trẻ em, sốt xuất huyết ở trẻ)' },
  { key: 'truyen_nhiem', vi: 'Truyền nhiễm (sốt xuất huyết, HIV, lao, viêm gan virus, kháng kháng sinh, nhiễm khuẩn huyết)' },
  { key: 'co_xuong_khop', vi: 'Cơ xương khớp (thoái hoá khớp, viêm khớp dạng thấp, gout, đau lưng, loãng xương gãy xương)' },
  { key: 'huyet_hoc_mien_dich', vi: 'Huyết học - miễn dịch (thiếu máu, thalassemia, rối loạn đông máu, bạch cầu cấp, lupus)' },
]

phase('Author')
log(`Authoring ${SPECIALTIES.length} specialties x 10 questions + 15 out-of-corpus controls`)

const authored = await parallel([
  ...SPECIALTIES.map(s => () =>
    agent(`${RULES}

${TYPES}

YOUR SPECIALTY: ${s.vi}

Write EXACTLY 10 questions in this specialty, distributed as: 2 patient_faq, 2 clinical_explainer, 2 study_result_numeric, 2 guideline_comparison, 2 differential_or_workup.

Set "specialty" to "${s.key}" on every row. Spread the questions across DIFFERENT diseases within the specialty — do not write five questions about the same condition.`,
      { label: `author:${s.key}`, phase: 'Author', schema: SCHEMA })
      .then(r => (r && r.questions ? r.questions.map(q => ({ ...q, specialty: s.key })) : []))
  ),
  () =>
    agent(`${RULES}

YOUR TASK IS DIFFERENT: write EXACTLY 15 OUT-OF-CORPUS CONTROL questions.

These are the abstention controls. Each must be a well-formed, serious Vietnamese medical question that a corpus of Vietnamese clinical journal articles and patient-education pages almost certainly CANNOT answer with evidence. The correct system behaviour is to abstain or to say it lacks evidence, so these measure whether the system refuses honestly rather than improvising.

Use these four mechanisms, at least 3 questions each, and set "question_type" to "out_of_corpus_control" is NOT allowed — instead pick the closest of the five types and say the mechanism in the rationale:
(a) needs a publication date, a recency claim, or a "latest guideline as of <year>" judgement;
(b) asks about a population or setting a Vietnamese clinical corpus would not cover (e.g. a specific non-Vietnamese national programme, a rare paediatric syndrome cohort);
(c) asks for a quantity that would only exist in a registry or a trial that a general corpus does not contain;
(d) the premise is subtly false or self-contradictory, so any confident answer is a failure.

Set "specialty" to "out_of_corpus_control" on every row. In "rationale", name the mechanism as (a), (b), (c) or (d) plus one clause.`,
      { label: 'author:controls', phase: 'Author', schema: SCHEMA })
      .then(r => (r && r.questions ? r.questions.map(q => ({ ...q, specialty: 'out_of_corpus_control' })) : []))
])

const rows = authored.filter(Boolean).flat()
log(`${rows.length} questions authored from ${authored.filter(Boolean).length}/${SPECIALTIES.length + 1} agents`)

phase('Audit')
const AUDIT_SCHEMA = {
  type: 'object',
  required: ['verdict', 'problems'],
  properties: {
    verdict: { type: 'string', enum: ['clean', 'problems_found'] },
    problems: {
      type: 'array',
      items: {
        type: 'object',
        required: ['question', 'problem', 'severity'],
        properties: {
          question: { type: 'string', description: 'The offending question, verbatim' },
          problem: { type: 'string' },
          severity: { type: 'string', enum: ['must_drop', 'must_edit', 'note'] },
          suggested_replacement: { type: 'string', description: 'A corrected question if severity is must_edit' },
        },
      },
    },
  },
}
const LIST = rows.map((q, i) => `${i}. [${q.specialty}/${q.question_type}] ${q.question}`).join('\n')

const AUDITS = [
  { key: 'leakage', brief: `LEAKAGE AUDITOR. Flag any question that names a specific study, article title, journal, author, hospital, institution, dataset, or is phrased so it could only be answered by one particular document. Also flag any question that embeds its own answer or an answer key. This set must be answerable-or-not by the system without the question having pre-selected a source.` },
  { key: 'language', brief: `VIETNAMESE LANGUAGE AUDITOR. You are a Vietnamese medical professional. Flag: wrong or missing diacritics, unnatural machine-translated phrasing, incorrect Vietnamese medical terminology, a question no real Vietnamese speaker would type, or English left in the text. Also flag any question that is medically malformed or nonsensical.` },
  { key: 'grid', brief: `GRID AUDITOR. Check the composition: are there near-duplicate or paraphrased questions across the whole list (report every pair)? Is any question mislabelled for its question_type (e.g. a "study_result_numeric" that does not actually ask for a quantity)? Are questions within a specialty clustered on one disease instead of spread? Report each as a problem with the offending question verbatim.` },
]

const audits = await parallel(AUDITS.map(a => () =>
  agent(`${a.brief}

Do NOT use any tool. Judge the list as given.

THE QUESTION SET (${rows.length} questions):
${LIST}`, { label: `audit:${a.key}`, phase: 'Audit', schema: AUDIT_SCHEMA })
    .then(r => (r ? { auditor: a.key, ...r } : null))
))

return {
  rows,
  audits: audits.filter(Boolean),
  counts: rows.reduce((acc, q) => { acc[q.specialty] = (acc[q.specialty] || 0) + 1; return acc }, {}),
  type_counts: rows.reduce((acc, q) => { acc[q.question_type] = (acc[q.question_type] || 0) + 1; return acc }, {}),
}
