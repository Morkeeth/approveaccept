import secrets
"""Tests for the three connections: MCP server, return URL plus webhooks, Telegram buttons.

Runs the app in substitute mode (no network, every ID starts SUB) in a temp folder, so the live
dashboard on 8752 is never touched. The MCP server runs as a real stdio subprocess.
  python3 -B -m unittest -v test_build
AA_APP_DIR runs the same tests against another copy of the app (used to watch them go red).
"""
import importlib, json, os, socket, subprocess, sys, tempfile, threading, time, unittest, urllib.parse, urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

APP_DIR = Path(os.environ.get('AA_APP_DIR') or Path(__file__).resolve().parent)
TMP = tempfile.mkdtemp(prefix='aa-test-')


class TestPortableWebhookRegistration(unittest.TestCase):
    def test_registration_uses_bundled_payment_adapter(self):
        source = (APP_DIR / 'connect' / 'webhook_register.py').read_text()
        self.assertIn("parents[1]", source)
        self.assertNotIn("parents[2] / 'leash'", source)

    def test_public_server_proxies_passkey_routes(self):
        source = (APP_DIR / 'design' / 'server.py').read_text()
        self.assertIn("'/api/passkey/enrol'", source)
        self.assertIn("'/api/passkey/options?'", source)
        self.assertIn("'/api/passkey/enrol/options?'", source)
        self.assertIn("'/api/approval-link'", source)
        self.assertIn("'/api/demo/start'", source)

    def test_host_script_never_turns_http_into_a_passkey_origin(self):
        source = (APP_DIR / 'start-host.sh').read_text()
        self.assertIn('APPROVEACCEPT_PUBLIC_BASE_URL#https://', source)


def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p


PORT, WPORT = free_port(), free_port()
PASSKEY_ORIGIN = 'https://approve.example.test'
OWNER_TOKEN = 'synthetic-test-owner-' + 'o' * 32
os.environ.update(LEASH_V2_SUBSTITUTE='1', LEASH_V2_DATA=TMP, LEASH_V2_PORT=str(PORT),
                  APPROVEACCEPT_PASSKEY_ORIGIN=PASSKEY_ORIGIN, APPROVEACCEPT_GUIDED_DEMO='1', APPROVEACCEPT_OWNER_TOKEN=OWNER_TOKEN)
for k in ('AA_TELEGRAM_TOKEN', 'AA_TELEGRAM_CHAT', 'AA_TELEGRAM_API'):
    os.environ.pop(k, None)
sys.path.insert(0, str(APP_DIR))
app = importlib.import_module('app')
app.S = app.State()
with app.S.book.db() as db:  # temp test database only: many holds, so lift the lifetime cap
    db.execute('UPDATE policy SET cap=100000000')
threading.Thread(target=ThreadingHTTPServer(('127.0.0.1', PORT), app.H).serve_forever, daemon=True).start()
threading.Thread(target=ThreadingHTTPServer(('127.0.0.1', WPORT), app.Webhook).serve_forever, daemon=True).start()
BASE = f'http://127.0.0.1:{PORT}'
PASSKEY_PRIVATE, PASSKEY_PUBLIC = Path(TMP) / 'passkey-private.pem', Path(TMP) / 'passkey-public.der'
subprocess.run(['openssl', 'ecparam', '-name', 'prime256v1', '-genkey', '-noout', '-out', PASSKEY_PRIVATE], check=True)
subprocess.run(['openssl', 'pkey', '-in', PASSKEY_PRIVATE, '-pubout', '-outform', 'DER', '-out', PASSKEY_PUBLIC], check=True)
PASSKEY_COUNT = 0


def passkey_auth_data(count=0):
    import hashlib
    return hashlib.sha256('approve.example.test'.encode()).digest() + bytes([0x05]) + count.to_bytes(4, 'big')


def passkey_client(kind, challenge):
    import passkeys
    raw = json.dumps({'type': 'webauthn.' + kind, 'challenge': challenge,
                      'origin': PASSKEY_ORIGIN}, separators=(',', ':')).encode()
    return raw, passkeys.b64e(raw)


def ensure_passkey():
    import passkeys
    if app.S.passkeys.has_credential():
        return
    token = app.S.passkeys.enrollment_token
    options = app.enrol_options(token)
    _, client = passkey_client('create', options['publicKey']['challenge'])
    app.enrol_passkey({'flow': options['flow'], 'token': token, 'id': 'owner-phone',
                       'clientDataJSON': client,
                       'authenticatorData': passkeys.b64e(passkey_auth_data()),
                       'publicKey': passkeys.b64e(PASSKEY_PUBLIC.read_bytes())})


def sign_passkey_options(options):
    import hashlib
    import passkeys
    global PASSKEY_COUNT
    PASSKEY_COUNT += 1
    raw, client = passkey_client('get', options['publicKey']['challenge'])
    auth_data = passkey_auth_data(PASSKEY_COUNT)
    signed, signature = Path(TMP) / 'passkey-signed.bin', Path(TMP) / 'passkey-signature.bin'
    signed.write_bytes(auth_data + hashlib.sha256(raw).digest())
    subprocess.run(['openssl', 'dgst', '-sha256', '-sign', PASSKEY_PRIVATE, '-out', signature, signed], check=True)
    return {'flow': options['flow'], 'id': 'owner-phone', 'clientDataJSON': client,
            'authenticatorData': passkeys.b64e(auth_data), 'signature': passkeys.b64e(signature.read_bytes())}


