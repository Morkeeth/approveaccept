#!/usr/bin/env python3
"""Read every payment back through PayPal's own MCP server (@paypal/mcp), then reconcile it.

    python3 connect/paypal_mcp_record.py          (with a Sandbox run in AA_DATA_DIR or ~/.config/approveaccept/data)
    python3 connect/paypal_mcp_record.py --json

ApproveAccept creates and decides the PayPal holds itself (Orders v2, AUTHORIZE). This tool is
the independent record: for each request that reached PayPal it starts PayPal's official MCP
server with only the orders.get tool, calls get_order, and checks what PayPal says against the
local state: the capture or authorization status, the amount, and the agent's name in the
order description. A request stopped by the spend rules never reached PayPal and is not listed.

Sandbox only. The access token is minted from the same Sandbox keys the app uses, passed to the
MCP server through its environment only (never argv, never printed), and dropped on exit.
Needs node and npx. The package is pinned: @paypal/mcp@1.8.1.
"""
import json, os, shlex, sqlite3, subprocess, sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PINNED = '@paypal/mcp@1.8.1'
TOOLS = '--tools=orders.get'

# local state -> (payments key at PayPal, the status PayPal must report)
EXPECT = {'captured': ('captures', 'COMPLETED'),
          'authorized': ('authorizations', ('CREATED', 'PENDING')),
          'voided': ('authorizations', 'VOIDED'),
          'refunded': ('captures', ('REFUNDED', 'PARTIALLY_REFUNDED'))}


def default_command():
    return [os.environ.get('APPROVEACCEPT_NPX', 'npx'), '-y', PINNED]


def data_dir():
    if os.environ.get('AA_DATA_DIR'):
        return Path(os.environ['AA_DATA_DIR'])
    home = Path(os.environ.get('APPROVEACCEPT_HOME') or Path.home() / '.config' / 'approveaccept')
    return home / 'data'


def load_rows(data):
    db_path = Path(data) / 'spend.db'
    if not db_path.is_file():
        raise SystemExit(f'No spend.db in {data}. Run the app and the demo agents first.')
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute('SELECT id, agent, cents, purpose, state, order_id, authorization_id, capture_id '
                          'FROM requests WHERE order_id IS NOT NULL ORDER BY rowid').fetchall()
    return [dict(r) for r in rows]


class PayPalMCP:
    """One stdio session with PayPal's MCP server per batch of get_order calls."""

    def __init__(self, command, token, environment='SANDBOX'):
        if environment != 'SANDBOX':
            raise SystemExit('Sandbox only: this record never reads Live PayPal.')
        self.command, self.token, self.environment = list(command), token, environment

    def get_orders(self, order_ids):
        msgs = [{'jsonrpc': '2.0', 'id': 0, 'method': 'initialize',
                 'params': {'protocolVersion': '2025-06-18', 'capabilities': {},
                            'clientInfo': {'name': 'approveaccept-record', 'version': '1'}}},
                {'jsonrpc': '2.0', 'method': 'notifications/initialized'}]
        msgs += [{'jsonrpc': '2.0', 'id': i + 1, 'method': 'tools/call',
                  'params': {'name': 'get_order', 'arguments': {'id': oid}}} for i, oid in enumerate(order_ids)]
        env = {k: os.environ[k] for k in ('PATH', 'HOME', 'TMPDIR', 'TEMP', 'TMP', 'SYSTEMROOT') if k in os.environ}
        env.update(PAYPAL_ACCESS_TOKEN=self.token, PAYPAL_ENVIRONMENT=self.environment)
        proc = subprocess.run(self.command + [TOOLS], input='\n'.join(json.dumps(m) for m in msgs) + '\n',
                              capture_output=True, text=True, env=env, timeout=240)
        out = {}
        for line in proc.stdout.splitlines():
            try:
                reply = json.loads(line)
            except ValueError:
                continue
            n = reply.get('id')
            if not isinstance(n, int) or n < 1 or n > len(order_ids):
                continue
            text = ((reply.get('result') or {}).get('content') or [{}])[0].get('text', '')
            try:
                body = json.loads(text)
            except ValueError:
                body = {'ok': False, 'message': 'unreadable reply'}
            out[order_ids[n - 1]] = body
        return out


