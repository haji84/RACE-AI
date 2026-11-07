"""All-race scoring uses official outcomes, including absent original forecasts."""
from copy import deepcopy
from datetime import datetime, timezone
from itertools import permutations
import unittest

from race_ai import observed_weight_learning as learning
from race_ai.boat_ab_shadow import MODEL_IDS as AB
from race_ai.boat_live_feature_shadow import MODEL_ID as C
from race_ai.boat_observed_pairwise_models import MODEL_IDS as OBSERVED
from tests.test_frozen_day_cycle import observation

NOW = datetime(2030, 4, 1, 8, tzinfo=timezone.utc)
MODELS = sorted(set(AB) | {C} | set(OBSERVED))


def evidence(count=2):
    rows = []; schedule = []; outcomes = []
    for number in range(1, count + 1):
        rid = f'20300401-01-{number:02d}'
        cutoff = f'2030-04-01T03:{number:02d}:00+00:00'
        row = dict(race_id=rid, stage='P1', model_id=MODELS[0],
                   cutoff_at=cutoff, as_of='2030-04-01T02:00:00+00:00',
                   server_saved_at='2030-04-01T02:01:00+00:00', artifact_id=number,
                   model_sha256=str(number)*64, roster={str(i):str(4000+i) for i in range(1,7)},
                   ranked=[list(t) for t in permutations(range(1,7),3)])
        row['top8'] = deepcopy(row['ranked'][:8])
        rows.append(row); schedule.append(dict(race_id=rid, cutoff_at=cutoff))
        outcome = observation(row)
        outcome['captured_at'] = '2030-04-01T04:00:00+00:00'
        outcomes.append(outcome)
    return rows, schedule, outcomes


def audit(rows, schedule, outcomes, **kwargs):
    return learning.coverage_audit(rows, schedule, now=NOW, observations=outcomes,
                                   **kwargs)['all_race_top8_target']


def score(out, mid=MODELS[0], stage='P1', variant='BASELINE'):
    return next(s for s in out['scoreboard'] if
                (s['stage'],s['model_id'],s['variant']) == (stage,mid,variant))


