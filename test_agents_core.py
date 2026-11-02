"""Core flow: named agents with their own keys send purchases to PayPal; the owner's limits decide.

Real loopback HTTP against an isolated substitute server; no PayPal credentials.
"""
import json, os, secrets, socket, subprocess, sys, tempfile, time, unittest, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OWNER = 'synthetic-core-owner-' + 32 * 'o'


class AgentsCore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); data = Path(cls.tmp.name)
        sock = socket.socket(); sock.bind(('127.0.0.1', 0)); cls.port = sock.getsockname()[1]; sock.close()
        cls.base = f'http://127.0.0.1:{cls.port}'
        env = {k: v for k, v in os.environ.items() if not k.startswith(('APPROVEACCEPT_', 'PAYPAL_', 'LEASH_V2_')) and not k.endswith('_API_KEY')}
        env.update(LEASH_V2_SUBSTITUTE='1', LEASH_V2_DATA=str(data), LEASH_V2_PORT=str(cls.port),
                   APPROVEACCEPT_PASSKEY_ORIGIN='https://approve.example.test', APPROVEACCEPT_OWNER_TOKEN=OWNER)
        cls.log = (data / 'server.log').open('w')
        cls.proc = subprocess.Popen([sys.executable, '-B', str(ROOT / 'app.py')], cwd=ROOT, env=env, stdout=cls.log, stderr=cls.log)
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.base + '/health', timeout=1).read(); break
            except Exception:
                time.sleep(.05)
        cls.keys = {}
        for name, cats, per, month in (('Claude Code', ['hosting', 'database', 'domain'], 3000, 12000),
                                       ('GrokBot', ['travel'], 5000, 20000)):
            cls.keys[name] = cls.req('/api/agent-key', {'agent': name})[1]['key']
            code, _ = cls.req('/api/allowance', {'agent': name, 'merchants': ['Sandbox dev services', 'Sandbox travel'],
                                                 'categories': cats, 'per_purchase_cents': per, 'monthly_cents': month, 'days': 7})
            assert code == 200

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate(); cls.proc.wait(timeout=5); cls.log.close(); cls.tmp.cleanup()

    @classmethod
    def req(cls, path, data=None, token=OWNER):
        r = urllib.request.Request(cls.base + path, data=None if data is None else json.dumps(data).encode(),
                                   headers={'Content-Type': 'application/json', 'Origin': cls.base, 'Authorization': 'Bearer ' + token})
        try:
            with urllib.request.urlopen(r, timeout=20) as resp:
                return resp.status, json.load(resp)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def buy(self, agent, title, category, cents, token=None, merchant='Sandbox dev services'):
        return self.req('/api/purchase', {'agent': agent, 'title': title, 'merchant': merchant, 'category': category,
                                          'cents': cents, 'why': 'Needed to ship the project today.', 'task': 'Ship the demo',
                                          'request_key': secrets.token_hex(12)}, token or self.keys[agent])

    def proposal(self, pid):
        return next(p for p in self.req('/api/state')[1]['proposals'] if p['id'] == pid)

    def test_inside_limit_captures_and_paypal_order_names_the_agent(self):
        code, r = self.buy('Claude Code', 'Domain name .com, 1 year', 'domain', 1200)
        self.assertEqual(code, 200); self.assertEqual(r['state'], 'captured'); self.assertTrue(r['capture_id'].startswith('SUB-'))
        self.assertEqual(self.proposal(r['id'])['money']['purpose'], 'Domain name .com, 1 year - sent by Claude Code')

    def test_over_limit_is_held_and_inbox_cannot_capture_without_face_id(self):
        code, r = self.buy('GrokBot', 'Flight Paris to Lisbon, economy', 'travel', 8900, merchant='Sandbox travel')
        self.assertEqual(code, 200); self.assertEqual(r['state'], 'authorized'); self.assertIn('approval_url', r)
        self.assertTrue(any('per purchase' in x for x in r['reasons']))
        code, e = self.req('/api/decide', {'id': r['id'], 'accept': True})
        self.assertEqual(code, 409); self.assertIn('Face ID', e['error'])
        code, d = self.req('/api/decide', {'id': r['id'], 'accept': False})
        self.assertEqual(code, 200); self.assertEqual(self.proposal(r['id'])['money']['state'], 'voided')

    def test_category_outside_this_agents_permissions_is_blocked_before_paypal(self):
        code, r = self.buy('Claude Code', 'Flight Paris to Lisbon, economy', 'travel', 900, merchant='Sandbox travel')
        self.assertEqual(code, 200); self.assertEqual(r['state'], 'blocked')
        self.assertIn('not allowed for Claude Code', r['reasons'][0])
        self.assertIsNone(self.proposal(r['id'])['money'])

    def test_a_key_cannot_speak_for_another_agent(self):
        code, _ = self.buy('GrokBot', 'Domain name .com, 1 year', 'domain', 1200, token=self.keys['Claude Code'])
        self.assertEqual(code, 403)

    def test_agent_key_cannot_change_permissions_or_read_the_queue(self):
        k = self.keys['Claude Code']
        self.assertEqual(self.req('/api/allowance', {'agent': 'Claude Code', 'merchants': ['x'], 'per_purchase_cents': 10**6,
                                                     'monthly_cents': 10**6}, token=k)[0], 401)
        self.assertEqual(self.req('/api/agent-key', {'agent': 'Claude Code'}, token=k)[0], 401)
        self.assertEqual(self.req('/api/state', token=k)[0], 401)

    def test_keys_are_stored_hashed_and_revocation_takes_effect(self):
        code, made = self.req('/api/agent-key', {'agent': 'Temp agent'})
        self.assertEqual(code, 200); self.assertTrue(made['key'].startswith('aa_agent_'))
        keys = self.req('/api/state')[1]['agent_keys']
        self.assertNotIn(made['key'], json.dumps(keys))
        self.assertEqual(self.req('/api/agent-key-revoke', {'agent': 'Temp agent'})[0], 200)
        self.assertEqual(self.buy('Temp agent', 'Hosting plan, Pro, 1 month', 'hosting', 100, token=made['key'])[0], 401)

    def test_owner_raises_a_limit_and_the_next_request_captures(self):
        code, r = self.buy('Claude Code', 'Managed Postgres, starter', 'database', 3500)
        self.assertEqual(r['state'], 'authorized')
        self.assertEqual(self.req('/api/allowance', {'agent': 'Claude Code', 'merchants': ['Sandbox dev services', 'Sandbox travel'],
                                                     'categories': ['hosting', 'database', 'domain'], 'per_purchase_cents': 4000,
                                                     'monthly_cents': 12000, 'days': 7})[0], 200)
        code, r = self.buy('Claude Code', 'Managed Postgres, starter', 'database', 3500)
        self.assertEqual(r['state'], 'captured')


if __name__ == '__main__':
    unittest.main()
