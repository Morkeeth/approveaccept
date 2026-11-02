import secrets
"""Security regressions use isolated real HTTP, MCP and WebAuthn signatures, no providers."""
import unittest,secrets,json
from unittest.mock import patch,Mock
import test_build as tb
app=tb.app

class CaptureGate(unittest.TestCase):
 def hold(self,source):
  if source=='MCP':return app.agent_request({'request_key':secrets.token_hex(16),'agent':'Concierge','sku':'cine2','link':'E1','why':'A quiet film.','task':'Film night'})
  with patch.object(app,'llm',return_value=({'sku':'cine2','why':'A quiet film.'},'')):
   result=app.propose('Film night','Concierge','E1')
  app.fund(result['id']);return result
 def test_http_and_telegram_cannot_capture_any_manual_prefix(self):
  import telegram_approve
  for source in ('MCP','P'):
   for channel in ('http','telegram'):
    with self.subTest(source=source,channel=channel):
     held=self.hold(source);self.assertTrue(held['id'].startswith(source));pid=held['id']
     if channel=='http':self.assertEqual(tb.post(tb.BASE+'/api/decide',{'id':pid,'accept':True})[0],409)
     else:
      bot=telegram_approve.Bot(app,'http://127.0.0.1:1','TEST','4242');bot.call=Mock(return_value=True)
      bot.tap({'id':'fake','data':'a:'+pid,'from':{'id':4242},'message':{'chat':{'id':4242},'message_id':1}})
     self.assertEqual(app.S.book.get(pid)['state'],'authorized')
 def test_real_purchase_bound_passkey_allows_both_prefixes(self):
  for source in ('MCP','P'):
   with self.subTest(source=source):
    held=self.hold(source);url=app.approval_link(held['id']);token=url.split('token=')[1]
    result=app.phone_decide(token,'approve',tb.approval_assertion(token));self.assertEqual(result['state'],'captured')
 def test_manual_flag_is_stored_and_automatic_is_explicit(self):
  held=self.hold('MCP')
  with app.S.db() as db:
   row=dict(db.execute('SELECT * FROM proposals WHERE id=?',(held['id'],)).fetchone())
  self.assertEqual(row.get('requires_passkey'),1)
  app.grant_allowance({'agent':'Security auto','merchants':['API Foundry'],'per_purchase_cents':1000,'monthly_cents':10000,'days':1})
  automatic=app.generic_agent_request({'request_key':secrets.token_hex(16),'agent':'Security auto','title':'Logs','merchant':'API Foundry','category':'software','cents':100,'why':'Build logs','task':'Build'})
  self.assertEqual(automatic['state'],'captured')
  with app.S.db() as db:self.assertEqual(db.execute('SELECT requires_passkey FROM proposals WHERE id=?',(automatic['id'],)).fetchone()[0],0)
 def test_legacy_proposals_migrate_to_passkey_required(self):
  import tempfile
  from pathlib import Path
  with tempfile.TemporaryDirectory() as folder,patch.object(app,'DATA',Path(folder)):
   old=app.State()
   with old.db() as db:
    db.execute("INSERT INTO proposals(id,agent,title,cents,link) VALUES ('legacy-manual','Concierge','Film',2600,'E1')")
    db.execute('ALTER TABLE proposals DROP COLUMN requires_passkey')
   migrated=app.State()
   with migrated.db() as db:self.assertEqual(db.execute("SELECT requires_passkey FROM proposals WHERE id='legacy-manual'").fetchone()[0],1)

