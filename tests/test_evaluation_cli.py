"""CLI subprocess tests with fictional past races and actual operation clocks."""
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_evaluation_experiment import plan,payload,labels
from race_ai.actions_contract import digest,canonical

ROOT=Path(__file__).resolve().parents[1]


class EvaluationCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='evaluation-cli-fictional-')
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.registry=self.base/'registry'
        self.p=json.loads(json.dumps(plan()).replace('2030-','2000-'))
        self.contexts,self.outputs=payload(self.p)
        for row in self.outputs:row['generated_at']='2000-01-06T00:00:00Z'
        self.labels=json.loads(json.dumps(labels()).replace('2030-','2000-'))
        self.files={name:self.write(name,value) for name,value in (
            ('plan',self.p),('contexts',self.contexts),('outputs',self.outputs),('labels',self.labels),('empty',[]))}

    def write(self,name,value):
        path=self.base/(name+'.json')
        path.write_text(json.dumps(value,indent=2),encoding='utf-8')
        return path

    def call(self,operation,*arguments,ok=True):
        result=subprocess.run([sys.executable,'-B','-m','race_ai.evaluation_cli',operation,
            '--root',str(self.registry),'--experiment','fictional-1',*map(str,arguments)],
            cwd=ROOT,capture_output=True,text=True,timeout=15)
        if ok:
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stderr,'')
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(result.stdout,'')
        self.assertNotIn('Traceback',result.stderr)
        self.assertNotIn(str(self.base),result.stderr)
        self.assertNotIn('SENSITIVE',result.stderr)
        return json.loads(result.stderr)

    def register(self):
        return self.call('register','--plan',self.files['plan'],'--expected-plan-sha',digest(self.p))

    def seal(self):
        self.register()
        return self.call('seal','--contexts',self.files['contexts'],'--outputs',self.files['outputs'],
                         '--expected-plan-sha',digest(self.p))

    def reveal(self,empty=False):
        sealed=self.seal()
        reported=self.call('reveal','--labels',self.files['empty' if empty else 'labels'],
                          '--expected-seal-sha',sealed['seal_sha256'])
        return sealed,reported

    def test_register_seal_reveal_report_across_fresh_processes(self):
        before=datetime.now(timezone.utc);sealed,report=self.reveal();after=datetime.now(timezone.utc)
        stored=json.loads((self.registry/'fictional-1/predictions.json').read_bytes())
        self.assertLessEqual(before,datetime.fromisoformat(stored['sealed_at']))
        self.assertLessEqual(datetime.fromisoformat(stored['sealed_at']),after)
        self.assertEqual(report['model_rows'],2)
        self.assertEqual(report['cohort_races'],4)
        self.assertNotIn('winning_triples',json.dumps(report))
        self.assertNotIn('top8',json.dumps(report))
        self.files['labels'].unlink()
        recovered=self.call('report','--expected-seal-sha',sealed['seal_sha256'],
                            '--expected-report-sha',report['report_sha256'])
        self.assertEqual(recovered['report_sha256'],report['report_sha256'])
        self.assertIsNone(recovered['through_batch'])

    def test_wrong_hash_fails_before_label_file_is_opened(self):
        self.seal()
        missing=self.base/'SENSITIVE-missing.json'
        result=self.call('reveal','--labels',missing,'--expected-seal-sha','0'*64,ok=False)
        self.assertEqual(result['error'],'JOURNAL_REJECTED')
        self.assertFalse((self.registry/'fictional-1/reveal-intent.json').exists())

    def test_register_hash_mismatch_and_overwrites_are_rejected(self):
        result=self.call('register','--plan',self.files['plan'],'--expected-plan-sha','0'*64,ok=False)
        self.assertEqual(result['error'],'EXPECTED_DIGEST_MISMATCH')
        self.assertFalse(self.registry.exists())
        self.register()
        before=(self.registry/'fictional-1/plan.json').read_bytes()
        self.call('register','--plan',self.files['plan'],'--expected-plan-sha',digest(self.p),ok=False)
        self.assertEqual((self.registry/'fictional-1/plan.json').read_bytes(),before)

    def test_normal_json_canonicalizes_and_duplicate_or_nonfinite_reject(self):
        for content in ('{"duplicate":1,"duplicate":2}', '{"SENSITIVE":NaN}', '{"SENSITIVE":1e999}'):
            self.files['plan'].write_text(content,encoding='utf-8')
            self.call('register','--plan',self.files['plan'],'--expected-plan-sha',digest(self.p),ok=False)
            self.assertFalse(self.registry.exists())
        self.write('plan',self.p);self.register()
        self.assertEqual((self.registry/'fictional-1/plan.json').read_text(encoding='utf-8'),canonical(self.p)+'\n')

    def test_missing_or_oversized_input_is_sanitized(self):
        result=self.call('register','--plan',self.base/'SENSITIVE-missing.json','--expected-plan-sha',digest(self.p),ok=False)
        self.assertEqual(result['error'],'FILE_NOT_FOUND')
        huge=self.base/'huge.json'
        with huge.open('wb') as stream:stream.truncate(100_000_001)
        result=self.call('register','--plan',huge,'--expected-plan-sha',digest(self.p),ok=False)
        self.assertEqual(result['error'],'INPUT_TOO_LARGE')

    def test_failed_reveal_does_not_allow_restart_with_changed_labels(self):
        sealed=self.seal()
        self.files['labels'].write_text('{"SENSITIVE":',encoding='utf-8')
        first=self.call('reveal','--labels',self.files['labels'],'--expected-seal-sha',sealed['seal_sha256'],ok=False)
        self.assertEqual(first['error'],'INPUT_JSON_INVALID')
        self.assertTrue((self.registry/'fictional-1/reveal-intent.json').exists())
        self.write('labels',self.labels)
        second=self.call('reveal','--labels',self.files['labels'],'--expected-seal-sha',sealed['seal_sha256'],ok=False)
        self.assertIn(second['error'],('JOURNAL_REJECTED','FILE_ALREADY_EXISTS'))

    def test_delayed_results_append_without_rewriting_predictions(self):
        sealed,report=self.reveal(empty=True)
        predictions=(self.registry/'fictional-1/predictions.json').read_bytes()
        appended=self.call('append','--labels',self.files['labels'],'--batch-number','1',
            '--expected-seal-sha',sealed['seal_sha256'],'--expected-report-sha',report['report_sha256'])
        self.assertNotEqual(appended['report_sha256'],report['report_sha256'])
        self.assertEqual(appended['batch_number'],1)
        self.assertEqual((self.registry/'fictional-1/predictions.json').read_bytes(),predictions)
        self.assertEqual((self.registry/'fictional-1/labels.json').read_text(),'[]\n')
        bad=self.call('append','--labels',self.base/'SENSITIVE-unread.json','--batch-number','2',
            '--expected-seal-sha',sealed['seal_sha256'],'--expected-report-sha',report['report_sha256'],ok=False)
        self.assertEqual(bad['error'],'JOURNAL_REJECTED')

    def test_report_explicit_recovery_after_pending_append(self):
        sealed,report=self.reveal(empty=True)
        self.files['labels'].write_text('{',encoding='utf-8')
        self.call('append','--labels',self.files['labels'],'--batch-number','1',
            '--expected-seal-sha',sealed['seal_sha256'],'--expected-report-sha',report['report_sha256'],ok=False)
        self.call('report','--expected-seal-sha',sealed['seal_sha256'],ok=False)
        recovered=self.call('report','--expected-seal-sha',sealed['seal_sha256'],'--through-batch','0',
                            '--expected-report-sha',report['report_sha256'])
        self.assertEqual(recovered['through_batch'],0)
        self.assertEqual(recovered['report_sha256'],report['report_sha256'])

    def test_report_export_is_exclusive_and_hash_checked(self):
        sealed,report=self.reveal()
        out=self.base/'private-report.json'
        self.call('report','--expected-seal-sha',sealed['seal_sha256'],'--expected-report-sha','0'*64,
                  '--output',out,ok=False)
        self.assertFalse(out.exists())
        self.call('report','--expected-seal-sha',sealed['seal_sha256'],'--expected-report-sha',report['report_sha256'],
                  '--output',out)
        original=out.read_bytes();self.assertEqual(digest(json.loads(original)),report['report_sha256'])
        self.call('report','--expected-seal-sha',sealed['seal_sha256'],'--output',out,ok=False)
        self.assertEqual(out.read_bytes(),original)

    def test_arbitrary_now_flag_is_unavailable(self):
        result=self.call('register','--plan',self.files['plan'],'--expected-plan-sha',digest(self.p),
                         '--now','2000-01-01T00:00:00Z',ok=False)
        self.assertEqual(result['error'],'INVALID_ARGUMENTS')

    def test_seal_cannot_overwrite_saved_predictions(self):
        self.seal()
        path=self.registry/'fictional-1/predictions.json';original=path.read_bytes()
        self.call('seal','--contexts',self.files['contexts'],'--outputs',self.files['outputs'],
                  '--expected-plan-sha',digest(self.p),ok=False)
        self.assertEqual(path.read_bytes(),original)

    def test_register_rejects_future_declaration_using_real_clock(self):
        from datetime import timedelta
        self.p['declared_at']=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
        self.write('plan',self.p)
        result=self.call('register','--plan',self.files['plan'],'--expected-plan-sha',digest(self.p),ok=False)
        self.assertEqual(result['error'],'PLAN_DECLARED_IN_FUTURE')
        self.assertFalse(self.registry.exists())

    def test_huge_allowed_feature_integer_has_safe_error_without_seal_or_label_read(self):
        self.register()
        self.contexts[0]['features']['historical_rating']=[10**1000]
        for output in self.outputs:
            if output['race_id']==self.contexts[0]['race_id']:
                output['context_sha256']=digest(self.contexts[0])
        self.write('contexts',self.contexts);self.write('outputs',self.outputs)
        # No result source exists during prediction sealing.
        self.files['labels'].unlink()
        result=self.call('seal','--contexts',self.files['contexts'],'--outputs',self.files['outputs'],
                         '--expected-plan-sha',digest(self.p),ok=False)
        self.assertEqual(result['error'],'JOURNAL_REJECTED')
        for name in ('predictions.json','reveal-intent.json','labels.json'):
            self.assertFalse((self.registry/'fictional-1'/name).exists())


if __name__=='__main__':unittest.main()
