"""Genuine-shaped native input retention, using fictional source boundaries."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import date, datetime
import hashlib
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai.boat_ab_shadow import MODEL_IDS as AB
from race_ai.boat_live_feature_shadow import MODEL_ID as CLITE
from race_ai.boat_observed_pairwise_models import MODEL_IDS as OBSERVED
from race_ai.observed_p1_connection import build_bundle, RIGHTS
from tests.test_observed_p1_connection import inputs, AT, PROGRAM_AT, PREVIEW_AT


def acquired_pair(sink=None, *, expire_after_optional_odds=False):
    """Replace only source acquisition/parsing; execute native models and hook."""
    from scripts import boat_nationwide_ab_pilot as pilot
    base, extra, _ = inputs()
    from tests.test_boat_official_program import page
    from tests.test_boat_observation_context import before_table,starts
    program = page(venue='01',race_no=1,row_options={n:dict(name=f'選手 {n}',national=f'{5+n/10:.2f}<br>30.00<br>45.00') for n in range(1,7)}).replace(b'20:30',b'10:59')
    preview = page(venue='01',race_no=1,content=before_table(display='6.82')+starts(populated=True)).replace(b'20:30',b'10:59').replace(b'/owpc/pc/race/racelist?rno=',b'/owpc/pc/race/beforeinfo?rno=')
    captures = [(program, datetime.fromisoformat(PROGRAM_AT), hashlib.sha256(program).hexdigest()),
                (preview, datetime.fromisoformat(PREVIEW_AT), hashlib.sha256(preview).hexdigest()),
                pilot.SourceError('FICTIONAL_ODDS_UNAVAILABLE')]
    clock = [datetime.fromisoformat(AT)]
    def acquire(*args, **kwargs):
        value = captures.pop(0)
        if isinstance(value, Exception):
            if expire_after_optional_odds:
                clock[0] = datetime.fromisoformat('2030-04-01T10:58:00+09:00')
            raise value
        return value
    with patch.object(pilot, 'get', side_effect=acquire) as get, \
         patch.object(pilot, '_clock', side_effect=lambda *args:clock[0]), \
         patch.object(pilot, 'collect_pitreport', return_value=None), \
         patch.object(pilot, 'collect_entry_history', return_value=None), \
         patch.object(pilot, 'observed_timestamp', return_value=AT), \
         patch.object(pilot, 'NATIVE_INPUT_SINK', sink, create=True), \
         patch.dict(os.environ, RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED='true'):
        result = pilot.make_pair(date(2030, 4, 1), dict(race_id=base['race_id'], cutoff_at=base['cutoff_at']))
    return result, get.call_count


class CurrentNativeInputTests(unittest.TestCase):
    def module(self):
        name = 'race_ai.all_existing_model_inputs'
        self.assertIsNotNone(importlib.util.find_spec(name), 'private native-input retention is required')
        return importlib.import_module(name)

    def requests(self):
        module = self.module()
        base, extra, proof = inputs()
        observed = build_bundle(base, extra, AT, **proof, owner_reviewed=True)
        return module.build_current_requests(base, extra, observed, **proof)

    def test_pilot_hook_captures_five_genuine_native_inputs_with_no_added_gets_or_output_changes(self):
        events = []
        original, original_gets = acquired_pair()
        retained, retained_gets = acquired_pair(events.append)
        self.assertEqual(retained, original)
        self.assertEqual((original_gets, retained_gets), (3, 3))
        self.assertEqual(len(events), 1, 'ready native inputs were discarded before private capture')
        module = self.module()
        requests = module.current_requests(events)
        self.assertEqual({r['cell_key'] for r in requests}, {'boat/'+mid for mid in (*AB, CLITE, *OBSERVED)})
        self.assertTrue(all(set(r) == {'cell_key', 'native_payload'} for r in requests))
        self.assertTrue(all('generated_at' not in r['native_payload'] for r in requests))
        self.assertEqual(requests[0]['native_payload']['source']['boats'][0]['national_win_rate'], 5.1)

    def test_callback_failure_and_mutation_do_not_discard_or_modify_primary_pairs(self):
        original, gets = acquired_pair()
        def failing_sink(requests):
            requests[0]['native_payload']['source']['boats'][0]['national_win_rate'] = 0.
            raise RuntimeError('private handoff unavailable')
        actual, actual_gets = acquired_pair(failing_sink)
        self.assertEqual(actual, original)
        self.assertEqual(actual_gets, gets)

    def test_late_primary_rejection_does_not_leave_an_orphan_pending_input(self):
        events = []
        output, gets = acquired_pair(events.append, expire_after_optional_odds=True)
        self.assertEqual(output[0]['state'], 'TOO_LATE_AFTER_MODEL')
        self.assertIsNone(output[1])
        self.assertEqual(len(events), 0)
        self.assertEqual(gets, 3)

    def test_capture_detaches_values_and_labels_derived_extra_sha_with_actual_upstreams(self):
        module = self.module(); base, extra, proof = inputs()
        observed = build_bundle(base, extra, AT, **proof, owner_reviewed=True)
        before = deepcopy((base, extra, observed))
        requests = module.build_current_requests(base, extra, observed, **proof)
        clite = next(r['native_payload'] for r in requests if r['cell_key'] == 'boat/'+CLITE)
        evidence = clite['source_evidence']
        direct = [r for r in evidence if r['evidence_basis'] == 'HTTP_BODY_SHA256']
        derived = next(r for r in evidence if r['evidence_basis'] == 'DERIVED_COMPOSITE_SHA256')
        self.assertEqual({r['source_ref'] for r in direct}, {proof['program_url'], proof['preview_url']})
        self.assertEqual(derived['source_ref'], proof['preview_url'])
        self.assertEqual(derived['source_sha256'], hashlib.sha256(('a'*64+'b'*64).encode()).hexdigest())
        self.assertEqual(derived['upstream_source_sha256'], ['a'*64, 'b'*64])
        self.assertEqual(derived['derivation'], 'SHA256_UTF8_CONCAT_PROGRAM_AND_BEFOREINFO_HEX_V1')
        self.assertTrue(all(r['source_rights_ref'] == RIGHTS for r in evidence))
        clite['extra']['participants'][0]['local_win_rate'] = 0.
        self.assertEqual((base, extra, observed), before)
        self.assertEqual(requests[0]['native_payload']['source']['boats'][0]['national_win_rate'], 5.1)

    def test_unavailable_native_inputs_are_omitted_and_conflicting_or_unbound_payloads_rejected(self):
        module = self.module(); base, extra, proof = inputs()
        requests = module.build_current_requests(base, extra, None, **proof)
        self.assertEqual({r['cell_key'] for r in requests}, {'boat/'+mid for mid in (*AB, CLITE)})
        first = requests[0]
        self.assertEqual(module.current_requests([requests, deepcopy(requests)]), requests)
        for change in (
                lambda r:r['native_payload']['source'].update(program_source_sha256='f'*64),
                lambda r:r['native_payload']['source_evidence'][0].update(captured_at='2030-04-01T11:00:00+09:00'),
                lambda r:r['native_payload'].update(generated_at=AT),
                lambda r:r['native_payload'].update(RACE_AI_STATE_KEY='never-a-key'),
                lambda r:r.update(cell_key='boat/boat-comprehensive-v1')):
            altered = deepcopy(first); change(altered)
            with self.subTest(change=change), self.assertRaises(ValueError):
                module.current_requests([altered])
        altered = deepcopy(first); altered['native_payload']['source']['boats'][0]['national_win_rate'] = 1.
        with self.assertRaises(ValueError):
            module.current_requests([first, altered])

    def test_private_pending_roundtrip_is_restricted_and_never_prints_or_accepts_git_paths(self):
        module = self.module(); requests = self.requests()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); private = root/'private'
            stdout = io.StringIO()
            with redirect_stdout(stdout), patch.dict(os.environ, RACE_AI_STATE_KEY=''):
                summary = module.write_private_pending_requests(requests, private)
                restored = module.read_private_pending_requests(private)
            self.assertEqual(restored, requests)
            self.assertEqual(stdout.getvalue(), '')
            self.assertEqual(summary['native_request_count'], 5)
            self.assertNotIn('requests', summary)
            self.assertEqual(stat.S_IMODE(private.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((private/'pending.json').stat().st_mode), 0o600)
            self.assertEqual(sorted(p.name for p in private.iterdir()), ['pending.json'])
            with self.assertRaises(ValueError):
                module.write_private_pending_requests(requests, private)
            repository = root/'repo'; repository.mkdir(); (repository/'.git').mkdir()
            with self.assertRaises(ValueError):
                module.write_private_pending_requests(requests, repository/'public')
            self.assertFalse((repository/'public').exists())
            with self.assertRaises(ValueError):
                module.write_private_pending_requests(requests, Path(__file__).resolve().parents[1]/'unapproved-input-capture')

    def test_pending_reader_rejects_symlinks_permissions_tampering_and_oversized_input(self):
        module = self.module(); requests = self.requests()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); private = root/'private'
            module.write_private_pending_requests(requests, private)
            pending = private/'pending.json'; original = pending.read_bytes()
            link = root/'link'; link.symlink_to(private, target_is_directory=True)
            with self.assertRaises(ValueError):module.read_private_pending_requests(link)
            with self.assertRaises(ValueError):module.write_private_pending_requests(requests, link/'new')
            pending.chmod(0o644)
            with self.assertRaises(ValueError):module.read_private_pending_requests(private)
            pending.chmod(0o600)
            envelope = json.loads(original); envelope['requests'][0]['native_payload']['source']['boats'][0]['national_win_rate'] = 0.
            pending.write_text(json.dumps(envelope))
            with self.assertRaises(ValueError):module.read_private_pending_requests(private)
            pending.write_bytes(original)
            with patch.object(module, 'MAX_PENDING_BYTES', 64), self.assertRaises(ValueError):
                module.read_private_pending_requests(private)
            external = root/'external.json'; pending.rename(external); pending.symlink_to(external)
            with self.assertRaises(ValueError):module.read_private_pending_requests(private)


if __name__ == '__main__':
    unittest.main()
