import importlib.util
from pathlib import Path
import tempfile
import copy
import json
import types
import unittest
from unittest.mock import patch
from tests.test_live_evaluation_contract import fixture,NOW
from web.evaluation_contract import build_research_evaluation

ROOT=Path(__file__).resolve().parents[1]


class EvaluationCallerTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('evaluation_caller',ROOT/'scripts/verify_research_evaluation.py')
        self.c=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.c)

    def test_dry_run_does_not_read_credentials_or_create_files(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(self.c,'workflow_session',side_effect=AssertionError('network')):
            output=Path(directory)/'evaluation.json'
            self.c.run('20261015-14-01',output)
            self.assertEqual(list(Path(directory).iterdir()),[])

    def test_invalid_target_or_identity_stops_before_credentials(self):
        for url,race in [('https://attacker.example/api/evaluation','20261015-14-01'),
                         ('https://race-ai-preview-safe-qq1130034-1738.vercel.app/api/evaluation','../escape')]:
            with patch.dict('os.environ',{'RACE_AI_EVALUATION_URL':url}),patch.object(self.c,'workflow_session') as session:
                with self.assertRaises(ValueError):self.c.run(race,Path('unused.json'),execute=True)
                session.assert_not_called()

    def test_live_receipts_replay_before_normalized_backup_without_source_get(self):
        prediction,bundle,race=fixture();report=build_research_evaluation(prediction,bundle,race,NOW)
        feed={'venues':[{'races':[race]}]};calls=[]
        def get_json(opener,request,*,limit):
            calls.append(request.full_url)
            self.assertEqual(request.get_method(),'GET')
            if request.full_url.endswith('/today'):return feed
            if '/prediction?' in request.full_url:return prediction
            if '/race?' in request.full_url:return bundle
            if '/evaluation?' in request.full_url:return report
            self.fail('unbounded target')
        env={'RACE_AI_EVALUATION_URL':'https://race-ai-preview-safe-qq1130034-1738.vercel.app/api/evaluation','RACE_AI_EVALUATION_COMMIT_SHA':'a'*40}
        with tempfile.TemporaryDirectory() as folder,patch.dict('os.environ',env),patch.object(self.c,'workflow_session',return_value=(object(),{})),patch.object(self.c,'get_json',side_effect=get_json),patch.object(self.c,'datetime',types.SimpleNamespace(now=lambda tz:NOW)):
            path=Path(folder)/'evaluation.json';self.c.run(race['race_id'],path,execute=True)
            self.assertEqual(json.loads(path.read_bytes()),report)
            self.assertEqual(len(calls),4)

    def test_changed_scores_claims_or_invalid_clock_are_rejected(self):
        prediction,bundle,race=fixture();report=build_research_evaluation(prediction,bundle,race,NOW)
        for mutate in (lambda x:x['models'][0].update(multiclass_brier=.01),lambda x:x.update(validation_status='VALIDATED'),lambda x:x.update(as_of='2026-10-15T10:49:00+09:99')):
            changed=copy.deepcopy(report);mutate(changed)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):self.c.verify_evaluation(changed,prediction,bundle,race,NOW)


if __name__=='__main__':unittest.main()
