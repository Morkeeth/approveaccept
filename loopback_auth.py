"""Owner/agent access for the internal API. Loopback is not an auth boundary."""
import os,secrets,threading,time
from http.cookies import SimpleCookie
SESSIONS={}
ATTEMPTS={}
LOCK=threading.Lock()
CAPABILITIES={'/api/phone-decision','/api/passkey/enrol','/api/suggestion'}
AGENT_KEYS=None  # set by app.py: callable(token) -> agent name or None, for owner-created per-agent keys

def role(handler):
 owner=os.environ.get('APPROVEACCEPT_OWNER_TOKEN','')
 agent=os.environ.get('APPROVEACCEPT_AGENT_TOKEN','')
 if owner and agent and secrets.compare_digest(owner.encode(),agent.encode()):return None
 value=handler.headers.get('Authorization','')
 value=value[7:] if value.startswith('Bearer ') else ''
 for name in ('OWNER','AGENT'):
  token=os.environ.get('APPROVEACCEPT_'+name+'_TOKEN','')
  if len(token)>=32 and value and secrets.compare_digest(value.encode(),token.encode()):
   if name=='AGENT':
    if not os.environ.get('APPROVEACCEPT_AGENT_NAME'):return None
    handler.agent_name=os.environ['APPROVEACCEPT_AGENT_NAME']
   return name.lower()
 if value and len(value)>=32 and AGENT_KEYS:
  agent=AGENT_KEYS(value)
  if agent:
   handler.agent_name=agent
   return 'agent'
 try:
  cookie=SimpleCookie(handler.headers.get('Cookie',''))
  token=cookie['aa_internal_owner'].value if 'aa_internal_owner' in cookie else ''
 except Exception:return None
 with LOCK:
  for expired in [k for k,v in SESSIONS.items() if v<=time.monotonic()]:SESSIONS.pop(expired,None)
  if token in SESSIONS:return 'owner'
 return None

def session(handler,body):
 """Called only after the explicit Origin check; ephemeral, rate-limited owner session."""
 if handler.path=='/api/session/end':
  try:
   cookie=SimpleCookie(handler.headers.get('Cookie',''))
   with LOCK:SESSIONS.pop(cookie['aa_internal_owner'].value,None)
  except (KeyError,ValueError):pass
  handler.send(200,{'signed_out':True},cookie='aa_internal_owner=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0')
  return
 token=os.environ.get('APPROVEACCEPT_OWNER_TOKEN','')
 if len(token)<32:return handler.send(503,{'error':'Owner sign-in is not configured'})
 with LOCK:
  peer=handler.client_address[0]
  recent=[t for t in ATTEMPTS.get(peer,[]) if t>time.monotonic()-60]
  ATTEMPTS[peer]=recent
  if len(recent)>=10:return handler.send(429,{'error':'Try sign-in again in a minute'})
  recent.append(time.monotonic())
 value=body.get('token')
 if not isinstance(value,str) or not secrets.compare_digest(value.encode(),token.encode()):
  return handler.send(401,{'error':'Owner sign-in refused'})
 key=secrets.token_urlsafe(32)
 with LOCK:SESSIONS[key]=time.monotonic()+3600
 secure='; Secure' if os.environ.get('APPROVEACCEPT_PUBLIC_BASE_URL','').startswith('https://') else ''
 handler.send(200,{'signed_in':True},cookie='aa_internal_owner='+key+'; HttpOnly; SameSite=Lax; Path=/; Max-Age=3600'+secure)
