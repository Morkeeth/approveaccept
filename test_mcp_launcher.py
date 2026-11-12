"""The .mcp.json launcher starts for a newcomer and still reads a prepared run file."""
import json, os, subprocess, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAUNCHER = HERE / 'connect' / 'agent_mcp.sh'
CLEAN = {k: v for k, v in os.environ.items()
         if not k.startswith(('APPROVEACCEPT_', 'AA_'))}


def session(env, calls):
    p = subprocess.Popen(['sh', str(LAUNCHER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, env=env, cwd=str(HERE))
    msgs = [{'jsonrpc': '2.0', 'id': 0, 'method': 'initialize',
             'params': {'protocolVersion': '2024-11-05', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '0'}}}]
    msgs += [{'jsonrpc': '2.0', 'id': i + 1, 'method': m, 'params': prm} for i, (m, prm) in enumerate(calls)]
    out, err = p.communicate('\n'.join(json.dumps(m) for m in msgs) + '\n', timeout=30)
    return [json.loads(line) for line in out.splitlines() if line.strip()], err, p.returncode


def text(reply):
    return json.loads(reply['result']['content'][0]['text'])


class Launcher(unittest.TestCase):
    def test_newcomer_gets_tools_and_a_plain_key_message(self):
        replies, err, _ = session(dict(CLEAN), [('tools/list', {}),
                                                ('tools/call', {'name': 'spending_policy', 'arguments': {'agent': 'x'}})])
        self.assertEqual(len(replies[1]['result']['tools']), 5)
        self.assertIn('No agent key', text(replies[2])['error'])
        self.assertIn('Agents tab', err)

    def test_newcomer_with_key_points_at_the_local_demo(self):
        env = dict(CLEAN, APPROVEACCEPT_AGENT_TOKEN='k' * 20, AA_URL='http://127.0.0.1:9')
        replies, err, _ = session(env, [('tools/call', {'name': 'spending_policy', 'arguments': {'agent': 'x'}})])
        self.assertEqual(text(replies[1])['error'], 'ApproveAccept is not running at http://127.0.0.1:9')
        self.assertEqual(err, '')
        replies, _, _ = session(dict(CLEAN, APPROVEACCEPT_AGENT_TOKEN='k' * 20),
                                [('tools/call', {'name': 'spending_policy', 'arguments': {'agent': 'x'}})])
        self.assertIn('127.0.0.1:8780', text(replies[1]).get('error', '127.0.0.1:8780'))

    def test_prepared_run_file_is_still_read(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'agent-env.sh'
            f.write_text("export AA_URL=http://127.0.0.1:10\nexport APPROVEACCEPT_AGENT_TOKEN=abcdefabcdefabcdef\n")
            replies, _, _ = session(dict(CLEAN, AA_AGENT_ENV_FILE=str(f)),
                                    [('tools/call', {'name': 'spending_policy', 'arguments': {'agent': 'x'}})])
            self.assertEqual(text(replies[1])['error'], 'ApproveAccept is not running at http://127.0.0.1:10')

    def test_relative_run_file_is_refused(self):
        _, err, code = session(dict(CLEAN, AA_AGENT_ENV_FILE='agent-env.sh'), [])
        self.assertNotEqual(code, 0)
        self.assertIn('absolute path', err)

    def test_owner_key_never_reaches_the_agent_server(self):
        env = dict(CLEAN, APPROVEACCEPT_OWNER_TOKEN='owner', APPROVEACCEPT_AGENT_TOKEN='')
        replies, _, _ = session(env, [('tools/call', {'name': 'spending_policy', 'arguments': {'agent': 'x'}})])
        self.assertIn('No agent key', text(replies[1])['error'])


if __name__ == '__main__':
    unittest.main()
