"""Cookie-less buyer return on the actual listener. Substitute payments only."""
import concurrent.futures,json,time,unittest,urllib.parse,urllib.request,urllib.error
from unittest.mock import patch
import test_build as tb
app=tb.app
class _ReturnFixture(unittest.TestCase):
 def setUp(self):
  import tempfile
  from pathlib import Path
  from contextlib import ExitStack
  stack=ExitStack();self.addCleanup(stack.close);folder=stack.enter_context(tempfile.TemporaryDirectory(prefix='buyer-return-test-'));stack.enter_context(patch.object(app,'DATA',Path(folder)));stack.enter_context(patch.object(app,'S',app.State()))
class BuyerReturn(_ReturnFixture):
 def order(self):
  pid='R'+str(time.time_ns());r=app.admit(pid,app.agent('Concierge'),'test','cine2','Cinema',2600,app.SHOP,'E1','why','-');return pid,r['order_id'],app.SUB.return_urls[r['order_id']]
 def get(self,url):
  try:
   with urllib.request.urlopen(url) as r:return r.status,r.read().decode(),dict(r.headers)
  except urllib.error.HTTPError as e:return e.code,e.read().decode(),dict(e.headers)
 def test_return_without_owner_cookie_verifies_order_but_never_captures(self):
  pid,oid,url=self.order();app.SUB.approve(oid)
  status,body,h=self.get(url+'&token='+oid);self.assertEqual(status,200);self.assertIn('awaiting owner approval',body)
  self.assertEqual(app.S.book.get(pid)['state'],'authorized');self.assertNotIn(oid,body);self.assertNotIn(pid,body);self.assertEqual(h['Referrer-Policy'],'no-referrer')
  with self.assertRaises(app.Refused):app.decide(pid,True)
  self.assertEqual(self.get(tb.BASE+'/api/state')[0],401);self.assertEqual(self.get(url+'&token='+oid)[0],404)
 def test_bare_id_forged_expired_mismatched_and_replayed_returns_cannot_authorize(self):
  pid,oid,url=self.order();self.assertEqual(self.get(tb.BASE+'/return?pid='+pid)[0],404);self.assertEqual(self.get(tb.BASE+'/return?receipt=forged&token='+oid)[0],404)
  self.assertEqual(self.get(url+'&token=OTHER-ORDER')[0],404);self.assertEqual(app.S.book.get(pid)['state'],'buyer_approval')
  token=urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['receipt'][0]
  with patch('buyer_returns.time.time',return_value=time.time()+1900):self.assertEqual(self.get(url+'&token='+oid)[0],404)
  self.assertEqual(app.S.book.get(pid)['state'],'buyer_approval')
 def test_unapproved_order_is_not_made_approved_by_return(self):
  pid,oid,url=self.order();status,body,_=self.get(url+'&token='+oid);self.assertEqual(status,409);self.assertIn('not confirmed',body);self.assertEqual(app.SUB.orders[oid]['status'],'CREATED');self.assertEqual(app.S.book.get(pid)['state'],'buyer_approval')
 def test_forged_return_never_enters_global_lock(self):
  class ForbiddenLock:
   def __enter__(self):raise AssertionError('Forged return took global lock')
   def __exit__(self,*args):pass
  with patch.object(app,'LOCK',ForbiddenLock()):self.assertEqual(self.get(tb.BASE+'/return?receipt=forged')[0],404)
 def test_provider_calls_do_not_hold_global_lock(self):
  pid,oid,url=self.order();app.SUB.approve(oid);original=app.S.leash.authorize;observed=[]
  def authorize(request_id):
   acquired=app.LOCK.acquire(blocking=False);observed.append(acquired)
   if acquired:app.LOCK.release()
   return original(request_id)
  with patch.object(app.S.leash,'authorize',side_effect=authorize):self.assertEqual(self.get(url+'&token='+oid)[0],200)
  self.assertEqual(observed,[True], 'Provider work must leave global lock free')
 def test_return_racing_a_verified_webhook_authorizes_only_once(self):
  import threading
  pid,oid,url=self.order();app.SUB.approve(oid);barrier=threading.Barrier(2);original=app.SUB.call;authorizations=[]
  def call(path,data=None,request_id=None,method='POST'):
   if path=='/v2/checkout/orders/'+oid and method=='GET':
    value=original(path,data,request_id,method);barrier.wait(timeout=3);return value
   if path=='/v2/checkout/orders/'+oid+'/authorize':authorizations.append(request_id)
   return original(path,data,request_id,method)
  event={'id':'WH-RACE-'+pid,'event_type':'CHECKOUT.ORDER.APPROVED','resource':{'id':oid,'status':'APPROVED'}}
  with patch.object(app.SUB,'call',side_effect=call),concurrent.futures.ThreadPoolExecutor(2) as pool:
   callback=pool.submit(self.get,url+'&token='+oid);webhook=pool.submit(app.paypal_event,event)
   self.assertIn(callback.result(timeout=8)[0],(200,409));self.assertTrue(webhook.result(timeout=8)['new'])
  self.assertEqual(authorizations,[pid+':authorize']);self.assertEqual(app.S.book.get(pid)['state'],'authorized')
 def test_cancel_and_concurrent_callbacks(self):
  pid,oid,url=self.order();status,body,_=self.get(url+'&cancel=1&token='+oid);self.assertEqual(status,200);self.assertIn('cancelled',body);self.assertEqual(app.S.book.get(pid)['state'],'buyer_approval')
  pid,oid,url=self.order();app.SUB.approve(oid)
  with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:self.get(url+'&token='+oid)[0],range(2)))
  self.assertEqual(sorted(results),[200,404]);self.assertEqual(app.S.book.get(pid)['state'],'authorized')

class PublicBuyerReturn(_ReturnFixture):
 def test_public_ingress_passes_capability_without_owner_credentials(self):
  import importlib.util,threading
  from http.server import ThreadingHTTPServer
  spec=importlib.util.spec_from_file_location('return_frontend',tb.APP_DIR/'design/server.py');web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web);web.UPSTREAM_ROOT=tb.BASE
  server=ThreadingHTTPServer(('127.0.0.1',0),web.H);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   base='http://127.0.0.1:'+str(server.server_port)
   with patch.object(app,'PUBLIC_BASE',base):pid,oid,url=BuyerReturn().order()
   app.SUB.approve(oid);self.assertTrue(url.startswith(base+'/return?receipt='))
   seen=[];original=app.H.buyer_return
   def inspect_headers(handler):
    seen.append(handler.headers.get('Authorization'));return original(handler)
   with patch.object(web,'AGENT_TOKEN','synthetic-agent-'+32*'a'),patch.object(app.H,'buyer_return',inspect_headers):
    with urllib.request.urlopen(url+'&token='+oid) as r:self.assertEqual(r.status,200);self.assertIn('awaiting owner approval',r.read().decode())
   self.assertEqual(seen,[None], 'Capability return must forward no Authorization header')
   self.assertEqual(app.S.book.get(pid)['state'],'authorized')
  finally:server.shutdown();server.server_close();thread.join()
