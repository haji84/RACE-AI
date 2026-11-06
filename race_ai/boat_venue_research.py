"""Authenticate an owner's scoped personal-research decision, not a licence.

Only the reviewed BOAT data routes and existing two-family shadow fitter are
covered. This never asserts provider permission, commercial use or promotion.
"""
import hashlib,hmac,re
from datetime import datetime
from urllib.parse import urlsplit
from .actions_contract import digest
from .boat_pdca_state import state_key
from .teiai_history import need

SCHEMA='RACE_AI_BOAT_VENUE_OWNER_PERSONAL_RESEARCH_V1'
BASIS='OWNER_PERSONAL_RESEARCH'
RIGHTS=frozenset(('OWNER_PERSONAL_OFFICIAL_B_ANALYSIS_20261104',
 'OWNER_PERSONAL_OFFICIAL_HISTORY_ANALYSIS_20261106',
 'OWNER_PERSONAL_OFFICIAL_RESULT_EVALUATION_20261106',
 'OWNER_PERSONAL_OFFICIAL_VENUE_HISTORY_ANALYSIS_20261106'))
FIELDS=frozenset(('repository_id','basis','purpose','instruction_ref','issued_at','expires_at',
 'source_pointer_sha256','source_content_sha256','dataset_pointer_sha256','source_refs_sha256',
 'provider_permission_confirmed','production_promoted','commercial_use_permitted','public_raw_data_permitted'))

def _time(value):
 try:t=value if isinstance(value,datetime) else datetime.fromisoformat(value.replace('Z','+00:00'))
 except (AttributeError,TypeError,ValueError):raise ValueError('OWNER_RESEARCH_TIME_INVALID') from None
 need(t.utcoffset() is not None,'OWNER_RESEARCH_TIME_INVALID');return t

def _refs(values):
 need(isinstance(values,(list,tuple,set,frozenset)) and values,'OWNER_RESEARCH_SOURCE_SCOPE')
 result=set()
 for item in values:
  need(isinstance(item,(list,tuple)) and len(item)==2 and all(type(s) is str for s in item),'OWNER_RESEARCH_SOURCE_SCOPE')
  url,rights=item
  try:p=urlsplit(url);host=p.hostname;port=p.port
  except ValueError:raise ValueError('OWNER_RESEARCH_SOURCE_SCOPE') from None
  need(p.scheme=='https' and not p.username and not p.password and port in (None,443) and not p.fragment and
       not any(c.isspace() or ord(c)<32 for c in url) and rights in RIGHTS and
       (host in ('www.boatrace.jp','www1.mbrace.or.jp') or host=='raw.githubusercontent.com' and p.path.startswith('/haji84/RACE-AI/')),
       'OWNER_RESEARCH_SOURCE_SCOPE')
  result.add((url,rights))
 return sorted(result)

def _bindings(source_pointer,content,dataset_pointer):
 from .boat_pdca_github_handoff import INPUT_SCHEMA,_scope,_cipher_path
 from .boat_venue_learning import _pin
 p=source_pointer
 need(type(p) is dict and set(p)=={'schema','status','repository_id','source_commit','cipher_path','cipher_sha256','scope'} and
      p['schema']==INPUT_SCHEMA and p['status']=='READY' and p['repository_id']=='1416489937','OWNER_RESEARCH_SOURCE_POINTER_INVALID')
 scope=_scope(p['scope'])
 need(scope['mode']=='production' and p['cipher_path']==_cipher_path(scope) and
      re.fullmatch('[a-f0-9]{40}',str(p['source_commit'])) and re.fullmatch('[a-f0-9]{64}',str(p['cipher_sha256'])) and
      re.fullmatch('[a-f0-9]{64}',str(content)),'OWNER_RESEARCH_SOURCE_POINTER_INVALID')
 _pin(dataset_pointer)
 return dict(source_pointer_sha256=digest(p),source_content_sha256=content,dataset_pointer_sha256=digest(dataset_pointer))

def _mac(decision):
 key=hmac.digest(state_key('production'),b'RACE_AI_OWNER_PERSONAL_RESEARCH_DECISION_V1','sha256')
 return hmac.new(key,digest(decision).encode('ascii'),hashlib.sha256).hexdigest()

def issue_owner_research_decision(*,source_pointer,state_content_sha256,dataset_pointer,source_refs,now,expires_at):
 """Explicit operator operation under the owner's 2026-11-07 instruction.

 The MAC authenticates this owner's audit record only. It is not an external
 review key or a provider's grant. Fitting never calls this issuer implicitly.
 """
 now=_time(now);end=_time(expires_at);need(now<end,'OWNER_RESEARCH_EXPIRY_INVALID')
 decision=dict(repository_id='1416489937',basis=BASIS,purpose='EXISTING_TWO_FAMILY_SHADOW_FIT',
  instruction_ref='OWNER_INSTRUCTION_20261107_PERSONAL_RESEARCH',issued_at=now.isoformat(),expires_at=end.isoformat(),
  **_bindings(source_pointer,state_content_sha256,dataset_pointer),source_refs_sha256=digest(_refs(source_refs)),
  provider_permission_confirmed=False,production_promoted=False,commercial_use_permitted=False,public_raw_data_permitted=False)
 return dict(schema=SCHEMA,decision=decision,mac=_mac(decision))

def verify_owner_research_decision(record,*,source_pointer,state_content_sha256,dataset_pointer,now,source_refs=None):
 need(type(record) is dict and set(record)=={'schema','decision','mac'} and record['schema']==SCHEMA and
      type(record['decision']) is dict and set(record['decision'])==FIELDS,'OWNER_RESEARCH_RECORD_INVALID')
 d=record['decision']
 need(type(record['mac']) is str and re.fullmatch('[a-f0-9]{64}',record['mac']) and
      hmac.compare_digest(record['mac'],_mac(d)),'OWNER_RESEARCH_SIGNATURE_INVALID')
 need(d['repository_id']=='1416489937' and d['basis']==BASIS and d['purpose']=='EXISTING_TWO_FAMILY_SHADOW_FIT' and
      d['instruction_ref']=='OWNER_INSTRUCTION_20261107_PERSONAL_RESEARCH' and
      all(d[k] is False for k in ('provider_permission_confirmed','production_promoted','commercial_use_permitted','public_raw_data_permitted')),
      'OWNER_RESEARCH_USE_SCOPE_INVALID')
 now=_time(now);need(_time(d['issued_at'])<=now,'OWNER_RESEARCH_DECISION_FROM_FUTURE')
 need(now<_time(d['expires_at']),'OWNER_RESEARCH_DECISION_EXPIRED')
 need(all(d[k]==v for k,v in _bindings(source_pointer,state_content_sha256,dataset_pointer).items()),'OWNER_RESEARCH_SCOPE_CHANGED')
 need(re.fullmatch('[a-f0-9]{64}',str(d['source_refs_sha256'])),'OWNER_RESEARCH_SOURCE_SCOPE')
 if source_refs is not None:need(d['source_refs_sha256']==digest(_refs(source_refs)),'OWNER_RESEARCH_SOURCE_SET_CHANGED')
 return digest(record)
