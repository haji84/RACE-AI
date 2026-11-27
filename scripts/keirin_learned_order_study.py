"""Fit, calibrate and measure a new order model on two pinned private SQLite archives."""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
import gzip
from hashlib import file_digest
from itertools import permutations
import json
from math import fsum, log
import os
from pathlib import Path
import re
import sqlite3
from unicodedata import normalize

from race_ai import keirin_dossier_conditions as dossier
from race_ai import keirin_calibrated_selection as selection
from race_ai import keirin_learned_order as learned
from race_ai import keirin_nationwide_auto_generator as core
from race_ai import keirin_official_condition_trial as trial
from race_ai.keirin_joint_finish import JointFinish
from race_ai.keirin_public_two_source_normalizer import _mark
from scripts.keirin_capture_official_form_history import _private_directory, _save_once

ARCHIVE_COMMIT = '2a1260fb0940ad11160b56a36f9c24cc4fb2f6d2'
ARCHIVE_SHAS = ('1bdad22b9744c9c5563f7bb1af31875170a3e6b7f4b0dd73fba8f98d645d8fc4',
                'd915560877493816b90df8bcd5e7bdef45557f57100b4cd40a3d017cd959334d')
TRAIN = ('20251001', '20260929')
CALIBRATE = ('20261001', '20261029')
EVALUATE = ('20261101', '20261122')
TRAIN_RESULTS_BEFORE = '20260930'
CALIBRATION_RESULTS_BEFORE = '20261031'
CARD_FIELDS = {
    'races': ('race_date', 'venue_code', 'rno', 'is_girls', 'grade', 'race_type'),
    'entries': ('race_date', 'venue_code', 'rno', 'kumiban', 'kyu', 'racer_class', 'kyaku_shitsu',
                'forecast_mark', 'keisoku_tokuten', 'recent_win_rate', 'recent_2rentai_rate',
                'recent_3rentai_rate', 'age', 'gear_ratio'),
    'line_predictions': ('race_date', 'venue_code', 'rno', 'kumiban', 'line_no', 'position_in_line',
                         'line_size', 'role'),
}
SETTLEMENT_FIELDS = {'payouts': ('race_date', 'venue_code', 'rno', 'bet_type', 'combination', 'payout', 'fetched_at')}
STYLE = {'逃': 'NIGE', '両': 'ALLROUND', '追': 'MARK'}
MARKETS = {'trifectas': (3, '3連単', (1, 2, 4, 9, 12)), 'exactas': (2, '2車単', (1, 2))}
ARMS = (learned.MODEL_ID, core.EVIDENCE_A, core.EVIDENCE_B, 'display-two-component-equal-weight')
FLOOR = 1e-15


def _clock():
    return datetime.now(timezone.utc).isoformat()


def _sha(path):
    with path.open('rb') as raw:
        return file_digest(raw, 'sha256').hexdigest()


def _read(path, fields, window):
    """Expose only the declared columns and window to the current stage."""
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA trusted_schema=OFF')
        db.execute('PRAGMA query_only=ON')
        db.set_authorizer(lambda action, table, column, *_: sqlite3.SQLITE_OK if (
            action == sqlite3.SQLITE_SELECT or (action == sqlite3.SQLITE_READ and column in fields.get(table, ()))
        ) else sqlite3.SQLITE_DENY)
        return {table: db.execute(f'SELECT {",".join(columns)} FROM {table} WHERE race_date BETWEEN ? AND ?',
                                  window).fetchall() for table, columns in fields.items()}


def _rid(row):
    value = row['race_date'] + f'{int(row["venue_code"]):02d}{row["rno"]:02d}'
    if not core.VENUE.fullmatch(value):
        raise ValueError('LEARNED_STUDY_ARCHIVE_IDENTITY')
    return value


def _group(rows):
    by_race = defaultdict(list)
    for row in rows:
        by_race[_rid(row)].append(row)
    return by_race


def _line_groups(rows, cars, girls):
    if not rows:
        return [[car] for car in cars] if girls else None
    if len(rows) != len(cars) or {row['kumiban'] for row in rows} != set(cars):
        return None
    groups = defaultdict(list)
    for row in rows:
        if '競' in (row['role'] or '') or type(row['line_no']) is not int:
            return None
        groups[row['line_no']].append(row)
    out = []
    for _, members in sorted(groups.items()):
        if ({row['position_in_line'] for row in members} != set(range(1, len(members) + 1)) or
                any(row['line_size'] != len(members) for row in members)):
            return None
        out.append([row['kumiban'] for row in sorted(members, key=lambda row: row['position_in_line'])])
    return out


