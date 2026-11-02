"""Stranger run 1 (GrokBot, Debian 13, 2 Nov 2026): one test per finding. Each fails on the code it ran."""
import json, os, re, secrets, socket, stat, subprocess, sys, tempfile, time, unittest, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p


def clean_env(**more):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('APPROVEACCEPT_', 'PAYPAL_', 'LEASH_V2_', 'AA_')) and not k.endswith('_API_KEY')}
    env.update(more); return env


class NoPayPalMode(unittest.TestCase):
    """Findings 1, 2, 3: one command, one port, one page, demo agents without copying a key by hand."""
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); cls.home = Path(cls.tmp.name) / 'aa'
        cls.port = free_port(); cls.base = f'http://127.0.0.1:{cls.port}'
        cls.log = (Path(cls.tmp.name) / 'out.log').open('w+')
        cls.proc = subprocess.Popen(['sh', str(ROOT / 'journey.sh'), '--no-paypal'], cwd=ROOT, stdout=cls.log, stderr=cls.log,
                                    env=clean_env(APPROVEACCEPT_HOME=str(cls.home), AA_PORT=str(cls.port)))
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.base + '/health', timeout=1).read(); break
            except Exception:
                if cls.proc.poll() is not None:
                    break
                time.sleep(.1)

    @classmethod
    def tearDownClass(cls):
        if cls.proc.poll() is None:
            cls.proc.terminate(); cls.proc.wait(timeout=5)
        cls.log.close(); cls.tmp.cleanup()

    def output(self):
        self.log.flush(); self.log.seek(0); return self.log.read()

    def test_1_no_paypal_mode_starts_without_keys_and_prints_a_working_owner_key(self):
        self.assertIsNone(self.proc.poll(), self.output())
        health = json.load(urllib.request.urlopen(self.base + '/health', timeout=5))
        self.assertEqual(health['mode'], 'substitute')
        key_file = self.home / 'no-paypal.env'
        self.assertEqual(stat.S_IMODE(key_file.stat().st_mode), 0o600)
        key = re.search(r'Owner key for sign-in: (\S+)', self.output()).group(1)
        req = urllib.request.Request(self.base + '/api/session', json.dumps({'token': key}).encode(),
                                     {'Content-Type': 'application/json', 'Origin': self.base})
        self.assertEqual(urllib.request.urlopen(req, timeout=5).status, 200)

    def test_2_both_modes_use_port_8780_and_print_the_inbox_address(self):
        self.assertIn(f'http://127.0.0.1:{self.port}/inbox', self.output())
        script = (ROOT / 'journey.sh').read_text()
        self.assertIn(': "${AA_PORT:=8780}"', script)
        self.assertLess(script.index(': "${AA_PORT:=8780}"'), script.index('if [ "${1:-}" = "--no-paypal" ]'))

    def test_3_demo_agents_finds_the_owner_key_and_runs_against_no_paypal_mode(self):
        r = subprocess.run([sys.executable, '-B', str(ROOT / 'connect' / 'demo_agents.py')], cwd=ROOT, capture_output=True, text=True,
                           timeout=180, env=clean_env(APPROVEACCEPT_HOME=str(self.home), AA_URL=self.base))
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        states = [json.loads(l)['state'] for l in r.stdout.splitlines() if l.startswith('{')]
        self.assertEqual(states, ['captured', 'captured', 'authorized'])


