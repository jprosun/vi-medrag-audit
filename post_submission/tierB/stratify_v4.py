"""Deterministic stratifications requested by the v3 re-review (no model calls).

Usage: python -I -X utf8 stratify_v4.py <repo dir> <tierB dir>
Writes <tierB>/stratify_v4.json and prints a summary.
"""
import json, sys, re, collections, random, math

R, B = sys.argv[1], sys.argv[2]
caps = {'shipped': R + '/benchmark/datasets/test_results/pilot_span_exposure_rivf134_2026-09-05_091659_raw.jsonl',
        'urlfirst': R + '/benchmark/datasets/test_results/pilot_span_exposure_urlfirst_2026-09-07_035612_raw.jsonl'}
qmeta = {}
for l in open(R + '/benchmark/datasets/probe_queries_v2.jsonl', encoding='utf-8'):
    q = json.loads(l); m = re.match(r'rivf_grid_v2:([^/]+)/(.+)', q['source'])
    qmeta[q['query_id']] = {'specialty': m.group(1), 'type': m.group(2), 'control': m.group(1) == 'out_of_corpus_control'}
rec = {}
for arm, p in caps.items():
    for l in open(p, encoding='utf-8'):
        r = json.loads(l); rec[(arm, r['query_id'])] = r
res = json.load(open(B + '/judge_result.json', encoding='utf-8'))
FIN, PA, PB = res['final'], res['passA'], res['passB']
keyA = [k for k in json.load(open(B + '/key_answers.json', encoding='utf-8')) if k['kind'] == 'real']
keyC = [k for k in json.load(open(B + '/key_claims.json', encoding='utf-8')) if k['kind'] == 'real']
out = {}


def wilson_deff(x, n, clusters_sizes, z=1.96):
    """Wilson interval with n replaced by effective n = n / deff, deff = 1 + (m-1)*icc estimated crudely
    via the variance ratio of the cluster-level proportions (Kish). Falls back to deff = 1."""
    if n == 0:
        return None
    p = x / n
    # Kish design effect from cluster totals
    k = len(clusters_sizes)
    mbar = n / k
    if 0 < p < 1 and k > 1:
        var_cluster = sum((xi - p * ni) ** 2 for xi, ni in clusters_sizes) / ((k - 1) * mbar ** 2) / k
        var_srs = p * (1 - p) / n
        deff = max(1.0, var_cluster / var_srs) if var_srs > 0 else 1.0
    else:
        deff = 1.0
    ne = n / deff
    c = z * z / ne
    centre = (p + c / 2) / (1 + c)
    half = z * math.sqrt(p * (1 - p) / ne + c / (4 * ne)) / (1 + c)
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4), round(deff, 2)]


# 1. answers: by arm x {all, answerable, controls} x coverage_mode x type, with abstention label on controls
ans = []
for k in keyA:
    r = rec[(k['arm'], k['query_id'])]; md = r['payload']['metadata']
    ans.append({'arm': k['arm'], 'qid': k['query_id'], 'label': FIN[k['item_id']]['label'], 'type': qmeta[k['query_id']]['type'],
                'control': qmeta[k['query_id']]['control'], 'coverage_mode': md.get('coverage_mode'), 'abstention': md.get('abstention_label'),
                'profile': md['pipeline'].get('retrieval_profile'), 'n_returned': len(r['payload']['claim_attributions']),
                'inline_cites': len(re.findall(r'\[\d+\]', r['payload']['answer']))})
