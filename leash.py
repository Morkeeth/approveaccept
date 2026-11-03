"""Leash: local agent payment policy and PayPal SANDBOX adapter. No live endpoint.

SQLite is appropriate only for this single-machine sandbox. All clients must share
one database. Agents cannot edit policy through this CLI. Unknown network outcomes
remain reserved until an operator reconciles them with PayPal.
"""
import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import urllib.error
import urllib.request


class Refused(ValueError):
    pass


def matches_amount(amount, cents):
    # PayPal adds breakdown={} on a real GET even when create sent only value.
    # Bind the payment's total and currency; optional metadata is not the total.
    return (isinstance(amount, dict) and amount.get('currency_code') == 'EUR'
            and amount.get('value') == f"{cents//100}.{cents%100:02d}")


def provision(path, agent, cap, per_purchase, merchants):
    if type(cap) is not int or type(per_purchase) is not int or not 0 < per_purchase <= cap:
        raise Refused('Use positive integer EUR cents; purchase cap cannot exceed total cap.')
    if not agent or not merchants or any(not m for m in merchants):
        raise Refused('Agent and allowed merchant IDs required.')
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    with sqlite3.connect(path) as db:
        db.executescript('''
        CREATE TABLE policy(agent TEXT PRIMARY KEY, cap INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0,
            purchase_cap INTEGER NOT NULL, merchants TEXT NOT NULL);
        CREATE TABLE requests(id TEXT PRIMARY KEY, agent TEXT NOT NULL, merchant TEXT NOT NULL,
            cents INTEGER NOT NULL, purpose TEXT NOT NULL, month TEXT NOT NULL, state TEXT NOT NULL,
            order_id TEXT UNIQUE, authorization_id TEXT UNIQUE, capture_id TEXT UNIQUE,
            approval_url TEXT, reason TEXT, refund_id TEXT UNIQUE);
        ''')
        db.execute('INSERT INTO policy(agent,cap,purchase_cap,merchants) VALUES (?,?,?,?)',
                   (agent, cap, per_purchase, json.dumps(sorted(set(merchants)))))


def ensure_refund_column(db):
    # Stores made before refunds existed gain the column on the first refund.
    if 'refund_id' not in [r[1] for r in db.execute('PRAGMA table_info(requests)')]:
        db.execute('ALTER TABLE requests ADD COLUMN refund_id TEXT')


class Book:
    def __init__(self, path):
        self.path = Path(path).resolve()

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=20)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def get(self, request_id):
        with self.db() as db:
            row = db.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone()
            if not row:
                raise Refused('Unknown request.')
            return dict(row)

    def request(self, request_id, agent, merchant, cents, purpose):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', request_id):
            raise Refused('Request ID must be 1 to 80 letters, digits, underscores or hyphens.')
        if type(cents) is not int or cents <= 0 or not purpose.strip():
            raise Refused('Positive integer EUR cents and purpose required.')
        month = datetime.now(timezone.utc).strftime('%Y-%m')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone()
            if old:
                if (old['agent'],old['merchant'],old['cents'],old['purpose']) != (agent,merchant,cents,purpose):
                    raise Refused('Request ID reused with different payment details.')
                return dict(old)
            policy = db.execute('SELECT * FROM policy WHERE agent=?', (agent,)).fetchone()
            if not policy:
                raise Refused('Unknown agent.')
            reason = ''
            if merchant not in json.loads(policy['merchants']):
                reason = 'Merchant is not allowed.'
            elif cents > policy['purchase_cap']:
                reason = 'Purchase exceeds its limit.'
            # Lifetime cap is deliberate: a clock change cannot reset available funds.
            # Policy renewal is an explicit operator action in a new database.
            if not reason:
                changed = db.execute('UPDATE policy SET used=used+? WHERE agent=? AND used+?<=cap',
                                     (cents,agent,cents)).rowcount
                if changed != 1:
                    reason = 'Total spending limit exhausted.'
            db.execute('INSERT INTO requests(id,agent,merchant,cents,purpose,month,state,reason) VALUES (?,?,?,?,?,?,?,?)',
                       (request_id,agent,merchant,cents,purpose,month,'refused' if reason else 'reserved',reason))
        return self.get(request_id)

    def claim(self, request_id, before, after):
        with self.db() as db:
            if db.execute('UPDATE requests SET state=? WHERE id=? AND state=?', (after,request_id,before)).rowcount != 1:
                raise Refused('Request is not ready; duplicate or uncertain operation refused.')
        return self.get(request_id)

    def finish(self, request_id, state, **fields):
        allowed = {'order_id','authorization_id','capture_id','approval_url','refund_id'}
        if not set(fields) <= allowed:
            raise Refused('Invalid provider fields.')
        with self.db() as db:
            if 'refund_id' in fields:
                ensure_refund_column(db)
            db.execute('UPDATE requests SET state=?' + ''.join(', '+k+'=?' for k in fields) + ' WHERE id=?',
                       (state,*fields.values(),request_id))
        return self.get(request_id)

    def summary(self):
        with self.db() as db:
            return {'environment':'sandbox', 'policy':[dict(r) for r in db.execute('SELECT * FROM policy')],
                    'requests':[dict(r) for r in db.execute('SELECT * FROM requests ORDER BY rowid')]}


