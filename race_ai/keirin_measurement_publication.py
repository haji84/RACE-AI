"""Publish verified aggregate measurement receipts to the existing public state."""
from datetime import date, timedelta
from math import isfinite
import re
from subprocess import TimeoutExpired

from . import keirin_dossier_conditions as dossier
from . import keirin_nationwide_auto_generator as model
from . import keirin_official_condition_scoring as condition
from . import keirin_official_condition_trial as trial_contract
from . import keirin_official_paired_measurement as official
from . import keirin_paired_measurement as paired
from . import keirin_public_forecasts as public

SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_MEASUREMENT_DAY_V1'
COHORT_SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_MEASUREMENT_COHORT_V1'
LATEST = 'measurements/latest.json'
FIRST = trial_contract.STUDY_FIRST_DAY
END = FIRST + timedelta(days=condition.MAX_DAYS)
ARMS = paired.ARMS
COVERAGE = ('official_registered_races', 'archived_baseline_races', 'archived_result_races',
            'official_order_replay_verified_races', 'official_payout_verified_races',
            'official_result_replay_held_races', 'archived_baseline_without_result',
            'registered_without_original', 'cancelled_or_refunded_result_replays')
TRIAL_COVERAGE = ('replayed_official_results', 'no_admitted_condition_pair', 'attested_condition_pairs',
                  'pair_or_witness_held', 'official_premise_held')


def _need(ok, code):
    if not ok:
        raise ValueError('KEIRIN_MEASUREMENT_PUBLICATION_' + code)


def _date(day):
    _need(type(day) is str and re.fullmatch(r'20[0-9]{2}-[0-9]{2}-[0-9]{2}', day), 'DATE')
    return date.fromisoformat(day)


def _sha(value, width):
    return type(value) is str and len(value) == width and re.fullmatch(r'[0-9a-f]+', value)


def _numeric(number):
    return number is None or type(number) is int and abs(number) <= 10**12 or type(number) is float and isfinite(number)


def _row(value, keys, *, integer=()):
    required = {key: value[key] for key in keys}
    _need(all(_numeric(number) for number in required.values()), 'NUMBER')
    _need(all(type(required[key]) is int for key in integer), 'INTEGER')
    return required


def _interval(value):
    _need(value is None or type(value) is list and len(value) == 2 and
          all(x is not None and _numeric(x) for x in value) and value[0] <= value[1], 'INTERVAL')
    return None if value is None else list(value)


def _prob_scores(row):
    return _row(row, ('count', 'brier', 'log_loss'), integer=('count',))


def _bucket(row, *, bins=False):
    fields = ('count', 'hits', 'mean_probability', 'observed_rate', 'coverage')
    if bins:
        fields += ('lower', 'upper')
    return dict(_row(row, fields, integer=('count', 'hits')), rate_ci95=_interval(row['rate_ci95']))


def _calibration(row):
    scores = _prob_scores(row)
    bins = row['bins']
    _need(type(bins) is list and len(bins) <= 10, 'BINS')
    counts = _row(row, ('unavailable_pairs',), integer=('unavailable_pairs',))
    return dict(scores, **counts, state='UNVALIDATED' if scores['count'] else 'NO_PAIRED_PROBABILITIES',
                bins=[_bucket(bucket, bins=True) for bucket in bins],
                confidence_bands={band: _bucket(row['confidence_bands'][band])
                                  for band in ('very_high', 'high', 'medium', 'low')
                                  if band in row['confidence_bands']},
                trusted_confidence_labels=[])


def _market(row, *, detail=True):
    numbers = ('paired_races', 'gained', 'lost')
    result = _row(row, (*numbers, 'paired_difference'), integer=numbers)
    count = result['paired_races']
    _need(0 <= result['gained'] + result['lost'] <= count <= 600 and
          min(result['gained'], result['lost']) >= 0, 'PAIRS')
    result['paired_difference_ci95'] = _interval(row['paired_difference_ci95'])
    for arm in ARMS:
        side = result[arm] = dict(_row(row[arm], ('hits', 'rate'), integer=('hits',)),
                                  rate_ci95=_interval(row[arm]['rate_ci95']))
        _need(0 <= side['hits'] <= count, 'HITS')
        if detail:
            side['calibration'] = _calibration(row[arm]['calibration'])
    if detail:
        raw = row['virtual_returns']
        fields = ('unit_yen', 'paired_races', 'unavailable_payout_or_refund_pairs')
        virtual = _row(raw, fields, integer=fields)
        _need(virtual['unit_yen'] == paired.STAKE_YEN and 0 <= virtual['paired_races'] <= count and
              virtual['unavailable_payout_or_refund_pairs'] == count - virtual['paired_races'], 'VIRTUAL_SCOPE')
        for arm in ARMS:
            fields = ('stake_yen', 'payout_yen', 'net_yen')
            virtual[arm] = _row(raw[arm], (*fields, 'max_drawdown_yen', 'return_rate'), integer=fields)
        result['virtual_returns'] = dict(virtual, drawdown_order='CUTOFF_TIME_SIMULTANEOUS_NETTED')
    return result


