"""Owner-only shopping flow. Frozen, expiring demo quotes; no live retailer claim.

POST routes run under app.LOCK. Persist a choice before any payment side effect:
interrupted attempts fail closed rather than creating a replacement purchase.
"""
import json, re, secrets, time
import catalog_ai, merchant_catalog
from shopping_modes import MODE_CONTEXT

AGENT = 'Shopping agent'
MERCHANT = 'ApproveAccept Sandbox shop'
SOURCE = 'ApproveAccept Sandbox catalog'

class Shopping:
    def __init__(self, app):
        self.a = app
        self.rules = app.SpendRules(frozenset({'gifts', 'experiences'}), {}, 7500)

    def db(self):
        db = self.a.S.db()
        db.execute('CREATE TABLE IF NOT EXISTS shopping_sessions(id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, value TEXT NOT NULL)')
        return db

    def config(self):
        with self.db() as db:
            row = db.execute("SELECT v FROM kv WHERE k='shopping_setup'").fetchone()
        return json.loads(row['v']) if row else None

    def status(self):
        config = self.config()
        return {'ready': bool(config), 'setup': config, 'allowance': self.a.allowance_for(AGENT),
                'payment_mode': 'substitute' if self.a.SUBSTITUTE else 'sandbox',
                'funding': 'Local payment substitute. No PayPal call.' if self.a.SUBSTITUTE else
                    'PayPal Sandbox test funding. No personal payment method is saved and no live money moves.',
                'catalog_source': SOURCE, 'ranking': 'Default Sandbox examples use local preference matching.',
                'ai_ranking': dict(zip(('ready','label'), catalog_ai.status())),
                'available_sources': [{'id':'demo','name':SOURCE,'ranking':'local'},
                    {'id':'ai','name':SOURCE,'ranking':'AI with your model key','enabled':catalog_ai.status()[0]},
                    {'id':'merci','name':merchant_catalog.SOURCE,'ranking':'subscription AI','enabled':not self.a.SUBSTITUTE,'modes':['surprise','gift','date']}]}

    def setup(self, b):
        if type(b.get('automatic')) is not bool:
            raise self.a.Refused('Choose whether automatic Sandbox purchases are enabled.')
        persona = str(b.get('persona', '')).strip()[:600]
        grant = self.a.grant_allowance({**b, 'agent': AGENT, 'merchants': [MERCHANT]})
        config = {'automatic': b['automatic'], 'persona': persona, 'saved_at': self.a.now()}
        with self.db() as db:
            db.execute("INSERT OR REPLACE INTO kv VALUES('shopping_setup',?)", (json.dumps(config),))
        return self.status()

    def save(self, session):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO shopping_sessions VALUES(?,?,?)',
                       (session['id'], session['request_key'], json.dumps(session)))

    def load(self, column, key):
        assert column in ('id', 'request_key')
        with self.db() as db:
            row = db.execute(f'SELECT value FROM shopping_sessions WHERE {column}=?', (key,)).fetchone()
        return json.loads(row['value']) if row else None

    def require_setup(self):
        config = self.config()
        if not config:
            raise self.a.Refused('Set up Sandbox payment limits first.')
        return config

    def automatic_check(self, config, quote):
        if not config['automatic']:
            raise self.a.Refused('Automatic purchases are off. Enable them explicitly in payment setup.')
        decision = self.a.allowance_decision(AGENT, MERCHANT, quote['category'], quote['cents'], False, self.rules)
        if not decision or decision.outcome != self.a.AUTOMATIC:
            raise self.a.Refused(' '.join(decision.reasons) if decision else 'An active owner allowance is required.')

    def ideas(self, b):
        config = self.require_setup()
        if set(b) - {'mode', 'request_key', 'buy_automatically', 'source'}:
            raise self.a.Refused('Choose a mode; prices and offers come from the server.')
        mode, key = b.get('mode'), b.get('request_key')
        if mode not in ('surprise', 'gift', 'date') or not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{12,80}', key):
            raise self.a.Refused('Choose surprise, gift or date and provide a fresh request key.')
        source = b.get('source', 'demo')
        if source not in ('demo','merci','ai'):
            raise self.a.Refused('Choose the Sandbox shop, AI ranking of it, or the connected Merci catalog.')
        auto = b.get('buy_automatically', False)
        if type(auto) is not bool:
            raise self.a.Refused('Automatic purchase must be true or false.')
        old = self.load('request_key', key)
        if old:
            if old['mode'] != mode or old['automatic_requested'] != auto or old.get('source','demo') != source:
                raise self.a.Refused('That request key belongs to a different choice.')
            if old.get('attempted') and not old.get('purchase'):
                raise self.a.Refused('Payment outcome needs reconciliation. No replacement purchase was created.')
            return old
        allowed = {'date': {'jazz2','cine2','veg2','horror2'}, 'gift': {'poems','phones','cube'},
                   'surprise': set(self.a.SKU)}[mode]
        persona = config['persona'].casefold()
        entries = []
        for item in self.a.CATALOG:
            if item['sku'] not in allowed:
                continue
            tags = [t.strip() for t in item['tags'].split(',')]
            if any(re.search(r'\b(?:no|avoid|dislike)\s+' + re.escape(tag) + r'\b', persona) for tag in tags):
                continue
            matched = [tag for tag in tags if tag in persona or (tag == 'book' and 'books' in persona)]
            quote = {'source': SOURCE, 'sku': item['sku'], 'cents': item['cents'], 'currency': 'EUR',
                     'category': 'experiences' if item['sku'] in {'jazz2','cine2','veg2','horror2'} else 'gifts',
                     'quoted_at': self.a.now(), 'expires_at': int(time.time()) + 900}
            entries.append({**item, 'quote': quote, 'why': 'Matches your preference for ' + ', '.join(matched) + '.' if matched else
                            'An alternative from the Sandbox shop; no matching preference signal yet.', '_match': len(matched)})
        entries.sort(key=lambda item: (-item['_match'], item['cents'], item['sku']))
        for item in entries:
            del item['_match']
        if not entries:
            raise self.a.Refused('No catalog ideas match these preferences.')
        ranking = {'method':'Local editable-preference matching, not an AI model run.', 'ai': False}
        if source == 'ai':
            try:
                entries, ranking = catalog_ai.rank(entries, config['persona'], mode, MODE_CONTEXT[mode]['intent'])
            except catalog_ai.Unavailable as exc:
                # Honest fallback: the local matcher's order and reasons, labelled as such.
                ranking = {'ai': False, 'fallback_reason': str(exc),
                           'method': 'Local preference matching, because AI ranking was unavailable: ' + str(exc)}
        if source == 'merci':
            if self.a.SUBSTITUTE:
                raise self.a.Refused('Live merchant/AI discovery is off in substitute mode. Use the connected Sandbox process.')
            try:
                merchant_offers = merchant_catalog.offers()
                entries, ranking = merchant_catalog.rank_with_ai(merchant_offers,config['persona'],mode,self.a.DATA)
            except Exception as exc:
                raise self.a.Refused('Merchant/AI discovery unavailable; no purchase made. ' + (str(exc) if isinstance(exc,ValueError) else type(exc).__name__)) from None
        if auto:
            eligible = []
            for item in entries:
                try:
                    self.automatic_check(config, item['quote']); eligible.append(item)
                except self.a.Refused:
                    pass
            if not eligible:
                raise self.a.Refused('No idea fits an active allowance with automatic purchases enabled.')
            selected = eligible[0]
        session = {'id': secrets.token_hex(16), 'request_key': key, 'mode': mode, 'created_at': self.a.now(),
                   'automatic_requested': auto, 'ideas': entries, 'source':source, 'ranking':ranking, 'mode_context':MODE_CONTEXT[mode]}
        self.save(session)
        if auto:
            self.choose({'session_id': session['id'], 'sku': selected['sku'], 'buy_automatically': True})
            session = self.load('id', session['id'])
        return session

    def choose(self, b):
        config = self.require_setup()
        if set(b) - {'session_id','sku','buy_automatically','owner_review_if_over'}:
            raise self.a.Refused('Client prices or extra purchase fields are not accepted.')
        review_if_over = b.get('owner_review_if_over', False)
        if type(review_if_over) is not bool:
            raise self.a.Refused('Owner review fallback must be true or false.')
        session = self.load('id', str(b.get('session_id', '')))
        if not session:
            raise self.a.Refused('Unknown idea session.')
        sku = b.get('sku')
        item = next((i for i in session['ideas'] if i['sku'] == sku), None)
        if not item:
            raise self.a.Refused('Choose an offer from this session.')
        auto = b.get('buy_automatically', False)
        if type(auto) is not bool:
            raise self.a.Refused('Automatic purchase must be true or false.')
        if session.get('attempted'):
            if session.get('chosen_sku') != sku or session.get('chosen_auto') != auto:
                raise self.a.Refused('This session already has a different purchase choice.')
            if session.get('purchase'):
                return session['purchase']
            raise self.a.Refused('Payment outcome needs reconciliation. No replacement purchase was created.')
        quote = item['quote']; current = self.a.SKU.get(sku)
        if session.get('source') == 'merci':
            try:
                merchant_catalog.revalidate(item)
            except Exception as exc:
                raise self.a.Refused('Merchant recheck failed; no purchase made. ' + (str(exc) if isinstance(exc,ValueError) else type(exc).__name__)) from None
        elif quote['expires_at'] <= time.time() or not current or current['cents'] != quote['cents'] or current['title'] != item['title']:
            raise self.a.Refused('This quote expired or changed. Ask for fresh ideas before buying.')
        over_reasons = []
        if auto:
            try:
                self.automatic_check(config, quote)
            except self.a.Refused:
                # One-path journey: a choice outside the allowance becomes one Face ID
                # decision instead of an error. A blocked category still refuses.
                decision = self.a.allowance_decision(AGENT, MERCHANT, quote['category'], quote['cents'], False, self.rules)
                if not review_if_over or not decision or decision.outcome == self.a.BLOCK:
                    raise
                auto, over_reasons = False, list(decision.reasons) if decision.outcome == self.a.APPROVE else []
        # chosen_auto records what the client asked for, so an identical retry returns the same purchase.
        session.update(attempted=True, chosen_sku=sku, chosen_auto=b.get('buy_automatically', False), owner_review=not auto)
        self.save(session)
        result = self.a.generic_agent_request({'request_key':'shopping-'+session['id'], 'agent': AGENT, 'title': item['title'], 'merchant': MERCHANT,
            'category': quote['category'], 'cents': quote['cents'], 'why': item['why'],
            'task': session['mode'] + ' idea; test payment to Sandbox shop only', 'suggested': not auto,
            'product_url':item.get('product_url','')},
            rules=self.rules, trusted_quote=quote)
        if over_reasons:
            result = {**result, 'over_limit_reasons': over_reasons}
        session['purchase'] = result
        self.save(session)
        return result
