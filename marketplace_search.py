"""Reusable Craigslist/Facebook search launcher. No listing scraper or background scan.

Examples:
  python marketplace_search.py --query 'Rolex Submarine' --region sfbay --postal 94103 --radius 50
  python marketplace_search.py --query 'Rolex Submariner' --region sfbay --serve --port 8082
"""
from __future__ import annotations
import argparse
import json
import secrets
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REGIONS = {
    'www':'Choose location on Craigslist', 'sfbay':'San Francisco Bay Area',
    'losangeles':'Los Angeles', 'sandiego':'San Diego', 'sacramento':'Sacramento',
    'seattle':'Seattle', 'portland':'Portland', 'lasvegas':'Las Vegas',
    'phoenix':'Phoenix', 'denver':'Denver', 'dallas':'Dallas', 'houston':'Houston',
    'austin':'Austin', 'chicago':'Chicago', 'newyork':'New York City',
    'boston':'Boston', 'washingtondc':'Washington DC', 'miami':'Miami', 'atlanta':'Atlanta',
}
ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / 'marketplace-search'


def profile(data):
    query = str(data.get('query') or 'Rolex Submariner').strip()
    query = ' '.join(query.split())
    if not 2 <= len(query) <= 160:
        raise ValueError('Enter a search between 2 and 160 characters.')
    corrected = query.lower() == 'rolex submarine'
    if corrected:
        query = 'Rolex Submariner'
    region = str(data.get('region') or 'www')
    if region not in REGIONS:
        raise ValueError('Choose one of the supported Craigslist regions.')
    postal = str(data.get('postal') or '').strip()
    if postal and (len(postal) != 5 or not postal.isascii() or not postal.isdigit()):
        raise ValueError('Enter a five-digit US ZIP code, or leave it blank.')
    try:
        radius_value = data.get('radius', 50)
        radius_text = str(50 if radius_value in (None, '') else radius_value)
        if not radius_text.isascii() or not radius_text.isdigit():
            raise ValueError('Radius must be a whole number.')
        radius = int(radius_text)
    except (TypeError, ValueError) as exc:
        raise ValueError('Radius must be a whole number.') from exc
    if not 1 <= radius <= 500:
        raise ValueError('Radius must be between 1 and 500 miles.')
    minimum, maximum = str(data.get('min_price') or '').strip(), str(data.get('max_price') or '').strip()
    for price in (minimum, maximum):
        if price and (not price.isascii() or not price.isdigit() or int(price) > 100_000_000):
            raise ValueError('Prices must be positive whole dollar amounts.')
    if minimum and maximum and int(minimum) > int(maximum):
        raise ValueError('Minimum price must not exceed maximum price.')
    fb_url = str(data.get('facebook_url') or '').strip()
    if fb_url:
        parsed = urlsplit(fb_url)
        if parsed.scheme != 'https' or parsed.netloc not in {'www.facebook.com','facebook.com'} or not parsed.path.startswith('/marketplace/') or not parsed.path.rstrip('/').endswith('/search'):
            raise ValueError('Paste an HTTPS Facebook Marketplace search URL, not a profile or login link.')
    return {'query':query, 'region':region, 'postal':postal, 'radius':radius,
            'min_price':minimum, 'max_price':maximum, 'facebook_url':fb_url, 'corrected':corrected}


