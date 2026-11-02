#!/usr/bin/env python3
"""Capture the local guided dashboard and phone decision at judge widths."""
import argparse
import json
import os
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright


parser = argparse.ArgumentParser()
parser.add_argument('--base', default='http://127.0.0.1:8879')
parser.add_argument('--out', type=Path, default=Path('../evidence'))
args = parser.parse_args()
args.out.mkdir(parents=True, exist_ok=True)

request = urllib.request.Request(args.base + '/api/demo/start', b'{}', {'Content-Type': 'application/json'})
with urllib.request.urlopen(request, timeout=20) as response:
    session = json.load(response)

with sync_playwright() as playwright:
    launch = {'headless': True}
    executable = os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH')
    if executable:
        launch['executable_path'] = executable
    browser = playwright.chromium.launch(**launch)
    for width, height in ((1440, 900), (390, 844)):
        page = browser.new_page(viewport={'width': width, 'height': height}, device_scale_factor=1)
        page.goto(args.base, wait_until='networkidle')
        page.screenshot(path=args.out / f'dashboard-{width}.png', full_page=False)
        page.goto(session['approval_url'], wait_until='networkidle')
        page.screenshot(path=args.out / f'phone-{width}.png', full_page=False)
        page.close()
    browser.close()

print(json.dumps({'out': str(args.out.resolve()), 'held_id': session['held_id'],
                  'mode': session['payment_mode'], 'reused': session['reused']}))
