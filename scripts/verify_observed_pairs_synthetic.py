"""Actual separate candidate + B bridge + same-race comparison; all facts fictional."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PINS = {
    'race_ai/boat_observed_pairwise_models.py': 'f568d433fd3aede29baf0553e4d61d48fbfa697bb40da8102229a36218e27a59',
    'race_ai/actions_contract.py': 'a086488af4765d44af3a824c3e6a2223ec9386ab43969bdaf0562ec5302fd79f',
    'race_ai/legacy_boat_rank.py': '4624905d02d36ca0fbaa2faf8f700ae7d871f99271ae19893bc2619ac18c5353',
}


def main(reference=None):
    if not __debug__:
        raise RuntimeError('enabled assertions required')
    sys.path.insert(0, str(ROOT))
    ref = Path(reference) if reference else ROOT/'pr71-observed-pair-reference'
    if not PINS:
        raise RuntimeError('fixed reviewed candidate source required')
    for name, expected in PINS.items():
        data = (ref/name).read_bytes().replace(b'\r\n', b'\n')
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError('candidate source digest mismatch')
        if name != 'race_ai/boat_observed_pairwise_models.py' and data != (ROOT/name).read_bytes().replace(b'\r\n', b'\n'):
            raise RuntimeError('candidate dependency differs from current audit kernel')
    spec = importlib.util.spec_from_file_location('race_ai._observed_candidate', ref/'race_ai/boat_observed_pairwise_models.py')
    model = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(model)
    from race_ai.actions_contract import digest
    from race_ai.boat_observed_program_bridge import build_program_snapshot
    from race_ai.observed_pair_comparison import compare_research_pairs
    from tests.test_boat_observed_program_bridge import fixture, DAY, ASOF

    with patch('socket.socket', side_effect=RuntimeError('network forbidden in synthetic check')):
        race, source = fixture()
        rows, contexts, cases, results = [], [], [], []
        for number, mode in enumerate(('complete', 'partial', 'absent', 'no-output'), 1):
            item = deepcopy(race)
            item['race_id'] = f'20300317-18-{number:02d}'
            for boat in item['boats']:
                lane = boat['lane']
                boat['national_win_rate'] = lane if mode != 'absent' else None
                boat['motor_top2_rate'] = 70-lane*5 if mode != 'absent' else None
                if mode == 'partial' and lane % 2:
                    boat['national_win_rate'] = None
            snapshot = build_program_snapshot(item, source, event_date_jst=DAY, as_of=ASOF, race_revision=1)
            rows.append(dict(race_id=snapshot['race_id'], sport='boat', venue=snapshot['venue'],
                             race_no=number, race_revision=1, sales_cutoff_at=snapshot['sales_cutoff_at']))
            results.append(dict(race_id=snapshot['race_id'], status='FINAL', trifecta_offered=True,
                payouts=[dict(combination=[1,2,3], yen_per_100=600)], refund_status='NONE', revision_no=1,
                confirmed_at=DAY+'T13:00:00+09:00', source_ref='https://example.org/fictional-result'))
            if mode == 'no-output':
                continue
            suite = model.predict_pair(snapshot, allow_source=lambda *args: True)  # Fictional test permission only.
            assert all(len(m['ordered_top8']) == 8 and len(m['candidates']) == 120 for m in suite['models'].values())
            assert all(m['score_discriminating'] == (mode != 'absent') for m in suite['models'].values())
            contexts.append(dict(race_id=snapshot['race_id'], stage='P0', as_of=ASOF, snapshot_sha256=digest(snapshot)))
            cases.append(dict(snapshot=snapshot, suite=suite))
        plan = dict(schema='RACE_AI_OBSERVED_PAIR_PLAN_V1', declared_at=DAY+'T07:00:00+09:00',
            event_date_jst=DAY, model_ids=list(model.MODEL_IDS), result_revision_policy='LATEST_SUPPLIED_REVISION', records=rows)
        out = compare_research_pairs(plan, contexts, cases, results, predict_pair=model.predict_pair,
                                     allow_source=lambda *args: True)
        assert out['claimed_eligible_denominator'] == 4 and out['formal_hit_at_8_all'] is None
        for result in out['stages']['P0']['models'].values():
            assert (result['output_count'], result['informative_count'], result['missing_count']) == (3,2,1)
            assert result['output_coverage'] == .75 and result['informative_coverage'] == .5
        assert out['stages']['P1']['paired_subset']['count'] == 0
    print(json.dumps(dict(status='SYNTHETIC_CI_PASS', scenarios=4, actual_candidate_models=2,
        same_race_stage=True, missing_output_retained=True, report_sha256=out['report_sha256'],
        real_sources=0, formal_accuracy_verified=False), sort_keys=True))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) == 2 else None)
