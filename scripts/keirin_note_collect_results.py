"""Follow published historical links and retain separate research-result deltas.

No forecasts are generated and neither owner private key is needed. A matched
Kdreams/netkeirin pair remains secondary research, never official settlement.
"""
from collections import Counter, deque
from datetime import date, datetime, timezone
from hashlib import sha256
import re
import time

from race_ai.keirin_note_feed import checked_result_checks, result_clock
from race_ai.keirin_note_view import canonical, _private_root
from race_ai import keirin_secondary_result_consensus as consensus
from scripts import keirin_capture_public_two_sources as capture
from scripts import keirin_note_collect_inputs as inputs
from scripts import keirin_secondary_result_poll as poll

SCHEMA='RACE_AI_KEIRIN_NOTE_RESEARCH_RESULTS_V1'
REPORT='RACE_AI_KEIRIN_NOTE_RESULT_COLLECTION_V1'
MATCHED='SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL'
FIELDS={'schema','race_id','state','winning_triple','payout_per_100yen','provider_receipts',
    'official_primary_result_authenticated','actual_organizer_cutoff_authenticated',
    'qualifies_for_formal_settlement'}
STATES={MATCHED,'HOLD_SECONDARY_RESULT_DISAGREEMENT','HOLD_NO_PUBLISHED_CUTOFF_HINT',
    'HOLD_PROVIDER_DENIED_OR_RATE_LIMITED_STOP','HOLD_RESULT_SOURCE_UNAVAILABLE',
    'HOLD_RESULT_SOURCE_UNVERIFIED','HOLD_RESULT_DAY_MISMATCH','HOLD_RESULT_RACE_MISMATCH',
    'HOLD_SPECIAL_REFUND_OR_TIE_REQUIRES_OFFICIAL','HOLD_CONFLICTING_SOURCE_RESULT',
    'PENDING_RESULT_NOT_PUBLISHED','PENDING_RESULT_NOT_FINAL'}


class BudgetExhausted(ValueError):pass


def fact_digest(observation):
    """Stable semantic SHA; changing ad bytes or capture clocks is not a revision."""
    facts={k:observation[k] for k in FIELDS}
    facts['provider_receipts']=sorted((dict(provider=r['provider'],source_url=r['source_url'])
        for r in observation['provider_receipts']),key=lambda r:(r['provider'],r['source_url']))
    return sha256(canonical(facts)).hexdigest()


def checked_observation(row):
    fields=FIELDS|{'captured_at','observation_sha256','previous_observation_sha256'}
    inputs.need(type(row) is dict and set(row)==fields and row['schema']==consensus.SCHEMA and
        type(row['state']) is str and row['state'] in STATES,'RESULT_OBSERVATION_FIELDS')
    inputs.need(type(row['race_id']) is str and consensus.RID.fullmatch(row['race_id']),
        'RESULT_OBSERVATION_RACE')
    captured=result_clock(row['captured_at'])
    inputs.need(all(row[k] is False for k in ('official_primary_result_authenticated',
        'actual_organizer_cutoff_authenticated','qualifies_for_formal_settlement')),'RESULT_SCOPE')
    receipts=row['provider_receipts']
    inputs.need(type(receipts) is list and len(receipts)<=2,'RESULT_RECEIPTS')
    providers=set()
    for receipt in receipts:
        inputs.need(type(receipt) is dict and set(receipt)=={
            'provider','source_bytes_sha256','observed_at','source_url'},'RESULT_RECEIPT_FIELDS')
        provider=receipt['provider']
        inputs.need(type(provider) is str and provider not in providers and
            type(receipt['source_bytes_sha256']) is str and
            re.fullmatch('[a-f0-9]{64}',receipt['source_bytes_sha256']) and
            result_clock(receipt['observed_at'])<=captured,'RESULT_RECEIPT_BINDING')
        consensus.check_race_url(provider=provider,url=receipt['source_url'],race_id=row['race_id'])
        providers.add(provider)
    if row['state']==MATCHED:
        triple=row['winning_triple'];payout=row['payout_per_100yen']
        inputs.need(providers=={'Kdreams','netkeirin'} and type(triple) is list and len(triple)==3 and
            all(type(n) is int and 1<=n<=9 for n in triple) and len(set(triple))==3 and
            type(payout) is int and 100<=payout<=10**9,'RESULT_MATCHED_FACTS')
    else:
        inputs.need(row['winning_triple'] is None and row['payout_per_100yen'] is None,'RESULT_HOLD_VALUES')
    prior=row['previous_observation_sha256']
    inputs.need(prior is None or type(prior) is str and re.fullmatch('[a-f0-9]{64}',prior),
        'RESULT_PREDECESSOR_SHA')
    inputs.need(row['observation_sha256']==fact_digest(row) and prior!=row['observation_sha256'],
        'RESULT_FACT_SHA')
    return row


def _status(observation):
    return 'MATCHED' if observation['state']==MATCHED else (
        'PENDING' if observation['state'].startswith('PENDING_') else 'HOLD')


