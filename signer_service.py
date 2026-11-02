"""TEST DOUBLE ONLY: simulated local hardware signer for ApproveAccept.

This process is deliberately separate from the purchase API. It signs an exact,
short-lived request challenge with a local HMAC key. It is a mock, not WebAuthn,
not a hardware security key, and not evidence of a real device integration. The
ApproveAccept app does not import or call this module.
"""
import hashlib
import hmac
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = int(os.environ.get('APPROVEACCEPT_SIGNER_PORT', '8760'))
KEY_FILE = Path(os.environ.get('APPROVEACCEPT_SIGNER_KEY_FILE', '/private/tmp/approveaccept-signer-test-double.db')).resolve()


def load_key():
    import sqlite3
    with sqlite3.connect(KEY_FILE) as db:
        row = db.execute("SELECT v FROM kv WHERE k='device_key'").fetchone()
    if not row:
        raise RuntimeError('simulated signer key is missing')
    return bytes.fromhex(row[0])


def sign_challenge(challenge):
    required = {'request_id', 'order_id', 'agent', 'merchant', 'title', 'cents', 'currency', 'expires', 'nonce'}
    if set(challenge) != required or challenge['currency'] != 'EUR':
        raise ValueError('challenge fields do not match the signer contract')
    if type(challenge['cents']) is not int or challenge['cents'] <= 0:
        raise ValueError('amount must be positive integer cents')
    if type(challenge['expires']) is not int or challenge['expires'] < int(time.time()):
        raise ValueError('challenge expired')
    raw = json.dumps(challenge, sort_keys=True, separators=(',', ':')).encode()
    return {'challenge': challenge, 'signature': hmac.new(load_key(), raw, hashlib.sha256).hexdigest(),
            'mode': 'SIMULATED local process'}


class H(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        if self.path != '/sign':
            return self.reply(404, {'error': 'not found'})
        try:
            size = min(int(self.headers.get('Content-Length') or 0), 16_384)
            return self.reply(200, sign_challenge(json.loads(self.rfile.read(size))))
        except (ValueError, json.JSONDecodeError, RuntimeError) as exc:
            return self.reply(409, {'error': str(exc)})

    def reply(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', PORT), H).serve_forever()
