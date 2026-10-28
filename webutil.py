"""Small helpers shared by the pages (1.6)."""
from urllib.parse import urlparse


def safe_next(nxt, fallback):
    """Only follow 'next' / referrer addresses inside the Hub (prevents redirects to other sites)."""
    nxt = (nxt or '').strip()
    if not nxt:
        return fallback
    u = urlparse(nxt)
    if u.scheme or u.netloc:
        if u.scheme in ('http', 'https') and u.hostname in ('127.0.0.1', 'localhost'):
            nxt = u.path + (f'?{u.query}' if u.query else '')
        else:
            return fallback
    if not nxt.startswith('/') or nxt.startswith('//') or '\\' in nxt:
        return fallback
    return nxt
