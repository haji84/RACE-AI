"""Explicit profile, current-time fresh-process tests using fictional archives."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_retained_captured_origin import fixture, policy, label, raw, sha, canonical_sha

PROJECT=Path(__file__).resolve().parents[1]


class CapturedCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.files=fixture('2020-01-04')

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.root=self.base/'journal'
        bundle=json.loads(self.files['bundle']);history=json.loads(self.files['history'])
        # Fixture helper exposes actual row identities, not manufactured source values.
        self.req={'schema':'RACE_AI_CAPTURED_ORIGIN_REQUEST_V1','profile':'RACE41_CAPTURED_HISTORY_V1',
            'target_race_ids':sorted(r['race_id']for r in bundle['races']),
            'history_race_ids':sorted({r['race_id']for r in history['history']['rows']}),'files':{}}
        for role,content in self.files.items():
            p=self.base/(role+'.json');p.write_bytes(content)
            self.req['files'][role]={'path':str(p),'sha256':sha(content)}
        self.p=policy();self.p['declared_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        self.rp=self.write('request.json',self.req);self.pp=self.write('policy.json',self.p)

    def write(self,name,value):
        path=self.base/name;path.write_bytes(raw(value));return path

    def run_cli(self,op,*args,profile=True):
        options=['--profile','captured-history-v1']if profile else[]
        return subprocess.run([sys.executable,'-B','-X','utf8','-m','race_ai.retained_evaluation_cli',op,
            '--root',str(self.root),'--audit','fictional',*options,*map(str,args)],cwd=PROJECT,
            capture_output=True,text=True,timeout=120)

    def imported(self):
        r=self.run_cli('import','--origin',self.rp,'--expected-origin-request-sha',canonical_sha(self.req),
            '--policy',self.pp,'--expected-policy-sha',canonical_sha(self.p))
        self.assertEqual(r.returncode,0,r.stderr)
        value=json.loads(r.stdout)
        self.assertEqual((value['cohort_races'],value['model_slots'],value['potentially_exposed_registry_keys']),(132,2508,552))
        return value['import_sha256']

    def test_import_observe_restart_original_bytes_and_full_cohort(self):
        imp=self.imported();items=[label(self.files,115),label(self.files,116),label(self.files,117,status='SOURCE_UNAVAILABLE_OR_INVALID')]
        entries=[]
        for i,item in enumerate(items):
            p=self.base/f'label-{i}.json';p.write_bytes(item['raw']);v=json.loads(item['raw'])
            entries.append({'race_id':v['race_id'],'revision':1,'source_id':'OFFICIAL_BOATRACE','file_sha256':item['expected_sha256'],'path':str(p)})
        request={'schema':'RACE_AI_RETAINED_LABEL_REQUEST_V1','observations':entries};rp=self.write('labels-request.json',request)
        r=self.run_cli('observe','--expected-import-sha',imp,'--label-request',rp,'--expected-request-sha',canonical_sha(request))
        self.assertEqual(r.returncode,0,r.stderr);first=json.loads(r.stdout)
        self.assertEqual((first['known_results'],first['unknown_results'],first['model_slots']),(2,130,2508))
        output=self.base/'report.json'
        recovered=self.run_cli('report','--expected-import-sha',imp,'--expected-report-sha',first['report_sha256'],'--output',output)
        self.assertEqual(recovered.returncode,0,recovered.stderr)
        report=json.loads(output.read_bytes());self.assertEqual(report['schema'],'RACE_AI_RETAINED_AUDIT_REPORT_V2')
        self.assertEqual(len(report['hash_witness_cohorts']['TIMELY_HASH_WITNESS']['race_ids']),16)
        for role,content in self.files.items():self.assertEqual((self.root/'retained-audits/fictional/origin'/f'{role}.json').read_bytes(),content)
        wrong=self.run_cli('report','--expected-import-sha',imp,profile=False)
        self.assertNotEqual(wrong.returncode,0)
        self.assertNotIn('Traceback',wrong.stderr)

    def test_default_profile_does_not_admit_new_descriptor(self):
        r=self.run_cli('import','--origin',self.rp,'--expected-origin-request-sha',canonical_sha(self.req),
            '--policy',self.pp,'--expected-policy-sha',canonical_sha(self.p),profile=False)
        self.assertNotEqual(r.returncode,0);self.assertFalse(self.root.exists())

    def test_missing_origin_leaves_pending_and_all_declared_aliases(self):
        Path(self.req['files']['history']['path']).unlink()
        r=self.run_cli('import','--origin',self.rp,'--expected-origin-request-sha',canonical_sha(self.req),
            '--policy',self.pp,'--expected-policy-sha',canonical_sha(self.p))
        self.assertNotEqual(r.returncode,0);self.assertEqual(len(list((self.root/'exposed-races').glob('*.json'))),552)
        self.assertFalse((self.root/'retained-audits/fictional/import-completed.json').exists())
        self.assertNotIn(str(self.base),r.stderr)


if __name__=='__main__':unittest.main()
