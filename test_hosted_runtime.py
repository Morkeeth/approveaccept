import secrets
"""Exercise the real hosted entrypoint without credentials or PayPal calls."""
import http.client
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class HostedRuntimeTests(unittest.TestCase):
    def test_container_ingress_and_substitute_identity_without_public_origin(self):
        # Selecting a local interface sends no packet to this documentation IP.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            try:
                sock.connect(('192.0.2.1', 80))
                interface = sock.getsockname()[0]
            except OSError:
                self.skipTest('No local network interface for ingress probe')
        if interface.startswith('127.'):
            self.skipTest('No non-loopback local interface for ingress probe')
        public_port, backend_port = free_port(), free_port()
        with tempfile.TemporaryDirectory(prefix='aa-host-proof-') as data:
            env = {'PATH': os.environ['PATH'], 'HOME': data,
                   'LEASH_V2_SUBSTITUTE': '1', 'AA_DATA_DIR': data,
                   'PORT': str(public_port), 'AA_BACKEND_PORT': str(backend_port)}
            with tempfile.TemporaryFile() as output:
                process = subprocess.Popen(['sh', './start-host.sh'], cwd=ROOT, env=env,
                                           stdout=output, stderr=output, start_new_session=True)
                try:
                    deadline = time.monotonic() + 10
                    while True:
                        try:
                            connection = http.client.HTTPConnection(interface, public_port, timeout=1)
                            connection.request('GET', '/api/state')
                            response = connection.getresponse()
                            state = json.loads(response.read())
                            connection.close()
                            break
                        except OSError:
                            if process.poll() is not None or time.monotonic() >= deadline:
                                output.seek(0)
                                self.fail('Hosted entrypoint did not accept ingress: ' + output.read().decode())
                            time.sleep(.1)
                    self.assertEqual(response.status, 200)
                    self.assertTrue(state['substitute'])
                    self.assertEqual(state['access'], 'public_demo')
                    self.assertEqual(state['source'], 'Synthetic read-only demo. No PayPal calls.')
                    self.assertNotIn('live PayPal', state['source'])
                finally:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=5)


class PublicBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = tempfile.TemporaryDirectory(prefix='aa-boundary-proof-')
        cls.output = tempfile.TemporaryFile()
        cls.port, cls.backend = free_port(), free_port()
        cls.origin = 'http://127.0.0.1:' + str(cls.port)
        cls.owner, cls.agent = 'local-owner-test-' + 'o' * 32, 'local-agent-test-' + 'a' * 32
        env = {'PATH': os.environ['PATH'], 'HOME': cls.data.name,
               'LEASH_V2_SUBSTITUTE': '1', 'AA_DATA_DIR': cls.data.name,
               'PORT': str(cls.port), 'AA_BACKEND_PORT': str(cls.backend),
               'AA_DESIGN_HOST': '127.0.0.1', 'APPROVEACCEPT_GUIDED_DEMO': '1',
               'APPROVEACCEPT_PASSKEY_ORIGIN': 'https://owner.example.test',
               'APPROVEACCEPT_OWNER_TOKEN': cls.owner, 'APPROVEACCEPT_AGENT_TOKEN': cls.agent,
               'APPROVEACCEPT_AGENT_NAME': 'Bound agent'}
        cls.process = subprocess.Popen(['sh', './start-host.sh'], cwd=ROOT, env=env,
                                       stdout=cls.output, stderr=cls.output, start_new_session=True)
        for _ in range(100):
            try:
                cls.request('/health')
                return
            except OSError:
                if cls.process.poll() is not None:
                    break
                time.sleep(.1)
        cls.output.seek(0)
        failure = cls.output.read().decode()
        cls.tearDownClass()
        raise AssertionError('Boundary server failed: ' + failure)

    @classmethod
    def tearDownClass(cls):
        if cls.process.poll() is None:
            os.killpg(cls.process.pid, signal.SIGTERM)
        cls.process.wait(timeout=5)
        cls.output.close()
        cls.data.cleanup()

    @classmethod
    def request(cls, path, body=None, token=None, cookie=None, origin=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        if cookie:
            headers['Cookie'] = cookie
        if origin:
            headers['Origin'] = origin
        connection = http.client.HTTPConnection('127.0.0.1', cls.port, timeout=5)
        connection.request('POST' if body is not None else 'GET', path,
                           json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        result = response.status, json.loads(response.read()), dict(response.getheaders())
        connection.close()
        return result

    @staticmethod
    def purchase(agent):
        return {'request_key':secrets.token_hex(16),'agent': agent, 'title': 'Local boundary test', 'merchant': 'API Foundry',
                'category': 'software', 'cents': 100, 'why': 'Local substitute check',
                'task': 'Exercise the access boundary'}

    def test_anonymous_cannot_grant_allowances_purchase_or_start_paypal_demo(self):
        for path in ['/api/allowance', '/api/allowance-revoke', '/api/purchase',
                     '/api/demo/start', '/api/approval-link', '/api/decide']:
            status, _, _ = self.request(path, {})
            self.assertEqual(status, 401, path)
        status, state, _ = self.request('/api/state')
        self.assertEqual(status, 200)
        self.assertEqual(state['access'], 'public_demo')
        self.assertNotIn('passkey_enrollment_link', state)
        self.assertNotIn('proposals', state)
        self.assertTrue(all(row['id'].startswith('SAMPLE-') for row in state['request_overview']['items']))

    def test_agent_cannot_impersonate_owner_or_another_agent(self):
        self.assertEqual(self.request('/api/allowance', {}, token=self.agent)[0], 401)
        self.assertEqual(self.request('/api/purchase', self.purchase('Other agent'), token=self.agent)[0], 403)
        status, request, _ = self.request('/api/purchase', self.purchase('Bound agent'), token=self.agent)
        self.assertEqual(status, 200)
        self.assertEqual(request['state'], 'captured')  # substitute adapter only
        status, result, _ = self.request('/api/agent/status?id=' + request['id'], token=self.agent)
        self.assertEqual(status, 200)
        self.assertEqual(result['agent'], 'Bound agent')
        self.assertTrue(result['capture_id'].startswith('SUB'))
        status, other, _ = self.request('/api/purchase', self.purchase('Other agent'), token=self.owner)
        self.assertEqual(status, 200)
        self.assertEqual(self.request('/api/agent/status?id=' + other['id'], token=self.agent)[0], 403)

    def test_owner_cookie_requires_same_origin_and_logout_revokes_it(self):
        self.assertEqual(self.request('/api/session', {'token': self.owner})[0], 403)
        self.assertEqual(self.request('/api/session', {'token': 'wrong'}, origin=self.origin)[0], 401)
        status, _, headers = self.request('/api/session', {'token': self.owner}, origin=self.origin)
        self.assertEqual(status, 200)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', headers['Set-Cookie'])
        cookie = headers['Set-Cookie'].split(';')[0]
        _, state, _ = self.request('/api/state', cookie=cookie)
        self.assertEqual(state['access'], 'owner')
        self.assertTrue(state['passkey_enrollment_link'])
        self.assertEqual(self.request('/api/demo/start', {}, cookie=cookie)[0], 403)
        self.assertEqual(self.request('/api/demo/start', {}, cookie=cookie, origin='https://other.example')[0], 403)
        status, demo, _ = self.request('/api/demo/start', {}, cookie=cookie, origin=self.origin)
        self.assertEqual(status, 200)
        self.assertEqual(demo['payment_mode'], 'substitute')
        self.assertEqual(self.request('/api/session/end', {}, cookie=cookie, origin=self.origin)[0], 200)
        self.assertEqual(self.request('/api/state', cookie=cookie)[1]['access'], 'public_demo')

    def test_policy_is_private_and_bound_to_the_agent_token(self):
        self.assertEqual(self.request('/api/agent/policy?agent=Bound%20agent')[0], 401)
        self.assertEqual(self.request('/api/agent/policy?agent=Other', token=self.agent)[0], 403)
        status, policy, _ = self.request('/api/agent/policy?agent=Bound%20agent', token=self.agent)
        self.assertEqual(status, 200)
        self.assertEqual(policy['agent'], 'Bound agent')
        self.assertEqual(policy['payment_mode'], 'substitute')
        self.assertTrue(any('EUR 30.00' in line for line in policy['lines']))

    def test_phone_capability_still_requires_real_backend_validation(self):
        self.assertEqual(self.request('/api/phone-decision', {'token': 'unknown', 'action': 'approve'})[0], 403)
        self.assertEqual(self.request('/api/phone-decision', {'token': 'unknown', 'action': 'approve'}, origin=self.origin)[0], 409)


if __name__ == '__main__':
    unittest.main()
