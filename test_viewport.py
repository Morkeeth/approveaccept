"""Rendered owner-page width regression test.

Run outside a restricted macOS sandbox with:
  python3 -B -m unittest -v test_viewport
"""
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent


class PageServer(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            body, kind = (HERE / 'index.html').read_bytes(), 'text/html; charset=utf-8'
        elif self.path == '/api/state':
            body = json.dumps({
                'spend_rules': [], 'generic_requests': [], 'subscriptions': [],
                'request_overview': {
                    'counts': {'needs_me': 1, 'auto_approved': 1, 'blocked': 1},
                    'next_action_id': 'BUY1',
                    'items': [{'id': 'BUY1', 'rank': 1, 'bucket': 'needs_me',
                               'agent': 'Build agent', 'title': 'API credit pack',
                               'amount': 'EUR 48.00', 'merchant': 'API Foundry',
                               'urgency': 'Decide now', 'risk': 'High risk',
                               'allowance': 'Outside allowance', 'recurring': False,
                               'why': 'Needed for a customer import.', 'task': 'Finish import',
                               'state': 'authorized'}],
                },
                'allowances': [{
                    'agent': 'Build agent', 'status': 'active',
                    'per_purchase_cents': 3000, 'monthly_cents': 12000,
                    'used_cents': 1800, 'remaining_cents': 10200,
                    'merchants': ['API Foundry', 'Developer Tools'],
                    'expires_at': '2026-11-23T00:39:00Z',
                }],
            }).encode()
            kind = 'application/json'
        else:
            body, kind = b'not found', 'text/plain'
            self.send_response(404)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class TestOwnerViewport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), PageServer)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_allowance_page_has_no_horizontal_scroll_at_390_by_844(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest('Playwright is not installed')
        with sync_playwright() as playwright:
            try:
                launch = {'headless': True}
                if os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH'):
                    launch['executable_path'] = os.environ['PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH']
                browser = playwright.chromium.launch(**launch)
            except Exception as exc:
                if os.environ.get('AA_REQUIRE_BROWSER') == '1':
                    raise
                self.skipTest('Chromium cannot start in this environment: ' + str(exc).splitlines()[0])
            page = browser.new_page(viewport={'width': 390, 'height': 844}, device_scale_factor=1)
            page.goto(f'http://127.0.0.1:{self.server.server_port}', wait_until='networkidle')
            size = page.evaluate('({innerWidth, scrollWidth: document.documentElement.scrollWidth})')
            page.locator('#shopping-activity > summary').click()
            panel = page.locator('section.overview').bounding_box()
            action = page.locator('#review').inner_text()
            browser.close()
        self.assertEqual(size, {'innerWidth': 390, 'scrollWidth': 390})
        self.assertLessEqual(round(panel['x'] + panel['width']), 390)
        self.assertEqual(action, 'Review top request')


if __name__ == '__main__':
    unittest.main()
