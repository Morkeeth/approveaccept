"""Prepare a private, isolated PayPal Sandbox run; no provider/network call."""
import os
from pathlib import Path
import secrets
import shlex
import socket
import sys
import tempfile
from urllib.parse import urlsplit


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python3 -B connect/prepare_fresh_run.py https://EXACT-HTTPS-HOST')
    origin = sys.argv[1].rstrip('/')
    url = urlsplit(origin)
    if url.scheme != 'https' or not url.hostname or url.path or url.query or url.fragment or url.username:
        raise SystemExit('Pass one exact HTTPS origin, with no path, query, or credentials')
    for port in (8891, 8892, 8893):
        with socket.socket() as sock:
            try:
                sock.bind(('127.0.0.1', port))
            except OSError:
                raise SystemExit(f'Port {port} is already in use; stop the conflicting service first') from None
    base = Path(os.environ.get('AA_RUN_BASE', Path.home() / '.config' / 'approveaccept' / 'runs'))
    base.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='paypal-judge-fresh-', dir=base))
    os.chmod(directory, 0o700)
    values = {
        'AA_DATA_DIR': str(directory), 'PORT': '8891', 'AA_BACKEND_PORT': '8892',
        'LEASH_V2_WEBHOOK_PORT': '8893', 'AA_DESIGN_HOST': '127.0.0.1',
        'APPROVEACCEPT_PUBLIC_BASE_URL': origin, 'APPROVEACCEPT_PASSKEY_ORIGIN': origin,
        'APPROVEACCEPT_OWNER_TOKEN': secrets.token_hex(32),
        'APPROVEACCEPT_AGENT_TOKEN': secrets.token_hex(32),
        'APPROVEACCEPT_AGENT_NAME': 'Build agent',
        'APPROVEACCEPT_GUIDED_DEMO': '0',
        'APPROVEACCEPT_LIVE_MONEY_ENABLED': 'false',
    }
    merchant = os.environ.get('APPROVEACCEPT_PAYPAL_SANDBOX_MERCHANT_ID', '').strip()
    if merchant:
        values['APPROVEACCEPT_PAYPAL_SANDBOX_MERCHANT_ID'] = merchant
    lines = ['# Private sandbox run. Source from the same trusted shell; do not share.\n',
             'unset LEASH_V2_SUBSTITUTE\n']
    lines += [f'export {name}={shlex.quote(value)}\n' for name, value in values.items()]
    file = directory / 'env.sh'
    descriptor = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as handle:
        handle.writelines(lines)
    agent_file = directory / 'agent-env.sh'
    agent_values = {'AA_URL': origin,
                    'APPROVEACCEPT_AGENT_TOKEN': values['APPROVEACCEPT_AGENT_TOKEN'],
                    'APPROVEACCEPT_AGENT_NAME': values['APPROVEACCEPT_AGENT_NAME'],
                    'AA_CLIENT': 'Codex'}
    descriptor = os.open(agent_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as handle:
        handle.write('unset APPROVEACCEPT_OWNER_TOKEN\n')
        handle.writelines(f'export {name}={shlex.quote(value)}\n' for name, value in agent_values.items())
    print('Prepared fresh sandbox data:', directory)
    print('Private environment file:', file)
    print('Agent-only environment file:', agent_file)
    print('Exact owner/passkey origin:', origin)
    print('No PayPal call or purchase was made.')


if __name__ == '__main__':
    main()