class Sandbox:
    BASE = 'https://api-m.sandbox.paypal.com'

    def __init__(self):
        def key(name, env_name):
            value = os.environ.get(env_name, '').strip()
            if value:
                return value
            value = subprocess.check_output(['security','find-generic-password','-a','leash-sandbox','-s',name,'-w'],stderr=subprocess.DEVNULL).decode().strip()
            if not value:
                raise Refused('Missing sandbox credential in Keychain.')
            return value
        client = key('leash.paypal.client-id', 'APPROVEACCEPT_PAYPAL_SANDBOX_CLIENT_ID')
        secret = key('leash.paypal.client-secret', 'APPROVEACCEPT_PAYPAL_SANDBOX_CLIENT_SECRET')
        auth = base64.b64encode((client+':'+secret).encode()).decode()
        req = urllib.request.Request(self.BASE+'/v1/oauth2/token', data=b'grant_type=client_credentials',
                                     headers={'Authorization':'Basic '+auth,'Content-Type':'application/x-www-form-urlencoded'})
        self.token = self.send(req)['access_token']

    @staticmethod
    def send(req):
        try:
            with urllib.request.urlopen(req,timeout=30) as response:
                raw=response.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            # Never emit provider bodies, credentials, headers or tokens.
            raise Refused('PayPal sandbox returned HTTP '+str(exc.code)+'. Reservation retained.') from None

    def call(self, path, data=None, request_id=None, method='POST'):
        if not re.fullmatch(r'/v[12]/[a-zA-Z0-9/_-]+',path):
            raise Refused('Invalid sandbox path.')
        headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json','Prefer':'return=representation'}
        if request_id:
            headers['PayPal-Request-Id']=hashlib.sha256(request_id.encode()).hexdigest()[:38]
        req=urllib.request.Request(self.BASE+path, data=json.dumps(data or {}).encode() if method!='GET' else None,
                                   headers=headers,method=method)
        return self.send(req)


