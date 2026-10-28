"""1.6 security fixes — SYNTHETIC data only."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import fresh  # noqa: E402

SP = fresh('sec')
import app as A  # noqa: E402
import notify as N  # noqa: E402
from webutil import safe_next  # noqa: E402

assert A.app.config['SESSION_COOKIE_SAMESITE'] == 'Strict'
for bad in ('//evil.example/x', 'https://evil.example/', 'http://127.0.0.1.evil.example/', '/\\evil', 'javascript:alert(1)'):
    assert safe_next(bad, '/home') == '/home', bad
assert safe_next('http://127.0.0.1:5000/accounts?tab=card', '/') == '/accounts?tab=card'
assert safe_next('/transactions', '/') == '/transactions'
A.app.testing = True
c = A.app.test_client()
PW = 'Synthetic pass 42'
r = c.post('/setup', data={'full_name': 'Test Person', 'username': 'tester', 'password': PW, 'password2': PW, 'erase': '1'})
cookie = r.headers.get('Set-Cookie', '')
assert 'SameSite=Strict' in cookie and 'HttpOnly' in cookie
h = c.get(r.headers['Location']).get_data(as_text=True)
import re  # noqa: E402
key = re.search(r'([A-Z0-9]{4}(?:-[A-Z0-9]{4}){3,})', h)
assert key, 'recovery key page'
for ck in c._cookies.values() if hasattr(c, '_cookies') else []:
    assert key.group(1) not in getattr(ck, 'value', ''), 'recovery key must not travel in the cookie'
# SQL in report download parameters is just a value now
r = c.get("/reports/download?start=2000-01-01' OR 1=1 --&end=2099-12-31")
assert r.status_code in (200, 302)
# scope literal with a question mark in a value
import scope as SC  # noqa: E402
with A.app.test_request_context():
    from flask import session
    session['scope'] = {'account': 'Odd? name', 'label': 'x'}
    lit = SC.txn_literal('t')
    assert "'Odd? name'" in lit and lit.count('?') == 1, lit
# recovery attempts are throttled
for _ in range(4):
    ok, msg = A.V.recover('tester', 'WRONG-KEY0-0000-0000', 'New password 123!')
assert 'Too many' in msg
# idle lock without any request
assert A.V.unlocked
A.V.last = time.time() - 31 * 60
N.tick()
assert not A.V.unlocked, 'idle lock should happen in the background'
print('ALL security OK')
