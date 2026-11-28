import json
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from research.chatgpt_dt_r1.future_retention_gate import check_first_retention


class FirstRetentionTests(unittest.TestCase):
    def test_first_pin_and_bytes(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp)
            name = 'a' * 64 + '.sealed.json'
            manifest = dict(summary=dict(day_jst='2026-11-28', reader_run_id='1', source_archive_commit='b'*40),
                            registry={}, model=dict(model_sha256='c'*64), entries=[dict(cipher=dict(file=name))])
            raw = json.dumps(manifest).encode()
            (p/'manifest.json').write_bytes(raw)
            (p/name).write_bytes(b'encrypted-fixture')
            digest = lambda b: sha256(b).hexdigest()
            verified = dict(manifest=manifest, manifest_sha256=digest(raw), directory=p, producer=dict(run_id=1))
            pin = dict(schema='DT_R1_FUTURE_FIRST_ACCEPTED_V1', day_jst='2026-11-28', model_sha256='c'*64,
                       producer_run_id='1', manifest_sha256=digest(raw), registry={}, source_archive_commit='b'*40,
                       retention_parent_commit='b'*40, retained_files=[dict(file=f.name, bytes=f.stat().st_size,
                       sha256=digest(f.read_bytes())) for f in p.iterdir()])
            pin_raw = json.dumps(pin).encode()
            def check(data=pin_raw, reader=lambda n: (p/n).read_bytes(), expected=digest(pin_raw)):
                return check_first_retention(verified, pin_raw=data, read_retained=reader, expected_pin_sha256=expected)
            self.assertEqual(check()['retained_files_verified'], 2)
            with self.assertRaisesRegex(ValueError, 'PIN_SHA'):
                check(expected='0'*64)
            with self.assertRaisesRegex(ValueError, 'RETAINED_BYTES_MISMATCH'):
                check(reader=lambda n: b'changed' if n == name else raw)
            altered = json.dumps(dict(pin, producer_run_id='2')).encode()
            with self.assertRaisesRegex(ValueError, 'PIN_BINDING'):
                check(data=altered, expected=digest(altered))
            duplicate = json.dumps(dict(pin, retained_files=[pin['retained_files'][0]]*2)).encode()
            with self.assertRaisesRegex(ValueError, 'FILE_BINDING'):
                check(data=duplicate, expected=digest(duplicate))
            (p/'unexpected').write_bytes(b'x')
            with self.assertRaisesRegex(ValueError, 'INVENTORY'):
                check()


if __name__ == '__main__':
    unittest.main()