def check(row, order):
    """Compare one local request with PayPal's order. Returns (match, why)."""
    if not order or order.get('ok') is False or 'purchase_units' not in order:
        return False, 'not read from PayPal: ' + str((order or {}).get('message', 'no reply'))[:80]
    if order.get('id') != row['order_id']:
        return False, 'order id differs at PayPal'
    unit = order['purchase_units'][0]
    value = (unit.get('amount') or {}).get('value')
    if value is None or int(Decimal(str(value)) * 100) != row['cents']:
        return False, f'amount at PayPal is {value}, local is {row["cents"] / 100:.2f}'
    if not str(unit.get('description', '')).endswith('sent by ' + row['agent']):
        return False, 'agent name not in the PayPal order description'
    expect = EXPECT.get(row['state'])
    if not expect:
        return False, f'local state {row["state"]} has no PayPal expectation'
    key, status = expect
    wanted = row['capture_id'] if key == 'captures' else row['authorization_id']
    items = (unit.get('payments') or {}).get(key) or []
    found = next((x for x in items if x.get('id') == wanted), None)
    if not found:
        return False, f'{key[:-1]} {wanted} not on the PayPal order'
    ok = found.get('status') in (status if isinstance(status, tuple) else (status,))
    return ok, ('PayPal says ' + found.get('status', '?')) if ok else f'{key[:-1]} is {found.get("status")} at PayPal'


def reconcile(rows, mcp):
    orders = mcp.get_orders([r['order_id'] for r in rows]) if rows else {}
    results = []
    for r in rows:
        match, why = check(r, orders.get(r['order_id']))
        results.append({'request': r['id'], 'agent': r['agent'], 'eur': r['cents'] / 100, 'local_state': r['state'],
                        'order_id': r['order_id'], 'match': match, 'why': why})
    return results


def summarize(results):
    s = {}
    for r in results:
        a = s.setdefault(r['agent'], {'paid_cents': 0, 'held_cents': 0, 'voided_cents': 0, 'refunded_cents': 0,
                                      'count': 0, 'all_match': True})
        key = {'captured': 'paid_cents', 'authorized': 'held_cents', 'voided': 'voided_cents',
               'refunded': 'refunded_cents'}.get(r['local_state'])
        if key:
            a[key] += round(r['eur'] * 100)
        a['count'] += 1
        a['all_match'] = a['all_match'] and r['match']
    return s


def save_check(data, results):
    """Leave the result beside spend.db so the inbox can say when PayPal last agreed, and about what."""
    import datetime
    out = {'at': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
           'source': 'PayPal MCP ' + PINNED + ' get_order, Sandbox',
           'matched': sum(1 for r in results if r['match']), 'total': len(results),
           'states': {r['request']: r['local_state'] for r in results}, 'by_agent': summarize(results)}
    path = Path(data) / 'paypal-record.json'
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(out, indent=1))
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    return out


def render(results):
    lines = ['Record read through PayPal MCP (@paypal/mcp get_order), PayPal Sandbox', '']
    for r in results:
        lines.append(f'{"OK " if r["match"] else "NO "} {r["agent"]:<12} EUR {r["eur"]:>7.2f}  {r["local_state"]:<10} {r["why"]}')
    lines.append('')
    for agent, a in summarize(results).items():
        lines.append(f'{agent:<12} paid EUR {a["paid_cents"] / 100:.2f} · held EUR {a["held_cents"] / 100:.2f} · '
                     f'released EUR {a["voided_cents"] / 100:.2f} · refunded EUR {a["refunded_cents"] / 100:.2f} · '
                     f'{"matches PayPal" if a["all_match"] else "MISMATCH"}')
    ok = sum(r['match'] for r in results)
    lines.append(f'\n{ok} of {len(results)} payments match PayPal.')
    return '\n'.join(lines)


def load_sandbox_config():
    """Read only documented Sandbox settings as data, never execute a shell file."""
    home = Path(os.environ.get('APPROVEACCEPT_HOME') or Path.home() / '.config' / 'approveaccept')
    config = home / 'sandbox.env'
    allowed = {'APPROVEACCEPT_PAYPAL_SANDBOX_CLIENT_ID', 'APPROVEACCEPT_PAYPAL_SANDBOX_CLIENT_SECRET'}
    if config.is_file():
        for line in config.read_text().splitlines():
            parts = shlex.split(line, comments=True)
            if len(parts) == 2 and parts[0] == 'export' and '=' in parts[1]:
                key, value = parts[1].split('=', 1)
                if key in allowed:
                    os.environ.setdefault(key, value)


def main():
    sys.path.insert(0, str(ROOT))
    load_sandbox_config()
    import leash  # environment or saved BYOK keys first, then macOS Keychain
    rows = load_rows(data_dir())
    results = reconcile(rows, PayPalMCP(default_command(), leash.Sandbox().token))
    save_check(data_dir(), results)
    if '--json' in sys.argv[1:]:
        print(json.dumps({'source': 'PayPal MCP ' + PINNED + ' get_order, Sandbox', 'results': results,
                          'by_agent': summarize(results)}, indent=1))
    else:
        print(render(results))
    return 0 if results and all(r['match'] for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