def approval_assertion(token):
    ensure_passkey()
    return sign_passkey_options(app.passkey_options(token))


class TestAFirstUsePasskey(unittest.TestCase):
    def setUp(self):
        from contextlib import ExitStack
        from unittest.mock import patch
        fixture = ExitStack()
        self.addCleanup(fixture.close)
        folder = fixture.enter_context(tempfile.TemporaryDirectory(prefix='aa-first-use-'))
        fixture.enter_context(patch.object(app, 'DATA', Path(folder)))
        fixture.enter_context(patch.object(app, 'S', app.State()))

    def test_enrolment_uses_configured_https_origin_and_consumes_one_time_link(self):
        self.assertFalse(app.S.passkeys.has_credential())
        token = app.S.passkeys.enrollment_token
        options = app.enrol_options(token)
        self.assertEqual(options['publicKey']['rp']['id'], 'approve.example.test')
        import passkeys
        _, client = passkey_client('create', options['publicKey']['challenge'])
        result = app.enrol_passkey({'flow': options['flow'], 'token': token, 'id': 'owner-phone',
                                    'clientDataJSON': client,
                                    'authenticatorData': passkeys.b64e(passkey_auth_data()),
                                    'publicKey': passkeys.b64e(PASSKEY_PUBLIC.read_bytes())})
        self.assertEqual(result, {'enrolled': True})
        self.assertTrue(app.S.passkeys.has_credential())
        self.assertEqual(app.S.passkeys.enrollment_link(), '')

    def test_phone_page_calls_platform_webauthn(self):
        source = (APP_DIR / 'phone.html').read_text()
        self.assertIn('navigator.credentials.create', source)
        self.assertIn('navigator.credentials.get', source)
        self.assertIn('Approve with Face ID', source)


def post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {'Content-Type': 'application/json', 'Origin': BASE, 'Authorization': 'Bearer '+OWNER_TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, {}


class MCP:
    """A real stdio session with mcp_server.py, as Claude Code or Codex would run it."""

    def __init__(self):
        self.p = subprocess.Popen([sys.executable, '-B', str(APP_DIR / 'mcp_server.py')], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  text=True, env=dict(os.environ, AA_URL=BASE, AA_CLIENT='test', APPROVEACCEPT_AGENT_TOKEN=OWNER_TOKEN))
        self.n = 0
        self.rpc('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '0'}})
        self.p.stdin.write(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) + '\n'); self.p.stdin.flush()

    def rpc(self, method, params=None):
        self.n += 1
        self.p.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': self.n, 'method': method, 'params': params or {}}) + '\n')
        self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())['result']

    def tool(self, name, **args):
        if name == 'request_purchase': args.setdefault('request_key', secrets.token_hex(16))
        return json.loads(self.rpc('tools/call', {'name': name, 'arguments': args})['content'][0]['text'])

    def close(self):
        self.p.stdin.close(); self.p.wait(5)
        self.p.stdout.close()


class TestMCP(unittest.TestCase):
    def setUp(self):
        self.m = MCP()

    def tearDown(self):
        self.m.close()

    def test_no_tool_can_make_a_manual_decision(self):
        names = [t['name'] for t in self.m.rpc('tools/list')['tools']]
        self.assertEqual(names, ['spending_policy', 'request_purchase', 'purchase_status', 'wait_for_decision'])

    def test_nothing_captured_without_approval(self):
        r = self.m.tool('request_purchase', agent='Concierge', sku='cine2', link='E1', why='Quiet film night.', task='book date night')
        self.assertEqual(r['state'], 'authorized', r)
        self.assertTrue(r['authorization_id'])
        w = self.m.tool('wait_for_decision', id=r['id'], timeout_seconds=3)
        self.assertEqual(w['state'], 'authorized')
        self.assertFalse(w['decided'])
        self.assertIsNone(w['capture_id'])
        self.assertEqual(app.S.book.get(r['id'])['state'], 'authorized')
        # Manual holds require a purchase-bound passkey regardless of ID prefix.
        code, _ = post(BASE + '/api/decide', {'id': r['id'], 'accept': True})
        self.assertEqual(code, 409)
        token = app.approval_link(r['id']).split('token=')[1]
        app.phone_decide(token, 'approve', approval_assertion(token))
        w = self.m.tool('wait_for_decision', id=r['id'], timeout_seconds=10)
        self.assertEqual(w['state'], 'captured')
        self.assertTrue(w['capture_id'].startswith('SUB-CAPTURE-'))

    def test_refuse_voids(self):
        r = self.m.tool('request_purchase', agent='Concierge', sku='cine2', link='E1', why='Film.')
        post(BASE + '/api/decide', {'id': r['id'], 'accept': False})
        self.assertEqual(self.m.tool('wait_for_decision', id=r['id'], timeout_seconds=10)['state'], 'voided')

    def test_checks_refuse_before_paypal(self):
        r = self.m.tool('request_purchase', agent='Concierge', sku='phones', link='E1', why='Nice headphones.')
        self.assertTrue(r.get('refused'), r)
        self.assertEqual(self.m.tool('purchase_status', id=r['id'])['order_id'], None)

    def test_agent_cannot_set_amount_or_payee(self):
        r = self.m.tool('request_purchase', agent='Concierge', sku='cine2', link='E1', why='x', amount=1, payee='ATTACKER')
        self.assertEqual(r['amount'], 'EUR 26.00')
        self.assertEqual(app.S.book.get(r['id'])['merchant'], app.SHOP)


