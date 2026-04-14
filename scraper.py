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
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.request import Request, urlopen
from urllib.parse import urlencode

# ── Keys — paste yours here ───────────────────────────────────────────────────
NEWS_API_KEY = '6d079103dd174946af894e6653d91a75'   # newsapi.org  (free, 100 req/day)
NPS_API_KEY  = 'DEMO_KEY'        # developer.nps.gov (optional, raises rate limit)
# ─────────────────────────────────────────────────────────────────────────────

OUT_FILE    = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scraped_alerts.json')
# Rolling 30-day window — keeps data fresh and avoids accumulating stale articles
CUTOFF_DT   = datetime.now(timezone.utc) - timedelta(days=30)
CUTOFF      = CUTOFF_DT.strftime('%Y-%m-%d')   # ISO date string for NewsAPI 'from' param

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
ATOM_ENTRY = f'{{{ATOM_NS}}}entry'

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


# ── 4. International RSS feeds ───────────────────────────────────────────────
# Mirrors the FEED_META entries in index.html that have a region set.
# These feeds block browser CORS so they can't be fetched client-side on
# GitHub Pages — scraping them here and saving to scraped_alerts.json is the
# only way they show up in the hosted version.

INTL_FEEDS = [
    # INTL 3 — park agency feeds (AU, NZ, UK)
    ('https://www.nationalparks.nsw.gov.au/api/rssfeed/get',
     'INTL 3', 'NSW National Parks'),
    ('http://www.doc.govt.nz/news/rss-feed-to-govtnz/',
     'INTL 3', 'NZ Dept. of Conservation'),
    ('https://www.peakdistrict.gov.uk/learning-about/news/news-rss',
     'INTL 3', 'Peak District National Park'),
    *[(f'https://parks.qld.gov.au/xml/rss/parkalerts-{r}.xml',
       'INTL 3',
       f'Queensland Parks – {r.replace("-", " ").title()}')
      for r in [
          'brisbane', 'bundaberg', 'capricorn', 'fraser-coast', 'gladstone',
          'gold-coast', 'mackay', 'outback-queensland',
          'southern-queensland-country', 'sunshine-coast',
          'townsville', 'tropical-north-queensland', 'whitsundays',
      ]],
    # INTL 1 — Google News RSS (pre-filtered by query, language-specific)
    ('https://news.google.com/rss/search?q=sentier+ferm%C3%A9&hl=fr&gl=FR&ceid=FR:fr',
     'INTL 1', 'Google News – France (sentier fermé)'),
    ('https://news.google.com/rss/search?q=sendero+cerrado&hl=es&gl=ES&ceid=ES:es',
     'INTL 1', 'Google News – Spain (sendero cerrado)'),
    ('https://news.google.com/rss/search?q=sendero+cerrado&hl=es&gl=AR&ceid=AR:es',
     'INTL 1', 'Google News – Latin America (sendero cerrado)'),
    ('https://news.google.com/rss/search?q=trilha+fechada&hl=pt-BR&gl=BR&ceid=BR:pt-419',
     'INTL 1', 'Google News – Brazil (trilha fechada)'),
    ('https://news.google.com/rss/search?q=%E7%99%BB%E5%B1%B1%E9%81%93+%E9%80%9A%E8%A1%8C%E6%AD%A2%E3%82%81&hl=ja&gl=JP&ceid=JP:ja',
     'INTL 1', 'Google News – Japan (登山道 通行止め)'),
    ('https://news.google.com/rss/search?q=%EB%93%B1%EC%82%B0%EB%A1%9C+%ED%86%B5%EC%A0%9C&hl=ko&gl=KR&ceid=KR:ko',
     'INTL 1', 'Google News – Korea (등산로 통제)'),
    # INTL 2 — Google News RSS (pre-filtered by query, language-specific)
    ('https://news.google.com/rss/search?q=Wanderweg+gesperrt&hl=de&gl=DE&ceid=DE:de',
     'INTL 2', 'Google News – Germany (Wanderweg gesperrt)'),
    ('https://news.google.com/rss/search?q=sentiero+chiuso&hl=it&gl=IT&ceid=IT:it',
     'INTL 2', 'Google News – Italy (sentiero chiuso)'),
    ('https://news.google.com/rss/search?q=wandelpad+gesloten&hl=nl&gl=NL&ceid=NL:nl',
     'INTL 2', 'Google News – Netherlands (wandelpad gesloten)'),
    ('https://news.google.com/rss/search?q=sti+stengt&hl=no&gl=NO&ceid=NO:no',
     'INTL 2', 'Google News – Norway (sti stengt)'),
    ('https://news.google.com/rss/search?q=vandringsled+st%C3%A4ngd&hl=sv&gl=SE&ceid=SE:sv',
     'INTL 2', 'Google News – Sweden (vandringsled stängd)'),
]


