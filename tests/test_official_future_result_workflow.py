"""Existing job shell routing only; no keys, source, GitHub or model execution."""
from pathlib import Path
import subprocess
import unittest

from tests import test_official_future_source_workflow as fixtures
from tests.test_official_future_source_workflow import ident,script,MANIFEST,RESULT_MODULE,UPLOAD


class FutureResultWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.FutureSourceWorkflowTests('runTest');self.fixture.setUp()
        self.steps=self.fixture.steps;self.text=self.fixture.text;self.job=self.fixture.job
    def execute(self,step,**kwargs):return self.fixture.execute(step,scope='official-result',**kwargs)
    def test_v2_uses_the_same_keyless_result_scope_and_purpose_gate(self):
        step=ident(self.steps,'future_source_scope')
        result,calls,values,_,_=self.execute(step,schema='RACE_AI_ALL_NATIVE_FUTURE_RESULT_CAPTURE_INPUT_V2')
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(calls,[])
        self.assertEqual(values,dict(scope='official-result',source_artifact_prefix='official-future-result-capture'))
        result,calls,values,_,_=self.execute(step,schema='RACE_AI_ALL_NATIVE_FUTURE_RESULT_CAPTURE_INPUT_V2',capture_kind='SOURCE')
        self.assertNotEqual(result.returncode,0);self.assertEqual(calls,[]);self.assertEqual(values,{})
    def test_result_prefix_is_explicit_and_ordinary_source_prefix_outputs_are_unchanged(self):
        route=ident(self.steps,'future_source_route')
        result,calls,values,_,_=self.execute(route,subject='official-future-result-capture: fixture')
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(calls,[])
        self.assertEqual(values,dict(requested='true',capture_kind='RESULT'))
        _,_,old,_,_=self.fixture.execute(route)
        self.assertEqual(old,dict(requested='true'))
        for subject,manifest in (('prefix official-future-result-capture: nope',True),
                                 ('official-future-result-capture',True),('official-future-result-capture: fixture',False)):
            result,calls,values,_,_=self.execute(route,subject=subject,manifest=manifest)
            self.assertEqual(result.returncode,0);self.assertEqual(calls,[]);self.assertEqual(values,{})
    def test_keyless_full_schema_validation_refuses_cross_purpose_before_secret_step(self):
        validate=ident(self.steps,'future_source_scope')
        result,calls,values,_,_=self.execute(validate)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(calls,[])
        self.assertEqual(values,dict(scope='official-result',source_artifact_prefix='official-future-result-capture'))
        for options in (dict(capture_kind='SOURCE'),dict(reject=True),dict(schema='UNKNOWN')):
            result,calls,values,_,_=self.execute(validate,**options)
            self.assertNotEqual(result.returncode,0);self.assertEqual(calls,[]);self.assertEqual(values,{})
            self.assertNotIn('private fixture error',result.stderr)
        result,calls,values,_,_=self.fixture.execute(validate,capture_kind='RESULT')
        self.assertNotEqual(result.returncode,0);self.assertEqual(calls,[]);self.assertEqual(values,{})
    def test_result_capture_keeps_filtered_browser_path_and_new_only_count_schema(self):
        capture=ident(self.steps,'future_source_capture')
        result,calls,values,proof,runner=self.execute(capture)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.fixture.last_fixture_modules,[RESULT_MODULE])
        self.assertEqual(calls,[['--input',MANIFEST,'--out-dir',runner+'/official-future-source-capture']])
        self.assertEqual(proof['schema'],'RACE_AI_ALL_NATIVE_FUTURE_RESULT_CAPTURE_COUNTS_V1')
        self.assertFalse(proof['ready']);self.assertIsNone(proof['source_requests'])
        self.assertFalse(proof['monetary_evaluation_available']);self.assertFalse(proof['all_requested_cases_confirmed'])
        for step in self.steps:
            if 'actions/setup-node@' in step or 'playwright@1.62.1' in step or 'id: future_source_browser' in step:
                self.assertIn("steps.future_source_scope.outputs.scope == 'official-result'",step)
    def test_result_upload_has_fixed_type_name_and_path_and_never_uses_native_upload(self):
        result=ident(self.steps,'future_source_result_upload');native=ident(self.steps,'future_source_native_upload')
        self.assertIsNotNone(result)
        self.assertIn("steps.future_source_scope.outputs.scope != 'official-result'",native)
        self.assertIn("steps.future_source_scope.outputs.scope == 'official-result'",result)
        self.assertIn("steps.future_source_capture.outputs.ready == 'true'",result)
        self.assertIn('uses: '+UPLOAD,result)
        self.assertIn('name: all-existing-official-results-${{ github.run_id }}-900030',result)
        self.assertIn('path: ${{ runner.temp }}/official-future-source-capture/result/results.enc',result)
        self.assertNotIn('outputs.result_path',result);self.assertNotIn('env:',result)
        source=ident(self.steps,'future_source_upload')
        self.assertIn('path: ${{ runner.temp }}/official-future-source-capture/source/*.enc',source)
        self.assertIn('steps.future_source_scope.outputs.source_artifact_prefix',source)
    def test_result_hold_uses_source_only_and_ready_result_uses_exact_actual_id_flag(self):
        step=ident(self.steps,'future_source_readback')
        self.assertIn('RESULT_ARTIFACT_ID: ${{ steps.future_source_result_upload.outputs.artifact-id }}',step)
        for result_id in ('','901'):
            result,calls,_,_,runner=self.execute(step,result_id=result_id)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(self.fixture.last_fixture_modules,[RESULT_MODULE])
            expected=['--input',MANIFEST,'--out-dir',runner+'/official-future-source-capture','--readback-source','802']
            if result_id:expected+=['--readback-result','901']
            self.assertEqual(calls,[expected])
        result,calls,_,_,_=self.execute(step,native_id='801')
        self.assertNotEqual(result.returncode,0);self.assertEqual(calls,[])
        result,calls,_,_,_=self.fixture.execute(step,result_id='901')
        self.assertNotEqual(result.returncode,0);self.assertEqual(calls,[])
    def test_existing_single_job_gates_and_all_inline_shell_syntax_stay_valid(self):
        self.fixture.test_only_owner_same_feature_pr71_attempt_one_after_required_success_can_capture()
        self.assertEqual(self.text.count('  official_future_source_capture:\n'),1)
        for item in self.steps:
            if '        run: ' in item:
                result=subprocess.run(['bash','-n'],input=script(item),text=True,capture_output=True)
                self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
