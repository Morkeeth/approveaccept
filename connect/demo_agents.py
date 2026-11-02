#!/usr/bin/env python3
"""Demo: two named agents buy through the real MCP server, each with its own key.

    AA_URL=http://127.0.0.1:8780 APPROVEACCEPT_OWNER_TOKEN=... python3 connect/demo_agents.py

As the owner it creates a key and limits for "Claude Code" (hosting, database, domain;
EUR 30 per item) and "GrokBot" (travel; EUR 50 per item). Then each agent sends
requests over MCP: Claude Code buys a domain and a hosting plan inside its limit;
GrokBot asks for a flight over its limit, which PayPal holds for the owner's Face ID.
Sandbox only. Prints request IDs and states, never keys.
"""
import json, os, secrets, subprocess, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = os.environ.get('AA_URL', 'http://127.0.0.1:8780').rstrip('/')
OWNER = os.environ.get('APPROVEACCEPT_OWNER_TOKEN', '')
AGENTS = {'Claude Code': {'categories': ['hosting', 'database', 'domain'], 'per': 3000, 'month': 12000},
          'GrokBot': {'categories': ['travel'], 'per': 5000, 'month': 20000}}
ASKS = [('Claude Code', 'Domain name .com, 1 year', 'Sandbox dev services', 'domain', 1200,
         'The launch page needs its own address before the demo.', 'Publish the hackathon landing page'),
        ('Claude Code', 'Hosting plan, Pro, 1 month', 'Sandbox dev services', 'hosting', 2000,
         'The free tier times out during builds; Pro removes the limit.', 'Deploy the demo build'),
        ('GrokBot', 'Flight Paris to Lisbon, economy', 'Sandbox travel', 'travel', 8900,
         'Cheapest direct option that lands before the 10:00 meeting.', 'Book travel for the Lisbon meetup')]


def owner(path, body):
    r = urllib.request.Request(URL + path, json.dumps(body).encode(), {'Content-Type': 'application/json', 'Origin': URL,
                               'Authorization': 'Bearer ' + OWNER})
    return json.load(urllib.request.urlopen(r, timeout=30))


def mcp(key, calls):
    env = {k: v for k, v in os.environ.items() if not k.startswith('APPROVEACCEPT_')}
    env.update(AA_URL=URL, APPROVEACCEPT_AGENT_TOKEN=key, AA_CLIENT='MCP demo driver')
    lines = [{'jsonrpc': '2.0', 'id': 0, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'demo', 'version': '1'}}}]
    lines += [{'jsonrpc': '2.0', 'id': i + 1, 'method': 'tools/call', 'params': {'name': n, 'arguments': a}} for i, (n, a) in enumerate(calls)]
    out = subprocess.run([sys.executable, '-B', str(ROOT / 'mcp_server.py')], input='\n'.join(json.dumps(l) for l in lines) + '\n',
                         capture_output=True, text=True, env=env, timeout=180).stdout
    replies = [json.loads(l) for l in out.splitlines() if l.strip()]
    return [r for r in replies if r.get('id', 0) > 0]


def main():
    if len(OWNER) < 32:
        raise SystemExit('Set APPROVEACCEPT_OWNER_TOKEN to the owner key from step 0.')
    keys = {}
    for name, p in AGENTS.items():
        keys[name] = owner('/api/agent-key', {'agent': name})['key']
        owner('/api/allowance', {'agent': name, 'merchants': ['Sandbox dev services', 'Sandbox travel'], 'categories': p['categories'],
                                 'per_purchase_cents': p['per'], 'monthly_cents': p['month'], 'days': 7})
        print(f'{name}: key created, EUR {p["per"] // 100} per item, {", ".join(p["categories"])}')
    for agent, title, merchant, category, cents, why, task in ASKS:
        args = {'request_key': secrets.token_hex(12), 'agent': agent, 'title': title, 'merchant': merchant,
                'category': category, 'cents': cents, 'why': why, 'task': task}
        reply = mcp(keys[agent], [('request_purchase', args)])[0]
        text = reply.get('result', {}).get('content', [{}])[0].get('text', '{}')
        try:
            r = json.loads(text)
        except ValueError:
            r = {'error': text[:200]}
        print(json.dumps({'agent': agent, 'title': title, 'eur': cents / 100, 'id': r.get('id'), 'state': r.get('state'),
                          'capture_id': r.get('capture_id'), 'error': r.get('error')}))


if __name__ == '__main__':
    main()