class AllRaceTargetTests(unittest.TestCase):
    def test_one_hit_and_one_missing_is_half_with_missing_kept_distinct(self):
        rows, schedule, outcomes = evidence()
        out = audit(rows[:1], schedule, outcomes); board = score(out)
        self.assertEqual((board['eligible'], board['hits'], board['issued'], board['missing']), (2,1,1,1))
        self.assertEqual(board['hit_at_8_all'], .5)
        self.assertEqual(board['hit_at_8_saved_only'], 1.)
        self.assertEqual([f['state'] for f in out['per_forecast'] if f['model_id']==MODELS[0]],
                         ['HIT','NO_PRE_CUTOFF_FORECAST'])
        self.assertEqual((board['distinct_days'],board['distinct_venue_days']), (1,1))
        self.assertEqual(out['all_schedule_completion_status'], 'COMPLETE')

    def test_missing_both_is_zero_and_does_not_forge_misses(self):
        _, schedule, outcomes = evidence()
        out = audit([], schedule, outcomes)
        self.assertEqual(len(out['scoreboard']), 5)
        for board in out['scoreboard']:
            self.assertEqual((board['eligible'],board['hits'],board['missing'],board['hit_at_8_all']), (2,0,2,0.))
        self.assertTrue(all(f['state']=='NO_PRE_CUTOFF_FORECAST' for f in out['per_forecast']))

    def test_five_models_share_races_but_never_union_tickets(self):
        rows, schedule, outcomes = evidence(); all_rows=[]
        for mid in MODELS:
            for original in rows:
                row=deepcopy(original); row['model_id']=mid
                if mid != MODELS[0]:
                    row['ranked']=row['ranked'][8:]+row['ranked'][:8]
                    row['top8']=deepcopy(row['ranked'][:8])
                all_rows.append(row)
        out=audit(all_rows,schedule,outcomes)
        self.assertEqual(out['eligible_normal_final_races'],2)
        for board in out['scoreboard']:
            self.assertEqual(board['eligible'],2)
            self.assertEqual(board['hits'],2 if board['model_id']==MODELS[0] else 0)

    def test_exact_eight_full_rank_and_pre_cutoff_receipt_required(self):
        for mutation in ('nine','duplicate','short_rank','late','future_receipt','wrong_cutoff','wrong_roster'):
            with self.subTest(mutation=mutation):
                rows,schedule,outcomes=evidence(1); row=rows[0]
                if mutation=='nine': row['top8']=deepcopy(row['ranked'][:9])
                if mutation=='duplicate': row['top8'][1]=deepcopy(row['top8'][0])
                if mutation=='short_rank': row['ranked']=row['ranked'][:8]
                if mutation=='late': row['server_saved_at']=row['cutoff_at']
                if mutation=='future_receipt': row['server_saved_at']='2030-04-02T01:00:00Z'
                if mutation=='wrong_cutoff': row['cutoff_at']='2030-04-01T05:00:00Z'
                if mutation=='wrong_roster': row['roster']['1']='9999'
                out=audit(rows,schedule,outcomes); board=score(out)
                self.assertEqual((board['eligible'],board['hits'],board['missing']), (1,0,1))
                item=next(f for f in out['per_forecast'] if f['model_id']==MODELS[0])
                self.assertEqual(item['state'],'NO_PRE_CUTOFF_FORECAST')
                self.assertTrue(item['reason'])

    def test_first_original_cannot_be_replaced_by_later_winning_tickets(self):
        rows,schedule,outcomes=evidence(1); later=deepcopy(rows[0])
        rows[0]['ranked']=rows[0]['ranked'][8:]+rows[0]['ranked'][:8]
        rows[0]['top8']=deepcopy(rows[0]['ranked'][:8])
        later.update(server_saved_at='2030-04-01T02:02:00Z',artifact_id=99)
        out=audit([later]+rows,schedule,outcomes)
        self.assertEqual(score(out)['hits'],0)
        self.assertEqual(next(f for f in out['per_forecast'] if f['model_id']==MODELS[0])['state'],'MISS')

    def test_same_receipt_conflicts_and_result_conflicts_remain_unknown(self):
        rows,schedule,outcomes=evidence(1); conflict=deepcopy(rows[0]); conflict['top8'].reverse()
        out=audit(rows+[conflict],schedule,outcomes)
        self.assertEqual(score(out)['missing'],1)
        conflicting_outcomes=deepcopy(outcomes)
        conflicting_outcomes[0]['source_sha256']='c'*64
        conflicting_outcomes[0]['data']['payouts'][0]['payout_per_100_yen']=2460
        out=audit(rows,schedule,outcomes+conflicting_outcomes)
        self.assertEqual((out['eligible_normal_final_races'],out['unknown_races']), (0,1))
        self.assertEqual(out['per_race'][0]['result_state'],'RESULT_CAPTURE_CONFLICT')

    def test_future_result_capture_preserves_current_denominator_and_settlement_in_both_orders(self):
        rows,schedule,outcomes=evidence(2)
        expected=audit(rows[:1],schedule,outcomes)
        for race_index in (0,1):
            for future_first in (True,False):
                with self.subTest(race_index=race_index,future_first=future_first):
                    future=deepcopy(outcomes[race_index])
                    future['captured_at']='2030-04-02T01:00:00Z'
                    future['data']['results'][0]['racer_registration_id']='9999'
                    captures=([future]+outcomes if future_first else outcomes+[future])
                    out=audit(rows[:1],schedule,captures)
                    self.assertEqual(out['scoreboard'],expected['scoreboard'])
                    self.assertEqual(out['per_race'],expected['per_race'])
                    self.assertEqual((score(out)['eligible'],score(out)['hits'],score(out)['missing'],score(out)['hit_at_8_all']),
                                     (2,1,1,.5))

    def test_latest_visible_result_is_selected_and_bound_to_settlement_in_both_orders(self):
        rows,schedule,outcomes=evidence(1)
        older=deepcopy(outcomes[0]); older['captured_at']='2030-04-01T03:30:00Z'
        older['source_sha256']='c'*64
        older['data']['results'][0]['racer_registration_id']='9999'
        for captures in ([older]+outcomes,outcomes+[older],outcomes+deepcopy(outcomes)):
            out=audit(rows,schedule,captures)
            self.assertEqual((score(out)['eligible'],score(out)['hits'],score(out)['issued']), (1,1,1))
            self.assertEqual(out['per_race'][0]['result_captured_at'],'2030-04-01T04:00:00+00:00')

    def test_float_and_boolean_top8_tickets_are_incompatible_without_erasing_race(self):
        for mutation in ('float','bool'):
            with self.subTest(mutation=mutation):
                rows,schedule,outcomes=evidence(1)
                if mutation=='float':
                    rows[0]['top8']=[[float(n) for n in ticket] for ticket in rows[0]['top8']]
                else:
                    rows[0]['top8'][0][0]=True
                out=audit(rows,schedule,outcomes); board=score(out)
                self.assertEqual((board['eligible'],board['hits'],board['issued'],board['missing']), (1,0,0,1))
                item=next(f for f in out['per_forecast'] if f['model_id']==MODELS[0])
                self.assertEqual(item['state'],'NO_PRE_CUTOFF_FORECAST')
                self.assertIn('INCOMPATIBLE_ORIGINAL',item['reason'])

    def test_unknown_pending_special_and_future_are_visible_without_fake_zero_results(self):
        rows,schedule,outcomes=evidence(6)
        outcomes[0]['status']='PENDING'
        outcomes[1]['data']['refund_boats']=[1]
        outcomes[2]['data'].update(status='cancelled',confirmed=True)
        outcomes[3]['data']['top3']=[6,5,4]
        outcomes[4]['captured_at']='2030-04-02T01:00:00Z'
        schedule[5]['cutoff_at']='2030-04-02T03:00:00Z'
        out=audit(rows,schedule,outcomes)
        self.assertEqual((out['eligible_normal_final_races'],out['pending_races'],out['unknown_races'],out['special_races'],out['future_races']), (0,2,1,2,1))
        self.assertEqual(len(out['per_race']),6)
        self.assertIsNone(score(out)['hit_at_8_all'])
        self.assertEqual(out['all_schedule_completion_status'],'INCOMPLETE')
        self.assertEqual(score(out)['target_status'],'INSUFFICIENT_OUTCOMES')

    def test_absent_forecast_requires_real_complete_official_roster_and_finish_order(self):
        for change in ('missing_roster','duplicate_racer','missing_finish','finish_conflict','wrong_identity'):
            with self.subTest(change=change):
                _,schedule,outcomes=evidence(1); data=outcomes[0]['data']
                if change=='missing_roster': data['results'].pop()
                if change=='duplicate_racer': data['results'][1]['racer_registration_id']='4001'
                if change=='missing_finish': del data['results'][0]['finish']
                if change=='finish_conflict': data['results'][0]['finish']=data['results'][1]['finish']
                if change=='wrong_identity': outcomes[0]['body_identity_verified']=False
                out=audit([],schedule,outcomes)
                self.assertEqual(out['eligible_normal_final_races'],0)
                self.assertEqual(out['unknown_races']+out['special_races'],1)

    def test_small_all_win_sample_is_only_observed_not_target_established(self):
        rows,schedule,outcomes=evidence(2); out=audit(rows,schedule,outcomes); board=score(out)
        self.assertEqual(board['target_status'],'MET_OBSERVED_ONLY')
        self.assertLess(board['wilson95']['lower'],.98)
        self.assertFalse(out['target_established']); self.assertFalse(out['auto_promoted'])
        self.assertFalse(board['target_established'])

    def test_learned_and_p0_are_separate_from_five_p1_baselines(self):
        rows,schedule,outcomes=evidence(1)
        p0=deepcopy(rows[0]);p0['stage']='P0'
        learned=deepcopy(rows[0]);learned.update(model_id=OBSERVED[0],variant='LEARNED_SHADOW',training_sha256='a'*64)
        out=audit(rows+[p0],schedule,outcomes,learned_rows=[learned])
        self.assertEqual(len(out['scoreboard']),8)
        self.assertEqual(score(out,OBSERVED[0],variant='LEARNED_SHADOW')['hits'],1)
        self.assertEqual(score(out,OBSERVED[1],variant='LEARNED_SHADOW')['missing'],1)
        self.assertEqual(score(out,stage='P0')['hits'],1)

    def test_no_observations_argument_preserves_legacy_output_and_inputs(self):
        rows,schedule,outcomes=evidence(1); before=deepcopy((rows,schedule,outcomes))
        legacy=learning.coverage_audit(rows,schedule,now=NOW)
        self.assertNotIn('all_race_top8_target',legacy)
        extended=learning.coverage_audit(rows,schedule,now=NOW,observations=outcomes)
        self.assertEqual({k:v for k,v in extended.items() if k!='all_race_top8_target'},legacy)
        self.assertEqual((rows,schedule,outcomes),before)

if __name__=='__main__': unittest.main()
