"""Demo video names (owner ruling, 2 Nov 2026): the video shows no third-party trademarks.

--video-names runs the demo with generic agent names, which reach the inbox and the PayPal
order description; APPROVEACCEPT_VIDEO_NAMES=1 shows "an AI model" instead of the model name.
Without them, the real names stay.
"""
import json, os, socket, subprocess, sys, tempfile, time, unittest, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OWNER = 'synthetic-video-owner-' + 32 * 'o'
BRANDS = ('Claude Code', 'GrokBot', 'claude-opus', 'Claude', 'Grok')


def clean_env(**more):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('APPROVEACCEPT_', 'PAYPAL_', 'LEASH_V2_', 'AA_')) and not k.endswith('_API_KEY')}
    env.update(more); return env


class Server:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        s = socket.socket(); s.bind(('127.0.0.1', 0)); self.port = s.getsockname()[1]; s.close()
        self.base = f'http://127.0.0.1:{self.port}'
        self.log = (Path(self.tmp.name) / 'server.log').open('w')
        self.proc = subprocess.Popen([sys.executable, '-B', str(ROOT / 'app.py')], cwd=ROOT, stdout=self.log, stderr=self.log,
                                     env=clean_env(LEASH_V2_SUBSTITUTE='1', LEASH_V2_DATA=self.tmp.name, LEASH_V2_PORT=str(self.port),
                                                   APPROVEACCEPT_PASSKEY_ORIGIN='https://approve.example.test', APPROVEACCEPT_OWNER_TOKEN=OWNER))
        for _ in range(100):
            try:
                urllib.request.urlopen(self.base + '/health', timeout=1).read(); break
            except Exception:
                time.sleep(.05)

    def demo(self, *args):
        return subprocess.run([sys.executable, '-B', str(ROOT / 'connect' / 'demo_agents.py'), *args], cwd=ROOT, capture_output=True,
                              text=True, timeout=180, env=clean_env(AA_URL=self.base, APPROVEACCEPT_OWNER_TOKEN=OWNER))

    def state(self):
        r = urllib.request.Request(self.base + '/api/state', headers={'Authorization': 'Bearer ' + OWNER})
        return json.load(urllib.request.urlopen(r, timeout=10))

    def close(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.log.close(); self.tmp.cleanup()


class VideoNames(unittest.TestCase):
    def test_video_names_reach_the_inbox_and_the_paypal_description_with_no_brand(self):
        srv = Server()
        try:
            r = srv.demo('--video-names')
            self.assertEqual(r.returncode, 0, r.stderr[-400:])
            state = srv.state()
            buys = [p for p in state['proposals'] if p['id'].startswith('BUY')]
            self.assertEqual(sorted({p['agent'] for p in buys}), ['Coding agent', 'Travel agent'])
            purposes = sorted(p['money']['purpose'] for p in buys if p['money'])
            self.assertIn('Domain name .com, 1 year - sent by Coding agent', purposes)
            self.assertIn('Flight Paris to Lisbon, economy - sent by Travel agent', purposes)
            shown = r.stdout + json.dumps(buys) + json.dumps(state.get('allowances')) + json.dumps(state.get('agent_keys'))
            self.assertEqual([b for b in BRANDS if b in shown], [])
        finally:
            srv.close()

    def test_without_the_flag_the_real_names_stay(self):
        srv = Server()
        try:
            self.assertEqual(srv.demo().returncode, 0)
            agents = {p['agent'] for p in srv.state()['proposals'] if p['id'].startswith('BUY')}
            self.assertEqual(agents, {'Claude Code', 'GrokBot'})
        finally:
            srv.close()

    def test_ai_label_hides_the_model_name_only_in_video_mode(self):
        probe = ('import json,types,catalog_ai as c\n'
                 'class F:\n'
                 '  def __init__(s): s.beta=types.SimpleNamespace(messages=types.SimpleNamespace(create=s.create))\n'
                 '  def create(s,**k): return types.SimpleNamespace(stop_reason="end_turn",model="claude-opus-5-5",content=[types.SimpleNamespace(type="text",text=json.dumps({"ranked":[{"sku":"a","preference_quote":"books","facts":[{"field":"tags","quote":"book"}]}]}))])\n'
                 'r,m=c.rank([dict(sku="a",title="Signed poetry book",cents=3200,tags="book")],"books","gift","i",client=F())\n'
                 'print(json.dumps([m["model"],m["label"]]))')
        out = lambda env: json.loads(subprocess.run([sys.executable, '-B', '-c', probe], cwd=ROOT, capture_output=True, text=True,
                                                    env=clean_env(**env)).stdout)
        self.assertEqual(out({'APPROVEACCEPT_VIDEO_NAMES': '1'}), ['an AI model', 'Ranked by an AI model with your key.'])
        self.assertEqual(out({})[0], 'claude-opus-5-5')


if __name__ == '__main__':
    unittest.main()