for arm in ('shipped', 'urlfirst'):
    a = [x for x in ans if x['arm'] == arm]
    d = {}
    for name, f in (('all', lambda x: True), ('answerable', lambda x: not x['control']), ('controls', lambda x: x['control'])):
        g = [x for x in a if f(x)]; n = len(g); y = sum(x['label'] == 'relevant' for x in g)
        d[name] = {'n': n, 'relevant': y, 'rate': round(y / n, 4)}
    d['by_coverage_mode_answerable'] = {}
    for cm in sorted({x['coverage_mode'] for x in a}):
        g = [x for x in a if x['coverage_mode'] == cm and not x['control']]
        if g: d['by_coverage_mode_answerable'][cm] = {'n': len(g), 'relevant': sum(x['label'] == 'relevant' for x in g), 'rate': round(sum(x['label'] == 'relevant' for x in g) / len(g), 3)}
    d['by_type_answerable'] = {}
    for t in sorted({x['type'] for x in a}):
        g = [x for x in a if x['type'] == t and not x['control']]
        y = sum(x['label'] == 'relevant' for x in g)
        lo, hi, _ = wilson_deff(y, len(g), [(int(x['label'] == 'relevant'), 1) for x in g]) if g else (None, None, None)
        d['by_type_answerable'][t] = {'n': len(g), 'relevant': y, 'rate': round(y / len(g), 3), 'wilson': [lo, hi]}
    d['by_profile_answerable'] = {p: {'n': len(g), 'relevant': sum(x['label'] == 'relevant' for x in g)} for p in ('standard', 'deep')
                                  for g in [[x for x in a if x['profile'] == p and not x['control']]]}
    d['controls_abstention_label'] = dict(collections.Counter(x['abstention'] for x in a if x['control']))
    d['controls_relevant_by_abstention'] = dict(collections.Counter((x['abstention'], x['label']) for x in a if x['control']).items()) and {f'{k[0]}|{k[1]}': v for k, v in collections.Counter((x['abstention'], x['label']) for x in a if x['control']).items()}
    d['answers_with_inline_citations'] = sum(x['inline_cites'] > 0 for x in a)
    # answers with a non-empty list and no responsive returned claim
    claims_rel = collections.defaultdict(int)
    for k in keyC:
        if k['arm'] == arm and k['status'] == 'returned' and FIN[k['item_id']]['label'] == 'relevant': claims_rel[k['query_id']] += 1
    nonempty = [x for x in a if x['n_returned'] > 0]
    d['nonempty_list_answers'] = len(nonempty)
    d['nonempty_list_no_responsive_claim'] = sum(claims_rel[x['qid']] == 0 for x in nonempty)
    d['nonempty_list_answer_relevant_no_responsive_claim'] = sum(claims_rel[x['qid']] == 0 and x['label'] == 'relevant' for x in nonempty)
    d['answer_relevant_with_nonempty_list'] = sum(x['label'] == 'relevant' for x in nonempty)
    d['empty_list_answer_relevant'] = sum(x['label'] == 'relevant' for x in a if x['n_returned'] == 0)
    d['empty_list_answers'] = sum(x['n_returned'] == 0 for x in a)
    out['answers_' + arm] = d

# 2. claims: responsive extracted per arm, patient-FAQ, question-level for withheld responsive, dedupe, rare-rate intervals
cl = []
for k in keyC:
    cl.append({**k, 'label': FIN[k['item_id']]['label'], 'type': qmeta[k['query_id']]['type'], 'passA': PA.get(k['item_id'], {}).get('label'), 'passB': PB.get(k['item_id'], {}).get('label'),
               'trust': None})