def _coverage(source, allowed):
    result = {key: source[key] for key in allowed if key in source}
    _need(all(type(value) is int and 0 <= value <= 600 for value in result.values()), 'COVERAGE')
    return result


def _trial(row, day):
    if row is None:
        return None
    _need(row['schema'] == condition.DAY_SCHEMA and row['day_jst'] == day, 'TRIAL')
    markets = {market: _market(row['markets'][market]) for market in condition.TICKET_BUDGETS}
    count = row['eligible_paired_races']
    _need(type(count) is int and all(market['paired_races'] == count for market in markets.values()), 'TRIAL_COUNT')
    allowed = dict(meeting_grade=dossier.GRADES, round_stage=dossier.ROUND_PATTERNS,
                   field_size=tuple(map(str, range(5, 10))), venue_code=tuple(f'{n:02}' for n in range(100)),
                   feature_coverage=('ALL', 'PARTIAL'), competition=model.CLASSES,
                   largest_line_size=tuple(map(str, range(1, 10))))
    groups = {axis: {category: {name: _market(metrics[name], detail=False) for name in paired.PRIMARY}
                     for category, metrics in row['subgroups'][axis].items() if category in categories}
              for axis, categories in allowed.items() if axis in row['subgroups']}
    return dict(schema=condition.DAY_SCHEMA, day_jst=day, eligible_paired_races=count, markets=markets,
                coverage=_coverage(row['coverage'], TRIAL_COVERAGE), subgroups=groups,
                result_authority='KEIRIN_JP_OFFICIAL_SP_REPLAY', premise='ALL_FINISH_NO_TIES',
                probability_status='UNVALIDATED', interval_scope='EXPLORATORY_NOMINAL_WILSON_RACES_UNCLUSTERED',
                probability_scores={arm: {metric: _prob_scores(row['probability_scores'][arm][metric])
                                          for metric in condition.PROBABILITY_METRICS} for arm in ARMS})


def _document(*, day, archive_commit, index_sha256, checked_at, coverage, official_t15, meeting_condition_trial):
    _need(_date(day) <= model.when(checked_at).astimezone(dossier.form.JST).date() and
          _sha(archive_commit, 40) and _sha(index_sha256, 64), 'ORIGIN')
    _need('official_registered_races' in coverage, 'OFFICIAL_REGISTRY')
    return dict(schema=SCHEMA, day=day, archive_commit=archive_commit, index_sha256=index_sha256, checked_at=checked_at,
                coverage=_coverage(coverage, COVERAGE),
                official_t15={name: {market: _market(official_t15[name][market]) for market in official.MARKETS}
                              for name in official.COMPARISONS},
                meeting_condition_trial=_trial(meeting_condition_trial, day))


def _wire(body):
    data = public.canonical(body) + b'\n'
    _need(len(data) <= public.MAX_BYTES, 'SIZE')
    return data


def _path(day):
    _date(day)
    return f'measurements/{day}.json'


def read_day(store, head, day):
    raw = store.read_previous(head, _path(day))
    if raw is None:
        return None
    data = public._json(raw)
    _need(data.pop('schema') == SCHEMA and data['day'] == day and _wire(_document(**data)) == raw, 'READBACK_SCHEMA')
    return dict(data, schema=SCHEMA)