def _card(race, entries, lines):
    live = [row for row in entries if '欠車' not in (row['kyu'] or '')]
    cars = sorted(row['kumiban'] for row in live)
    if not 3 <= len(cars) <= 9 or len(cars) != len(set(cars)) or any(not 1 <= car <= 9 for car in cars):
        return None
    riders = []
    for row in live:
        try:
            mark = _mark(normalize('NFKC', row['forecast_mark']), len(cars))
        except (TypeError, ValueError):
            mark = None
        riders.append(dict(car=row['kumiban'], mark_rank=mark if type(mark) is int else
                           len(cars) + 1 if mark == 'UNMARKED' else None,
                           points=row['keisoku_tokuten'] or None, win_rate=row['recent_win_rate'],
                           top2_rate=row['recent_2rentai_rate'], top3_rate=row['recent_3rentai_rate'],
                           age=row['age'], gear=row['gear_ratio'], style=STYLE.get(row['kyaku_shitsu']),
                           rider_class=row['racer_class']))
    classes = {row['rider_class'] for row in riders}
    competition = ('GIRLS' if race['is_girls'] else 'CHALLENGE' if classes == {'A3'} else
                   'A1_A2' if classes <= {'A1', 'A2'} else 'S' if classes <= {'SS', 'S1', 'S2'} else 'OTHER')
    grade = (race['grade'] or '').upper()
    grade = {'FI': 'F1', 'FII': 'F2'}.get(grade, grade)
    return dict(race_id=_rid(race), riders=riders, line_groups=_line_groups(lines, cars, race['is_girls']),
                meeting_grade=grade, round_stage=dossier.round_stage(race['race_type']), competition=competition)


def _cards(paths, window):
    cards = {}
    for path in paths:
        tables = _read(path, CARD_FIELDS, window)
        entries, lines = map(_group, (tables['entries'], tables['line_predictions']))
        for race in tables['races']:
            race_id = _rid(race)
            if race_id in cards:
                raise ValueError('LEARNED_STUDY_DUPLICATE_RACE')
            cards[race_id] = _card(race, entries[race_id], lines[race_id])
    return dict(sorted(cards.items()))


def _paid(rows, before):
    settled, conflicts = defaultdict(dict), set()
    for row in rows:
        cutoff = row['fetched_at']
        fetched = cutoff[:10].replace('-', '') if type(cutoff) is str else ''
        expected_width = {'3連単': 3, '2車単': 2}.get(row['bet_type'])
        if (expected_width is None or type(row['payout']) is not int or row['payout'] <= 0 or
                (before is not None and (not re.fullmatch(r'20[0-9]{6}', fetched) or fetched >= before)) or
                type(row['combination']) is not str):
            continue
        text = normalize('NFKC', row['combination']).strip()
        if re.fullmatch(r'[1-9]' + r'(-[1-9])' * (expected_width - 1), text):
            ticket = tuple(map(int, text.split('-')))
            if len(set(ticket)) == expected_width:
                key = (_rid(row), row['bet_type'])
                amount = row['payout']
                if settled[key].get(ticket, amount) != amount:
                    conflicts.add(key)
                settled[key][ticket] = amount
    return {key: dict(sorted(values.items())) for key, values in settled.items() if key not in conflicts}


def _settlements(paths, window, *, before=None):
    return _paid((row for path in paths for row in _read(path, SETTLEMENT_FIELDS, window)['payouts']), before)


def _labels(contexts, winners):
    for context in contexts:
        tickets = winners.get((context.race_id, '3連単'), ())
        if tickets and all(set(ticket) <= set(context.cars) for ticket in tickets):
            yield context, tickets


def _calibrate(trained, contexts, payouts):
    examples = list(_labels(contexts, payouts))
    if not examples:
        raise ValueError('LEARNED_STUDY_NO_CALIBRATION_RACES')
    totals = dict.fromkeys(learned.TEMPERATURES, 0.)
    for basis, (_, winners) in zip(learned.bases(trained, [context for context, _ in examples]), examples, strict=True):
        for temperature in totals:
            totals[temperature] -= log(max(FLOOR, basis.winning_mass(winners, temperature)))
    losses = {str(key): value / len(examples) for key, value in totals.items()}
    return dict(temperature=min(totals, key=totals.get), races=len(examples), log_loss=losses)


