"""Register (or replace) the one ApproveAccept sandbox webhook on a public URL. Sandbox only.
Usage: python3 -B connect/webhook_register.py https://<name>.trycloudflare.com/webhooks/paypal
Prints the webhook id and URL only, never a token. Deletes the webhook this script made last time first,
because a quick tunnel gets a new URL on every start."""
import json, os, sys, urllib.request, urllib.error
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import leash

LAST = Path(os.environ.get(
    'APPROVEACCEPT_WEBHOOK_ID_FILE',
    Path.home() / '.config' / 'approveaccept' / 'webhook-id.txt',
))
LAST.parent.mkdir(parents=True, exist_ok=True)
EVENTS = ['CHECKOUT.ORDER.APPROVED', 'PAYMENT.AUTHORIZATION.CREATED', 'PAYMENT.AUTHORIZATION.VOIDED', 'PAYMENT.CAPTURE.COMPLETED']
sb = leash.Sandbox()


def call(path, data=None, method='GET'):
    req = urllib.request.Request(sb.BASE + path, json.dumps(data).encode() if data is not None else None,
                                 {'Authorization': 'Bearer ' + sb.token, 'Content-Type': 'application/json'}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        b = json.loads(e.read() or b'{}')
        return e.code, {k: b.get(k) for k in ('name', 'message', 'details')}


url = sys.argv[1]
assert url.startswith('https://') and url.endswith('/webhooks/paypal'), 'want https://.../webhooks/paypal'
if LAST.exists():
    print('delete old', LAST.read_text().strip(), call('/v1/notifications/webhooks/' + LAST.read_text().strip(), method='DELETE')[0])
s, w = call('/v1/notifications/webhooks', {'url': url, 'event_types': [{'name': n} for n in EVENTS]}, 'POST')
if s != 201:
    sys.exit(f'create failed {s} {json.dumps(w)[:300]}')
LAST.write_text(w['id'])
print(w['id'])
