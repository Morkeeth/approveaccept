#!/usr/bin/env python3
"""Step 0: bring your own PayPal Sandbox keys and connect your agent.

    python3 connect/byok.py

Paste your PayPal Sandbox REST app client ID and secret, and optionally an
Anthropic API key for AI ranking (input is hidden).
The keys are checked against api-m.sandbox.paypal.com and saved in ONE file
outside this repository, mode 0600:

    ~/.config/approveaccept/sandbox.env   (override with APPROVEACCEPT_HOME)

Nothing is written to the repository, printed to stdout or logged. The owner
sign-in key is shown once on your terminal (/dev/tty) only. Sandbox only:
there is no live PayPal endpoint in this code.
"""
import base64, getpass, json, os, secrets, stat, subprocess, sys, urllib.error, urllib.request
from pathlib import Path

SANDBOX = 'https://api-m.sandbox.paypal.com'
REPO = Path(__file__).resolve().parent.parent
AGENT_NAME = 'Judge agent'


def home():
    return Path(os.environ.get('APPROVEACCEPT_HOME') or Path.home() / '.config' / 'approveaccept').expanduser().resolve()


def ask(prompt, hidden=True):
    # Hidden input on a terminal; plain stdin lines when piped (tests, scripted dry runs).
    if sys.stdin.isatty():
        return (getpass.getpass(prompt) if hidden else input(prompt)).strip()
    sys.stderr.write(prompt + '\n')
    return sys.stdin.readline().strip()


def call(req):
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        # Never echo the request; PayPal error bodies carry no credential.
        raise SystemExit(f'PayPal Sandbox refused the keys (HTTP {e.code}). Check you copied the Sandbox, not Live, client ID and secret.') from None
    except urllib.error.URLError as e:
        raise SystemExit(f'Could not reach PayPal Sandbox: {e.reason}') from None


def verify(client, secret):
    auth = base64.b64encode(f'{client}:{secret}'.encode()).decode()
    return call(urllib.request.Request(SANDBOX + '/v1/oauth2/token', data=b'grant_type=client_credentials',
                headers={'Authorization': 'Basic ' + auth, 'Content-Type': 'application/x-www-form-urlencoded'}))['access_token']


def derive_merchant(token):
    # An unfunded order with no payee names the app's own business account. No payment
    # source is attached, so it stays CREATED and expires; no money is held or moved.
    body = json.dumps({'intent': 'AUTHORIZE', 'purchase_units': [{'amount': {'currency_code': 'EUR', 'value': '1.00'},
                       'description': 'ApproveAccept key check, never funded'}]}).encode()
    order = call(urllib.request.Request(SANDBOX + '/v2/checkout/orders', data=body,
                 headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', 'Prefer': 'return=representation'}))
    merchant = order['purchase_units'][0].get('payee', {}).get('merchant_id', '')
    if not merchant:
        raise SystemExit('Could not read your Sandbox merchant ID. Run again and paste it (Sandbox accounts > business account > Account ID).')
    return merchant


def verify_model_key(value):
    # A free model-list call proves the key works without generating any tokens.
    try:
        import anthropic
    except ImportError:
        raise SystemExit('Install the Anthropic SDK first: pip install anthropic') from None
    try:
        anthropic.Anthropic(api_key=value, max_retries=0, timeout=20.0).models.list(limit=1)
    except anthropic.AuthenticationError:
        raise SystemExit('The Anthropic API refused that key.') from None
    except anthropic.APIError:
        raise SystemExit('Could not check the model key with the Anthropic API. Try again.') from None


def write_env(path, values):
    if path.is_relative_to(REPO):
        raise SystemExit('Refusing to store keys inside the repository. Set APPROVEACCEPT_HOME outside it.')
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_suffix('.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write('# ApproveAccept local keys. Sandbox only. Do not commit or share.\n')
        for k, v in values.items():
            f.write(f"export {k}='{v}'\n")
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def tty(text):
    try:
        with open('/dev/tty', 'w') as t:
            t.write(text)
    except OSError:
        sys.stderr.write('No terminal attached: read the owner key from the saved file when you need it.\n')


def main():
    offline = os.environ.get('APPROVEACCEPT_BYOK_OFFLINE') == '1'  # tests only: skip the PayPal check
    print('Step 0 · Connect PayPal Sandbox. Get keys at developer.paypal.com > Apps & Credentials > Sandbox.')
    client = ask('Sandbox client ID (hidden): ')
    secret = ask('Sandbox client secret (hidden): ')
    merchant = ask('Sandbox merchant ID, or Enter to look it up: ', hidden=False)
    model_key = ask('Anthropic API key for AI ranking (hidden), or Enter to skip: ')
    if not client or not secret:
        raise SystemExit('Both the client ID and the secret are required.')
    if offline:
        merchant = merchant or 'OFFLINETESTMERCHANT'
    else:
        token = verify(client, secret)
        print('Keys accepted by PayPal Sandbox.')
        if not merchant:
            merchant = derive_merchant(token)
    if model_key and not offline:
        verify_model_key(model_key)
        print('Model key accepted by the Anthropic API.')
    elif not model_key:
        print('No model key: ideas will be ranked by the local matcher and labelled "No AI".')
    path = home() / 'sandbox.env'
    owner, agent = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    write_env(path, {
        'APPROVEACCEPT_PAYPAL_SANDBOX_CLIENT_ID': client,
        'APPROVEACCEPT_PAYPAL_SANDBOX_CLIENT_SECRET': secret,
        'APPROVEACCEPT_PAYPAL_SANDBOX_MERCHANT_ID': merchant,
        'APPROVEACCEPT_OWNER_TOKEN': owner,
        'APPROVEACCEPT_AGENT_TOKEN': agent,
        'APPROVEACCEPT_AGENT_NAME': AGENT_NAME,
        'APPROVEACCEPT_LIVE_MONEY_ENABLED': 'false',
        **({'APPROVEACCEPT_ANTHROPIC_API_KEY': model_key} if model_key else {}),
    })
    print(f'Saved to {path} (mode 600, outside the repository).')
    print(f'Payments go to your own Sandbox business account {merchant}.')
    print(f'Connect your agent: point an MCP client at mcp_server.py with AA_URL set and the agent key from that file, agent name "{AGENT_NAME}".')
    tty(f'\nOwner sign-in key (shown once, not saved in any log):\n{owner}\n\n')
    print('Next: ./journey.sh, then open the printed /journey link and sign in with the owner key.')


if __name__ == '__main__':
    main()