def _parse_feed_xml(root):
    """Return list of (title, link, desc, pubdate) from RSS or Atom XML."""
    entries = []

    # RSS 2.0 — <item> elements
    for item in root.iter('item'):
        title   = strip_tags(item.findtext('title') or '')
        link    = (item.findtext('link') or '').strip()
        desc    = strip_tags(item.findtext('description') or '')
        pubdate = (item.findtext('pubDate') or '').strip()
        if title:
            entries.append((title, link, desc, pubdate))

    # Atom — <entry> elements (fallback if no <item> found)
    if not entries:
        for entry in root.iter(ATOM_ENTRY):
            title   = strip_tags(entry.findtext(f'{{{ATOM_NS}}}title') or
                                 entry.findtext('title') or '')
            link_el = entry.find(f'{{{ATOM_NS}}}link')
            link    = (link_el.get('href', '') if link_el is not None
                       else (entry.findtext('link') or '')).strip()
            desc    = strip_tags(entry.findtext(f'{{{ATOM_NS}}}summary') or
                                 entry.findtext(f'{{{ATOM_NS}}}content') or '')
            pubdate = (entry.findtext(f'{{{ATOM_NS}}}updated') or
                       entry.findtext(f'{{{ATOM_NS}}}published') or '').strip()
            if title:
                entries.append((title, link, desc, pubdate))

    return entries


def fetch_intl_feeds():
    log('International RSS feeds…')
    all_items = []

    for url, region, source_name in INTL_FEEDS:
        try:
            raw  = fetch(url)
            root = ET.fromstring(raw.encode('utf-8', errors='replace'))
        except Exception as e:
            log(f'  ✗ {source_name}: {e}')
            time.sleep(0.3)
            continue

        entries = _parse_feed_xml(root)
        batch = []
        for title, link, desc, pubdate in entries:
            # Drop articles older than the rolling 30-day window
            if pubdate:
                try:
                    dt = parsedate_to_datetime(pubdate)
                except Exception:
                    try:
                        dt = datetime.fromisoformat(pubdate.replace('Z', '+00:00'))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                    except Exception:
                        dt = None
                if dt and dt < CUTOFF_DT:
                    continue

            batch.append({
                'id':      f"intl-{abs(hash(link or title))}",
                'title':   title,
                'content': desc[:400],
                'url':     link,
                'date':    pubdate,
                'source':  source_name,
                'state':   '',
                'region':  region,
                'keyword': 'Scraped',
            })

        log(f'  {source_name}: {len(batch)} items')
        all_items.extend(batch)
        time.sleep(0.3)

    log(f'International feeds total: {len(all_items)} items')
    return all_items


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f'\n  AllTrails News Hub – Scraper')
    print(f'  {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')

    items = []
    items.extend(scrape_nps_api());   time.sleep(0.5)
    items.extend(fetch_inciweb());    time.sleep(0.5)
    items.extend(fetch_intl_feeds()); time.sleep(0.5)
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