def _display(card, cars):
    if len(cars) < 5:
        return {}
    riders = [dict(car=row['car'], competition_points=row['points'], win_rate=row['win_rate'],
                   top2_rate=row['top2_rate'], top3_rate=row['top3_rate'], style=row['style'],
                   mark_rank='UNMARKED' if row['mark_rank'] == len(cars) + 1 else row['mark_rank'])
              for row in card['riders']]
    domain = set(permutations(cars, 3))
    supported = trial._display_models(dict(race_id=card['race_id'], riders=riders, line_groups=card['line_groups']), domain)
    if {core.EVIDENCE_A, core.EVIDENCE_B} <= supported.keys():
        supported[ARMS[-1]] = {order: fsum(.5 * law.get(order, 0.) for law in supported.values()) for order in domain}
    return {name: JointFinish(cars, {order: law.get(order, 0.) for order in domain}, tail=(0., 0.))
            for name, law in supported.items()}


def _freeze_forecasts(path, trained, cards, contexts, temperature):
    # Every test prediction is written before opening any test payout table.
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'wb') as file:
        with gzip.GzipFile(fileobj=file, mode='wb', mtime=0) as output:
            predictions = learned.predict(trained, contexts, temperature=temperature)
            for context, joint in zip(contexts, predictions, strict=True):
                arms = {learned.MODEL_ID: joint, **_display(cards[context.race_id], context.cars)}
                laws = {name: [[*ticket, probability] for ticket, probability in sorted(record.trifectas().items())
                               if probability > 0] for name, record in arms.items()}
                output.write(core.canonical(dict(race_id=context.race_id, distributions=laws)) + b'\n')
        file.flush()
        os.fsync(file.fileno())
    return _sha(path)


def _cases(card):
    if card is None:
        return ('all', 'card:unavailable')
    count = len(card['riders'])
    day = card['race_id'][:8]
    return ('all', f'day:{day}', f'venue:{card["race_id"][8:10]}', f'field:{count}',
            f'competition:{card["competition"]}', f'grade:{card["meeting_grade"] or "unknown"}',
            f'round:{card["round_stage"] or "unknown"}', f'lines:{"available" if card["line_groups"] else "unavailable"}')


