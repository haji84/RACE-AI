"""Prepare a private context for the existing owner's live GitHub Pages check."""
import argparse
import base64
from datetime import date,datetime,timezone,timedelta
import json
import math
import os
from pathlib import Path
import re
import sys
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts import boat_saved_view_feed as CLI
from scripts import boat_private_original_vault as VCLI
from race_ai.existing_model_coverage import is_retired

JST=timezone(timedelta(hours=9))
SIMULATION_SCHEMA='RACE_AI_SAVED_SITE_SIMULATION_EXPECTED_V1'
COMPARISON_FIELDS={'hits','misses','pending','void','noForecast','review'}
FINANCIAL_FIELDS={'budgetPerDay','raceBudget','budgetTotal','spent','reserved','held','unspent',
    'payout','refund','settledStake','settledCount','pendingStake','bought','skippedBudget',
    'balance','settledNet','net','roi'}


def _need(value,reason):
    if not value:raise ValueError('SAVED_SITE_'+reason)


class SnapshotFeedRepository(CLI.F.FeedRepository):
    """Pin one read-only feed generation and fetch only needed snapshots."""
    def __init__(self,repo,*,snapshot):
        self._snapshot_parent=None
        super().__init__(repo)
        target=Path(snapshot)
        _need(target.is_dir() and not target.is_symlink() and not any(target.iterdir())
              and target.stat().st_mode&0o077==0,'SNAPSHOT_DIRECTORY_REQUIRED')
        self.repo=target.resolve()
        self._run(['init','--bare'])

    def head(self):
        if self._snapshot_parent is None:
            parent=super().head()
            _need(type(parent) is str and re.fullmatch('[a-f0-9]{40}',parent),'SNAPSHOT_REF_REQUIRED')
            self._snapshot_parent=parent
        return self._snapshot_parent

    def fetch(self,commit):
        _need(type(commit) is str and re.fullmatch('[a-f0-9]{40}',commit),'SNAPSHOT_COMMIT_INVALID')
        present=subprocess.run(['git','cat-file','-t',commit],cwd=self.repo,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15)
        _need(present.returncode in (0,128),'SNAPSHOT_COMMIT_INSPECTION_FAILED')
        target='refs/race-ai/pinned-state/'+commit
        if present.returncode==0:
            _need(present.stdout==b'commit\n','SNAPSHOT_COMMIT_INVALID')
            self._run(['update-ref',target,commit])
            return
        self._run(['fetch','--no-tags','--no-write-fetch-head','--depth=1',
            self.fetch_url,commit+':'+target])
        _need(self._run(['cat-file','-t',commit])==b'commit\n','SNAPSHOT_COMMIT_INVALID')

    def commit(self,*args,**kwargs):raise ValueError('SAVED_SITE_READ_ONLY_TRANSPORT')
    def commit_snapshot(self,*args,**kwargs):raise ValueError('SAVED_SITE_READ_ONLY_TRANSPORT')
    def push(self,*args,**kwargs):raise ValueError('SAVED_SITE_READ_ONLY_TRANSPORT')


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
    native=set();native_races=set();future_races=set();native_cutoffs=[];future=None;probe=None
    for row in rows:
        predictions=[p for p in [row.get('prediction'),*row.get('comparison_predictions',[])]
                     if p is not None and not is_retired(p.get('model_id'))]
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
            native_races.add(row['race_id']);native_cutoffs.append(cutoff)
            if probe is None:
                probe=dict(race_id=row['race_id'],index=index,cutoff_at=p.get('cutoff_at') or row.get('cutoff_at'))
            if now<cutoff and (future is None or cutoff>_aware(future['cutoff_at'])):
                _need(re.fullmatch(r'[0-9]{8}-[0-9]{2}-[0-9]{2}',row['race_id']),'RACE_ID_INVALID')
                future=dict(race_id=row['race_id'],index=index,cutoff_at=p.get('cutoff_at') or row['cutoff_at'])
            if now<cutoff:future_races.add(row['race_id'])
    _need(bool(native),'NATIVE_P1_REQUIRED')
    _need(not require_future or future is not None,'FUTURE_NATIVE_REQUIRED')
    previous=sorted({r['event_date_jst'] for r in view['records']
                     if r.get('sport')=='boat' and r['event_date_jst']<day})
    old_day=previous[0] if previous else None
    completed=lambda records:sum((r.get('result') or {}).get('status') in ('final','void') for r in records)
    key=base64.urlsafe_b64encode(bootstrap['key']).rstrip(b'=').decode('ascii')
    return dict(schema='RACE_AI_PRIVATE_LIVE_SITE_CHECK_CONTEXT_V1',
        owner_url='https://haji84.github.io/RACE-AI/#saved='+bootstrap['view_id']+'.'+key,
        day=day,current_day=current,date_scope='CURRENT_DAY' if day==current else 'HISTORICAL_DAY',
        generation=generation,day_races=len(rows),minimum_results=completed(rows),native_p1_groups=len(native),
        native_p1_races=len(native_races),future_native_races=len(future_races),
        latest_native_cutoff_lead_seconds=int((max(native_cutoffs)-now).total_seconds()),
        native_groups=[list(group) for group in sorted(native,key=lambda group:json.dumps(group))],native_probe=probe,
        old_day=old_day,old_completed=completed([r for r in view['records'] if r.get('sport')=='boat'
            and r['event_date_jst']==old_day]),future_native=future)


