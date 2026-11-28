"""Private prospective adapter for the independent frozen Codex order model."""
from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
import json

from race_ai import keirin_learned_official_inputs as official
from race_ai import keirin_learned_order as learned
from race_ai import keirin_nationwide_auto_generator as baseline
from race_ai import keirin_official_learned_replay as replay
from race_ai import keirin_official_run_history as codec
from race_ai.keirin_joint_finish import JointFinish

from .admission import _source_proof
from .official_inputs import source_projection
from .policy import check_race_day, checked_sha, clock, digest, require, validate_forecast


MODEL_SHA256 = '17d8fddfbe4f6ba25871c9e869175e5ca2ca5e7475e96ab5f5b6a19e1bf0d7c6'
VERIFICATION_PATH = Path(replay.FROZEN_MODEL).with_name('verification.json')
VERIFICATION_SHA256 = '68b03379e3320371f6da0fb3a93223476cc6ea87c0f2d3a8de108b22f854d11b'
RESTORE_RECEIPT = Path('research/chatgpt_dt_r1/evidence/20261128-continuation/owner-model-restore.json')
RESTORE_RECEIPT_SHA256 = '4afbca0d442b159d9f87668cad5c1d17a00c342dd8f16c6d99e43d7af75fb7e6'
RESTORE_RUN_ID = '46080603797'
FEATURE_SCHEMA_SHA256 = digest(list(learned.FEATURES))
MARGIN = timedelta(minutes=15)


@dataclass(frozen=True)
class FrozenCandidate:
    trained: object
    day: str
    temperature: float
    sealed_at: str
    confirmed_at: str


def model_identity():
    """Exact native identity and separately pinned artifact bytes."""
    return dict(model_id=learned.MODEL_ID, model_sha256=MODEL_SHA256,
                model_file_sha256=replay.FROZEN_MODEL_SHA256, venue_file_sha256=None)


def _pinned_bytes(path, expected):
    require(path.is_file() and not path.is_symlink(), 'CODEX_FUTURE_MODEL_EVIDENCE_FILE')
    raw = path.read_bytes()
    require(sha256(raw).hexdigest() == expected, 'CODEX_FUTURE_MODEL_EVIDENCE_SHA')
    return raw


def load_frozen(repo, private, day):
    """Load the existing sealed model and verify its retrospective/readback clocks."""
    repo = Path(repo)
    identity = model_identity()
    sealed = codec._checked_cipher(_pinned_bytes(repo / replay.FROZEN_MODEL, identity['model_file_sha256']))
    report = json.loads(_pinned_bytes(repo / VERIFICATION_PATH, VERIFICATION_SHA256))
    acceptance = json.loads(_pinned_bytes(repo / RESTORE_RECEIPT, RESTORE_RECEIPT_SHA256))
    official_restore = acceptance['observed_report']
    restored = official_restore['models']['codex_frozen']
    frozen = report['model']
    report_sealed = report['sealed_model']
    sealed_at, confirmed_at = sealed['observed_at'], official_restore['verified_at']
    check_race_day(sealed['day_jst'], sealed_at)
    check_race_day(official_restore['day_jst'], confirmed_at)
    require(report['schema'] == 'RACE_AI_KEIRIN_LEARNED_ORDER_RESEARCH_RECEIPT_V1' and
            report['scope'] == 'RETROSPECTIVE_ARCHIVE_NO_PRE_CUTOFF_ATTESTATION' and
            frozen['model_id'] == restored['model_id'] == identity['model_id'] and
            frozen['tree_sha256'] == restored['tree_sha256'] == identity['model_sha256'] and
            report_sealed['sealed_sha256'] == restored['sealed_model_sha256'] == identity['model_file_sha256'] and
            report_sealed['plaintext_sha256'] == sealed['evidence_plaintext_sha256'] and
            report_sealed['sealed_at'] == sealed_at and
            clock(frozen['fitted_at']) <= clock(frozen['frozen_at']) <=
            clock(report['frozen_evaluation_forecasts_at']) <= clock(report['readback_at']) <=
            clock(sealed_at) <= clock(official_restore['started_at']) <= clock(confirmed_at),
            'CODEX_FUTURE_MODEL_EVIDENCE_BINDING')
    require(acceptance['schema'] == 'DT_R1_OWNER_RESTORATION_ACCEPTANCE_V1' and
            str(acceptance['run_id']) == official_restore['reader_run_id'] == RESTORE_RUN_ID and
            official_restore['state'] == 'OWNER_MODELS_RESTORED_AND_VERIFIED' and
            restored['status'] == 'RESTORED' and restored['owner_decryption_verified'] is True,
            'CODEX_FUTURE_MODEL_RESTORE_CONFIRMATION')
    trained, manifest = replay.load_candidate(repo, private, day)
    require(trained is not None and manifest['model_id'] == identity['model_id'] and
            manifest['tree_sha256'] == identity['model_sha256'] and
            manifest['sealed_model_sha256'] == identity['model_file_sha256'] and
            manifest['temperature'] == frozen['calibration']['temperature'] and
            manifest['calibration_window'] == frozen['calibration_window'] and
            manifest['prior_evaluation_window'] == frozen['evaluation_window'] and
            day.replace('-', '') > frozen['evaluation_window'][1],
            'CODEX_FUTURE_MODEL_IDENTITY')
    return FrozenCandidate(trained, day, manifest['temperature'], sealed_at, confirmed_at)


