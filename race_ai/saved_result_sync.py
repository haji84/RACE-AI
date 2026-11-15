"""Private result-only journal. No HTTP, prediction, formal scoring or key use."""
from copy import deepcopy
from datetime import date,datetime,timezone,timedelta
import hashlib
import itertools
import json
from pathlib import Path
import re
import race_ai

from .boat_history_store import instant,wire
from .boat_pdca_state import need
from .actions_contract import digest
from .private_cycle_projection import _observation

JOURNAL='viewer-result-journal.json'
SCHEMA='RACE_AI_SAVED_RESULTS_JOURNAL_V1'
REFERENCE=str(Path(__file__).resolve().parents[1]/'pr64-reference'/'race_ai')
if REFERENCE not in race_ai.__path__:race_ai.__path__.append(REFERENCE)

def parse_capture(raw,receipt):
    """Use selected official race identity, six finishes and this market only.

    Start times and unrelated betting-market payouts are not required facts for
    a trifecta result. Missing identities or winning coverage never settle.
    """
    if str(receipt.get('source_url','')).startswith('https://www.boatrace.jp/owsp/sp/spdata?'):
        from .boat_sp_settlement import parse_settlement
        return parse_settlement(raw,receipt,now=instant(receipt['captured_at']))
    from . import official_race_updates as old
    need(type(raw) is bytes and len(raw)<=3*1024*1024 and receipt.get('http_status')==200,'RESULT_CAPTURE_INVALID')
    need(hashlib.sha256(raw).hexdigest()==receipt.get('source_sha256'),'RESULT_CAPTURE_HASH_MISMATCH')
    day,venue,number=old.identity(receipt['source_url'],path='/owpc/pc/race/raceresult')
    event=date(int(day[:4]),int(day[4:6]),int(day[6:8]))
    frame,base=old.context(raw,'raceresult',event,venue,number,receipt['source_url'],receipt['captured_at'])
    if frame is None:return base
    cancellation_panels=[n for n in frame.children if isinstance(n,old.Node) and n.tag=='div' and n.has('title12')]
    headings=[n.text().strip() for panel in cancellation_panels for n in panel.children if isinstance(n,old.Node) and n.tag=='h3' and n.has('title12_title')]
    if set(headings).intersection({'レース中止','不成立'}):
        need(len(cancellation_panels)==1 and len(headings)==1,'RESULT_CANCELLATION_LAYOUT_AMBIGUOUS')
        for table in frame.find('table'):
            head=next(table.find('thead'),None)
            if head is not None and all(label in head.text() for label in ('着','枠','ボートレーサー','レースタイム')):
                need(not any(re.search('[0-9]{4}',body.text()) for body in table.find('tbody')),'RESULT_CANCELLATION_CONFLICT')
        paid_tables=[table for table in frame.find('table') if (head:=next(table.find('thead'),None)) is not None and all(label in head.text() for label in ('勝式','組番','払戻金'))]
        need(len(paid_tables)<=1,'RESULT_CANCELLATION_CONFLICT')
        for table in paid_tables:
            for values in old.expanded_rows(table,4):
                combo,amount=values[1].text().strip(),values[2].text().strip()
                need(combo in ('','-','--','―','—') and amount in ('','-','--','―','—'),'RESULT_CANCELLATION_CONFLICT')
        return dict(base,status='AVAILABLE',data=dict(status='cancelled',confirmed=True,finish_confirmed=False,
            results=[],payouts=[],refund_boats=[],refunds=[],top3=None,confirmed_scope='TRIFECTA_ONLY'))
    try:table=old.table_with(frame,'着','枠','ボートレーサー','レースタイム')
    except old.SourceError:
        return dict(base,status='PENDING',data=None,missing_reason='OFFICIAL_RESULT_FINISH_NOT_PUBLISHED')
    records=[]
    for body in table.find('tbody'):
        for row in body.find('tr'):
            cells=old.cells(row);need(len(cells)==4,'RESULT_FINISH_ROW_INVALID')
            finish,lane=cells[0].text().strip(),cells[1].text().strip()
            person=re.fullmatch(r'\s*([0-9]{4})(?!\d)\s*(.+?)\s*',cells[2].text())
            need(re.fullmatch('[1-6]',lane) and cells[1].has('is-boatColor'+lane) and person,'RESULT_ROSTER_IDENTITY_MISMATCH')
            need(finish in {'1','2','3','4','5','6','欠','転','落','沈','失','妨','不','F','L','エ'},'RESULT_FINISH_DISPOSITION_UNKNOWN')
            records.append(dict(race_id=base['race_id'],lane=int(lane),racer_registration_id=person[1],
                name=person[2].strip(),finish=int(finish) if finish.isdecimal() else None,
                finish_status='FINISHED' if finish.isdecimal() else finish,verified_official=True))
    need(3<=len(records)<=6 and len({r['lane'] for r in records})==len(records) and
         len({r['racer_registration_id'] for r in records})==len(records),'RESULT_ROSTER_IDENTITY_MISMATCH')
    payouts=[]
    for cells in old.expanded_rows(old.table_with(frame,'勝式','組番','払戻金'),4):
        label,combo,amount,_=(c.text().strip() for c in cells)
        if label!='3連単' or not combo and not amount:continue
        need('特払' not in combo,'RESULT_SPECIAL_PAYOUT_REVIEW')
        values=[int(v) for v in re.findall('[1-6]',combo)]
        need(len(values)==3 and len(set(values))==3 and not re.sub(r'[1-6\s=\-]','',combo),'RESULT_WINNER_INVALID')
        money=re.sub(r'[￥¥円,\s]','',amount)
        need(re.fullmatch('[0-9]+',money) and 1<=int(money)<=9007199254740991,'RESULT_PAYOUT_INVALID')
        payouts.append(dict(bet_type='trifecta',combination=values,payout_per_100_yen=int(money)))
    winners={tuple(p['combination']) for p in payouts}
    finishes={r['lane']:r['finish'] for r in records}
    expected=set()
    for t in itertools.permutations(finishes,3):
        places=[finishes[n] for n in t]
        if all(type(p) is int for p in places) and places==sorted(places) and places[0]==1 and places[-1]<=3 and all(n in t for n,p in finishes.items() if p is not None and p<places[-1]):expected.add(t)
    need(winners and len(winners)==len(payouts) and winners==expected,'RESULT_WINNER_MISMATCH')
    returned=[]
    for item in old.table_with(frame,'返還').find(css='numberSet1_number'):
        text=item.text().strip();need(re.fullmatch('[1-6]',text) and int(text) not in returned,'RESULT_REFUND_INVALID');returned.append(int(text))
    need(not any(set(t).intersection(returned) for t in winners),'RESULT_WINNER_REFUND_CONFLICT')
    need(all(r['lane'] in returned for r in records if r['finish_status'] in ('F','L','欠')),'RESULT_REFUND_DISPOSITION_MISSING')
    numeric=[p for p in finishes.values() if p is not None]
    return dict(base,status='AVAILABLE',data=dict(status='settled',confirmed=True,finish_confirmed=True,
        confirmed_scope='TRIFECTA_ONLY',results=records,payouts=payouts,top3=payouts[0]['combination'],
        dead_heat=len(numeric)!=len(set(numeric)),refund_boats=sorted(returned),refunds=None if returned else []))

