"""Score independently saved private venue P1 pairs without public forecasts.

Admission, owner authentication and exact forecast replay precede scoring.
Private inputs, outcomes and full paired scores stay in one owner-encrypted
three-file candidate per race; callers receive only aggregate PDCA. The exact
source ciphertext archive is retained separately under its authenticated hash.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
from pathlib import Path

from .actions_contract import digest
from .boat_pdca_state import state_key
from .boat_venue_dataset import _bytes
from .boat_venue_learning import seal_candidate
from .boat_venue_research_receipt import _verified_private_p1_artifact
from .frozen_day_cycle import official_id
from .observed_weight_learning import read_shadow_rows, score_shadows, ts
from scripts.boat_all_racers import _write
from scripts.boat_history_collect import private_root


def _need(ok, reason):
    if not ok:
        raise ValueError('VENUE_PRIVATE_PDCA_'+reason)


def _output(path):
    path = Path(path).absolute()
    _need('..' not in path.parts and not any(p.is_symlink() for p in (path, *path.parents)),
          'OUTPUT_PATH_INVALID')
    _need(not path.exists(), 'OUTPUT_EXISTS_DO_NOT_RESET')
    _need(not any((p/'.git').exists() for p in (path, *path.parents)), 'OUTPUT_OUTSIDE_GIT_REQUIRED')
    return path


def _baseline_rows(payload, metadata):
    """Map the already replayed suite into the unchanged paired scorer contract."""
    snapshot = payload['snapshot']; suite = payload['baseline_suite']
    race_id = official_id(snapshot['race_id'])
    roster = {str(p['lane']): p['registration_no'] for p in snapshot['participants']}
    return [dict(race_id=race_id, sport='boat', stage='P1', model_id=model_id,
                 as_of=snapshot['as_of'], cutoff_at=snapshot['sales_cutoff_at'],
                 server_saved_at=metadata['created_at'], artifact_id=metadata['id'],
                 original_json_sha256=digest(payload), model_sha256=model['prediction_sha256'],
                 roster=deepcopy(roster), top8=deepcopy(model['ordered_top8']),
                 ranked=[deepcopy(c['combination']) for c in model['candidates']], calibrated=False)
            for model_id, model in suite['models'].items()]


def _summary(admission, training, forecasts, baselines, score, observations):
    paired = {r['race_id'] for r in score['per_forecast'] if r['paired']}
    return dict(schema='RACE_AI_PRIVATE_VENUE_PDCA_COUNTS_V1',
        state='PRIVATE_VENUE_PDCA_SCORED' if score['paired_forecasts'] else 'PRIVATE_VENUE_PDCA_PENDING',
        unique_races=len(forecasts), partition_count=len(forecasts), baseline_forecast_count=len(baselines),
        saved_shadow_forecasts=score['saved_shadow_forecasts'], paired_forecasts=score['paired_forecasts'],
        paired_unique_races=len(paired), observation_count=len(observations),
        result_state_counts=dict(Counter(r['state'] for r in score['per_forecast'])),
        scoreboard=deepcopy(score['scoreboard']), training_sha256=training['training_sha256'],
        source_artifact_id=admission['artifact_id'], source_artifact_digest=admission['artifact_digest'],
        source_workflow_run_id=admission['workflow_run_id'], source_head_sha=admission['head_sha'],
        independent_pre_cutoff_receipt_verified=True, provider_permission_confirmed=False,
        baseline_coefficients_changed=False, production_promoted=False, actual_purchases=False,
        accuracy_improvement_proven=False, plaintext_published=False)


def score_private_p1_artifact(raw, metadata, observations, output, *, now,
                              expected_run_id, expected_head_sha):
    """Return aggregate scores after authenticating one complete private archive.

    The caller supplies actual artifact metadata and official observations.
    Duplicate result revisions are rejected; selecting a latest authenticated
    revision belongs to the existing official result reader before this call.
    Every source record is authenticated before any partition is written.
    ``output`` must be absent and becomes a private container whose race-named
    children use the unchanged candidate codec. A failed later partition leaves
    earlier records intact; another invocation never resets that container.
    """
    state_key('production')
    _need(type(now) is datetime and now.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
    root = _output(output)
    admission, forecasts = _verified_private_p1_artifact(raw, metadata, now=now,
        expected_run_id=expected_run_id, expected_head_sha=expected_head_sha)
    _need(admission.get('independent_pre_cutoff_receipt_verified') is True and forecasts,
          'AUTHENTICATED_FORECASTS_REQUIRED')
    training = forecasts[0]['training']
    _need(all(p['training'] == training for p in forecasts), 'SINGLE_TRAINING_REQUIRED')
    race_ids = [official_id(p['snapshot']['race_id']) for p in forecasts]
    _need(len(race_ids) == len(set(race_ids)), 'DUPLICATE_FORECAST_RACE')
    source_sha = hashlib.sha256(raw).hexdigest()
    _need(admission.get('artifact_digest') == 'sha256:'+source_sha, 'SOURCE_ARCHIVE_HASH_MISMATCH')
    _need(type(observations) in (list, tuple), 'OBSERVATIONS_INVALID')
    identities = set()
    for observation in observations:
        _need(type(observation) is dict and type(observation.get('race_id')) is str and
              type(observation.get('captured_at')) is str, 'OBSERVATIONS_INVALID')
        race_id = observation['race_id']
        _need(race_id not in identities, 'DUPLICATE_OBSERVATION')
        identities.add(race_id)
        try:
            captured = ts(observation['captured_at'])
        except ValueError as exc:
            raise ValueError('VENUE_PRIVATE_PDCA_OBSERVATION_CLOCK_INVALID') from exc
        _need(captured <= now, 'FUTURE_OBSERVATION')
    baselines = []
    document = dict(observed_pairwise_p1_bundles=[], learned_pairwise_shadows=[])
    for payload in forecasts:
        baselines.extend(_baseline_rows(payload, metadata))
        document['observed_pairwise_p1_bundles'].append(dict(
            race_id=official_id(payload['snapshot']['race_id']), snapshot=payload['snapshot'],
            suite=payload['baseline_suite']))
        document['learned_pairwise_shadows'].extend(payload['shadows'])
    shadows = read_shadow_rows(document, metadata, baselines)
    score = score_shadows(shadows, baselines, observations)
    summary = _summary(admission, training, forecasts, baselines, score, observations)
    _need(not root.exists() and not root.is_symlink(), 'OUTPUT_EXISTS_DO_NOT_RESET')
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    private_root(root)
    for race_id, forecast in zip(race_ids, forecasts):
        race_baselines = [row for row in baselines if row['race_id'] == race_id]
        race_shadows = [row for row in shadows if row['race_id'] == race_id]
        race_observations = [row for row in observations if row['race_id'] == race_id]
        race_score = score_shadows(race_shadows, race_baselines, race_observations)
        payload = dict(schema='RACE_AI_PRIVATE_VENUE_PDCA_V1', evaluated_at=now.isoformat(),
            summary=_summary(admission, training, [forecast], race_baselines, race_score, race_observations),
            training=deepcopy(training), excluded=[], source_artifact_zip_sha256=source_sha,
            source_artifact_metadata=deepcopy(metadata), forecast_record_sha256=digest(forecast),
            private_forecasts=[forecast], observations=deepcopy(race_observations),
            baseline_rows=race_baselines, shadow_rows=race_shadows, score=race_score)
        child = root/race_id
        _need(not child.exists() and not child.is_symlink(), 'OUTPUT_EXISTS_DO_NOT_RESET')
        result = seal_candidate(payload, child)
        _need(result.get('encrypted_readback_verified') is True, 'PARTITION_READBACK_FAILED')
    summary['encrypted_readback_verified'] = True
    _write(root/'summary.json', _bytes(summary))
    return summary
