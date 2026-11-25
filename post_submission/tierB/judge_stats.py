"""Statistics for the Tier-B relevance judging (claims: returned + withheld, both arms; narrative answers).

Usage: python -I -X utf8 judge_stats.py <tierB dir> <repo dir>
Expects <tierB>/judge_result.json = {passA:{id:{label,...}}, passB:{...}, adjudicated:{...}, final:{id:{label,source}}}
Writes <tierB>/judge_stats.json and prints markdown.
"""
import json, sys, re, collections, random

B, R = sys.argv[1], sys.argv[2]
res = json.load(open(B + '/judge_result.json', encoding='utf-8'))
A, Bp, FIN = res['passA'], res['passB'], res['final']
keyC = {k['item_id']: k for k in json.load(open(B + '/key_claims.json', encoding='utf-8'))}
keyA = {k['item_id']: k for k in json.load(open(B + '/key_answers.json', encoding='utf-8'))}

# question metadata
qmeta = {}
for l in open(R + '/benchmark/datasets/probe_queries_v2.jsonl', encoding='utf-8'):
    q = json.loads(l); m = re.match(r'rivf_grid_v2:([^/]+)/(.+)', q['source'])
    qmeta[q['query_id']] = {'specialty': m.group(1), 'type': m.group(2), 'control_q': m.group(1) == 'out_of_corpus_control'}
# profile per arm/question from captures
caps = {'shipped': R + '/benchmark/datasets/test_results/pilot_span_exposure_rivf134_2026-09-05_091659_raw.jsonl',
        'urlfirst': R + '/benchmark/datasets/test_results/pilot_span_exposure_urlfirst_2026-09-07_035612_raw.jsonl'}
profile = {}
for arm, p in caps.items():
    for l in open(p, encoding='utf-8'):
        r = json.loads(l)
        profile[(arm, r['query_id'])] = (r['payload']['metadata'].get('pipeline') or {}).get('retrieval_profile', 'unknown')


def kappa(pairs):
    n = len(pairs)
    if n == 0:
        return float('nan'), float('nan')
    po = sum(a == b for a, b in pairs) / n
    labs = set(x for p in pairs for x in p)
    pe = sum((sum(a == l for a, _ in pairs) / n) * (sum(b == l for _, b in pairs) / n) for l in labs)
    return po, (po - pe) / (1 - pe) if pe < 1 else float('nan')


def boot(rows, pred, seed=0, n=5000):
    byq = collections.defaultdict(list)
    for r in rows:
        byq[r['query_id']].append(1 if pred(r) else 0)
    qs = list(byq); rng = random.Random(seed); vals = []
    for _ in range(n):
        s = [byq[rng.choice(qs)] for _ in qs]
        den = sum(len(x) for x in s); vals.append(sum(sum(x) for x in s) / den if den else 0.0)
    vals.sort(); return round(vals[int(0.025 * n)], 4), round(vals[int(0.975 * n)], 4)


def paired_boot(rows_a, rows_b, pred, seed=0, n=5000):
    """difference of pooled rates (b - a), resampling the union of question ids"""
    qa = collections.defaultdict(list); qb = collections.defaultdict(list)
    for r in rows_a: qa[r['query_id']].append(1 if pred(r) else 0)
    for r in rows_b: qb[r['query_id']].append(1 if pred(r) else 0)
    qs = sorted(set(qa) | set(qb)); rng = random.Random(seed); vals = []
    for _ in range(n):
        s = [rng.choice(qs) for _ in qs]
        na = sum(len(qa[q]) for q in s); nb = sum(len(qb[q]) for q in s)
        ra = sum(sum(qa[q]) for q in s) / na if na else 0.0; rb = sum(sum(qb[q]) for q in s) / nb if nb else 0.0
        vals.append(rb - ra)
    vals.sort(); return round(vals[int(0.025 * n)], 4), round(vals[int(0.975 * n)], 4)


