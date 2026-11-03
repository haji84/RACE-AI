"""Same-race/same-stage diagnostics, permanently ineligible for formal scores.

Reuses the result-revision parser; neither local source claims nor deterministic
model replay attest prospective availability, an official result or a freeze.
The supplied predictor is an audited-code interface, not an authority callback.
"""
from copy import deepcopy
from datetime import date, timedelta, timezone
import re

from .actions_contract import canonical, digest, stamp
from .proof_aware_settlement import audit_settlement

MODEL_IDS = ('boat-observed-pairwise-factor-v1', 'boat-observed-pairwise-start-v1')
SCHEMA = 'RACE_AI_OBSERVED_PAIR_PLAN_V1'
STAGES = ('P0', 'P1')
JST = timezone(timedelta(hours=9))


class ComparisonError(ValueError):
    pass


def _require(condition):
    if not condition:
        raise ComparisonError('same-race research comparison rejected')


def _exact(obj, keys):
    _require(type(obj) is dict and set(obj) == set(keys.split()))


def _list(value, cap):
    _require(type(value) is list and len(value) <= cap)


def _sha(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def _ratio(n, d):
    return n/d if d else None


def compare_research_pairs(plan, contexts, cases, results, *, predict_pair, allow_source=None):
    """Evaluate claims on one declared target set; no formal accuracy promotion.

    plan records bind race revision and cutoff; contexts bind one snapshot/as_of
    per race/stage for BOTH models. Absent cases count as missing, not exclusions.
    Each supplied suite must exactly replay from its original snapshot. Replay
    verifies arithmetic only: the predictor must be independently reviewed/pinned
    by the caller. No result or metric is passed to the predictor.
    """
    # Finite JSON and independent copy before any callback.
    canonical([plan, contexts, cases, results])
    plan, contexts, cases, results = deepcopy((plan, contexts, cases, results))
    _exact(plan, 'schema declared_at event_date_jst model_ids result_revision_policy records')
    _require(plan['schema'] == SCHEMA and plan['model_ids'] == list(MODEL_IDS)
             and plan['result_revision_policy'] == 'LATEST_SUPPLIED_REVISION')
    declared = stamp(plan['declared_at'])
    day = date.fromisoformat(plan['event_date_jst'])
    _require(day.isoformat() == plan['event_date_jst'])
    _list(plan['records'], 10000)
    _require(bool(plan['records']) and callable(predict_pair))
    rows = {}
    for row in plan['records']:
        _exact(row, 'race_id sport venue race_no race_revision sales_cutoff_at')
        _require(type(row['venue']) is str and re.fullmatch('boatrace-jcd-(0[1-9]|1[0-9]|2[0-4])', row['venue']) is not None
                 and row['sport'] == 'boat' and type(row['race_no']) is int and 1 <= row['race_no'] <= 12
                 and type(row['race_revision']) is int and row['race_revision'] >= 1)
        ident = f"boat:{day.isoformat()}:{row['venue']}:{row['race_no']}"
        _require(row['race_id'] == ident and ident not in rows)
        cutoff = stamp(row['sales_cutoff_at'])
        _require(declared < cutoff and cutoff.astimezone(JST).date() == day)
        rows[ident] = row
    _list(contexts, 20000); _list(cases, 20000); _list(results, 100000)
    declared_contexts = {}
    for ctx in contexts:
        _exact(ctx, 'race_id stage as_of snapshot_sha256')
        _require(type(ctx['race_id']) is str and ctx['race_id'] in rows and ctx['stage'] in STAGES
                 and _sha(ctx['snapshot_sha256']))
        key = ctx['race_id'], ctx['stage']
        _require(key not in declared_contexts and declared <= stamp(ctx['as_of']) < stamp(rows[key[0]]['sales_cutoff_at']))
        declared_contexts[key] = ctx
    for race_id in rows:
        p0, p1 = (declared_contexts.get((race_id, s)) for s in STAGES)
        if p0 and p1:
            _require(stamp(p0['as_of']) < stamp(p1['as_of']))

    ledger = dict(schema='RACE_AI_FORECAST_AUDIT_V1', dataset_status='AUDIT_ONLY',
                  event_date_jst=day.isoformat(), records=list(rows.values()))
    audit_settlement(ledger, results, [])  # Structural parser ONLY; all authorities default-deny.
    latest = {}
    for result in results:
        _require(all(all(type(n) is int and 1 <= n <= 6 for n in payout['combination'])
                     for payout in result['payouts']))
        if result['status'] == 'FINAL':
            _require(stamp(result['confirmed_at']) > stamp(rows[result['race_id']]['sales_cutoff_at']))
        latest[result['race_id']] = result

    bound = {}
    for case in cases:
        _exact(case, 'snapshot suite')
        snapshot, suite = case['snapshot'], case['suite']
        _require(type(snapshot) is dict and type(suite) is dict)
        ident, stage = snapshot.get('race_id'), snapshot.get('stage')
        _require(type(ident) is str and stage in STAGES and ident in rows)
        key = ident, stage
        _require(key in declared_contexts and key not in bound)
        ctx, row = declared_contexts[key], rows[ident]
        snapshot_sha = digest(snapshot)
        _require(snapshot_sha == ctx['snapshot_sha256'] and snapshot.get('as_of') == ctx['as_of']
                 and snapshot.get('race_revision') == row['race_revision']
                 and snapshot.get('sales_cutoff_at') == row['sales_cutoff_at'])
        candidate = deepcopy(snapshot)
        replay = predict_pair(candidate, allow_source=allow_source)
        _require(digest(candidate) == snapshot_sha and canonical(replay) == canonical(suite))
        _require(suite.get('schema') == 'RACE_AI_BOAT_OBSERVED_PAIRWISE_SUITE_V1'
                 and type(suite.get('models')) is dict and set(suite['models']) == set(MODEL_IDS))
        for item in (suite, *suite['models'].values()):
            _require(type(item) is dict and item.get('race_id') == ident and item.get('stage') == stage
                     and item.get('race_revision') == row['race_revision']
                     and item.get('as_of') == ctx['as_of'] and item.get('snapshot_sha256') == snapshot_sha
                     and item.get('sales_cutoff_at') == row['sales_cutoff_at']
                     and item.get('official_prediction') is False
                     and item.get('result_or_cutoff_proof_eligible') is False)
        for name in MODEL_IDS:
            model = suite['models'][name]
            _require(model.get('model_id') == name and model.get('model_version') == '0.1.0-UNTRAINED'
                     and type(model.get('score_discriminating')) is bool)
            tickets = model.get('ordered_top8')
            _list(tickets, 8)
            _require(bool(tickets))
            unique = set()
            for ticket in tickets:
                _require(type(ticket) is list and len(ticket) == 3 and
                         all(type(n) is int and 1 <= n <= 6 for n in ticket) and len(set(ticket)) == 3)
                unique.add(tuple(ticket))
            _require(len(unique) == len(tickets))
        bound[key] = suite

    eligible = {ident for ident, r in latest.items() if r['status'] == 'FINAL' and r['trifecta_offered']}
    denominator = len(eligible)
    reports = {}
    race_reports = []
    hit_lookup = {}
    for ident in sorted(rows):
        outcome = latest.get(ident)
        winners = {tuple(p['combination']) for p in outcome['payouts']} if outcome else set()
        rr = dict(race_id=ident, result_revision=outcome['revision_no'] if outcome else None,
                  result_status=outcome['status'] if outcome else 'MISSING',
                  claimed_eligible=ident in eligible, stages={})
        for stage in STAGES:
            suite = bound.get((ident, stage))
            rr['stages'][stage] = {}
            for name in MODEL_IDS:
                model = suite['models'][name] if suite else None
                hit = bool(ident in eligible and model and any(tuple(t) in winners for t in model['ordered_top8']))
                hit_lookup[ident, stage, name] = hit
                rr['stages'][stage][name] = dict(output_present=model is not None,
                    score_discriminating=model['score_discriminating'] if model else False,
                    research_hit_at_8=hit, missing_reason=None if model else 'NO_RESEARCH_OUTPUT',
                    formal_freeze_verified=False)
        race_reports.append(rr)
    for stage in STAGES:
        paired = [i for i in eligible if (i, stage) in bound]
        models = {}
        for name in MODEL_IDS:
            informative = sum(bound[i, stage]['models'][name]['score_discriminating'] for i in paired)
            hits = sum(hit_lookup[i, stage, name] for i in eligible)
            models[name] = dict(output_count=len(paired), informative_count=informative,
                uninformative_count=len(paired)-informative, missing_count=denominator-len(paired),
                hit_at_8_count=hits, output_coverage=_ratio(len(paired), denominator),
                informative_coverage=_ratio(informative, denominator), research_hit_at_8_all=_ratio(hits, denominator))
        paired_hits = {n: sum(hit_lookup[i, stage, n] for i in paired) for n in MODEL_IDS}
        reports[stage] = dict(models=models, paired_subset=dict(count=len(paired),
            selection='BOTH_RESEARCH_OUTPUTS_PRESENT_SUPPLEMENTARY_ONLY', hit_counts=paired_hits,
            research_hit_rates={n: _ratio(v, len(paired)) for n,v in paired_hits.items()}))
    both_stages = [i for i in eligible if all((i, s) in bound for s in STAGES)]
    within = {n: dict(paired_race_count=len(both_stages), comparison_type='LATER_INFORMATION_CHANGE_NOT_ALGORITHM_EFFECT',
                     p0_hits=sum(hit_lookup[i, 'P0', n] for i in both_stages),
                     p1_hits=sum(hit_lookup[i, 'P1', n] for i in both_stages)) for n in MODEL_IDS}
    output = dict(schema='RACE_AI_OBSERVED_PAIR_COMPARISON_V1', target_race_count=len(rows),
        claimed_eligible_denominator=denominator, pending_or_excluded_count=len(rows)-denominator,
        stages=reports, races=race_reports, within_model_stage_comparison=within,
        research_only=True, official_results_verified=False, source_availability_verified=False,
        external_freeze_verified=False, formal_hit_at_8_all=None,
        full_official_coverage_verified=False, main_integrated=False, purchase_decision='NO_BET',
        plan_sha256=digest(plan), contexts_sha256=digest(contexts), cases_sha256=digest(cases),
        results_sha256=digest(results))
    output['report_sha256'] = digest(output)
    return output