def _held(rid,state,receipts=()):
    return dict(schema=consensus.SCHEMA,race_id=rid,state=state,
        winning_triple=None,payout_per_100yen=None,provider_receipts=list(receipts),
        official_primary_result_authenticated=False,actual_organizer_cutoff_authenticated=False,
        qualifies_for_formal_settlement=False)


def _error_state(reason):
    return {'TRIFECTA_RESULT_NOT_PUBLISHED':'PENDING_RESULT_NOT_PUBLISHED',
        'SOURCE_HTML_NOT_FINAL_RESULT_PAGE':'PENDING_RESULT_NOT_FINAL',
        'SOURCE_HTML_WRONG_OR_UNKNOWN_DAY':'HOLD_RESULT_DAY_MISMATCH',
        'SOURCE_HTML_RACE_NUMBER_MISSING':'HOLD_RESULT_RACE_MISMATCH',
        'SPECIAL_REFUND_OR_TIE_REQUIRES_OFFICIAL':'HOLD_SPECIAL_REFUND_OR_TIE_REQUIRES_OFFICIAL',
        'MULTIPLE_CONFLICTING_TRIFECTA_VALUES':'HOLD_CONFLICTING_SOURCE_RESULT',
        inputs.DENIED:'HOLD_PROVIDER_DENIED_OR_RATE_LIMITED_STOP',
        'PUBLIC_PROVIDER_HTTP_ERROR_STOP':'HOLD_RESULT_SOURCE_UNAVAILABLE',
        'PUBLIC_PROVIDER_UNAVAILABLE_STOP':'HOLD_RESULT_SOURCE_UNAVAILABLE'}.get(reason,'HOLD_RESULT_SOURCE_UNVERIFIED')


class ResultSession(inputs._Session):
    def __init__(self,*args,monotonic,budget_seconds,**kwargs):
        super().__init__(*args,**kwargs)
        self.monotonic=monotonic;self.deadline=monotonic()+budget_seconds
        self.budget_exhausted=False

    def __call__(self,url):
        if self.monotonic()>=self.deadline:
            self.budget_exhausted=True;raise BudgetExhausted('NOTE_RESULT_BUDGET_EXHAUSTED')
        return super().__call__(url)