out = {}
md = []
# ---------- agreement
for name, keys in (('claims', keyC), ('answers', keyA)):
    allp = [(A[i]['label'], Bp[i]['label']) for i in keys if i in A and i in Bp]
    realp = [(A[i]['label'], Bp[i]['label']) for i in keys if i in A and i in Bp and keys[i]['kind'] == 'real']
    po1, k1 = kappa(allp); po2, k2 = kappa(realp)
    ctrl = [FIN[i]['label'] for i in keys if keys[i]['kind'] == 'control' and i in FIN]
    out[f'agreement_{name}'] = {'n_all': len(allp), 'agree_all': round(po1, 4), 'kappa_all': round(k1, 4), 'n_real': len(realp), 'agree_real': round(po2, 4), 'kappa_real': round(k2, 4),
                                'controls_final': dict(collections.Counter(ctrl)), 'unlabelled': [i for i in keys if i not in FIN]}
    md.append(f'- {name}: agreement {po1:.3f} (kappa {k1:.3f}) over {len(allp)} items incl. controls; {po2:.3f} (kappa {k2:.3f}) on {len(realp)} real items; controls final labels {dict(collections.Counter(ctrl))}')

# ---------- claims: rates by arm x status
rows = []
for i, k in keyC.items():
    if k['kind'] != 'real' or i not in FIN or FIN[i]['label'] is None:
        continue
    rows.append({**k, 'label': FIN[i]['label'], 'type': qmeta[k['query_id']]['type'], 'control_q': qmeta[k['query_id']]['control_q'], 'profile': profile.get((k['arm'], k['query_id']), '?')})
rel = lambda r: r['label'] == 'relevant'
md.append('\n| arm | status | drop reason | n | relevant | partial | not_relevant | responsiveness [95% CI] |')
md.append('|---|---|---|---|---|---|---|---|')
for arm in ('shipped', 'urlfirst'):
    groups = [('returned', ''), ('withheld', 'cited_record_not_citable'), ('withheld', 'span_not_found_in_cited_chunk'), ('withheld', 'chunk_id_not_resolvable'), ('withheld', '*')]
    for status, reason in groups:
        g = [r for r in rows if r['arm'] == arm and r['status'] == status and (reason in ('', '*') or r['drop_reason'] == reason)]
        if not g:
            continue
        c = collections.Counter(r['label'] for r in g); n = len(g); rate = c['relevant'] / n
        lo, hi = boot(g, rel)
        out[f'claims/{arm}/{status}/{reason or "all"}'] = {'n': n, 'counts': dict(c), 'responsiveness': round(rate, 4), 'ci': [lo, hi]}
        md.append(f'| {arm} | {status} | {reason or "-"} | {n} | {c["relevant"]} | {c["partial"]} | {c["not_relevant"]} | {rate:.3f} [{lo:.3f}, {hi:.3f}] |')
# withheld-by-citability vs returned, shipped, same instrument: difference + CI
g_ret = [r for r in rows if r['arm'] == 'shipped' and r['status'] == 'returned']
g_cit = [r for r in rows if r['arm'] == 'shipped' and r['drop_reason'] == 'cited_record_not_citable']
if g_ret and g_cit:
    d = g_cit and (sum(rel(r) for r in g_cit) / len(g_cit) - sum(rel(r) for r in g_ret) / len(g_ret))
    lo, hi = paired_boot(g_ret, g_cit, rel)
    out['claims/shipped/withheld_minus_returned'] = {'diff': round(d, 4), 'ci': [lo, hi]}
    md.append(f'\nShipped arm, withheld-for-citability minus returned (same instrument): {d:+.4f} [{lo:.4f}, {hi:.4f}]')
    # 'partial or relevant' (on-topic) difference too
    ontopic = lambda r: r['label'] != 'not_relevant'
    d2 = sum(ontopic(r) for r in g_cit) / len(g_cit) - sum(ontopic(r) for r in g_ret) / len(g_ret)
    lo2, hi2 = paired_boot(g_ret, g_cit, ontopic)
    out['claims/shipped/withheld_minus_returned_ontopic'] = {'diff': round(d2, 4), 'ci': [lo2, hi2]}
    md.append(f'On-topic (relevant or partial) withheld minus returned: {d2:+.4f} [{lo2:.4f}, {hi2:.4f}]')