class TestReturnAndWebhooks(unittest.TestCase):
    def buyer_order(self):
        pid = 'T' + str(time.time_ns())[-9:]
        r = app.admit(pid, app.agent('Concierge'), 'test', 'cine2', 'Cinema', 2600, app.SHOP, 'E1', 'why', '-')
        return pid, r['order_id']

    def test_order_carries_return_url(self):
        pid, oid = self.buyer_order()
        self.assertTrue(app.SUB.return_urls[oid].startswith(f'http://127.0.0.1:{PORT}/return?receipt='))
        self.assertNotIn(pid, app.SUB.return_urls[oid])

    def test_return_url_funds_the_hold(self):
        pid, oid = self.buyer_order()
        app.SUB.approve(oid)
        urllib.request.urlopen(urllib.request.Request(app.SUB.return_urls[oid] + '&token=' + oid, headers={'Authorization':'Bearer '+OWNER_TOKEN}), timeout=30).read()
        self.assertEqual(app.S.book.get(pid)['state'], 'authorized')

    def test_webhook_changes_the_screen(self):
        pid, oid = self.buyer_order()
        app.SUB.approve(oid)
        before = next(p for p in json.loads(urllib.request.urlopen(urllib.request.Request(BASE + '/api/state', headers={'Authorization':'Bearer '+OWNER_TOKEN})).read())['proposals'] if p['id'] == pid)
        self.assertEqual((before['money']['state'], before['paypal_events']), ('buyer_approval', []))
        ev = {'id': 'WH-TEST-' + pid, 'event_type': 'CHECKOUT.ORDER.APPROVED', 'resource': {'id': oid, 'status': 'APPROVED'}}
        code, _ = post(f'http://127.0.0.1:{WPORT}/webhooks/paypal', ev)
        self.assertEqual(code, 200)
        after = next(p for p in json.loads(urllib.request.urlopen(urllib.request.Request(BASE + '/api/state', headers={'Authorization':'Bearer '+OWNER_TOKEN})).read())['proposals'] if p['id'] == pid)
        self.assertEqual(after['money']['state'], 'authorized')
        self.assertEqual(after['paypal_events'][0]['type'], 'CHECKOUT.ORDER.APPROVED')
        post(f'http://127.0.0.1:{WPORT}/webhooks/paypal', ev)  # PayPal retries: recorded once
        with app.S.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM paypal_events WHERE pid=?', (pid,)).fetchone()[0], 1)

    def test_unsigned_webhook_refused_in_sandbox_mode(self):
        class NoSig:
            def call(self, path, data=None, request_id=None, method='POST'):
                return {'verification_status': 'FAILURE'}
        old = (app.SUBSTITUTE, app.provider)
        app.SUBSTITUTE, app.provider = False, lambda: NoSig()
        try:
            code, _ = post(f'http://127.0.0.1:{WPORT}/webhooks/paypal', {'id': 'WH-FORGED', 'event_type': 'PAYMENT.CAPTURE.COMPLETED', 'resource': {}})
        finally:
            app.SUBSTITUTE, app.provider = old
        self.assertEqual(code, 401)
        with app.S.db() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM paypal_events WHERE event_id='WH-FORGED'").fetchone())


class TestAttackSet(unittest.TestCase):
    def test_all_eight_refuse_and_mismatch_names_the_failed_rule(self):
        rows = app.attacks()
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(r['refused'] and r['id'] for r in rows), rows)
        mismatch = next(r for r in rows if r['id'] == 'A7')
        self.assertEqual(mismatch['reason'], 'Agent may propose for this kind of item')

    def test_screen_is_now_generic_instead_of_the_old_personal_demo(self):
        source = (APP_DIR / 'index.html').read_text()
        self.assertIn('Agent requests,<br>already sorted.', source)
        self.assertIn('data-filter=needs_me', source)
        self.assertIn('data-filter=auto_approved', source)
        self.assertIn('data-filter=blocked', source)
        self.assertIn('Review top request', source)
        self.assertNotIn('date night', source.lower())