def meeting_manifests(session,day,*,tick,day_count):
    """Yield one published meeting before requesting the next one."""
    parsed=date.fromisoformat(day)
    calendar=inputs.links.CALENDAR.format(year=parsed.year,month=parsed.month,day=parsed.day)
    cards=inputs.links.linked_racecards(session(calendar),base_url=calendar,day=day)
    inputs.need(cards,'NO_PUBLISHED_MEETING_LINKS')
    ordered=sorted(cards.items());offset=(tick//day_count)%len(ordered)
    # Increment this offset once per full day rotation, so an N-day/M-meeting
    # combination cannot repeatedly visit only one arithmetic subset.
    for venue,url in ordered[offset:]+ordered[:offset]:
        if session.stopped or session.budget_exhausted:break
        raw=session(url)
        details=inputs.links.linked_details(raw,base_url=url,day=day,venue=venue)
        hints=inputs.links.linked_cutoff_hints(raw,base_url=url,day=day,venue=venue)
        rows=[]
        for race_id,kdreams_url in sorted(details.items()):
            net='https://keirin.netkeiba.com/race/entry/?race_id='+race_id
            capture._allow_url(net,'net',race_id);capture._allow_url(kdreams_url,'kd',race_id)
            rows.append(dict(race_id=race_id,netkeirin_url=net,kdreams_url=kdreams_url,
                cutoff_hint=hints.get(race_id)))
        manifest=dict(schema=capture.SCHEMA,day_jst=day,races=rows,
            source_use_scope='OWNER_PERSONAL_RESEARCH_ONLY')
        capture.manifest_check(manifest,registered_ids=[row['race_id'] for row in rows])
        yield manifest


def collect_results(*,days,private_root,result_checks=None,fetch=None,clock=None,
                    monotonic=None,budget_seconds=120):
    """Return private delta handles and opaque progress; no total race/date cap."""
    inputs.need(type(days) in (tuple,list,set) and days and all(type(d) is str and
        date.fromisoformat(d).isoformat()==d for d in days),'RESULT_DAYS')
    inputs.need(type(budget_seconds) in (int,float) and 0<budget_seconds<=240,'RESULT_BUDGET')
    checks=checked_result_checks(result_checks or {})
    clock=clock or (lambda:datetime.now(timezone.utc));now=inputs._now(clock)
    inputs.need(all(result_clock(row['checked_at'])<=now for row in checks.values()),'RESULT_CHECK_IN_FUTURE')
    today=now.astimezone(inputs.JST).date().isoformat()
    inputs.need(all(d<=today for d in days),'RESULT_FUTURE_DAY')
    root=_private_root(private_root)
    for name in ('raw','receipts','data'):(root/name).mkdir(mode=0o700,exist_ok=True)
    session=ResultSession(root,today,fetch or capture.fetch_once,clock,
        monotonic=monotonic or time.monotonic,budget_seconds=budget_seconds)
    counts=Counter();states=Counter();updates={};changed={}
    tick=int(now.timestamp())//600
    historical_days=sorted(set(days)-{today})
    if historical_days:
        # Keep the existing round robin for dates before today's JST card.
        offset=tick%len(historical_days)
        historical_days=historical_days[offset:]+historical_days[:offset]

    def consume(day,manifest):
        counts['observed_races']+=len(manifest['races']);candidates=[]
        for row in manifest['races']:
            rid=row['race_id'];old=checks.get(rid)
            if old and (now-result_clock(old['checked_at'])).total_seconds()<(
                    3600 if old['status']=='MATCHED' else 600):
                counts['not_due_races']+=1;continue
            hint=row['cutoff_hint']
            if day==today and hint is not None and inputs.model.when(hint)>=now:
                counts['future_races']+=1;continue
            candidates.append((old['checked_at'] if old else '',row))
        # Poll this meeting's oldest checks before discovering another one.
        # Hints order ties; they never certify an organizer's cutoff.
        for _,row in sorted(candidates,key=lambda item:(
                result_clock(item[0]) if item[0] else datetime.min.replace(tzinfo=timezone.utc),
                inputs.model.when(item[1]['cutoff_hint']) if item[1]['cutoff_hint'] else
                    datetime.max.replace(tzinfo=timezone.utc),item[1]['race_id'])):
            if session.stopped or session.budget_exhausted:break
            rid=row['race_id'];old=checks.get(rid)
            if day==today and row['cutoff_hint'] is None:
                counts['unknown_cutoff_races']+=1
                observed=_held(rid,'HOLD_NO_PUBLISHED_CUTOFF_HINT')
            else:
                try:
                    observed=poll.poll(manifest=manifest,race_id=rid,fetch=session,clock=clock)
                except BudgetExhausted:break
                except (ValueError,KeyError,TypeError,OSError) as error:
                    reason=inputs._safe_reason(error)
                    state=_error_state(reason)
                    kd,net=poll.verified_pair_urls(manifest,rid)
                    receipts=[]
                    for provider,url in (('Kdreams',kd),('netkeirin',net)):
                        record=session.receipts.get(url)
                        if record:receipts.append(dict(provider=provider,source_url=url,
                            source_bytes_sha256=record['bytes_sha256'],observed_at=record['captured_at']))
                    observed=_held(rid,state,receipts)
            at=inputs._now(clock).isoformat();digest=fact_digest(observed);status=_status(observed)
            counts['checked_races']+=1;counts[status.lower()+'_races']+=1;states[observed['state']]+=1
            updates[rid]=dict(checked_at=at,digest=digest,status=status)
            if old is None or old['digest']!=digest or old['status']!=status:
                observed.update(captured_at=at,observation_sha256=digest,
                    previous_observation_sha256=old['digest'] if old else None)
                checked_observation(observed)
                changed.setdefault(day,[]).append(observed)
                counts['changed_observations']+=1
    def process_meetings(scan_days, *, seek_due_first=False):
        for day in scan_days:
            if session.stopped or session.budget_exhausted:break
            discovered=False
            try:
                for manifest in meeting_manifests(session,day,tick=tick,day_count=len(scan_days)):
                    if not discovered:counts['discovered_days']+=1;discovered=True
                    checked_before=counts['checked_races']
                    consume(day,manifest)
                    if not seek_due_first or counts['checked_races']>checked_before:
                        seek_due_first=False
                        yield
                    if session.stopped or session.budget_exhausted:break
            except BudgetExhausted:break
            except (ValueError,KeyError,TypeError,OSError) as error:
                states['HOLD_'+inputs._safe_reason(error)]+=1

    # Give a meeting with due results today the first turn. Future-only and
    # recently checked meetings should not hand that turn to past dates.
    # Then alternate meetings under the same deadline and provider stop latch.
    scans=deque()
    if today in days:scans.append(process_meetings([today],seek_due_first=True))
    if historical_days:scans.append(process_meetings(historical_days))
    try:
        while scans and not session.stopped and not session.budget_exhausted:
            scan=scans.popleft()
            try:
                next(scan)
            except StopIteration:
                continue
            scans.append(scan)
    finally:
        session.finish()
    for day,observations in changed.items():
        folder=root/'data'/day;folder.mkdir(mode=0o700)
        inputs._write_snapshot(folder/'research_results.json',dict(schema=SCHEMA,day_jst=day,observations=observations))
    safe=dict(schema=REPORT,days_requested=len(set(days)),provider_denied=session.stopped==inputs.DENIED,
        budget_exhausted=session.budget_exhausted,public_page_requests=session.requests,
        national_universe_verified=False,formal_model_admission=False,actual_four_model_forecast_saved=False,
        **{key:counts[key] for key in ('discovered_days','observed_races','checked_races','matched_races',
            'hold_races','pending_races','changed_observations','not_due_races','future_races','unknown_cutoff_races')},
        states=dict(states))
    return dict(site_root=str(root),result_checks=updates,safe_report=safe)
