"""Register one NEW PayPal Sandbox webhook for an isolated ApproveAccept run.

No existing webhook is listed, changed or deleted. This is an outward provider call:
run only in the root-owned sandbox flow, after choosing the exact HTTPS origin.
"""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import leash

EVENTS = [
    'CHECKOUT.ORDER.APPROVED',
    'PAYMENT.AUTHORIZATION.CREATED',
    'PAYMENT.AUTHORIZATION.VOIDED',
    'PAYMENT.CAPTURE.COMPLETED',
]


def main():
    data = os.environ.get('AA_DATA_DIR', '')
    origin = os.environ.get('APPROVEACCEPT_PUBLIC_BASE_URL', '').rstrip('/')
    if not data or not origin:
        raise SystemExit('AA_DATA_DIR and APPROVEACCEPT_PUBLIC_BASE_URL are required')
    parsed = urlsplit(origin)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise SystemExit('Use one exact HTTPS origin with no path, query or credentials')
    directory = Path(data).resolve()
    if not directory.is_dir():
        raise SystemExit('Fresh AA_DATA_DIR must exist before webhook registration')
    output = directory / 'webhook-id.txt'
    if output.exists():
        raise SystemExit('This run already has a webhook ID; no existing registration was changed')
    url = origin + '/webhooks/paypal'
    result = leash.Sandbox().call('/v1/notifications/webhooks',
                                  {'url': url, 'event_types': [{'name': e} for e in EVENTS]})
    webhook_id = result.get('id', '')
    if not isinstance(webhook_id, str) or not webhook_id:
        raise SystemExit('PayPal Sandbox did not return a webhook ID')
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as handle:
        handle.write(webhook_id + '\n')
    print('Registered new PayPal Sandbox webhook for this run:', webhook_id)
    print('Destination:', url)
    print('Restart the same data directory with LEASH_V2_WEBHOOK_ID set to this ID.')


if __name__ == '__main__':
    main()
