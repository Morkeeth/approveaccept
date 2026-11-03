"""PayPal's own MCP server as the record: every local payment is read back through @paypal/mcp get_order.

Offline: a stub MCP server stands in for @paypal/mcp and answers get_order from a fixture.
Set APPROVEACCEPT_TEST_NETWORK=1 with a real Sandbox run in AA_DATA_DIR to also read the
real orders through the real PayPal MCP package (needs node and npx).
"""
import json, os, secrets, sqlite3, subprocess, sys, tempfile, textwrap, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'connect'))
import paypal_mcp_record as rec

STUB = textwrap.dedent('''
    import json, os, sys
    orders = json.load(open(os.environ['STUB_ORDERS']))
    seen = {'argv': sys.argv[1:], 'token': os.environ.get('PAYPAL_ACCESS_TOKEN'),
            'env': os.environ.get('PAYPAL_ENVIRONMENT'), 'env_names': sorted(os.environ)}
    open(os.environ['STUB_SEEN'], 'w').write(json.dumps(seen))
    for line in sys.stdin:
        m = json.loads(line)
        if 'id' not in m:
            continue
        if m['method'] == 'initialize':
            out = {'protocolVersion': '2025-06-18', 'capabilities': {}, 'serverInfo': {'name': 'stub', 'version': '1'}}
        elif m['method'] == 'tools/call' and m['params']['name'] == 'get_order':
            oid = m['params']['arguments']['id']
            body = orders.get(oid, {'ok': False, 'status': 404, 'code': 'PAYPAL_API_HTTP_ERROR', 'message': 'not found'})
            out = {'content': [{'type': 'text', 'text': json.dumps(body)}]}
        else:
            out = {}
        print(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': out}), flush=True)
''')


def order(oid, desc, cents, captures=(), auths=()):
    value = f'{cents / 100:.2f}'
    pay = {}
    if captures:
        pay['captures'] = [{'id': cid, 'status': st, 'amount': {'currency_code': 'EUR', 'value': value}} for cid, st in captures]
    if auths:
        pay['authorizations'] = [{'id': aid, 'status': st, 'amount': {'currency_code': 'EUR', 'value': value}} for aid, st in auths]
    return {'id': oid, 'intent': 'AUTHORIZE', 'status': 'COMPLETED',
            'purchase_units': [{'description': desc, 'amount': {'currency_code': 'EUR', 'value': value}, 'payments': pay}]}


ROWS = [  # id, agent, cents, purpose, state, order, auth, capture
    ('BUY1', 'Claude Code', 1200, 'Domain name .com, 1 year - sent by Claude Code', 'captured', 'ORDER00000000000A1', 'AUTH1', 'CAP1'),
    ('BUY2', 'Codex', 2000, 'Hosting plan, Pro, 1 month - sent by Codex', 'captured', 'ORDER00000000000A2', 'AUTH2', 'CAP2'),
    ('BUY3', 'GrokBot', 8900, 'Flight Paris to Lisbon, economy - sent by GrokBot', 'authorized', 'ORDER00000000000A3', 'AUTH3', None),
    ('BUY4', 'GrokBot', 21000, 'Hotel in Lisbon, 2 nights - sent by GrokBot', 'voided', 'ORDER00000000000A4', 'AUTH4', None),
]


def fixture():
    return {
        'ORDER00000000000A1': order('ORDER00000000000A1', ROWS[0][3], 1200, captures=[('CAP1', 'COMPLETED')], auths=[('AUTH1', 'CAPTURED')]),
        'ORDER00000000000A2': order('ORDER00000000000A2', ROWS[1][3], 2000, captures=[('CAP2', 'COMPLETED')], auths=[('AUTH2', 'CAPTURED')]),
        'ORDER00000000000A3': order('ORDER00000000000A3', ROWS[2][3], 8900, auths=[('AUTH3', 'CREATED')]),
        'ORDER00000000000A4': order('ORDER00000000000A4', ROWS[3][3], 21000, auths=[('AUTH4', 'VOIDED')]),
    }


