"""Scripted IMAP4rev1 server (Gmail-like responses) to check mailreader.Imap's commands and response parsing."""
import socket, ssl, threading, re, sys, os, tempfile, datetime as _dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import fresh  # noqa: E402
fresh('imap')
# self-signed certificate for the test server (made with the cryptography package — no openssl needed)
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
_k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_n = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
_c = (x509.CertificateBuilder().subject_name(_n).issuer_name(_n).public_key(_k.public_key()).serial_number(1)
      .not_valid_before(_dt.datetime(2020, 1, 1)).not_valid_after(_dt.datetime(2040, 1, 1)).sign(_k, hashes.SHA256()))
_d = tempfile.mkdtemp()
open(f'{_d}/c.pem', 'wb').write(_c.public_bytes(serialization.Encoding.PEM))
open(f'{_d}/k.pem', 'wb').write(_k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
MSG = {41: b'From: Bank <a@sbi.co.in>\r\nSubject: Statement\r\nDate: Wed, 07 Oct 2026 10:00:00 +0530\r\nMessage-ID: <m41@x>\r\n\r\nbody 41\r\n',
       42: b'From: Shop <b@shop.example>\r\nSubject: Sale\r\nMessage-ID: <m42@x>\r\n\r\nbody 42\r\n'}
SEEN = []
def hdr(m):
    return m.split(b'\r\n\r\n')[0] + b'\r\n\r\n'
def serve(sock):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(f'{_d}/c.pem', f'{_d}/k.pem')
    for _conn in range(2):
        conn, _ = sock.accept(); s = ctx.wrap_socket(conn, server_side=True); f = s.makefile('rwb')
        session(f)
def session(f):
    w = lambda b: (f.write(b), f.flush())
    w(b'* OK Gimap ready\r\n')
    while True:
        line = f.readline()
        if not line: break
        SEEN.append(line.decode().strip())
        tag, cmd = line.split(b' ', 1); c = cmd.strip().upper()
        if c.startswith(b'CAPABILITY'):
            w(b'* CAPABILITY IMAP4rev1 X-GM-EXT-1 UIDPLUS\r\n' + tag + b' OK done\r\n')
        elif c.startswith(b'AUTHENTICATE XOAUTH2'):          # 1.8: Outlook
            w(b'+ \r\n')
            import base64
            SEEN.append('XOAUTH2 ' + base64.b64decode(f.readline().strip()).decode().replace('\x01', '|'))
            w(tag + b' OK AUTHENTICATE completed.\r\n')
        elif c.startswith(b'LOGIN'):
            w(tag + b' OK user authenticated\r\n')
        elif c.startswith(b'SELECT'):
            w(b'* FLAGS (\\Seen)\r\n* 2 EXISTS\r\n* OK [UIDVALIDITY 9876] UIDs valid.\r\n* OK [UIDNEXT 43] Predicted next UID.\r\n' + tag + b' OK [READ-WRITE] INBOX selected.\r\n')
        elif c.startswith(b'UID SEARCH'):
            w(b'* SEARCH 41 42\r\n' + tag + b' OK SEARCH completed\r\n')
        elif c.startswith(b'UID FETCH') and b'HEADER.FIELDS' in c:
            out = b''
            for i, u in enumerate((41, 42), 1):
                h = hdr(MSG[u]); out += b"* %d FETCH (BODY[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)] {%d}\r\n" % (i, len(h)) + h + b" UID %d RFC822.SIZE %d)\r\n" % (u, len(MSG[u]))
            w(out + tag + b' OK Success\r\n')
        elif c.startswith(b'UID FETCH'):
            u = int(re.search(rb'UID FETCH (\d+)', c).group(1)); m = MSG[u]
            w(b'* 1 FETCH (UID %d BODY[] {%d}\r\n' % (u, len(m)) + m + b')\r\n' + tag + b' OK Success\r\n')
        elif c.startswith(b'UID STORE'):
            w(b'* 1 FETCH (UID 41 X-GM-LABELS ("FinanceHub"))\r\n' + tag + b' OK Success\r\n')
        elif c.startswith(b'LOGOUT'):
            w(b'* BYE\r\n' + tag + b' OK bye\r\n'); break
        else:
            w(tag + b' BAD unknown\r\n')
sock = socket.socket(); sock.bind(('127.0.0.1', 0)); sock.listen(1); port = sock.getsockname()[1]
threading.Thread(target=serve, args=(sock,), daemon=True).start()
import mailreader as M, ssl as _ssl
_orig = _ssl.create_default_context
M.ssl.create_default_context = lambda: (lambda c: (setattr(c, 'check_hostname', False), setattr(c, 'verify_mode', _ssl.CERT_NONE), c)[2])(_orig())
from datetime import date
cli = M.Imap('127.0.0.1', port, 'hub@gmail.com', 'pw pw')
print('caps has gmail ext:', 'X-GM-EXT-1' in cli.caps)
uv = cli.select('INBOX'); print('uidvalidity', uv)
uids = cli.search_since(date(2026, 9, 1)); print('uids', uids)
h = cli.headers(uids); print('headers', {k: (v[0][:30], v[1]) for k, v in h.items()})
raw = cli.message(41); print('full', raw[:40])
cli.label(41, 'FinanceHub'); cli.close()
for s in SEEN: print('  C:', s)
assert uv == '9876' and uids == [41, 42] and set(h) == {41, 42} and h[41][1] == len(MSG[41]) and raw == MSG[41]
assert any('SINCE 01-Sep-2026' in s for s in SEEN) and any('BODY.PEEK[]' in s for s in SEEN) and any('+X-GM-LABELS ("FinanceHub")' in s for s in SEEN)
print('IMAP client OK')
SEEN.clear()
cli = M.Imap('127.0.0.1', port, 'hub@outlook.com', None, oauth_token='AT-synthetic')
assert cli.select('INBOX') == '9876'; cli.close()
assert 'XOAUTH2 user=hub@outlook.com|auth=Bearer AT-synthetic||' in SEEN and not any(x.split(' ', 1)[1].upper().startswith('LOGIN') for x in SEEN if ' ' in x), SEEN
print('IMAP XOAUTH2 OK')
