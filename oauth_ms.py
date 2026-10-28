"""Finance Hub 1.8 — "Sign in with Microsoft" for Outlook.com / Hotmail / Live / Microsoft 365 mailboxes.

Microsoft stopped accepting passwords and app passwords for IMAP / SMTP on Outlook.com in September 2024; apps must use
OAuth 2.0. The Hub uses the *device code* sign-in (no web server or redirect needed):
  1. the Hub asks Microsoft for a short code;
  2. you open microsoft.com/devicelogin, type the code and sign in to your Outlook account, and allow access to mail;
  3. the Hub receives a refresh token, keeps it inside your encrypted database, and from then on gets a fresh access token
     (valid about an hour) whenever it reads mail (IMAP, outlook.office365.com) or sends reminders (SMTP, smtp-mail.outlook.com).

It needs an "application (client) ID" — a free, one-time app registration in Microsoft Entra (Azure portal) by the user:
supported account types "any organizational directory and personal Microsoft accounts", "Allow public client flows" = Yes.
Only these delegated permissions are requested: read / write mail over IMAP, send mail over SMTP, and offline access.
"""
import base64
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request

AUTHORITY = 'https://login.microsoftonline.com/{tenant}/oauth2/v2.0'
SCOPES = 'offline_access openid email https://outlook.office.com/IMAP.AccessAsUser.All https://outlook.office.com/SMTP.Send'
IMAP_HOST, IMAP_PORT = 'outlook.office365.com', 993
SMTP_HOST, SMTP_PORT = 'smtp-mail.outlook.com', 587
DEVICE = {}            # pending sign-ins: (Hub user, mailbox id) → device-code response
TOKENS = {}            # sha256(refresh token presented) → (access token, expiry, newest refresh token)
# Only someone holding a refresh token can reach its cached access token: nothing is shared by mailbox address or between Hub users.


class AuthError(Exception):
    pass


def _post(url, data, timeout=20):
    """→ (http status, json). Replaced by the tests."""
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method='POST',
                                 headers={'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or '{}')
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or '{}')
        except ValueError:
            return e.code, {'error': 'http_error', 'error_description': str(e)}


def _call(kind, client_id, tenant, data):
    """POST to /devicecode or /token; switches to the 'consumers' endpoint when the app is for personal accounts only."""
    tenant = tenant or 'common'
    status, j = _post(f"{AUTHORITY.format(tenant=tenant)}/{kind}", dict(data, client_id=client_id))
    if status >= 400 and 'AADSTS9002331' in str(j.get('error_description', '')) and tenant != 'consumers':
        status, j = _post(f"{AUTHORITY.format(tenant='consumers')}/{kind}", dict(data, client_id=client_id))
        j['_tenant'] = 'consumers'
    return status, j


def friendly(j):
    d = str(j.get('error_description') or j.get('error') or j)
    for code, text in (('AADSTS70002', 'in the app registration, turn on “Allow public client flows” (Authentication › Advanced settings)'),
                       ('AADSTS700016', 'the application (client) ID was not found — copy it again from the app registration'),
                       ('AADSTS50020', 'this account cannot sign in to that app registration — set its supported account types to '
                                       '“any organizational directory and personal Microsoft accounts”'),
                       ('AADSTS65001', 'access to mail was not allowed — sign in again and accept'),
                       ('invalid_grant', 'the Microsoft sign-in has expired or was withdrawn — click “Sign in with Microsoft” again'),
                       ('expired_token', 'the code expired before you signed in — start again'),
                       ('authorization_declined', 'you declined the access request')):
        if code in d:
            return text
    return d.split('\r\n')[0][:200]


def start(client_id, tenant='common'):
    """Begin a sign-in. → dict(user_code, verification_uri, interval, expires_in, message, device_code, tenant)"""
    if not (client_id or '').strip():
        raise AuthError('enter the application (client) ID first')
    status, j = _call('devicecode', client_id.strip(), tenant, {'scope': SCOPES})
    if status >= 400 or 'device_code' not in j:
        raise AuthError(friendly(j))
    j['tenant'] = j.pop('_tenant', tenant or 'common')
    j['started'] = time.time()
    return j


def poll(client_id, pending):
    """One check whether the user has finished signing in. → ('pending' | 'ok' | 'error', payload)"""
    status, j = _call('token', client_id, pending.get('tenant'), {'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
                                                                  'device_code': pending['device_code']})
    if status < 400 and j.get('refresh_token'):
        _remember(j['refresh_token'], j)
        j['account'] = signed_in_as(j)
        return 'ok', j
    err = j.get('error', '')
    if err in ('authorization_pending', 'slow_down'):
        return 'pending', j
    return 'error', friendly(j)


def _key(rt):
    return hashlib.sha256(rt.encode()).hexdigest()


def _remember(presented, j):
    if j.get('access_token'):
        entry = (j['access_token'], time.time() + int(j.get('expires_in', 3600)) - 120, j.get('refresh_token') or presented)
        TOKENS[_key(presented)] = entry
        if j.get('refresh_token'):
            TOKENS[_key(j['refresh_token'])] = entry


def signed_in_as(j):
    """The account Microsoft signed in (from the id_token of the sign-in; read only to compare with the mailbox address)."""
    try:
        part = j['id_token'].split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))
        return str(claims.get('email') or claims.get('preferred_username') or '').lower()
    except (KeyError, IndexError, ValueError, TypeError):
        return ''


def forget(user=None):
    """Drop cached access tokens and pending sign-ins (on lock / quit)."""
    TOKENS.clear()
    for k in [k for k in DEVICE if user is None or k[0] == user]:
        DEVICE.pop(k, None)


def access_token(client_id, tenant, refresh_token, user=''):
    """A valid access token for IMAP / SMTP. → (access token, newest refresh token)
    Microsoft may hand out a new refresh token; the caller saves it (older ones stay valid until they expire)."""
    if not refresh_token:
        raise AuthError('not signed in to Microsoft — click “Sign in with Microsoft” on Settings › Mail inbox')
    cached = TOKENS.get(_key(refresh_token))
    if cached and cached[1] > time.time():
        return cached[0], cached[2]
    status, j = _call('token', client_id, tenant, {'grant_type': 'refresh_token', 'refresh_token': refresh_token, 'scope': SCOPES})
    if status >= 400 or not j.get('access_token'):
        TOKENS.pop(_key(refresh_token), None)
        raise AuthError(friendly(j))
    _remember(refresh_token, j)
    return j['access_token'], j.get('refresh_token') or refresh_token


def xoauth2(user, token):
    """The SASL XOAUTH2 string for IMAP AUTHENTICATE / SMTP AUTH (not yet base64-encoded)."""
    return f'user={user}\x01auth=Bearer {token}\x01\x01'
