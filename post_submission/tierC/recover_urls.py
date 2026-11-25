"""Recover source URLs for the URL-less patient-education stratum by matching record titles to the
source site's public sitemap (robots.txt allows /sitemap*; search pages are disallowed and not used),
then verifying each candidate page's <h1>/<title> against the record title.

Usage: python -I -X utf8 recover_urls.py <repo dir> <out dir>
"""
import json, sys, re, time, gzip, unicodedata, urllib.request, urllib.robotparser, difflib, html, collections, ssl

R, OUT = sys.argv[1], sys.argv[2]
UA = 'vi-medrag-audit-research/1.0 (title-to-URL recovery; low rate)'
BASE = 'https://nhathuoclongchau.com.vn'
ctx = ssl.create_default_context()
rp = urllib.robotparser.RobotFileParser()
_robots = __import__('subprocess').run(['curl', '-s', '--max-time', '20', '-A', UA, BASE + '/robots.txt'], capture_output=True).stdout.decode('utf-8', 'ignore')
rp.parse(_robots.splitlines())


def log(*a):
    print(*a, file=sys.stderr, flush=True)


import subprocess


def get(url, n=8_000_000):
    """Fetch with curl and the same honest research User-Agent (urllib is refused by the CDN's
    client fingerprinting; curl with the identical UA is served). robots.txt is honoured."""
    if not rp.can_fetch(UA, url):
        raise PermissionError('robots')
    p = subprocess.run(['curl', '-s', '-L', '--compressed', '--max-time', '40', '-A', UA, '-w', '\n__STATUS__%{http_code}', url],
                       capture_output=True)
    out = p.stdout
    body, _, status = out.rpartition(b'\n__STATUS__')
    if status.strip() != b'200':
        raise IOError('HTTP ' + status.decode(errors='ignore'))
    if url.endswith('.gz'):
        try:
            body = gzip.decompress(body)
        except Exception:
            pass
    return body[:n].decode('utf-8', 'ignore')


def slug(s):
    s = unicodedata.normalize('NFD', html.unescape(s or '').lower()).replace('đ', 'd')
    s = ''.join(ch for ch in s if unicodedata.category(ch) != 'Mn')
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')


def norm(s):
    s = unicodedata.normalize('NFC', html.unescape(s or '')).lower()
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', s)).strip()


# 1. titles behind URL-less claims (primary) and behind all retrieved URL-less chunks (secondary)
cap = R + '/benchmark/datasets/test_results/pilot_span_exposure_rivf134_2026-09-05_091659_raw.jsonl'
claim_titles = collections.Counter()
chunk_titles = collections.Counter()
claim_rows = []
for l in open(cap, encoding='utf-8'):
    r = json.loads(l)
    pl = r['payload']
    chunks = {c['id']: c for c in pl['retrieved_chunks']}
    for c in pl['retrieved_chunks']:
        m = c['metadata']
        if m.get('source_id') == 'hf_vi_mtue29_medical':
            chunk_titles[m.get('canonical_title') or m.get('title')] += 1
    for status, lst in (('returned', pl['claim_attributions']), ('withheld', pl['dropped_claims'])):
        for c in lst:
            if not c.get('source_url') and c.get('chunk_id'):
                ch = chunks.get(c['chunk_id'])
                t = (ch['metadata'].get('canonical_title') if ch else None) or c.get('title')
                claim_titles[t] += 1
                claim_rows.append({'query_id': r['query_id'], 'status': status, 'drop_reason': c.get('drop_reason', ''),
                                   'claim': c.get('claim', ''), 'title': t})
log('claim titles', len(claim_titles), 'chunk titles', len(chunk_titles))

