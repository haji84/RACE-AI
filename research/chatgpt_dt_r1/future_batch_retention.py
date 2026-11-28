"""Append genuinely verified DT-R1 ciphertext to the existing owner archive.

The caller supplies the outputs of verified_producer and verify_readback.
This module binds and preserves their bytes without decrypting forecasts or
attesting official result, source replay, or model accuracy.
"""
from datetime import timedelta
from pathlib import Path

from race_ai import keirin_nationwide_cipher_history as archive
from race_ai import keirin_official_nationwide_records as records
from race_ai import keirin_official_run_history as codec
from race_ai.keirin_github_origin_evidence import MAX_ARCHIVE_BYTES, MAX_REPORT_BYTES, _id
from research.chatgpt_dt_r1.policy import clock


ROOT = 'research/chatgpt-dt-r1/future'
POINTER_SCHEMA = 'DT_R1_FUTURE_FIRST_SLOT_V1'
ORIGIN_SCHEMA = 'DT_R1_FUTURE_SERVER_ORIGIN_V1'
POINTER_FIELDS = {'schema', 'day_jst', 'model_sha256', 'slot_sha256', 'producer_run_id',
                  'manifest_sha256', 'readback_sha256', 'cipher_sha256'}
ORIGIN_ID_FIELDS = ('producer_job_id', 'readback_job_id', 'producer_artifact_id', 'readback_artifact_id')
ORIGIN_SHA_FIELDS = ('producer_archive_sha256', 'readback_archive_sha256', 'manifest_sha256')
ORIGIN_FLAGS = ('source_authenticated', 'official_result_verified', 'production_promoted')
ORIGIN_FIELDS = {'schema', 'producer_run_id', 'readback_run_id', 'latest_server_evidence_at',
                 'eligible_slots', 'held_slots', 'minimum_margin_seconds',
                 *ORIGIN_ID_FIELDS, *ORIGIN_SHA_FIELDS, *ORIGIN_FLAGS}
MARGIN_SECONDS = 900
MAX_POINTER_BYTES = 16_384


def _need(condition, reason):
    if not condition:
        raise ValueError('DT_R1_FUTURE_BATCH_' + reason)


def _sha(value):
    return type(value) is str and archive.SHA.fullmatch(value) is not None


def _run(value):
    return type(value) is str and archive.RUN.fullmatch(value) is not None


def _prefix(day, model_sha256):
    codec._day(day)
    _need(_sha(model_sha256), 'MODEL_PIN')
    return f"{ROOT}/{day.replace('-', '')}/{model_sha256}"


def _slots(slots):
    values = tuple(slots)
    _need(len(values) <= records.MAX_RACES and all(_sha(slot) for slot in values), 'SLOT_SET')
    unique = set(values)
    _need(len(unique) == len(values), 'SLOT_DUPLICATE')
    return unique


def _manifest_entries(manifest, day, model_sha256, run):
    from scripts import keirin_dt_r1_future_shadow as shadow

    _need(type(manifest) is dict and manifest.get('schema') == shadow.SCHEMA, 'MANIFEST_SCHEMA')
    summary, model, entries = (manifest.get(key) for key in ('summary', 'model', 'entries'))
    _need(type(summary) is dict and summary.get('day_jst') == day and summary.get('reader_run_id') == run and
          type(model) is dict and model.get('model_sha256') == model_sha256, 'MANIFEST_IDENTITY')
    _need(type(entries) is list and 0 < len(entries) <= records.MAX_RACES and
          type(summary.get('registered_races')) is int and len(entries) == summary['registered_races'] and
          all(type(entry) is dict and set(entry) == shadow.ENTRY_FIELDS for entry in entries),
          'MANIFEST_DENOMINATOR')
    _slots(entry.get('slot_sha256') for entry in entries)
    return {entry['slot_sha256']: entry for entry in entries}