def _study_day(row):
    count = row['eligible_paired_races']
    _need(type(count) is int and 0 <= count <= 600, 'STUDY_COUNT')
    markets = {}
    for key in paired.PRIMARY:
        source = row['markets'][key]
        fields = ('paired_races', 'gained', 'lost')
        market = _row(source, fields, integer=fields)
        _need(market['paired_races'] == count and 0 <= min(market['gained'], market['lost']) and
              market['gained'] + market['lost'] <= count, 'STUDY_PAIRS')
        payouts = source['virtual_returns']
        paid = payouts['paired_races']
        _need(type(paid) is int and 0 <= paid <= count, 'STUDY_PAID_COUNT')
        virtual = {'paired_races': paid}
        for arm in ARMS:
            summary = market[arm] = _row(source[arm], ('hits',), integer=('hits',))
            money = virtual[arm] = _row(payouts[arm], ('stake_yen', 'payout_yen'),
                                        integer=('stake_yen', 'payout_yen'))
            _need(0 <= summary['hits'] <= count and money['stake_yen'] >= 0 and money['payout_yen'] >= 0 and
                  bool(money['stake_yen']) == bool(paid), 'STUDY_ARM')
        _need(virtual['published']['stake_yen'] == virtual['trial']['stake_yen'], 'STUDY_STAKE')
        markets[key] = dict(market, virtual_returns=virtual)
    return dict(schema=condition.DAY_SCHEMA, day_jst=row['day_jst'], eligible_paired_races=count, markets=markets)


def _cohort(store, parent, day, trial):
    raw = store.read_previous(parent, LATEST)
    previous = public._json(raw) if raw else None
    rows = {}
    if previous is not None:
        _need(previous['schema'] == COHORT_SCHEMA and type(previous['study_days']) is list and
              len(previous['study_days']) <= condition.MAX_DAYS, 'COHORT_HISTORY')
        for row in previous['study_days']:
            slug = row['day_jst']
            canonical = _study_day(row)
            _need(slug not in rows and FIRST <= _date(slug) < END and row == canonical, 'COHORT_DAY')
            rows[slug] = canonical
        _need(condition.summarize_days(list(rows.values())) == previous['cohort'], 'COHORT_READBACK')
    if FIRST <= _date(day) < END and trial is not None:
        rows[day] = _study_day(trial)
    study_days = [rows[day_key] for day_key in sorted(rows)]
    return dict(schema=COHORT_SCHEMA, study_days=study_days, cohort=condition.summarize_days(study_days))


def publish_day(store, report, *, index_sha256, checked_at):
    """Write one aggregate day and its bounded cohort in the same CAS commit."""
    _need(report['schema'] == official.SCHEMA and report['state'] == 'OFFICIAL_SP_RESULT_ARCHIVE_MEASURED',
          'OFFICIAL_REPORT')
    doc = _document(day=report['day_jst'], archive_commit=report['archive_commit'], index_sha256=index_sha256,
                    checked_at=checked_at.isoformat(), coverage=report['coverage'],
                    official_t15={name: report['comparisons'][name]['official_t15'] for name in official.COMPARISONS},
                    meeting_condition_trial=report.get('meeting_condition_trial'))
    day, path = doc['day'], _path(doc['day'])
    fresh = _wire(doc)
    for attempt in range(2):
        parent = store.head()
        _need(_sha(parent, 40), 'PUBLIC_BRANCH')
        store.fetch(parent)
        old = read_day(store, parent, day)
        if old:
            ignored = ('archive_commit', 'checked_at')
            stable = {key: value for key, value in doc.items() if key not in ignored}
            if stable == {key: value for key, value in old.items() if key not in ignored}:
                return dict(state='PUBLIC_MEASUREMENT_CURRENT', commit=parent, day=day)
            _need(model.when(old['checked_at']) < model.when(doc['checked_at']), 'STALE_MEASUREMENT')
            _need(old['meeting_condition_trial'] is None or doc['meeting_condition_trial'] is not None,
                  'MISSING_TRIAL_REPLAY')
        files = {path: fresh}
        cohort = _wire(_cohort(store, parent, day, doc['meeting_condition_trial']))
        if cohort != store.read_previous(parent, LATEST):
            files[LATEST] = cohort
        commit = store.commit(files, parent)
        delta = store.run(['diff-tree','--no-commit-id','--name-only','-r',parent,commit])
        _need(set(delta.decode().splitlines()) == set(files), 'PUBLISH_PATHS')
        try:
            store.push(commit, parent)
        except (ValueError, TimeoutExpired):
            head = store.head()
            if attempt or head == parent:
                raise
            continue
        _need(all(store.read_previous(commit, key) == raw for key, raw in files.items()), 'PUBLISH_READBACK')
        return dict(state='PUBLIC_MEASUREMENT_PUBLISHED', commit=commit, day=day)
    raise ValueError('KEIRIN_MEASUREMENT_PUBLICATION_CONCURRENT')