class RequestKeys(unittest.TestCase):
 def setUp(self):app.grant_allowance({'agent':'Retry agent','merchants':['API Foundry'],'per_purchase_cents':1000,'monthly_cents':20000,'days':1})
 def payload(self,**more):return {'request_key':secrets.token_hex(16),'agent':'Retry agent','title':'Logs','merchant':'API Foundry','category':'software','cents':100,'why':'Need logs','task':'Build',**more}
 def test_generic_requires_key_and_retries_same_capture(self):
  body=self.payload();missing={k:v for k,v in body.items() if k!='request_key'}
  self.assertEqual(tb.post(tb.BASE+'/api/purchase',missing)[0],409)
  first=tb.post(tb.BASE+'/api/purchase',body);second=tb.post(tb.BASE+'/api/purchase',body)
  self.assertEqual(first[0],200);self.assertEqual(second,first)
  self.assertEqual(tb.post(tb.BASE+'/api/purchase',{**body,'cents':101})[0],409)
 def test_catalog_mcp_requires_key_and_reuses_one_hold(self):
  m=tb.MCP()
  try:
   args={'agent':'Concierge','sku':'cine2','link':'E1','why':'Film','task':'Date'}
   def call(a):return json.loads(m.rpc('tools/call',{'name':'request_purchase','arguments':a})['content'][0]['text'])
   self.assertIn('error',call(args));args['request_key']=secrets.token_hex(16);first=call(args);second=call(args)
   self.assertEqual(first['id'],second['id']);self.assertEqual(first['state'],'authorized')
   self.assertIn('error',call({**args,'sku':'jazz2'}))
  finally:m.close()
 def test_concurrent_http_retries_only_one_purchase(self):
  import concurrent.futures
  body=self.payload();
  with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:tb.post(tb.BASE+'/api/purchase',body),range(4)))
  self.assertTrue(all(x[0]==200 for x in results));self.assertEqual(len({x[1]['id'] for x in results}),1)
 def test_uncertain_operation_does_not_retry_provider(self):
  body=self.payload()
  with patch.object(app.S.leash,'card_hold',side_effect=app.Refused('Injected uncertain hold')) as hold:
   with self.assertRaises(app.Refused):app.generic_agent_request(body)
   with self.assertRaises(app.Refused):app.generic_agent_request(body)
   self.assertEqual(hold.call_count,1)

class HardenedModelLauncher(unittest.TestCase):
 def test_legacy_and_merchant_paths_disable_tools_and_strip_payment_secrets(self):
  import os,subprocess,merchant_catalog as merchant
  seen=[]
  def fake_run(command,**kwargs):
   seen.append((command,kwargs));data={'ranked':[{'sku':'notebook','preference_quote':'writing','fact_keys':['title'],'action_id':'gift-notebook'}]} if 'Rank these' in kwargs.get('input','') else {'sku':'cine2','why':'Quiet film'}
   text=json.dumps({'result':json.dumps(data),'modelUsage':{'fixture-model':{}}}) if '--output-format' in command else json.dumps(data)
   return subprocess.CompletedProcess(command,0,text,'')
  item={'sku':'notebook','title':'Notebook','product_type':'Carnet','tags':'paper','cents':1400,'quote':{'handle':merchant.HANDLES[0],'source_url':'https://merci-merci.com/products/'+merchant.HANDLES[0]}}
  sentinel={'APPROVEACCEPT_PAYPAL_SANDBOX_CLIENT_SECRET':'TEST-SENTINEL','APPROVEACCEPT_OWNER_TOKEN':'TEST-SENTINEL','AA_TELEGRAM_TOKEN':'TEST-SENTINEL','ANTHROPIC_API_KEY':'TEST-SENTINEL','UNRELATED_SECRET':'TEST-SENTINEL'}
  with patch.dict(os.environ,sentinel),patch('subprocess.run',side_effect=fake_run):
   app.llm('Return the catalog choice as JSON only.')
   merchant.rank_with_ai([item],'Likes writing','gift',app.DATA)
   for command,kwargs in seen:
    effective=kwargs.get('env',os.environ)
    for key in sentinel:self.assertFalse(key in effective,'Credential variable inherited: '+key)
    self.assertIn('--tools',command);self.assertEqual(command[command.index('--tools')+1],'')
    self.assertIn('--strict-mcp-config',command);self.assertTrue(json.loads(command[command.index('--settings')+1])['disableAllHooks'])
    self.assertEqual(effective['CLAUDE_CODE_DISABLE_ATTACHMENTS'],'1')
 def test_real_child_gets_no_app_credentials(self):
  import tempfile,os,sys
  from pathlib import Path
  import llm_launcher
  with tempfile.TemporaryDirectory() as folder:
   cli=Path(folder)/'claude';cli.write_text('#!'+sys.executable+'\nimport os,sys,json\nr={"secret_present":any(k.startswith(("APPROVEACCEPT_","AA_TELEGRAM","PAYPAL_")) or k.endswith("_SECRET") for k in os.environ),"tools_disabled":"--tools" in sys.argv and sys.argv[sys.argv.index("--tools")+1]=="","mcp_disabled":"--strict-mcp-config" in sys.argv}\nprint(json.dumps({"result":json.dumps(r)}))\n');cli.chmod(0o700)
   with patch.dict(os.environ,{'APPROVEACCEPT_PAYPAL_SANDBOX_CLIENT_SECRET':'TEST-SENTINEL','UNRELATED_SECRET':'TEST-SENTINEL'}),patch.object(llm_launcher,'CLAUDE_BINARY',str(cli)):
    result,_=llm_launcher.run_json('Inspect only the fixture environment.','haiku',Path(folder))
   self.assertEqual(result,{'secret_present':False,'tools_disabled':True,'mcp_disabled':True})
