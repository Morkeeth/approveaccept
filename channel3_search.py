"""Channel3 product search for agents. Discovery only: it never buys, pays or sets a payee.

An agent calls find_products before request_purchase, so the item, merchant and price it asks
the human about come from a real retailer offer. The human still approves in ApproveAccept and
PayPal still holds the money. Key: CHANNEL3_API_KEY. Docs: https://docs.trychannel3.com
"""
import json, os, urllib.request

API = 'https://api.trychannel3.com/v1/search'


class Unavailable(Exception):
    pass


def offer_view(product):
    offers = [o for o in product.get('offers') or [] if o.get('availability') == 'InStock'] or product.get('offers') or []
    if not offers:
        return None
    best = min(offers, key=lambda o: (o.get('price') or {}).get('price') or 1e12)
    price = best.get('price') or {}
    return {'channel3_id': product.get('id'), 'title': str(product.get('title', ''))[:160],
            'brand': ', '.join(b.get('name', '') for b in product.get('brands') or [])[:80],
            'merchant': best.get('domain'), 'price': price.get('price'), 'currency': price.get('currency'),
            'availability': best.get('availability'), 'offer_url': best.get('url'),
            'image': next((i.get('url') for i in product.get('images') or [] if i.get('is_main_image')), None)}


def search(query, max_price=None, limit=5, key=None):
    key = key or os.environ.get('CHANNEL3_API_KEY')
    if not key:
        raise Unavailable('Set CHANNEL3_API_KEY to search real retailer offers.')
    query = str(query or '').strip()[:200]
    if not query:
        raise Unavailable('Say what to look for.')
    body = {'query': query, 'limit': max(1, min(int(limit), 10))}
    if max_price:
        body['filters'] = {'price': {'max_price': float(max_price)}}
    req = urllib.request.Request(API, data=json.dumps(body).encode(), method='POST',
                                 headers={'x-api-key': key, 'content-type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read(2_000_000))
    except Exception as exc:
        raise Unavailable('Channel3 search failed: ' + type(exc).__name__) from None
    items = [v for v in (offer_view(p) for p in data.get('products') or []) if v]
    return {'source': 'Channel3 product search (discovery only, no purchase)', 'query': query, 'products': items,
            'next_step': 'Pick one and call request_purchase with its title, merchant and price. The human approves.'}


if __name__ == '__main__':
    import sys
    print(json.dumps(search(' '.join(sys.argv[1:]) or 'travel adapter', limit=3), indent=1))