def _simulation_context(view,context):
    """Keep authenticated rows in process pipes; accept only aggregate fields."""
    def count(value):return type(value) is int and 0<=value<=9007199254740991
    def counts(value,fields):
        return type(value) is dict and set(value)==fields and all(count(v) for v in value.values())
    try:
        request=dict(view=view,day=context['day'],generation=context['generation'],as_of=context['simulation_as_of'],native_groups=context['native_groups'])
        child_environment={'PATH':os.environ.get('PATH',''),'LANG':'C.UTF-8','TZ':'UTC'}
        result=subprocess.run(['node',str(ROOT/'scripts/boat_saved_simulation_context.cjs')],
            input=json.dumps(request,ensure_ascii=False),text=True,capture_output=True,check=False,timeout=45,env=child_environment)
        if result.returncode!=0 or result.stderr or len(result.stdout.encode('utf-8'))>65536:raise ValueError()
        value=json.loads(result.stdout)
        if type(value) is not dict or set(value)!={'schema','day','generation','group_sha256',
            'eligible_native_races','issued_races','observed','observed_closed','lifecycle','scenarios','budget_cap_exercised','budget_cap_coverage'}:raise ValueError()
        if value['schema']!=SIMULATION_SCHEMA or value['day']!=context['day'] or \
            type(value['generation']) is not int or value['generation']!=context['generation']:raise ValueError()
        if type(value['group_sha256']) is not str or not re.fullmatch('[a-f0-9]{64}',value['group_sha256']):raise ValueError()
        if not count(value['eligible_native_races']) or value['eligible_native_races']<1 or not count(value['issued_races']):raise ValueError()
        observed=value['observed']
        if not counts(observed,COMPARISON_FIELDS|{'races','available'}) or \
            not value['eligible_native_races']<=value['issued_races']<=observed['races'] or \
            observed['races']!=context['day_races'] or observed['available']>observed['races'] or \
            sum(observed[k] for k in COMPARISON_FIELDS)!=observed['races']:raise ValueError()
        lifecycle=value['lifecycle'];closed=value['observed_closed']
        if type(lifecycle) is not dict or set(lifecycle)!={'as_of','closed','upcoming','unknown'} or \
            _aware(lifecycle['as_of'])!=_aware(context['simulation_as_of']) or \
            not all(count(lifecycle[k]) for k in ('closed','upcoming','unknown')) or \
            sum(lifecycle[k] for k in ('closed','upcoming','unknown'))!=observed['races']:raise ValueError()
        if not counts(closed,COMPARISON_FIELDS|{'races','available'}) or closed['races']!=lifecycle['closed'] or \
            closed['available']>closed['races'] or sum(closed[k] for k in COMPARISON_FIELDS)!=closed['races'] or \
            any(closed[k]>observed[k] for k in COMPARISON_FIELDS|{'available'}):raise ValueError()
        scenarios=value['scenarios']
        if type(scenarios) is not list or len(scenarios)!=4:raise ValueError()
        combinations=set()
        for scenario in scenarios:
            if type(scenario) is not dict or set(scenario)!=FINANCIAL_FIELDS|{'comparison','boughtComparison'}:raise ValueError()
            if any(not count(scenario[k]) for k in FINANCIAL_FIELDS-{'settledNet','net','roi'}):raise ValueError()
            for name in ('settledNet','net'):
                if scenario[name] is not None and not (type(scenario[name]) is int and abs(scenario[name])<=9007199254740991):raise ValueError()
            roi=scenario['roi']
            if roi is not None and not (type(roi) in (int,float) and math.isfinite(roi) and roi>=0):raise ValueError()
            for name in ('comparison','boughtComparison'):
                if not counts(scenario[name],COMPARISON_FIELDS):raise ValueError()
            if scenario['comparison']!={k:observed[k] for k in COMPARISON_FIELDS} or \
                sum(scenario['boughtComparison'].values())!=scenario['bought'] or scenario['bought']>observed['races']:raise ValueError()
            pair=(scenario['budgetPerDay'],scenario['raceBudget'])
            if pair in combinations:raise ValueError()
            combinations.add(pair)
        if combinations!={(10000,800),(10000,1000),(5000,800),(5000,1000)}:raise ValueError()
        capped=all(next(s['bought'] for s in scenarios if (s['budgetPerDay'],s['raceBudget'])==(10000,race))>
                   next(s['bought'] for s in scenarios if (s['budgetPerDay'],s['raceBudget'])==(5000,race)) for race in (800,1000))
        if type(value['budget_cap_exercised']) is not bool or value['budget_cap_exercised']!=capped or \
            value['budget_cap_coverage']!=('EXERCISED' if capped else 'INSUFFICIENT_ELIGIBLE_RACES'):raise ValueError()
        return value
    except Exception:
        raise ValueError('SAVED_SITE_SIMULATION_CONTEXT_REJECTED') from None


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
        bootstrap=CLI.F.open_bootstrap(raw);CLI.git_auth()
        with tempfile.TemporaryDirectory(prefix='boat-site-snapshot-',dir=folder) as snapshot:
            git=SnapshotFeedRepository(repo,snapshot=snapshot)
            parent,_,generation,view=CLI.F.current_view(git,bootstrap,**(dict(day=day) if args.day is not None else {}))
            if args.latest_saved_day:
                day=max((r['event_date_jst'] for r in view['records'] if r.get('sport')=='boat' and r['event_date_jst']<=day),default=None)
                _need(day is not None,'CURRENT_DAY_REQUIRED')
            history=getattr(git,'_saved_history_context',None)
            if history:
                earlier=sorted(d for d in history['index']['days'] if d<day)
                if earlier:
                    old_parent,_,old_generation,old=CLI.F.current_view(git,bootstrap,day=earlier[0])
                    _need((old_parent,old_generation)==(parent,generation),'SNAPSHOT_GENERATION_CHANGED')
                    view=dict(view,records=[*view['records'],*old['records']])
        context=build_context(bootstrap,view,generation,now=clock,event_day=day if args.latest_saved_day else args.day)
        _need(not args.require_future or context['future_native'] is not None,'FUTURE_NATIVE_REQUIRED')
        context['simulation_as_of']=clock.isoformat()
        context['simulation_expected']=_simulation_context(view,context)
        context['numeric_simulation_required']=True
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(context,stream,ensure_ascii=False,sort_keys=True);stream.write('\n')
        print(json.dumps(dict(status='SAVED_SITE_PRIVATE_CONTEXT_READY',generation=generation,
            checked_day=context['day'],current_day=context['current_day'],date_scope=context['date_scope'],
            native_p1_groups=context['native_p1_groups'],completed_results=context['minimum_results'],
            native_p1_races=context['native_p1_races'],future_native_races=context['future_native_races'],
            latest_native_cutoff_lead_seconds=context['latest_native_cutoff_lead_seconds'],
            numeric_simulation_required=True,numeric_simulation_scenarios=len(context['simulation_expected']['scenarios']),
            numeric_budget_cap_coverage=context['simulation_expected']['budget_cap_coverage'],
            future_native_available=context['future_native'] is not None,plaintext_published=False,
            official_source_requests=0),sort_keys=True))
        return 0
    except Exception as error:
        reason=str(error) if isinstance(error,ValueError) and re.fullmatch(
            r'(?:SAVED_SITE|FEED|HISTORY|VAULT|STATE)_[A-Z0-9_]{1,100}',str(error)) else 'SAVED_SITE_OPERATION_FAILED'
        report=dict(status='SAVED_SITE_CONTEXT_REJECTED',reason=reason)
        if reason=='SAVED_SITE_FUTURE_NATIVE_REQUIRED' and 'context' in locals():
            report.update({k:context[k] for k in ('generation','native_p1_groups','native_p1_races',
                'future_native_races','latest_native_cutoff_lead_seconds')})
            report.update(checked_day=context['day'],current_day=context['current_day'],
                date_scope=context['date_scope'],official_source_requests=0,plaintext_published=False)
        print(json.dumps(report,sort_keys=True))
        return 2


if __name__=='__main__':raise SystemExit(main())
