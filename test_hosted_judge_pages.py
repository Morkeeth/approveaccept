"""The hosted entrypoint (start-host.sh, the one render.yaml deploys) serves the product a judge sees.

A judge opens the hosted URL, not 127.0.0.1:8780. These tests start the real hosted entrypoint
in substitute mode (no PayPal calls) and drive the same pages the README and the video use:
/inbox and /journey, owner sign-in through the public front, the demo agents, Deny, Surprise me.
Browser steps need Playwright for Python; they skip without it.
"""
import os, signal, socket, subprocess, sys, tempfile, time, unittest, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class HostedJudgePages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = tempfile.TemporaryDirectory(prefix='aa-judge-pages-')
        cls.out = tempfile.TemporaryFile()
        cls.port, cls.backend = free_port(), free_port()
        cls.base = f'http://127.0.0.1:{cls.port}'
        cls.owner = 'judge-pages-owner-' + 'o' * 32
        env = {'PATH': os.environ['PATH'], 'HOME': cls.data.name, 'LEASH_V2_SUBSTITUTE': '1',
               'AA_DATA_DIR': cls.data.name, 'PORT': str(cls.port), 'AA_BACKEND_PORT': str(cls.backend),
               'AA_DESIGN_HOST': '127.0.0.1', 'APPROVEACCEPT_PUBLIC_BASE_URL': cls.base,
               'APPROVEACCEPT_OWNER_TOKEN': cls.owner,
               'APPROVEACCEPT_AGENT_TOKEN': 'judge-pages-agent-' + 'a' * 32, 'APPROVEACCEPT_AGENT_NAME': 'Build agent'}
        cls.proc = subprocess.Popen(['sh', './start-host.sh'], cwd=ROOT, env=env, stdout=cls.out,
                                    stderr=cls.out, start_new_session=True)
        for _ in range(150):
            try:
                urllib.request.urlopen(cls.base + '/health', timeout=1)
                return
            except OSError:
                if cls.proc.poll() is not None:
                    break
                time.sleep(.1)
        cls.out.seek(0)
        failure = cls.out.read().decode()
        cls.tearDownClass()
        raise AssertionError('Hosted entrypoint failed: ' + failure)

    @classmethod
    def tearDownClass(cls):
        if cls.proc.poll() is None:
            os.killpg(cls.proc.pid, signal.SIGTERM)
        cls.proc.wait(timeout=5)
        cls.out.close()
        cls.data.cleanup()

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as r:
            return r.status, r.headers.get('Content-Type', ''), r.read().decode()

    def test_inbox_and_journey_are_served_by_the_hosted_front(self):
        for path, marker in (('/inbox', 'Your agents ask.'), ('/journey', 'Tap a mood.')):
            status, ctype, body = self.get(path)
            self.assertEqual(status, 200, path)
            self.assertIn('text/html', ctype, path)
            self.assertIn(marker, body, path)

    def test_root_still_serves_the_page_it_served(self):
        status, _, body = self.get('/')
        self.assertEqual(status, 200)
        self.assertIn('ApproveAccept', body)

    @unittest.skipIf(sync_playwright is None, 'Playwright for Python not installed')
    def test_judge_path_through_the_public_front(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(self.base + '/inbox')
            # Anonymous visitors must be able to sign in: the gate is shown, not a sample that hides it.
            page.wait_for_selector('#gate:not([hidden])', timeout=10000)
            # A judge without the owner key is told where the full path runs, with no key needed.
            page.wait_for_selector('#gate-public:not([hidden])', timeout=10000)
            self.assertIn('github.com/Morkeeth/approveaccept', page.inner_html('#gate-public'))
            page.fill('#key', self.owner)
            page.press('#key', 'Enter')
            page.wait_for_selector('#app:not([hidden])', timeout=10000)
            # The demo agents buy through the public front, as an agent elsewhere would.
            env = {k: v for k, v in os.environ.items() if not k.startswith(('APPROVEACCEPT_', 'AA_', 'LEASH_V2_'))}
            env.update(AA_URL=self.base, APPROVEACCEPT_OWNER_TOKEN=self.owner, HOME=self.data.name)
            run = subprocess.run([sys.executable, '-B', str(ROOT / 'connect' / 'demo_agents.py')], cwd=ROOT,
                                 env=env, capture_output=True, text=True, timeout=180)
            self.assertEqual(run.returncode, 0, run.stderr[-800:])
            self.assertEqual(run.stdout.count('"state": "captured"'), 2, run.stdout)
            self.assertEqual(run.stdout.count('"state": "authorized"'), 1, run.stdout)
            page.wait_for_selector('[data-deny]', timeout=10000)
            page.click('[data-deny]')
            page.wait_for_function("!document.querySelector('[data-deny]')", timeout=10000)
            # One place for the month: both agents, with the paid total and the PayPal check line.
            page.wait_for_function("document.querySelector('#month').innerText.includes('GrokBot')", timeout=10000)
            self.assertIn('Claude Code', page.inner_text('#month'))
            self.assertIn('Not checked with PayPal yet', page.inner_text('#check'))
            # Refund sits behind a tap on the row, then needs a second tap.
            self.assertEqual(page.locator('[data-refund]').count(), 0)
            page.locator('[data-row]').first.click()
            page.locator('[data-refund]').first.click()
            self.assertIn('Tap again to refund', page.inner_text('.undo.armed'))
            page.locator('.undo.armed').click()
            page.wait_for_function("document.querySelector('#paid').innerText.includes('Refunded')", timeout=10000)
            self.assertIn('refunded', page.inner_text('#month'))
            # Surprise me on the hosted journey page, same session.
            page.goto(self.base + '/journey')
            page.wait_for_selector('#app:not([hidden])', timeout=10000)
            page.click('button[data-mode=surprise]')
            page.wait_for_selector('button[data-yes]', timeout=60000)
            page.click('button[data-yes]')
            page.wait_for_selector('#receipt:not([hidden])', timeout=60000)
            self.assertIn('SUB', page.inner_text('#receipt'))
            browser.close()


if __name__ == '__main__':
    unittest.main()