def _checked_origin(origin, manifest, *, run, manifest_sha256, entries):
    from scripts import keirin_dt_r1_future_shadow as shadow

    _need(type(origin) is dict and set(origin) == ORIGIN_FIELDS and origin['schema'] == ORIGIN_SCHEMA and
          origin['producer_run_id'] == run and _run(origin['readback_run_id']) and
          origin['readback_run_id'] != run and
          all(_id(origin[key]) for key in ORIGIN_ID_FIELDS) and
          origin['producer_job_id'] != origin['readback_job_id'] and
          origin['producer_artifact_id'] != origin['readback_artifact_id'] and
          all(_sha(origin[key]) for key in ORIGIN_SHA_FIELDS) and origin['manifest_sha256'] == manifest_sha256 and
          type(origin['minimum_margin_seconds']) is int and origin['minimum_margin_seconds'] == MARGIN_SECONDS and
          all(origin[key] is False for key in ORIGIN_FLAGS), 'READBACK_BINDING')
    latest = clock(origin['latest_server_evidence_at'])
    _need(clock(manifest['summary']['finished_at']) <= latest, 'READBACK_CLOCK')
    eligible, held = [], {}
    for slot, entry in entries.items():
        if entry['cipher'] is None:
            _need(entry['state'] == 'HOLD', 'MISSING_READY_CIPHER')
        elif entry['state'] != shadow.READY:
            held[slot] = 'PRODUCER_ORIGINAL_HELD'
        elif latest > clock(entry['clocks']['cutoff_at']) - timedelta(seconds=MARGIN_SECONDS):
            held[slot] = 'SERVER_READBACK_AFTER_T15'
        else:
            eligible.append(slot)
    _need(origin['eligible_slots'] == sorted(eligible) and origin['held_slots'] == held, 'READBACK_SLOT_PARTITION')
    return set(eligible)


def _check_cipher(raw, entry, day):
    cipher = entry['cipher']
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_ARCHIVE_BYTES and
          type(cipher) is dict and cipher.get('file') == entry['slot_sha256'] + '.sealed.json' and
          cipher.get('bytes') == len(raw) and cipher.get('sha256') == codec._sha(raw), 'CIPHER_SHA')
    envelope = codec._checked_cipher(raw)
    _need(envelope['day_jst'] == day and envelope['observed_at'] == entry['clocks']['seal_started_at'] and
          envelope['evidence_plaintext_sha256'] == cipher['plaintext_sha256'], 'CIPHER_ENVELOPE_BINDING')
    return raw


def _require_complete_history(repo, head):
    if archive._cmd(repo, 'rev-parse', '--is-shallow-repository')[1] != 'true':
        return
    shallow_path = archive._cmd(repo, 'rev-parse', '--path-format=absolute', '--git-path', 'shallow')[1]
    root = archive._cmd(repo, '--no-replace-objects', 'rev-list', '--first-parent',
                        '--max-parents=0', head)[1]
    _need(archive.COMMIT.fullmatch(root) and root not in Path(shallow_path).read_text().splitlines(),
          'ARCHIVE_ANCESTRY_TRUNCATED')


def _tree_entries(repo, commit, paths):
    result = archive._cmd(repo, '--no-replace-objects', 'ls-tree', '--full-tree', '-z',
                          commit, '--', *sorted(paths))[1]
    entries = {}
    for line in result.split('\0'):
        if line:
            meta, sep, path = line.partition('\t')
            _need(sep and path in paths and path not in entries, 'ARCHIVE_TREE_ENTRY')
            entries[path] = meta
    return entries


def _pointer_introductions(repo, head, paths, *, namespace=None):
    # A full registry check also sees a retired slot or a deleted pointer.
    # Name-only output avoids hydrating blobs for absent slots.
    pathspec = [namespace] if namespace else sorted(paths)
    result = archive._cmd(repo, '--no-replace-objects', 'log', '--first-parent', '--full-history',
        '--diff-merges=first-parent', '--no-renames', '--no-show-signature',
        '--format=%x00%H', '--name-only', f'--max-count={len(paths) + 1}', head, '--', *pathspec)[1]
    intro = {}
    pieces = result.split('\0')
    _need(pieces[0] == '', 'ARCHIVE_POINTER_HISTORY_FORMAT')
    for piece in pieces[1:]:
        commit, *changed = piece.split()
        _need(archive.COMMIT.fullmatch(commit), 'ARCHIVE_POINTER_HISTORY_FORMAT')
        for path in changed:
            _need(path in paths, 'POINTER_OUTSIDE_REGISTRY')
            _need(path not in intro, 'ARCHIVE_POINTER_CHANGED')
            intro[path] = commit
    _need(len(pieces) <= len(paths) + 1, 'ARCHIVE_POINTER_CHANGED')
    if paths:
        _need(intro.keys() == _tree_entries(repo, head, paths).keys(), 'ARCHIVE_POINTER_MISSING_OR_UNPINNED')
    return intro


def _check_introduction(repo, head, commit, paths):
    parents = archive._cmd(repo, '--no-replace-objects', 'rev-list', '--parents', '-n', '1', commit)[1].split()
    _need(len(parents) == 2 and parents[0] == commit and archive.COMMIT.fullmatch(parents[1]),
          'ARCHIVE_INTRODUCTION_PARENT')
    files = _tree_entries(repo, commit, paths)
    _need(not _tree_entries(repo, parents[1], paths) and files.keys() == paths and
          all(meta.startswith('100644 blob ') for meta in files.values()) and
          files == _tree_entries(repo, head, paths), 'ARCHIVE_INTRODUCTION_MISMATCH')