class TestRankedOwnerOverview(unittest.TestCase):
    def request(self, **changes):
        payload = {'request_key':secrets.token_hex(16),'agent': 'Overview agent', 'title': 'Build input', 'merchant': 'API Foundry',
                   'category': 'data', 'cents': 1200, 'why': 'Needed for overview testing.',
                   'task': 'Test the owner overview'}
        payload.update(changes)
        return app.generic_agent_request(payload)

    def test_requests_are_grouped_ranked_and_labeled_from_spend_facts(self):
        app.grant_allowance({'agent': 'Overview agent', 'merchants': ['API Foundry'],
                             'per_purchase_cents': 2000, 'monthly_cents': 5000, 'days': 30})
        automatic = self.request(title='Inside request')
        owner = self.request(title='Large request', cents=5200)
        blocked = self.request(title='Blocked request', category='travel')
        overview = app.snapshot()['request_overview']
        rows = {row['id']: row for row in overview['items']}
        self.assertEqual(rows[owner['id']]['bucket'], 'needs_me')
        self.assertEqual(rows[owner['id']]['allowance'], 'Outside allowance')
        self.assertEqual(rows[owner['id']]['risk'], 'High risk')
        self.assertEqual(rows[automatic['id']]['bucket'], 'auto_approved')
        self.assertEqual(rows[automatic['id']]['allowance'], 'Inside allowance')
        self.assertEqual(rows[blocked['id']]['bucket'], 'blocked')
        self.assertLess(rows[owner['id']]['rank'], rows[automatic['id']]['rank'])
        next_row = next(row for row in overview['items'] if row['id'] == overview['next_action_id'])
        self.assertEqual(next_row['bucket'], 'needs_me')
        self.assertEqual(next_row['rank'], min(row['rank'] for row in overview['items'] if row['bucket'] == 'needs_me'))

    def test_dashboard_rotates_a_link_only_for_a_waiting_request(self):
        owner = self.request(title='Rotate link', cents=5400)
        first = owner['approval_url']
        second = app.refresh_approval_link(owner['id'])['approval_url']
        self.assertNotEqual(first, second)
        with self.assertRaisesRegex(app.Refused, 'invalid or expired'):
            app.approval_record(urllib.parse.parse_qs(urllib.parse.urlparse(first).query)['token'][0])
        token = urllib.parse.parse_qs(urllib.parse.urlparse(second).query)['token'][0]
        self.assertEqual(app.phone_payload(token)['queue_context']['id'], owner['id'])

    def test_owner_row_chips_and_state_use_owner_facing_semantics(self):
        source = (APP_DIR / 'index.html').read_text()
        self.assertIn('.signals{display:flex;align-items:center', source)
        self.assertIn('.signals .chip{display:inline-flex;align-items:center;min-height:28px;padding:4px 9px', source)
        self.assertIn('.chip.outside{color:var(--warn)}', source)
        self.assertIn("r.bucket==='needs_me'?'Held for you'", source)
        self.assertNotIn('<b>${esc(r.state)}</b>', source)


