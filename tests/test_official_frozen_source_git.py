"""Source public-admission composition: real Git, synthetic GitHub metadata.

The original recovery grants and provider boundary have separate real-AES tests.
No owner key, provider or remote GitHub is used here.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import all_existing_model_official_result_recovery as worker
from tests.test_official_frozen_execution import GitFixture,ObjectReader,REQUEST,ISSUE,wire


class FrozenSourceGitCompositionTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.git=GitFixture(self.root)
        # Reuse the reviewed immutable public bootstrap pin declaration. No
        # artifact is downloaded; subsequent crypto authentication is separate.
        f=self.git;request=json.loads(f.files[REQUEST])
        request['manifest'].update(json.loads((Path(__file__).parent/'fixtures/official-result-issue-bootstrap-pins.json').read_bytes()))
        f.files[REQUEST]=wire(request)
        f.base=f.commit(f.files,[],'official-results-collect: synthetic source gate')
        f.tip=f.commit(dict(f.files,**{'ui.txt':b'unrelated UI'}),[f.base],'unrelated UI')
        f.issue=f.marker(f.base,f.tip)
        f.intent_files=dict(f.files,**{'ui.txt':b'unrelated UI',ISSUE:wire(f.issue)})
        f.intent=f.commit(f.intent_files,[f.tip],'official-results-issue: synthetic source gate')
        f.current_files=dict(f.intent_files,**{'ui.txt':b'later unrelated UI'})
        f.current=f.commit(f.current_files,[f.intent],'later UI')
        self.reader=ObjectReader(f)
        self.git.git('reset','--hard','-q',self.git.base)
        self.request_raw=self.git.files[REQUEST];self.request=json.loads(self.request_raw)
        self.env=dict(head_sha=self.git.base,run_id=17)

    def context(self):
        from scripts import all_existing_model_official_result_issue as issuer
        self.assertTrue(callable(getattr(issuer,'failed_dispositions',None)),'shared failed-anchor gate is missing')
        self.assertTrue(callable(getattr(issuer,'source_continuity',None)),'complete source history gate is missing')
        with patch.object(worker,'__file__',str(self.root/'scripts'/'recovery.py')),\
             patch('race_ai.all_existing_model_official_issue_transport.GithubIssueTransport',return_value=self.reader),\
             patch.object(worker,'state_key',side_effect=AssertionError('public admission read owner key')):
            return worker._frozen_source_context(self.env,self.request,self.request_raw)

    def test_actual_git_gate_accepts_unrelated_code_then_rejects_intent_replacement(self):
        context=self.context();binding=deepcopy(context['binding'])
        self.assertEqual(binding['tested_execution_head_sha'],self.git.base)
        self.assertEqual(binding['intent_head_sha'],self.git.intent)
        self.git.current_files['race_ai/untrusted.py']=b'raise AssertionError("CURRENT_CODE_EXECUTED")'
        self.git.current=self.git.commit(self.git.current_files,[self.git.current],'later unrelated Python')
        worker._refresh_frozen(context,self.env,self.request)
        self.assertEqual(context['binding'],binding)
        self.assertEqual(context['snapshot'].facts['current_head_sha'],self.git.current)
        revoked=deepcopy(self.git.current_files);revoked[ISSUE]=b'{"revoked":true}'
        self.git.current=self.git.commit(revoked,[self.git.current],'revoke source intent')
        with self.assertRaises(ValueError):worker._refresh_frozen(context,self.env,self.request)

    def test_public_history_failure_precedes_key_and_refresh_uses_published_phase(self):
        from scripts import all_existing_model_official_result_issue as issuer
        context=self.context()
        with patch.object(issuer,'failed_dispositions',wraps=issuer.failed_dispositions) as failed,\
             patch.object(issuer,'source_continuity',wraps=issuer.source_continuity) as continuity:
            worker._refresh_frozen(context,self.env,self.request)
        self.assertTrue(failed.call_args.kwargs['published'])
        self.assertEqual(continuity.call_args.args[2],self.request)
        self.assertIn('verified_failed',continuity.call_args.kwargs)
        with patch.object(issuer,'source_continuity',side_effect=ValueError('OFFICIAL_ISSUE_MISSING_PRIOR_SOURCE')),\
             patch.object(worker,'state_key',side_effect=AssertionError('owner key before history proof')) as key:
            with self.assertRaisesRegex(ValueError,'MISSING_PRIOR_SOURCE'):self.context()
        key.assert_not_called()

    def test_wrong_source_checkout_and_actor_or_fork_stop_before_key(self):
        self.git.git('reset','--hard','-q',self.git.current)
        with self.assertRaisesRegex(ValueError,'SOURCE_CHECKOUT_HEAD'):self.context()
        self.git.git('reset','--hard','-q',self.git.base)
        original=self.reader.json('actions/runs/17');wrong=deepcopy(original);wrong['actor']['id']=9
        self.reader.overrides['actions/runs/17']=wrong
        with self.assertRaises(ValueError):self.context()
        self.reader.overrides.pop('actions/runs/17')
        fork=self.git.pr();fork['head']['repo']['id']=9;self.reader.overrides['pulls/71']=fork
        with self.assertRaises(ValueError):self.context()


if __name__=='__main__':unittest.main()
