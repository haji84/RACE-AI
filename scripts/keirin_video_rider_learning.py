"""Learn rider tendencies from reviewed video labels and score them on later JST race days.

The reviewed input is the validated annotation export, not proposed detections or
result-sheet checkpoints. The baseline and rider estimator see only earlier race
history, never the observed partner or movements from the race being predicted.

`attack` records the first visibly initiated move inside the specified window.
A selected clip describes that clip only. Full-lap or full-race windows can
measure the location of the first move and the chance of any move separately.
`follow` describes the reviewed tracking interval and its identified target.
`passed_target` denotes an observed overtake of that previously followed rider.
A confirmed negative requires coverage of the corresponding observation window.
"""

import argparse
from collections import Counter, defaultdict
from contextlib import closing, contextmanager
from datetime import date
import gzip
from itertools import groupby
import json
import math
import os
from pathlib import Path
import sqlite3
from tempfile import NamedTemporaryFile

from scripts.keirin_rider_profile_history import is_registration


FINAL_PHASES = ('H', 'HB', 'B', 'B4C', '4C', 'straight')
EARLY_PHASES = ('before_bell', 'bell', 'bell_to_H')
ATTACK_PHASES = {
    'before_bell': ('before_bell',), 'bell': ('bell',), 'bell_to_H': ('bell', 'bell_to_H', 'H'),
    'H': ('H',), 'HB': ('H', 'HB', 'B'), 'B': ('B',),
    'B4C': ('B', 'B4C', '4C'), '4C': ('4C',), 'straight': ('4C', 'straight'),
    'whole_final_lap': FINAL_PHASES, 'whole_race': (*EARLY_PHASES, *FINAL_PHASES),
}
TARGETED_FOLLOW = ('held', 'lost', 'rejoined', 'passed_target')
FOLLOW = (*TARGETED_FOLLOW, 'no_target')
FULL_WINDOWS = ('whole_final_lap', 'whole_race')
LEVELS = ('clip', 'sector', *FULL_WINDOWS)
PRIOR_STRENGTH = 4  # prior same-scope starts, as in the earlier rider/corner study


def iso_day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('An ISO race date is required.')
    return value


def valid_car(value):
    return type(value) is int and 1 <= value <= 9


def index_census(db, census):
    db.executescript('''
        CREATE TABLE races(id TEXT PRIMARY KEY, day TEXT NOT NULL) WITHOUT ROWID;
        CREATE TABLE starters(race TEXT, car INTEGER, rider TEXT,
            PRIMARY KEY(race, car), UNIQUE(race, rider)) WITHOUT ROWID;
        CREATE TABLE labels(day TEXT, race TEXT, car INTEGER, rider TEXT, task TEXT,
            scope TEXT, level TEXT, value TEXT, PRIMARY KEY(day, race, car, task, scope, level)) WITHOUT ROWID;
    ''')
    for record in census:
        day = iso_day(record['race_date'])
        race = record['race_id']
        if not isinstance(race, str) or not race:
            raise ValueError('A census race ID is required.')
        db.execute('INSERT INTO races VALUES(?, ?)', (race, day))
        starters = []
        for entrant in record['riders']:
            car, rider = entrant['car'], entrant['rider_id']
            if not valid_car(car) or (rider is not None and not is_registration(rider)):
                raise ValueError('Invalid census car or registration.')
            starters.append((race, car, rider))
        db.executemany('INSERT INTO starters VALUES(?, ?, ?)', starters)


def label_values(task, scope):
    return FOLLOW if task == 'follow' else (*ATTACK_PHASES[scope], 'no_attack')