def _batch_metadata(repo, head, stem, day, model_sha256, pointer):
    from scripts import keirin_dt_r1_future_shadow as shadow

    manifest_raw = archive.read_blob_bytes(repo, head, stem + '/manifest.json',
                                           max_bytes=shadow.MAX_MANIFEST_BYTES + 1)
    origin_raw = archive.read_blob_bytes(repo, head, stem + '/readback.json', max_bytes=MAX_REPORT_BYTES + 1)
    _need(manifest_raw is not None and origin_raw is not None, 'BATCH_METADATA_MISSING')
    manifest_sha, origin_sha = codec._sha(manifest_raw), codec._sha(origin_raw)
    _need(pointer['manifest_sha256'] == manifest_sha and pointer['readback_sha256'] == origin_sha,
          'POINTER_BATCH_SHA')
    manifest, origin = codec._json(manifest_raw), codec._json(origin_raw)
    run = pointer['producer_run_id']
    entries = _manifest_entries(manifest, day, model_sha256, run)
    eligible = _checked_origin(origin, manifest, run=run, manifest_sha256=manifest_sha, entries=entries)
    return manifest_sha, origin_sha, entries, eligible, manifest, origin


def read_retained_forecasts(repo, head, day, model_sha256, slots, *,
                            authenticate_batch=None, verify_registry=False):
    """Check first-parent introductions and return the pinned ciphertext references."""
    _need(type(head) is str and archive.COMMIT.fullmatch(head), 'ARCHIVE_HEAD_PIN')
    _need(authenticate_batch is None or callable(authenticate_batch), 'ARCHIVE_AUTHENTICATOR')
    prefix = _prefix(day, model_sha256)
    namespace = f'{prefix}/first-slots'
    paths = {f'{namespace}/{slot}.json': slot for slot in sorted(_slots(slots))}
    if not paths and not verify_registry:
        return {}
    _require_complete_history(repo, head)
    introductions = _pointer_introductions(repo, head, paths, namespace=namespace if verify_registry else None)
    pointers, introduced_files = {}, {}
    for path, commit in introductions.items():
        slot = paths[path]
        raw = archive.read_blob_bytes(repo, head, path, max_bytes=MAX_POINTER_BYTES + 1)
        _need(raw is not None, 'ARCHIVE_POINTER_MISSING_OR_UNPINNED')
        pointer = codec._json(raw)
        _need(type(pointer) is dict and set(pointer) == POINTER_FIELDS and pointer['schema'] == POINTER_SCHEMA and
              pointer['day_jst'] == day and pointer['model_sha256'] == model_sha256 and
              pointer['slot_sha256'] == slot and _run(pointer['producer_run_id']) and
              all(_sha(pointer[key]) for key in ('cipher_sha256', 'manifest_sha256', 'readback_sha256')),
              'POINTER_SCHEMA_OR_IDENTITY')
        run = pointer['producer_run_id']
        stem = f'{prefix}/batches/{run}'
        introduced_files.setdefault(commit, set()).update(
            (path, f'{stem}/manifest.json', f'{stem}/readback.json', f'{stem}/{slot}.sealed.json'))
        pointers[slot] = pointer
    for commit, files in introduced_files.items():
        _check_introduction(repo, head, commit, files)

    batches, forecasts = {}, {}
    for slot, pointer in pointers.items():
        run = pointer['producer_run_id']
        stem = f'{prefix}/batches/{run}'
        if run not in batches:
            batches[run] = _batch_metadata(repo, head, stem, day, model_sha256, pointer)
        manifest_sha, origin_sha, entries, eligible, manifest, _ = batches[run]
        _need(pointer['manifest_sha256'] == manifest_sha and pointer['readback_sha256'] == origin_sha and
              slot in eligible and pointer['cipher_sha256'] == entries[slot]['cipher']['sha256'],
              'POINTER_BATCH_BINDING')
        cipher_path = f'{stem}/{slot}.sealed.json'
        cipher = archive.read_blob_bytes(repo, head, cipher_path, max_bytes=MAX_ARCHIVE_BYTES + 1)
        _check_cipher(cipher, entries[slot], day)
        forecasts[slot] = dict(entry=entries[slot], manifest=manifest, cipher_path=cipher_path)
    if authenticate_batch is not None:
        for manifest_sha, _, _, _, manifest, origin in batches.values():
            authenticate_batch(manifest, origin, manifest_sha)
    return forecasts


def retained_slots(repo, head, day, model_sha256, slots, *, authenticate_batch=None):
    return set(read_retained_forecasts(repo, head, day, model_sha256, slots,
                                       authenticate_batch=authenticate_batch))


