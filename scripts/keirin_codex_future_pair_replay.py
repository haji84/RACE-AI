"""Reproduce an independently timed Codex shadow original before opening results."""
from contextlib import contextmanager
from hashlib import sha256

from race_ai import keirin_official_nationwide_records as records
from race_ai import keirin_official_run_history as codec
from research.chatgpt_dt_r1 import codex_future_candidate, official_inputs
from research.chatgpt_dt_r1.policy import clock, digest
from scripts import keirin_dt_r1_future_shadow as shadow


class CodexReplayError(ValueError):
    """One static reason suitable for a run's aggregate hold counts."""

    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


@contextmanager
def _stage(reason):
    try:
        yield
    except Exception:
        raise CodexReplayError(reason) from None


def _need(ok):
    if not ok:
        raise ValueError('Codex replay mismatch')


def replay_codex_original(entry, raw, manifest, source, rid, private, candidate, client, cache):
    """Verify and reproduce one sealed original from the caller's admitted batch.

    The caller verifies the producer/readback GitHub witness and matches the
    independently timed peer DT-R1 entry. This function reads only the pinned
    official pre-race original, using the producer's clock solely for replay.
    """
    with _stage('CODEX_REPLAY_SCOPE'):
        summary = manifest['summary']
        registry, meta = source.index['registry'], source.index['originals'][rid]
        scope = shadow._report_scope(True)
        peer = {key: summary[key] for key in shadow.CODEX_PEER_FIELDS}
        shadow._check_codex_peer(peer, summary['reader_run_id'])
        _need(manifest['schema'] == shadow.SCHEMA and
              manifest['model'] == codex_future_candidate.model_identity() and
              summary['schema'] == shadow.CODEX_SUMMARY_SCHEMA and summary['scope'] == scope and
              summary['day_jst'] == source.day and summary['source_archive_commit'] == source.head and
              manifest['registry'] == {key: registry[key] for key in ('evidence_sha256', 'cipher_sha256')} and
              entry['state'] == shadow.READY and entry['source_admitted'] is True and entry['reason'] is None and
              entry['context_geometry_present'] is None and
              entry['slot_sha256'] == shadow.slot(source.day, rid) and
              sum(item['slot_sha256'] == entry['slot_sha256'] for item in manifest['entries']) == 1 and
              entry in manifest['entries'])
    with _stage('CODEX_REPLAY_CLOCKS'):
        clocks = entry['clocks']
        _need(set(clocks) == set(shadow.CLOCK_FIELDS) | {'cutoff_at'} and
              meta['race_id'] == rid and meta['cutoff_at'] == clocks['cutoff_at'])
        cutoff = clock(clocks['cutoff_at'])
        times = [clock(clocks[field]) for field in shadow.CLOCK_FIELDS]
        _need(all(shadow._same_day(at, source.day) for at in [*times, cutoff]) and
              times == sorted(times) and
              clock(summary['started_at']) <= times[0] <= times[-1] <= clock(summary['finished_at']) and
              shadow._timely(times[-1], clocks['cutoff_at']))
    with _stage('CODEX_REPLAY_CIPHERTEXT'):
        cipher = entry['cipher']
        _need(type(raw) is bytes and len(raw) == cipher['bytes'] and
              sha256(raw).hexdigest() == cipher['sha256'] and
              cipher['file'] == entry['slot_sha256'] + '.sealed.json')
        envelope = codec._checked_cipher(raw)
        _need(envelope['evidence_plaintext_sha256'] == cipher['plaintext_sha256'] and
              envelope['day_jst'] == source.day and envelope['observed_at'] == clocks['seal_started_at'])
        saved = codec.decrypt_evidence(raw, private)
    with _stage('CODEX_REPLAY_PRIVATE_BINDING'):
        binding = dict(schema=shadow.CODEX_PRIVATE_SCHEMA, day_jst=source.day, race_id=rid,
            observed_at=clocks['seal_started_at'], reader_code_commit=summary['reader_code_commit'],
            reader_run_id=summary['reader_run_id'], source_archive_commit=source.head,
            source_registry_reference=records.wire(registry), source_original_reference=records.wire(meta),
            safe_report=dict(day_jst=source.day, scope=scope, new_forecasts=1,
                             confidence='HOLD', independently_admitted_new_forecasts=0))
        _need(set(saved) == set(binding) | {'forecast', 'feature_row', 'shared_material'} and
              all(saved[key] == value for key, value in binding.items()))
    with _stage('CODEX_REPLAY_OFFICIAL_INPUT'):
        payload = source.read(meta, private)
        original, _ = records.admit_original(source, payload, private, origin_client=client, packet_cache=cache)
        _need(original['race_id'] == rid and original['day_jst'] == source.day and
              original['snapshot']['published_cutoff_at'] == clocks['cutoff_at'])
    with _stage('CODEX_REPLAY_FEATURES'):
        common = official_inputs.verification_payload(
            payload, original, prediction_at=clocks['input_at'])['normalized_input']
        row = codex_future_candidate.project(payload, original, day=source.day, cutoff_at=clocks['cutoff_at'],
            input_at=clocks['input_at'], original_meta=meta, input_sha256=common['input_sha256'])
        material = dict(schema=shadow.CODEX_MATERIAL_SCHEMA, **peer,
            source_projection_sha256=row['source_projection_sha256'], source_archive_commit=source.head,
            source_original_reference=records.wire(meta), source_verification=row['source_proof'],
            input_sha256=row['input_sha256'])
        expected_bindings = dict(input_sha256=row['input_sha256'], feature_input_sha256=row['feature_input_sha256'],
            source_receipt_sha256=row['source_attestation_sha256'], shared_material_sha256=digest(material))
        _need(entry['bindings'] == expected_bindings and
              digest(saved['feature_row']) == digest(records.wire(row)) and
              digest(saved['shared_material']) == expected_bindings['shared_material_sha256'])
    with _stage('CODEX_REPLAY_DISTRIBUTION'):
        reproduced = codex_future_candidate.forecast(candidate, row,
            generated_or_started_at=clocks['prediction_started_at'])
        reproduced.update(prediction_at=clocks['prediction_at'], scope=scope + '_PENDING_INDEPENDENT_READBACK',
                          forecast_original_independently_read_back=False, production_promoted=False)
        _need(digest(saved['forecast']) == digest(records.wire(reproduced)))
        return saved['forecast']
