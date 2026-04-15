#!/usr/bin/env python3
"""
AllTrails News Hub – local dev server
Run: python3 server.py
Then open: http://localhost:8000
"""
import os
import ssl
import urllib.request
import urllib.error
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

# macOS Python SSL fix (same as scraper.py)
SSL_CTX = ssl._create_unverified_context()

# Always serve files from the folder that contains this script
os.chdir(os.path.dirname(os.path.abspath(__file__)))

ALLOWED_PREFIXES = (
    'https://www.google.com/alerts/feeds/',
    'https://www.nps.gov/',
    # International park agencies
    'https://www.nationalparks.nsw.gov.au/',   # Australia – NSW
    'https://parks.qld.gov.au/',               # Australia – Queensland
    'http://www.doc.govt.nz/',                 # New Zealand – DOC
    'https://www.doc.govt.nz/',                # New Zealand – DOC (https)
    'https://www.peakdistrict.gov.uk/',        # UK – Peak District
    'https://news.google.com/rss/',            # Google News multilingual RSS
)

class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/feed?'):
            self._proxy()
        elif self.path == '/scraped-alerts':
            self._scraped_alerts()
        else:
            super().do_GET()

    def _scraped_alerts(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scraped_alerts.json')
        if not os.path.exists(path):
            self._json_response(b'{"items":[]}')
            return
        with open(path, 'rb') as f:
            data = f.read()
        self._json_response(data)

    def _json_response(self, data):
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _proxy(self):
        qs  = parse_qs(urlparse(self.path).query)
        url = qs.get('url', [''])[0]

        if not any(url.startswith(p) for p in ALLOWED_PREFIXES):
            try:
                self.send_response(403)
                self.end_headers()
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                              'AppleWebKit/537.36 (KHTML, like Gecko) '
                              'Chrome/124.0.0.0 Safari/537.36',
                'Accept': 'application/atom+xml,application/xml,text/xml,*/*',
            })
            with urllib.request.urlopen(req, timeout=25, context=SSL_CTX) as resp:
                data = resp.read()
            try:
                self.send_response(200)
                self.send_header('Content-Type', 'application/xml; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass
        except urllib.error.HTTPError as e:
            try:
                self.send_response(e.code)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(f'Upstream error: {e.code} {e.reason}'.encode())
            except (BrokenPipeError, ConnectionResetError):
                pass
        except Exception as e:
            try:
                self.send_response(502)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(str(e).encode())
            except (BrokenPipeError, ConnectionResetError):
                pass

    def log_message(self, fmt, *args):
        # Only log feed proxy calls, suppress static file noise
        first = str(args[0]) if args else ''
        if '/feed?' in first:
            print(f'  feed › {args[1]}')


# Threaded server — handles each request in its own thread so 40+ concurrent
# feed fetches don't queue up and trigger the browser's 8-second timeout.
class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


if __name__ == '__main__':
    port = 8000
    server = ThreadedHTTPServer(('localhost', port), Handler)
    print(f'\n  AllTrails News Hub')
    print(f'  → http://localhost:{port}\n')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n  Stopped.')
