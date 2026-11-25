"""Replay pinned official results into private dated rider histories on the owner runner."""
import argparse
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from race_ai import keirin_nationwide_cipher_history as archive
from race_ai import keirin_official_nationwide_records as records
from race_ai.keirin_official_rider_history import project_day_for_dossier
from race_ai.keirin_official_form_history import _aware
from race_ai.keirin_note_view import _create, _private_root, canonical

KEY_ENV = 'RACE_AI_KEIRIN_PRIVATE_RSA_PEM'
FIELDS = {'schema', 'source_day', 'target_day', 'archive_commit', 'index_sha256', 'knowledge_as_of',
          'expected_originals', 'expected_result_races'}


class ReadbackHold(ValueError):
    """Only fixed codes from this module may reach logs."""


def need(condition, code):
    if not condition:
        raise ReadbackHold(code)


def checked_receipt(receipt):
    need(type(receipt) is dict and set(receipt) == FIELDS and
         receipt['schema'] == 'KEIRIN_OFFICIAL_RIDER_HISTORY_SOURCE_V1', 'OFFICIAL_HISTORY_RECEIPT')
    for key, width in (('archive_commit', 40), ('index_sha256', 64)):
        need(type(receipt[key]) is str and re.fullmatch('[0-9a-f]{'+str(width)+'}', receipt[key]),
             'OFFICIAL_HISTORY_RECEIPT')
    for key in ('source_day', 'target_day'):
        need(type(receipt[key]) is str and date.fromisoformat(receipt[key]).isoformat() == receipt[key],
             'OFFICIAL_HISTORY_RECEIPT')
    need(type(receipt['knowledge_as_of']) is str, 'OFFICIAL_HISTORY_RECEIPT')
    _aware(receipt['knowledge_as_of'])
    need(receipt['source_day'] < receipt['target_day'] and
         all(type(receipt[key]) is int for key in ('expected_originals', 'expected_result_races')) and
         0 < receipt['expected_result_races'] <= receipt['expected_originals'] <= records.MAX_RACES,
         'OFFICIAL_HISTORY_RECEIPT')
    return receipt


def prepare_store(repo, receipt):
    """Read immutable Git ciphertext metadata and its external pin before key use."""
    checked_receipt(receipt)
    store = records.RecordStore(repo, receipt['source_day'], index_commit=receipt['archive_commit'])
    raw = archive.read_blob_bytes(store.repo, store.head, store.path, max_bytes=records.MAX_INDEX_BYTES)
    need(type(raw) is bytes and sha256(raw).hexdigest() == receipt['index_sha256'] and
         store.head == store.index_commit == receipt['archive_commit'] and
         len(store.index['originals']) == receipt['expected_originals'] and
         len(store.index['results']) == receipt['expected_result_races'], 'OFFICIAL_HISTORY_PIN')
    return store


def verify_envelopes(store):
    """Check retained SP ciphertext bytes and envelope bindings without a key."""
    metadata = list(store.index['originals'].values())
    metadata.extend(meta for versions in store.index['results'].values() for meta in versions)
    if store.index['registry'] is not None:
        metadata.append(store.index['registry'])
    for meta in metadata:
        raw = archive.read_blob_bytes(store.repo, store.head,
            records.ROOT+'/'+store.day+'/'+meta['evidence_sha256']+'.sealed.json',
            max_bytes=records.history.MAX_CIPHER_BYTES)
        need(type(raw) is bytes and sha256(raw).hexdigest() == meta['cipher_sha256'], 'OFFICIAL_HISTORY_CIPHER')
        envelope = records.history._checked_cipher(raw)
        need(envelope['day_jst'] == store.day and envelope['observed_at'] == meta['observed_at'] and
             envelope['evidence_plaintext_sha256'] == meta['evidence_sha256'], 'OFFICIAL_HISTORY_CIPHER')
    return len(metadata)


def restore(*, store, receipt, owner_private_pem, output_dir, clock=lambda:datetime.now(timezone.utc)):
    checked_receipt(receipt)
    need(store.head == store.index_commit == receipt['archive_commit'], 'OFFICIAL_HISTORY_PIN')
    projection = project_day_for_dossier(store, owner_private_pem, target_day=receipt['target_day'],
                                        knowledge_as_of=receipt['knowledge_as_of'], clock=clock)
    report = projection.receipt
    need(report['originals_by_as_of'] == receipt['expected_originals'] and
         report['admitted_races'] == receipt['expected_result_races'] and report['held_races'] == 0 and
         report['no_result_by_as_of'] == receipt['expected_originals'] - receipt['expected_result_races'] and
         report['numeric_finishes'] > 0, 'OFFICIAL_HISTORY_COUNTS')
    numbers = sorted({row['registration_id'] for race in projection.private_races.values()
                      for row in race['finishes'] if row['place'] is not None})
    histories = [projection.finish_history(number) for number in numbers]
    need(sum(row['periods']['all']['observed_count'] for row in histories) == report['numeric_finishes'],
         'OFFICIAL_HISTORY_COUNTS')
    output = canonical(dict(schema='KEIRIN_OFFICIAL_RIDER_HISTORY_PRIVATE_V1',
        scope='DERIVED_OFFICIAL_RESULT_PROJECTION_NOT_FORECAST_OR_SECOND_STATE_AUTHORITY',
        receipt=receipt, replay=report, histories=histories, races=projection.private_races))
    root = _private_root(output_dir)
    target = root/'official-rider-histories.json'
    need(not target.exists(), 'OFFICIAL_HISTORY_OUTPUT_EXISTS')
    _create(target, output)
    return dict(report, state='OFFICIAL_RIDER_HISTORY_PRIVATE_READBACK_VERIFIED',
        numeric_histories_restored=len(histories), private_projection_written=True,
        private_projection_sha256=sha256(output).hexdigest(), private_projection_bytes=len(output),
        forecast_original_authenticated=False, predictive_model_changed=False, accuracy_improvement_proven=False)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ReadbackHold('OFFICIAL_HISTORY_ARGUMENTS_INVALID')


def main(argv=None):
    private_value = os.environ.pop(KEY_ENV, '')
    try:
        parser = Parser(description=__doc__, allow_abbrev=False)
        parser.add_argument('--repo', type=Path, required=True)
        parser.add_argument('--receipt', type=Path, required=True)
        parser.add_argument('--output-dir', type=Path)
        parser.add_argument('--verify-only', action='store_true')
        args = parser.parse_args(argv)
        raw = args.receipt.read_bytes()
        need(0 < len(raw) <= 16384, 'OFFICIAL_HISTORY_RECEIPT')
        # Canonical JSON rejects duplicate fields and nonfinite values.
        receipt = records.history._json(raw)
        store = prepare_store(args.repo, receipt)
        count = verify_envelopes(store)
        if args.verify_only:
            result = dict(state='OFFICIAL_RIDER_HISTORY_PINNED_INDEX_VERIFIED', owner_key_used=False,
                          encrypted_records_verified=count)
        else:
            need(bool(private_value) and args.output_dir is not None, 'OFFICIAL_HISTORY_OWNER_SECRET_UNAVAILABLE')
            result = restore(store=store, receipt=receipt, owner_private_pem=private_value.encode(),
                             output_dir=args.output_dir)
        del private_value
    except ReadbackHold as error:
        print(json.dumps(dict(state=str(error), private_projection_written=False)))
        return 2
    except Exception:
        print(json.dumps(dict(state='OFFICIAL_HISTORY_INPUT_INVALID', private_projection_written=False)))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