class TestGenericPurchaseAndPhoneApproval(unittest.TestCase):
    def manual_request(self):
        return app.generic_agent_request({'request_key':secrets.token_hex(16),
            'agent': 'Build agent', 'title': 'API credit pack', 'merchant': 'API Foundry',
            'category': 'software', 'cents': 4800,
            'why': 'Needed to finish the customer import.', 'task': 'Finish customer import',
        })

    def test_generic_mcp_request_returns_phone_link_and_waits(self):
        m = MCP()
        try:
            r = m.tool('request_purchase', agent='Research agent', title='Data pack', merchant='API Foundry',
                       category='data', cents=4800, why='Needed for the analysis.', task='Finish analysis')
        finally:
            m.close()
        self.assertEqual(r['state'], 'authorized', r)
        self.assertEqual(r['decision'], 'needs_approval')
        self.assertTrue(r['approval_url'].startswith(BASE + '/approve?token='), r)
        self.assertIsNone(app.S.book.get(r['id'])['capture_id'])

    def test_phone_link_shows_request_then_approves_once(self):
        r = self.manual_request()
        token = urllib.parse.parse_qs(urllib.parse.urlparse(r['approval_url']).query)['token'][0]
        shown = json.loads(urllib.request.urlopen(BASE + '/api/approval?token=' + urllib.parse.quote(token)).read())
        self.assertEqual((shown['agent'], shown['merchant'], shown['state']), ('Build agent', 'API Foundry', 'authorized'))
        code, decided = post(BASE + '/api/phone-decision', {
            'token': token, 'action': 'approve', 'assertion': approval_assertion(token)})
        self.assertEqual((code, decided['state']), (200, 'captured'))
        code, _ = post(BASE + '/api/phone-decision', {'token': token, 'action': 'refuse'})
        self.assertEqual(code, 409)

    def test_disallowed_category_never_reaches_paypal(self):
        r = app.generic_agent_request({'request_key':secrets.token_hex(16),'agent': 'Buying agent', 'title': 'Desk toy', 'merchant': 'API Foundry',
            'category': 'collectibles', 'cents': 100, 'why': 'It wants one.', 'task': 'Decorate desk'})
        self.assertEqual(r['state'], 'blocked')
        with self.assertRaises(app.Refused):
            app.S.book.get(r['id'])

    def test_purchase_inside_rules_is_automatic(self):
        r = app.generic_agent_request({'request_key':secrets.token_hex(16),'agent': 'Release agent', 'title': 'Small developer tool',
            'merchant': 'Developer Tools', 'category': 'software', 'cents': 100,
            'why': 'Needed to package a release.', 'task': 'Package release'})
        self.assertEqual((r['decision'], r['state']), ('automatic', 'captured'))
        self.assertNotIn('approval_url', r)
        self.assertTrue(r['capture_id'].startswith('SUB-CAPTURE-'))

    def test_public_origin_controls_tunnel_ready_link(self):
        old = app.PUBLIC_BASE
        app.PUBLIC_BASE = 'https://approve.example.test'
        try:
            r = self.manual_request()
        finally:
            app.PUBLIC_BASE = old
        self.assertTrue(r['approval_url'].startswith('https://approve.example.test/approve?token='))

    def test_monthly_plan_has_separate_approval_reminder_and_cancel(self):
        r = app.generic_agent_request({'request_key':secrets.token_hex(16),
            'agent': 'Release agent', 'title': 'Error monitoring', 'merchant': 'Developer Tools',
            'category': 'software', 'cents': 2400, 'why': 'Watch the release.',
            'task': 'Monitor the release', 'recurring': 'monthly',
        })
        self.assertEqual((r['decision'], r['state'], r['recurring']), ('needs_approval', 'authorized', 'monthly'))
        token = urllib.parse.parse_qs(urllib.parse.urlparse(r['approval_url']).query)['token'][0]
        before = app.phone_payload(token)
        self.assertEqual(before['subscription']['status'], 'pending')
        self.assertLess(before['subscription']['reminder_at'], before['subscription']['renewal_at'])
        approved = app.phone_decide(token, 'approve', approval_assertion(token))
        self.assertEqual(approved['state'], 'captured')
        self.assertEqual([s['title'] for s in approved['suggestions']], ['Backup storage', 'Usage dataset'])
        after = app.phone_payload(token)
        self.assertEqual(after['subscription']['status'], 'active')
        canceled = app.cancel_subscription(r['id'])
        self.assertEqual(canceled['status'], 'canceled')
        self.assertEqual(next(s for s in app.snapshot()['subscriptions'] if s['pid'] == r['id'])['status'], 'canceled')

    def test_monthly_plan_above_cap_stops_before_paypal(self):
        r = app.generic_agent_request({'request_key':secrets.token_hex(16),
            'agent': 'Release agent', 'title': 'Expensive monitoring', 'merchant': 'Developer Tools',
            'category': 'software', 'cents': 6100, 'why': 'Watch everything.',
            'task': 'Monitor the release', 'recurring': 'monthly',
        })
        self.assertEqual((r['decision'], r['state']), ('blocked', 'blocked'))
        self.assertIn('EUR 60.00', r['reasons'][0])
        with self.assertRaises(app.Refused):
            app.S.book.get(r['id'])

    def test_suggestions_appear_after_approval_and_each_needs_fresh_approval(self):
        r = self.manual_request()
        token = urllib.parse.parse_qs(urllib.parse.urlparse(r['approval_url']).query)['token'][0]
        self.assertEqual(app.phone_payload(token)['suggestions'], [])
        decided = app.phone_decide(token, 'approve', approval_assertion(token))
        self.assertEqual(len(decided['suggestions']), 3)
        follow_up = app.request_suggestion(token, 0)
        self.assertEqual((follow_up['decision'], follow_up['state']), ('needs_approval', 'authorized'))
        self.assertIn('/approve?token=', follow_up['approval_url'])
        self.assertIsNone(app.S.book.get(follow_up['id'])['capture_id'])

    def test_phone_page_has_narrow_width_guards_and_eur_copy(self):
        phone = (APP_DIR / 'phone.html').read_text()
        rules = (APP_DIR / 'spend_rules.py').read_text()
        self.assertIn('overflow-x:hidden', phone)
        self.assertIn('min-width:0', phone)
        self.assertNotIn('merchant automatic limit of {merchant_cap} cents', rules)

    def test_guided_demo_uses_normal_rules_and_never_approves_for_the_judge(self):
        result = app.guided_demo_start()
        self.assertEqual(app.S.book.get(result['automatic_id'])['state'], 'captured')
        self.assertEqual(app.S.book.get(result['held_id'])['state'], 'authorized')
        with self.assertRaises(app.Refused):
            app.S.book.get(result['blocked_id'])
        self.assertIn('/approve?token=', result['approval_url'])
        repeated = app.guided_demo_start()
        self.assertTrue(repeated['reused'])
        self.assertEqual(repeated['held_id'], result['held_id'])

    def test_guided_demo_endpoint_is_explicitly_gated(self):
        old = app.GUIDED_DEMO
        app.GUIDED_DEMO = False
        try:
            with self.assertRaisesRegex(app.Refused, 'not enabled'):
                app.guided_demo_start()
        finally:
            app.GUIDED_DEMO = old


