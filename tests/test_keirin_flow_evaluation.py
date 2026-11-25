"""The forward-score adapter reuses the existing development PDCA authority."""
from copy import deepcopy
import unittest

from race_ai.keirin_flow_evaluation import summarize_flow
from race_ai import keirin_form_fall_blind_pdca as pdca

RID = '209901016201'
SHA = 'a' * 64
FROZEN = '2099-01-01T10:00:00+09:00'
CUTOFF = '2099-01-01T12:00:00+09:00'
AFTER = '2099-01-01T13:00:00+09:00'


def flow_path():
    return {**{phase:[1,2,3] for phase in ('INITIAL','BELL','FINAL_HOME','FINAL_BACK','FOURTH_CORNER')},
            'INITIATIVE':1, 'ATTACK_ORDER':[1,3,2]}


def observation(aspect='INITIATIVE', value=2, *, source='video', complete=True):
    return dict(race_id=RID, aspect=aspect, observed=value, source=source, complete=complete,
                receipt=dict(reference='synthetic:source', recorded_at=AFTER,
                             sha256=None if source in ('user','estimate') else 'b'*64))


def packet(facts=None):
    return dict(schema='KEIRIN_FLOW_OBSERVATIONS_V1', forecast_sha256=SHA, recorded_at=AFTER,
                races=[dict(race_id=RID, observations=[observation()] if facts is None else facts)])


class FlowAdapterTests(unittest.TestCase):
    def summarize(self, *, facts=None, normalized_at=None, flow=None, winners=None):
        path = flow_path() if flow is None else flow
        predictions = dict(races=[dict(race_id=RID, cutoff_at=CUTOFF, points=1,
                                     published=[[1,2,3]], trial=[[1,2,3]],
                                     flow={side:path for side in ('published','trial')})])
        receipt = dict(frozen_at=FROZEN)
        if normalized_at:
            receipt.update(normalized_at=normalized_at, timestamp_semantics='original_ticket_forecast_freeze')
        return summarize_flow(predictions, packet(facts), forecast_sha256=SHA,
                              receipt=receipt, orders_by_race={RID:[1,2,3] if winners is None else winners},
                              starters_by_race={RID:{1,2,3}})

    def test_registered_hit_and_confirmed_flow_disagreement_are_b(self):
        out = self.summarize()
        self.assertEqual(out['published']['categories'], {'A':0,'B':1,'C':0,'D':0,'E':0})
        self.assertFalse(out['independent_source_authentication_performed'])

    def test_after_cutoff_normalization_does_not_admit_reconstructed_flow(self):
        facts = [observation(aspect, value) for aspect,value in flow_path().items()]
        out = self.summarize(facts=facts, normalized_at=AFTER)
        for side in ('published','trial'):
            self.assertEqual(out[side]['categories'], dict.fromkeys('ABCDE',0))
            self.assertEqual(out[side]['origin_not_admitted'], 1)
        out = self.summarize(facts=facts, normalized_at='2099-01-01T11:00:00+09:00')
        self.assertEqual(out['published']['categories']['A'], 1)

    def test_compatible_complete_and_partial_attack_evidence_count_once(self):
        facts = [observation(aspect,value) for aspect,value in flow_path().items()]
        facts.append(observation('ATTACK_ORDER',[1,3],source='article',complete=False))
        out = self.summarize(facts=facts)
        self.assertEqual(out['published']['categories']['A'],1)
        self.assertEqual(out['published']['confirmed_metrics']['ATTACK_ORDER']['compared'],1)
        facts[-1]['observed']=[3,1]
        out = self.summarize(facts=facts)
        self.assertEqual(out['published']['categories']['E'],1)
        self.assertEqual(out['published']['confirmed_metrics']['ATTACK_ORDER']['conflicting'],1)

    def test_front_prefix_and_full_initial_order_share_one_conflict_domain(self):
        facts = [observation(aspect,value) for aspect,value in flow_path().items()]
        facts.append(observation('INITIAL',[3],source='article',complete=False))
        out = self.summarize(facts=facts)
        self.assertEqual(out['published']['categories']['E'],1)
        self.assertEqual(out['published']['confirmed_metrics']['INITIAL']['conflicting'],1)

    def test_user_provisional_ai_excluded_and_missing_original_is_e(self):
        user = self.summarize(facts=[observation(source='user')])
        self.assertEqual(user['published']['categories']['E'],1)
        self.assertEqual(user['published']['provisional_categories']['B'],1)
        ai = self.summarize(facts=[observation(source='estimate')])
        self.assertEqual(ai['published']['provisional_categories']['E'],1)
        missing = self.summarize(flow={})
        self.assertEqual(missing['published']['categories']['E'],1)
        self.assertEqual(missing['published']['missing_original_flow'],1)

    def test_source_chronology_and_digest_are_checked_without_mutating_inputs(self):
        facts = [observation()]
        saved=deepcopy(facts)
        self.summarize(facts=facts)
        self.assertEqual(facts,saved)
        for field,value in [('recorded_at',FROZEN),('recorded_at','2099-01-02T00:00:00Z'),('sha256',None)]:
            changed=deepcopy(facts);changed[0]['receipt'][field]=value
            with self.subTest(field=field,value=value), self.assertRaises(ValueError):
                self.summarize(facts=changed)

    def test_empty_partial_attack_sequence_has_no_order_evidence(self):
        for partial in ([],[1]):
            with self.subTest(partial=partial), self.assertRaises(ValueError):
                self.summarize(facts=[observation('ATTACK_ORDER',partial,complete=False)])

    def test_conversation_reference_uses_existing_pdca_and_has_no_formal_origin(self):
        forecast=dict(scope='conversation_reference',race_id=RID,tickets=[[1,2,3]],flow={'INITIATIVE':1})
        out=pdca.compare_race_development(race_id=RID,starters=[1,2,3],forecast=forecast,
            order=dict(race_id=RID,winning_triples=[[1,2,3]]),observations=[observation(source='user')],
            verify_forecast=lambda _:False,verify_order=lambda _:True,verify_observation=lambda _:False)
        self.assertFalse(out['placing']['formal'])
        self.assertIsNone(out['grade'])
        self.assertEqual(out['reference_grade'],'B')


if __name__=='__main__':
    unittest.main()
