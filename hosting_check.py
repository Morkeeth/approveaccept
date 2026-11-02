#!/usr/bin/env python3
"""Fail closed on outward placeholders, credential-shaped values and the retired product name."""
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent
FILES = ['README.md', 'ENVIRONMENT.md', 'JUDGE-PATH.md', 'render.yaml', 'index.html', 'design/index.html',
         'journey.html', 'inbox.html']
PLACEHOLDER = re.compile(r'(?i)\b(?:FILL[_ -]?ME|TODO|TBD|CHANGEME|EXAMPLE\.COM)\b')
CREDENTIAL = re.compile(r'(?i)(?:client[_-]?secret|api[_-]?key|access[_-]?token)\s*[:=]\s*["\']?[A-Za-z0-9_\-]{20,}')
BANNED_NAME = re.compile(r'(?i)\bLeash\b')

class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip += 1
    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.skip:
            self.skip -= 1
    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

hits = []
for rel in FILES:
    path = ROOT / rel
    if not path.exists():
        hits.append(f'{rel}: missing')
        continue
    source = path.read_text(errors='replace')
    for n, line in enumerate(source.splitlines(), 1):
        if PLACEHOLDER.search(line):
            hits.append(f'{rel}:{n}: placeholder')
        if CREDENTIAL.search(line):
            hits.append(f'{rel}:{n}: credential-shaped value')
        visible_line = re.sub(r'`[^`]*`', '', line) if path.suffix == '.md' else ''
        if visible_line and BANNED_NAME.search(visible_line):
            hits.append(f'{rel}:{n}: retired product name')
    if path.suffix == '.html':
        parser = VisibleText()
        parser.feed(source)
        if BANNED_NAME.search(' '.join(parser.parts)):
            hits.append(f'{rel}: visible retired product name')
if hits:
    print('\n'.join(hits), file=sys.stderr)
    raise SystemExit(1)
print('PASS: outward files contain no placeholders, credential-shaped values or retired product name')