# 2. sitemap crawl
idx = get(BASE + '/sitemap.xml')
subs = re.findall(r'<loc>\s*([^<\s]+)\s*</loc>', idx)
log('sitemap index entries:', len(subs), subs[:20])
urls = []
for i, s in enumerate(subs):
    try:
        x = get(s)
    except Exception as e:
        log('  skip', s, type(e).__name__)
        continue
    locs = re.findall(r'<loc>\s*([^<\s]+)\s*</loc>', x)
    if locs and locs[0].endswith(('.xml', '.xml.gz')):
        for s2 in locs:
            try:
                urls += re.findall(r'<loc>\s*([^<\s]+)\s*</loc>', get(s2))
            except Exception:
                pass
            time.sleep(1.0)
    else:
        urls += locs
    log(f'  {i + 1}/{len(subs)} {s} -> total urls {len(urls)}')
    time.sleep(1.0)
all_urls = sorted(set(urls))
json.dump(all_urls, open(OUT + '/sitemap_urls.json', 'w', encoding='utf-8'))
by_slug = {}
for u in all_urls:
    last = u.rstrip('/').rsplit('/', 1)[-1]
    by_slug.setdefault(re.sub(r'\.html?$', '', last), []).append(u)
log('sitemap URLs:', len(all_urls), 'distinct slugs:', len(by_slug))
slug_keys = list(by_slug)


def candidates(t):
    s = slug(t)
    if s in by_slug:
        return by_slug[s], 'exact_slug'
    keys = difflib.get_close_matches(s, slug_keys, n=1, cutoff=0.88)
    return (by_slug[keys[0]], 'fuzzy_slug') if keys else ([], 'none')


# 3. claim titles: match + verify by fetching the page
verified = {}
for t in sorted(claim_titles, key=lambda x: -claim_titles[x]):
    cands, how = candidates(t)
    rec = {'title': t, 'n_claims': claim_titles[t], 'match': how, 'url': cands[0] if cands else None}
    if cands:
        try:
            page = get(cands[0], 1_500_000)
            h1 = re.search(r'<h1[^>]*>(.*?)</h1>', page, re.S | re.I)
            h1 = re.sub(r'<[^>]+>', ' ', h1.group(1)).strip() if h1 else ''
            tt = re.search(r'<title[^>]*>(.*?)</title>', page, re.S | re.I)
            tt = html.unescape(tt.group(1)).strip() if tt else ''
            sims = [difflib.SequenceMatcher(None, norm(t), norm(x)).ratio() for x in (h1, tt) if x]
            sim = max(sims) if sims else 0.0
            rec.update(h1=h1[:200], page_title=tt[:200], sim=round(sim, 3), verified=sim >= 0.8)
        except Exception as e:
            rec.update(error=type(e).__name__, verified=False)
        time.sleep(1.5)
    else:
        rec['verified'] = False
    verified[t] = rec
    log(f"{rec['match']:10s} verified={rec.get('verified')} sim={rec.get('sim')} | {t[:70]}")

# chunk titles: slug match only (no page fetch)
chunk_match = collections.Counter()
chunk_match_w = collections.Counter()
for t, n in chunk_titles.items():
    h = candidates(t)[1]
    chunk_match[h] += 1
    chunk_match_w[h] += n

# 4. roll-up
by_status = collections.defaultdict(collections.Counter)
for row in claim_rows:
    key = row['status'] + ('/' + row['drop_reason'] if row['drop_reason'] else '')
    by_status[key]['total'] += 1
    by_status[key]['recovered'] += bool(verified[row['title']].get('verified'))
summary = {
    'sitemap_urls': len(all_urls),
    'claim_titles': {'distinct': len(claim_titles), 'slug_matched': sum(v['match'] != 'none' for v in verified.values()),
                     'verified': sum(bool(v.get('verified')) for v in verified.values())},
    'claims': {k: dict(v) for k, v in by_status.items()},
    'retrieved_chunk_titles': {'distinct': len(chunk_titles), 'total_chunks': sum(chunk_titles.values()),
                               'match_by_title': dict(chunk_match), 'match_by_chunk_weight': dict(chunk_match_w)},
}
json.dump({'summary': summary, 'titles': verified, 'claim_rows': claim_rows}, open(OUT + '/url_recovery.json', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print(json.dumps(summary, ensure_ascii=False, indent=1))
