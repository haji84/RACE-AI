"""Prepare a private context for the existing owner's live GitHub Pages check."""
import argparse
import base64
import hashlib
from collections import Counter
from datetime import date,datetime,timezone,timedelta
import json
import os
from pathlib import Path
import re
import sys
import traceback

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts import boat_saved_view_feed as CLI
from scripts import boat_private_original_vault as VCLI
from race_ai.existing_model_coverage import is_retired

JST=timezone(timedelta(hours=9))


def _need(value,reason):
    if not value:raise ValueError('SAVED_SITE_'+reason)


def _aware(value):
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        _need(parsed.utcoffset() is not None,'CLOCK_INVALID')
        return parsed
    except (AttributeError,TypeError,ValueError):
        raise ValueError('SAVED_SITE_CLOCK_INVALID') from None


def _selected_day(requested,now):
    _need(isinstance(now,datetime) and now.utcoffset() is not None,'CLOCK_INVALID')
    current=now.astimezone(JST).date().isoformat()
    if requested is None:return current
    try:valid=type(requested) is str and date.fromisoformat(requested).isoformat()==requested and requested<=current
    except (ValueError,TypeError):valid=False
    _need(valid,'EVENT_DAY_INVALID');return requested


def build_context(bootstrap,view,generation,*,now,require_future=False,event_day=None):
    _need(isinstance(now,datetime) and now.utcoffset() is not None,'CLOCK_INVALID')
    _need(type(generation) is int and generation>0,'GENERATION_INVALID')
    _need(type(bootstrap.get('key')) is bytes and len(bootstrap['key'])==32 and
          type(bootstrap.get('view_id')) is str and re.fullmatch('[a-f0-9]{64}',bootstrap['view_id']),
          'VIEWER_BINDING_INVALID')
    _need(type(view) is dict and type(view.get('records')) is list,'VIEW_INVALID')
    current=now.astimezone(JST).date().isoformat();day=_selected_day(event_day,now)
    rows=[r for r in view['records'] if r.get('sport')=='boat' and r['event_date_jst']==day]
    _need(bool(rows),'CURRENT_DAY_REQUIRED' if event_day is None else 'SELECTED_DAY_REQUIRED')
    native=set();future=None;probe=None;model_probe=None;model_counts=Counter()
    for row in rows:
        predictions=[p for p in [row.get('prediction'),*row.get('comparison_predictions',[])]
                     if p is not None and not is_retired(p.get('model_id'))]
        families={}
        for index,p in enumerate(predictions):
            tickets=p.get('ordered_top8');model_id=p.get('model_id')
            if isinstance(model_id,str) and model_id and isinstance(tickets,list) and 1<=len(tickets)<=8:
                families.setdefault(model_id,dict(model_id=model_id,index=index,tickets_sha256=hashlib.sha256(json.dumps(tickets,separators=(',',':')).encode()).hexdigest()))
        model_counts[len(families)]+=1
        if model_probe is None and len(families)>1 and row.get('cutoff_at'):
            model_probe=dict(race_id=row['race_id'],cutoff_at=row['cutoff_at'],choices=list(families.values())[:2])
        for index,p in enumerate(predictions):
            if not p or p.get('stage')!='P1' or p.get('native_dispatch_prediction') is not True or \
               p.get('external_receipt_verified') is not True or p.get('eligible_pre_cutoff') is not True:continue
            _need(type(p.get('model_id')) is str and 0<len(p['model_id'])<=256,'MODEL_ID_INVALID')
            cutoff=_aware(p.get('cutoff_at') or row.get('cutoff_at'))
            _need(all(_aware(p.get(k))<cutoff for k in ('generated_at','as_of','persisted_at')),
                  'ORIGINAL_CLOCK_INVALID')
            _need(all(_aware(p[k])<=now for k in ('generated_at','as_of','persisted_at')),
                  'FUTURE_ORIGINAL_CLOCK_INVALID')
            version=p.get('model_version');variant=p.get('variant')
            code=p.get('source_code_commit') if version is None and \
                type(p.get('source_code_commit')) is str and re.fullmatch('[a-f0-9]{40}',p['source_code_commit']) and \
                type(p.get('artifact_id')) is int and p['artifact_id']>0 and \
                type(p.get('original_json_sha256')) is str and re.fullmatch('[a-f0-9]{64}',p['original_json_sha256']) else None
            _need((version is None or type(version) is str) and (variant is None or type(variant) is str),
                  'MODEL_ID_INVALID')
            native.add((p['model_id'],version,variant,code))
            _need(re.fullmatch(r'[0-9]{8}-[0-9]{2}-[0-9]{2}',row['race_id']),'RACE_ID_INVALID')
            if probe is None:
                probe=dict(race_id=row['race_id'],index=index,cutoff_at=p.get('cutoff_at') or row.get('cutoff_at'))
            if now<cutoff and (future is None or cutoff>_aware(future['cutoff_at'])):
                _need(re.fullmatch(r'[0-9]{8}-[0-9]{2}-[0-9]{2}',row['race_id']),'RACE_ID_INVALID')
                future=dict(race_id=row['race_id'],index=index,cutoff_at=p.get('cutoff_at') or row['cutoff_at'])
    _need(bool(native),'NATIVE_P1_REQUIRED')
    _need(not require_future or future is not None,'FUTURE_NATIVE_REQUIRED')
    previous=sorted({r['event_date_jst'] for r in view['records']
                     if r.get('sport')=='boat' and r['event_date_jst']<day})
    old_day=previous[0] if previous else None
    completed=lambda records:sum((r.get('result') or {}).get('status') in ('final','void') for r in records)
    previews=[r for r in rows if r.get('cutoff_at') and isinstance((r.get('live_boat_observation') or {}).get('context'),dict)
        and any(p.get('display_time') is not None for p in ((r['live_boat_observation']['context'].get('beforeinfo') or {}).get('participants') or []))]
    preview_probe=dict(race_id=previews[0]['race_id'],cutoff_at=previews[0]['cutoff_at']) if previews else None
    key=base64.urlsafe_b64encode(bootstrap['key']).rstrip(b'=').decode('ascii')
    return dict(schema='RACE_AI_PRIVATE_LIVE_SITE_CHECK_CONTEXT_V1',
        owner_url='https://haji84.github.io/RACE-AI/#saved='+bootstrap['view_id']+'.'+key,
        day=day,current_day=current,date_scope='CURRENT_DAY' if day==current else 'HISTORICAL_DAY',
        generation=generation,day_races=len(rows),minimum_results=completed(rows),native_p1_groups=len(native),
        native_groups=[list(group) for group in sorted(native,key=lambda group:json.dumps(group))],native_probe=probe,
        live_beforeinfo_races=len(previews),live_beforeinfo_probe=preview_probe,
        model_switch_probe=model_probe,model_family_counts=dict(sorted(model_counts.items())),
        old_day=old_day,old_completed=completed([r for r in view['records'] if r.get('sport')=='boat'
            and r['event_date_jst']==old_day]),future_native=future)


