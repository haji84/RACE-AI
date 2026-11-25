"""Registered-rider tactical dossier summaries from observed race episodes."""
from collections import Counter, defaultdict
import re

from .keirin_nationwide_auto_generator import VENUE, when
from .keirin_small_ticket_budget import wilson_lower

ABILITIES = {
    'resist_makuri': 'Observed response while an opposing line was trying to pass.',
    'follower_acceleration': 'Observed second-wheel response after the line leader faded.',
    'side_by_side_sustain': 'Observed side-by-side effort with calibrated speed when available.',
    'tactical_switch': 'Observed opportunity to change from following to an independent attack.',
    'late_kick_after_effort': 'Observed late response following a documented earlier effort.',
    'inside_outside': 'Observed position in a side-by-side contest with independently verified finish where available.',
}
SOURCES = {'video', 'official_report', 'attributed_article'}


def _registration(value):
    return type(value) is str and re.fullmatch(r'[0-9]{6}', value) is not None


def _race(value):
    return type(value) is str and VENUE.fullmatch(value) is not None


def _episode(row):
    ability = row['ability']
    if (ability not in ABILITIES or type(row['event_id']) is not str or
            not row['event_id'] or len(row['event_id']) > 100):
        raise ValueError('A tactical episode requires a supported ability and stable event identifier.')
    if ability == 'inside_outside':
        side, finish = row['side'], row['finish']
        if side not in {'inside','outside'} or (finish is not None and
                (type(finish) is not int or not 1 <= finish <= 9)):
            raise ValueError('An inside/outside observation needs a documented side and an optional numeric finish.')
        return side, finish
    outcome = row['outcome']
    if outcome not in {'success', 'failure', 'unknown'}:
        raise ValueError('An episode outcome is success, failure or unknown.')
    measurement = row.get('measurement')
    if (measurement not in (None, 'relative_position', 'calibrated_speed') or
            ability == 'side_by_side_sustain' and measurement is None):
        raise ValueError('An observation needs a valid kind of measurement for its scope.')
    return outcome, measurement


def _sample(counts, successes, known):
    total = counts['observed_opportunities']
    unknown = total-known
    state = 'observed' if known else 'outcomes_unavailable' if total else 'unobserved'
    counts.update(known_outcomes=known, unknown_outcomes=unknown)
    return dict(counts, state=state, observed_successes=successes,
                observed_success_rate=successes/known if known else None,
                wilson_95_interval=[max(0.0, wilson_lower(successes,known)),
                    min(1.0, 1-wilson_lower(known-successes,known))] if known else None,
                success_rate_bounds_for_all_observed=[successes/total,(successes+unknown)/total] if total else None)


def profile_episodes(episodes, *, registration, as_of, target_race_id, verify):
    """Describe available, verified opportunities without estimating unobserved abilities.

    The caller verifies the registration-to-starter binding, the source and the
    opportunity semantics defined by ``ABILITIES``. For side-specific finishes
    the verification includes the independently confirmed result. Each side's
    finish distribution counts an observed race once. A rider who occupied
    both sides in separate contests appears once in each distribution. Episode ids
    identify the same opportunity across source revisions. A verified capture
    establishes when material was available even if no publication time was reported.
    """
    if not _registration(registration) or not _race(target_race_id) or not callable(verify):
        raise ValueError('A tactical dossier needs a registered rider, a target race and an evidence verifier.')
    cutoff = when(as_of)
    available = defaultdict(set)
    dated_publications = set()
    excluded = Counter()
    for row in episodes:
        if row.get('registration') != registration:
            continue
        rid = row['race_id']
        if not _race(rid):
            raise ValueError('A tactical observation needs a race identifier.')
        if rid == target_race_id:
            excluded['target_race'] += 1
            continue
        observed = when(row['observed_at'])
        published = when(row['published_at']) if row['published_at'] is not None else None
        if observed >= cutoff or published is not None and published > observed:
            excluded['not_available_before_cutoff'] += 1
            continue
        if row.get('source') not in SOURCES or verify(row) is not True:
            excluded['source_unverified'] += 1
            continue
        value = _episode(row)
        key = row['ability'], rid, row['event_id']
        available[key].add(value)
        if published is not None:
            dated_publications.add(key)

    counts = {ability: Counter(observed_opportunities=0, conflicts=0) for ability in ABILITIES}
    side_counts = {side: Counter(observed_opportunities=0, conflicts=0) for side in ('inside','outside')}
    finishes = defaultdict(Counter)
    side_races = defaultdict(set)
    race_finishes = defaultdict(set)
    for (ability, race_id, _), values in available.items():
        counts[ability]['observed_opportunities'] += 1
        if ability == 'inside_outside':
            outcomes = {finish for _, finish in values if finish is not None}
            race_finishes[race_id].update(outcomes)
            sides = {side for side, _ in values}
            if len(sides) != 1:
                counts[ability]['conflicts'] += 1
                continue
            side, = sides
            side_counts[side]['observed_opportunities'] += 1
            side_races[side].add(race_id)
            if len(outcomes)>1:
                side_counts[side]['conflicts'] += 1
                counts[ability]['conflicts'] += 1
            elif outcomes:
                finish, = outcomes
                finishes[side][finish] += 1
            continue
        count = counts[ability]
        if ability == 'side_by_side_sustain':
            values = {(outcome, kind) for outcome, kind in values if kind == 'calibrated_speed'}
            if not values:
                count['relative_position_only'] += 1
        outcomes = {outcome for outcome,_ in values if outcome != 'unknown'}
        if len(outcomes) > 1:
            count['conflicts'] += 1
        elif outcomes:
            outcome, = outcomes
            count[outcome] += 1

    abilities = {}
    for ability, group in counts.items():
        if ability == 'inside_outside':
            sides = {}
            for side, sample in side_counts.items():
                numbers = finishes[side]
                known = sum(numbers.values())
                ranks = [race_finishes[race_id] for race_id in side_races[side]]
                race_counts = Counter(next(iter(rank)) for rank in ranks if len(rank) == 1)
                known_races = sum(race_counts.values())
                sides[side] = dict(sample, known_finishes=known,
                                   unknown_finishes=sample['observed_opportunities']-known,
                                   finish_counts={str(rank):count for rank,count in sorted(numbers.items())},
                                   observed_win_rate=numbers[1]/known if known else None,
                                   observed_races=len(ranks), races_with_confirmed_finish=known_races,
                                   races_with_unresolved_finish=len(ranks)-known_races,
                                   races_with_conflicting_finish=sum(len(rank) > 1 for rank in ranks),
                                   race_finish_counts={str(rank): count for rank, count in sorted(race_counts.items())},
                                   observed_race_win_rate=race_counts[1]/known_races if known_races else None)
            abilities[ability] = dict(group, sides=sides)
        else:
            abilities[ability] = _sample(group, group['success'], group['success']+group['failure'])
    return {'registration':registration, 'as_of':as_of, 'target_race_id':target_race_id,
            'abilities':abilities, 'excluded':dict(excluded),
            'publication_times_unreported':len(available.keys() - dated_publications),
            'coverage_scope':'source-verified observed opportunities', 'predictive_rating':None}
