"""Fictional GitHub-anchor shape validation only."""
import json,unittest
from scripts.check_anchor_witness import validate,WitnessError
PATH="audit/freezes/2030-01-15/"+"a"*64+".json"
def sample():return json.dumps({"schema":"RACE_AI_GITHUB_FREEZE_ANCHOR_V1",
  "race_id":"boat:2030-01-15:fictional:1",
  "prediction_sha256":"b"*64,"cutoff_at":"2030-01-15T10:00:00+09:00"}).encode()
class TestWitness(unittest.TestCase):
 def test_shape(self):self.assertTrue(validate(PATH,sample()))
 def test_unlisted_fields(self):
    o=json.loads(sample());o["odds"]=30
    with self.assertRaises(WitnessError):validate(PATH,json.dumps(o).encode())
 def test_wrong_path(self):
    with self.assertRaises(WitnessError):validate("../"+PATH,sample())
 def test_duplicate_anchor_keys(self):
    with self.assertRaisesRegex(WitnessError,"duplicate"):
        validate(PATH,b'{"race_id":"x","race_id":"y"}')
if __name__=="__main__":unittest.main()
