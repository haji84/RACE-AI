"""Match retained official results to existing encrypted saved forecasts only."""
import base64,json
from copy import deepcopy
from datetime import date
from pathlib import Path
from . import saved_view_feed as F,saved_view_history as H
from .racer_daily import need,clock,wire,sha,JST
from .racer_daily_handoff import _DailyFilteredFetch

class ResultFeedRepository(_DailyFilteredFetch,F.FeedRepository):pass

def status(*,now,state='READY',rows=(),changed=0):
    values=[r for r in rows if r.get('sport')=='boat'];confirmed=sum((r.get('result') or {}).get('status') in ('final','void') for r in values);held=sum((r.get('result') or {}).get('status')=='unsupported' for r in values)
    return dict(schema='RACE_AI_RESULT_SYNC_V1',state=state,checked_at=clock(now).isoformat(),races=len(values),confirmed=confirmed,pending=len(values)-confirmed-held,held=held,changed_races=changed)

class SavedResultBridge:
    def __init__(self,repo,*,now,transport=None,bootstrap=None):
        self.now=clock(now);self.git=transport or ResultFeedRepository(repo)
        if bootstrap is None:
            path=Path(repo)/'audit/state/boat-saved-view-input.json';need(path.stat().st_size<=8192,'RESULT_FEED_INPUT_BOUND');config=json.loads(path.read_bytes())
            need(set(config)=={'schema','bootstrap','bootstrap_sha256','catchup_artifact_id','catchup_sha256'} and config['schema']=='RACE_AI_SAVED_VIEW_INPUT_V1','RESULT_FEED_INPUT_INVALID')
            raw=base64.b64decode(config['bootstrap'],validate=True);need(sha(raw)==config['bootstrap_sha256'],'RESULT_FEED_BOOTSTRAP_HASH');bootstrap=F.open_bootstrap(raw)
        self.bootstrap=bootstrap;_,_,_,view=F.current_view(self.git,self.bootstrap);context=getattr(self.git,'_saved_history_context',None);today=self.now.astimezone(JST).date().isoformat()
        if context:
            reader=F._history_reader(self.git);load=lambda loc:H.decrypt_catalog(reader(loc),self.bootstrap['key'],view_id=self.bootstrap['view_id']);dates=[]
            for index in H._indexes(context['index'],load):
                dates.extend(day for day in index['days'] if day<=today)
            self.available_days=sorted(set(dates),reverse=True)
            self.days=self.available_days[:2]
            self.views={d:F.current_view(self.git,self.bootstrap,day=d)[3] for d in self.days};self.history=True
        else:
            self.available_days=sorted({r['event_date_jst'] for r in view['records'] if r['event_date_jst']<=today},reverse=True)
            self.days=self.available_days[:2];self.views={None:view};self.history=False
        self.rows=[r for v in self.views.values() for r in v['records'] if r['event_date_jst'] in self.days and r.get('sport')=='boat']
        need(len(self.rows)<=576,'RESULT_FEED_RACE_BOUND')

    def choose_older_pending_day(self):
        """Read AES authenticated history; return one older unsettled day, no source GET.

        The first pass favors recently expired days. Never infer a race result
        from age, a forecast, or the existence of a source request.
        """
        if not self.history:return None
        for day in self.available_days[2:18]:
            historical=F.current_view(self.git,self.bootstrap,day=day)[3]
            if any(row.get('sport')=='boat' and row['event_date_jst']==day and
                   (row.get('result') or {}).get('status') not in ('final','void')
                   for row in historical['records']):
                return day
        return None

    def include_backfill_day(self,day):
        """Append the exact preflight-approved AES day; preserve all originals."""
        if day is None:return
        need(type(day) is str and day in self.available_days,'RESULT_BACKFILL_DAY_NOT_AUTHENTICATED')
        if day in self.days:return
        need(self.history and len(self.days)==2 and day<self.days[-1],'RESULT_BACKFILL_SCOPE_INVALID')
        view=F.current_view(self.git,self.bootstrap,day=day)[3]
        self.views[day]=view;self.days.append(day)
        self.rows.extend(r for r in view['records'] if r.get('sport')=='boat'
                         and r['event_date_jst']==day)
        need(len(self.rows)<=576 and len({r['race_id'] for r in self.rows})==len(self.rows),
             'RESULT_FEED_BACKFILL_RACE_BOUND')

    def targets(self):
        output=[]
        for row in self.rows:
            times=[v for v in row.get('saved_cutoff_variants',[]) if v]
            cutoff=row.get('cutoff_at') or (min(times,key=clock) if times else None)
            result=row.get('result') or {};pending=result.get('status') not in ('final','void')
            captures=[o.get('captured_at') for o in row.get('result_observations',[]) if o.get('captured_at')]
            if result.get('observed_at'):captures.append(result['observed_at'])
            output.append(dict(race_id=row['race_id'],cutoff_at=cutoff,pending=pending,after=max(captures,key=clock) if captures else None))
        return output

    def prepare(self,state):
        """Only a freshly authenticated feed acknowledges a retained capture."""
        pointers=state.control.get('settlement_captures',{})
        if not pointers:return
        acknowledged=state.control.setdefault('settlement_published',{});active={r['race_id'] for r in self.rows}
        for row in self.rows:
            pointer=pointers.get(row['race_id']);result=row.get('result') or {}
            if pointer and result.get('status') in ('final','void') and result.get('source_sha256')==pointer['source_sha256'] and result.get('observed_at') and clock(result['observed_at'])>=clock(pointer['captured_at']):acknowledged[row['race_id']]=pointer['settlement_sha256']
        for rid,pointer in list(pointers.items()):
            if rid not in active and acknowledged.get(rid)==pointer['settlement_sha256']:
                del pointers[rid];acknowledged.pop(rid,None);state.control.get('settlement_next',{}).pop(rid,None)

    def publish(self,state,*,now):
        now=clock(now);changed=0;rows=[];pointers=state.control.get('settlement_captures',{})
        for day in sorted(self.views,key=lambda v:v or ''):
            parent,previous,generation,view=F.current_view(self.git,self.bootstrap,day=day)
            selected={r['race_id'] for r in view['records'] if r['event_date_jst'] in self.days and r.get('sport')=='boat'}
            retained={rid:state.capture(pointer) for rid,pointer in pointers.items() if rid in selected}
            captures=list(retained.values())
            if captures or any(rid in state.control.get('beforeinfo_checks',{}) for rid in selected):
                observations=[]
                for row in view['records']:
                    capture=retained.get(row['race_id'])
                    if capture is None:continue
                    receipt=capture[1]
                    observations.extend(o for o in row.get('result_observations',[])
                        if o.get('race_id')==row['race_id'] and all(o.get(k)==receipt.get(k)
                            for k in ('captured_at','source_sha256','source_url')))
                # Keep the stored observation intact; matching retained bytes
                # supply only the current parser's display projection.
                updated=F.update_view(view,observations,captures=captures,synced_at=now.isoformat()) if captures else deepcopy(view)
                from .racer_beforeinfo import project_beforeinfo
                for row in updated['records']:
                    if row.get('sport')=='boat':
                        live=project_beforeinfo(row,state,now=now)
                        if live is not None:row['live_boat_observation']=live
                need(F.originals_sha(updated)==F.originals_sha(view),'RESULT_FEED_ORIGINAL_CHANGED')
                before={r['race_id']:wire(r) for r in view['records']}
                count=sum(before.get(r['race_id'])!=wire(r) for r in updated['records'])
                if count:
                    F.publish_view(self.git,self.bootstrap,updated,parent=parent,previous=previous,generation=generation);view=updated;changed+=count
            rows.extend(r for r in view['records'] if r['event_date_jst'] in self.days)
        self.rows=[r for r in rows if r.get('sport')=='boat']
        return status(now=now,rows=self.rows,changed=changed)
