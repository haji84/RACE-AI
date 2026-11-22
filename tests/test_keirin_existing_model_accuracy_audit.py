"""Stored existing-A shadow comparisons, invented records, no source requests."""
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from race_ai import keirin_existing_model_accuracy as learning
from race_ai import keirin_nationwide_auto_generator as original
from scripts.keirin_note_collect_results import fact_digest
from tests.test_keirin_existing_model_accuracy import row
from scripts import keirin_existing_model_accuracy_audit as audit

NOW=datetime(2030,1,16,5,tzinfo=timezone.utc)
SAVED='2030-01-16T01:01:00+00:00'


class FrozenAccuracyAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifact=learning.fit_candidates([row(i) for i in range(1,7)],
            [row(7),row(8)],clock=lambda:datetime(2030,1,15,tzinfo=timezone.utc))

    def case(self):
        r=row(16,winning=[7,6,5]);at=datetime(2030,1,16,1,tzinfo=timezone.utc)
        forecast=learning.forecast_candidate(r['snapshot'],self.artifact,clock=lambda:at,
            expected_artifact_sha256=self.artifact['artifact_sha256'])
        return dict(input=r['snapshot'],forecast=forecast),r['result']

    def compare(self,forecasts,results,**kwargs):
        return audit.compare_locked(artifact=self.artifact,forecasts=forecasts,
            latest_results=results,expected_candidate_sha256=kwargs.pop('expected',self.artifact['artifact_sha256']),
            expected_forecast_sha256=kwargs.pop('forecast_sha',original.digest(forecasts)),
            git_observed_at=kwargs.pop('saved',SAVED),clock=lambda:NOW,**kwargs)

    def test_same_eight_ticket_budget_uses_existing_scorer_and_fixed_cohort(self):
        forecast,result=self.case();report=self.compare([forecast],[result])
        self.assertEqual(report['expected'],1)
        self.assertEqual(report['matched'],1)
        self.assertEqual(report['baseline_hits8'],0)
        self.assertEqual(report['candidate_hits8'],1)
        self.assertEqual(report['candidate_only_hits'],1)
        self.assertIsNone(report['statistical_improvement_supported'])
        self.assertFalse(report['formal_model_admission'])

    def test_pending_and_held_results_never_become_misses(self):
        forecast,result=self.case()
        pending=self.compare([forecast],[])
        self.assertEqual(pending['pending'],1);self.assertIsNone(pending['baseline_hit_at_8'])
        result.update(state='HOLD_RESULT_SOURCE_UNAVAILABLE',winning_triple=None,
            payout_per_100yen=None,provider_receipts=[])
        result['observation_sha256']=fact_digest(result)
        held=self.compare([forecast],[result])
        self.assertEqual(held['held'],1);self.assertEqual(held['matched'],0)

    def test_duplicate_forecasts_or_unresolved_result_revisions_are_rejected(self):
        forecast,result=self.case()
        with self.assertRaises(ValueError):self.compare([forecast,forecast],[result])
        with self.assertRaises(ValueError):self.compare([forecast],[result,result])

    def test_future_or_pre_cutoff_result_receipts_are_rejected(self):
        forecast,result=self.case()
        for receipt in result['provider_receipts']:receipt['observed_at']=forecast['input']['as_of']
        result['observation_sha256']=fact_digest(result)
        with self.assertRaises(ValueError):self.compare([forecast],[result])
        forecast,result=self.case();result['captured_at']='2030-02-01T00:00:00+00:00'
        with self.assertRaises(ValueError):self.compare([forecast],[result])

    def test_saved_time_after_cutoff_or_wrong_locked_candidate_is_rejected(self):
        forecast,result=self.case()
        with self.assertRaises(ValueError):self.compare([forecast],[result],saved='2030-01-16T03:00:00+00:00')
        with self.assertRaises(ValueError):self.compare([forecast],[result],expected='e'*64)

    def test_rehashed_control_tickets_cannot_change_the_original_A_comparison(self):
        forecast,result=self.case();forecast=deepcopy(forecast)
        forecast['forecast']['baseline_ranked_tickets'][0]=[7,6,5]
        forecast['forecast']['forecast_sha256']=original.digest({k:v for k,v in forecast['forecast'].items() if k!='forecast_sha256'})
        with self.assertRaises(ValueError):self.compare([forecast],[result])

    def test_inputs_and_outputs_do_not_expose_raw_tickets_or_results(self):
        forecast,result=self.case();before=deepcopy((forecast,result))
        report=self.compare([forecast],[result]);text=json.dumps(report)
        self.assertEqual((forecast,result),before)
        self.assertNotIn('ranked_tickets',text);self.assertNotIn('winning_triple',text)
        self.assertNotIn(forecast['input']['race_id'],text)

    def test_post_result_cohort_subset_does_not_match_the_published_forecast_list(self):
        first,result=self.case();second=deepcopy(first)
        second['input']['race_id']='203001169802'
        second['forecast']=learning.forecast_candidate(second['input'],self.artifact,
            clock=lambda:datetime(2030,1,16,1,tzinfo=timezone.utc))
        expected=original.digest([first,second])
        with self.assertRaises(ValueError):self.compare([first],[result],forecast_sha=expected)

    def test_scope_source_clock_and_pre_training_inputs_cannot_be_rehashed_into_a_shadow(self):
        for field,value in [('schema','invalid'),('scope','invalid'),
                ('source_as_of','2030-01-15T00:00:00+00:00'),
                ('published_cutoff_at','2030-01-17T03:00:00+00:00')]:
            with self.subTest(field=field):
                forecast,result=self.case();forecast['forecast'][field]=value
                forecast['forecast']['forecast_sha256']=original.digest({k:v for k,v in forecast['forecast'].items() if k!='forecast_sha256'})
                with self.assertRaises(ValueError):self.compare([forecast],[result])
        forecast,result=self.case();old='2030-01-01T00:00:00+00:00'
        forecast['input']['as_of']=old;forecast['input']['cutoff_source']['captured_at']=old
        for source in forecast['input']['source_pages']:source['captured_at']=old
        forecast['forecast'].update(source_as_of=old,source_facts_sha256=original.digest(forecast['input']))
        forecast['forecast']['forecast_sha256']=original.digest({k:v for k,v in forecast['forecast'].items() if k!='forecast_sha256'})
        with self.assertRaises(ValueError):self.compare([forecast],[result])

    def test_cli_accepts_private_inputs_and_prints_counts_only_without_overwriting(self):
        forecast,result=self.case()
        with TemporaryDirectory() as tmp:
            root=Path(tmp);root.chmod(0o700)
            paths=[]
            for name,value in [('artifact',self.artifact),('forecasts',[forecast]),('results',[result])]:
                p=root/(name+'.json');p.write_text(json.dumps(value));p.chmod(0o600);paths.append(p)
            out=root/'report';out.mkdir(mode=0o700)
            code="from datetime import datetime,timezone;import sys;from scripts import keirin_existing_model_accuracy_audit as m;raise SystemExit(m.main(sys.argv[1:],clock=lambda:datetime(2030,1,16,5,tzinfo=timezone.utc)))"
            args=[sys.executable,'-c',code,
                '--artifact',str(paths[0]),'--forecasts',str(paths[1]),'--results',str(paths[2]),
                '--expected-candidate-sha256',self.artifact['artifact_sha256'],
                '--expected-forecast-sha256',original.digest([forecast]),
                '--git-observed-at',SAVED,'--private-root',str(out)]
            p=subprocess.run(args,cwd=Path(__file__).resolve().parents[1],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            self.assertEqual(p.returncode,0,p.stderr.decode());self.assertEqual(json.loads(p.stdout)['matched'],1)
            self.assertEqual((out/'report.json').stat().st_mode&0o777,0o600)
            p=subprocess.run(args,cwd=Path(__file__).resolve().parents[1],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            self.assertEqual(p.returncode,2)
            paths[0].chmod(0o644)
            args[-1]=str(root/'other')
            p=subprocess.run(args,cwd=Path(__file__).resolve().parents[1],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            self.assertEqual(p.returncode,2)


if __name__=='__main__':unittest.main()