for arm in ('shipped', 'urlfirst'):
    c = [x for x in cl if x['arm'] == arm]
    d = {'extracted': len(c), 'extracted_responsive': sum(x['label'] == 'relevant' for x in c),
         'patient_faq_extracted': sum(x['type'] == 'patient_faq' for x in c),
         'patient_faq_responsive': sum(x['type'] == 'patient_faq' and x['label'] == 'relevant' for x in c)}
    ret = [x for x in c if x['status'] == 'returned']
    by_q = collections.defaultdict(list)
    for x in ret: by_q[x['query_id']].append(int(x['label'] == 'relevant'))
    y = sum(x['label'] == 'relevant' for x in ret)
    d['returned'] = len(ret); d['returned_responsive_final'] = y
    d['returned_responsive_passA'] = sum(x['passA'] == 'relevant' for x in ret)
    d['returned_responsive_passB'] = sum(x['passB'] == 'relevant' for x in ret)
    d['returned_wilson_deff'] = wilson_deff(y, len(ret), [(sum(v), len(v)) for v in by_q.values()])
    allq = collections.defaultdict(list)
    for x in c: allq[x['query_id']].append(int(x['label'] == 'relevant'))
    d['extracted_wilson_deff'] = wilson_deff(d['extracted_responsive'], len(c), [(sum(v), len(v)) for v in allq.values()])
    if arm == 'shipped':
        wr = [x for x in c if x['status'] == 'withheld' and x['drop_reason'] == 'cited_record_not_citable' and x['label'] == 'relevant']
        d['withheld_responsive'] = len(wr)
        d['withheld_responsive_questions'] = len({x['query_id'] for x in wr})
        d['withheld_responsive_per_question'] = dict(collections.Counter(x['query_id'] for x in wr))
        d['withheld_responsive_distinct_texts'] = len({re.sub(r'\s+', ' ', x['claim']).strip() for x in wr})
        rq = {x['query_id'] for x in c if x['label'] == 'relevant'}
        d['questions_with_any_responsive_claim'] = len(rq)
        d['questions_with_responsive_withheld_only'] = len({x['query_id'] for x in wr} - {x['query_id'] for x in ret if x['label'] == 'relevant'})
        d['questions_with_any_withheld_citability'] = len({x['query_id'] for x in c if x['drop_reason'] == 'cited_record_not_citable'})
        d['questions_with_returned'] = len({x['query_id'] for x in ret})
    out['claims_' + arm] = d

# 3. trust tier: retrieved chunks, returned claims (by chunk), withheld responsive
for arm in ('shipped', 'urlfirst'):
    tiers = collections.Counter(); ret_tiers = collections.Counter(); wr_tiers = collections.Counter()
    for (a, qid), r in rec.items():
        if a != arm: continue
        chunks = {c['id']: c for c in r['payload']['retrieved_chunks']}
        for c in r['payload']['retrieved_chunks']: tiers[c['metadata'].get('trust_tier')] += 1
        for c in r['payload']['claim_attributions']:
            ch = chunks.get(c.get('chunk_id')); ret_tiers[ch['metadata'].get('trust_tier') if ch else None] += 1
    out['trust_' + arm] = {'retrieved': dict(tiers), 'returned_claims': dict(ret_tiers)}

# 4. verifier: code override vs model verdict, from verification_issues text
for arm in ('shipped', 'urlfirst'):
    vc = collections.Counter()
    for (a, qid), r in rec.items():
        if a != arm: continue
        md = r['payload']['metadata']; st = md.get('verification_status'); iss = ' | '.join(md.get('verification_issues') or [])
        if 'downgraded to revise' in iss: kind = 'model_pass_overridden_by_code'
        elif 'truncat' in iss.lower() or 'prefix' in iss.lower() or 'no status' in iss.lower(): kind = 'truncated_or_recovered'
        elif st == 'pass': kind = 'model_pass'
        else: kind = 'model_' + str(st)
        vc[(st, kind)] += 1
    out['verifier_' + arm] = {f'{k[0]}|{k[1]}': v for k, v in vc.items()}
r075 = rec[('shipped', 'rivf_075')]['payload']['answer']
out['rivf_075_answer_head'] = r075[:200]

# 5. small-integer quantities (1-2 digits + unit) in delivered answers, shipped
UNIT = r'(mg|mcg|µg|g|kg|ml|mL|l|lít|giờ|ngày|tuần|tháng|năm|tuổi|lần|viên|ống|liều|phút|giây|mmHg|mmol|%|cm|mm|IU|UI)'
# integers of one or two digits only: decimals and percentages are claim figures and are gated
pat = re.compile(r'(?<![\d.,])(\d{1,2})(?![.,]\d)\s?' + UNIT + r'\b', re.I)
tot = 0; nans = 0
for (a, qid), r in rec.items():
    if a != 'shipped': continue
    n = len(pat.findall(re.sub(r'\[\d+\]', '', r['payload']['answer'])))
    tot += n; nans += n > 0
out['small_int_unit_quantities_shipped'] = {'count': tot, 'answers_with_any': nans}

json.dump(out, open(B + '/stratify_v4.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
