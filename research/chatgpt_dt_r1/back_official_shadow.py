"""Private paired inference from the retained DT-R1 final-back candidate."""
from contextlib import contextmanager
from functools import partial
from tempfile import TemporaryDirectory
from pathlib import Path

from . import back_candidate, back_phase_study, official_inputs, retained_back_readback
from .model import MODEL_ID, RankModel
from .pipeline import validate_prediction_inputs
from .policy import digest, require, validate_forecast
from .runtime import _private_path


SCHEMA = 'DT_R1_OFFICIAL_BACK_SHADOW_PAIR_V1'


@contextmanager
def restored_candidate(receipt_path, private_root, *, owner_private_pem):
    """Load pinned weights for one protected job and remove restored files on exit.

    The yielded callable needs the existing independent source and history
    verifiers. Results are private and ready for the caller's encryption and
    independent readback. This helper never collects or settles target results.
    """
    root = _private_path(private_root)
    require(root.is_dir(), 'B_OFFICIAL_PRIVATE_ROOT_REQUIRED')
    with TemporaryDirectory(prefix='dt-r1-back-official-', dir=root) as temporary:
        destination = Path(temporary) / 'restored'
        with retained_back_readback.verified_bundle(receipt_path) as verified:
            receipt = verified['receipt']
            manifest_sha = receipt['manifest']['sha256']
            restored = back_candidate.restore_candidate(verified['directory'], destination,
                expected_manifest_sha256=manifest_sha, owner_private_pem=owner_private_pem)
            require(restored['status'] == 'B_CANDIDATE_RESTORED' and
                    restored['artifact_sha256'] == receipt['artifact_sha256'] and
                    restored['manifest_sha256'] == manifest_sha and
                    restored['production_promoted'] is False, 'B_OFFICIAL_RESTORE_BINDING')
            candidate = back_candidate.load_candidate(destination / 'back_candidate.json',
                expected_sha256=receipt['candidate_bytes_sha256'])
            evidence = dict(archive_commit=receipt['archive_commit'], manifest_sha256=manifest_sha,
                receipt_file_sha256=verified['receipt_file_sha256'],
                candidate_bytes_sha256=receipt['candidate_bytes_sha256'],
                artifact_sha256=receipt['artifact_sha256'],
                dataset_sha256=receipt['dataset_sha256'],
                leader_sha256=digest(candidate['leader']),
                conditional_model_sha256=candidate['conditional']['model_sha256'],
                direct_model_sha256=candidate['direct']['model_sha256'])
        direct = RankModel.from_dict(candidate['direct'])
        conditional = RankModel.from_dict(candidate['conditional'])
        yield partial(_forecast_pair, candidate, evidence, direct, conditional)


def _arm(law, model_sha256, common, starters):
    forecast = validate_forecast(dict(common, model_sha256=model_sha256, **law))
    require(forecast['starters'] == starters, 'B_OFFICIAL_DISTRIBUTION_ROSTER')
    return dict(model_sha256=model_sha256, trifectas=forecast['trifectas'],
        exactas=forecast['exactas'], riders=law['riders'],
        trifecta_top12=[ticket['cars'] for ticket in forecast['trifectas'][:12]],
        exacta_top2=[ticket['cars'] for ticket in forecast['exactas'][:2]],
        distribution_condition=law['distribution_condition'])


def _forecast_pair(candidate, evidence, direct, conditional, *, payload, original,
                   prediction_at, source_verifier, history_records=(), history_verifier=None):
    target = official_inputs.project(payload, original, prediction_at=prediction_at,
                                     source_verifier=source_verifier)
    history, support = official_inputs._history(history_records, target, prediction_at,
                                                history_verifier)
    model_meta = dict(created_at=candidate['created_at'],
                      parameter_information_end_day=candidate['parameter_information_end_day'],
                      training_last_day=candidate['parameter_information_end_day'])
    _, cutoff = validate_prediction_inputs(target, prediction_at=prediction_at, model_meta=model_meta)
    row = next(row for row in back_phase_study.prepare(history + [target])
               if row['race_id'] == target['race_id'])
    require(row['feature_status'] == 'READY', 'B_OFFICIAL_FEATURES_UNAVAILABLE')
    starters = sorted(rider['car'] for rider in target['riders'])
    common = dict(race_id=row['race_id'], day=row['day'], model_id=MODEL_ID,
        status='READY', cohort='prospective', input_sha256=row['input_sha256'],
        prediction_at=prediction_at, cutoff_at=cutoff, field_size=len(starters))
    mixture = back_phase_study.mixture(candidate['leader'], conditional, row, full=True)
    arms = {
        'back_mixture': _arm(mixture, evidence['artifact_sha256'], common, starters),
        'direct': _arm(direct.distribution(row, full=True), evidence['direct_model_sha256'], common, starters),
    }
    back = [dict(car=car, probability=probability)
            for car, probability in sorted(mixture['back_leader'].items())]
    return dict(common, schema=SCHEMA, scope='PROSPECTIVE_PRIVATE_SHADOW',
        starters=starters, feature_input_sha256=row['feature_input_sha256'],
        feature_schema_sha256=digest(row['feature_names']),
        source_attestation_sha256=target['source_attestation_sha256'],
        source_proof=target['source_proof'], history=support, candidate=dict(evidence),
        arms=arms, back_leader_estimate=dict(observed=False, scope=mixture['scope'],
            probabilities=back, favorite_car=mixture['favorite_car'],
            favorite_loss_by_back_leader=mixture['favorite_loss_by_back_leader']),
        confidence=dict(label='HOLD', reason='NO_B_SPECIFIC_AUDITED_CALIBRATION'),
        independent_forecast_readback=False, production_promoted=False)
