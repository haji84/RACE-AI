"""Synthetic metadata contract tests. No live GitHub access or real forecasts."""
import base64
import json
import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import HTTPSHandler
from urllib.response import addinfourl
from email.message import Message

from race_ai.github_freeze_receipt import (
    verify_github_freeze, ReceiptVerificationError, BASE, ANCHOR_SCHEMA
)


class GitHubReceiptTest(unittest.TestCase):
    def setUp(self):
        self.sha = "a" * 64
        self.receipt = {"run_id": 9001, "path": "audit/freezes/2026-10-23/boat-kojima-1.json"}
        self.cutoff = "2026-10-23T12:00:00+09:00"
        self.claimed = "2026-10-23T11:45:00+09:00"
        self.run = {"id": 9001, "event": "push", "repository": {"full_name": "haji84/RACE-AI"},
                    "head_sha": "b" * 40, "created_at": "2026-10-23T02:46:00Z"}
        self.anchor = {"schema": ANCHOR_SCHEMA, "race_id": "boat:kojima:2026-10-23:1",
                       "prediction_sha256": self.sha, "cutoff_at": self.cutoff}

    def lookup(self, url):
        if url == f"{BASE}/actions/runs/9001":
            return self.run
        if url.endswith("?ref=" + "b" * 40):
            return {"type": "file", "encoding": "base64", "content":
                    base64.b64encode(json.dumps(self.anchor).encode()).decode()}
        raise AssertionError("unapproved fetch " + url)

    def verify(self):
        return verify_github_freeze(self.receipt, self.sha, self.claimed,
                                    self.cutoff, _fetch=self.lookup)

    def test_all_four_sports(self):
        for sport in ("boat", "keirin", "autorace", "horse"):
            with self.subTest(sport=sport):
                self.anchor["race_id"] = sport + ":venue:2026-10-23:1"
                self.assertTrue(self.verify())

    def test_server_time_cutoff(self):
        self.run["created_at"] = "2026-10-23T03:00:00Z"
        with self.assertRaises(ReceiptVerificationError):
            self.verify()

    def test_modified_hash(self):
        self.anchor["prediction_sha256"] = "f" * 64
        with self.assertRaises(ReceiptVerificationError):
            self.verify()

    def test_forged_foreign_run(self):
        self.run["repository"]["full_name"] = "other/repo"
        with self.assertRaises(ReceiptVerificationError):
            self.verify()

    def test_dispatch_run_not_push(self):
        self.run["event"] = "workflow_dispatch"
        with self.assertRaises(ReceiptVerificationError):
            self.verify()

    def test_same_repository_pr_run_accepted(self):
        self.run["event"] = "pull_request"
        self.run["head_repository"] = {"full_name": "haji84/RACE-AI"}
        self.assertTrue(self.verify())

    def test_fork_pr_run_denied(self):
        self.run["event"] = "pull_request"
        self.run["head_repository"] = {"full_name": "other/fork"}
        with self.assertRaises(ReceiptVerificationError):
            self.verify()

    def test_changed_cutoff(self):
        self.anchor["cutoff_at"] = "2026-10-23T12:10:00+09:00"
        with self.assertRaises(ReceiptVerificationError):
            self.verify()

    def test_path_traversal(self):
        self.receipt["path"] = "audit/freezes/2026-10-23/../../README.md"
        with self.assertRaises(ReceiptVerificationError):
            self.verify()

    def test_naive_timestamp(self):
        with self.assertRaises(ReceiptVerificationError):
            verify_github_freeze(self.receipt, self.sha, self.claimed,
                                 "2026-10-23T12:00:00", _fetch=self.lookup)

    def test_claimed_time_cannot_override_server(self):
        self.run["created_at"] = "2026-10-23T03:01:00Z"
        self.claimed = "2026-10-23T10:00:00+09:00"
        with self.assertRaises(ReceiptVerificationError):
            self.verify()