class Record(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); t = Path(self.tmp.name)
        self.stub = t / 'stub_mcp.py'; self.stub.write_text(STUB)
        self.orders = t / 'orders.json'; self.seen = t / 'seen.json'
        self.token = 'A21TESTTOKEN' + secrets.token_hex(16)
        self.data = t / 'data'; self.data.mkdir()
        with sqlite3.connect(self.data / 'spend.db') as db:
            db.execute('CREATE TABLE requests (id TEXT, agent TEXT, merchant TEXT, cents INT, purpose TEXT, month TEXT, '
                       'state TEXT, order_id TEXT, authorization_id TEXT, capture_id TEXT, approval_url TEXT, reason TEXT)')
            db.executemany('INSERT INTO requests VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                           [(r[0], r[1], 'Sandbox', r[2], r[3], '2026-11', r[4], r[5], r[6], r[7], None, None) for r in ROWS])

    def tearDown(self):
        self.tmp.cleanup()

    def mcp(self, orders):
        self.orders.write_text(json.dumps(orders))
        self.stub.write_text(STUB.replace("os.environ['STUB_ORDERS']", repr(str(self.orders))).replace("os.environ['STUB_SEEN']", repr(str(self.seen))))
        return rec.PayPalMCP([sys.executable, '-I', str(self.stub)], self.token)

    def test_every_payment_matches_paypal_through_mcp(self):
        results = rec.reconcile(rec.load_rows(self.data), self.mcp(fixture()))
        self.assertEqual([r['match'] for r in results], [True, True, True, True])
        s = rec.summarize(results)
        self.assertEqual(s['Claude Code']['paid_cents'], 1200)
        self.assertEqual(s['Codex']['paid_cents'], 2000)
        self.assertEqual(s['GrokBot']['held_cents'], 8900)
        self.assertEqual(s['GrokBot']['voided_cents'], 21000)
        self.assertTrue(all(v['all_match'] for v in s.values()))

    def test_refunded_payment_must_be_refunded_at_paypal(self):
        with sqlite3.connect(self.data / 'spend.db') as db:
            db.execute("UPDATE requests SET state='refunded' WHERE id='BUY1'")
        o = fixture(); o['ORDER00000000000A1']['purchase_units'][0]['payments']['captures'][0]['status'] = 'REFUNDED'
        r = rec.reconcile(rec.load_rows(self.data), self.mcp(o))
        self.assertTrue(r[0]['match'], r[0])
        s = rec.summarize(r)['Claude Code']
        self.assertEqual((s['paid_cents'], s['refunded_cents']), (0, 1200))
        o['ORDER00000000000A1']['purchase_units'][0]['payments']['captures'][0]['status'] = 'COMPLETED'
        self.assertFalse(rec.reconcile(rec.load_rows(self.data), self.mcp(o))[0]['match'])

    def test_capture_not_completed_at_paypal_is_a_mismatch(self):
        o = fixture(); o['ORDER00000000000A1']['purchase_units'][0]['payments']['captures'][0]['status'] = 'DECLINED'
        r = rec.reconcile(rec.load_rows(self.data), self.mcp(o))
        self.assertFalse(r[0]['match']); self.assertIn('capture', r[0]['why'])
        self.assertFalse(rec.summarize(r)['Claude Code']['all_match'])

    def test_amount_at_paypal_differs_is_a_mismatch(self):
        o = fixture(); o['ORDER00000000000A2']['purchase_units'][0]['amount']['value'] = '200.00'
        r = rec.reconcile(rec.load_rows(self.data), self.mcp(o))
        self.assertFalse(r[1]['match']); self.assertIn('amount', r[1]['why'])

    def test_agent_name_must_be_in_paypal_description(self):
        o = fixture(); o['ORDER00000000000A3']['purchase_units'][0]['description'] = 'Flight Paris to Lisbon, economy - sent by Codex'
        r = rec.reconcile(rec.load_rows(self.data), self.mcp(o))
        self.assertFalse(r[2]['match']); self.assertIn('agent', r[2]['why'])

    def test_voided_locally_but_still_held_at_paypal_is_a_mismatch(self):
        o = fixture(); o['ORDER00000000000A4']['purchase_units'][0]['payments']['authorizations'][0]['status'] = 'CREATED'
        r = rec.reconcile(rec.load_rows(self.data), self.mcp(o))
        self.assertFalse(r[3]['match'])

    def test_unreadable_order_is_not_a_match(self):
        o = fixture(); del o['ORDER00000000000A2']
        r = rec.reconcile(rec.load_rows(self.data), self.mcp(o))
        self.assertFalse(r[1]['match']); self.assertIn('not read', r[1]['why'])

    def test_token_goes_by_env_only_and_never_into_output(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {'APPROVEACCEPT_OWNER_TOKEN': 'fixture-owner', 'ANTHROPIC_API_KEY': 'fixture-model'}):
            results = rec.reconcile(rec.load_rows(self.data), self.mcp(fixture()))
        seen = json.loads(self.seen.read_text())
        self.assertNotIn('APPROVEACCEPT_OWNER_TOKEN', seen['env_names'])
        self.assertNotIn('ANTHROPIC_API_KEY', seen['env_names'])
        self.assertEqual(seen['token'], self.token)
        self.assertEqual(seen['env'], 'SANDBOX')
        self.assertNotIn(self.token, ' '.join(seen['argv']))
        self.assertTrue(any(a.startswith('--tools=orders.get') for a in seen['argv']))
        self.assertNotIn(self.token, rec.render(results) + json.dumps(results))

    def test_saved_check_records_what_was_checked_and_no_token(self):
        results = rec.reconcile(rec.load_rows(self.data), self.mcp(fixture()))
        rec.save_check(self.data, results)
        saved = json.loads((self.data / 'paypal-record.json').read_text())
        self.assertEqual((saved['matched'], saved['total']), (4, 4))
        self.assertEqual(sorted(saved['states']), ['BUY1', 'BUY2', 'BUY3', 'BUY4'])
        self.assertEqual(saved['states']['BUY3'], 'authorized')
        self.assertIn('@paypal/mcp', saved['source'])
        self.assertTrue(saved['at'])
        self.assertNotIn(self.token, json.dumps(saved))

    def test_refuses_production(self):
        with self.assertRaises(SystemExit):
            rec.PayPalMCP(['node', 'x'], self.token, environment='PRODUCTION')

    def test_reads_saved_byok_config_without_executing_shell(self):
        from unittest.mock import patch
        config = Path(self.tmp.name) / 'sandbox.env'
        config.write_text("export APPROVEACCEPT_PAYPAL_SANDBOX_CLIENT_ID='fixture-client'\n"
                          "export APPROVEACCEPT_PAYPAL_SANDBOX_CLIENT_SECRET='fixture-secret'\n"
                          "export UNRELATED='ignored'\n"
                          "touch should-not-run\n")
        with patch.dict(os.environ, {'APPROVEACCEPT_HOME': self.tmp.name}, clear=True):
            rec.load_sandbox_config()
            self.assertEqual(os.environ['APPROVEACCEPT_PAYPAL_SANDBOX_CLIENT_ID'], 'fixture-client')
            self.assertEqual(os.environ['APPROVEACCEPT_PAYPAL_SANDBOX_CLIENT_SECRET'], 'fixture-secret')
            self.assertNotIn('UNRELATED', os.environ)
            os.environ['APPROVEACCEPT_PAYPAL_SANDBOX_CLIENT_ID'] = 'explicit-client'
            rec.load_sandbox_config()
            self.assertEqual(os.environ['APPROVEACCEPT_PAYPAL_SANDBOX_CLIENT_ID'], 'explicit-client')

    def test_default_command_is_pinned(self):
        self.assertIn('@paypal/mcp@1.8.1', ' '.join(rec.default_command()))


@unittest.skipUnless(os.environ.get('APPROVEACCEPT_TEST_NETWORK') == '1' and os.environ.get('AA_DATA_DIR'),
                     'network: set APPROVEACCEPT_TEST_NETWORK=1 and AA_DATA_DIR to a real Sandbox run')
class RealPayPalMCP(unittest.TestCase):
    def test_real_run_reads_back_through_paypal_mcp(self):
        out = subprocess.run([sys.executable, '-B', str(ROOT / 'connect' / 'paypal_mcp_record.py'), '--json'],
                             capture_output=True, text=True, timeout=300)
        self.assertEqual(out.returncode, 0, out.stderr[-500:])
        results = json.loads(out.stdout)['results']
        self.assertTrue(results and all(r['match'] for r in results))


if __name__ == '__main__':
    unittest.main()
