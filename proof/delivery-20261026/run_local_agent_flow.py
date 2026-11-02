"""Isolated MCP + hosted proxy + webhook substitute proof. Never calls PayPal."""
import json, os, pathlib, secrets, signal, socket, subprocess, tempfile, time, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = pathlib.Path('/tmp/paypal-delivery-proof-20261026')
OUT.mkdir(exist_ok=True)
PORTS = (8891, 8892, 8893)
for port in PORTS:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', port))
DATA = pathlib.Path(tempfile.mkdtemp(prefix='aa-fresh-local-', dir=OUT))
ORIGIN = 'http://127.0.0.1:8891'
ENV = os.environ.copy()
ENV.update({'AA_DATA_DIR': str(DATA), 'PORT': '8891', 'AA_BACKEND_PORT': '8892',
            'LEASH_V2_WEBHOOK_PORT': '8893', 'AA_DESIGN_HOST': '127.0.0.1',
            'LEASH_V2_SUBSTITUTE': '1', 'APPROVEACCEPT_PUBLIC_BASE_URL': ORIGIN,
            'APPROVEACCEPT_OWNER_TOKEN': secrets.token_hex(32),
            'APPROVEACCEPT_AGENT_TOKEN': secrets.token_hex(32),
            'APPROVEACCEPT_AGENT_NAME': 'Build agent',
            'APPROVEACCEPT_LIVE_MONEY_ENABLED': 'false', 'APPROVEACCEPT_GUIDED_DEMO': '0'})


def http(method, path, body=None, owner=False, same_origin=False):
    headers = {'Content-Type': 'application/json'}
    if owner:
        headers['Authorization'] = 'Bearer ' + ENV['APPROVEACCEPT_OWNER_TOKEN']
    if same_origin:
        headers['Origin'] = ORIGIN
    request = urllib.request.Request(ORIGIN + path,
              json.dumps(body).encode() if body is not None else None, headers, method=method)
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = response.read()
        return response.status, json.loads(raw) if raw else None


def tool(process, call_id, name, args):
    message = {'jsonrpc': '2.0', 'id': call_id, 'method': 'tools/call',
               'params': {'name': name, 'arguments': args}}
    process.stdin.write(json.dumps(message) + '\n')
    process.stdin.flush()
    reply = json.loads(process.stdout.readline())
    return json.loads(reply['result']['content'][0]['text'])


log = (DATA / 'server.log').open('wb')
server = subprocess.Popen(['sh', './start-host.sh'], cwd=ROOT, env=ENV,
                          stdout=log, stderr=log, start_new_session=True)
agent = None
try:
    for _ in range(70):
        try:
            if http('GET', '/health')[1]['ok']:
                break
        except Exception:
            time.sleep(.1)
    else:
        raise RuntimeError('Fresh hosted service did not become healthy')
    assert http('GET', '/api/state', owner=True)[1]['source'] == 'local substitute, no PayPal calls'
    http('POST', '/api/allowance', {'agent': 'Build agent', 'merchants': ['API Foundry'],
         'per_purchase_cents': 3000, 'monthly_cents': 12000, 'days': 1}, owner=True, same_origin=True)
    mcp_env = ENV.copy()
    mcp_env.update({'AA_URL': ORIGIN, 'AA_CLIENT': 'local MCP protocol proof'})
    agent = subprocess.Popen(['python3', '-B', 'mcp_server.py'], cwd=ROOT, env=mcp_env,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, bufsize=1)
    task = 'Validate the customer import against real API responses.'
    held = tool(agent, 1, 'request_purchase', {'agent': 'Build agent', 'title': 'API credit pack',
        'merchant': 'API Foundry', 'category': 'software', 'cents': 4800,
        'why': 'API credits unblock customer import validation.', 'task': task})
    assert held['state'] == 'authorized' and held['decision'] == 'needs_approval'
    status = tool(agent, 2, 'purchase_status', {'id': held['id']})
    assert status['order_id'].startswith('SUB') and status['authorization_id'].startswith('SUB')
    assert status['capture_id'] is None
    event = {'id': 'WH-LOCAL-' + secrets.token_hex(5),
             'event_type': 'PAYMENT.AUTHORIZATION.CREATED',
             'resource': {'id': status['authorization_id'], 'status': 'CREATED',
                          'supplementary_data': {'related_ids': {'order_id': status['order_id']}}}}
    webhook_status = http('POST', '/webhooks/paypal', event)[0]
    assert webhook_status == 200
    after_webhook = tool(agent, 3, 'purchase_status', {'id': held['id']})
    assert len(after_webhook['paypal_events']) == 1 and after_webhook['state'] == 'authorized'
    waiting = tool(agent, 4, 'wait_for_decision', {'id': held['id'], 'timeout_seconds': 1})
    assert waiting['state'] == 'authorized' and waiting['decided'] is False
    automatic = tool(agent, 5, 'request_purchase', {'agent': 'Build agent', 'title': 'Build logs',
        'merchant': 'API Foundry', 'category': 'infrastructure', 'cents': 1800,
        'why': 'Keep failure logs for the same customer import validation.', 'task': task})
    assert automatic['state'] == 'captured' and automatic['capture_id'].startswith('SUB')
    blocked = tool(agent, 6, 'request_purchase', {'agent': 'Build agent', 'title': 'Weekend flight',
        'merchant': 'Travel Desk', 'category': 'travel', 'cents': 7600,
        'why': 'Unrelated flight.', 'task': task})
    assert blocked['state'] == 'blocked' and not blocked.get('order_id')
    token = held['approval_url'].split('token=', 1)[1]
    refused = http('POST', '/api/phone-decision', {'token': token, 'action': 'refuse'},
                   same_origin=True)[1]
    assert refused['state'] == 'voided'
    final = tool(agent, 7, 'purchase_status', {'id': held['id']})
    assert final['state'] == 'voided' and final['capture_id'] is None
    proof = {'mode': 'local substitute; no PayPal provider call or passkey claim',
             'source_worktree': str(ROOT), 'ports': PORTS,
             'mcp_client': 'local JSON-RPC harness; no model call', 'task': task,
             'held': {'id': held['id'], 'order_id': status['order_id'],
                      'authorization_id': status['authorization_id'],
                      'initial_state': status['state'], 'capture_id': status['capture_id'],
                      'webhook_http': webhook_status,
                      'webhook_event_type': after_webhook['paypal_events'][0]['type'],
                      'wait_state': waiting['state'], 'final_state': final['state']},
             'automatic': {'id': automatic['id'], 'state': automatic['state'],
                           'capture_id': automatic['capture_id']},
             'blocked': {'id': blocked['id'], 'state': blocked['state'],
                         'order_id': blocked.get('order_id')},
             'data_dir': str(DATA)}
    (OUT / 'local-agent-flow.json').write_text(json.dumps(proof, indent=2))
    print(json.dumps(proof, indent=2))
finally:
    if agent:
        agent.terminate()
        agent.wait(timeout=3)
    os.killpg(server.pid, signal.SIGTERM)
    server.wait(timeout=5)
    log.close()
