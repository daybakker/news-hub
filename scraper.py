#!/usr/bin/env python3
"""
AllTrails News Hub – scraper
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SETUP (one-time):
  1. Get a free NewsAPI key at https://newsapi.org → "Get API Key"
  2. Paste it below where it says YOUR_KEY_HERE
  3. Get a free NPS key at https://www.nps.gov/subjects/developer/get-started.htm
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Run:  python3 scraper.py
Cron: 0 7 * * * /usr/bin/python3 "/Users/dana/alert hub/scraper.py" >> /tmp/at-scraper.log 2>&1
"""

import json, re, sys, os, time, ssl
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode

# ── Keys — paste yours here ───────────────────────────────────────────────────
NEWS_API_KEY = '6d079103dd174946af894e6653d91a75'   # newsapi.org  (free, 100 req/day)
NPS_API_KEY  = 'DEMO_KEY'        # developer.nps.gov (optional, raises rate limit)
# ─────────────────────────────────────────────────────────────────────────────

OUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scraped_alerts.json')
CUTOFF   = '2026-04-01'          # Don't pull articles older than this

# macOS Python SSL fix
SSL_CTX = ssl._create_unverified_context()

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/html, */*',
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def fetch(url, timeout=20):
    with urlopen(Request(url, headers=HEADERS), timeout=timeout, context=SSL_CTX) as r:
        return r.read().decode('utf-8', errors='replace')

def fetch_json(url, timeout=20):
    with urlopen(Request(url, headers=HEADERS), timeout=timeout, context=SSL_CTX) as r:
        return json.loads(r.read().decode('utf-8'))

def log(msg): print(f'  {msg}', flush=True)
def strip_tags(s): return re.sub(r'<[^>]+>', ' ', s or '').strip()


# ── Region / state detection from article text ───────────────────────────────

US_STATES = [
    'Alabama','Alaska','Arizona','Arkansas','California','Colorado','Connecticut',
    'Delaware','Florida','Georgia','Hawaii','Idaho','Illinois','Indiana','Iowa',
    'Kansas','Kentucky','Louisiana','Maine','Maryland','Massachusetts','Michigan',
    'Minnesota','Mississippi','Missouri','Montana','Nebraska','Nevada',
    'New Hampshire','New Jersey','New Mexico','New York','North Carolina',
    'North Dakota','Ohio','Oklahoma','Oregon','Pennsylvania','Rhode Island',
    'South Carolina','South Dakota','Tennessee','Texas','Utah','Vermont',
    'Virginia','Washington','West Virginia','Wisconsin','Wyoming',
]

REGION_MAP = [
    # US regions
    ({'California','Oregon','Washington','Nevada','Arizona','Utah','Colorado',
      'Idaho','Montana','Wyoming','Alaska','Hawaii','New Mexico'},            'West'),
    ({'North Dakota','South Dakota','Nebraska','Kansas','Minnesota','Iowa',
      'Missouri','Wisconsin','Michigan','Illinois','Indiana','Ohio'},         'North'),
    ({'New York','Pennsylvania','New Jersey','Connecticut','Massachusetts',
      'Rhode Island','Vermont','New Hampshire','Maine','Maryland','Virginia',
      'West Virginia','Delaware'},                                            'East'),
    ({'Texas','Florida','Georgia','Alabama','Mississippi','Louisiana',
      'Arkansas','Tennessee','North Carolina','South Carolina','Oklahoma',
      'Kentucky'},                                                            'South'),
    # INTL 3
    ({'Canada','British Columbia','Ontario','Alberta','Quebec','Manitoba',
      'Saskatchewan','Nova Scotia','New Brunswick'},                          'INTL 3'),
    ({'Australia','New South Wales','Victoria','Queensland','Western Australia',
      'Tasmania','South Australia'},                                          'INTL 3'),
    ({'New Zealand','England','Scotland','Wales','Ireland','United Kingdom',
      'Northern Ireland'},                                                    'INTL 3'),
    # INTL 1
    ({'Japan','China','South Korea','India','Thailand','Vietnam','Indonesia',
      'Philippines','Malaysia','Singapore','Taiwan'},                         'INTL 1'),
    ({'Brazil','Argentina','Chile','Peru','Colombia','Ecuador','Bolivia',
      'Venezuela','Uruguay','Paraguay'},                                      'INTL 1'),
    ({'France','Spain','Portugal','Mexico'},                                  'INTL 1'),
    # INTL 2
    ({'Germany','Austria','Italy','Netherlands','Belgium','Luxembourg',
      'Poland','Czech Republic','Hungary','Romania','Bulgaria','Greece',
      'Norway','Sweden','Finland','Denmark','Iceland','Switzerland',
      'Slovakia','Slovenia','Croatia','Serbia'},                              'INTL 2'),
]

def detect_state(text):
    for s in US_STATES:
        if re.search(r'\b' + re.escape(s) + r'\b', text or '', re.I):
            return s
    return ''

def detect_region(text):
    t = text or ''
    for keywords, region in REGION_MAP:
        for kw in keywords:
            if re.search(r'\b' + re.escape(kw) + r'\b', t, re.I):
                return region
    return ''


# ── 1. NewsAPI.org ────────────────────────────────────────────────────────────
# Searches thousands of news outlets worldwide for trail/park closure keywords.
# Free tier: 100 requests/day, articles from the past month.

NEWS_QUERIES = [
    # English – worldwide
    ('trail closed',           ''),
    ('trail open',             ''),
    # English – AU/NZ use "track" instead of "trail"
    ('track closed',           'en'),
    ('track open',             'en'),
    # French – Canada, France, Belgium, Switzerland
    ('sentier fermé',          'fr'),
    ('sentier ouvert',         'fr'),
    # Spanish – Spain, Mexico, Latin America
    ('sendero cerrado',        'es'),
    ('sendero abierto',        'es'),
    # German – Germany, Austria, Switzerland
    ('Wanderweg gesperrt',     'de'),
    # Portuguese – Brazil, Portugal
    ('trilha fechada',         'pt'),
    # Italian
    ('sentiero chiuso',        'it'),
    # Dutch – Netherlands, Belgium
    ('wandelpad gesloten',     'nl'),
    # Norwegian
    ('sti stengt',             'no'),
    # Swedish
    ('led stängd',             'sv'),
]

def fetch_newsapi():
    if NEWS_API_KEY == 'YOUR_KEY_HERE':
        log('NewsAPI: ⚠ No key set — get one free at newsapi.org and paste into scraper.py')
        return []

    log('NewsAPI.org…')
    items = []
    seen  = set()

    for i, (query, lang) in enumerate(NEWS_QUERIES):
        params = {'q': query, 'from': CUTOFF, 'sortBy': 'publishedAt',
                  'pageSize': 100, 'apiKey': NEWS_API_KEY}
        if lang:
            params['language'] = lang
        url = 'https://newsapi.org/v2/everything?' + urlencode(params)

        try:
            data = fetch_json(url)
        except Exception as e:
            log(f'  ✗ query {i+1}: {e}')
            time.sleep(0.5)
            continue

        if data.get('status') != 'ok':
            log(f'  ✗ query {i+1}: {data.get("message", "error")}')
            time.sleep(0.5)
            continue

        added = 0
        for a in data.get('articles', []):
            link  = (a.get('url') or '').strip()
            title = (a.get('title') or '').strip()
            desc  = (a.get('description') or '').strip()
            if not title or title == '[Removed]' or link in seen:
                continue
            seen.add(link)
            combined = f'{title} {desc}'
            items.append({
                'id':      f"news-{abs(hash(link))}",
                'title':   title,
                'content': desc,
                'url':     link,
                'date':    a.get('publishedAt', ''),
                'source':  a.get('source', {}).get('name', 'News'),
                'state':   detect_state(combined),
                'region':  detect_region(combined),
                'keyword': 'Scraped',
            })
            added += 1

        log(f'  Query {i+1}/{len(NEWS_QUERIES)} ("{query[:40]}…"): {added} items')
        time.sleep(0.3)   # stay well under rate limit

    log(f'NewsAPI total: {len(items)} unique items')
    return items


# ── 2. NPS Alerts API ────────────────────────────────────────────────────────
# Structured closure / danger alerts for all US national parks.

def scrape_nps_api():
    log('NPS Alerts API…')
    items, start = [], 0
    KEEP = {'Closure', 'Danger', 'Caution'}

    while True:
        url = (f'https://developer.nps.gov/api/v1/alerts'
               f'?api_key={NPS_API_KEY}&limit=100&start={start}')
        try:
            data = fetch_json(url)
        except Exception as e:
            log(f'  ✗ NPS API: {e}')
            break

        batch = data.get('data', [])
        total = int(data.get('total', 0))

        for a in batch:
            if a.get('category', '') not in KEEP:
                continue
            title = (a.get('title') or '').strip()
            if not title:
                continue
            park = a.get('parkCode', '').upper()
            items.append({
                'id':      f"nps-api-{a.get('id', '')}",
                'title':   title,
                'content': (a.get('description') or '').strip(),
                'url':     (a.get('url') or '').strip(),
                'date':    (a.get('lastIndexedDate') or '').strip(),
                'source':  f'NPS ({park})',
                'state':   '',
                'region':  '',
                'keyword': 'Scraped',
            })

        start += len(batch)
        if start >= total or not batch:
            break

    log(f'NPS API: {len(items)} alerts')
    return items


# ── 3. InciWeb RSS ────────────────────────────────────────────────────────────
# Active wildfire / emergency incidents from the US interagency system.

ATOM_NS = 'http://www.w3.org/2005/Atom'

def fetch_inciweb():
    log('InciWeb RSS…')
    url = 'https://inciweb.nwcg.gov/feeds/rss/incidents/'
    try:
        raw  = fetch(url)
        root = ET.fromstring(raw.encode('utf-8', errors='replace'))
    except Exception as e:
        log(f'  ✗ InciWeb: {e}')
        return []

    items = []
    for item in root.iter('item'):
        title   = strip_tags(item.findtext('title') or '')
        link    = (item.findtext('link') or '').strip()
        desc    = strip_tags(item.findtext('description') or '')
        pubdate = (item.findtext('pubDate') or '').strip()
        if not title:
            continue
        combined = f'{title} {desc}'
        items.append({
            'id':      f"inciweb-{abs(hash(link or title))}",
            'title':   title,
            'content': desc[:400],
            'url':     link,
            'date':    pubdate,
            'source':  'InciWeb',
            'state':   detect_state(combined),
            'region':  detect_region(combined),
            'keyword': 'Scraped',
        })

    log(f'InciWeb: {len(items)} incidents')
    return items


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f'\n  AllTrails News Hub – Scraper')
    print(f'  {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')

    items = []
    items.extend(scrape_nps_api());  time.sleep(0.5)
    items.extend(fetch_inciweb());   time.sleep(0.5)
    items.extend(fetch_newsapi())

    # Deduplicate
    seen, deduped = set(), []
    for it in items:
        if it['id'] not in seen:
            seen.add(it['id'])
            deduped.append(it)

    out = {
        'updated': datetime.now(timezone.utc).isoformat(),
        'count':   len(deduped),
        'items':   deduped,
    }
    with open(OUT_FILE, 'w') as f:
        json.dump(out, f, indent=2)

    print(f'\n  Done — {len(deduped)} items → {os.path.basename(OUT_FILE)}\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
