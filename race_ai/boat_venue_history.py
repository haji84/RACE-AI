"""Streaming official history -> all racers x 24 venues, explicitly incomplete.

Research observations only. No point-rating substitution for official local
win rates, grade inference, age bonus, missing=zero, or model training.
"""
from collections import Counter
from datetime import date,datetime,timedelta,timezone
import hashlib
import math

from .actions_contract import stamp,digest
from .teiai_history import need,racer_number,VENUES
from .teiai_official_reconciliation import official_day
from .official_lzh_extract import extract_daily_lzh
from .boat_racer_tendencies import METHODS
from .official_archive_probe import official_url

NAMES={code:name for name,code in VENUES.items()}
JST=timezone(timedelta(hours=9))


def _bucket():
    return dict(n=0,finishes=[0]*6,dispositions=Counter(),st_n=0,st_sum=0,st_sum2=0,
                unknown_course_n=0,inward_n=0,outward_n=0,
                wins_by_method=Counter(),in1_loss_winner_method_proxy=Counter(),
                unknown_winner_method_n=0,special_result_n=0)


def _update(b,row,*,special):
    b['n']+=1;finish=row['finish'];course=row['course'];method=row.get('winner_method')
    if finish in range(1,7):b['finishes'][finish-1]+=1
    else:b['dispositions'][row.get('result_code') or 'UNKNOWN']+=1
    if row['st_status']=='OK' and row['st'] is not None:
        value=int(round(row['st']*100));b['st_n']+=1;b['st_sum']+=value;b['st_sum2']+=value*value
    if course is None:b['unknown_course_n']+=1
    else:
        b['inward_n']+=course<row['lane'];b['outward_n']+=course>row['lane']
    b['special_result_n']+=special
    if finish==1:
        if method in METHODS:b['wins_by_method'][method]+=1
        else:b['unknown_winner_method_n']+=1
    if course==1 and type(finish) is int and finish>1 and not special:
        if method in METHODS:b['in1_loss_winner_method_proxy'][method]+=1
        else:b['unknown_winner_method_n']+=1


def _stats(b):
    f=b['finishes'];n=sum(f);sn=b['st_n']
    variance=(sn*b['st_sum2']-b['st_sum']**2)/(sn*sn*10000) if sn else None
    return dict(opportunities=b['n'],numeric_finish_n=n,abnormal_or_missing_n=b['n']-n,
        finish_counts=f.copy(),wins=f[0],top2=sum(f[:2]),top3=sum(f[:3]),
        win_rate_numeric=f[0]/n if n else None,top2_rate_numeric=sum(f[:2])/n if n else None,
        top3_rate_numeric=sum(f[:3])/n if n else None,dispositions=dict(b['dispositions']),
        st_n=sn,mean_st=b['st_sum']/(sn*100) if sn else None,
        st_std_population=math.sqrt(max(0,variance)) if sn else None,
        unknown_course_n=b['unknown_course_n'],entered_inward_observed=b['inward_n'],
        displaced_outward_observed=b['outward_n'],wins_by_method=dict(b['wins_by_method']),
        in1_loss_race_winner_method_proxy=dict(b['in1_loss_winner_method_proxy']),
        unknown_winner_method_n=b['unknown_winner_method_n'],special_result_n=b['special_result_n'],
        denominator_definition='numeric_finish_only_v1; ST_OK_only_population_std; all_opportunities_separately_counted',
        causal_or_intent_claim=False)


