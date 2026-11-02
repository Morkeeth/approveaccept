"""Step 0 keys: stored once, outside the repo, mode 0600, and never echoed, logged or committed.

Offline by default. Set APPROVEACCEPT_TEST_NETWORK=1 to also drive the server's real
Sandbox credential path with fake keys (one refused OAuth call to api-m.sandbox.paypal.com)
and grep every log, data file and HTTP reply for them.
"""
import json, os, secrets, socket, stat, subprocess, sys, tempfile, time, unittest, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def clean_env(**more):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('APPROVEACCEPT_', 'PAYPAL_', 'LEASH_V2_', 'AA_')) and not k.endswith('_API_KEY')}
    env.update(more)
    return env


class Byok(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.home = Path(self.tmp.name) / 'aa'
        self.client = 'TESTCLIENT' + secrets.token_hex(16)
        self.secret = 'TESTSECRET' + secrets.token_hex(16)
        self.model_key = 'sk-ant-TESTMODEL' + secrets.token_hex(16)

    def tearDown(self):
        self.tmp.cleanup()

    def run_byok(self, home):
        return subprocess.run([sys.executable, '-B', str(ROOT / 'connect' / 'byok.py')], cwd=ROOT, text=True,
                              input=f'{self.client}\n{self.secret}\n\n{self.model_key}\n', capture_output=True, stdin=None,
                              env=clean_env(APPROVEACCEPT_HOME=str(home), APPROVEACCEPT_BYOK_OFFLINE='1'), timeout=30)

    def secrets_in(self, text):
        return [s for s in (self.client, self.secret, self.model_key) if s in text]

    def test_keys_saved_once_private_and_never_echoed(self):
        r = self.run_byok(self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.secrets_in(r.stdout + r.stderr), [])
        f = self.home / 'sandbox.env'
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.home.stat().st_mode), 0o700)
        body = f.read_text()
        self.assertIn(self.client, body); self.assertIn(self.secret, body); self.assertIn(self.model_key, body)
        self.assertIn("APPROVEACCEPT_LIVE_MONEY_ENABLED='false'", body)
        owner = [l for l in body.splitlines() if 'OWNER_TOKEN' in l][0].split("'")[1]
        self.assertGreaterEqual(len(owner), 32)
        self.assertNotIn(owner, r.stdout + r.stderr)

    def test_refuses_to_store_keys_inside_the_repository(self):
        inside = ROOT / ('.byok-test-' + secrets.token_hex(4))
        try:
            r = self.run_byok(inside)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('inside the repository', r.stderr)
            self.assertFalse((inside / 'sandbox.env').exists())
        finally:
            if inside.exists():
                for p in sorted(inside.rglob('*'), reverse=True):
                    p.unlink() if p.is_file() else p.rmdir()
                inside.rmdir()

    def test_no_key_lands_in_tracked_or_untracked_repository_files(self):
        self.assertEqual(self.run_byok(self.home).returncode, 0)
        files = subprocess.run(['git', 'ls-files', '-co', '--exclude-standard'], cwd=ROOT, text=True,
                               capture_output=True).stdout.split()
        hits = [f for f in files if (ROOT / f).is_file() and self.secrets_in((ROOT / f).read_text(errors='ignore'))]
        self.assertEqual(hits, [])

    @unittest.skipUnless(os.environ.get('APPROVEACCEPT_TEST_NETWORK') == '1', 'network leak check is opt-in')
    def test_server_sandbox_path_never_echoes_keys(self):
        self.assertEqual(self.run_byok(self.home).returncode, 0)
        sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
        base = f'http://127.0.0.1:{port}'
        log = Path(self.tmp.name) / 'server.log'
        env = clean_env(APPROVEACCEPT_HOME=str(self.home), AA_PORT=str(port), AA_DATA_DIR=str(Path(self.tmp.name) / 'data'))
        with log.open('w') as out:
            proc = subprocess.Popen(['sh', str(ROOT / 'journey.sh')], cwd=ROOT, env=env, stdout=out, stderr=out)
        try:
            for _ in range(100):
                try:
                    urllib.request.urlopen(base + '/health', timeout=1).read(); break
                except Exception:
                    time.sleep(.05)
            owner = [l for l in (self.home / 'sandbox.env').read_text().splitlines() if 'OWNER_TOKEN' in l][0].split("'")[1]
            replies = []

            def post(path, body):
                req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={
                    'Content-Type': 'application/json', 'Origin': base, 'Authorization': 'Bearer ' + owner})
                try:
                    with urllib.request.urlopen(req, timeout=60) as r: text = r.read().decode()
                except urllib.error.HTTPError as e: text = e.read().decode()
                replies.append(text); return json.loads(text)
            post('/api/shopping/setup', {'per_purchase_cents': 5000, 'monthly_cents': 20000, 'days': 7, 'automatic': True, 'persona': 'books'})
            session = post('/api/ideas', {'mode': 'gift', 'request_key': secrets.token_hex(12), 'buy_automatically': False})
            reply = post('/api/ideas/choose', {'session_id': session['id'], 'sku': session['ideas'][0]['sku'], 'buy_automatically': True, 'owner_review_if_over': True})
            self.assertIn('error', reply)  # fake keys are refused by PayPal Sandbox
        finally:
            proc.terminate(); proc.wait(timeout=5)
        seen = log.read_text() + ''.join(replies)
        for p in (Path(self.tmp.name) / 'data').rglob('*'):
            if p.is_file():
                seen += p.read_bytes().decode(errors='ignore')
        self.assertEqual(self.secrets_in(seen), [])


if __name__ == '__main__':
    unittest.main()
