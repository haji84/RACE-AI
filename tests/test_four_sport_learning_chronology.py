"""Invented complete inputs exercise chronological admission, not live accuracy."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import unittest

from race_ai import comprehensive_four_sport_models as facts
from race_ai import four_sport_learning as learning

TRAIN_END='2030-01-06T23:59:00+00:00'
VALID_END='2030-01-08T23:59:00+00:00'
TEST_END='2030-01-10T23:59:00+00:00'


def example(day):
    cutoff=datetime(2030,1,day,10,tzinfo=timezone.utc)
    asof=cutoff-timedelta(minutes=15)
    def observation(value):
        return dict(value=value,published_at=(asof-timedelta(minutes=1)).isoformat(),
            captured_at=asof.isoformat(),source_ref='synthetic://invented-input',
            source_rights_ref='fixture-only',sample_n=8,transform_id='fixture-unit')
    participants=[]
    for number in range(1,7):
        participants.append(dict(number=number,identity='invented-'+str(number),draw=number,
            style='front' if number%2 else 'closer',group_id=None,features={
                name:observation(.1+number*.1) for name in
                facts.COMMON_REQUIRED+facts.SPORT_REQUIRED['boat']}))
    env={name:observation(1.0 if name=='wind_mps' else 20.0 if name=='air_temp_c'
        else 50.0 if name=='humidity_pct' else .1)
        for name in facts.ENV_COMMON+facts.ENV_SPORT['boat']}
    snap=dict(schema=facts.SCHEMA,scope=facts.SYNTHETIC,
        race=dict(race_id='invented-boat-'+str(day),sport='boat',venue='fixture',
            event_date_jst=cutoff.astimezone(facts.JST).date().isoformat(),
            sales_cutoff_at=cutoff.isoformat(),as_of=asof.isoformat(),distance_m=1800,
            surface='water',race_kind='fixture',race_revision=1),participants=participants,
        environment=env)
    result=dict(race_id=snap['race']['race_id'],status='settled',ordered_top3=[6,5,4],
        published_at=(cutoff+timedelta(minutes=1)).isoformat(),
        captured_at=(cutoff+timedelta(minutes=2)).isoformat(),
        source_ref='synthetic://invented-result',source_rights_ref='fixture-only')
    return dict(snapshot=snap,result=result)


def set_asof(row,at):
    row['snapshot']['race']['as_of']=at
    for p in row['snapshot']['participants']:
        for obs in p['features'].values():obs.update(published_at=at,captured_at=at)
    for obs in row['snapshot']['environment'].values():obs.update(published_at=at,captured_at=at)


def fit(rows):
    return learning.fit_chronological(rows,sport='boat',train_end_at=TRAIN_END,
        validation_end_at=VALID_END,test_end_at=TEST_END,epochs=1)


class ChronologicalLearningTests(unittest.TestCase):
    def test_validation_input_must_follow_training_end_even_if_cutoff_is_later(self):
        for at in (TRAIN_END,'2030-01-06T23:58:00+00:00'):
            with self.subTest(at=at):
                rows=[example(day) for day in range(1,11)];set_asof(rows[6],at)
                with self.assertRaisesRegex(facts.ModelInputError,'validation snapshot must follow training boundary'):
                    fit(rows)

    def test_final_test_input_must_follow_validation_end(self):
        for at in (VALID_END,'2030-01-07T23:59:00+00:00'):
            with self.subTest(at=at):
                rows=[example(day) for day in range(1,11)];set_asof(rows[8],at)
                with self.assertRaisesRegex(facts.ModelInputError,'test snapshot must follow validation boundary'):
                    fit(rows)

    def test_separated_cohorts_admit_and_do_not_mutate_inputs(self):
        rows=[example(day) for day in range(1,11)];original=deepcopy(rows)
        artifact=fit(rows)
        self.assertEqual(artifact['trained_examples'],6)
        self.assertEqual(artifact['validation_diagnostics']['n'],2)
        self.assertEqual(artifact['holdout_diagnostics']['n'],2)
        self.assertEqual(rows,original)
        self.assertFalse(artifact['official_model_approved'])

    def test_one_microsecond_after_each_boundary_is_admitted(self):
        rows=[example(day) for day in range(1,11)]
        set_asof(rows[6],'2030-01-06T23:59:00.000001+00:00')
        set_asof(rows[8],'2030-01-08T23:59:00.000001+00:00')
        self.assertEqual(fit(rows)['trained_examples'],6)

    def test_validation_labels_do_not_change_training_weights(self):
        rows=[example(day) for day in range(1,11)]
        other=deepcopy(rows)
        for row in other[6:]:row['result']['ordered_top3']=[1,2,3]
        self.assertEqual(fit(rows)['weights'],fit(other)['weights'])


if __name__=='__main__':unittest.main()
