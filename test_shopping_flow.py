"""Real loopback HTTP against isolated substitute data, never live payment credentials."""
import concurrent.futures,http.cookiejar,json,os,secrets,socket,sqlite3,subprocess,sys,tempfile,time,unittest,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parent
class ShoppingFlow(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory();cls.data=Path(cls.tmp.name);sock=socket.socket();sock.bind(('127.0.0.1',0));cls.port=sock.getsockname()[1];sock.close();cls.base='http://127.0.0.1:'+str(cls.port)
  env=os.environ.copy()
  for k in list(env):
   if k.endswith('_API_KEY') or k.startswith(('PAYPAL_','AA_TELEGRAM','ANTHROPIC_','OPENAI_','APPROVEACCEPT_')):env.pop(k,None)
  env.update(LEASH_V2_SUBSTITUTE='1',LEASH_V2_DATA=str(cls.data),LEASH_V2_PORT=str(cls.port),APPROVEACCEPT_PASSKEY_ORIGIN='https://approve.example.test',APPROVEACCEPT_OWNER_TOKEN='synthetic-shopping-owner-'+32*'o')
  cls.log=(cls.data/'server.log').open('w');cls.proc=subprocess.Popen([sys.executable,'-B',str(ROOT/'app.py')],cwd=ROOT,env=env,stdout=cls.log,stderr=cls.log)
  for _ in range(100):
   try:
    urllib.request.urlopen(cls.base+'/health',timeout=1).read();break
   except Exception:time.sleep(.05)
  else:raise RuntimeError('Owned substitute server did not start')
 @classmethod
 def tearDownClass(cls):cls.proc.terminate();cls.proc.wait(timeout=5);cls.log.close();cls.tmp.cleanup()
 def req(self,path,data=None):
  request=urllib.request.Request(self.base+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json','Origin':self.base,'Authorization':'Bearer synthetic-shopping-owner-'+32*'o'})
  try:
   with urllib.request.urlopen(request,timeout=10) as r:return r.status,json.load(r)
  except urllib.error.HTTPError as e:return e.code,json.load(e)
 def setup(self,automatic=True):
  status,result=self.req('/api/shopping/setup',{'per_purchase_cents':6000,'monthly_cents':20000,'days':7,'automatic':automatic,'persona':'Live jazz, vegetarian, books. No horror.'});self.assertEqual(status,200);return result
 def ideas(self,mode='date',**more):
  return self.req('/api/ideas',{'mode':mode,'request_key':secrets.token_hex(12),**more})
 def test_payment_setup_is_real_gate_and_invalid_limits_rejected(self):
  with sqlite3.connect(self.data/'state.db') as db:db.execute("DELETE FROM kv WHERE k='shopping_setup'")
  code,state=self.req('/api/shopping/status');self.assertEqual(code,200);self.assertFalse(state['ready']);self.assertEqual(self.ideas()[0],409)
  self.assertEqual(self.req('/api/shopping/setup',{'per_purchase_cents':100,'monthly_cents':1,'days':7,'automatic':True})[0],409)
  self.assertTrue(self.setup()['ready'])
 def test_mode_options_are_frozen_server_quotes_with_reasons(self):
  self.setup();status,session=self.ideas();self.assertEqual(status,200);self.assertGreaterEqual(len(session['ideas']),2)
  self.assertTrue(all(x['quote']['source']=='ApproveAccept Sandbox catalog' and x['why'] for x in session['ideas']))
  self.assertEqual(len({x['sku'] for x in session['ideas']}),len(session['ideas']))
  self.assertTrue(all('horror' not in x['title'].lower() for x in session['ideas']))
 def test_auto_choice_and_retries_reuse_one_purchase(self):
  self.setup();key=secrets.token_hex(12);body={'mode':'date','request_key':key,'buy_automatically':True}
  code,session=self.req('/api/ideas',body);self.assertEqual(code,200);self.assertEqual(session['purchase']['state'],'captured');pid=session['purchase']['id']
  again=self.req('/api/ideas',body)[1];self.assertEqual(again['purchase']['id'],pid)
  reply=self.req('/api/ideas/choose',{'session_id':session['id'],'sku':session['chosen_sku'],'buy_automatically':True})[1];self.assertEqual(reply['id'],pid)
  self.assertTrue(reply['capture_id'].startswith('SUB-'))
 def test_opt_in_and_live_allowance_are_checked_before_automatic_purchase(self):
  self.setup(False);code,_=self.ideas(buy_automatically=True);self.assertEqual(code,409)
  self.setup();self.req('/api/allowance-revoke',{'agent':'Shopping agent'});code,result=self.ideas(buy_automatically=True);self.assertEqual(code,409)
 def test_client_cannot_choose_unknown_sku_or_supply_a_price(self):
  self.setup();code,session=self.ideas('gift');self.assertEqual(code,200)
  self.assertEqual(self.req('/api/ideas/choose',{'session_id':session['id'],'sku':'forged','buy_automatically':True})[0],409)
  self.assertEqual(self.req('/api/ideas/choose',{'session_id':session['id'],'sku':session['ideas'][0]['sku'],'cents':1,'buy_automatically':True})[0],409)

 def test_concurrent_retries_capture_once_and_changed_choice_is_refused(self):
  self.setup();key=secrets.token_hex(12);body={'mode':'date','request_key':key,'buy_automatically':True}
  with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:self.req('/api/ideas',body),range(4)))
  self.assertEqual([r[0] for r in results],[200]*4);self.assertEqual(len({r[1]['purchase']['id'] for r in results}),1)
  session=results[0][1];other=next(i['sku'] for i in session['ideas'] if i['sku']!=session['chosen_sku'])
  self.assertEqual(self.req('/api/ideas/choose',{'session_id':session['id'],'sku':other,'buy_automatically':True})[0],409)
  self.assertEqual(self.req('/api/ideas',{**body,'mode':'gift'})[0],409)
 def test_expired_quote_and_interrupted_purchase_fail_closed(self):
  self.setup();_,session=self.ideas()
  with sqlite3.connect(self.data/'state.db') as db:
   session['ideas'][0]['quote']['expires_at']=0;db.execute('UPDATE shopping_sessions SET value=? WHERE id=?',(json.dumps(session),session['id']))
  body={'session_id':session['id'],'sku':session['ideas'][0]['sku'],'buy_automatically':True}
  self.assertEqual(self.req('/api/ideas/choose',body)[0],409)
  session.update(attempted=True,chosen_sku=body['sku'],chosen_auto=True)
  with sqlite3.connect(self.data/'state.db') as db:db.execute('UPDATE shopping_sessions SET value=? WHERE id=?',(json.dumps(session),session['id']))
  code,result=self.req('/api/ideas/choose',body);self.assertEqual(code,409);self.assertIn('reconciliation',result['error'])
 def test_manual_choice_holds_without_automatic_opt_in(self):
  self.setup(False);_,session=self.ideas('gift');code,result=self.req('/api/ideas/choose',{'session_id':session['id'],'sku':session['ideas'][0]['sku'],'buy_automatically':False})
  self.assertEqual(code,200);self.assertEqual(result['state'],'authorized');self.assertIn('approval_url',result);self.assertNotIn('capture_id',result)
 def test_journey_over_limit_choice_becomes_one_face_id_hold(self):
  self.setup();_,session=self.ideas('gift');over=next(x for x in session['ideas'] if x['cents']>6000)
  body={'session_id':session['id'],'sku':over['sku'],'buy_automatically':True}
  self.assertEqual(self.req('/api/ideas/choose',body)[0],409)
  _,session=self.ideas('gift');body={'session_id':session['id'],'sku':over['sku'],'buy_automatically':True,'owner_review_if_over':True}
  code,result=self.req('/api/ideas/choose',body);self.assertEqual(code,200)
  self.assertEqual(result['state'],'authorized');self.assertIn('approval_url',result);self.assertNotIn('capture_id',result)
  self.assertTrue(any('per purchase' in r for r in result['over_limit_reasons']))
  self.assertEqual(self.req('/api/ideas/choose',body)[1]['id'],result['id'])
  self.assertEqual(self.req('/api/ideas/choose',{**body,'owner_review_if_over':'yes'})[0],409)
 def test_journey_under_limit_choice_still_captures_automatically(self):
  self.setup();_,session=self.ideas('gift');under=next(x for x in session['ideas'] if x['cents']<=6000)
  code,result=self.req('/api/ideas/choose',{'session_id':session['id'],'sku':under['sku'],'buy_automatically':True,'owner_review_if_over':True})
  self.assertEqual(code,200);self.assertEqual(result['state'],'captured');self.assertTrue(result['capture_id'].startswith('SUB-'))
 def test_journey_with_automatic_off_holds_without_an_over_limit_label(self):
  self.setup(False);_,session=self.ideas('gift');under=next(x for x in session['ideas'] if x['cents']<=6000)
  code,result=self.req('/api/ideas/choose',{'session_id':session['id'],'sku':under['sku'],'buy_automatically':True,'owner_review_if_over':True})
  self.assertEqual(code,200);self.assertEqual(result['state'],'authorized');self.assertNotIn('over_limit_reasons',result)
 def test_ai_source_without_model_key_falls_back_with_an_honest_label(self):
  self.setup();code,session=self.ideas('surprise',source='ai');self.assertEqual(code,200)
  self.assertFalse(session['ranking']['ai']);self.assertIn('No model key',session['ranking']['fallback_reason'])
  self.assertIn('Local preference matching',session['ranking']['method'])
  self.assertTrue(all(x['why'] and 'reason_evidence' not in x and '\u201c' not in x['why'] for x in session['ideas']))
  status=self.req('/api/shopping/status')[1];self.assertFalse(status['ai_ranking']['ready'])
