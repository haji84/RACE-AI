"""All-retained-history reconciliation index, stored inside the existing encrypted Git packet.

There is no age-based eviction. The saved V5 day view remains the authoritative
per-race record; this compact index tracks outstanding IDs and scanned days.
It does not issue HTTP requests, create predictions, or make results final.
"""
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
import re

JST = timezone(timedelta(hours=9))
SCHEMA = 'RACE_AI_RESULT_DUE_LEDGER_V2'
DAY = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}\Z')
RACE_ID = re.compile(r'([0-9]{8})-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])\Z')
MASKS = {'missing':'m','pending':'p','unsupported':'u'}
RACE_SLOTS = 24 * 12


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def _day(value):
    need(type(value) is str and DAY.fullmatch(value),'RESULT_DUE_DAY_INVALID')
    try:
        need(date.fromisoformat(value).isoformat()==value,'RESULT_DUE_DAY_INVALID')
    except ValueError:
        raise ValueError('RESULT_DUE_DAY_INVALID') from None
    return value


def _clock(value):
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    except (ValueError, TypeError, AttributeError):
        raise ValueError('RESULT_DUE_CLOCK_INVALID') from None
    need(parsed.utcoffset() is not None, 'RESULT_DUE_CLOCK_INVALID')
    return parsed


def _slot(rid):
    match=RACE_ID.fullmatch(rid) if type(rid) is str else None
    need(match is not None,'RESULT_DUE_RACE_ID_INVALID')
    day=_day(match[1][:4]+'-'+match[1][4:6]+'-'+match[1][6:])
    slot=(int(match[2])-1)*12+(int(match[3])-1)
    return day,1<<slot


def _rid_day(rid):
    return _slot(rid)[0]


def _mask(value, *, length=RACE_SLOTS):
    need(type(value) is str and 1 <= len(value) <= (length+3)//4 and
         re.fullmatch('[0-9a-f]+', value), 'RESULT_DUE_MASK_INVALID')
    num=int(value,16)
    need(0 <= num < 1<<length,'RESULT_DUE_MASK_INVALID')
    return num


def _entry(day, first_seen_at):
    return dict(m='0',p='0',u='0',first_seen_at=first_seen_at)


def _validate(doc, now):
    need(type(doc) is dict and set(doc)=={'schema','pending_days','scanned_months','scan_round'}
         and doc['schema']==SCHEMA,'RESULT_DUE_SCHEMA_INVALID')
    pending,scanned,seq=doc['pending_days'],doc['scanned_months'],doc['scan_round']
    need(type(pending) is dict and type(scanned) is dict and type(seq) is int and seq>=0,
         'RESULT_DUE_SCHEMA_INVALID')
    today=now.astimezone(JST).date().isoformat()
    for day,entry in pending.items():
        _day(day)
        need(day<=today and type(entry) is dict and set(entry)=={'m','p','u','first_seen_at'},
             'RESULT_DUE_ENTRY_INVALID')
        bits=[_mask(entry[name]) for name in ('m','p','u')]
        need(any(bits) and (bits[0]&bits[1])==0 and (bits[0]&bits[2])==0 and (bits[1]&bits[2])==0,
             'RESULT_DUE_ENTRY_MASK_CONFLICT')
        need(_clock(entry['first_seen_at'])<=now,'RESULT_DUE_FIRST_SEEN_INVALID')
    for month,mask in scanned.items():
        need(type(month) is str and re.fullmatch(r'[0-9]{4}-[0-9]{2}',month),
             'RESULT_DUE_SCAN_MONTH_INVALID')
        try:
            days=monthrange(int(month[:4]),int(month[5:]))[1]
        except (ValueError,OverflowError):
            raise ValueError('RESULT_DUE_SCAN_MONTH_INVALID') from None
        need(_mask(mask,length=31)<(1<<days),'RESULT_DUE_SCAN_MASK_INVALID')
    return doc


def ledger(control, *, now):
    """Validate an authenticated, non-expiring compact per-day backlog index."""
    need(type(control) is dict,'RESULT_DUE_CONTROL_INVALID')
    at=_clock(now)
    value=control.setdefault('result_due_ledger',dict(schema=SCHEMA,pending_days={},scanned_months={},scan_round=0))
    return _validate(value,at)


def is_scanned(doc, day):
    day=_day(day)
    return bool(_mask(doc['scanned_months'].get(day[:7],'0'),length=31)&(1<<(int(day[8:])-1)))


def record_scanned(doc, day):
    """Call only after the encrypted saved-day was independently authenticated."""
    day=_day(day)
    month=day[:7]
    bits=_mask(doc['scanned_months'].get(month,'0'),length=31)
    doc['scanned_months'][month]=format(bits | (1<<(int(day[8:])-1)),'x')