class GitHubAuthenticatedTransportTests(unittest.TestCase):
    def test_uses_configured_token_to_read_actual_github_metadata(self):
        from race_ai.github_freeze_receipt import _github_json
        calls=[]
        def response(handler,request):
            calls.append(request.full_url)
            if request.get_header('Authorization')!='Bearer fictional-token':
                raise HTTPError(request.full_url,401,'authentication required',{},None)
            value=addinfourl(BytesIO(b'{"id":9001}'),{},request.full_url,200);value.msg='OK';return value
        with patch.dict('os.environ',{'GH_TOKEN':'fictional-token','GITHUB_TOKEN':''}),patch.object(HTTPSHandler,'https_open',response):
            self.assertEqual(_github_json(BASE+'/actions/runs/9001'),{'id':9001})
        self.assertEqual(len(calls),1)

    def test_redirect_is_rejected_before_credentials_can_reach_another_host(self):
        from race_ai.github_freeze_receipt import _github_json
        calls=[]
        def response(handler,request):
            calls.append(request.full_url)
            status=302 if len(calls)==1 else 200
            headers=Message()
            if status==302:headers['Location']='https://example.org/foreign'
            value=addinfourl(BytesIO(b'{}'),headers,request.full_url,status);value.msg='Found' if status==302 else 'OK';return value
        with patch.dict('os.environ',{'GH_TOKEN':'fictional-token'}),patch.object(HTTPSHandler,'https_open',response):
            with self.assertRaises((HTTPError,ValueError)):_github_json(BASE+'/actions/runs/9001')
        self.assertEqual(calls,[BASE+'/actions/runs/9001'])


class GitHubPairManifestTests(unittest.TestCase):
    def setUp(self):
        self.receipt={'run_id':9001,'path':'audit/freezes/2026-11-06/fictional-pairs.json'}
        self.entry={'pair_sha256':'a'*64,'file_sha256':'b'*64,'local_freeze_receipt_sha256':'c'*64,
                    'race_id':'20261106-17-01','stage':'P0','write_completed_at':'2026-11-06T01:30:00+09:00',
                    'cutoff_at':'2026-11-06T10:59:00+09:00'}
        self.document={'schema':'RACE_AI_RESEARCH_PAIRS_SHA_ONLY_V2','entries':[dict(self.entry)],
                       'prepared_races':1,'scheduled_races':1,'research_only':True,'actual_purchases':False,'auto_promoted':False}
        self.created='2026-11-05T16:31:00Z'

    def fetch(self,url):
        if url==BASE+'/actions/runs/9001':
            return {'id':9001,'event':'push','repository':{'full_name':'haji84/RACE-AI'},'head_sha':'d'*40,'created_at':self.created}
        if url.endswith('?ref='+'d'*40):
            return {'type':'file','encoding':'base64','content':base64.b64encode(json.dumps(self.document).encode()).decode()}
        raise AssertionError('unapproved metadata endpoint')

    def verify(self):
        from race_ai.github_freeze_receipt import verify_github_pair_manifest
        return verify_github_pair_manifest(self.receipt,self.entry,_fetch=self.fetch)

    def test_membership_binds_pair_body_receipt_race_and_cutoff(self):
        self.assertTrue(self.verify())
        for key,value in [('file_sha256','e'*64),('local_freeze_receipt_sha256','f'*64),('race_id','20261106-17-02'),
                          ('cutoff_at','2026-11-06T11:00:00+09:00')]:
            old=self.document['entries'][0][key];self.document['entries'][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.verify()
            self.document['entries'][0][key]=old

    def test_duplicate_or_wrong_schema_or_count_is_rejected(self):
        for change in ('duplicate','schema','count'):
            old=json.loads(json.dumps(self.document))
            if change=='duplicate':self.document['entries'].append(dict(self.entry));self.document['prepared_races']=2
            elif change=='schema':self.document['schema']='RACE_AI_RESEARCH_PAIRS_SHA_ONLY_V1'
            else:self.document['prepared_races']=2
            with self.subTest(change=change),self.assertRaises(ValueError):self.verify()
            self.document=old

    def test_server_time_after_cutoff_never_admits_a_preclaimed_manifest(self):
        self.created='2026-11-06T03:00:00Z'
        with self.assertRaises(ValueError):self.verify()


if __name__ == "__main__":
    unittest.main()