def append_verified_batch(repo, verified, origin, *, legacy_accepted_slots=(), synthetic_local=False,
                          authenticate_batch=None):
    """Append a batch and its previously unaccepted slots in one normal Git push."""
    from scripts import keirin_dt_r1_future_shadow as shadow

    folder = Path(verified['directory'])
    manifest_sha = verified['manifest_sha256']
    manifest = shadow.verify_output(folder, expected_manifest_sha256=manifest_sha)
    producer = verified['producer']
    run = str(producer['run_id'])
    _need(manifest == verified['manifest'] and _id(producer['run_id']) and _run(run), 'VERIFIED_MANIFEST_BINDING')
    day, model_sha = manifest['summary']['day_jst'], manifest['model']['model_sha256']
    prefix = _prefix(day, model_sha)
    entries = _manifest_entries(manifest, day, model_sha, run)
    eligible = _checked_origin(origin, manifest, run=run, manifest_sha256=manifest_sha, entries=entries)
    _need(origin['producer_job_id'] == producer['job_id'] and origin['producer_artifact_id'] == producer['artifact_id']
          and origin['producer_archive_sha256'] == producer['archive_sha256'] and
          manifest['summary']['reader_code_commit'] == producer['commit'], 'VERIFIED_PRODUCER_BINDING')
    manifest_raw = (folder / 'manifest.json').read_bytes()
    _need(manifest_raw == codec._canonical(manifest), 'VERIFIED_MANIFEST_BYTES')
    origin_raw = codec._canonical(origin)
    _need(0 < len(origin_raw) <= MAX_REPORT_BYTES, 'READBACK_SIZE')
    origin_sha = codec._sha(origin_raw)
    legacy = _slots(legacy_accepted_slots)
    repo = archive._remote(repo, synthetic_local=synthetic_local)
    stem = f'{prefix}/batches/{run}'
    report = dict(producer_run_id=run, registered_races=len(entries), independently_timed_candidates=len(eligible),
                  noneligible_registered_slots=len(entries) - len(eligible))
    previous = None
    for _ in range(3):
        head = archive._refresh(repo, blobless=True)
        records._check_archive_commit(repo, manifest['summary']['source_archive_commit'])
        if previous is not None:
            _need(previous != head and archive._cmd(repo, '--no-replace-objects', 'merge-base',
                '--is-ancestor', previous, head, okay=True)[0] == 0, 'ARCHIVE_PUSH_UNACKNOWLEDGED')
        retained = retained_slots(repo, head, day, model_sha, eligible,
                                  authenticate_batch=authenticate_batch)
        new = eligible - legacy - retained
        counts = dict(report, already_accepted_slots=len(eligible) - len(new),
                      new_first_slots=len(new))
        if not new:
            return dict(counts, state='DT_R1_FUTURE_BATCH_NO_NEW_FIRST_SLOTS', archive_commit=head, retained_files=0)
        files = {stem + '/manifest.json': manifest_raw, stem + '/readback.json': origin_raw}
        for slot in sorted(new):
            entry = entries[slot]
            name = slot + '.sealed.json'
            path = folder / name
            _need(path.is_file() and not path.is_symlink(), 'VERIFIED_CIPHER_PATH')
            files[f'{stem}/{name}'] = _check_cipher(path.read_bytes(), entry, day)
            files[f'{prefix}/first-slots/{slot}.json'] = codec._canonical(dict(
                schema=POINTER_SCHEMA, day_jst=day, model_sha256=model_sha, slot_sha256=slot,
                producer_run_id=run, manifest_sha256=manifest_sha, readback_sha256=origin_sha,
                cipher_sha256=entry['cipher']['sha256']))
        status, commit = archive._push_archive_files(repo, head, files, 'archive(keirin): retain verified DT-R1 batch')
        if status != 0:
            previous = head
            continue
        observed = archive._refresh(repo, blobless=True)
        _need(archive._cmd(repo, '--no-replace-objects', 'merge-base',
                          '--is-ancestor', commit, observed, okay=True)[0] == 0, 'ARCHIVE_READBACK_MISMATCH')
        if observed != commit:
            committed = _tree_entries(repo, commit, files)
            _need(committed.keys() == files.keys() and committed == _tree_entries(repo, observed, files),
                  'ARCHIVE_READBACK_MISMATCH')
        _need(retained_slots(repo, observed, day, model_sha, new) == new, 'ARCHIVE_READBACK_MISMATCH')
        return dict(counts, state='DT_R1_FUTURE_BATCH_APPENDED', archive_commit=observed,
                    write_commit=commit, retained_files=len(files))
    raise ValueError('DT_R1_FUTURE_BATCH_CONCURRENT_PUSH_RETRY_EXHAUSTED')