# all C0 claims shipped (what responsiveness would have been with no gate)
g_c0 = [r for r in rows if r['arm'] == 'shipped']
c = collections.Counter(r['label'] for r in g_c0); lo, hi = boot(g_c0, rel)
out['claims/shipped/C0_all'] = {'n': len(g_c0), 'counts': dict(c), 'responsiveness': round(c['relevant'] / len(g_c0), 4), 'ci': [lo, hi]}
md.append(f'All 351 C0 claims (shipped), no gate: relevant {c["relevant"]}/{len(g_c0)} = {c["relevant"]/len(g_c0):.3f} [{lo:.3f}, {hi:.3f}]')
# by type and profile (returned, shipped) and by stratum (URL-less vs citable), all C0
for name, keyf in (('type', lambda r: r['type']), ('profile', lambda r: r['profile']), ('urlless', lambda r: 'urlless' if (not r['source_url']) else 'citable')):
    tab = {}
    for arm in ('shipped', 'urlfirst'):
        g = [r for r in rows if r['arm'] == arm]
        for v in sorted(set(keyf(r) for r in g)):
            gg = [r for r in g if keyf(r) == v]; cc = collections.Counter(r['label'] for r in gg)
            tab[f'{arm}/{v}'] = {'n': len(gg), 'relevant': cc['relevant'], 'partial': cc['partial'], 'not_relevant': cc['not_relevant'], 'responsiveness': round(cc['relevant'] / len(gg), 4)}
    out[f'claims_by_{name}_allC0'] = tab
    md.append(f'\nClaims by {name} (all C0 claims per arm): ' + '; '.join(f'{k}: {v["relevant"]}/{v["n"]}={v["responsiveness"]:.3f}' for k, v in tab.items()))
# comparison with the artifact's original returned-claim labels (shipped): same claim text + query
try:
    rk = json.load(open(R + '/benchmark/rivf/relevance_model_key_v1.json', encoding='utf-8'))
    rj = json.load(open(R + '/benchmark/rivf/relevance_model_judgements_v1.json', encoding='utf-8'))
    pa = {x['item_id']: x['label'] for x in rj['pass_a']}; pb = {x['item_id']: x['label'] for x in rj['pass_b']}
    adj = {x['item_id']: x['label'] for x in rj.get('adjudication', []) if isinstance(x, dict) and 'item_id' in x}
    orig = {}
    items = rk if isinstance(rk, dict) else {x['item_id']: x for x in rk}
    for iid, meta in items.items():
        if not isinstance(meta, dict) or meta.get('kind') == 'control':
            continue
        lab = pa.get(iid) if pa.get(iid) == pb.get(iid) else adj.get(iid, pa.get(iid))
        qid = meta.get('query_id') or meta.get('question_id'); cl = (meta.get('claim') or '').strip()
        if qid and cl:
            orig[(qid, cl)] = lab
    conf = collections.Counter()
    for r in g_ret:
        o = orig.get((r['query_id'], r['claim']))
        if o:
            conf[(o, r['label'])] += 1
    out['shipped_returned_vs_original_labels'] = {f'{a}->{b}': n for (a, b), n in conf.items()}
    md.append('\nShipped returned claims: original label -> prior-free label: ' + ', '.join(f'{a}->{b}: {n}' for (a, b), n in sorted(conf.items())))
except Exception as e:
    out['shipped_returned_vs_original_labels'] = f'not computed: {type(e).__name__}: {e}'

