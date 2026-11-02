"""AI ranking: evidence-bound reasons, honest fallback, no faked model. Offline: a fake client."""
import json, os, types, unittest
from unittest import mock
import catalog_ai

PERSONA = 'Live jazz, vegetarian, books. No horror.'
ITEMS = [dict(sku='jazz2', title='Jazz club, entry for two', cents=4400, tags='live jazz, small bar, music'),
         dict(sku='poems', title='Signed poetry book', cents=3200, tags='book, poetry, gift'),
         dict(sku='veg2', title='Vegetarian tasting menu for two', cents=5800, tags='vegetarian, dinner, food')]


def good():
    return {'ranked': [
        {'sku': 'veg2', 'preference_quote': 'vegetarian', 'facts': [{'field': 'tags', 'quote': 'vegetarian'}]},
        {'sku': 'jazz2', 'preference_quote': 'Live jazz', 'facts': [{'field': 'tags', 'quote': 'live jazz'}, {'field': 'title', 'quote': 'Jazz club'}]},
        {'sku': 'poems', 'preference_quote': 'books', 'facts': [{'field': 'title', 'quote': 'Signed poetry book'}]}]}


class FakeClient:
    def __init__(self, payload=None, stop='end_turn', raise_=None):
        self.payload, self.stop, self.raise_ = payload, stop, raise_
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=self.create))
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        if self.raise_:
            raise self.raise_
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return types.SimpleNamespace(stop_reason=self.stop, model='claude-opus-5-5',
                                     content=[types.SimpleNamespace(type='text', text=text)])


class CatalogAI(unittest.TestCase):
    def test_valid_answer_reorders_and_every_reason_is_built_from_quotes(self):
        ranked, meta = catalog_ai.rank(ITEMS, PERSONA, 'surprise', 'intent', client=FakeClient(good()))
        self.assertEqual([i['sku'] for i in ranked], ['veg2', 'jazz2', 'poems'])
        self.assertTrue(meta['ai']); self.assertEqual(meta['model'], 'claude-opus-5-5')
        jazz = ranked[1]
        self.assertEqual(jazz['why'], 'Matches your “Live jazz”: live jazz · Jazz club')
        self.assertEqual(jazz['cents'], 4400)

    def test_request_uses_structured_output_low_effort_and_default_fallbacks(self):
        c = FakeClient(good()); catalog_ai.rank(ITEMS, PERSONA, 'gift', 'intent', client=c)
        kw = c.calls[0]
        self.assertEqual(kw['output_config']['format']['type'], 'json_schema')
        self.assertEqual(kw['output_config']['effort'], 'low')
        self.assertEqual(kw['fallbacks'], 'default'); self.assertIn('server-side-fallback-2026-07-01', kw['betas'])
        self.assertNotIn('temperature', kw)

    def test_invented_preference_fact_or_sku_is_refused_whole(self):
        for mutate in (lambda r: r['ranked'][0].update(preference_quote='loves opera'),
                       lambda r: r['ranked'][0]['facts'][0].update(quote='Michelin star'),
                       lambda r: r['ranked'][0]['facts'][0].update(field='price'),
                       lambda r: r['ranked'][0].update(sku='yacht'),
                       lambda r: r['ranked'].pop(),
                       lambda r: r['ranked'][0].update(facts=[]),
                       lambda r: r['ranked'][2].update(sku='veg2')):
            payload = good(); mutate(payload)
            with self.assertRaises(catalog_ai.Unavailable):
                catalog_ai.rank(ITEMS, PERSONA, 'surprise', 'intent', client=FakeClient(payload))

    def test_refusal_bad_json_and_api_errors_become_honest_labels(self):
        import anthropic, httpx
        req = httpx.Request('POST', 'https://api.anthropic.com/v1/messages')
        cases = [FakeClient(good(), stop='refusal'), FakeClient('not json'),
                 FakeClient(raise_=anthropic.AuthenticationError('x', response=httpx.Response(401, request=req), body=None)),
                 FakeClient(raise_=anthropic.APIConnectionError(request=req))]
        labels = []
        for c in cases:
            with self.assertRaises(catalog_ai.Unavailable) as e:
                catalog_ai.rank(ITEMS, PERSONA, 'date', 'intent', client=c)
            labels.append(str(e.exception))
        self.assertIn('declined', labels[0]); self.assertIn('JSON', labels[1])
        self.assertIn('refused', labels[2]); self.assertIn('reached', labels[3])

    def test_no_key_is_unavailable_without_any_model_call(self):
        with mock.patch.dict(os.environ, {catalog_ai.KEY_ENV: ''}):
            ok, label = catalog_ai.status()
            self.assertFalse(ok); self.assertIn('No model key', label)
            with self.assertRaises(catalog_ai.Unavailable):
                catalog_ai.rank(ITEMS, PERSONA, 'gift', 'intent')


if __name__ == '__main__':
    unittest.main()
