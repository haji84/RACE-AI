"""Adapter from the actual PR #71 research suite to the PR #72 KEIRIN worker.

Run PR #71's pinned four_sport_model_suite.run_suite as injected callback.
No model substitutes, hard-coded picks, network I/O, or source-use grants.
A synthetic source checker in CI proves mechanics only. For real input the
owner must supply independently authorized, purpose-scoped source validation.
"""
from __future__ import annotations

from hashlib import sha256

from .keirin_result_delivery import canonical, utc
from .keirin_next_forecast_worker import _no_market_features


class Pr71AdapterError(ValueError):
    pass


def _require(ok, code):
    if not ok:
        raise Pr71AdapterError(code)


def run_pr71_for_next_race(private_snapshot, *, run_suite, verify_suite,
                           source_admission, model_id, issued_at):
    """Return the worker's strictly typed 8-pick payload from a real PR71 run.

    run_suite / verify_suite are trusted functions imported from a pinned PR71
    commit by the execution host. source_admission must check every
    real-source observation's exact purpose and grant. This code does not
    certify the caller supplied a legally valid grant.
    """
    _require(callable(run_suite) and callable(verify_suite),
             'PINNED_PR71_MODEL_AND_VERIFIER_REQUIRED')
    _require(type(private_snapshot) is dict
             and private_snapshot.get('schema') == 'RACE_AI_KEIRIN_PRIVATE_PRE_RACE_V1'
             and type(private_snapshot.get('facts')) is dict
             and set(private_snapshot['facts']) == {'pr71_evidenced_snapshot'},
             'PR71_EVIDENCE_INPUT_REQUIRED')
    _no_market_features(private_snapshot)
    evidence = private_snapshot['facts']['pr71_evidenced_snapshot']
    _require(type(evidence) is dict and evidence.get('schema') ==
             'RACE_AI_FOUR_SPORT_EVIDENCED_SNAPSHOT_V1',
             'INVALID_PR71_EVIDENCE')
    race = evidence.get('race')
    _require(type(race) is dict and
             race.get('sport') == 'keirin' and
             race.get('surface') == 'velodrome' and
             race.get('race_id') == private_snapshot['race_id'] and
             race.get('sales_cutoff_at') == private_snapshot['official_cutoff_at'] and
             race.get('as_of') == private_snapshot['as_of'] and
             evidence.get('scope') in ('SYNTHETIC_ONLY','OPERATOR_SUPPLIED_RESEARCH'),
             'RACE_TIME_OR_SCOPE_MISMATCH')
    runners = evidence.get('participants')
    _require(type(runners) is list and
             sorted(p.get('number') for p in runners if type(p) is dict) ==
             sorted(private_snapshot['starters']) and
             len(runners) == len(private_snapshot['starters']),
             'PR71_STARTERS_MISMATCH')
    _require(type(model_id) is str and model_id in (
                'multisport-factor-interaction-v1',
                'multisport-scenario-ensemble-v1',
                'multisport-matchup-interaction-v1',
                'multisport-matchup-scenario-v1'),
             'UNRECOGNIZED_PR71_MODEL_ID')
    at = utc(issued_at)
    _require(utc(private_snapshot['as_of']) <= at <
             utc(private_snapshot['official_cutoff_at']),
             'NOT_PROSPECTIVE')
    _require(evidence['scope'] != 'OPERATOR_SUPPLIED_RESEARCH'
             or callable(source_admission),
             'REAL_SOURCE_ADMISSION_REQUIRED')
    # Actual untrained PR71 algorithm; source admission is validated by its
    # own per-feature validators as well as the owner worker source receipt.
    suite = run_suite(evidence, allow_source=source_admission)
    _require(verify_suite(suite) is True and
             suite.get('race_id') == private_snapshot['race_id'] and
             suite.get('sales_cutoff_at') == private_snapshot['official_cutoff_at'] and
             suite.get('as_of') == private_snapshot['as_of'] and
             suite.get('official_prediction') is False and
             suite.get('external_timestamp_receipts') is None and
             suite.get('rights_not_granted_by_runner') is True,
             'PR71_SUITE_VERIFICATION_FAILED')
    models = suite['models']
    _require(type(models) is dict and model_id in models,
             'SELECTED_MODEL_ABSENT')
    result = models[model_id]
    _require(result.get('trained') is False and
             result.get('official_prediction') is False and
             result.get('odds_independent') is True and
             result.get('calibrated') is False and
             result.get('snapshot_sha256') == suite['input_sha256'] and
             result.get('model_version') == '0.1.0-UNTRAINED',
             'PR71_NOT_AN_UNTRAINED_RESEARCH_MODEL')
    picks = result.get('ordered_top8')
    _require(type(picks) is list and len(picks) == 8,
             'PR71_EIGHT_PICKS_REQUIRED')
    return {
        'race_id': private_snapshot['race_id'],
        'model_id': model_id,
        'model_version': result['model_version'],
        'generated_at': at.isoformat(),
        # This PR71 model is not trained. Do not invent a historical cutoff.
        'trained': False,
        'trained_until': None,
        'snapshot_sha256': sha256(canonical(private_snapshot)).hexdigest(),
        'top8': [list(pick) for pick in picks],
    }