def _feature_sha(row):
    return digest({key: row[key] for key in (
        'race_id', 'day', 'cutoff_at', 'context_as_of', 'input_sha256',
        'source_projection_sha256', 'source_attestation_sha256',
        'feature_schema_sha256', 'codex_features')})


def project(payload, original, *, day, cutoff_at, input_at, original_meta, input_sha256=None):
    """Project only a previously admitted official SP original and its pinned index entry."""
    snapshot = original['snapshot']
    rid = original['race_id']
    check_race_day(day, cutoff_at)
    check_race_day(day, input_at)
    at, cutoff = clock(input_at), clock(cutoff_at)
    proof = _source_proof(original, original_meta, snapshot, rid, day)
    saved = original['baseline']
    require(original_meta['race_id'] == rid and clock(snapshot['published_cutoff_at']) == cutoff and
            saved['A']['model'] == baseline.MODEL_A and saved['B']['model'] == baseline.MODEL_B and
            clock(proof['latest_server_evidence_at']) <= at <= cutoff - MARGIN and
            clock(original_meta['observed_at']) <= at, 'CODEX_FUTURE_SOURCE_CLOCK_OR_ROLE')
    native = official.project(payload, original)
    require(native['race_id'] == rid and [r['car'] for r in native['riders']] ==
            sorted(r['car'] for r in snapshot['riders']), 'CODEX_FUTURE_SOURCE_ROSTER')
    projection_sha = digest(source_projection(payload, original))
    input_sha = projection_sha if input_sha256 is None else checked_sha(input_sha256)
    row = dict(race_id=rid, day=day, cutoff_at=cutoff_at, context_as_of=input_at,
        input_sha256=input_sha, source_attestation_sha256=proof['evidence_sha256'],
        source_projection_sha256=projection_sha, feature_schema_sha256=FEATURE_SCHEMA_SHA256,
        source_proof=dict(proof), codex_features=native)
    return dict(row, feature_input_sha256=_feature_sha(row))


def _tickets(distribution):
    return [dict(cars=list(order), probability=probability)
            for order, probability in sorted(distribution.items(), key=lambda item: (-item[1], item[0]))]


def forecast(candidate, row, *, generated_or_started_at):
    """Compute both markets from one native joint law, before the cutoff margin."""
    require(isinstance(candidate, FrozenCandidate) and candidate.day == row['day'],
            'CODEX_FUTURE_MODEL_IDENTITY')
    require(row['feature_schema_sha256'] == FEATURE_SCHEMA_SHA256 and
            row['feature_input_sha256'] == _feature_sha(row), 'CODEX_FUTURE_FEATURE_BINDING')
    check_race_day(row['day'], row['cutoff_at'])
    check_race_day(row['day'], row['context_as_of'])
    check_race_day(row['day'], generated_or_started_at)
    started, at, cutoff = map(clock, (generated_or_started_at, row['context_as_of'], row['cutoff_at']))
    require(clock(candidate.sealed_at) <= clock(candidate.confirmed_at) <= at,
            'CODEX_FUTURE_MODEL_NOT_YET_CONFIRMED')
    require(at <= started <= cutoff - MARGIN, 'CODEX_FUTURE_PREDICTION_CLOCK')
    context = learned.context(row['codex_features'])
    joint, = learned.predict(candidate.trained, [context], temperature=candidate.temperature)
    require(isinstance(joint, JointFinish), 'CODEX_FUTURE_JOINT_LAW_REQUIRED')
    result = dict(model_identity(), race_id=row['race_id'], day=row['day'], status='READY',
        cohort='prospective', scope='prospective_shadow_pending_independent_readback',
        input_sha256=row['input_sha256'], feature_input_sha256=row['feature_input_sha256'],
        feature_schema_sha256=row['feature_schema_sha256'], input_schema_sha256=row['feature_schema_sha256'],
        source_attestation_sha256=row['source_attestation_sha256'],
        context_as_of=row['context_as_of'], prediction_at=generated_or_started_at, cutoff_at=row['cutoff_at'],
        field_size=len(context.cars), trifectas=_tickets(joint.trifectas()), exactas=_tickets(joint.exactas()),
        model_sealed_at=candidate.sealed_at, model_confirmed_at=candidate.confirmed_at,
        model_confirmation_receipt_sha256=RESTORE_RECEIPT_SHA256,
        confidence={'label': 'HOLD', 'reason': 'NO_INDEPENDENTLY_AUDITED_PROSPECTIVE_POLICY'},
        forecast_original_independently_read_back=False, production_promoted=False)
    return validate_forecast(result)
