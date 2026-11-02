"""Persistent client intent keys. Unknown outcomes never start replacement payments."""
import hashlib,json,re
from leash import Refused


class PreflightRefused(Refused):
 """A refusal proven to occur before any provider effect; the spend controller confirmed no reservation."""

class PreflightResult(dict):
 """A returned policy refusal, proven to precede all provider effects."""


def execute_once(state,namespace,body,operation):
 key=body.get('request_key');agent=str(body.get('agent','')).strip()
 if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{12,80}',key):
  raise Refused('request_key is required: 12 to 80 letters, digits, underscores or hyphens. Reuse it for retries.')
 if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ._@/-]{0,79}',agent):
  raise Refused('Name the requesting agent using ordinary text.')
 # Client label is provenance, not a payment detail: HTTP/MCP retries can share intent.
 canonical={k:v for k,v in body.items() if k not in ('request_key','client')}
 fingerprint=hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 with state.db() as db:
  db.execute('BEGIN IMMEDIATE')
  old=db.execute('SELECT fingerprint,response FROM purchase_requests WHERE namespace=? AND agent=? AND request_key=?',(namespace,agent,key)).fetchone()
  if old:
   if old['fingerprint']!=fingerprint:raise Refused('request_key was already used with different purchase details.')
   if old['response'] is None:raise Refused('This request is pending or its payment outcome is uncertain. Reconcile it; no replacement payment was started.')
   previous=json.loads(old['response'])
   if not previous.get('__preflight_refusal__'):
    return previous
   # Preserve fingerprint binding; atomically reclaim only a known safe refusal.
   db.execute('UPDATE purchase_requests SET response=NULL WHERE namespace=? AND agent=? AND request_key=?',(namespace,agent,key))
  else:
   db.execute('INSERT INTO purchase_requests(namespace,agent,request_key,fingerprint,response) VALUES(?,?,?,?,NULL)',(namespace,agent,key,fingerprint))
 # Persist the claim before effects. Only explicitly typed pre-provider refusals retry.
 try:
  value=operation()
 except PreflightRefused:
  with state.db() as db:
   db.execute('UPDATE purchase_requests SET response=? WHERE namespace=? AND agent=? AND request_key=?',(json.dumps({'__preflight_refusal__':True}),namespace,agent,key))
  raise
 result=json.loads(json.dumps(value))
 stored={'__preflight_refusal__':True,'result':result} if isinstance(value,PreflightResult) else result
 with state.db() as db:
  db.execute('UPDATE purchase_requests SET response=? WHERE namespace=? AND agent=? AND request_key=?',(json.dumps(stored),namespace,agent,key))
 return result
