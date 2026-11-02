"""Known pre-provider refusal may be retried; payment uncertainty never may."""
import secrets,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import test_build as tb
app=tb.app
class SafeRefusalRetry(unittest.TestCase):
 def setUp(self):
  from contextlib import ExitStack
  stack=ExitStack();self.addCleanup(stack.close)
  folder=stack.enter_context(tempfile.TemporaryDirectory(prefix='aa-retry-'))
  stack.enter_context(patch.object(app,'DATA',Path(folder)))
  stack.enter_context(patch.object(app,'S',app.State()))
 def body(self):return {'request_key':secrets.token_hex(16),'agent':'Retry rules','title':'Logs','merchant':'API Foundry','category':'software','cents':100,'why':'Build logs','task':'Build'}
 def test_low_level_spend_refusal_retries_same_intent_after_policy_change(self):
  body=self.body();app.S.ensure_agent_policy(body['agent'])
  with app.S.book.db() as db:db.execute('UPDATE policy SET purchase_cap=1 WHERE agent=?',(body['agent'],))
  with patch.object(app.S.leash,'card_hold',wraps=app.S.leash.card_hold) as hold:
   with self.assertRaises(app.Refused):app.generic_agent_request(body)
   self.assertEqual(hold.call_count,0)
   with self.assertRaises(app.Refused):app.generic_agent_request({**body,'cents':101})
   with app.S.book.db() as db:db.execute('UPDATE policy SET purchase_cap=1000 WHERE agent=?',(body['agent'],))
   result=app.generic_agent_request(body);self.assertIn(result['state'],('captured','authorized'))
   self.assertEqual(app.generic_agent_request(body),result);self.assertEqual(hold.call_count,1)
 def test_product_rule_block_retries_after_rules_change_without_rebinding_details(self):
  from spend_rules import SpendRules
  body=self.body();deny=SpendRules(frozenset({'other'}),{},10000)
  with patch.object(app.S.leash,'card_hold',wraps=app.S.leash.card_hold) as hold:
   result=app.generic_agent_request(body,rules=deny);self.assertEqual(result['state'],'blocked');self.assertEqual(hold.call_count,0)
   with self.assertRaises(app.Refused):app.generic_agent_request({**body,'cents':101})
   result=app.generic_agent_request(body);self.assertIn(result['state'],('captured','authorized'));self.assertEqual(hold.call_count,1)
 def test_catalog_known_refusal_retries_after_policy_change(self):
  body={'request_key':secrets.token_hex(16),'agent':'Concierge','sku':'cine2','link':'E1','why':'Quiet film','task':'Date'}
  with app.S.book.db() as db:db.execute("UPDATE policy SET purchase_cap=1 WHERE agent='Concierge'")
  first=app.agent_request(body);self.assertTrue(first['refused'])
  with app.S.book.db() as db:db.execute("UPDATE policy SET purchase_cap=100000 WHERE agent='Concierge'")
  self.assertEqual(app.agent_request(body)['state'],'authorized')
 def test_provider_uncertainty_retains_claim_across_state_reopen(self):
  body=self.body()
  with patch.object(app.S.leash,'card_hold',side_effect=app.Refused('Uncertain provider response')) as hold:
   with self.assertRaises(app.Refused):app.generic_agent_request(body)
   self.assertEqual(hold.call_count,1)
  app.S=app.State()
  with patch.object(app.S.leash,'card_hold') as hold:
   with self.assertRaises(app.Refused):app.generic_agent_request(body)
   self.assertEqual(hold.call_count,0)