def index_reviewed(db, reviewed):
    for row in reviewed:
        race, day, car, rider = (row[key] for key in ('race_id', 'race_date', 'car', 'rider_id'))
        task, scope, level = (row[key] for key in ('task', 'scope', 'window_level'))
        if task not in ('attack', 'follow') or scope not in ATTACK_PHASES or level not in LEVELS:
            raise ValueError('Unknown movement task or scope.')
        if (scope in FULL_WINDOWS or level in FULL_WINDOWS) and scope != level:
            raise ValueError('Whole race and lap labels require their exact full observation window.')
        if not valid_car(car) or not is_registration(rider):
            raise ValueError('A reviewed car needs a known registration.')
        binding = db.execute('''SELECT day, rider FROM races JOIN starters ON races.id = starters.race
                                WHERE races.id = ? AND car = ?''', (race, car)).fetchone()
        if binding != (day, rider):
            raise ValueError('Reviewed starter does not match its census race, date and registration.')
        value = row['value']
        if value == 'unknown':
            value = None
        if value is not None and value not in label_values(task, scope):
            raise ValueError('Movement label outside the reviewed scope.')
        partner, partner_id = row.get('target_car'), row.get('target_rider_id')
        if task == 'follow' and value in TARGETED_FOLLOW:
            if not valid_car(partner) or partner == car or not is_registration(partner_id):
                raise ValueError('A follow observation requires a distinct and identified target.')
            matched = db.execute('SELECT rider FROM starters WHERE race = ? AND car = ?', (race, partner)).fetchone()
            if matched != (partner_id,):
                raise ValueError('Follow target does not match the census.')
        elif value is not None and (partner is not None or partner_id is not None):
            raise ValueError('A known label with no follow target cannot carry partner information.')
        db.execute('INSERT INTO labels VALUES(?, ?, ?, ?, ?, ?, ?, ?)',
                   (day, race, car, rider, task, scope, level, value))


def probabilities(values, pooled_counts, rider_counts):
    total = pooled_counts.total() + len(values)
    population = {v: (pooled_counts[v] + 1) / total for v in values}
    n = rider_counts.total()
    if not n:
        return population, population
    individual = {v: (rider_counts[v] + PRIOR_STRENGTH * population[v]) / (n + PRIOR_STRENGTH) for v in values}
    return population, individual


def score(distribution, outcome):
    return {
        'top_one_hits': int(max(distribution, key=distribution.get) == outcome),
        'brier': sum((p - (value == outcome)) ** 2 for value, p in distribution.items()),
        'log_loss': -math.log(distribution[outcome]),
    }


def score_movements(task, scope, distribution, value):
    yield 'movement', score(distribution, value)
    if task == 'attack':
        none = distribution['no_attack']
        yield 'any_attack_in_observed_window', score({False: none, True: 1 - none}, value != 'no_attack')
        if scope in FULL_WINDOWS and value != 'no_attack':
            location = {phase: p / (1 - none) for phase, p in distribution.items() if phase != 'no_attack'}
            yield 'first_location_given_attack', score(location, value)


def score_report(totals):
    n = totals['population']['n']
    def metrics(arm):
        return {'top_one_hits': totals[arm]['top_one_hits'],
                **{m: totals[arm][m] / n if n else None for m in ('brier', 'log_loss')}}
    return {'n': n, 'rider': metrics('rider'), 'population': metrics('population')}


