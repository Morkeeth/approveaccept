"""One tool-free subscription CLI boundary for all model calls.

Only runtime/locale variables are inherited. Application, payment, owner, bot and
provider credentials never enter the model process. No hooks, skills or MCP tools.
"""
import json,os,re,shutil,subprocess,time,tempfile

CLAUDE_BINARY=shutil.which('claude') or 'claude'
RUNTIME_ENV=frozenset({'HOME','PATH','USER','LOGNAME','SHELL','TMPDIR','TMP','TEMP','LANG','LC_ALL','LC_CTYPE','TERM','TZ'})


def run_json(prompt,model,cwd,timeout=60):
 env={k:v for k,v in os.environ.items() if k in RUNTIME_ENV}
 env.update(CLAUDE_CODE_DISABLE_AUTO_MEMORY='1',CLAUDE_CODE_DISABLE_ATTACHMENTS='1')
 command=[CLAUDE_BINARY,'-p','--model',model,'--tools','',
          '--settings','{"disableAllHooks":true,"autoMemoryEnabled":false}',
          '--strict-mcp-config','--mcp-config','{"mcpServers":{}}','--disable-slash-commands',
          '--setting-sources','','--no-session-persistence','--output-format','json']
 started=time.monotonic()
 try:
  with tempfile.TemporaryDirectory(prefix='approveaccept-model-') as isolated:
   proc=subprocess.run(command,input=prompt,capture_output=True,text=True,timeout=timeout,cwd=isolated,env=env)
 except (OSError,subprocess.SubprocessError):
  raise ValueError('Model launcher unavailable or timed out; no automatic retry.') from None
 if proc.returncode or len(proc.stdout)>1_000_000:
  raise ValueError('Model launcher failed; no automatic retry.')
 try:
  envelope=json.loads(proc.stdout)
  if envelope.get('is_error'):raise ValueError('Model error')
  match=re.search(r'\{.*\}',envelope['result'],re.S);result=json.loads(match.group(0))
  if not isinstance(result,dict):raise ValueError('Expected JSON object')
 except (ValueError,KeyError,TypeError,AttributeError):
  raise ValueError('Model did not return a valid JSON object.') from None
 return result,{'transport':'subscription CLI; runtime-only environment; tools/hooks/skills/MCP disabled',
                'requested_model':model,'reported_models':list(envelope.get('modelUsage',{})),
                'elapsed_seconds':round(time.monotonic()-started,2),'at_epoch':int(time.time())}
