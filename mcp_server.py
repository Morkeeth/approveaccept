"""ApproveAccept MCP server (stdio). An agent in Claude Code or Codex asks to buy; a human decides.

Tools: request_purchase, purchase_status, wait_for_decision. There is deliberately no tool that
captures, voids or approves: only the human, on the dashboard or in Telegram, can move the money.
The agent names an item and says why. ApproveAccept sets payee and amount, runs every check, and
holds the money in a PayPal sandbox authorization.

Claude Code: .mcp.json in this folder with the fresh run's AA_AGENT_ENV_FILE.
Codex or Claude: see README.md, "Connect your agent".
AA_URL points at the public service for remote agent access (the old local default
http://127.0.0.1:8752 is for trusted single-machine development only).
"""
import json, os, sys, time, urllib.error, urllib.parse, urllib.request

URL = os.environ.get('AA_URL', 'http://127.0.0.1:8752').rstrip('/')
CLIENT = os.environ.get('AA_CLIENT', 'an MCP client')

TOOLS = [
    {'name': 'spending_policy',
     'description': 'Read the effective sandbox spend rules and remaining allowance before requesting a purchase. No payment is made.',
     'inputSchema': {'type': 'object', 'additionalProperties': False, 'required': ['agent'],
                     'properties': {'agent': {'type': 'string', 'description': 'Your assigned agent identity.'}}}},
    {'name': 'request_purchase',
     'description': 'Ask to buy something under the configured spend rules. A blocked request stops before PayPal; '
                    'an automatic request captures in PayPal Sandbox; anything else returns an expiring owner approval URL.',
     'inputSchema': {'type': 'object', 'additionalProperties': False,
                     'required': ['request_key', 'agent', 'title', 'merchant', 'category', 'cents', 'why', 'task'], 'properties': {
         'request_key': {'type':'string','minLength':12,'maxLength':80,'pattern':'^[A-Za-z0-9_-]+$','description':'Stable client intent key. Reuse unchanged on retries; use a new key only for a new purchase.'},
         'agent': {'type': 'string', 'description': 'The name of the requesting agent.'},
         'title': {'type': 'string', 'description': 'What the agent wants to buy.'},
         'merchant': {'type': 'string', 'description': 'Merchant name used by the spend rules.'},
         'category': {'type': 'string', 'description': 'Purchase category, for example hosting, database, domain or travel. The owner allows categories per agent.'},
         'cents': {'type': 'integer', 'minimum': 1, 'description': 'Exact price in euro cents.'},
         'why': {'type': 'string', 'description': 'Why the purchase is needed now.'},
         'task': {'type': 'string', 'description': 'The blocked task this purchase would unblock.'},
         'product_url': {'type': 'string', 'description': 'Optional HTTPS product or pricing page. Agent-supplied; not treated as a verified quote.'},
         'recurring': {'type': 'string', 'enum': ['monthly'],
                       'description': 'Set to monthly to request a monthly plan under the separate subscription cap.'}}}},
    {'name': 'purchase_status',
     'description': 'Read the state of a purchase request: authorized (held, waiting), captured, voided or refused.',
     'inputSchema': {'type': 'object', 'additionalProperties': False, 'required': ['id'],
                     'properties': {'id': {'type': 'string'}}}},
    {'name': 'wait_for_decision',
     'description': 'Wait until the human approves or refuses, up to timeout_seconds (max 600). Returns the final state.',
     'inputSchema': {'type': 'object', 'additionalProperties': False, 'required': ['id'], 'properties': {
         'id': {'type': 'string'}, 'timeout_seconds': {'type': 'integer', 'minimum': 1, 'maximum': 600}}}},
]


def http(method, path, body=None):
    headers = {'Content-Type': 'application/json', 'Origin': URL}
    token = os.environ.get('APPROVEACCEPT_AGENT_TOKEN', '')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(URL + path, json.dumps(body).encode() if body is not None else None,
                                 headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return {'error': json.loads(e.read()).get('error', f'HTTP {e.code}')}
        except json.JSONDecodeError:
            return {'error': f'HTTP {e.code}'}
    except urllib.error.URLError:
        return {'error': 'ApproveAccept is not running at ' + URL}


def status(pid):
    return http('GET', '/api/agent/status?id=' + urllib.parse.quote(pid))


def call(name, a):
    if name == 'spending_policy':
        return http('GET', '/api/agent/policy?agent=' + urllib.parse.quote(str(a.get('agent', ''))))
    if name == 'request_purchase':
        import re
        if not isinstance(a.get('request_key'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{12,80}',a['request_key']):
            return {'error':'request_key is required; reuse the same key and details on retries.'}
        # Keep the historical catalog request compatible for recorded sandbox proofs.
        path = '/api/agent/request' if 'sku' in a else '/api/purchase'
        r = http('POST', path, dict(a, client=CLIENT))
        if r.get('state') == 'authorized':
            r['next'] = f"Held, not paid. Give the owner the approval_url, then call wait_for_decision with id {r['id']}."
        return r
    if name == 'purchase_status':
        return status(str(a.get('id', '')))
    if name == 'wait_for_decision':
        end = time.time() + min(int(a.get('timeout_seconds') or 120), 600)
        while True:
            r = status(str(a.get('id', '')))
            if r.get('error') or r.get('decided') or time.time() >= end:
                if not r.get('error') and not r.get('decided'):
                    r['next'] = 'Still waiting for the human. Nothing was paid.'
                return r
            time.sleep(2)
    return {'error': 'Unknown tool ' + name}


def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        m = json.loads(line)
        mid, method = m.get('id'), m.get('method')
        if mid is None:
            continue  # notification
        if method == 'initialize':
            res = {'protocolVersion': m.get('params', {}).get('protocolVersion', '2024-11-05'),
                   'capabilities': {'tools': {}}, 'serverInfo': {'name': 'approveaccept', 'version': '0.1.0'}}
        elif method == 'tools/list':
            res = {'tools': TOOLS}
        elif method == 'tools/call':
            p = m.get('params', {})
            out = call(p.get('name'), p.get('arguments') or {})
            res = {'content': [{'type': 'text', 'text': json.dumps(out, indent=1)}], 'isError': bool(out.get('error'))}
        elif method == 'ping':
            res = {}
        else:
            sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32601, 'message': 'Method not found'}}) + '\n')
            sys.stdout.flush()
            continue
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': mid, 'result': res}) + '\n')
        sys.stdout.flush()


if __name__ == '__main__':
    main()
