"""Read one fresh run's PayPal Sandbox order/authorization/capture by ID.

Provider calls are GET only. Never prints OAuth or sandbox credentials.
"""
import json
import os
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import leash


def main():
    if len(sys.argv) != 2 or not sys.argv[1].startswith('BUY'):
        raise SystemExit('Usage: python3 -B connect/sandbox_readback.py BUY_REQUEST_ID')
    data = Path(os.environ.get('AA_DATA_DIR', '')).resolve()
    if 'paypal-judge-fresh-' not in data.name or not (data / 'spend.db').is_file():
        raise SystemExit('Use an isolated paypal-judge-fresh- AA_DATA_DIR with spend.db')
    with sqlite3.connect(data / 'spend.db') as db:
        db.row_factory = sqlite3.Row
        row = db.execute('SELECT id,cents,state,order_id,authorization_id,capture_id FROM requests WHERE id=?',
                         (sys.argv[1],)).fetchone()
    if not row or not row['order_id']:
        raise SystemExit('No PayPal order for this request in the fresh run')
    provider = leash.Sandbox()
    order = provider.call('/v2/checkout/orders/' + row['order_id'], method='GET')
    authorization = (provider.call('/v2/payments/authorizations/' + row['authorization_id'], method='GET')
                     if row['authorization_id'] else {})
    capture = (provider.call('/v2/payments/captures/' + row['capture_id'], method='GET')
               if row['capture_id'] else {})
    unit = (order.get('purchase_units') or [{}])[0]
    amount = (unit.get('amount') or {}).get('value')
    amount_matches = amount is not None and int(Decimal(str(amount)) * 100) == row['cents']
    result = {'mode': 'PayPal Sandbox provider GET; no write', 'request_id': row['id'],
              'local_state': row['state'], 'order_id': row['order_id'],
              'provider_order_status': order.get('status'),
              'authorization_id': row['authorization_id'],
              'provider_authorization_status': authorization.get('status'),
              'capture_id': row['capture_id'],
              'provider_capture_status': capture.get('status'),
              'order_amount_matches_local': amount_matches,
              'provider_order_description': unit.get('description')}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