class HeldRequests(unittest.TestCase):
    """Findings 4 and 5, against an isolated local stand-in."""
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); cls.port = free_port(); cls.base = f'http://127.0.0.1:{cls.port}'
        cls.owner = 'synthetic-stranger-owner-' + 32 * 'o'
        cls.log = (Path(cls.tmp.name) / 'server.log').open('w')
        cls.proc = subprocess.Popen([sys.executable, '-B', str(ROOT / 'app.py')], cwd=ROOT, stdout=cls.log, stderr=cls.log,
                                    env=clean_env(LEASH_V2_SUBSTITUTE='1', LEASH_V2_DATA=cls.tmp.name, LEASH_V2_PORT=str(cls.port),
                                                  APPROVEACCEPT_PASSKEY_ORIGIN='https://approve.example.test', APPROVEACCEPT_OWNER_TOKEN=cls.owner))
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.base + '/health', timeout=1).read(); break
            except Exception:
                time.sleep(.05)
        cls.key = cls.req('/api/agent-key', {'agent': 'GrokBot'})[1]['key']
        cls.grant = {'agent': 'GrokBot', 'merchants': ['Sandbox travel'], 'categories': ['travel'],
                     'per_purchase_cents': 5000, 'monthly_cents': 20000, 'days': 7}
        cls.req('/api/allowance', cls.grant)
        cls.held = cls.req('/api/purchase', {'agent': 'GrokBot', 'title': 'Flight Paris to Lisbon, economy', 'merchant': 'Sandbox travel',
                                             'category': 'travel', 'cents': 8900, 'why': 'Meeting', 'task': 'Travel',
                                             'request_key': secrets.token_hex(12)}, cls.key)[1]

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate(); cls.proc.wait(timeout=5); cls.log.close(); cls.tmp.cleanup()

    @classmethod
    def req(cls, path, data=None, token=None):
        r = urllib.request.Request(cls.base + path, None if data is None else json.dumps(data).encode(),
                                   {'Content-Type': 'application/json', 'Origin': cls.base, 'Authorization': 'Bearer ' + (token or cls.owner)})
        try:
            with urllib.request.urlopen(r, timeout=20) as x: return x.status, json.load(x)
        except urllib.error.HTTPError as e: return e.code, json.load(e)

    def test_4_raising_a_limit_names_the_request_still_held_and_never_captures_it(self):
        self.assertEqual(self.held['state'], 'authorized')
        code, r = self.req('/api/allowance', dict(self.grant, per_purchase_cents=9000))
        self.assertEqual(code, 200)
        self.assertEqual(r['still_held'], [self.held['id']])
        self.assertIn('next request', r['note'])
        state = next(p for p in self.req('/api/state')[1]['proposals'] if p['id'] == self.held['id'])
        self.assertEqual(state['money']['state'], 'authorized')
        inbox = (ROOT / 'inbox.html').read_text()
        self.assertIn('for next time', inbox); self.assertIn('still_held', inbox)

    def test_5_the_held_request_shows_this_agents_own_categories(self):
        code, status = self.req('/api/agent/status?id=' + self.held['id'], token=self.key)
        self.assertEqual(code, 200)
        line = next(l for l in status['context']['policy']['lines'] if l.startswith('Allowed categories'))
        self.assertEqual(line, 'Allowed categories: travel. Other categories are blocked.')


class Docs(unittest.TestCase):
    def setUp(self):
        self.readme = (ROOT / 'README.md').read_text()

    def test_6_readme_has_one_numbered_path_per_mode_and_no_keychain_contradiction(self):
        self.assertNotIn('Keychain', self.readme)
        a = self.readme.index('### Path A. No PayPal account'); b = self.readme.index('### Path B. PayPal Sandbox')
        path_a, path_b = self.readme[a:b], self.readme[b:self.readme.index('### Connect your own agent')]
        for path, start in ((path_a, './journey.sh --no-paypal'), (path_b, './journey.sh')):
            self.assertIn(start, path)
            self.assertIn('http://127.0.0.1:8780/inbox', path)
            step = re.search(r'\n\d\. In a second terminal', path)
            self.assertIsNotNone(step, 'demo agents must be a numbered step')
            self.assertIn('connect/demo_agents.py', path[step.start():step.start() + 300])
        self.assertIn('**Start here.**', self.readme)

    def test_7_playwright_is_an_optional_dev_dependency_and_check_stamps_says_so(self):
        self.assertIn('Optional dev dependency: [Playwright]', self.readme)
        r = subprocess.run(['node', str(ROOT / 'design' / 'check-stamps.cjs')], capture_output=True, text=True, timeout=60,
                           env=dict(os.environ, APPROVEACCEPT_FORCE_NO_PLAYWRIGHT='1'))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('SKIPPED rendered check', r.stdout); self.assertIn('optional dev dependency', r.stdout)
        self.assertIn('(source only)', r.stdout)


if __name__ == '__main__':
    unittest.main()
