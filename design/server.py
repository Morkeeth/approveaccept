"""Public web process for the generic dashboard and phone approval page.

It proxies purchase requests, phone-link reads and decisions to the internal Sandbox API.
If that API is down, the state route uses a stripped fixture and every write fails.
Run: python3 -B design/server.py
"""
import json
import os
import pathlib
import secrets
import threading
import time
from http.cookies import SimpleCookie
from urllib.parse import urlsplit
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = pathlib.Path(__file__).parent
UPSTREAM_ROOT = os.environ.get('AA_UPSTREAM', 'http://127.0.0.1:8752').rstrip('/')
PORT = int(os.environ.get('AA_DESIGN_PORT', os.environ.get('PORT', '8754')))
HOST = os.environ.get('AA_DESIGN_HOST', '127.0.0.1')
OWNER_TOKEN = os.environ.get('APPROVEACCEPT_OWNER_TOKEN', '')
AGENT_TOKEN = os.environ.get('APPROVEACCEPT_AGENT_TOKEN', '')
AGENT_NAME = os.environ.get('APPROVEACCEPT_AGENT_NAME', '')
PUBLIC_ORIGIN = os.environ.get('APPROVEACCEPT_PUBLIC_BASE_URL', '').rstrip('/')
WEBHOOK_PORT = os.environ.get('LEASH_V2_WEBHOOK_PORT', '')
if OWNER_TOKEN and AGENT_TOKEN and secrets.compare_digest(OWNER_TOKEN.encode(), AGENT_TOKEN.encode()):
    raise ValueError('Owner and agent access keys must be different')
SESSIONS = {}
SESSION_LOCK = threading.Lock()
LOGIN_ATTEMPTS = {}
CAPABILITY_WRITES = {'/api/phone-decision', '/api/passkey/enrol', '/api/suggestion'}
WRITES = {'/api/decide', '/api/attacks', '/api/purchase', '/api/phone-decision',
          '/api/passkey/enrol', '/api/suggestion', '/api/subscription-cancel',
          '/api/allowance', '/api/allowance-revoke', '/api/approval-link',
          '/api/demo/start', '/api/shopping/setup', '/api/ideas', '/api/ideas/choose',
          '/api/agent-key', '/api/agent-key-revoke'}


AGENT_KEY_PREFIX = 'aa_agent_'


def is_agent_key(value):
    # Owner-created per-agent keys. The front cannot check them (only their hash lives in the
    # backend), so it forwards the caller's own key and the backend decides who it is.
    return value.startswith(AGENT_KEY_PREFIX) and 40 <= len(value) <= 120 and value.isascii() \
        and all(c.isalnum() or c in '_-' for c in value)


def upstream_headers(owner=True, agent_key=''):
    # Forward the already-checked role, never upgrade an agent to owner.
    token = OWNER_TOKEN if owner else (agent_key or AGENT_TOKEN)
    headers = {'Content-Type': 'application/json', 'Origin': UPSTREAM_ROOT}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    return headers


def upstream_request(path, owner=True, agent_key=''):
    return urllib.request.Request(UPSTREAM_ROOT + path, headers=upstream_headers(owner, agent_key))


def state():
    try:
        with urllib.request.urlopen(upstream_request('/api/state'), timeout=10) as r:
            d = json.load(r)
        src = 'local substitute, no PayPal calls' if d.get('substitute') else 'PayPal Sandbox backend'
    except Exception:
        d = json.loads((HERE / 'fixtures' / 'state.json').read_text())
        src = 'fixture snapshot 18 Oct'
    for p in d.get('proposals', []):
        if p.get('money'):
            p['money'].pop('approval_url', None)
    d['source'] = src
    return d


