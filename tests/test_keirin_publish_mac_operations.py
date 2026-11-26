from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts import keirin_publish_mac_operations as operations


class MacPublicOperationsTests(unittest.TestCase):
    def test_only_counters_from_verified_receipts_are_projected(self):
        with TemporaryDirectory() as folder:
            state = Path(folder)
            ticks = state/'ticks'
            ticks.mkdir()
            first = '2026-11-26T09:55:00+00:00'
            last = '2026-11-26T10:10:00+00:00'
            for at, mode in [(first, 'TRIAL_PROFILE_REUSED'), (last, 'TRIAL_PROFILE_FITTED')]:
                raw = json.dumps(dict(schema='KEIRIN_MAC_CYCLE_V1', checked_at=at, production_weights_promoted=False,
                    video=dict(model_state=mode, recorded=0, observation_count=2, trial_sha256='a'*64,
                               internal_path='/private/example'))).encode()
                timestamp = datetime.fromisoformat(at).astimezone(timezone.utc).strftime(operations.STAMP)
                path = ticks/f'{timestamp}-{sha256(raw).hexdigest()}.json'
                path.write_bytes(raw)
            audit = dict(schema='KEIRIN_MAC_CYCLE_TIMING_V1', scope='LOCAL_KEIRIN_RESEARCH', completed_ticks=2,
                         first_tick=first, last_tick=last, seconds_observed=900, seconds_since_last_completion=15,
                         checked_at='2026-11-26T10:10:15+00:00', new_recordings=0, new_candidate_fits=1,
                         full_24h_local_cadence=False)
            body = operations.summarize(state, audit)
            mac = body['mac']
            self.assertEqual(mac['state'], 'running')
            self.assertEqual((mac['newRecordings'], mac['reviewedObservations'], mac['refits'], mac['reuses']), (0,2,1,1))
            self.assertEqual((mac['checkpointSame'], mac['trainingUsedInProduction'], mac['full24h']), (True,False,False))
            self.assertNotIn('/private/example', json.dumps(body))
            self.assertNotIn('a'*64, json.dumps(body))
            audit['seconds_since_last_completion'] = 961
            self.assertEqual(operations.summarize(state, audit)['mac']['state'], 'idle')
            path.write_bytes(path.read_bytes()+b'\n')
            with self.assertRaisesRegex(ValueError, 'MAC_OPERATIONS_RECEIPT_HASH'):
                operations.summarize(state, audit)