def pending_count(doc):
    return sum(sum(_mask(e[k]).bit_count() for k in ('m','p','u')) for e in doc['pending_days'].values())


def count_older(doc,recent_days):
    recent={_day(x) for x in recent_days}
    return sum(sum(_mask(e[k]).bit_count() for k in ('m','p','u'))
               for day,e in doc['pending_days'].items() if day not in recent)


def choose_older_day(doc, *, all_days, recent_days):
    """Fair selection of *all* saved history, without a trailing-day cutoff.

    Each pass processes at most one old day, preserving existing source limits.
    Unknown/deleted original days remain in the private pending ledger.
    """
    days=sorted({_day(x) for x in all_days},reverse=True)
    recent={_day(x) for x in recent_days}
    need(recent <= set(days),'RESULT_DUE_RECENT_DAY_MISSING')
    older=[x for x in days if x not in recent]
    due=[x for x in older if x in doc['pending_days']]
    unscanned=[x for x in older if not is_scanned(doc,x)]
    turn=doc['scan_round']
    if due and (turn%2==0 or not unscanned):
        selected=due[(turn//2)%len(due)]
    elif unscanned:
        selected=unscanned[0]
    elif due:
        selected=due[(turn//2)%len(due)]
    else:
        selected=None
    if selected is not None:
        doc['scan_round']=turn+1
    return selected


def reconciled_status(row):
    """A reference-only display is not a verified final training/PDCA label."""
    result=row.get('result') or {}
    status=result.get('status') or 'missing'
    reference=result.get('cutoff_reconciliation') or {}
    if status in ('final','void') and (result.get('formal_eligible') is False or
        type(reference) is dict and reference.get('formal_eligible') is False):
        return 'unsupported'
    return status


def update(doc,rows,*,now):
    """Update only observed IDs. Never delete an untouched day or unverified ID."""
    at=_clock(now)
    timestamp=at.isoformat()
    today=at.astimezone(JST).date().isoformat()
    seen=set()
    for row in rows:
        rid=row['race_id']
        day,mask=_slot(rid)
        need(day<=today,'RESULT_DUE_FUTURE_RACE_INVALID')
        need(row.get('event_date_jst',day)==day,'RESULT_DUE_DAY_IDENTITY_CONFLICT')
        need(rid not in seen,'RESULT_DUE_DUPLICATE_RACE')
        seen.add(rid)
        state=reconciled_status(row)
        need(state in MASKS or state in ('final','void'),'RESULT_DUE_UNKNOWN_RESULT_STATE')
        entry=doc['pending_days'].get(day)
        if entry is None and state in ('final','void'):
            continue
        if entry is None:
            entry=doc['pending_days'].setdefault(day,_entry(day,timestamp))
        values={k:_mask(entry[k])&~mask for k in ('m','p','u')}
        if state in MASKS:
            values[MASKS[state]]|=mask
        if not any(values.values()):
            del doc['pending_days'][day]
        else:
            entry.update({k:format(v,'x') for k,v in values.items()})
    types={label:0 for label in MASKS}
    for entry in doc['pending_days'].values():
        for label,mask in MASKS.items():
            types[label]+=_mask(entry[mask]).bit_count()
    return dict(pending=sum(types.values()),pending_by_status=types,
                pending_days=len(doc['pending_days']),
                scanned_months=len(doc['scanned_months']),all_saved_dates_retained=True)


def unavailable_days(doc,all_days):
    available={_day(x) for x in all_days}
    return len(set(doc['pending_days'])-available)


def ordered_result_targets(*,fresh,bootstrap,new_stats,old,other_due,revisions,
                           max_requests,used_requests):
    """Give older overdue results one slot *inside* the existing GET budget.

    Neither the source budget nor the stop/WAIT policy is changed here.
    A continuous stream of current races cannot permanently starve older ones.
    """
    need(type(max_requests) is int and type(used_requests) is int and
         0<=used_requests<=max_requests<=12,'RESULT_DUE_SOURCE_BUDGET_INVALID')
    prioritized=list(fresh)+list(bootstrap)+list(new_stats)
    old=list(old)
    remaining=max_requests-used_requests
    # Never displace today's venue/bootstrap headers to resolve older backlog.
    # After current venue discovery, spend at most one existing slot on old due cases.
    if old and remaining and not bootstrap and (remaining>1 or not prioritized):
        before=max(0,remaining-1)
        return (prioritized[:before]+old[:1]+prioritized[before:]+old[1:]+
                list(other_due)+list(revisions))
    return prioritized+old+list(other_due)+list(revisions)