def _measure(path, expected, cards, payouts):
    if _sha(path) != expected:
        raise ValueError('LEARNED_STUDY_TEST_FORECAST_CHANGED')
    with gzip.open(path, 'rt') as records:
        forecasts = {row['race_id']: row['distributions'] for row in map(json.loads, records)}
    totals, coverage = defaultdict(Counter), Counter()
    uncertainty, paid_by_day = defaultdict(Counter), defaultdict(Counter)
    for race_id, card in cards.items():
        saved = forecasts.get(race_id, {})
        laws = {arm: {tuple(row[:3]): row[3] for row in rows} for arm, rows in saved.items()}
        coverage['scheduled_in_archive'] += 1
        coverage['candidate_generated'] += learned.MODEL_ID in laws
        for market, (places, query, budgets) in MARKETS.items():
            actual = payouts.get((race_id, query))
            coverage[f'{market}_known_settlement'] += bool(actual)
            if not actual:
                continue
            coverage[f'{market}_multiple_winning_tickets'] += len(actual) > 1
            selections, losses, probabilities = {}, {}, {}
            for arm, triple_mass in laws.items():
                market_mass = defaultdict(float)
                for order, probability in triple_mass.items():
                    market_mass[order[:places]] += probability
                selections[arm] = sorted(market_mass, key=lambda ticket: (-market_mass[ticket], ticket))
                losses[arm] = -log(max(FLOOR, fsum(market_mass.get(ticket, 0.) for ticket in actual)))
                probabilities[arm] = market_mass
            ranking = selections.get(learned.MODEL_ID, [])
            for size in budgets:
                if len(ranking) < size:
                    continue
                shortlist = ranking[:size]
                mass = min(1., fsum(probabilities[learned.MODEL_ID][ticket] for ticket in shortlist))
                hit = any(ticket in actual for ticket in shortlist)
                _, band = selection._band(mass)
                uncertainty[market, size, band].update(n=1, hits=int(hit), mass=mass, brier=(mass - hit) ** 2)
                paid_by_day[market, size, race_id[:8]].update(stake=100 * size, payout=sum(actual.get(ticket, 0)
                                                                                           for ticket in shortlist))
            for group in _cases(card):
                total = totals[group, market]
                total['eligible'] += 1
                for arm in ARMS:
                    picks = selections.get(arm, [])
                    total[arm + ':forecast'] += bool(picks)
                    if picks:
                        total[arm + ':log_loss_sum'] += losses[arm]
                    for size in budgets:
                        hit = any(ticket in picks[:size] for ticket in actual)
                        key = f':Hit@{size}'
                        total[arm + key] += hit
                        if arm != learned.MODEL_ID and len(picks) >= size and len(selections.get(learned.MODEL_ID, ())) >= size:
                            fitted_hit = any(ticket in selections[learned.MODEL_ID][:size] for ticket in actual)
                            total[arm + key + ':paired'] += 1
                            total[arm + key + ':paired_existing_hits'] += hit
                            total[arm + key + ':paired_learned_hits'] += fitted_hit
    fixed_confidence = {f'{market}/Hit@{size}/{band}': dict(
        races=row['n'], hits=row['hits'], observed_rate=row['hits'] / row['n'],
        mean_probability=row['mass'] / row['n'], brier=row['brier'] / row['n'])
        for (market, size, band), row in sorted(uncertainty.items())}
    fixed_returns = {}
    for market, (_, _, budgets) in MARKETS.items():
        for size in budgets:
            amounts = [row for (kind, points, _), row in sorted(paid_by_day.items()) if (kind, points) == (market, size)]
            balance = peak = drawdown = 0
            for row in amounts:
                balance += row['payout'] - row['stake']
                peak = max(peak, balance)
                drawdown = max(drawdown, peak - balance)
            stake, payout = (sum(row[field] for row in amounts) for field in ('stake', 'payout'))
            fixed_returns[f'{market}/Hit@{size}'] = dict(stake_yen=stake, payout_yen=payout,
                return_rate=payout / stake if stake else None, max_day_net_drawdown_yen=drawdown if stake else None)
    confidence = selection.grade_confidence(0., series=learned.MODEL_ID, at=_clock())
    return dict(coverage=coverage, breakdown={f'{group}/{market}': dict(numbers)
                                              for (group, market), numbers in sorted(totals.items())},
                fixed_set_calibration=fixed_confidence, fixed_set_virtual_returns=fixed_returns,
                confidence_status=confidence['status'])


def recheck(paths, root):
    """Reuse a previously frozen model and forecasts without refitting or selecting."""
    root = _private_directory(root)
    if tuple(map(_sha, paths)) != ARCHIVE_SHAS:
        raise ValueError('LEARNED_STUDY_ARCHIVE_PIN')
    prior = json.loads((root / 'report.json').read_bytes())
    receipt = json.loads((root / 'test-forecast-receipt.json').read_bytes())
    path = root / 'test-forecasts.jsonl.gz'
    expected = receipt['forecast_sha256']
    if (_sha(path) != expected or expected != prior['test_forecasts_sha256'] or
            _sha(root / 'trees.txt') != prior['tree_sha256'] or prior['evaluation_window'] != list(EVALUATE)):
        raise ValueError('LEARNED_STUDY_ARTIFACT_CHANGED')
    cards = _cards(paths, EVALUATE)
    trained, temperature = learned.load_frozen(json.loads((root / 'model.json').read_bytes()),
                                               (root / 'trees.txt').read_text())
    with gzip.open(path, 'rt') as records:
        row = json.loads(next(records))
    context = learned.context(cards[row['race_id']])
    joint, = learned.predict(trained, [context], temperature=temperature)
    frozen = {tuple(ticket[:3]): ticket[3] for ticket in row['distributions'][learned.MODEL_ID]}
    if joint.trifectas() != frozen:
        raise ValueError('LEARNED_STUDY_REOPENED_MODEL_FORECAST_CHANGED')
    result = _measure(path, expected, cards, _settlements(paths, EVALUATE))
    if result['coverage'] != prior['coverage'] or result['breakdown'] != prior['breakdown']:
        raise ValueError('LEARNED_STUDY_FIXED_SCORE_CHANGED')
    report = dict(prior, **result, reopened_model_forecast_verified=True)
    output = root / 'verified-report.json'
    if output.exists():
        saved_report = json.loads(output.read_bytes())
        if report != {key: value for key, value in saved_report.items() if key != 'readback_at'}:
            raise ValueError('LEARNED_STUDY_READBACK_RESULT_CHANGED')
        return saved_report
    report['readback_at'] = _clock()
    _save_once(output, core.canonical(report))
    return report


