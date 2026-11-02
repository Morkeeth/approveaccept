import unittest
from unittest.mock import patch
import merchant_catalog as m

class MerchantGrounding(unittest.TestCase):
 def test_no_arbitrary_url_and_currency_must_be_eur(self):
  with self.assertRaises(ValueError):m.read_json('https://example.com/product.js')
  with patch.object(m,'read_json',return_value={'currency':'USD'}):
   with self.assertRaises(ValueError):m.offers()
 def test_normalizes_actual_product_shape_and_rejects_unavailable(self):
  raw={'id':1,'title':'Notebook','handle':'carnet-merci-maison-beige','type':'Notebook','tags':['paper'],'variants':[{'id':2,'price':1400,'available':True,'title':'Beige'}]}
  item=m.normalize(raw,'carnet-merci-maison-beige','EUR');self.assertEqual(item['cents'],1400);self.assertEqual(item['quote']['variant_id'],2);self.assertTrue(item['quote']['source_url'].startswith('https://merci-merci.com/'))
  raw['variants'][0]['available']=False
  with self.assertRaises(ValueError):m.normalize(raw,'carnet-merci-maison-beige','EUR')
 def test_ai_cannot_invent_products_preferences_or_evidence(self):
  offers=[{'sku':'one','title':'Notebook','product_type':'Stationery','tags':'paper','cents':1400},{'sku':'two','title':'Pouch','product_type':'Pouch','tags':'linen','cents':3500}]
  for item in offers:item['quote']={'source_url':'https://merci-merci.com/products/carnet-merci-maison-beige'}
  valid={'ranked':[{'sku':'two','preference_quote':'linen','fact_keys':['tags']},{'sku':'one','preference_quote':'writing','fact_keys':['title']}]}
  out=m.apply_ranking(offers,'Likes linen and writing',valid);self.assertEqual(out[0]['sku'],'two');self.assertIn('linen',out[0]['why'])
  for result in [{'ranked':[{'sku':'invented','preference_quote':'linen','fact_keys':['tags']}]},{'ranked':[{'sku':'one','preference_quote':'cheapest in Paris','fact_keys':['reviews']}]}]:
   with self.assertRaises(ValueError):m.apply_ranking(offers,'Likes linen and writing',result)
 def test_revalidation_rejects_price_stock_variant_and_currency_drift(self):
  quote={'handle':'carnet-merci-maison-beige','variant_id':2,'cents':1400,'currency':'EUR'}
  current={'quote':{**quote},'title':'Notebook'}
  with patch.object(m,'fetch_offer',return_value=current):self.assertTrue(m.revalidate({'title':'Notebook','quote':quote}))
  for change in [{'cents':1500},{'variant_id':3},{'currency':'USD'}]:
   with patch.object(m,'fetch_offer',return_value={'quote':{**quote,**change},'title':'Notebook'}):
    with self.assertRaises(ValueError):m.revalidate({'title':'Notebook','quote':quote})
 def test_choose_merchant_drift_refuses_before_purchase_or_attempt(self):
  from types import SimpleNamespace
  from unittest.mock import Mock
  from shopping import Shopping
  from spend_rules import SpendRules
  import copy
  raw={'title':'Notebook','handle':m.HANDLES[0],'type':'Carnet','tags':[],
       'variants':[{'id':2,'price':1400,'available':True,'title':'Beige'}]}
  item=m.normalize(raw,m.HANDLES[0],'EUR')
  for change in ('price','stock','currency','expiry'):
   with self.subTest(change=change):
    a=SimpleNamespace(SpendRules=SpendRules,Refused=RuntimeError,SKU={},generic_agent_request=Mock())
    shopping=Shopping(a);shopping.require_setup=Mock(return_value={'automatic':True})
    chosen=copy.deepcopy(item);current=copy.deepcopy(raw);currency='EUR'
    if change=='price':current['variants'][0]['price']=1500
    if change=='stock':current['variants'][0]['available']=False
    if change=='currency':currency='USD'
    if change=='expiry':chosen['quote']['expires_at']=0
    shopping.load=Mock(return_value={'source':'merci','id':'session','ideas':[chosen]});shopping.save=Mock()
    def read(url):return {'currency':currency} if url.endswith('/cart.js') else current
    with patch.object(m,'read_json',side_effect=read):
     with self.assertRaisesRegex(RuntimeError,'Merchant recheck failed'):
      shopping.choose({'session_id':'session','sku':chosen['sku'],'buy_automatically':True})
    a.generic_agent_request.assert_not_called();shopping.save.assert_not_called()
 def test_three_modes_have_distinct_supported_actions_and_no_bookings(self):
  from shopping_modes import prepare, MODE_CONTEXT
  items=[{'sku':h,'product_type':t,'quote':{'handle':h}} for h,t in zip(m.HANDLES,['Carnet','Trousse','Jeux'])]
  outputs={mode:prepare(items,mode) for mode in ('surprise','gift','date')}
  self.assertEqual([len(outputs[x]) for x in ('surprise','gift','date')],[3,3,2])
  self.assertEqual(len({outputs[x][0]['action']['id'] for x in outputs}),3)
  self.assertTrue(all(x['action']['mode']=='date' and x['action']['scope']=='At-home activity suggestion; product only, no booking.' for x in outputs['date']))
  self.assertIn('at-home',MODE_CONTEXT['date']['intent'])
 def test_ai_cannot_swap_date_action_for_gift_action(self):
  from shopping_modes import prepare
  items=[{'sku':'one','title':'Notebook','product_type':'Carnet','tags':'paper','cents':1400,'quote':{'handle':m.HANDLES[0],'source_url':'https://merci-merci.com/products/'+m.HANDLES[0]}}]
  item=prepare(items,'date')[0]
  row={'sku':'one','preference_quote':'writing','fact_keys':['title'],'action_id':item['action']['id']}
  self.assertEqual(m.apply_ranking([item],'Likes writing',{'ranked':[row]})[0]['action']['mode'],'date')
  with self.assertRaises(ValueError):m.apply_ranking([item],'Likes writing',{'ranked':[{**row,'action_id':'gift-notebook'}]})