def public_demo():
    """Synthetic examples only, never a snapshot of the owner's payment store."""
    items = []
    for rank, bucket, title, amount in [(1, 'needs_me', 'API credit pack', 'EUR 48.00'),
                                      (2, 'auto_approved', 'Build logs', 'EUR 18.00'),
                                      (3, 'blocked', 'Unplanned flight', 'EUR 76.00')]:
        items.append({'id': 'SAMPLE-' + str(rank), 'rank': rank, 'bucket': bucket,
                      'agent': 'Example build agent', 'title': title, 'amount': amount,
                      'merchant': 'Example supplier', 'urgency': 'Sample request',
                      'risk': 'Owner review', 'allowance': 'Inside allowance' if bucket == 'auto_approved' else 'Outside allowance',
                      'recurring': False, 'why': 'Synthetic example. No purchase was made.',
                      'task': 'Show how an agent request is sorted.'})
    return {'access': 'public_demo', 'source': 'Synthetic read-only demo. No PayPal calls.',
            'substitute': True, 'guided_demo': True, 'passkey_ready': False,
            'request_overview': {'items': items, 'next_action_id': 'SAMPLE-1',
                                 'counts': {'needs_me': 1, 'auto_approved': 1, 'blocked': 1}}}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype, cookie=None):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(b)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if urlsplit(self.path).path == '/return':
            self.send_header('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(b)

    def token_role(self):
        header = self.headers.get('Authorization', '')
        value = header[7:] if header.startswith('Bearer ') else ''
        if len(OWNER_TOKEN) >= 32 and value and secrets.compare_digest(value.encode(), OWNER_TOKEN.encode()):
            return 'owner'
        if len(AGENT_TOKEN) >= 32 and AGENT_NAME and value and secrets.compare_digest(value.encode(), AGENT_TOKEN.encode()):
            return 'agent'
        if value and is_agent_key(value):
            return 'agent_key'
        return None

    def agent_key(self):
        header = self.headers.get('Authorization', '')
        value = header[7:] if header.startswith('Bearer ') else ''
        return value if self.token_role() == 'agent_key' else ''

    def owner_session(self):
        try:
            cookie = SimpleCookie(self.headers.get('Cookie', ''))
            token = cookie['aa_owner'].value if 'aa_owner' in cookie else ''
        except Exception:
            return False
        with SESSION_LOCK:
            expired = [key for key, until in SESSIONS.items() if until <= time.monotonic()]
            for key in expired:
                del SESSIONS[key]
            return token in SESSIONS

    def is_owner(self):
        return self.token_role() == 'owner' or self.owner_session()

    def same_origin(self):
        origin = self.headers.get('Origin', '')
        expected = PUBLIC_ORIGIN or 'http://' + self.headers.get('Host', '')
        return bool(origin) and origin == expected

    def reply_json(self, code, body, cookie=None):
        return self.send(code, json.dumps(body), 'application/json', cookie=cookie)

    def do_GET(self):
        if self.path == '/health':
            return self.send(200, json.dumps({'ok': True, 'service': 'approveaccept-web'}), 'application/json')
        if self.path == '/api/shopping/status':
            if not self.is_owner():
                return self.reply_json(401, {'error': 'Owner sign-in required'})
            try:
                with urllib.request.urlopen(upstream_request(self.path, self.is_owner()), timeout=10) as response:
                    return self.send(response.status, response.read(), 'application/json')
            except Exception:
                return self.reply_json(502, {'error': 'Shopping backend unavailable'})
        if self.path == '/api/state':
            if not self.is_owner():
                return self.reply_json(200, public_demo())
            value = state()
            value['access'] = 'owner'
            return self.reply_json(200, value)
        if self.path.startswith('/api/agent/policy?'):
            if not (self.is_owner() or self.token_role() in ('agent', 'agent_key')):
                return self.reply_json(401, {'error': 'Agent sign-in required'})
            from urllib.parse import parse_qs, quote
            name = parse_qs(urlsplit(self.path).query).get('agent', [''])[0]
            if not self.is_owner() and self.token_role() == 'agent' and name != AGENT_NAME:
                return self.reply_json(403, {'error': 'Use the agent identity assigned to this token'})
            try:
                with urllib.request.urlopen(upstream_request('/api/agent/policy?agent=' + quote(name), self.is_owner(), self.agent_key()), timeout=10) as response:
                    return self.send(response.status, response.read(), 'application/json')
            except urllib.error.HTTPError as exc:
                return self.send(exc.code, exc.read(), 'application/json')
            except Exception:
                return self.reply_json(502, {'error': 'PayPal sandbox backend unavailable'})
        if self.path.startswith('/api/agent/status?'):
            if not (self.is_owner() or self.token_role() in ('agent', 'agent_key')):
                return self.reply_json(401, {'error': 'Agent sign-in required'})
            try:
                with urllib.request.urlopen(upstream_request(self.path, self.is_owner(), self.agent_key()), timeout=10) as response:
                    value = json.load(response)
                if not self.is_owner() and self.token_role() == 'agent' and value.get('agent') != AGENT_NAME:
                    return self.reply_json(403, {'error': 'This request belongs to another agent'})
                return self.reply_json(200, value)
            except urllib.error.HTTPError as exc:
                return self.send(exc.code, exc.read(), 'application/json')
            except Exception:
                return self.reply_json(502, {'error': 'PayPal sandbox backend unavailable'})
        if self.path.startswith(('/api/approval?', '/api/passkey/options?', '/api/passkey/enrol/options?')):
            try:
                with urllib.request.urlopen(upstream_request(self.path, self.is_owner()), timeout=10) as r:
                    return self.send(r.status, r.read(), 'application/json')
            except urllib.error.HTTPError as exc:
                return self.send(exc.code, exc.read(), 'application/json')
            except Exception:
                return self.send(502, json.dumps({'error': 'PayPal sandbox backend unavailable'}), 'application/json')
        if urlsplit(self.path).path == '/return':
            # The one-order return capability is checked upstream. Never attach owner authority.
            try:
                with urllib.request.urlopen(urllib.request.Request(UPSTREAM_ROOT + self.path), timeout=30) as response:
                    return self.send(response.status, response.read(), 'text/html; charset=utf-8')
            except urllib.error.HTTPError as exc:
                return self.send(exc.code, exc.read(), 'text/html; charset=utf-8')
            except Exception:
                return self.send(502, 'Sandbox return verification unavailable. Ask the owner to check the existing purchase.', 'text/plain')
        if self.path in ('/', '/index.html'):
            return self.send(200, (HERE.parent / 'index.html').read_bytes(), 'text/html; charset=utf-8')
        if self.path.startswith('/approve?') or self.path == '/approve':
            return self.send(200, (HERE.parent / 'phone.html').read_bytes(), 'text/html; charset=utf-8')
        self.send(404, 'not found', 'text/plain')

    def do_POST(self):
        if self.path == '/webhooks/paypal':
            # Public provider ingress has no owner cookie. The loopback listener verifies the
            # PayPal signature against this run's webhook ID before recording an event.
            if not WEBHOOK_PORT.isdecimal():
                return self.reply_json(503, {'error': 'Sandbox webhook listener is not configured'})
            try:
                n = int(self.headers.get('Content-Length') or 0)
                if not 0 < n <= 200_000:
                    return self.reply_json(413, {'error': 'Invalid webhook size'})
                raw = self.rfile.read(n)
                headers = {'Content-Type': self.headers.get('Content-Type', 'application/json')}
                for name in ('PAYPAL-AUTH-ALGO', 'PAYPAL-CERT-URL', 'PAYPAL-TRANSMISSION-ID',
                             'PAYPAL-TRANSMISSION-SIG', 'PAYPAL-TRANSMISSION-TIME'):
                    if self.headers.get(name):
                        headers[name] = self.headers[name]
                req = urllib.request.Request('http://127.0.0.1:' + WEBHOOK_PORT + '/webhooks/paypal',
                                             raw, headers, method='POST')
                with urllib.request.urlopen(req, timeout=30) as response:
                    return self.send(response.status, response.read(), 'application/json')
            except urllib.error.HTTPError as exc:
                return self.send(exc.code, exc.read(), 'application/json')
            except (ValueError, OSError):
                return self.reply_json(502, {'error': 'Sandbox webhook listener unavailable'})
        if self.path in ('/api/session', '/api/session/end'):
            if not self.same_origin():
                return self.reply_json(403, {'error': 'Same-origin sign-in required'})
            if self.path == '/api/session/end':
                try:
                    cookie = SimpleCookie(self.headers.get('Cookie', ''))
                    with SESSION_LOCK:
                        SESSIONS.pop(cookie['aa_owner'].value if 'aa_owner' in cookie else '', None)
                except Exception:
                    pass
                return self.reply_json(200, {'signed_out': True}, 'aa_owner=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
            if len(OWNER_TOKEN) < 32:
                return self.reply_json(503, {'error': 'Owner sign-in is not configured'})
            peer = self.client_address[0]
            with SESSION_LOCK:
                attempts = [at for at in LOGIN_ATTEMPTS.get(peer, []) if at > time.monotonic() - 60]
                LOGIN_ATTEMPTS[peer] = attempts
                if len(attempts) >= 10:
                    return self.reply_json(429, {'error': 'Try sign-in again in a minute'})
                attempts.append(time.monotonic())
            try:
                length = int(self.headers.get('Content-Length') or 0)
                if not 0 < length <= 4096:
                    return self.reply_json(400, {'error': 'Small sign-in request required'})
                value = json.loads(self.rfile.read(length)).get('token', '')
                if not isinstance(value, str) or not secrets.compare_digest(value, OWNER_TOKEN):
                    return self.reply_json(401, {'error': 'Owner sign-in refused'})
            except (ValueError, TypeError, AttributeError):
                return self.reply_json(400, {'error': 'Invalid sign-in request'})
            token = secrets.token_urlsafe(32)
            with SESSION_LOCK:
                SESSIONS[token] = time.monotonic() + 3600
            secure = '; Secure' if PUBLIC_ORIGIN.startswith('https://') else ''
            return self.reply_json(200, {'signed_in': True}, 'aa_owner=' + token + '; HttpOnly; SameSite=Strict; Path=/; Max-Age=3600' + secure)
        if self.path not in WRITES:
            return self.send(405, json.dumps({'error': 'route not allowed'}), 'application/json')
        role = self.token_role()
        owner = self.is_owner()
        if self.path not in CAPABILITY_WRITES:
            if not owner and not (role in ('agent', 'agent_key') and self.path == '/api/purchase'):
                return self.reply_json(401, {'error': 'Owner or authorized agent sign-in required'})
            if role != 'owner' and owner and not self.same_origin():
                return self.reply_json(403, {'error': 'Same-origin owner action required'})
        elif not self.same_origin():
            return self.reply_json(403, {'error': 'Same-origin phone action required'})
        try:
            n = int(self.headers.get('Content-Length') or 0)
            if not 0 <= n <= 16_384:
                return self.reply_json(413, {'error': 'Request too large'})
            body = self.rfile.read(n) or b'{}'
            value = json.loads(body)
            if not isinstance(value, dict):
                return self.reply_json(400, {'error': 'JSON object required'})
            if role == 'agent' and not owner and value.get('agent') != AGENT_NAME:
                return self.reply_json(403, {'error': 'Use the agent identity assigned to this token'})
            req = urllib.request.Request(UPSTREAM_ROOT + self.path, body,
                                         upstream_headers(owner, self.agent_key() if not owner else ''))
            with urllib.request.urlopen(req, timeout=60) as r:
                return self.send(r.status, r.read(), 'application/json')
        except json.JSONDecodeError:
            return self.send(400, json.dumps({'error': 'bad json'}), 'application/json')
        except urllib.error.HTTPError as exc:
            return self.send(exc.code, exc.read(), 'application/json')
        except Exception:
            return self.send(502, json.dumps({'error': 'PayPal sandbox backend unavailable'}), 'application/json')


if __name__ == '__main__':
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
