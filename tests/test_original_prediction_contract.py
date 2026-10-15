"""Synthetic pinned original timing research; no media or external requests."""
import copy
from datetime import timedelta
import importlib
import json
import math
from pathlib import Path
import subprocess
import sys
import unittest

from tests.test_exhibition_contract import fixture as preview_fixture,NOW,PRE_RACE,sha
from tests.test_boatcast_original import original,companion
from race_ai.boatcast_original import parse_original,endpoint
from web.race_contract import stamp

ROOT=Path(__file__).resolve().parents[1]


def fixture(unequal=False):
    baseline,bundle,race=preview_fixture()
    first=original().replace(b'36.42',b'35.42',1) if unequal else original()
    capture=PRE_RACE+timedelta(seconds=3)
    observation=parse_original(first,companion().replace(b'6.81',b'6.92'),race=race,
        source_url=endpoint(race['race_id'],'original'),captured_at=stamp(capture),
        companion_source_url=endpoint(race['race_id'],'standard'),companion_captured_at=stamp(capture),now=NOW)
    receipt=dict(schema_version=1,request_id='223456-1',observation=observation,
        runner_saved_at=stamp(capture+timedelta(seconds=1)),cloud_saved_at=stamp(capture+timedelta(seconds=2)),
        cloud_eligible_pre_race=True,program_identity_sha256=observation['program_identity_sha256'])
    return baseline,bundle,receipt,race


class OriginalPredictionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.c=importlib.import_module('web.original_prediction_contract')
            cls.o=importlib.import_module('web.original_exhibition_contract')
        except ModuleNotFoundError:cls.c=cls.o=None

    def setUp(self):
        self.assertIsNotNone(self.c,'separate original prediction contract required')
        self.baseline,self.bundle,self.original,self.race=fixture()

    def build(self):return self.c.build_original_prediction_bundle(self.baseline,self.bundle,self.original,self.race,NOW)

    def test_complete_equal_metrics_preserve_baseline_and_all_distribution_deltas(self):
        post=self.build();base=self.baseline['snapshot']['models'][1]
        self.assertEqual(post['variant'],'original-v1')
        self.assertEqual(post['model']['model_id'],'official-display-original-pl')
        self.assertEqual(post['model']['parameters'],dict(display_coefficient_per_second=1.0,
            lap_coefficient_per_second=.05,turn_coefficient_per_second=.20,straight_coefficient_per_second=.20,
            log_strength_min=-20.0,log_strength_max=20.0,rating_floor=.01))
        self.assertEqual(len(post['model']['triples']),120);self.assertEqual(len(post['model']['marginals']),6)
        self.assertAlmostEqual(math.fsum(x['probability'] for x in post['model']['triples']),1,places=13)
        self.assertAlmostEqual(math.fsum(x['delta_probability'] for x in post['deltas']['triples']),0,places=13)
        self.assertAlmostEqual(post['model']['triples'][0]['probability'],base['triples'][0]['probability'],places=14)
        self.assertEqual(post['feature_status']['original_exhibition'],dict(status='AVAILABLE',used=True,reason=None))
        self.assertFalse(post['feature_status']['exhibition_video']['used'])
        self.assertEqual(post['purchase_recommendations'],[]);self.assertEqual(post['purchase_decision'],'skip')

    def test_unequal_original_lap_contribution_matches_independent_arithmetic(self):
        self.baseline,self.bundle,self.original,self.race=fixture(True);post=self.build();boat=post['boats'][0]
        self.assertAlmostEqual(boat['contributions']['lap_s']['delta_seconds'],5/6,places=12)
        self.assertAlmostEqual(boat['contributions']['lap_s']['log_strength_contribution'],1/24,places=12)
        self.assertAlmostEqual(boat['adjusted_strength'],boat['base_strength']*math.exp(1/24),places=12)
        self.assertGreater(post['deltas']['marginals'][0]['first']['delta_probability'],0)

    def test_full24_coverage_and_exact_beforeinfo_display_match_required(self):
        for kind in ['missing','different']:
            self.baseline,self.bundle,self.original,self.race=fixture()
            observation=self.original['observation'];boat=observation['boats'][0]
            if kind=='missing':boat['original_times']['turn_s']=None;boat['missing_reasons']['turn_s']='SOURCE_NOT_PUBLISHED';observation['status']='PARTIAL'
            else:boat['display_time_s']=6.91
            observation['snapshot_id']=sha({k:v for k,v in observation.items() if k!='snapshot_id'})
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'ORIGINAL_TIMINGS_INCOMPLETE|ORIGINAL_DISPLAY_CONFLICT'):self.build()

    def test_missing_or_late_original_receipt_cannot_become_forecast(self):
        with self.assertRaisesRegex(ValueError,'ORIGINAL_NOT_OBTAINED'):
            self.c.build_original_prediction_bundle(self.baseline,self.bundle,None,self.race,NOW)
        self.original['cloud_eligible_pre_race']=False
        with self.assertRaises(ValueError):self.build()
        self.original['cloud_eligible_pre_race']=True;self.original['cloud_saved_at']=self.race['closed_at']
        with self.assertRaises(ValueError):self.build()

    def test_original_link_pins_two_exact_sources_and_immutable_receipt(self):
        post=self.build();link=post['original_link']
        self.assertEqual(link['request_id'],'223456-1');self.assertEqual(link['receipt_sha256'],sha(self.original))
        self.assertEqual(link['snapshot_id'],self.original['observation']['snapshot_id'])
        self.assertEqual(link['sources'],self.original['observation']['sources'])
        self.assertFalse(self.original['observation']['body_date_verified'])
        self.assertNotEqual(post['b_program_sha256'],post['program_identity_sha256'])

    def test_source_receipt_runner_cloud_identity_and_extra_fields_checked(self):
        mutations=[lambda r:r.update(runner_saved_at=stamp(PRE_RACE)),lambda r:r.update(cloud_saved_at=stamp(PRE_RACE)),
            lambda r:r.update(program_identity_sha256='b'*64),lambda r:r.update(extra=True),
            lambda r:r['observation']['sources'][0].update(source_url='https://attacker.example/'),
            lambda r:r['observation']['boats'][0].update(racer_registration_id='4999')]
        for mutation in mutations:
            self.baseline,self.bundle,self.original,self.race=fixture();mutation(self.original)
            with self.subTest(mutation=repr(mutation)),self.assertRaises(ValueError):self.build()

    def test_rehashed_contribution_parameter_link_and_missing_video_tampering_rejected(self):
        mutations=[lambda p:p['boats'][0]['contributions']['lap_s'].update(log_strength_contribution=2),
            lambda p:p['model']['parameters'].update(turn_coefficient_per_second=1),
            lambda p:p['original_link'].update(request_id='223457-1'),
            lambda p:p['feature_status']['exhibition_video'].update(used=True)]
        for mutation in mutations:
            post=self.build();mutation(post);post['snapshot_id']=sha({k:v for k,v in post.items() if k!='snapshot_id'})
            with self.assertRaises(ValueError):self.c.validate_original_prediction_bundle(post,self.baseline,self.bundle['records'][0],self.original,self.race,NOW)

    def test_pinned_replay_after_close_preserves_inputs_and_detaches_sources(self):
        original=copy.deepcopy((self.baseline,self.bundle,self.original,self.race));post=self.build()
        replay=self.c.validate_original_prediction_bundle(post,self.baseline,self.bundle['records'][0],self.original,
            self.race,NOW+timedelta(hours=2))
        self.assertEqual(post,replay);post['original_link']['sources'][0]['source_sha256']='b'*64
        self.assertEqual((self.baseline,self.bundle,self.original,self.race),original)

    def test_standalone_original_validator_and_model_need_no_race_ai_or_api(self):
        script='''import sys,json,datetime
sys.path.insert(0,sys.argv[1]);import original_prediction_contract as p
d=json.load(sys.stdin);r=p.build_original_prediction_bundle(d['b'],d['u'],d['o'],d['r'],datetime.datetime.fromisoformat(d['now']))
assert not any(k.startswith(('race_ai','api.','cv2','sqlite3')) for k in sys.modules)
print(r['variant'])'''
        run=subprocess.run([sys.executable,'-I','-S','-c',script,str(ROOT/'web')],input=json.dumps(dict(b=self.baseline,u=self.bundle,o=self.original,r=self.race,now=NOW.isoformat())),text=True,encoding='utf-8',capture_output=True)
        self.assertEqual(run.returncode,0,run.stderr);self.assertEqual(run.stdout.strip(),'original-v1')


if __name__=='__main__':unittest.main()