def _merge(items):
    out={}
    for o in items:
        need(type(o) is dict and re.fullmatch('[0-9]{8}-[0-9]{2}-[0-9]{2}',o.get('race_id','')),'RESULT_OBSERVATION_IDENTITY_INVALID')
        key=(o['race_id'],instant(o['captured_at']));previous=out.get(key)
        need(previous is None or wire(previous)==wire(o),'RESULT_CAPTURE_CONFLICT')
        out.setdefault(key,deepcopy(o))
    return [out[k] for k in sorted(out)]

def _document(state):
    row=state.db.execute('SELECT sha FROM heads WHERE name=?',(JOURNAL,)).fetchone()
    if row is None:return dict(schema=SCHEMA,observations=[],captures=[],synced_at=None)
    doc=json.loads(state._get(row[0]));need(doc.get('schema')==SCHEMA,'RESULT_JOURNAL_SCHEMA_INVALID');return doc

def retain_batch(state,observations,captures=()):
    """Append observations and raw pages, without touching pairs/results/scores."""
    observations=list(observations);captures=list(captures)
    doc=_document(state);need(len(doc['observations'])+len(observations)<=10000,'RESULT_JOURNAL_BOUND')
    merged=_merge([*doc['observations'],*observations])
    existing={ (v['source_sha256'],v['captured_at']):v for v in doc['captures'] }
    parsed=[]
    for capture in captures:
        raw,receipt=capture['raw'],capture['receipt'];parsed.append(parse_capture(raw,receipt))
        key=(receipt['source_sha256'],receipt['captured_at']);need(key not in existing or existing[key]==receipt,'RESULT_CAPTURE_CONFLICT');existing[key]=deepcopy(receipt)
    # Conflicts with old structured observations must stop before journal mutation.
    old=[json.loads(body) for body, in state.db.execute('SELECT body FROM results')]
    previous_observations,_,_=read_batch(state)
    _merge([*old,*previous_observations,*merged,*parsed])
    need(all(instant(o['captured_at'])<=datetime.now(timezone.utc) for o in [*merged,*parsed]),'RESULT_FUTURE_CAPTURE')
    if merged==doc['observations'] and list(existing.values())==doc['captures']:
        return dict(observations=len(merged),captures=len(existing),synced_at=doc['synced_at'])
    with state.db:
        for capture in captures:
            state._put('viewer-result-sources/'+capture['receipt']['source_sha256']+'.html',capture['raw'])
        doc=dict(schema=SCHEMA,observations=merged,captures=list(existing.values()),synced_at=datetime.now(timezone.utc).isoformat())
        state._put(JOURNAL,(wire(doc)+'\n').encode())
    return dict(observations=len(merged),captures=len(existing),synced_at=doc['synced_at'])