class VenueHistory:
    def __init__(self,*,start,end,roster=(),clock=None):
        self.start=date.fromisoformat(start);self.end=date.fromisoformat(end)
        need(self.start<=self.end,'VENUE_PERIOD_INVALID')
        self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.opened_at=self.clock();self.available_at=self.opened_at
        self.roster={racer_number(p) for p in roster};self.ids=set(self.roster)
        self.sources={};self.buckets={};self.races=Counter();self.starts=Counter();self._coverage_cache=None

    def add_archive(self,raw,*,day,captured_at):
        d=date.fromisoformat(day);need(day==d.isoformat(),'VENUE_DAY_NOT_CANONICAL');captured=stamp(captured_at)
        need(captured<=self.clock(),'VENUE_CAPTURE_FROM_FUTURE')
        need(self.start<=d<=self.end and d<=captured.astimezone(JST).date(),'VENUE_SOURCE_DAY_INVALID')
        sha=hashlib.sha256(raw).hexdigest()
        if day in self.sources:
            need(self.sources[day]['source_sha256']==sha,'VENUE_REVISED_DAY_REBUILD_REQUIRED');return
        parsed=official_day(extract_daily_lzh(raw,f'K{d:%y%m%d}.TXT'),day=day)
        need(not parsed['unpublished_venues'],'VENUE_DAY_NOT_FULLY_PUBLISHED')
        # A whole date is admitted atomically only after the existing strict
        # national parser accepted every recorded race. Unsupported files remain
        # catalog gaps; not silently filtered races in a complete-date claim.
        rows=parsed['rows'];seen=set();finishes={};special=set()
        for r in rows:
            key=(r['race_id'],r['lane']);need(key not in seen,'VENUE_DUPLICATE_RACE_ENTRY');seen.add(key)
            if type(r['finish']) is int:
                key=(r['race_id'],r['finish']);finishes[key]=finishes.get(key,0)+1
        special={rid for (rid,_),n in finishes.items() if n>1}
        for r in rows:
            pid=racer_number(r['racer_id']);v=r['race_id'][9:11];need(v in NAMES,'VENUE_CODE_INVALID')
            self.ids.add(pid)
            for course in (0,r['course']):
                if course is None:continue
                key=(pid,v,course);b=self.buckets.setdefault(key,_bucket());_update(b,r,special=r['race_id'] in special)
            self.starts[v]+=1
        for rid in {r['race_id'] for r in rows}:self.races[rid[9:11]]+=1
        self.sources[day]=dict(source_url=official_url(d,'K'),source_sha256=sha,captured_at=captured_at,
                               parsed_starts=len(rows),parsed_races=len({r['race_id'] for r in rows}))
        self.available_at=max(self.available_at,self.clock(),captured);self._coverage_cache=None

    def _coverage(self,as_of):
        need(stamp(as_of)>=self.available_at,'VENUE_CAPTURE_OR_IMPORT_AFTER_AS_OF')
        if self._coverage_cache is None:
            expected=(self.end-self.start).days+1;processed=len(self.sources)
            self._coverage_cache=dict(requested_start=self.start.isoformat(),requested_end=self.end.isoformat(),
                    requested_calendar_days=expected,fully_parsed_days=processed,
                    unavailable_or_unprocessed_days=expected-processed,
                    source_window_complete=processed==expected,source_set_sha256=digest(self.sources))
        return self._coverage_cache.copy()

    def profile(self,racer_id,venue_code,*,as_of):
        racer_number(racer_id);need(venue_code in NAMES and racer_id in self.ids,'VENUE_PROFILE_IDENTITY_INVALID')
        coverage=self._coverage(as_of);b=self.buckets.get((racer_id,venue_code,0),_bucket())
        observed=b['n']>0;complete=coverage['source_window_complete']
        state=('COMPLETE_OBSERVED' if observed else 'COMPLETE_NO_OBSERVATIONS') if complete else ('PARTIAL_OBSERVED' if observed else 'INCOMPLETE_NO_OBSERVATIONS')
        return dict(racer_id=racer_id,venue_code=venue_code,venue_name=NAMES[venue_code],
                    as_of=as_of,coverage_status=state,history_completeness=complete,coverage=coverage,
                    stats=_stats(b),by_actual_course={str(c):_stats(self.buckets.get((racer_id,venue_code,c),_bucket())) for c in range(1,7)},
                    official_local_win_rate=None,official_local_top2_rate=None,official_local_top3_rate=None,
                    missing={'official_local_win_rate':'NOT_PROVIDED_BY_K','grade':'NOT_PROVIDED_BY_K',
                             'motor_cycle':'NOT_PROVIDED','true_last_10_30':'GAPS_OR_NOT_RECONSTRUCTED'},
                    formal_backtest_eligible=False,source_authenticity_attested=False,
                    description='Observed venue sample; absent observations are not proven no-start without complete source coverage.')

    def profiles(self,*,as_of):
        self._coverage(as_of)
        for pid in sorted(self.ids):
            for venue in sorted(NAMES):yield self.profile(pid,venue,as_of=as_of)

    def summary(self,*,as_of):
        coverage=self._coverage(as_of)
        return dict(schema='RACE_AI_BOAT_VENUE_HISTORY_COVERAGE_V1',coverage=coverage,
                    roster_racers=len(self.roster),known_racers=len(self.ids),grid_cells=len(self.ids)*24,
                    observed_racer_venue_pairs=sum(c==0 for _,_,c in self.buckets),
                    observed_starts=sum(self.starts.values()),observed_races=sum(self.races.values()),
                    venues_with_observations=len(self.starts),all_venue_player_history_complete=coverage['source_window_complete'],
                    venue_counts=[dict(venue_code=v,venue_name=NAMES[v],races=self.races[v],starts=self.starts[v],
                        racers=sum(code==v and course==0 for _,code,course in self.buckets)) for v in sorted(NAMES)],
                    formal_backtest_eligible=False,private_individual_records_published=False)
