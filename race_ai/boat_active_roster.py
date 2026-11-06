"""Identity checks and ranking for a confirmed BOAT entrant roster.

The source adapter establishes which entrants withdrew. These pure model
helpers never infer withdrawals from absent exhibition or feature values.
"""
import itertools
import math
import re

from .legacy_boat_rank import plackett_luce


def active_roster(rows, *, identity_key, error_type=ValueError):
    """Return sorted physical lanes after checking 3..6 distinct identities."""
    if type(rows) is not list or not 3 <= len(rows) <= 6:
        raise error_type('three to six confirmed active entrants required')
    lanes, registrations = set(), set()
    for row in rows:
        if type(row) is not dict:
            raise error_type('entrant identity row required')
        lane, registration = row.get('lane'), row.get(identity_key)
        if type(lane) is not int or not 1 <= lane <= 6 or lane in lanes:
            raise error_type('entrants must be unique lanes 1..6')
        if (type(registration) is not str or not re.fullmatch(r'[0-9]{4}', registration)
                or registration in registrations):
            raise error_type('unique four-digit racer identity required')
        lanes.add(lane)
        registrations.add(registration)
    return tuple(sorted(lanes))


def rank_active(strengths_by_lane):
    """Use the unchanged legacy kernel for six; enumerate active triples otherwise."""
    if type(strengths_by_lane) is not dict:
        raise ValueError('physical lane strengths required')
    if (not 3 <= len(strengths_by_lane) <= 6 or any(type(lane) is not int or not 1 <= lane <= 6
                                                 for lane in strengths_by_lane)):
        raise ValueError('three to six physical lane strengths required')
    lanes = tuple(sorted(strengths_by_lane))
    if len(lanes) == 6:
        return plackett_luce(strengths_by_lane)
    if any(type(value) not in (int, float) or not math.isfinite(value) or not 1e-9 <= value <= 1e9
           for value in strengths_by_lane.values()):
        raise ValueError('invalid finite strength')
    triples = []
    for order in itertools.permutations(lanes, 3):
        remaining, probability = list(lanes), 1.0
        for lane in order:
            probability *= strengths_by_lane[lane] / math.fsum(strengths_by_lane[x] for x in remaining)
            remaining.remove(lane)
        triples.append(dict(combination=list(order), probability=probability))
    mass = math.fsum(row['probability'] for row in triples)
    for row in triples:
        row['probability'] /= mass
    return dict(triples=triples)


def _identity_rows(rows, race_id, *, missing_registration=False):
    if type(rows) is not list or len(rows)>6:
        raise ValueError('bounded saved participant identities required')
    result = {}
    for row in rows:
        if type(row) is not dict or ('race_id' in row and row['race_id'] != race_id):
            raise ValueError('saved participant race identity mismatch')
        numbers = [row[key] for key in ('lane','number') if key in row]
        identities = [row[key] for key in ('registration_no','racer_registration_id','registration_number','participant_id','racer_id') if key in row]
        if (not numbers or any(type(n) is not int or not 1<=n<=6 or n!=numbers[0] for n in numbers)
                or numbers[0] in result or not identities or any(value!=identities[0] for value in identities)):
            raise ValueError('saved participant lane identity mismatch')
        registration = identities[0]
        if not (registration is None and missing_registration or type(registration) is str
                and re.fullmatch(r'[0-9]{4}',registration)):
            raise ValueError('saved participant registration identity mismatch')
        if registration is not None and registration in result.values():
            raise ValueError('saved participant registration lane conflict')
        result[numbers[0]] = registration
    return result


def result_roster_bindings(forecast, *, race_id):
    """Return active identities, saved identity proofs and declared withdrawals.

    An unknown withdrawn registration can remain display metadata, but cannot
    authorize an extra result identity. All supplied physical bindings agree.
    """
    if type(forecast) is not dict or forecast.get('race_id',race_id)!=race_id:
        raise ValueError('saved roster race identity mismatch')
    roster = forecast.get('roster')
    if roster is not None:
        if type(roster) is not dict or any(type(n) is not str or not re.fullmatch(r'[1-6]',n) for n in roster):
            raise ValueError('saved physical roster required')
        active = _identity_rows([dict(lane=int(n),registration_no=pid) for n,pid in roster.items()],race_id)
    else:
        active = _identity_rows(forecast.get('participants',[]),race_id)
    if not 3<=len(active)<=6 or any(pid is None for pid in active.values()):
        raise ValueError('three to six saved active identities required')
    known = dict(active)
    withdrawn = forecast.get('withdrawn_lanes',[])
    if type(withdrawn) is not list or any(type(n) is not int or not 1<=n<=6 for n in withdrawn) or len(set(withdrawn))!=len(withdrawn):
        raise ValueError('saved withdrawn lanes invalid')
    withdrawn = set(withdrawn)
    def bind(rows):
        for lane,registration in rows.items():
            if registration is None:
                continue
            if ((lane in known and known[lane]!=registration)
                    or registration in known.values() and known.get(lane)!=registration):
                raise ValueError('saved same-race registration binding conflict')
            known[lane] = registration
    absent_people = _identity_rows(forecast.get('withdrawn_participants',[]),race_id,missing_registration=True)
    withdrawn.update(absent_people)
    bind(absent_people)
    snapshots = forecast.get('saved_participant_rosters',[])
    if type(snapshots) is not list or len(snapshots)>1000:
        raise ValueError('saved roster snapshots invalid')
    for snapshot in snapshots:
        if type(snapshot) is not dict or snapshot.get('race_id',race_id)!=race_id:
            raise ValueError('saved roster snapshot race mismatch')
        people = snapshot.get('participants')
        proof = _identity_rows(people,race_id,missing_registration=True)
        if not 3<=len(proof)<=6:
            raise ValueError('saved roster snapshot incomplete')
        bind(proof)
        withdrawn.update(row.get('number',row.get('lane')) for row in people
                         if row.get('active') is False or row.get('withdrawn') is True or row.get('entry_status')=='withdrawn')
    if withdrawn.intersection(active) or len(known)>6:
        raise ValueError('active and withdrawn roster conflict')
    return active,known,withdrawn


def match_result_roster(forecast, results, *, race_id):
    """Return active official rows; extra absences need an exact saved identity."""
    active,known,withdrawn = result_roster_bindings(forecast,race_id=race_id)
    observed = _identity_rows(results,race_id)
    if not 3<=len(observed)<=6 or not set(active)<=set(observed):
        raise ValueError('official result missing saved active entrants')
    if any(observed[lane]!=pid for lane,pid in active.items()):
        raise ValueError('official/saved racer identity mismatch')
    for row in results:
        lane = row.get('lane',row.get('number'))
        if row.get('verified_official',True) is not True:
            raise ValueError('official result row identity unverified')
        if lane not in active:
            if (known.get(lane)!=observed[lane] or row.get('finish_status') not in ('ABSENT','WITHDRAWN','RETURNED','欠')
                    or row.get('finish') is not None):
                raise ValueError('extra official result lacks saved withdrawal identity')
    return [row for row in results if row.get('lane',row.get('number')) in active]
