"""Count/hash readback of one retained native original; no native-input output.

The fixed locator identifies an already retained original and captured metadata.
Only its authenticated retention clock replays original admission. Actual now
stays separate. Each safe_summary call restores and replays genuine material;
it accepts no detached report, capsule, mutable digest or caller authority flags.
No generation input, current receipt, source permission or dispatch is returned.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256

from .actions_contract import digest
from . import boat_private_original_vault as vault
from .all_existing_model_receipt import _verified_private_pairs_artifact


def _need(ok, reason):
    if not ok:
        raise ValueError('ARCHIVED_NATIVE_' + reason)


@dataclass(frozen=True, slots=True)
class _Binding:
    artifact_id: int
    workflow_run_id: int
    head_sha: str
    artifact_name: str
    original_zip_sha256: str
    original_zip_size: int
    metadata_sha256: str
    metadata_size: int
    original_saved_at: str
    archived_at: str
    source_commit: str
    batch_path: str
    batch_sha256: str
    entry_sha256: str
    cipher_sha256: str
    cipher_size: int
    record_count: int
    native_capsule_count: int


_FIXED_BINDING = _Binding(
    artifact_id=13559236491,
    workflow_run_id=42334526055,
    head_sha='8cf76d3d023591a4c67d04a0001465ac32b441c5',
    artifact_name='all-existing-model-pairs-42334526055-900001',
    original_zip_sha256='864d9e43e1ffbcc231a38fc8467648ee21179f402523680700ace75ef397a248',
    original_zip_size=7399390,
    metadata_sha256='fe7ca01fabf94e33340bf60b24096081f5e05c98fa62600977c81398262a8bd3',
    metadata_size=740,
    original_saved_at='2026-11-07T03:35:08Z',
    archived_at='2026-11-07T03:44:14.584647+00:00',
    source_commit='0490a9d5273d58ae4b50252542608dd40f932431',
    batch_path='state/boat-private-originals/v1/2026-11/batches/'
        '4d81eacb052090d6ba4954a01028ba314e3c63fd0e9fcd8a346ecd5956eba7b6.json',
    batch_sha256='4d81eacb052090d6ba4954a01028ba314e3c63fd0e9fcd8a346ecd5956eba7b6',
    entry_sha256='e43f9b465b177fb20b834bbdd07069b74437cd3ae057e0b7aaa5f50b38546699',
    cipher_sha256='0a9399823d8a543571a74d0d372f205a103b65226d55249477ec462fdfc8f93b',
    cipher_size=7400747,
    record_count=16,
    native_capsule_count=88,
)


def _original_bytes(raw, metadata_raw, binding):
    _need(type(raw) is bytes and len(raw) == binding.original_zip_size and
          sha256(raw).hexdigest() == binding.original_zip_sha256, 'ORIGINAL_ZIP_BYTES')
    _need(type(metadata_raw) is bytes and len(metadata_raw) == binding.metadata_size and
          sha256(metadata_raw).hexdigest() == binding.metadata_sha256, 'ORIGINAL_METADATA_BYTES')


def safe_summary(pin, repo, *, now=None, key=None, transport=None):
    """Restore/replay the fixed original and return only count/hash evidence.

    Select this archival operation explicitly. Unrelated pins refuse before
    transport, and a failed archive never attempts a live fallback. Production
    key access belongs to the existing trusted Actions audit; this helper
    supplies no key or workflow and writes no state. Its returned report is not
    a receipt or native-payload container and cannot authorize current use.
    """
    b = _FIXED_BINDING
    expected_pin = dict(id=b.artifact_id, digest='sha256:'+b.original_zip_sha256,
                        run_id=b.workflow_run_id, head_sha=b.head_sha)
    _need(type(pin) is dict and set(pin) == set(expected_pin) and
          type(pin['id']) is int and type(pin['run_id']) is int and
          type(pin['digest']) is str and type(pin['head_sha']) is str and
          pin == expected_pin, 'EXACT_FIXED_PIN_REQUIRED')
    current = datetime.now(timezone.utc) if now is None else now
    _need(type(current) is datetime and current.utcoffset() is not None, 'AWARE_CURRENT_CLOCK_REQUIRED')
    admitted_at = vault._time(b.archived_at)
    _need(admitted_at <= current, 'FUTURE_ARCHIVED_ADMISSION')
    locator = dict(schema='RACE_AI_BOAT_PRIVATE_ORIGINAL_LOCATOR_V1', repository_id=vault.REPO_ID,
        ref=vault.VAULT_REF, source_commit=b.source_commit, batch_path=b.batch_path,
        batch_sha256=b.batch_sha256, entry_sha256=b.entry_sha256,
        artifact_id=b.artifact_id, kind='PRIVATE_PAIRS', status='READY')
    try:
        git = vault._transport(repo, transport)
        restored = vault.restore_original(locator, repo, key=key, transport=git)
        _, mac_key = vault._keys(key)
        reference = {name:locator[name] for name in
                     ('batch_path','batch_sha256','entry_sha256','artifact_id','kind')}
        entry = vault._batch_entry(git, b.source_commit, reference, mac_key)
    except Exception:
        raise ValueError('ARCHIVED_NATIVE_RESTORE_REJECTED') from None
    _need(entry['cipher_sha256'] == b.cipher_sha256 and entry['cipher_size'] == b.cipher_size and
          entry['header']['files'] == {
              'metadata.json':dict(sha256=b.metadata_sha256, size=b.metadata_size),
              'original.zip':dict(sha256=b.original_zip_sha256, size=b.original_zip_size)},
          'PINNED_CIPHER_AND_FILE_INVENTORY')
    _need(type(restored) is dict and set(restored) ==
          {'raw_zip', 'metadata_raw', 'metadata', 'provenance'}, 'EXACT_RESTORED_ORIGINAL')
    raw = restored['raw_zip']; metadata_raw = restored['metadata_raw']
    _original_bytes(raw, metadata_raw, b)
    expected_provenance = dict(receipt_scope='ARCHIVED_GITHUB_ARTIFACT_RESPONSE',
        current_artifact_status='NOT_QUERIED', archived_at=b.archived_at,
        source_commit=b.source_commit, entry_sha256=b.entry_sha256,
        independent_git_readback_verified=True, github_artifact_receipt_created=False)
    provenance = restored['provenance']
    _need(type(provenance) is dict and provenance == expected_provenance and
          provenance.get('independent_git_readback_verified') is True and
          provenance.get('github_artifact_receipt_created') is False, 'AUTHENTICATED_ARCHIVE_PROVENANCE')
    try:
        metadata = vault._json(metadata_raw, vault.MAX_METADATA)
        _need(type(metadata) is dict and type(restored['metadata']) is dict and
              metadata == restored['metadata'] and type(metadata.get('id')) is int and
              metadata['id'] == b.artifact_id and metadata.get('name') == b.artifact_name and
              metadata.get('created_at') == b.original_saved_at, 'EXACT_ORIGINAL_METADATA')
    except Exception:
        raise ValueError('ARCHIVED_NATIVE_ORIGINAL_METADATA_REJECTED') from None
    try:
        # This clock replays only the original historical receipt. It is never
        # forwarded to generation, rights, fresh source or dispatch code.
        admitted, records = _verified_private_pairs_artifact(raw, metadata, now=admitted_at,
            expected_run_id=b.workflow_run_id, expected_head_sha=b.head_sha, key=key)
        _need(type(admitted) is dict and admitted.get('independent_pre_cutoff_receipt_verified') is True and
              admitted.get('provider_permission_confirmed') is False and
              type(records) is list and len(records) == b.record_count, 'HISTORICAL_NATIVE_ADMISSION')
        capsule_hashes = []
        for record in records:
            captured = record.get('captured_native_inputs') if type(record) is dict else None
            _need(type(captured) is list and captured, 'ARCHIVED_CAPSULES_REQUIRED')
            for capsule in captured:
                _need(type(capsule) is dict and type(capsule.get('native_payload')) is dict,
                      'ARCHIVED_CAPSULE_REQUIRED')
                capsule_hashes.append(digest(capsule))
        _need(len(capsule_hashes) == b.native_capsule_count, 'ARCHIVED_CAPSULE_COUNT')
        record_hashes = [digest(record) for record in records]
    except Exception:
        raise ValueError('ARCHIVED_NATIVE_HISTORICAL_REPLAY_REJECTED') from None
    # Derive every data aggregate here from the authenticated original. Never
    # expose records/capsules or reverify caller-supplied detached graph claims.
    return dict(
        schema='RACE_AI_ARCHIVED_NATIVE_ORIGINAL_READBACK_COUNTS_V1',
        receipt_scope='ARCHIVED_NATIVE_ORIGINAL_READBACK_ONLY',
        artifact_id=b.artifact_id, workflow_run_id=b.workflow_run_id,
        head_sha=b.head_sha, source_commit=b.source_commit,
        source_batch_sha256=b.batch_sha256, source_entry_sha256=b.entry_sha256,
        cipher_sha256=entry['cipher_sha256'], cipher_size_bytes=entry['cipher_size'],
        original_zip_sha256=sha256(raw).hexdigest(), original_zip_size_bytes=len(raw),
        original_metadata_sha256=sha256(metadata_raw).hexdigest(),
        original_metadata_size_bytes=len(metadata_raw),
        source_record_count=len(record_hashes), source_records_sha256=digest(record_hashes),
        native_capsule_count=len(capsule_hashes), archived_capsules_sha256=digest(capsule_hashes),
        archived_original_replay_verified=True, new_model_input_count=0,
        current_artifact_status='NOT_QUERIED', github_artifact_receipt_created=False,
        current_native_admission_created=False, provider_permission_granted=False,
        current_generation_authorized=False, dispatch_authorized=False,
        label_or_training_authorization_granted=False, plaintext_published=False)