def evaluate(db, before):
    condition = 'day < ?' if before else '1'
    args = (before,) if before else ()
    query = f'SELECT day, task, scope, level, rider, value FROM labels WHERE value IS NOT NULL AND {condition} ORDER BY day, race, car, task, scope, level'
    pools = defaultdict(Counter)
    riders = defaultdict(Counter)
    scores = defaultdict(lambda: defaultdict(Counter))
    bootstrap = Counter()
    for _, group in groupby(db.execute(query, args), key=lambda row: row[0]):
        today = list(group)
        for _, task, scope, level, rider, value in today:
            what = (task, scope, level)
            if not pools[what]:
                bootstrap[what] += 1
                continue
            prior = riders[what, rider]
            cohort = 'prior_rider' if prior else 'cold_rider'
            common, individual = probabilities(label_values(task, scope), pools[what], prior)
            for arm, distribution in [('population', common), ('rider', individual)]:
                for measure, result in score_movements(task, scope, distribution, value):
                    metrics = dict(n=1, **result)
                    for bucket in ('all', cohort):
                        scores[what, measure, bucket][arm].update(metrics)
        for _, task, scope, level, rider, value in today:
            what = (task, scope, level)
            pools[what][value] += 1
            riders[what, rider][value] += 1

    profiles = {rider: [] for rider, in db.execute(f'''SELECT DISTINCT rider FROM starters
                JOIN races ON starters.race = races.id WHERE rider IS NOT NULL AND {condition} ORDER BY rider''', args)}
    for ((task, scope, level), rider), counts in sorted(riders.items()):
        _, posterior = probabilities(label_values(task, scope), pools[task, scope, level], counts)
        profiles[rider].append(dict(task=task, scope=scope, window_level=level,
                                    observations=counts.total(), counts=dict(counts), probabilities=posterior))
    strata = []
    for what, pool in sorted(pools.items()):
        task, scope, level = what
        def paired(measure):
            return {bucket: score_report(scores[what, measure, bucket])
                    for bucket in ('all', 'prior_rider', 'cold_rider')}
        common, _ = probabilities(label_values(task, scope), pool, Counter())
        summary = dict(task=task, scope=scope, window_level=level, observed_counts=dict(pool),
                       population_probabilities=common,
                       bootstrap_observations=bootstrap[what], scores=paired('movement'))
        if task == 'attack':
            summary['any_attack_in_observed_window'] = paired('any_attack_in_observed_window')
            if scope in FULL_WINDOWS:
                summary['first_location_given_attack'] = paired('first_location_given_attack')
        strata.append(summary)
    reviewed_races, observed_races, unknown = db.execute(f'''SELECT COUNT(DISTINCT race),
        COUNT(DISTINCT CASE WHEN value IS NOT NULL THEN race END), COUNT(*) - COUNT(value)
        FROM labels WHERE {condition}''', args).fetchone()
    through, = db.execute(f'SELECT max(day) FROM races WHERE {condition}', args).fetchone()
    last_label, = db.execute(f'SELECT max(day) FROM labels WHERE value IS NOT NULL AND {condition}', args).fetchone()
    return dict(eligible_riders=len(profiles), observed_riders=sum(bool(rows) for rows in profiles.values()),
                census_through_jst=through, last_training_race_date_jst=last_label,
                reviewed_races=reviewed_races, observed_races=observed_races, unknown_observations=unknown,
                before_jst_exclusive=before, prior_strength=PRIOR_STRENGTH, strata=strata), profiles


def study(census, reviewed, *, before=None):
    """Fit through the last race day strictly earlier than `before`, if supplied."""
    if before is not None:
        iso_day(before)
    # SQLite spools the full census and labels on disk; only a day is held for updating.
    with closing(sqlite3.connect('')) as db:
        try:
            index_census(db, census)
            index_reviewed(db, reviewed)
        except sqlite3.IntegrityError as exc:
            raise ValueError('Duplicate census race, starter or reviewed observation.') from exc
        return evaluate(db, before)


def json_lines(path):
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


@contextmanager
def atomic_output(path):
    path = Path(path)
    with NamedTemporaryFile(mode='w', dir=path.parent, delete=False, encoding='utf-8') as handle:
        tmp = Path(handle.name)
        try:
            yield handle
            handle.flush()
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)


def write_outputs(report, profiles, *, profiles_path, report_path):
    if Path(profiles_path).resolve() == Path(report_path).resolve():
        raise ValueError('Profile and report outputs must differ.')
    with atomic_output(profiles_path) as output:
        for rider, profile in profiles.items():
            print(json.dumps({'rider_id': rider, 'history': profile, 'before_jst_exclusive': report['before_jst_exclusive'],
                              'last_training_race_date_jst': report['last_training_race_date_jst']},
                             sort_keys=True), file=output)
    with atomic_output(report_path) as output:
        print(json.dumps(report, sort_keys=True, indent=2, allow_nan=False), file=output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('census', 'reviewed', 'profiles', 'report'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--before', help='Exclusive last fit date, YYYY-MM-DD in Japan.')
    args = parser.parse_args()
    if len({p.resolve() for p in (args.census, args.reviewed, args.profiles, args.report)}) != 4:
        parser.error('Inputs and outputs need distinct paths.')
    report, profiles = study(json_lines(args.census), json_lines(args.reviewed), before=args.before)
    write_outputs(report, profiles, profiles_path=args.profiles, report_path=args.report)


if __name__ == '__main__':
    main()