# ---------- answers
arows = []
for i, k in keyA.items():
    if k['kind'] != 'real' or i not in FIN or FIN[i]['label'] is None:
        continue
    arows.append({**k, 'label': FIN[i]['label'], 'type': qmeta[k['query_id']]['type'], 'control_q': qmeta[k['query_id']]['control_q'], 'profile': profile.get((k['arm'], k['query_id']), '?')})
md.append('\n| arm | subset | n answers | relevant | partial | not_relevant | answer responsiveness [95% CI] |')
md.append('|---|---|---|---|---|---|---|')
for arm in ('shipped', 'urlfirst'):
    subsets = [('all 134', lambda r: True), ('answerable 119', lambda r: not r['control_q']), ('controls 15', lambda r: r['control_q']),
               ('with returned claims', lambda r: r['n_returned'] > 0), ('no returned claims', lambda r: r['n_returned'] == 0)]
    for name, f in subsets:
        g = [r for r in arows if r['arm'] == arm and f(r)]
        if not g:
            continue
        c = collections.Counter(r['label'] for r in g); n = len(g)
        # answers are one per question: bootstrap over questions = simple percentile bootstrap
        lo, hi = boot(g, rel)
        out[f'answers/{arm}/{name}'] = {'n': n, 'counts': dict(c), 'responsiveness': round(c['relevant'] / n, 4), 'ci': [lo, hi]}
        md.append(f'| {arm} | {name} | {n} | {c["relevant"]} | {c["partial"]} | {c["not_relevant"]} | {c["relevant"]/n:.3f} [{lo:.3f}, {hi:.3f}] |')
# paired difference between arms on all 134 answers
ga = [r for r in arows if r['arm'] == 'shipped']; gb = [r for r in arows if r['arm'] == 'urlfirst']
if ga and gb:
    d = sum(rel(r) for r in gb) / len(gb) - sum(rel(r) for r in ga) / len(ga); lo, hi = paired_boot(ga, gb, rel)
    out['answers/urlfirst_minus_shipped'] = {'diff': round(d, 4), 'ci': [lo, hi]}
    md.append(f'\nAnswer-level responsiveness, URL-first minus shipped: {d:+.4f} [{lo:.4f}, {hi:.4f}]')
    # by type and profile
    for name, keyf in (('type', lambda r: r['type']), ('profile', lambda r: r['profile'])):
        tab = {}
        for arm, g in (('shipped', ga), ('urlfirst', gb)):
            for v in sorted(set(keyf(r) for r in g)):
                gg = [r for r in g if keyf(r) == v]; cc = collections.Counter(r['label'] for r in gg)
                tab[f'{arm}/{v}'] = {'n': len(gg), 'relevant': cc['relevant'], 'responsiveness': round(cc['relevant'] / len(gg), 4)}
        out[f'answers_by_{name}'] = tab
        md.append(f'Answers by {name}: ' + '; '.join(f'{k}: {v["relevant"]}/{v["n"]}={v["responsiveness"]:.3f}' for k, v in tab.items()))
# claim-level vs answer-level joint (shipped): answers that are relevant but carry no relevant claim, etc.
claim_rel_q = collections.defaultdict(lambda: {'shipped': False, 'urlfirst': False})
for r in g_ret: claim_rel_q[r['query_id']]['shipped'] |= rel(r)
for r in rows:
    if r['arm'] == 'urlfirst' and r['status'] == 'returned': claim_rel_q[r['query_id']]['urlfirst'] |= rel(r)
for arm, g in (('shipped', ga), ('urlfirst', gb)):
    cross = collections.Counter((('answer_relevant' if rel(r) else 'answer_not'), ('claim_relevant' if claim_rel_q[r['query_id']][arm] else 'claim_not')) for r in g)
    out[f'answers_vs_claims/{arm}'] = {f'{a}&{b}': n for (a, b), n in cross.items()}
    md.append(f'{arm}: answer-level vs any-returned-claim-relevant cross-tab: ' + ', '.join(f'{a}&{b}={n}' for (a, b), n in sorted(cross.items())))

json.dump(out, open(B + '/judge_stats.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('\n'.join(md))
