"""A retained P1 receipt can substantiate a changed deadline, never late bets."""
from copy import deepcopy
from datetime import datetime
import unittest

from tests.test_frozen_day_cycle import sample, observation
from race_ai.frozen_day_cycle import read_p0, evaluate
from race_ai.all_race_top8_target import all_race_top8_target


def inputs(revised='2030-04-01T10:48:00+09:00'):
    _, raw, receipt = sample()
    _, rows = read_p0(raw, receipt, expected_day='2030-04-01')
    witness = deepcopy(rows[0])
    witness.update(stage='P1', cutoff_at=revised, artifact_id=2,
                   as_of='2030-04-01T01:40:00Z', server_saved_at='2030-04-01T01:41:00Z')
    rows.append(witness)
    obs = observation(witness)
    return rows, [obs]


class CutoffRevisionTests(unittest.TestCase):
    def test_baseline_revision_does_not_rescue_foreign_learned_roster(self):
        from race_ai.boat_observed_pairwise_models import MODEL_IDS
        rows,obs=inputs();learned=deepcopy(rows[0]);learned.update(stage='P1',model_id=MODEL_IDS[0])
        learned['roster']['1']='9999'
        result=all_race_top8_target(rows,[dict(race_id=rows[0]['race_id'],cutoff_at=rows[0]['cutoff_at'])],obs,
            now=datetime.fromisoformat('2030-04-01T03:00:00+00:00'),expected_models={r['model_id'] for r in rows},learned_rows=[learned])
        selected=[r for r in result['per_forecast'] if r['variant']=='LEARNED_SHADOW' and r['model_id']==learned['model_id']]
        self.assertFalse(selected[0]['issued'])

    def test_learned_variant_uses_same_baseline_authenticated_revision(self):
        from race_ai.boat_observed_pairwise_models import MODEL_IDS
        rows,obs=inputs();learned=deepcopy(rows[0]);learned.update(stage='P1',model_id=MODEL_IDS[0])
        before=deepcopy(learned)
        result=all_race_top8_target(rows,[dict(race_id=rows[0]['race_id'],cutoff_at=rows[0]['cutoff_at'])],obs,
            now=datetime.fromisoformat('2030-04-01T03:00:00+00:00'),expected_models={r['model_id'] for r in rows},learned_rows=[learned])
        selected=[r for r in result['per_forecast'] if r['variant']=='LEARNED_SHADOW' and r['model_id']==learned['model_id']]
        self.assertTrue(selected[0]['issued'])
        self.assertIn('cutoff_revision_evidence',selected[0])
        self.assertEqual(learned,before)

    def test_later_revision_cannot_rescue_receipt_late_under_its_original_deadline(self):
        rows,obs=inputs('2030-04-01T11:10:00+09:00');rows[0]['server_saved_at']='2030-04-01T02:05:00Z'
        result=evaluate(rows,obs)
        self.assertEqual(result['per_forecast'][0]['state'],'RESULT_REJECTED')
        target=all_race_top8_target(rows,[dict(race_id=rows[0]['race_id'],cutoff_at=rows[0]['cutoff_at'])],obs,
            now=datetime.fromisoformat('2030-04-01T03:00:00+00:00'),expected_models={r['model_id'] for r in rows})
        selected=[r for r in target['per_forecast'] if r['stage']=='P0' and r['model_id']==rows[0]['model_id']]
        self.assertFalse(selected[0]['issued'])

    def test_preclose_same_roster_revision_scores_both_phases_without_rewriting_original(self):
        rows, obs = inputs(); before = deepcopy(rows)
        result = evaluate(rows, obs)
        self.assertEqual(result['scored_forecasts'], 3)
        first = result['per_forecast'][0]
        self.assertEqual(first['cutoff_at'], before[0]['cutoff_at'])
        self.assertEqual(first['settlement_cutoff_at'], '2030-04-01T10:48:00+09:00')
        self.assertEqual(first['cutoff_revision_evidence']['artifact_id'], 2)
        self.assertEqual(rows, before)

    def test_changed_result_cutoff_alone_does_not_authorize_revision(self):
        rows, obs = inputs()
        result = evaluate(rows[:2], obs)
        self.assertEqual(result['scored_forecasts'], 0)
        self.assertTrue(all(r['state']=='RESULT_REJECTED' for r in result['per_forecast']))

    def test_forecast_late_under_earlier_revised_deadline_is_rejected(self):
        rows, obs = inputs('2030-04-01T10:42:00+09:00')
        result = evaluate(rows, obs)
        self.assertEqual(result['scored_forecasts'], 1)
        self.assertEqual(result['per_forecast'][0]['state'], 'RESULT_REJECTED')

    def test_foreign_roster_cannot_supply_revision_for_other_phases(self):
        rows, obs = inputs(); rows[-1]['roster']['1']='9999'
        result = evaluate(rows, obs)
        self.assertEqual(result['scored_forecasts'], 0)

    def test_late_p1_cannot_substantiate_revision(self):
        rows, obs = inputs(); rows[-1]['server_saved_at']='2030-04-01T02:00:00Z'
        self.assertEqual(evaluate(rows, obs)['scored_forecasts'], 0)

    def test_conflicting_same_time_p1_revisions_are_not_order_dependent(self):
        rows, obs = inputs(); other=deepcopy(rows[-1])
        other.update(model_id=rows[1]['model_id'], cutoff_at='2030-04-01T10:49:00+09:00')
        rows.append(other)
        self.assertEqual(evaluate(rows, obs)['scored_forecasts'],0)
        self.assertEqual(evaluate(list(reversed(rows)), obs)['scored_forecasts'],0)

    def test_all_target_and_conditional_use_same_revised_result(self):
        rows, obs = inputs()
        schedule=[dict(race_id=rows[0]['race_id'],cutoff_at=rows[0]['cutoff_at'])]
        result=all_race_top8_target(rows,schedule,obs,now=datetime.fromisoformat('2030-04-01T03:00:00+00:00'),expected_models={r['model_id'] for r in rows})
        self.assertEqual(result['eligible_normal_final_races'],1)
        p0=[r for r in result['scoreboard'] if r['stage']=='P0']
        self.assertTrue(all(r['issued']==1 for r in p0))

    def test_future_receipt_cannot_revise_an_earlier_audit_boundary(self):
        rows, obs = inputs('2030-04-01T14:00:00+09:00')
        rows[-1].update(as_of='2030-04-01T02:58:00Z',server_saved_at='2030-04-01T02:59:00Z')
        obs[0]['closed_at']=rows[0]['cutoff_at']
        result=all_race_top8_target(rows,[dict(race_id=rows[0]['race_id'],cutoff_at=rows[0]['cutoff_at'])],obs,
            now=datetime.fromisoformat('2030-04-01T02:30:00+00:00'),expected_models={r['model_id'] for r in rows})
        self.assertEqual(result['eligible_normal_final_races'],1)
