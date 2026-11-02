"""Purchase-bound WebAuthn approval using the standard library and OpenSSL.

The maintained py_webauthn package is preferred, but it is not present in this
offline build environment. This is adapted from the phone-proven review-panel
implementation. The relying-party origin is configured, never inferred from a
request Host header.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit


def b64e(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode()


def b64d(value):
    value = str(value or '').encode()
    return base64.urlsafe_b64decode(value + b'=' * (-len(value) % 4))


class PurchasePasskeys:
    def __init__(self, state_file, public_origin, openssl='openssl'):
        self.state_file = Path(state_file)
        self.public_origin = str(public_origin).rstrip('/')
        parsed = urlsplit(self.public_origin)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.path:
            raise ValueError('passkey origin must be an https origin without a path')
        self.rp_id = parsed.hostname.lower()
        self.openssl = openssl
        self.lock = threading.Lock()
        self.challenges = {}
        self.enrollment_token = secrets.token_urlsafe(32)

    def enrollment_link(self):
        if not self.enrollment_token:
            return ''
        return f'{self.public_origin}/approve?enrol={self.enrollment_token}'

    def has_credential(self):
        return bool((self._state().get('credential') or {}).get('id'))

    def _state(self):
        try:
            value = json.loads(self.state_file.read_text())
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_state(self, value):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='.approveaccept-passkey-', dir=self.state_file.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump(value, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, self.state_file)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _remember(self, kind, challenge, **fields):
        flow = secrets.token_urlsafe(18)
        self.challenges[flow] = dict(kind=kind, challenge=b64e(challenge),
                                     expires=time.time() + 300, **fields)
        return flow

    def registration_options(self, token):
        if not self.enrollment_token or not secrets.compare_digest(str(token), self.enrollment_token):
            raise ValueError('enrolment link is invalid or has already been used')
        challenge = secrets.token_bytes(32)
        with self.lock:
            flow = self._remember('create', challenge, token=str(token))
        return dict(flow=flow, publicKey=dict(
            challenge=b64e(challenge), rp={'name': 'ApproveAccept', 'id': self.rp_id},
            user={'id': b64e(b'approveaccept-owner'), 'name': 'Owner', 'displayName': 'ApproveAccept owner'},
            pubKeyCredParams=[{'type': 'public-key', 'alg': -7}], timeout=60000,
            attestation='none',
            authenticatorSelection={'authenticatorAttachment': 'platform', 'residentKey': 'required',
                                    'requireResidentKey': True, 'userVerification': 'required'}))

    @staticmethod
    def purchase_identity(purchase):
        return {
            'purchase_id': str(purchase['purchase_id']),
            'amount_cents': int(purchase['amount_cents']),
            'merchant': str(purchase['merchant']),
        }

    def assertion_options(self, purchase, approval_token):
        credential = self._state().get('credential') or {}
        if not credential.get('id'):
            raise ValueError('no passkey has been enrolled')
        bound = dict(self.purchase_identity(purchase), expires=int(time.time()) + 300,
                     nonce=secrets.token_hex(16))
        challenge = json.dumps(bound, sort_keys=True, separators=(',', ':')).encode()
        with self.lock:
            flow = self._remember('get', challenge, purchase=bound,
                                  approval_hash=hashlib.sha256(str(approval_token).encode()).hexdigest())
        return dict(flow=flow, publicKey=dict(challenge=b64e(challenge), timeout=60000,
                    rpId=self.rp_id, userVerification='required',
                    allowCredentials=[{'type': 'public-key', 'id': credential['id']}]))

    def _consume(self, flow, kind):
        with self.lock:
            row = self.challenges.pop(str(flow), None)
        if not row or row['kind'] != kind or row['expires'] < time.time():
            raise ValueError('challenge is invalid or expired')
        return row

    def _client(self, payload, kind, challenge):
        try:
            raw = b64d(payload['clientDataJSON'])
            client = json.loads(raw)
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError('bad client data') from exc
        if client.get('type') != f'webauthn.{kind}' or client.get('challenge') != challenge:
            raise ValueError('client challenge refused')
        if client.get('origin', '').lower() != self.public_origin.lower():
            raise ValueError('client origin refused')
        return raw

    def _auth_data(self, payload):
        try:
            value = b64d(payload['authenticatorData'])
        except (KeyError, ValueError) as exc:
            raise ValueError('bad authenticator data') from exc
        if len(value) < 37 or value[:32] != hashlib.sha256(self.rp_id.encode()).digest():
            raise ValueError('authenticator site refused')
        if value[32] & 0x05 != 0x05:
            raise ValueError('user presence and verification are required')
        return value

    def _verify_key(self, der):
        with tempfile.NamedTemporaryFile() as key:
            key.write(der)
            key.flush()
            result = subprocess.run([self.openssl, 'pkey', '-pubin', '-inform', 'DER', '-in', key.name,
                                     '-noout'], capture_output=True, timeout=5)
        if result.returncode:
            raise ValueError('unsupported public key')

    def register(self, payload):
        row = self._consume(payload.get('flow'), 'create')
        if not secrets.compare_digest(str(payload.get('token', '')), row['token']):
            raise ValueError('enrolment token refused')
        self._client(payload, 'create', row['challenge'])
        auth = self._auth_data(payload)
        try:
            credential_id, public_key = str(payload['id']), b64d(payload['publicKey'])
        except (KeyError, ValueError) as exc:
            raise ValueError('passkey response is incomplete') from exc
        if not credential_id or len(public_key) > 4096:
            raise ValueError('passkey response is invalid')
        self._verify_key(public_key)
        self._write_state({'credential': {'id': credential_id, 'public_key': b64e(public_key),
                                           'sign_count': int.from_bytes(auth[33:37], 'big')}})
        with self.lock:
            self.enrollment_token = ''
        return {'enrolled': True}

    def verify_assertion(self, payload, purchase, approval_token):
        row = self._consume(payload.get('flow'), 'get')
        current = self.purchase_identity(purchase)
        if any(row['purchase'].get(key) != value for key, value in current.items()):
            raise ValueError('purchase details changed after Face ID started')
        if int(row['purchase']['expires']) < int(time.time()):
            raise ValueError('challenge is invalid or expired')
        expected_hash = hashlib.sha256(str(approval_token).encode()).hexdigest()
        if not secrets.compare_digest(row['approval_hash'], expected_hash):
            raise ValueError('Face ID approval belongs to a different purchase link')
        client_raw = self._client(payload, 'get', row['challenge'])
        auth = self._auth_data(payload)
        state, credential_id = self._state(), str(payload.get('id', ''))
        credential = state.get('credential') or {}
        if not credential_id or not secrets.compare_digest(credential_id, str(credential.get('id', ''))):
            raise ValueError('unknown passkey')
        try:
            signature = b64d(payload['signature'])
            public_key = b64d(credential['public_key'])
        except (KeyError, ValueError) as exc:
            raise ValueError('bad assertion') from exc
        signed = auth + hashlib.sha256(client_raw).digest()
        with tempfile.NamedTemporaryFile() as key, tempfile.NamedTemporaryFile() as sig, \
                tempfile.NamedTemporaryFile() as data:
            key.write(public_key); key.flush()
            sig.write(signature); sig.flush()
            data.write(signed); data.flush()
            result = subprocess.run([self.openssl, 'dgst', '-sha256', '-verify', key.name,
                                     '-keyform', 'DER', '-signature', sig.name, data.name],
                                    capture_output=True, timeout=5)
        if result.returncode:
            raise ValueError('bad assertion')
        count, old = int.from_bytes(auth[33:37], 'big'), int(credential.get('sign_count') or 0)
        if count and old and count <= old:
            raise ValueError('passkey counter did not advance')
        if count > old:
            credential['sign_count'] = count
            state['credential'] = credential
            self._write_state(state)
        return {'verified': True, 'purchase': row['purchase']}
