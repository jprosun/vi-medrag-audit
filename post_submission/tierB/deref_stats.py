"""Roll the per-URL dereference results up to the claim level, per arm.

Usage: python -I -X utf8 deref_stats.py <tierB dir>
Reads  deref_results.json (per distinct URL) and key_claims.json (per claim).
Writes deref_stats.json and prints a markdown table.
"""
import json, sys, collections, random

B = sys.argv[1]
res = {r['url']: r for r in json.load(open(B + '/deref_results.json', encoding='utf-8'))}
claims = [c for c in json.load(open(B + '/key_claims.json', encoding='utf-8')) if c.get('kind') == 'real']

ORDER = ['article_title_match', 'reached_title_mismatch', 'issue_index', 'fail_404', 'fail_other', 'error', 'robots_refused', 'no_url']


def cls_of(url):
    if not url:
        return 'no_url'
    r = res.get(url)
    if r is None:
        return 'not_probed'
    if r.get('status') == 'robots_refused':
        return 'robots_refused'
    c = r['class']
    if c.startswith('fail_') and c != 'fail_404':
        return 'fail_other'
    return c


def boot_ci(rows, pred, seed=0, n=5000):
    """percentile cluster bootstrap over query_id of share of rows satisfying pred"""
    byq = collections.defaultdict(list)
    for r in rows:
        byq[r['query_id']].append(pred(r))
    qs = list(byq)
    rng = random.Random(seed)
    vals = []
    for _ in range(n):
        s = [byq[rng.choice(qs)] for _ in qs]
        num = sum(sum(x) for x in s); den = sum(len(x) for x in s)
        vals.append(num / den if den else 0.0)
    vals.sort()
    return vals[int(0.025 * n)], vals[int(0.975 * n)]


out = {}
lines = ['| arm | status | n claims | ' + ' | '.join(ORDER) + ' |', '|---|---|---|' + '---|' * len(ORDER)]
for arm in ('shipped', 'urlfirst'):
    for status in ('returned', 'withheld'):
        rows = [c for c in claims if c['arm'] == arm and c['status'] == status]
        if not rows:
            continue
        cnt = collections.Counter(cls_of(c['source_url']) for c in rows)
        n = len(rows)
        out[f'{arm}/{status}'] = {'n': n, 'counts': dict(cnt)}
        if status == 'returned':
            share_article = cnt['article_title_match'] / n
            lo, hi = boot_ci(rows, lambda r: cls_of(r['source_url']) == 'article_title_match')
            share_open = (cnt['article_title_match'] + cnt['issue_index'] + cnt['reached_title_mismatch']) / n
            out[f'{arm}/{status}'].update(share_article_match=round(share_article, 4), ci_article=[round(lo, 4), round(hi, 4)],
                                           share_reachable_any=round(share_open, 4))
        lines.append(f'| {arm} | {status} | {n} | ' + ' | '.join(str(cnt.get(k, 0)) for k in ORDER) + ' |')

# distinct-URL level
urls = collections.Counter()
for u, r in res.items():
    urls[r.get('status') == 'robots_refused' and 'robots_refused' or r['class']] += 1
out['distinct_urls'] = {'n': len(res), 'counts': dict(urls)}
# strict retention: returned claims whose URL resolves to the cited article, over C0 claims
for arm, c0 in (('shipped', 351), ('urlfirst', 379)):
    k = f'{arm}/returned'
    if k in out:
        strict = out[k]['counts'].get('article_title_match', 0)
        out[arm + '/strict_retention'] = {'article_match_returned': strict, 'c0': c0, 'retention_strict': round(strict / c0, 4),
                                         'retention_binary': round(out[k]['n'] / c0, 4)}
json.dump(out, open(B + '/deref_stats.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('\n'.join(lines))
print()
print(json.dumps({k: v for k, v in out.items() if 'retention' in k or k == 'distinct_urls'}, indent=1))
for arm in ('shipped', 'urlfirst'):
    k = f'{arm}/returned'
    if k in out:
        print(arm, 'returned: article-match share', out[k]['share_article_match'], 'CI', out[k]['ci_article'], '| reachable any', out[k]['share_reachable_any'])