def read_batch(state):
    doc=_document(state);observations=list(doc['observations']);raw_sources=set()
    for receipt in doc['captures']:
        source=receipt['source_sha256'];raw=state._get(source)
        parsed=parse_capture(raw,receipt);observations.append(parsed);raw_sources.add(digest(parsed))
    return _merge(observations),raw_sources,doc['synced_at']

def project_observation(observation,row,*,freeze_at,raw_bound=False):
    """Keep strict scoring intact; flag an optional raw-backed UI reference."""
    if row.get('cutoff_at') is None and len(row.get('saved_cutoff_variants',[]))>1 and raw_bound:
        return _reconcile_original_cutoffs(observation,row)
    try:return _observation(observation,row)
    except ValueError as error:
        if str(error)!='RESULT_CUTOFF_MISMATCH' or not raw_bound:raise
    original,observed=instant(row['cutoff_at']),instant(observation['closed_at'])
    jst=timezone(timedelta(hours=9));offset=(observed-original).total_seconds()
    data=observation.get('data') or {}
    cancelled=data.get('status') in ('cancelled','no_contest') and data.get('confirmed') is True
    sp=observation.get('schedule_binding')=='SP_EXPLICIT_RACE_HEADER'
    need(original.astimezone(jst).date()==observed.astimezone(jst).date() and (cancelled or abs(offset)<=60 or sp),'RESULT_CUTOFF_MISMATCH')
    if sp:
        forecasts=[p for p in [row.get('prediction'),*row.get('comparison_predictions',[])] if p is not None]
        need(forecasts and all(p.get('persisted_at') is not None and instant(p['persisted_at'])<min(original,observed) and
            all(p.get(k) is None or instant(p[k])<min(original,observed) for k in ('as_of','generated_at','source_captured_at','server_saved_at')) for p in forecasts),'RESULT_CUTOFF_REFERENCE_CHRONOLOGY')
    need(instant(freeze_at)<(original if cancelled else min(original,observed)) and instant(observation['captured_at'])>=max(original,observed),'RESULT_CUTOFF_REFERENCE_CHRONOLOGY')
    need(3<=len(row.get('participants',[]))<=6 and (cancelled or 3<=len(data.get('results',[]))<=6),'RESULT_CUTOFF_REFERENCE_ROSTER_REQUIRED')
    reference=_observation(observation,{**row,'cutoff_at':observation['closed_at'],'saved_cutoff_variants':[observation['closed_at']]})
    reference['cutoff_reference']=dict(original_cutoff_at=row['cutoff_at'],result_schedule_cutoff_at=observation['closed_at'],offset_seconds=offset,formal_eligible=False,basis='RAW_OFFICIAL_CANCELLATION_SELECTED_RACE' if cancelled else 'RAW_OFFICIAL_SP_SAME_ROSTER_SAVED_BEFORE_BOTH' if sp else 'RAW_OFFICIAL_PAGE_SAME_ROSTER_SAVED_BEFORE_BOTH')
    return reference

