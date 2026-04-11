"""
Route crawler for bowling-league-tracker.

Uses the Flask test client to BFS-crawl all reachable GET routes,
parsing every <a href> and <form action> (GET forms) from each page.
Reports non-200 responses and Jinja/server errors.

Usage:
    python3 crawl_routes.py [--verbose]
"""

import sys, re
from collections import deque
from urllib.parse import urlparse, urljoin, urlunparse
from bs4 import BeautifulSoup

VERBOSE = '--verbose' in sys.argv

# Paths to skip (destructive, auth-triggering, or binary downloads)
SKIP_PATTERNS = [
    re.compile(p) for p in [
        r'^/admin/.*/(toggle_active|send_magic_links)',  # POSTs only
        r'^/logout',
        r'^/auth/',
        r'^/static/',
        r'/download',
        r'/export',
        r'/backup',
    ]
]


def should_skip(path):
    return any(p.search(path) for p in SKIP_PATTERNS)


def normalize(url, base='/'):
    """Return the path+query string for an internal URL, or None if external."""
    if not url or url.startswith(('mailto:', 'javascript:', '#')):
        return None
    parsed = urlparse(url)
    # External host → skip
    if parsed.netloc and parsed.netloc not in ('localhost', '127.0.0.1', ''):
        return None
    # Rebuild as path?query (drop fragment)
    path = parsed.path or '/'
    qs   = ('?' + parsed.query) if parsed.query else ''
    return path + qs


def crawl():
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from app import create_app

    app = create_app()
    client = app.test_client()

    # Log in as the first editor bowler so auth passes everywhere.
    with app.app_context():
        from models import Bowler
        editor = Bowler.query.filter_by(is_editor=True).first()
        if not editor:
            print('ERROR: no editor bowler found in DB — cannot authenticate test client.')
            sys.exit(1)
        editor_id = editor.id
        print(f'Authenticating as editor: {editor.last_name}, {editor.first_name} (id={editor_id})\n')

    # Inject a flask-login session so all requests appear authenticated as that editor.
    with client.session_transaction() as sess:
        sess['_user_id'] = str(editor_id)
        sess['_fresh']   = True

    visited = set()
    queue   = deque(['/'])
    results = {'ok': [], 'error': [], 'skip': []}

    def enqueue(url):
        norm = normalize(url)
        if norm and norm not in visited and not should_skip(norm):
            visited.add(norm)
            queue.append(norm)

    enqueue('/')

    while queue:
        path = queue.popleft()

        if VERBOSE:
            print(f'  GET {path}')

        try:
            resp = client.get(path, follow_redirects=True)
        except Exception as exc:
            results['error'].append((path, f'EXCEPTION: {exc}'))
            continue

        status = resp.status_code

        if status == 200:
            results['ok'].append(path)
            # Parse links from the response
            try:
                soup = BeautifulSoup(resp.data, 'html.parser')
                for tag in soup.find_all('a', href=True):
                    enqueue(tag['href'])
                # GET forms
                for form in soup.find_all('form'):
                    method = (form.get('method') or 'get').lower()
                    if method == 'get':
                        action = form.get('action') or path
                        enqueue(action)
            except Exception:
                pass  # parsing failure is not a route error

        elif status in (301, 302, 303, 307, 308):
            # follow_redirects=True means this shouldn't happen, but just in case
            location = resp.headers.get('Location', '')
            results['ok'].append(f'{path} → {location}')
            enqueue(location)

        elif status == 404:
            results['error'].append((path, '404 Not Found'))

        elif status == 500:
            # Try to extract the error message from the HTML
            try:
                soup = BeautifulSoup(resp.data, 'html.parser')
                # Flask debug page has an <h1> with the exception type
                h1 = soup.find('h1')
                pre = soup.find('pre')
                msg = (h1.get_text(strip=True) if h1 else '') + \
                      (' — ' + pre.get_text(strip=True)[:200] if pre else '')
            except Exception:
                msg = resp.data[:300].decode('utf-8', errors='replace')
            results['error'].append((path, f'500: {msg}'))

        else:
            results['error'].append((path, f'HTTP {status}'))

    return results


def main():
    print('Crawling routes...\n')
    results = crawl()

    print(f'Pages crawled OK : {len(results["ok"])}')
    print(f'Errors           : {len(results["error"])}')

    if results['error']:
        print('\n── ERRORS ──────────────────────────────────────────────')
        for path, msg in results['error']:
            print(f'  {path}')
            print(f'    {msg}')
    else:
        print('\nAll reachable routes returned 200.')

    if VERBOSE and results['ok']:
        print('\n── OK ──────────────────────────────────────────────────')
        for p in sorted(results['ok']):
            print(f'  {p}')


if __name__ == '__main__':
    main()
