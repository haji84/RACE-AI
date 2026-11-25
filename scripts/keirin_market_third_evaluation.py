"""Evaluate the retained market-third research handoff from public Git receipts.

This command reads immutable aggregates only. It does not rerun private race
rows or turn the separate November 26 forecast commitment into market results.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess

from scripts import keirin_research_ledger as ledger
from scripts.keirin_generate_result_unread_analysis import instant, need
from scripts.keirin_joint_forward_score import _json
from scripts.keirin_research_cohort_score import CAPS


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = 'docs/evidence/keirin-joint-calibration-20261125'
REPLAY_COMMIT = '08213ae6bea3558f8b18559d6574ad8f0acb187b'
CONDITIONAL_COMMIT = '466343d9933844d834b2b5a0ff972b849b5554a0'
REGISTRATION_COMMIT = '6fc5cce0162f3fffdd42147bd88852573bb181e8'
ADAPTER_SHA256 = '9eee2278c66ff36543297d1f415a2ba03d238a28e95136d27f582721dfe078c9'
COMPLETE_WINDOWS = ('2026-11-23_complete', '2026-11-25_complete')
STRICT_WINDOW = '2026-11-25_strict_T15_T10'


def _receipt(repo, commit, path, sha256=None):
    timestamp, raw = ledger._lookup(commit, path, ADAPTER_SHA256,
                                   lambda revision, file: ledger._git_read(repo, revision, file))
    digest = ledger._digest(raw)
    need(sha256 is None or digest == sha256, 'RETAINED_RECEIPT_SHA_MISMATCH')
    return _json(raw), dict(commit=commit, sha256=digest, recorded_git_time=timestamp)


def _historical_scores(replay, conditional, baseline_fit_sha256):
    need(replay['schema'] == 'KEIRIN_MARKET_THIRD_ADAPTER_REPLAY_V1'
         and conditional['schema'] == 'KEIRIN_ARCHIVED_MARKET_CONDITIONAL_SWAP_V1'
         and replay['scope'] == 'REPLAY_SAVED_PODIUM_ODDS_AND_PAIRED_HISTORICAL_LABELS'
         and replay['adapter_sha256'] == ADAPTER_SHA256
         and ledger._sha(baseline_fit_sha256) and replay['baseline_fit_sha256'] == baseline_fit_sha256
         and replay['previous_historical_comparison_sha256'] == conditional['private_reproduction_packet_sha256']
         and replay['accessed_new_results'] is False and replay['production_changes'] is False
         and all(replay[key] is True for key in ('exacta_pair_mass_return_identical',
                                                'conditional_tail_scores_return_identical', 'original_support_identical')),
         'RETAINED_MARKET_REPLAY_BINDING_MISMATCH')
    windows = {}
    keys = (*COMPLETE_WINDOWS, STRICT_WINDOW)
    need(set(keys) == set(replay['scores']) == set(conditional['counts']), 'RETAINED_MARKET_WINDOWS_MISMATCH')
    for key in keys:
        echoed = replay['scores'][key]
        reference = conditional['counts'][key]
        races = echoed['races']
        need(type(races) is int and 0 < races == reference['n'], 'RETAINED_MARKET_WINDOW_RACE_COUNT_MISMATCH')
        scores = {}
        for cap in CAPS:
            pair = reference['fixed_budget_scores'][str(cap)]
            baseline, candidate = pair['original'], pair['market_third_only']
            old, new = echoed[f'prior_{cap}'], echoed[f'trial_{cap}']
            gained, lost = candidate['gained_vs_original'], candidate['lost_vs_original']
            need(all(row['n'] == races and row['same_budget_points'] == cap * races for row in (baseline, candidate))
                 and old == baseline['hits'] and new == candidate['hits']
                 and all(type(value) is int and 0 <= value <= races for value in (old, new, gained, lost))
                 and lost <= old and gained <= races - old and new == old + gained - lost,
                 'RETAINED_MARKET_FIXED_BUDGET_SCORE_MISMATCH')
            scores[str(cap)] = dict(races=races, tickets_per_arm=cap * races, baseline_hits=old,
                                   candidate_hits=new, gained=gained, lost=lost)
        for field in ('baseline_hits', 'candidate_hits'):
            hits = [scores[str(cap)][field] for cap in CAPS]
            need(hits == sorted(hits), 'RETAINED_MARKET_NESTED_BUDGET_MISMATCH')
        windows[key] = dict(races=races, subset_of=COMPLETE_WINDOWS[-1] if key == STRICT_WINDOW else None,
                            scores=scores)
    for cap in map(str, CAPS):
        strict = windows[STRICT_WINDOW]['scores'][cap]
        complete = windows[COMPLETE_WINDOWS[-1]]['scores'][cap]
        # The four paired outcome counts of the subset must fit within the
        # corresponding counts of the complete race day.
        for field in ('gained', 'lost'):
            need(strict[field] <= complete[field], 'RETAINED_MARKET_WINDOW_SUBSET_MISMATCH')
        need(strict['baseline_hits'] - strict['lost'] <= complete['baseline_hits'] - complete['lost']
             and strict['races'] - strict['baseline_hits'] - strict['gained'] <=
             complete['races'] - complete['baseline_hits'] - complete['gained'],
             'RETAINED_MARKET_WINDOW_SUBSET_MISMATCH')
    races = sum(windows[key]['races'] for key in COMPLETE_WINDOWS)
    need(races == replay['historical_unique_races'], 'RETAINED_MARKET_UNIQUE_RACE_COUNT_MISMATCH')
    pooled = {cap: {field: sum(windows[key]['scores'][cap][field] for key in COMPLETE_WINDOWS)
                    for field in windows[COMPLETE_WINDOWS[0]]['scores'][cap]}
              for cap in map(str, CAPS)}
    return dict(scope='RETAINED_RETROSPECTIVE_AGGREGATES', races=races, windows=windows,
                complete_windows_pooled=pooled, baseline_fit_sha256=baseline_fit_sha256,
                baseline_fit_before=replay['baseline_fit_before'], adapter_sha256=ADAPTER_SHA256,
                exacta_top2=dict(scored=0, pair_mass_preserved_in_replay=True))


def _registration(repo, replay):
    readiness, pointer = _receipt(repo, REGISTRATION_COMMIT, f'{EVIDENCE}/nov26-readiness-2347.json')
    need(readiness['schema'] == 'KEIRIN_NOV26_READINESS_REVERIFIED_V1'
         and readiness['raw_inputs_or_forecasts_in_record'] is False,
         'RETAINED_COHORT_RECEIPT_INVALID')
    provenance = {}
    for name, binding in readiness['provenance'].items():
        provenance[name], _ = _receipt(repo, REGISTRATION_COMMIT, binding['git_path'], binding['sha256'])
    fixed_pair = provenance['fixed_pair_fallback']
    identities, identity_pointer = _receipt(repo, readiness['roster']['frozen_identity_witness_commit'],
        'docs/evidence/keirin-winner-variation-20261125/nov26-identities-receipt.json')
    earliest, latest = (readiness['cutoffs'][f'conservative_{name}_jst'] for name in ('first', 'last'))
    roster, preparation = (readiness[key] for key in ('roster', 'preparation'))
    races = roster['races']
    need(readiness['date_jst'] == fixed_pair['date'] == identities['date']
         and instant(identities['assembled_at']) <= instant(identity_pointer['recorded_git_time'])
         <= instant(readiness['recorded_at_utc']) <= instant(pointer['recorded_git_time'])
         < instant(earliest) <= instant(latest)
         and fixed_pair['earliest'] == earliest and fixed_pair['latest'] == latest
         and ledger._sha(fixed_pair['fit_sha256']) and ledger._sha(fixed_pair['forecast_sha256'])
         and ledger._sha(identities['identity_manifest_sha256'])
         and identities['identity_manifest_sha256'] == roster['frozen_identity_manifest_sha256']
         and identities['starter_appearances'] == roster['starter_appearances']
         and races == fixed_pair['races'] == identities['registered_races'] == preparation['eligible']
         and races == preparation['missing_result'] and roster['same_registered_races_all_methods'] is True
         and preparation['scored'] == identities['target_day_final_result_rows_checked']
         == readiness['coverage']['target_day_t15_to_t10_capture_or_generation_verified']
         == replay['prospective_market_candidates'] == 0,
         'RETAINED_COHORT_SCOPE_OR_TIME_MISMATCH')
    return dict(scope='RETAINED_REGISTRATION_RECEIPTS', date=readiness['date_jst'],
                as_of=readiness['recorded_at_utc'], races=races, methods=roster['comparison_methods'],
                starter_appearances=roster['starter_appearances'], earliest_cutoff=earliest, latest_cutoff=latest,
                earliest_official_published_cutoff=readiness['cutoffs']['published_official_first_jst'],
                fixed_pair_fit_sha256=fixed_pair['fit_sha256'], fixed_pair_forecast_sha256=fixed_pair['forecast_sha256'],
                frozen_identity_manifest_sha256=identities['identity_manifest_sha256'],
                market_candidates_registered_in_receipts=replay['prospective_market_candidates'],
                races_scored_at_receipt=preparation['scored'], receipt=pointer, identity_receipt=identity_pointer)


def evaluate_retained(repo=ROOT):
    _, adapter = ledger._git_read(repo, REPLAY_COMMIT, 'scripts/keirin_market_third_study.py')
    need(ledger._digest(adapter) == ADAPTER_SHA256, 'MARKET_THIRD_ADAPTER_SHA_MISMATCH')
    replay, replay_pointer = _receipt(repo, REPLAY_COMMIT, f'{EVIDENCE}/market-third-adapter-replay.json')
    conditional, conditional_pointer = _receipt(repo, CONDITIONAL_COMMIT, f'{EVIDENCE}/conditional-trifecta-odds-replay.json')
    baseline, _ = _receipt(repo, REPLAY_COMMIT,
        'docs/evidence/keirin-tactical-dossier-20261125/joint-finish-forward-receipt.json')
    historical = _historical_scores(replay, conditional, baseline['fit_sha256'])
    historical.update(replay_receipt=replay_pointer, paired_reference=conditional_pointer)
    registration = _registration(repo, replay)
    reasons = ['NO_INDEPENDENT_MARKET_CANDIDATES_AT_RETAINED_READBACK']
    top4 = historical['complete_windows_pooled']['4']
    if top4['candidate_hits'] < top4['baseline_hits']:
        reasons.append('COMPLETE_HISTORICAL_TOP4_DECREASED')
    return dict(schema='KEIRIN_RETAINED_MARKET_THIRD_EVALUATION_V1',
                historical_market_replay=historical, retained_prospective_commitment=registration,
                candidate_disposition='HOLD_INDEPENDENT_MARKET_EVALUATION',
                candidate_disposition_reasons=reasons,
                accuracy_improvement_proven=False, production_weights_promoted=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT, help='Local checkout with the retained evidence commits.')
    args = parser.parse_args(argv)
    try:
        report = evaluate_retained(args.repo)
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        code = str(error) if re.fullmatch(r'[A-Z0-9_]+', str(error)) else type(error).__name__
        parser.exit(1, f'Cannot evaluate retained market evidence: {code}\n')
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