class TestBoundedAllowancesAndPasskey(unittest.TestCase):
    def grant(self, agent, per_purchase=3000, monthly=5000, merchants=None):
        return app.grant_allowance({'agent': agent, 'merchants': merchants or ['API Foundry'],
                                    'per_purchase_cents': per_purchase, 'monthly_cents': monthly, 'days': 30})

    def buy(self, agent, cents, merchant='API Foundry'):
        return app.generic_agent_request({'request_key':secrets.token_hex(16),'agent': agent, 'title': 'Build input', 'merchant': merchant,
            'category': 'data', 'cents': cents, 'why': 'Needed for the bounded build.', 'task': 'Finish bounded build'})

    def token(self, response):
        return urllib.parse.parse_qs(urllib.parse.urlparse(response['approval_url']).query)['token'][0]

    def test_owner_grant_is_visible_with_scope_limits_usage_and_expiry(self):
        row = self.grant('Allowance screen agent', monthly=9000, merchants=['API Foundry', 'Developer Tools'])
        self.assertEqual(row['status'], 'active')
        shown = next(a for a in app.snapshot()['allowances'] if a['agent'] == 'Allowance screen agent')
        self.assertEqual(shown['merchants'], ['API Foundry', 'Developer Tools'])
        self.assertEqual((shown['per_purchase_cents'], shown['monthly_cents'], shown['used_cents']), (3000, 9000, 0))
        self.assertTrue(shown['expires_at'].endswith('Z'))

    def test_inside_allowance_captures_without_owner_prompt(self):
        self.grant('Inside agent')
        result = self.buy('Inside agent', 1800)
        self.assertEqual((result['decision'], result['state']), ('automatic', 'captured'))
        self.assertNotIn('approval_url', result)
        shown = app.allowance_for('Inside agent')
        self.assertEqual((shown['used_cents'], shown['remaining_cents']), (1800, 3200))

    def test_per_purchase_merchant_and_monthly_edges_go_to_phone(self):
        self.grant('Edge agent')
        too_large = self.buy('Edge agent', 3100)
        self.assertEqual(too_large['decision'], 'needs_approval')
        self.assertIn('EUR 30.00', too_large['reasons'][0])
        wrong_merchant = self.buy('Edge agent', 1000, 'Cloud Compute')
        self.assertEqual(wrong_merchant['decision'], 'needs_approval')
        self.assertIn('outside the allowance', wrong_merchant['reasons'][0])
        self.buy('Edge agent', 3000)
        over_month = self.buy('Edge agent', 2100)
        self.assertEqual(over_month['decision'], 'needs_approval')
        self.assertTrue(any('monthly limit' in reason for reason in over_month['reasons']))

    def test_expired_or_revoked_allowance_goes_to_phone(self):
        self.grant('Expiry agent')
        with app.S.db() as db:
            db.execute("UPDATE allowances SET expires_at='2020-01-01T00:00:00Z' WHERE agent='Expiry agent'")
        expired = self.buy('Expiry agent', 1000)
        self.assertEqual(expired['decision'], 'needs_approval')
        self.assertIn('expired', expired['reasons'][0])
        self.grant('Revoked agent')
        app.revoke_allowance('Revoked agent')
        revoked = self.buy('Revoked agent', 1000)
        self.assertEqual(revoked['decision'], 'needs_approval')
        self.assertIn('revoked', revoked['reasons'][0])

    def test_above_threshold_requires_and_verifies_face_id_passkey(self):
        response = self.buy('Signer agent', 5200)
        token = self.token(response)
        payload = app.phone_payload(token)
        self.assertTrue(payload['passkey_required'])
        self.assertEqual(payload['signer_mode'], 'Face ID passkey')
        decided = app.phone_decide(token, 'approve', approval_assertion(token))
        self.assertEqual(decided['state'], 'captured')
        with app.S.db() as db:
            receipt = db.execute('SELECT * FROM passkey_receipts WHERE pid=?', (response['id'],)).fetchone()
        self.assertIsNotNone(receipt)
        challenge = json.loads(receipt['challenge'])
        self.assertEqual((challenge['purchase_id'], challenge['amount_cents'], challenge['merchant']),
                         (response['id'], 5200, 'API Foundry'))

    def test_generic_capture_cannot_bypass_passkey_endpoint(self):
        response = self.buy('Bypass agent', 5100)
        with self.assertRaisesRegex(app.Refused, 'Face ID approval'):
            app.decide(response['id'], True)
        self.assertEqual(app.S.book.get(response['id'])['state'], 'authorized')

    def test_expired_stored_receipt_cannot_bypass_fresh_face_id(self):
        response = self.buy('Expired receipt agent', 5150)
        expired = {'purchase_id': response['id'], 'amount_cents': 5150,
                   'merchant': 'API Foundry', 'expires': int(time.time()) - 1, 'nonce': 'old'}
        with app.S.db() as db:
            db.execute('INSERT INTO passkey_receipts VALUES (?,?,?,?)',
                       (response['id'], json.dumps(expired), 'owner-phone', app.now()))
        with self.assertRaisesRegex(app.Refused, 'Face ID approval'):
            app.decide(response['id'], True)
        self.assertEqual(app.S.book.get(response['id'])['state'], 'authorized')

    def test_clear_fallback_when_no_passkey_exists(self):
        response = self.buy('No passkey agent', 5300)
        token = self.token(response)
        old = app.S.passkeys
        app.S.passkeys = None
        try:
            with self.assertRaisesRegex(app.Refused, 'HTTPS origin'):
                app.phone_decide(token, 'approve')
        finally:
            app.S.passkeys = old
        self.assertEqual(app.S.book.get(response['id'])['state'], 'authorized')

    def test_wrong_purchase_replay_is_rejected(self):
        first, second = self.buy('Replay passkey agent A', 5400), self.buy('Replay passkey agent B', 5400)
        first_token, second_token = self.token(first), self.token(second)
        assertion = approval_assertion(first_token)
        with self.assertRaisesRegex(app.Refused, 'details changed|different purchase link'):
            app.phone_decide(second_token, 'approve', assertion)
        self.assertEqual(app.S.book.get(second['id'])['state'], 'authorized')

    def test_expired_passkey_challenge_is_rejected(self):
        response = self.buy('Expired passkey agent', 5450)
        token = self.token(response)
        ensure_passkey()
        options = app.passkey_options(token)
        app.S.passkeys.challenges[options['flow']]['expires'] = 0
        assertion = sign_passkey_options(options)
        with self.assertRaisesRegex(app.Refused, 'invalid or expired'):
            app.phone_decide(token, 'approve', assertion)
        self.assertEqual(app.S.book.get(response['id'])['state'], 'authorized')

    def test_tampered_amount_after_face_id_starts_is_rejected(self):
        response = self.buy('Tamper passkey agent', 5500)
        token = self.token(response)
        ensure_passkey()
        options = app.passkey_options(token)
        assertion = sign_passkey_options(options)
        with app.S.book.db() as db:
            db.execute('UPDATE requests SET cents=5600 WHERE id=?', (response['id'],))
        try:
            with self.assertRaisesRegex(app.Refused, 'details changed'):
                app.phone_decide(token, 'approve', assertion)
        finally:
            with app.S.book.db() as db:
                db.execute('UPDATE requests SET cents=5500 WHERE id=?', (response['id'],))
        self.assertEqual(app.S.book.get(response['id'])['state'], 'authorized')

    def test_allowance_input_rejects_ambiguous_or_unbounded_grants(self):
        with self.assertRaisesRegex(app.Refused, 'cannot exceed'):
            self.grant('Bad cap agent', per_purchase=6000, monthly=5000)
        with self.assertRaisesRegex(app.Refused, 'distinct merchants'):
            self.grant('Duplicate merchant agent', merchants=['API Foundry', 'api foundry'])


