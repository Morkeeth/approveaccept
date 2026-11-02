"""Single-use purchase-scoped buyer returns; no owner session or capture authority."""
import hashlib,re,secrets,sqlite3,time
from leash import Refused
class BuyerReturns:
 def __init__(self,path):
  self.path=path
  with self.db() as db:db.execute('CREATE TABLE IF NOT EXISTS buyer_returns(pid TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, order_id TEXT, expires INTEGER NOT NULL, used INTEGER)')
 def db(self):
  db=sqlite3.connect(self.path,timeout=20);db.row_factory=sqlite3.Row;return db
 def issue(self,pid):
  token=secrets.token_urlsafe(32)
  with self.db() as db:db.execute('INSERT OR REPLACE INTO buyer_returns VALUES(?,?,NULL,?,NULL)',(pid,hashlib.sha256(token.encode()).hexdigest(),int(time.time())+1800))
  return token
 def bind(self,token,order_id):
  with self.db() as db:db.execute('UPDATE buyer_returns SET order_id=? WHERE digest=? AND used IS NULL',(order_id,hashlib.sha256(token.encode()).hexdigest()))
 def consume(self,token,returned_order=''):
  if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):raise Refused('This return link is invalid, expired or already used.')
  with self.db() as db:
   db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT * FROM buyer_returns WHERE digest=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
   if not row or row['used'] is not None or row['expires']<=int(time.time()) or not row['order_id'] or returned_order and returned_order!=row['order_id']:raise Refused('This return link is invalid, expired or already used.')
   db.execute('UPDATE buyer_returns SET used=? WHERE digest=?',(int(time.time()),row['digest']))
   return dict(row)