def _reconcile_original_cutoffs(observation,row):
    """Project the same authenticated raw result against every saved clock.

    This is a display reference only. No original cutoff or formal settlement
    is changed. Explicit SP headers check each forecast against its own cutoff
    and the source cutoff, rather than another model's earlier saved cutoff.
    """
    from .boat_saved_model_view import validate_cutoff_reconciliation
    need(observation.get('body_identity_verified') is True and isinstance(observation.get('closed_at'),str),'RESULT_IDENTITY_UNVERIFIED')
    variants=row['saved_cutoff_variants'];clocks=[instant(c) for c in variants]+[instant(observation['closed_at'])]
    per_model=observation.get('schedule_binding')=='SP_EXPLICIT_RACE_HEADER'
    need(per_model or (max(clocks)-min(clocks)).total_seconds()<=60,'RESULT_CUTOFF_MISMATCH')
    predictions=[p for p in [row.get('prediction'),*row.get('comparison_predictions',[])] if p is not None]
    need(predictions,'RESULT_CUTOFF_REFERENCE_CHRONOLOGY')
    if per_model:
        need(all(isinstance(p.get('cutoff_at'),str) and instant(p['cutoff_at']) in clocks[:-1] for p in predictions),'RESULT_CUTOFF_REFERENCE_CHRONOLOGY')
    projected=[]
    for cutoff in variants:
        group=[p for p in predictions if not per_model or instant(p['cutoff_at'])==instant(cutoff)]
        need(group,'RESULT_CUTOFF_REFERENCE_CHRONOLOGY')
        narrow={**row,'cutoff_at':cutoff,'saved_cutoff_variants':[cutoff],'prediction':group[0],'comparison_predictions':group[1:]}
        saved=max(instant(p['persisted_at']) for p in group)
        result=project_observation(observation,narrow,freeze_at=saved.isoformat(),raw_bound=True)
        result.pop('cutoff_reference',None);projected.append(result)
    need(all(wire(r)==wire(projected[0]) for r in projected),'RESULT_CUTOFF_REFERENCE_CONFLICT')
    result=projected[0]
    result['cutoff_reconciliation']=dict(basis='RAW_OFFICIAL_SP_RESULT_PER_SAVED_MODEL_CUTOFF' if per_model else 'RAW_OFFICIAL_RESULT_PER_ORIGINAL_CUTOFF',formal_eligible=False,
        original_cutoffs=list(variants),source_sha256=observation['source_sha256'],
        maximum_offset_seconds=(max(clocks)-min(clocks)).total_seconds(),
        roster_identity_verified=True,all_originals_saved_before_both=True)
    if per_model:
        result['cutoff_reconciliation'].update(source_cutoff_at=observation['closed_at'],source_schedule_binding='SP_EXPLICIT_RACE_HEADER')
    validate_cutoff_reconciliation(row,result)
    return result