class FakeTelegram(BaseHTTPRequestHandler):
    """Local stand-in for api.telegram.org. Nothing leaves this machine."""
    sent, updates = [], []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])) or b'{}')
        method = self.path.rsplit('/', 1)[-1]
        if method == 'sendMessage':
            FakeTelegram.sent.append(body)
            res = {'message_id': len(FakeTelegram.sent), 'chat': {'id': int(body['chat_id'])}, 'text': body['text']}
        elif method == 'getUpdates':
            res, FakeTelegram.updates[:] = list(FakeTelegram.updates), []
        else:
            res = True
        out = json.dumps({'ok': True, 'result': res}).encode()
        self.send_response(200); self.send_header('Content-Length', str(len(out))); self.end_headers(); self.wfile.write(out)


class TestTelegram(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tport = free_port()
        threading.Thread(target=ThreadingHTTPServer(('127.0.0.1', tport), FakeTelegram).serve_forever, daemon=True).start()
        import telegram_approve
        with app.S.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS telegram_sent(pid TEXT PRIMARY KEY, message_id INTEGER)')
        cls.bot = telegram_approve.Bot(app, f'http://127.0.0.1:{tport}', 'TESTTOKEN', '4242')

    def hold(self):
        r = app.agent_request({'request_key':secrets.token_hex(16),'agent': 'Concierge', 'sku': 'cine2', 'link': 'E1', 'why': 'Film night.'})
        self.bot.announce()
        msg = next(m for m in FakeTelegram.sent if r['order_id'] in m['text'])
        return r, msg

    def tap(self, r, kind, who=4242):
        FakeTelegram.updates.append({'update_id': int(time.time_ns() % 10**9), 'callback_query': {
            'id': 'cb1', 'data': kind + ':' + r['id'], 'from': {'id': who}, 'message': {'message_id': 1, 'chat': {'id': who}, 'text': 'x'}}})
        self.bot.updates()

    def test_message_has_two_buttons(self):
        r, msg = self.hold()
        self.assertEqual([b['text'] for b in msg['reply_markup']['inline_keyboard'][0]], ['Accept EUR 26.00', 'Refuse'])
        self.assertIn('EUR 26.00', msg['text'])
        self.bot.announce()
        self.assertEqual(sum(r['order_id'] in m['text'] for m in FakeTelegram.sent), 1)

    def test_approve_tap_requires_purchase_bound_passkey(self):
        r, _ = self.hold()
        self.tap(r, 'a')
        self.assertEqual(app.S.book.get(r['id'])['state'], 'authorized')

    def test_refuse_tap_voids(self):
        r, _ = self.hold()
        self.tap(r, 'r')
        self.assertEqual(app.S.book.get(r['id'])['state'], 'voided')

    def test_stranger_tap_ignored(self):
        r, _ = self.hold()
        self.tap(r, 'a', who=999)
        self.assertEqual(app.S.book.get(r['id'])['state'], 'authorized')

    def test_slow_keychain_does_not_block_startup(self):
        import telegram_approve
        old = telegram_approve.subprocess.check_output
        try:
            def slow(*args, **kwargs):
                raise subprocess.TimeoutExpired(args[0], kwargs.get('timeout'))
            telegram_approve.subprocess.check_output = slow
            self.assertEqual(telegram_approve.keychain('missing'), '')
        finally:
            telegram_approve.subprocess.check_output = old


class TestDesignTokens(unittest.TestCase):
    """Design rule (19 Oct): keep the approved brown and shiny look. The app and the design keep the frozen tokens."""

    def run_check(self, *files):
        return subprocess.run(['node', str(APP_DIR / 'design' / 'check-tokens.cjs'), *map(str, files)], capture_output=True, text=True)

    def test_app_and_design_keep_tokens(self):
        r = self.run_check()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_drift_fails(self):
        src = (APP_DIR / 'index.html').read_text().replace('--acc:oklch(0.85 0.13 190)', '--acc:oklch(0.32 0.09 258)', 1)
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'index.html'
            f.write_text(src)
            r = self.run_check(f)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn('--acc', r.stdout)


class TestContrast(unittest.TestCase):
    """Colour check for the redesign: every text pair passes WCAG AA (4.5:1) in dark and light, on the app and the design page."""

    def run_check(self, f):
        return subprocess.run(['node', str(APP_DIR / 'design' / 'check-contrast.cjs'), str(f)], capture_output=True, text=True)

    def test_both_pages_pass(self):
        for f in ('index.html', 'design/index.html'):
            r = self.run_check(APP_DIR / f)
            self.assertEqual(r.returncode, 0, f + ': ' + r.stdout + r.stderr)

    def test_low_contrast_fails(self):
        src = (APP_DIR / 'index.html').read_text().replace('--mute:oklch(0.73 0.02 70)', '--mute:oklch(0.42 0.02 70)', 1)
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'index.html'
            f.write_text(src)
            r = self.run_check(f)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn('--mute on --ground', r.stdout)


if __name__ == '__main__':
    unittest.main()


class TestRequestShoppingContext(unittest.TestCase):
    def payload(self, **changes):
        value = dict(request_key=secrets.token_hex(16), agent='Shopping context agent', title='API credit pack', merchant='API Foundry',
                     category='software', cents=4800, why='Validate an import against sample API responses.',
                     task='Test the customer import', product_url='https://example.com/api-credit-pack')
        value.update(changes)
        return value

    def test_owner_and_agent_see_same_frozen_policy_and_source_link(self):
        app.grant_allowance(dict(agent='Shopping context agent', merchants=['API Foundry'],
                                per_purchase_cents=2000, monthly_cents=9000, days=1))
        created = app.generic_agent_request(self.payload())
        token = urllib.parse.parse_qs(urllib.parse.urlparse(created['approval_url']).query)['token'][0]
        before = app.phone_payload(token)
        self.assertEqual(before['context']['policy']['source'], 'Owner allowance')
        self.assertIn('EUR 20.00', before['context']['policy']['lines'][0])
        self.assertTrue(any('EUR 20.00' in x for x in before['reasons']))
        self.assertEqual(before['context']['product_url'], self.payload()['product_url'])
        self.assertEqual(before['context'], app.agent_status(created['id'])['context'])
        app.grant_allowance(dict(agent='Shopping context agent', merchants=['API Foundry'],
                                per_purchase_cents=6000, monthly_cents=9000, days=1))
        self.assertEqual(app.phone_payload(token)['context'], before['context'])
        app.phone_decide(token, 'refuse')
        self.assertEqual(app.agent_status(created['id'])['state'], 'voided')
        with self.assertRaisesRegex(app.Refused, 'already been used'):
            app.phone_decide(token, 'refuse')

    def test_bad_links_and_non_integer_prices_stop_before_provider(self):
        before = len(app.SUB.orders)
        for change in [dict(product_url='javascript:alert(1)'), dict(product_url='https://a:b@example.com'),
                       dict(product_url='https://example.com/ bad'), dict(cents=True), dict(cents='4800')]:
            with self.assertRaises(app.Refused):
                app.generic_agent_request(self.payload(**change))
        self.assertEqual(len(app.SUB.orders), before)

    def test_allowance_cannot_bypass_subscription_hard_cap(self):
        app.grant_allowance(dict(agent='Subscription cap agent', merchants=['API Foundry'],
                                per_purchase_cents=10000, monthly_cents=50000, days=1))
        before = len(app.SUB.orders)
        created = app.generic_agent_request(self.payload(agent='Subscription cap agent', cents=6100, recurring='monthly'))
        self.assertEqual(created['state'], 'blocked')
        self.assertEqual(len(app.SUB.orders), before)
        self.assertEqual(app.agent_status(created['id'])['state'], 'blocked')
        self.assertTrue(app.agent_status(created['id'])['decided'])