def run(paths, root, *, threads=2):
    import lightgbm as lgb

    root = _private_directory(root)
    if (root / 'model.json').exists():
        raise ValueError('LEARNED_STUDY_ALREADY_FROZEN_USE_RECHECK')
    if tuple(map(_sha, paths)) != ARCHIVE_SHAS:
        raise ValueError('LEARNED_STUDY_ARCHIVE_PIN')
    paths = tuple(paths)
    fit_cards = _cards(paths, TRAIN)
    fit_examples = list(_labels((learned.context(card) for card in fit_cards.values() if card is not None),
                                _settlements(paths, TRAIN, before=TRAIN_RESULTS_BEFORE)))
    trained = learned.fit(fit_examples, train_through=TRAIN[1], threads=threads)
    booster_path = root / 'trees.txt'
    _save_once(booster_path, trained.model_to_string().encode())
    fitted_at = _clock()
    print(json.dumps(dict(fitted_races=len(fit_examples), inventory=len(fit_cards), fitted_at=fitted_at)), flush=True)
    trained = lgb.Booster(model_file=str(booster_path))
    cal_cards = _cards(paths, CALIBRATE)
    calibration = _calibrate(trained, [learned.context(card) for card in cal_cards.values() if card is not None],
                             _settlements(paths, CALIBRATE, before=CALIBRATION_RESULTS_BEFORE))
    frozen = dict(model_id=learned.MODEL_ID, archive_commit=ARCHIVE_COMMIT,
                  archive_sha256=list(ARCHIVE_SHAS), features=list(learned.FEATURES), tree_sha256=_sha(booster_path),
                  fit_window=TRAIN, fit_results_before=TRAIN_RESULTS_BEFORE,
                  fit_inventory=len(fit_cards), fit_labels=len(fit_examples), fitted_at=fitted_at,
                  calibration_window=CALIBRATE, calibration_results_before=CALIBRATION_RESULTS_BEFORE,
                  calibration=calibration, lightgbm=lgb.__version__,
                  evaluation_window=EVALUATE, frozen_at=_clock())
    _save_once(root / 'model.json', core.canonical(frozen))
    eval_cards = _cards(paths, EVALUATE)
    path = root / 'test-forecasts.jsonl.gz'
    forecast_sha = _freeze_forecasts(path, trained, eval_cards,
        [learned.context(card) for card in eval_cards.values() if card is not None], calibration['temperature'])
    forecasts_frozen_at = _clock()
    _save_once(root / 'test-forecast-receipt.json', core.canonical(dict(forecast_sha256=forecast_sha,
                                                                      frozen_at=forecasts_frozen_at)))
    print(json.dumps(dict(test_forecast_sha256=forecast_sha, forecasts_frozen_at=forecasts_frozen_at,
                          calibration=calibration)), flush=True)
    if _sha(path) != forecast_sha:
        raise ValueError('LEARNED_STUDY_TEST_FORECAST_READBACK')
    report = dict(frozen, test_forecasts_sha256=forecast_sha, test_forecasts_frozen_at=forecasts_frozen_at,
                  scope='RETROSPECTIVE_ARCHIVE_NO_PRE_CUTOFF_ATTESTATION',
                  operational_confidence='判定保留', verified_pre_cutoff_odds_count=0, provider_requests=0,
                  **_measure(path, forecast_sha, eval_cards, _settlements(paths, EVALUATE)))
    report['scored_at'] = _clock()
    _save_once(root / 'report.json', core.canonical(report))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archives', nargs=2, type=Path, required=True)
    parser.add_argument('--private-root', type=Path, required=True)
    parser.add_argument('--recheck', action='store_true', help='Verify the fixed score again and record set calibration')
    args = parser.parse_args()
    os.umask(0o077)
    result = recheck(args.archives, args.private_root) if args.recheck else run(args.archives, args.private_root)
    print(json.dumps({'private_root': str(args.private_root), 'coverage': result['coverage'],
                      'overall': {key: value for key, value in result['breakdown'].items() if key.startswith('all/')}},
                     ensure_ascii=False), flush=True)
