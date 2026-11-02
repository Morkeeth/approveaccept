"""Actual loopback listener access boundaries; substitute payments only."""
import json,unittest,urllib.request,urllib.error
from unittest.mock import patch
import test_build as tb
app=tb.app
class LoopbackAuth(unittest.TestCase):
 def request(self,path='/api/state',body=None,origin=None,token=None):
  headers={'Content-Type':'application/json'}
  if origin is not None:headers['Origin']=origin
  if token:headers['Authorization']='Bearer '+token
  req=urllib.request.Request(tb.BASE+path,json.dumps(body).encode() if body is not None else None,headers)
  try:
   with urllib.request.urlopen(req) as r:return r.status,json.load(r)
  except urllib.error.HTTPError as e:return e.code,json.load(e)
 def test_private_reads_and_owner_writes_require_auth(self):
  with patch.dict('os.environ',APPROVEACCEPT_OWNER_TOKEN='synthetic-owner-'+32*'o'):
   self.assertEqual(self.request()[0],401)
   self.assertEqual(self.request('/api/shopping/status')[0],401)
   self.assertEqual(self.request('/api/persona',{'text':'forbidden'},tb.BASE)[0],401)
   self.assertEqual(self.request(token='synthetic-owner-'+32*'o')[0],200)
 def test_missing_null_and_foreign_origins_refused_even_with_owner_token(self):
  with patch.dict('os.environ',APPROVEACCEPT_OWNER_TOKEN='synthetic-owner-'+32*'o'):
   for origin in (None,'null','https://attacker.invalid'):
    self.assertEqual(self.request('/api/persona',{'text':'forbidden'},origin,'synthetic-owner-'+32*'o')[0],403)
   self.assertEqual(self.request('/api/persona',{'text':'allowed'},tb.BASE,'synthetic-owner-'+32*'o')[0],200)
 def test_capability_routes_still_need_origin_and_valid_token(self):
  self.assertEqual(self.request('/api/phone-decision',{'token':'invalid','action':'approve'})[0],403)
  self.assertEqual(self.request('/api/phone-decision',{'token':'invalid','action':'approve'},tb.BASE)[0],409)
 def test_agent_cannot_read_owner_state_or_impersonate_other_agent(self):
  with patch.dict('os.environ',APPROVEACCEPT_AGENT_TOKEN='synthetic-agent-'+32*'a',APPROVEACCEPT_AGENT_NAME='Bound agent'):
   key='synthetic-agent-'+32*'a'
   self.assertEqual(self.request(token=key)[0],401)
   self.assertEqual(self.request('/api/agent/policy?agent=Other',token=key)[0],403)
   self.assertEqual(self.request('/api/agent/policy?agent=Bound%20agent',token=key)[0],200)
   self.assertEqual(self.request('/api/purchase',{'agent':'Other'},tb.BASE,key)[0],403)
 def test_owner_session_signin_and_signout(self):
  key='synthetic-owner-'+32*'o'
  with patch.dict('os.environ',APPROVEACCEPT_OWNER_TOKEN=key):
   self.assertEqual(self.request('/api/session',{'token':key})[0],403)
   req=urllib.request.Request(tb.BASE+'/api/session',json.dumps({'token':key}).encode(),{'Content-Type':'application/json','Origin':tb.BASE})
   with urllib.request.urlopen(req) as r:cookie=r.headers['Set-Cookie'].split(';')[0]
   req=urllib.request.Request(tb.BASE+'/api/state',headers={'Cookie':cookie})
   with urllib.request.urlopen(req) as r:self.assertEqual(json.load(r)['access'],'owner')
   req=urllib.request.Request(tb.BASE+'/api/session/end',b'{}',{'Origin':tb.BASE,'Cookie':cookie})
   urllib.request.urlopen(req).close()
   with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(urllib.request.Request(tb.BASE+'/api/state',headers={'Cookie':cookie}))
   self.assertEqual(caught.exception.code,401)

 def test_unconfigured_keys_fail_closed_and_agent_status_is_scoped(self):
  with patch.dict('os.environ',APPROVEACCEPT_OWNER_TOKEN='',APPROVEACCEPT_AGENT_TOKEN=''):
   self.assertEqual(self.request(token='arbitrary')[0],401)
  with patch.dict('os.environ',APPROVEACCEPT_AGENT_TOKEN='synthetic-agent-'+32*'a',APPROVEACCEPT_AGENT_NAME='Bound agent'):
   key='synthetic-agent-'+32*'a'
   self.assertEqual(self.request('/api/agent/status?id=unknown',token=key)[0],403)
   self.assertEqual(self.request('/api/allowance',{},tb.BASE,key)[0],401)
