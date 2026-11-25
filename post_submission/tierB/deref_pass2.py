import json, sys, re, time, urllib.request, html, difflib, unicodedata, ssl
B = sys.argv[1]
UA = 'vi-medrag-audit-tierB/1.0 (+research; contact: reviewer)'
ctx = ssl.create_default_context()
def norm(s):
    s = unicodedata.normalize('NFC', html.unescape(s or '')).lower()
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', s)).strip()
def meta(body, name):
    m = re.search(r'<meta[^>]+name=["\']' + re.escape(name) + r'["\'][^>]*content=["\']([^"\']*)["\']', body, re.I) or \
        re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*name=["\']' + re.escape(name) + r'["\']', body, re.I)
    return html.unescape(m.group(1)).strip() if m else ''
res = json.load(open(B + '/deref_results.json', encoding='utf-8'))
for i, r in enumerate(res):
    if r.get('class') != 'reached_title_mismatch':
        continue
    req = urllib.request.Request(r['final_url'], headers={'User-Agent': UA, 'Accept-Language': 'vi,en'})
    try:
        with urllib.request.urlopen(req, timeout=25, context=ctx) as resp:
            body = resp.read(600000).decode('utf-8', 'ignore')
    except Exception as e:
        r['pass2_error'] = type(e).__name__; continue
    ct = meta(body, 'citation_title') or meta(body, 'DC.Title') or meta(body, 'og:title')
    h1 = re.search(r'<h1[^>]*class=["\'][^"\']*page_title[^"\']*["\'][^>]*>(.*?)</h1>', body, re.S | re.I)
    h1 = re.sub(r'<[^>]+>', ' ', h1.group(1)).strip() if h1 else ''
    cand = [x for x in (ct, h1) if x]
    best = 0.0
    for t in r['claim_titles']:
        for c in cand:
            a, b = norm(c), norm(t)
            s = difflib.SequenceMatcher(None, a, b).ratio()
            if a and b and (a in b or b in a): s = max(s, 0.95)
            best = max(best, s)
    r['citation_title'] = ct[:250]; r['h1_title'] = h1[:250]; r['title_similarity_pass2'] = round(best, 3)
    r['class'] = 'article_title_match' if best >= 0.6 else ('reached_no_article_metadata' if not cand else 'reached_title_mismatch')
    print(f'{i}: {r["class"]} sim={best:.2f} | {ct[:60]} | {(r["claim_titles"] or [""])[0][:60]}', file=sys.stderr)
    time.sleep(1.5)
json.dump(res, open(B + '/deref_results.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('pass2 done', file=sys.stderr)
