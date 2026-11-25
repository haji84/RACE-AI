"""Recovery structure checks use invented records and an explicit decrypt double."""
import base64
from contextlib import redirect_stdout
from copy import deepcopy
from hashlib import sha256
from io import BytesIO, StringIO
import importlib
import importlib.util
from itertools import permutations
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from race_ai.keirin_joint_finish import JointFinish
from race_ai.keirin_joint_forecast import build_forecast, public_projection


DAY = '2026-11-25'
CREATED = '2026-11-25T12:01:00+00:00'
WITNESSED = '2026-11-25T12:03:00+00:00'
CIPHER = 'c' * 64
COMMIT = 'd' * 40
CODE = (
    'scripts/keirin_accuracy_study.py', 'scripts/keirin_boosted_choice_study.py',
    'scripts/keirin_ordered_ticket_study.py', 'scripts/keirin_line_event_study.py',
    'race_ai/keirin_archive_study.py', 'race_ai/keirin_joint_finish.py',
)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode()


def file_record(value):
    raw = canonical(value)
    return {'text': raw.decode(), 'bytes': len(raw), 'sha256': sha256(raw).hexdigest()}


def archive_record(files):
    out = BytesIO()
    with tarfile.open(fileobj=out, mode='w:gz') as archive:
        for name, raw in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(raw)
            archive.addfile(member, BytesIO(raw))
    raw = out.getvalue()
    return {'base64': base64.b64encode(raw).decode(), 'bytes': len(raw),
            'sha256': sha256(raw).hexdigest()}


def invented_note():
    archived = {f'frozen-model/stage-{n}.txt': f'invented stage {n}'.encode() for n in range(3)}
    archived.update({'frozen-code/' + name: b'# Invented source, never executed.\n' for name in CODE})
    model = {'stage_sha256': [sha256(archived[f'frozen-model/stage-{n}.txt']).hexdigest() for n in range(3)],
             'source_files_sha256': {name: sha256(archived['frozen-code/' + name]).hexdigest() for name in CODE}}
    archived['frozen-model/model.json'] = canonical(model)
    archived['frozen-model/freeze-prospective.py'] = b'# Never executed.\n'
    version = sha256(archived['frozen-model/model.json']).hexdigest()
    inputs = []
    for number, count in ((1, 3), (2, 4)):
        rid = '2026112561' + f'{number:02d}'
        cars = list(range(1, count + 1))
        source = f'<html>Invented source {number}</html>'.encode()
        source_sha = sha256(source).hexdigest()
        archived['sources/' + source_sha + '.html'] = source
        captured = '2026-11-25T11:00:00+00:00'
        cutoff = '2026-11-25T22:04:00+09:00' if number == 1 else '2026-11-25T22:10:00+09:00'
        inputs.append({
            'race_id': rid, 'cutoff_at': cutoff, 'source_as_of': captured,
            'forecast_generated_at': '2026-11-25T12:00:00+00:00',
            'input': {'race_id': rid, 'line_groups': [cars], 'riders': [
                {'car': car, 'competition_points': 100.5 - car, 'win_rate': 10.1,
                 'top2_rate': 20.2, 'top3_rate': 30.3, 'mark_rank': 'UNMARKED',
                 'class': 'S2', 'style': 'NIGE' if car == 1 else 'MARK'} for car in cars]},
            'roster': [{'car': car, 'name': f'Invented person {number}-{car}', 'registration': None} for car in cars],
            'source': {'race_id': rid, 'raw_sha256': source_sha, 'raw_bytes': len(source),
                       'raw_path': '/old/private/not-followed/' + source_sha + '.html',
                       'http_status': 200, 'requested_at': '2026-11-25T10:59:59+00:00',
                       'captured_at': captured, 'publication_at': None,
                       'publication_clock_status': 'NOT_INDEPENDENTLY_ATTESTED',
                       'source_url': f'https://keirin.kdreams.jp/tamano/racedetail/61202611250100{number:02d}/'},
        })
    input_file = file_record({'schema': 'RACE_AI_KEIRIN_COMPARISON_INPUTS_V1', 'races': inputs})
    baseline, candidate = [], []
    for row in inputs:
        cars = [r['car'] for r in row['roster']]
        orders = list(permutations(cars, 3))
        joint = JointFinish(cars, {order: 1 / len(orders) for order in orders}, tail=(.3, -.1))
        metadata = dict(race_id=row['race_id'], generated_at=row['forecast_generated_at'],
            cutoff_at=row['cutoff_at'], source_as_of=row['source_as_of'], model_version=version,
            input_sha256=sha256(canonical(row['input'])).hexdigest(),
            source_packet_sha256=input_file['sha256'],
            source_forecast_generated_at=row['forecast_generated_at'], riders=row['roster'])
        baseline.append(build_forecast(joint, model_id='comparison-B-before-saved', **metadata))
        candidate.append(build_forecast(joint, model_id='comparison-B-residual', **metadata))
    prefix = 'data/' + DAY + '/'
    note = {'schema': 'RACE_AI_KEIRIN_NOTE_VIEW_V1', 'dates': [DAY],
        'scope': 'OWNER_FROZEN_JOINT_COMPARISON_RESEARCH', 'imported_at': '2026-11-25T12:00:00+00:00',
        'model_id': 'keirin-comparison-B-residual', 'model_sha256': version,
        'formal_model_admission': False, 'production_weight_switch': False, 'wagers_placed': False,
        'comparison_private_nonce': 'invented-private-entropy',
        'files': {
            prefix + 'comparison_inputs.json': input_file,
            prefix + 'comparison_baselines.json': file_record({'races': baseline}),
            prefix + 'comparison_joint_originals.json': file_record({'races': candidate}),
            prefix + 'joint_forecasts.json': file_record({'schema': 'RACE_AI_KEIRIN_JOINT_FORECASTS_V1',
                                                         'races': [public_projection(r) for r in candidate]}),
            prefix + 'races.json': file_record({'races': [{'race_id': row['race_id'], 'cutoff': row['cutoff_at'],
                'lines': row['input']['line_groups'], 'riders': [
                    {'number': rider['car'], 'name': rider['name'], 'score': 100.5 - rider['car']}
                    for rider in row['roster']]} for row in inputs]}),
        },
        'preserved_archives': {'comparison-originals.tar.gz': archive_record(archived)},
    }
    return note, archived


class JointOriginalReadbackTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('scripts.keirin_joint_original_readback'),
                             'The independent research-original readback verifier is missing.')
        self.module = importlib.import_module('scripts.keirin_joint_original_readback')
        self.note, self.archived = invented_note()
        self.raw_cipher = canonical({'observed_at': '2026-11-25T23:30:00+09:00', 'fixture': True})
        self.pem = b'Invented decrypt double; no key is generated.'
        self.update_payload()

    def update_payload(self):
        raw = canonical(self.note)
        self.expected_note = sha256(raw).hexdigest()
        self.payload = {'schema': 'KEIRIN_JOINT_ORIGINAL_RECOVERY_V1', 'day_jst': DAY,
            'original_note_b64': base64.b64encode(raw).decode(),
            'original_note_sha256': self.expected_note, 'original_cipher_sha256': CIPHER,
            'original_archive_commit': COMMIT,
            'safe_report': {'day_jst': DAY, 'original_created_at': CREATED,
                'original_git_readback_at': WITNESSED, 'earliest_cutoff': '2026-11-25T22:04:00+09:00',
                'original_header': {'schema': 'RACE_AI_SAVED_WEB_VIEW_V1',
                                    'source_content_sha256': self.expected_note}}}

    def verify(self, **changes):
        arguments = {'expected_original_note_sha256': self.expected_note,
                     'expected_original_cipher_sha256': CIPHER,
                     'expected_original_archive_commit': COMMIT,
                     'expected_original_created_at': CREATED,
                     'expected_original_git_readback_at': WITNESSED}
        arguments.update(changes)
        with patch.object(self.module.history, 'decrypt_evidence', return_value=self.payload):
            return self.module.verify_recovery(self.raw_cipher, self.pem, **arguments)

    def alter_file(self, filename, change):
        key = 'data/' + DAY + '/' + filename
        data = json.loads(self.note['files'][key]['text'])
        change(data)
        self.note['files'][key] = file_record(data)
        self.update_payload()

    def test_reads_all_full_pairs_and_four_car_floats_without_exposing_them(self):
        report = self.verify()
        self.assertEqual(report['paired_races'], 2)
        self.assertEqual(report['full_forecast_records_verified'], 4)
        self.assertEqual(report['source_files_verified'], 2)
        self.assertTrue(report['independent_research_plaintext_readback'])
        self.assertFalse(report['formal_PR71'])
        self.assertFalse(report['actual_organizer_cutoff_authenticated'])
        self.assertEqual(report['original_note_sha256'], self.expected_note)
        rendered = json.dumps(report)
        for private in ('Invented person', 'trifectas', 'rank_probabilities', 'line_groups',
                        'original_note_b64', 'raw_path'):
            self.assertNotIn(private, rendered)

    def test_new_recovery_copy_clock_after_cutoff_preserves_old_exact_commitment(self):
        report = self.verify()
        self.assertEqual(report['original_created_at'], CREATED)
        self.assertEqual(report['original_git_readback_at'], WITNESSED)
        self.assertTrue(report['all_originals_before_earliest_cutoff'])

    def test_different_note_bytes_cannot_reuse_the_original_header_hash(self):
        decoded = base64.b64decode(self.payload['original_note_b64'])
        self.payload['original_note_b64'] = base64.b64encode(decoded + b' ').decode()
        with self.assertRaisesRegex(ValueError, 'JOINT_RECOVERY_NOTE_SHA_MISMATCH'):
            self.verify()

    def test_payload_bindings_must_equal_external_hashes_and_archive_commit(self):
        for field, value in (('original_cipher_sha256', 'e' * 64),
                             ('original_archive_commit', 'e' * 40),
                             ('original_note_sha256', 'e' * 64)):
            before = deepcopy(self.payload)
            self.payload[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'JOINT_RECOVERY_EXTERNAL_BINDING_MISMATCH'):
                self.verify()
            self.payload = before

    def test_payload_cannot_supply_its_own_original_commitment_clock(self):
        self.payload['safe_report']['original_git_readback_at'] = '2026-11-25T12:03:01+00:00'
        with self.assertRaisesRegex(ValueError, 'JOINT_RECOVERY_EXTERNAL_CLOCK_MISMATCH'):
            self.verify()

    def test_original_witness_after_cutoff_is_not_accepted_as_pre_cutoff(self):
        late = '2026-11-25T22:05:00+09:00'
        self.payload['safe_report']['original_git_readback_at'] = late
        with self.assertRaisesRegex(ValueError, 'JOINT_RECOVERY_ORIGINAL_COMMITMENT_LATE'):
            self.verify(expected_original_git_readback_at=late)

    def test_note_file_bytes_and_declared_lengths_are_checked(self):
        record = self.note['files']['data/' + DAY + '/comparison_baselines.json']
        record['bytes'] += 1
        self.update_payload()
        with self.assertRaisesRegex(ValueError, 'JOINT_RECOVERY_FILE_BYTES_MISMATCH'):
            self.verify()

    def test_actual_input_hash_must_match_both_full_forecasts(self):
        self.alter_file('comparison_inputs.json',
                        lambda d: d['races'][0]['input']['riders'][0].update(competition_points=123.0))
        with self.assertRaisesRegex(ValueError, 'JOINT_RECOVERY_INPUT_SHA_MISMATCH'):
            self.verify()

    def test_version_roster_and_cutoff_must_match_across_each_pair(self):
        cases = (('model_version', 'e' * 64), ('cutoff_at', '2026-11-25T22:06:00+09:00'))
        for field, value in cases:
            self.note, self.archived = invented_note()
            self.alter_file('comparison_joint_originals.json', lambda d: d['races'][0].update({field: value}))
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'JOINT_RECOVERY_PAIR_METADATA_MISMATCH'):
                self.verify()
        self.note, self.archived = invented_note()
        self.alter_file('comparison_joint_originals.json',
                        lambda d: d['races'][0]['riders'][0].update(name='Another invented person'))
        with self.assertRaisesRegex(ValueError, 'JOINT_RECOVERY_ROSTER_MISMATCH'):
            self.verify()

    def test_late_or_incomplete_forecasts_do_not_enter_recovered_pre_cutoff_counts(self):
        self.alter_file('comparison_joint_originals.json', lambda d: d['races'][0].update(
            generated_at='2026-11-25T22:05:00+09:00', scope='RETROSPECTIVE_RESEARCH'))
        with self.assertRaisesRegex(ValueError, 'JOINT_RECOVERY_FORECAST_LATE'):
            self.verify()
        self.note, self.archived = invented_note()
        self.alter_file('comparison_baselines.json', lambda d: d['races'][0]['trifectas'].pop())
        with self.assertRaisesRegex(ValueError, 'JOINT_RECOVERY_FORECAST_INVALID'):
            self.verify()

    def test_missing_pair_and_duplicate_race_are_rejected(self):
        self.alter_file('comparison_baselines.json', lambda d: d['races'].pop())
        with self.assertRaisesRegex(ValueError, 'JOINT_RECOVERY_COHORT_MISMATCH'):
            self.verify()
        self.note, self.archived = invented_note()
        self.alter_file('comparison_baselines.json', lambda d: d['races'].append(deepcopy(d['races'][0])))
        with self.assertRaisesRegex(ValueError, 'JOINT_RECOVERY_COHORT_INVALID'):
            self.verify()

    def test_archived_source_bytes_and_frozen_model_files_are_verified(self):
        for prefix, reason in (('sources/', 'JOINT_RECOVERY_SOURCE_BYTES_MISMATCH'),
                               ('frozen-model/stage-', 'JOINT_RECOVERY_MODEL_ARCHIVE_MISMATCH')):
            self.note, self.archived = invented_note()
            name = next(n for n in self.archived if n.startswith(prefix))
            self.archived[name] += b'changed'
            self.note['preserved_archives']['comparison-originals.tar.gz'] = archive_record(self.archived)
            self.update_payload()
            with self.subTest(prefix=prefix), self.assertRaisesRegex(ValueError, reason):
                self.verify()

    def test_archive_paths_are_never_extracted_or_followed(self):
        self.archived['../../escape-secret'] = b'No filesystem write is permitted.'
        self.note['preserved_archives']['comparison-originals.tar.gz'] = archive_record(self.archived)
        self.update_payload()
        with self.assertRaisesRegex(ValueError, 'JOINT_RECOVERY_ARCHIVE_MEMBER_INVALID'):
            self.verify()

    def test_archive_bound_includes_hidden_pax_headers_before_tar_parsing(self):
        out = BytesIO()
        with tarfile.open(fileobj=out, mode='w:gz', format=tarfile.PAX_FORMAT) as archive:
            for index, (name, raw) in enumerate(self.archived.items()):
                member = tarfile.TarInfo(name)
                member.size = len(raw)
                if index == 0:
                    member.pax_headers = {'comment': 'x' * 100_000}
                archive.addfile(member, BytesIO(raw))
        raw = out.getvalue()
        self.note['preserved_archives']['comparison-originals.tar.gz'] = {
            'base64': base64.b64encode(raw).decode(), 'bytes': len(raw),
            'sha256': sha256(raw).hexdigest()}
        self.update_payload()
        with patch.object(self.module, 'MAX_EXPANDED', 32_768):
            with self.assertRaisesRegex(ValueError, 'JOINT_RECOVERY_ARCHIVE_TOO_LARGE'):
                self.verify()

    def test_projection_must_come_from_the_same_full_original(self):
        self.alter_file('joint_forecasts.json',
                        lambda d: d['races'][0]['riders'][0].update(top3_probability=.5))
        with self.assertRaisesRegex(ValueError, 'JOINT_RECOVERY_PROJECTION_MISMATCH'):
            self.verify()

    def test_cli_pops_owner_secret_and_never_echoes_decryption_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'cipher.json').write_bytes(self.raw_cipher)
            receipt = {'recovery_cipher_sha256': sha256(self.raw_cipher).hexdigest(),
                       'original_note_sha256': self.expected_note, 'original_cipher_sha256': CIPHER,
                       'original_archive_commit': COMMIT, 'expected_original_created_at': CREATED,
                       'expected_original_git_readback_at': WITNESSED}
            (root / 'receipt.json').write_bytes(canonical(receipt))
            secret = 'private-key-canary-never-log'
            output = StringIO()
            with patch.dict(os.environ, {'RACE_AI_KEIRIN_PRIVATE_RSA_PEM': secret}), \
                    patch.object(self.module.history, 'decrypt_evidence', side_effect=ValueError(secret)), \
                    redirect_stdout(output):
                status = self.module.main(['--cipher', str(root / 'cipher.json'),
                                           '--receipt', str(root / 'receipt.json')])
                self.assertNotIn('RACE_AI_KEIRIN_PRIVATE_RSA_PEM', os.environ)
            self.assertEqual(status, 2)
            self.assertNotIn(secret, output.getvalue())
            self.assertIn('JOINT_RECOVERY_DECRYPTION_FAILED', output.getvalue())

    def test_invalid_secret_text_is_removed_and_reports_only_a_fixed_hold(self):
        secret='private-canary-\udcff'
        output=StringIO()
        with patch.dict(os.environ, {'RACE_AI_KEIRIN_PRIVATE_RSA_PEM':secret}), redirect_stdout(output):
            status=self.module.main([])
            self.assertNotIn('RACE_AI_KEIRIN_PRIVATE_RSA_PEM',os.environ)
        self.assertEqual(status,2)
        self.assertNotIn('private-canary',output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['state'],'JOINT_RECOVERY_INPUT_INVALID')


if __name__ == '__main__':
    unittest.main()