def main(argv=None,*,now=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    parser.add_argument('--require-future',action='store_true')
    dates=parser.add_mutually_exclusive_group()
    dates.add_argument('--day',help='Explicit saved event day; current-day checks never silently fall back')
    dates.add_argument('--latest-saved-day',action='store_true')
    args=parser.parse_args(argv)
    try:
        repo=VCLI._environment(ROOT)
        folder=Path(os.environ['RUNNER_TEMP']).resolve();target=Path(args.output).resolve()
        _need(target.parent==folder and target.name=='boat-saved-site-context.json','PRIVATE_OUTPUT_REQUIRED')
        clock=now or datetime.now(timezone.utc);day=_selected_day(args.day,clock)
        config=CLI._json(CLI._read(ROOT/'audit/state/boat-saved-view-input.json',8192),8192)
        _need(config.get('schema')=='RACE_AI_SAVED_VIEW_INPUT_V1','INPUT_INVALID')
        raw=base64.b64decode(config['bootstrap'],validate=True)
        _need(CLI.sha(raw)==config['bootstrap_sha256'],'BOOTSTRAP_HASH_INVALID')
        bootstrap=CLI.F.open_bootstrap(raw);CLI.git_auth();git=CLI.F.FeedRepository(repo)
        _,_,generation,view=CLI.F.current_view(git,bootstrap,**(dict(day=day) if args.day is not None else {}))
        if args.latest_saved_day:
            day=max((r['event_date_jst'] for r in view['records'] if r.get('sport')=='boat' and r['event_date_jst']<=day),default=None)
            _need(day is not None,'CURRENT_DAY_REQUIRED')
        history=getattr(git,'_saved_history_context',None)
        if history:
            earlier=sorted(d for d in history['index']['days'] if d<day)
            if earlier:
                _,_,_,old=CLI.F.current_view(git,bootstrap,day=earlier[0])
                view=dict(view,records=[*view['records'],*old['records']])
        context=build_context(bootstrap,view,generation,now=clock,require_future=args.require_future,event_day=day if args.latest_saved_day else args.day)
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(context,stream,ensure_ascii=False,sort_keys=True);stream.write('\n')
        print(json.dumps(dict(status='SAVED_SITE_PRIVATE_CONTEXT_READY',generation=generation,
            checked_day=context['day'],current_day=context['current_day'],date_scope=context['date_scope'],
            native_p1_groups=context['native_p1_groups'],completed_results=context['minimum_results'],
            live_beforeinfo_races=context['live_beforeinfo_races'],
            model_family_counts=context['model_family_counts'],model_switch_probe_available=context['model_switch_probe'] is not None,
            future_native_available=context['future_native'] is not None,plaintext_published=False,
            official_source_requests=0),sort_keys=True))
        return 0
    except Exception as error:
        reason=str(error) if isinstance(error,ValueError) and re.fullmatch(
            r'(?:SAVED_SITE|FEED|HISTORY|VAULT|STATE)_[A-Z0-9_]{1,100}',str(error)) else 'SAVED_SITE_OPERATION_FAILED'
        trace=[Path(frame.filename).name+':'+str(frame.lineno)+':'+frame.name
               for frame in traceback.extract_tb(error.__traceback__)[-5:]]
        print(json.dumps(dict(status='SAVED_SITE_CONTEXT_REJECTED',reason=reason,code_trace=trace),sort_keys=True))
        return 2


if __name__=='__main__':raise SystemExit(main())
