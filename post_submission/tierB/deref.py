import json, sys, re, time, urllib.request, urllib.robotparser, urllib.parse, html, difflib, unicodedata, ssl
B = sys.argv[1]
UA = 'vi-medrag-audit-tierB/1.0 (+research; contact: reviewer)'
ctx = ssl.create_default_context()
ISSUE = re.compile(r'/issue/(view|archive)/')
def norm(s):
    s = unicodedata.normalize('NFC', s or '').lower()
    s = re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', s)).strip()
    return s
robots = {}
def allowed(url):
    p = urllib.parse.urlparse(url); base = f'{p.scheme}://{p.netloc}'
    if base not in robots:
        rp = urllib.robotparser.RobotFileParser(); rp.set_url(base + '/robots.txt')
        try: rp.read(); robots[base] = rp
        except Exception: robots[base] = None
    rp = robots[base]
    return True if rp is None else rp.can_fetch(UA, url)
def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'vi,en'})
    try:
        with urllib.request.urlopen(req, timeout=25, context=ctx) as resp:
            body = resp.read(400000).decode('utf-8', 'ignore')
            m = re.search(r'<title[^>]*>(.*?)</title>', body, re.S | re.I)
            title = html.unescape(m.group(1)).strip() if m else ''
            return resp.status, resp.geturl(), title, len(body)
    except urllib.error.HTTPError as e:
        return e.code, e.geturl() if hasattr(e, 'geturl') else url, '', 0
    except Exception as e:
        return -1, url, type(e).__name__, 0
# collect distinct URLs with the claim titles that cite them
claims = json.load(open(B + '/key_claims.json', encoding='utf-8'))
urls = {}
for c in claims:
    if c.get('kind') != 'real' or not c.get('source_url'): continue
    u = c['source_url']; urls.setdefault(u, {'arms': set(), 'titles': set(), 'n_claims': 0, 'n_returned': 0})
    urls[u]['arms'].add(c['arm']); urls[u]['titles'].add(c.get('title') or ''); urls[u]['n_claims'] += 1
    urls[u]['n_returned'] += (c['status'] == 'returned')
print('distinct URLs', len(urls), file=sys.stderr)
out = []
for i, (u, info) in enumerate(sorted(urls.items())):
    rec = {'url': u, 'arms': sorted(info['arms']), 'n_claims': info['n_claims'], 'n_returned': info['n_returned'], 'claim_titles': sorted(t for t in info['titles'] if t)}
    if not allowed(u):
        rec.update(status='robots_refused'); out.append(rec); continue
    st, final, title, size = fetch(u)
    best = max((difflib.SequenceMatcher(None, norm(title), norm(t)).ratio() for t in info['titles'] if t), default=0.0)
    rec.update(http_status=st, final_url=final, page_title=title[:200], title_similarity=round(best, 3), redirected=(final != u),
               final_is_issue_pattern=bool(ISSUE.search(final)), stored_is_issue_pattern=bool(ISSUE.search(u)))
    if st == -1: cls = 'error'
    elif st >= 400: cls = 'fail_' + str(st)
    elif rec['final_is_issue_pattern']: cls = 'issue_index'
    elif best >= 0.6: cls = 'article_title_match'
    else: cls = 'reached_title_mismatch'
    rec['class'] = cls; out.append(rec)
    print(f'{i+1}/{len(urls)} {cls} {st} sim={best:.2f} {u[:80]}', file=sys.stderr)
    time.sleep(1.5)
json.dump(out, open(B + '/deref_results.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('done', len(out), file=sys.stderr)
