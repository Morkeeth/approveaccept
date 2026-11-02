#!/usr/bin/env python3
"""Return rendered no-stamp evidence for check-stamps.cjs."""
import json
import os
import sys

from playwright.sync_api import sync_playwright


with sync_playwright() as playwright:
    launch = {'headless': True}
    executable = os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH')
    if executable:
        launch['executable_path'] = executable
    browser = playwright.chromium.launch(**launch)
    page = browser.new_page()
    page.goto(sys.argv[1], wait_until='networkidle')
    result = page.evaluate("""() => ({
      classes: [...document.querySelectorAll('*')].flatMap(e => [...e.classList]).filter(c => /stamp/i.test(c)),
      text: (document.body.innerText.match(/\\S*stamp\\S*/gi) || []),
    })""")
    browser.close()
print(json.dumps(result))
