"""
Route crawler for bowling-league-tracker.

Uses the Flask test client to BFS-crawl all reachable GET routes as both
an editor and a viewer, checking:

  Editor pass  — every reachable page must return 200.
  Viewer pass  — pages in the ViewerPermission ALLOW list must return 200;
                 all other pages must return 403 (not 200 = security leak,
                 not 500 = server bug).

Usage:
    python3 crawl_routes.py [--verbose]
"""

import sys, re
from collections import deque
from urllib.parse import urlparse
from bs4 import BeautifulSoup

VERBOSE = '--verbose' in sys.argv

# Paths to skip entirely (destructive, auth-only, or binary)
SKIP_PATTERNS = [
    re.compile(p) for p in [
        r'^/admin/.*/(toggle_active|send_magic_links)',
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


def normalize(url):
    """Return path+query for an internal URL, or None if external/skippable."""
    if not url or url.startswith(('mailto:', 'javascript:', '#')):
        return None
    parsed = urlparse(url)
    if parsed.netloc and parsed.netloc not in ('localhost', '127.0.0.1', ''):
        return None
    path = parsed.path or '/'
    qs   = ('?' + parsed.query) if parsed.query else ''
    return path + qs


def extract_links(html, current_path):
    """Return all internal hrefs from an HTML page."""
    links = set()
    try:
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup.find_all('a', href=True):
            n = normalize(tag['href'])
            if n:
                links.add(n)
        for form in soup.find_all('form'):
            if (form.get('method') or 'get').lower() == 'get':
                n = normalize(form.get('action') or current_path)
                if n:
                    links.add(n)
    except Exception:
        pass
    return links


def get_endpoint(app, path):
    """Resolve a URL path to its Flask endpoint name, or None."""
    try:
        # Strip query string for matching
        pure_path = path.split('?')[0]
        with app.test_request_context(pure_path):
            from flask import request as r
            adapter = app.url_map.bind('')
            endpoint, _ = adapter.match(pure_path)
            return endpoint
    except Exception:
        return None


def make_client(app, bowler_id):
    """Return a test client pre-authenticated as bowler_id."""
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(bowler_id)
        sess['_fresh']   = True
    return client


# ── Editor crawl ──────────────────────────────────────────────────────────────

def crawl_as_editor(app, editor_id):
    """BFS crawl as editor. Returns (all_urls, errors) where all_urls is the
    complete set of internal paths discovered."""
    client = make_client(app, editor_id)
    visited, queue = set(), deque(['/'])
    visited.add('/')
    errors = []
    all_urls = set()

    while queue:
        path = queue.popleft()
        if should_skip(path):
            continue
        if VERBOSE:
            print(f'  [editor] GET {path}')
        try:
            resp = client.get(path, follow_redirects=True)
        except Exception as exc:
            errors.append((path, f'EXCEPTION: {exc}'))
            continue

        status = resp.status_code
        if status == 200:
            all_urls.add(path)
            for link in extract_links(resp.data, path):
                if link not in visited and not should_skip(link):
                    visited.add(link)
                    queue.append(link)
        elif status == 500:
            msg = _extract_500(resp)
            errors.append((path, f'500: {msg}'))
        elif status == 404:
            errors.append((path, '404 Not Found'))
        else:
            errors.append((path, f'HTTP {status}'))

    return all_urls, errors


# ── Viewer crawl ──────────────────────────────────────────────────────────────

def crawl_as_viewer(app, viewer_id, all_urls, allowed_endpoints):
    """
    Test every URL discovered by the editor crawl as a viewer.
    Returns dict with lists: security_leaks, broken_allowed, server_errors.
    """
    client = make_client(app, viewer_id)
    results = {'security_leaks': [], 'broken_allowed': [], 'server_errors': [], 'ok': []}

    for path in sorted(all_urls):
        if should_skip(path):
            continue
        endpoint = get_endpoint(app, path)
        viewer_should_see = endpoint in allowed_endpoints

        if VERBOSE:
            flag = 'ALLOW' if viewer_should_see else 'DENY '
            print(f'  [viewer/{flag}] GET {path}  ({endpoint})')

        try:
            resp = client.get(path, follow_redirects=True)
        except Exception as exc:
            results['server_errors'].append((path, f'EXCEPTION: {exc}'))
            continue

        status = resp.status_code

        if status == 500:
            results['server_errors'].append((path, _extract_500(resp)))
        elif status == 200 and not viewer_should_see:
            results['security_leaks'].append((path, endpoint or '?'))
        elif status == 403 and viewer_should_see:
            results['broken_allowed'].append((path, endpoint or '?'))
        elif status == 200 and viewer_should_see:
            results['ok'].append(path)
        # 403 on a denied endpoint = correct, ignore
        # other statuses on denied = also fine (404 etc)

    return results


def _extract_500(resp):
    try:
        soup = BeautifulSoup(resp.data, 'html.parser')
        h1  = soup.find('h1')
        pre = soup.find('pre')
        return (h1.get_text(strip=True) if h1 else '') + \
               (' — ' + pre.get_text(strip=True)[:200] if pre else '') or \
               resp.data[:200].decode('utf-8', errors='replace')
    except Exception:
        return resp.data[:200].decode('utf-8', errors='replace')


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from app import create_app

    app = create_app()

    with app.app_context():
        from models import Bowler, ViewerPermission

        editor = Bowler.query.filter_by(is_editor=True).first()
        if not editor:
            print('ERROR: no editor bowler in DB.')
            sys.exit(1)

        # Find a non-editor authenticated bowler to use as viewer
        viewer = Bowler.query.filter_by(is_editor=False).first()
        if not viewer:
            print('ERROR: no non-editor bowler in DB.')
            sys.exit(1)

        allowed_endpoints = {
            r.endpoint
            for r in ViewerPermission.query.filter_by(viewer_accessible=True).all()
        }
        # These are always accessible to any authenticated user
        allowed_endpoints.update({'index', 'auth.login', 'auth.logout'})

    print(f'Editor : {editor.last_name}, {editor.first_name} (id={editor.id})')
    print(f'Viewer : {viewer.last_name}, {viewer.first_name} (id={viewer.id})')
    print(f'Viewer-allowed endpoints: {sorted(allowed_endpoints)}\n')

    # ── Editor pass ──
    print('── Editor crawl ────────────────────────────────────────')
    all_urls, editor_errors = crawl_as_editor(app, editor.id)
    print(f'Pages crawled : {len(all_urls)}')
    print(f'Errors        : {len(editor_errors)}')
    if editor_errors:
        for path, msg in editor_errors:
            print(f'  {path}')
            print(f'    {msg}')
    else:
        print('All editor-visible pages returned 200.')

    # ── Viewer pass ──
    print(f'\n── Viewer crawl ({len(all_urls)} URLs) ──────────────────────────')
    vr = crawl_as_viewer(app, viewer.id, all_urls, allowed_endpoints)

    ok_count = len(vr['ok'])
    leak_count = len(vr['security_leaks'])
    broken_count = len(vr['broken_allowed'])
    err_count = len(vr['server_errors'])

    print(f'Allowed pages returned 200 : {ok_count}')
    print(f'Security leaks (200 on denied page) : {leak_count}')
    print(f'Broken viewer access (403 on allowed page) : {broken_count}')
    print(f'Server errors (500) : {err_count}')

    if vr['security_leaks']:
        print('\n⚠ SECURITY LEAKS — viewer got 200 on denied endpoint:')
        for path, ep in vr['security_leaks']:
            print(f'  {path}  [{ep}]')

    if vr['broken_allowed']:
        print('\n✗ BROKEN VIEWER ACCESS — viewer got 403 on allowed endpoint:')
        for path, ep in vr['broken_allowed']:
            print(f'  {path}  [{ep}]')

    if vr['server_errors']:
        print('\n✗ SERVER ERRORS during viewer crawl:')
        for path, msg in vr['server_errors']:
            print(f'  {path}')
            print(f'    {msg}')

    if not any([editor_errors, leak_count, broken_count, err_count]):
        print('\nAll checks passed.')


if __name__ == '__main__':
    main()
