"""Fresh-process CLI tests using fictional past archives and current import time."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_retained_prediction_audit import fixture,policy,label,request,raw,sha,canonical_sha

PROJECT = Path(__file__).resolve().parents[1]


class RetainedCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files=fixture('2020-01-04')

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.root=self.base/'journal'
        self.origin={'schema':'RACE_AI_RETAINED_ORIGIN_REQUEST_V1','files':{}}
        for role,content in self.files.items():
            path=self.base/(role+'.json');path.write_bytes(content)
            self.origin['files'][role]={'path':str(path),'sha256':sha(content)}
        self.p=policy();self.p['declared_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        self.origin_path=self.write('origin-request.json',self.origin);self.policy_path=self.write('policy.json',self.p)

    def write(self,name,value):
        p=self.base/name;p.write_bytes(raw(value));return p

    def run_cli(self,*args):
        env=dict(os.environ);env['PYTHONIOENCODING']='utf-8'
        return subprocess.run([sys.executable,'-B','-m','race_ai.retained_evaluation_cli',*map(str,args)],cwd=PROJECT,
                              env=env,capture_output=True,text=True,timeout=120)

    def imported(self):
        result=self.run_cli('import','--root',self.root,'--audit','fictional','--origin',self.origin_path,
            '--expected-origin-request-sha',canonical_sha(self.origin),'--policy',self.policy_path,'--expected-policy-sha',canonical_sha(self.p))
        self.assertEqual(result.returncode,0,result.stderr)
        value=json.loads(result.stdout);self.assertEqual(value['cohort_races'],168)
        self.assertEqual(value['potentially_exposed_registry_keys'],336)
        self.assertNotIn('1001',result.stdout);self.assertNotIn(str(self.base),result.stdout)
        return value['import_sha256']

    def label_request(self,items,name='labels-request.json'):
        req=request(items)
        for i,(item,entry)in enumerate(zip(items,req['observations'])):
            path=self.base/(name+f'.{i}.label');path.write_bytes(item['raw']);entry['path']=str(path)
        return req,self.write(name,req)

    def test_import_observe_delayed_append_and_restart_prior_report(self):
        imp=self.imported();req,path=self.label_request([label(self.files)])
        first=self.run_cli('observe','--root',self.root,'--audit','fictional','--expected-import-sha',imp,
            '--label-request',path,'--expected-request-sha',canonical_sha(req))
        self.assertEqual(first.returncode,0,first.stderr);summary=json.loads(first.stdout)
        self.assertEqual(summary['model_slots'],3192)
        req2,path2=self.label_request([label(self.files,38,status='SOURCE_UNAVAILABLE_OR_INVALID')],'later-request.json')
        second=self.run_cli('append','--root',self.root,'--audit','fictional','--expected-import-sha',imp,
            '--expected-report-sha',summary['report_sha256'],'--batch-number',1,'--label-request',path2,'--expected-request-sha',canonical_sha(req2))
        self.assertEqual(second.returncode,0,second.stderr)
        output=self.base/'report.json'
        recovered=self.run_cli('report','--root',self.root,'--audit','fictional','--expected-import-sha',imp,
            '--through-batch',0,'--expected-report-sha',summary['report_sha256'],'--output',output)
        self.assertEqual(recovered.returncode,0,recovered.stderr)
        report=json.loads(output.read_bytes());self.assertEqual(report['models'][0]['known_results'],1)
        self.assertEqual(report['models'][0]['unobserved_results'],167)
        self.assertEqual(json.loads(recovered.stdout)['through_batch'],0)
        before=output.read_bytes()
        again=self.run_cli('report','--root',self.root,'--audit','fictional','--expected-import-sha',imp,'--output',output)
        self.assertNotEqual(again.returncode,0);self.assertEqual(output.read_bytes(),before)

    def test_wrong_import_hash_never_opens_nonexistent_label(self):
        imp=self.imported();req=request([label(self.files)])
        req['observations'][0]['path']=str(self.base/'DO_NOT_OPEN_SECRET_LABEL')
        path=self.write('request.json',req)
        result=self.run_cli('observe','--root',self.root,'--audit','fictional','--expected-import-sha','0'*64,
            '--label-request',path,'--expected-request-sha',canonical_sha(req))
        self.assertEqual(json.loads(result.stderr)['error'],'RETAINED_AUDIT_REJECTED')
        self.assertNotIn('Traceback',result.stderr);self.assertNotIn('SECRET',result.stderr)
        self.assertFalse((self.root/'retained-audits/fictional/result-batches').exists())

    def test_duplicate_json_and_now_override_are_rejected_without_registry(self):
        self.origin_path.write_text('{"schema":1,"schema":2}',encoding='utf-8')
        result=self.run_cli('import','--root',self.root,'--audit','fictional','--origin',self.origin_path,
            '--expected-origin-request-sha',canonical_sha(self.origin),'--policy',self.policy_path,'--expected-policy-sha',canonical_sha(self.p))
        self.assertNotEqual(result.returncode,0);self.assertNotIn('Traceback',result.stderr);self.assertFalse(self.root.exists())
        result=self.run_cli('report','--root',self.root,'--audit','fictional','--expected-import-sha','0'*64,'--now','2020-01-01T00:00:00Z')
        self.assertEqual(json.loads(result.stderr)['error'],'INVALID_ARGUMENTS')

    def test_fresh_process_import_closure_has_no_model_modules(self):
        code="import sys; import race_ai.retained_evaluation_cli; print(','.join(sorted(k for k in sys.modules if k.startswith('race_ai.'))))"
        result=subprocess.run([sys.executable,'-B','-c',code],cwd=PROJECT,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(set(result.stdout.strip().split(',')),{'race_ai.retained_evaluation_cli','race_ai.retained_prediction_audit','race_ai.evaluation_metrics'})


if __name__=='__main__':unittest.main()