class Leash:
    def __init__(self, book, provider_factory=Sandbox):
        self.book, self.provider_factory = book, provider_factory

    def create(self, request_id):
        # Atomic state claim happens before credential loading or any external call.
        row=self.book.claim(request_id,'reserved','creating')
        p=self.provider_factory()
        order=p.call('/v2/checkout/orders',{'intent':'AUTHORIZE','purchase_units':[{
            'reference_id':request_id,'custom_id':request_id,'description':row['purpose'][:127],
            'payee':{'merchant_id':row['merchant']},
            'amount':{'currency_code':'EUR','value':f"{row['cents']//100}.{row['cents']%100:02d}"}}]},request_id+':create')
        url=next((l['href'] for l in order.get('links',[]) if l['rel']=='approve'),'')
        if not re.fullmatch(r'https://www\.sandbox\.paypal\.com/[^\s]*',url):
            raise Refused('Missing sandbox buyer approval link. Reservation retained.')
        return self.book.finish(request_id,'buyer_approval',order_id=order['id'],approval_url=url)

    @staticmethod
    def verify_order(row, order):
        units=order.get('purchase_units',[])
        if order.get('id')!=row['order_id'] or order.get('intent')!='AUTHORIZE' or len(units)!=1:
            raise Refused('Order identity or intent mismatch.')
        unit=units[0]
        if not matches_amount(unit.get('amount'),row['cents']) or unit.get('payee',{}).get('merchant_id')!=row['merchant'] or unit.get('custom_id')!=row['id']:
            raise Refused('Order amount, currency, merchant or request changed.')

    def authorize(self, request_id):
        row=self.book.get(request_id)
        if row['state']!='buyer_approval':
            raise Refused('Buyer approval required.')
        p=self.provider_factory()
        order=p.call('/v2/checkout/orders/'+row['order_id'],method='GET')
        self.verify_order(row,order)
        if order.get('status')!='APPROVED':
            raise Refused('Buyer has not approved in PayPal sandbox.')
        self.book.claim(request_id,'buyer_approval','authorizing')
        order=p.call('/v2/checkout/orders/'+row['order_id']+'/authorize',{},request_id+':authorize')
        self.verify_order(row,order)
        authorization=order['purchase_units'][0]['payments']['authorizations'][0]
        if authorization.get('status')!='CREATED' or not matches_amount(authorization.get('amount'),row['cents']):
            raise Refused('Authorization not confirmed. Reservation retained.')
        return self.book.finish(request_id,'authorized',authorization_id=authorization['id'])

    def capture(self, request_id):
        row=self.book.claim(request_id,'authorized','capturing')
        p=self.provider_factory()
        result=p.call('/v2/payments/authorizations/'+row['authorization_id']+'/capture',{'final_capture':True},request_id+':capture')
        if result.get('status')!='COMPLETED' or not matches_amount(result.get('amount'),row['cents']):
            raise Refused('Capture not confirmed. Reservation retained.')
        return self.book.finish(request_id,'captured',capture_id=result['id'])

    def void(self, request_id):
        row=self.book.claim(request_id,'authorized','voiding')
        self.provider_factory().call('/v2/payments/authorizations/'+row['authorization_id']+'/void',{},request_id+':void')
        # Keep admitted spend charged conservatively. Never refill automatically.
        return self.book.finish(request_id,'voided')

    def refund(self, request_id):
        # Uncertain refunds are checked by GET only. Never issue a second refund POST.
        row=self.book.get(request_id)
        if row['state']=='refunding':
            capture=self.provider_factory().call('/v2/payments/captures/'+row['capture_id'],method='GET')
            if capture.get('id')!=row['capture_id'] or not matches_amount(capture.get('amount'),row['cents']):
                raise Refused('Capture identity or amount mismatch while checking refund.')
            if capture.get('status')=='REFUNDED':
                return self.book.finish(request_id,'refunded')
            return row  # COMPLETED may still have an in-flight refund. Keep it pending.
        row=self.book.claim(request_id,'captured','refunding')
        result=self.provider_factory().call('/v2/payments/captures/'+row['capture_id']+'/refund',{},request_id+':refund')
        if result.get('status') not in ('COMPLETED','PENDING') or not result.get('id'):
            raise Refused('Refund not confirmed by PayPal. Check the capture in Sandbox before trying again.')
        if result.get('amount') and not matches_amount(result['amount'],row['cents']):
            raise Refused('Refund amount differs from the capture. Check the capture in Sandbox.')
        # Same rule as a void: the allowance is not refilled automatically.
        return self.book.finish(request_id,'refunded' if result['status']=='COMPLETED' else 'refunding',refund_id=result['id'])


def main():
    p=argparse.ArgumentParser(description='Leash: agent payments with limits. EUR sandbox only.')
    p.add_argument('--db',required=True)
    sub=p.add_subparsers(dest='command',required=True)
    init=sub.add_parser('init');init.add_argument('--agent',required=True);init.add_argument('--cap',type=int,required=True);init.add_argument('--purchase-cap',type=int,required=True);init.add_argument('--merchant',action='append',required=True)
    req=sub.add_parser('request');req.add_argument('id');req.add_argument('--agent',required=True);req.add_argument('--merchant',required=True);req.add_argument('--cents',type=int,required=True);req.add_argument('--purpose',required=True)
    sub.add_parser('status')
    for name in ('create','authorize','capture','void'):
        sub.add_parser(name).add_argument('id')
    args=p.parse_args()
    try:
        if args.command=='init':
            provision(args.db,args.agent,args.cap,args.purchase_cap,args.merchant);result={'environment':'sandbox','status':'provisioned'}
        elif args.command=='request':
            result=Book(args.db).request(args.id,args.agent,args.merchant,args.cents,args.purpose)
        elif args.command=='status':result=Book(args.db).summary()
        else:result=getattr(Leash(Book(args.db)),args.command)(args.id)
        print(json.dumps(result,indent=2))
    except (Refused,subprocess.CalledProcessError,OSError) as exc:
        p.exit(1,'Refused: '+ ('Sandbox credentials unavailable in Keychain.' if isinstance(exc,subprocess.CalledProcessError) else str(exc))+'\n')

if __name__=='__main__':main()
