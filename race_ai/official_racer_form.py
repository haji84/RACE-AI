"""Offline official racer recent meet results (per-meet only, never fictitious race IDs)."""
from __future__ import annotations

from datetime import date
from .official_motor_join import (
    OfficialSourceError, _rows, _normal, _name, _DATES, _ALLOWED, _DIGIT
)


def parse_racer_recent_meets(text: str, *, racer_name: str, racer_id: str,
                             source_url: str, captured_at: str) -> list[dict]:
    if not source_url.startswith('https://') or not captured_at:
        raise OfficialSourceError('source URL/capture time required')
    if _name(racer_name) not in _name(_normal(text)):
        raise OfficialSourceError('racer name does not match submitted recent-results text')
    output=[]
    for cells in _rows(text):
        if len(cells)<4:
            continue
        d=_DATES.search(_normal(cells[0]))
        if not d:
            continue
        start=date.fromisoformat(d.group('start').replace('/','-'))
        end=date.fromisoformat(d.group('end').replace('/','-'))
        if end<start:
            raise OfficialSourceError('meet dates invalid')
        seq=_normal(cells[-1]).replace(' ','').replace('　','')
        if not seq or not _ALLOWED.fullmatch(seq):
            raise OfficialSourceError('unrecognized recent results format')
        results=[int(x) for x in _DIGIT.findall(seq)]
        if not results:
            raise OfficialSourceError('recent results contain no numeric finishes')
        output.append(dict(racer_id=racer_id,racer_name=_name(racer_name),
            start=start.isoformat(),end=end.isoformat(),venue_name=_name(cells[1]),
            event_title=_normal(cells[-2]),finish_sequence=seq,
            finish_count=len(results),top2_count=sum(r in (1,2) for r in results),
            source_url=source_url,captured_at=captured_at))
    if not output:
        raise OfficialSourceError('no completed recent-racer meet rows')
    if len({(x['start'],x['end']) for x in output})!=len(output):
        raise OfficialSourceError('duplicate recent meet rows')
    return sorted(output,key=lambda r:r['start'],reverse=True)


def attach_prior_player_form(audit:dict, recent_meets:list[dict]) -> dict:
    """Use only complete *earlier* meets; source snapshots still retrospective."""
    if audit.get('previous') is None or not audit.get('profile'):
        raise OfficialSourceError('must join a verified racer profile first')
    p=audit['profile']
    motor_start=audit['previous']['start']
    if any(r['racer_id']!=p['racer_id'] or r['racer_name']!=p['racer_name'] for r in recent_meets):
        raise OfficialSourceError('racer profile ID/name mismatch in recent results')
    older=[x for x in recent_meets if x['end']<motor_start]
    race_n=sum(r['finish_count'] for r in older)
    top2=sum(r['top2_count'] for r in older)
    result=dict(audit)
    result['preceding_player_form']={
       'meet_count':len(older),'finish_count':race_n,'top2_count':top2,
       'historical_top2_rate':round(top2/race_n,6) if race_n else None,
       'meets':older,'predictive_use_confirmed':False,
       'interpretation':'Raw prior finishing record; not a calibrated counterfactual motor-blind prediction.'
    }
    return result