def search_plan(data):
    item = profile(data)
    params = {'query':item['query'], 'sort':'date'}
    if item['postal']:
        params.update({'postal':item['postal'], 'search_distance':item['radius']})
    if item['min_price']:
        params['min_price'] = item['min_price']
    if item['max_price']:
        params['max_price'] = item['max_price']
    craigslist = 'https://' + item['region'] + '.craigslist.org/search/sss?' + urlencode(params)
    parsed = urlsplit(item['facebook_url'] or 'https://www.facebook.com/marketplace/search/')
    # Preserve location filters from a search the user explicitly supplied.
    # Never carry authentication tokens or arbitrary query parameters forward.
    allowed = {'latitude','longitude','radius','deliveryMethod','sortBy','minPrice','maxPrice','exact'}
    fb_params = {k:v for k,v in parse_qsl(parsed.query) if k in allowed}
    fb_params['query'] = item['query']
    facebook = urlunsplit(('https','www.facebook.com',parsed.path,urlencode(fb_params),''))
    terms = item['query'] + (' ' + REGIONS[item['region']] if item['region'] != 'www' else '')
    return {'profile':item, 'created_at':datetime.now(timezone.utc).isoformat(), 'mode':'search_launcher',
            'sources':[{'name':'Craigslist','url':craigslist,'status':'ready_to_open','filters':('ZIP and radius supplied' if item['postal'] else 'Region only; no distance filter')},
                       {'name':'Facebook Marketplace','url':facebook,'status':'ready_to_open','filters':('Saved Facebook URL filters retained; verify on Facebook' if item['facebook_url'] else 'Uses your Facebook location; verify radius on Facebook')}],
            'indexed_searches':[{'name':name,'url':'https://www.google.com/search?' + urlencode({'q':f'site:{domain} {terms}'})} for name,domain in [('Craigslist public index','craigslist.org'),('Facebook public index','facebook.com/marketplace/item/')]],
            'notice':'Opening searches is not a completed scan. This program does not read listings, refresh marketplace pages, or bypass sign-in.'}


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True


def serve(data, port=8082):
    token = secrets.token_urlsafe(32)
    default = profile(data)
    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, value, content_type='application/json'):
            body = json.dumps(value).encode() if content_type == 'application/json' else value
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def valid_host(self):
            return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
        def do_GET(self):
            if not self.valid_host():
                return self.reply(403, {'error':'Local access only'})
            path = urlsplit(self.path).path
            if path == '/api/config':
                return self.reply(200, {'default':default,'regions':REGIONS,'launch_token':token})
            files = {'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8')}
            if path not in files:
                return self.reply(404, {'error':'Not found'})
            filename, mime = files[path]
            return self.reply(200, (ASSETS / filename).read_bytes(), mime)
        def do_POST(self):
            expected = f'http://{self.headers.get("Host", "")}'
            if not self.valid_host() or self.headers.get('Origin') != expected or not secrets.compare_digest(self.headers.get('X-LockX-Launch-Token',''),token):
                return self.reply(403, {'error':'Open the local workbench to run searches.'})
            if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                return self.reply(415, {'error':'Use JSON.'})
            try:
                length = int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 8192:
                    return self.reply(413, {'error':'Request too large or empty.'})
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload,dict):
                    raise ValueError('Invalid search settings.')
                plan = search_plan(payload)
            except (ValueError, TypeError) as exc:
                return self.reply(422, {'error':str(exc)})
            path = urlsplit(self.path).path
            if path not in {'/api/plan','/api/open'}:
                return self.reply(404, {'error':'Not found'})
            if path == '/api/open':
                results = []
                for source in plan['sources']:
                    try:
                        accepted = webbrowser.open_new_tab(source['url'])
                        results.append({'name':source['name'],'status':'sent_to_browser' if accepted else 'open_manually'})
                    except (webbrowser.Error, OSError):
                        results.append({'name':source['name'],'status':'open_manually'})
                plan['launch_results'] = results
            return self.reply(200, plan)
        def log_message(self, format, *args):
            pass
    server = LocalServer(('127.0.0.1', port), Handler)
    print(f'LockX marketplace search: http://127.0.0.1:{server.server_port}/',flush=True)
    print('Local launcher only. Search results remain on the marketplaces.',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--query', default='Rolex Submariner')
    parser.add_argument('--region', choices=REGIONS, default='www')
    parser.add_argument('--postal', default='')
    parser.add_argument('--radius', type=int, default=50)
    parser.add_argument('--min-price', default='')
    parser.add_argument('--max-price', default='')
    parser.add_argument('--facebook-url', default='')
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--port', type=int, default=8082)
    parser.add_argument('--open', action='store_true', help='Ask the default browser to open both searches once.')
    args = parser.parse_args()
    try:
        plan = search_plan(vars(args))
    except ValueError as exc:
        parser.error(str(exc))
    if args.serve:
        serve(vars(args), args.port)
    else:
        print(json.dumps(plan, indent=2))
        if args.open:
            for source in plan['sources']:
                webbrowser.open_new_tab(source['url'])


if __name__ == '__main__':
    main()
