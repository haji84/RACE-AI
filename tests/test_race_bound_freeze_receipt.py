"""Only imaginary SHA, receipts, races and GitHub API responses."""
import base64
import json
import unittest
from race_ai.race_bound_freeze_receipt import BoundReceiptError,verify_bound_receipt

RACE="boat:2030-01-15:fake-venue:1"
HASH="a"*64
CUTOFF="2030-01-15T10:00:00+09:00"
PERSISTED="2030-01-15T09:40:00+09:00"
RECEIPT={"run_id":42,"path":"audit/freezes/2030-01-15/fake.json"}

def fixture(mismatch=False, *, duplicate=False):
    name=RACE.replace(":1",":2") if mismatch else RACE
    anchor={"schema":"RACE_AI_GITHUB_FREEZE_ANCHOR_V1","race_id":name,
            "prediction_sha256":HASH,"cutoff_at":CUTOFF}
    b=json.dumps(anchor).encode("utf-8")
    if duplicate:
        b=b'{"race_id":"'+RACE.encode()+b'","race_id":"'+name.encode()+b'"}'
    return {"type":"file","encoding":"base64","content":base64.b64encode(b).decode()}

def trusted_test_double(receipt,sha,persisted,cutoff,*,_fetch):
    assert _fetch("https://api.github.com/repos/haji84/RACE-AI/actions/runs/42")["id"]==42
    b=_fetch("https://api.github.com/repos/haji84/RACE-AI/contents/audit/freezes/2030-01-15/fake.json?ref="+("b"*40))
    return b["type"]=="file"

def reader(blob):
    def get(url):
        if "/contents/" in url:return blob
        return {"id":42}
    return get

class BoundFreezeTests(unittest.TestCase):
    def test_identity_checked_and_no_assumed_freeze(self):
        self.assertTrue(verify_bound_receipt(RECEIPT,HASH,PERSISTED,CUTOFF,
                        expected_race_id=RACE,trusted_legacy_verifier=trusted_test_double,
                        github_fetch=reader(fixture())))

    def test_wrong_race_hash_and_cutoff_rejected(self):
        with self.assertRaisesRegex(BoundReceiptError,"RACE_ID_MISMATCH"):
            verify_bound_receipt(RECEIPT,HASH,PERSISTED,CUTOFF,expected_race_id=RACE,
                 trusted_legacy_verifier=trusted_test_double,github_fetch=reader(fixture(True)))
        with self.assertRaisesRegex(BoundReceiptError,"fingerprint"):
            verify_bound_receipt(RECEIPT,"b"*64,PERSISTED,CUTOFF,expected_race_id=RACE,
                 trusted_legacy_verifier=trusted_test_double,github_fetch=reader(fixture()))

    def test_duplicate_race_id_and_untrusted_missing_reader(self):
        with self.assertRaisesRegex(BoundReceiptError,"duplicate"):
            verify_bound_receipt(RECEIPT,HASH,PERSISTED,CUTOFF,expected_race_id=RACE,
                 trusted_legacy_verifier=trusted_test_double,github_fetch=reader(fixture(duplicate=True)))
        with self.assertRaisesRegex(BoundReceiptError,"trusted verifier"):
            verify_bound_receipt(RECEIPT,HASH,PERSISTED,CUTOFF,expected_race_id=RACE,
                 trusted_legacy_verifier=None,github_fetch=reader(fixture()))

    def test_cannot_mark_as_valid_without_pinned_blob(self):
        def no_blob(*args,**kwargs):return True
        with self.assertRaisesRegex(BoundReceiptError,"incomplete"):
            verify_bound_receipt(RECEIPT,HASH,PERSISTED,CUTOFF,expected_race_id=RACE,
                 trusted_legacy_verifier=no_blob,github_fetch=reader(fixture()))

if __name__=="__main__":
    unittest.main()
