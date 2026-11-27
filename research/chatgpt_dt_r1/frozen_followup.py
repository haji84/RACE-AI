"""One-time post-archive frozen-model evaluation. No training or promotion.

A later secondary-source snapshot does not prove pre-cutoff availability.
Old history is read from the original pinned databases; only the new interval
comes from the new immutable Git blob. No individual forecast is published.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha1, sha256
from itertools import groupby
import json
from pathlib import Path
import subprocess

from .data import (SOURCE_COMMIT, PINNED_SOURCE_SHA256, _verify_file,
                   load_archives, input_digest)
from .features import FeatureBuilder
from .context import augment_features
from .venues import VenueStore
from .agari import augment_agari
from .abilities import augment_abilities
from .model import RankModel, digest
from .pipeline import forecast_row, summarize_predictions, write_private_json, _result_key

START = '2026-11-23'
END = '2026-11-26'
DAYS = ('2026-11-23', '2026-11-24', '2026-11-25', '2026-11-26')
NEW_COMMIT = '5068110588614856c1bd27b96d437ea55815af57'
NEW_NAME = 'keirin_2026q4.db'
NEW_BLOB = '306a2ea072e4341bc25a35403d165f8c987c2b98'
NEW_BYTES = 48734208
OLD_N = 30713
OLD_END = '2026-11-22'
OLD_DATASET = '9bc3fbda8339b32ba178f5c9c39d6623216ad5c2d5519774870ac5491ba0a847'
ROOT = Path(__file__).parent
MODELS = {
    'initial': ('evidence/20261128/frozen_model.json',
                '562b14ecee281be26660b5a1659e14e9fa08b9a34ff4baca8fa31d7ce13491fa'),
    'five_abilities': ('evidence/20261128-resume/frozen_model.json',
                       '5e022092a35c0258954090c6f3d0f8fa14f03f22511b28d6aa9183f5a38c381c'),
}
GEOMETRY = 'a7d832a2661c6f05167e7a412a55e51183c21e746447f91dac44e14eeb4dfe19'


def check(condition, reason):
    if not condition:
        raise ValueError(reason)


def download(commit, name, target):
    check(not target.exists(), 'SOURCE_DESTINATION_ALREADY_EXISTS')
    url = f'https://raw.githubusercontent.com/sumidatadayoshi/keirin-data/{commit}/data/{name}'
    subprocess.run(['curl', '--fail', '--silent', '--show-error', '--location',
                    '--proto', '=https', '--proto-redir', '=https',
                    '--connect-timeout', '15', '--max-time', '180',
                    '--output', str(target), url], check=True)


def file_pins(path, size, blob):
    """Authenticate the immutable Git object first, then record SHA-256."""
    check(path.stat().st_size == size, 'NEW_ARCHIVE_SIZE_MISMATCH')
    a, b = sha1(), sha256()
    a.update(f'blob {size}\0'.encode())
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            a.update(chunk)
            b.update(chunk)
    check(a.hexdigest() == blob, 'NEW_ARCHIVE_GIT_BLOB_MISMATCH')
    return b.hexdigest()


def select_records(old, new):
    check(all(r['day'] <= OLD_END for r in old), 'OLD_HISTORY_EXCEEDS_PINNED_BOUNDARY')
    targets = [r for r in new if START <= r['day'] <= END]
    check({r['day'] for r in targets} == set(DAYS), 'NEW_WINDOW_INCOMPLETE')
    ids = [r['race_id'] for r in old + targets]
    check(len(ids) == len(set(ids)), 'WINDOW_DUPLICATE_RACE')
    return sorted(old + targets, key=lambda r: (r['day'], r['race_id'])), targets


def blind_target(record):
    # The only target data passed to the feature builder are the card and
    # source metadata. The semantic input digest excludes all outcomes.
    row = {k:v for k,v in record.items()
           if k not in ('result_rows','result_status','finish','top3','archived_weather')}
    check(input_digest(row) == record['input_sha256'], 'BLIND_INPUT_CHANGED')
    return row


def target_features(records):
    builder = FeatureBuilder()
    rows = []
    for day, group in groupby(records, key=lambda r:r['day']):
        group = list(group)
        if START <= day <= END:
            rows.extend(builder.transform(blind_target(row)) for row in group)
        # Outcomes enter history only after all same-day input rows are built.
        builder.update_day(group)
    return rows


def load_models():
    models = {}
    for name, (path, pin) in MODELS.items():
        model = RankModel.from_dict(json.loads((ROOT/path).read_text()))
        check(model.to_dict()['model_sha256'] == pin, 'FROZEN_MODEL_PIN_MISMATCH')
        check(model.fit_meta.get('parameter_information_end_day','') < START,
              'MODEL_PARAMETER_WINDOW_OVERLAP')
        check(model.fit_meta.get('training_last_day','') < START,
              'MODEL_TRAINING_WINDOW_OVERLAP')
        check(model.fit_meta.get('temperature_calibration',{}).get('end_day','') < START,
              'MODEL_CALIBRATION_WINDOW_OVERLAP')
        check(model.fit_meta['context']['venue_file_sha256'] == GEOMETRY,
              'VENUE_PIN_MISMATCH')
        models[name] = model
    # Initial model did not use external context; only retired timing columns
    # and provenance binding changed in its shared feature/score path.
    initial = models['initial']
    for i,n in enumerate(initial.feature_names):
        if n.startswith(('context_', 'history_observed_')):
            check(not initial.weights[:,i].any(), 'INITIAL_CONTEXT_NOT_MASKED')
    for file, expected in models['five_abilities'].fit_meta['source_code_sha256'].items():
        check(sha256((ROOT/file).read_bytes()).hexdigest() == expected,
              'CURRENT_MODEL_SOURCE_CODE_MISMATCH:'+file)
    return models


def evaluate(private, out):
    old_dir = private/'old'
    new_dir = private/'new'
    old_dir.mkdir(mode=0o700)
    new_dir.mkdir(mode=0o700)
    paths = []
    for name in PINNED_SOURCE_SHA256:
        target = old_dir/name
        download(SOURCE_COMMIT, name, target)
        _verify_file(target, PINNED_SOURCE_SHA256)
        paths.append(target)
    old, old_audit = load_archives(paths)
    check(len(old)==OLD_N and old_audit['dataset_sha256']==OLD_DATASET and
          old_audit['last_day']==OLD_END, 'OLD_ARCHIVE_PIN_MISMATCH')
    new_path = new_dir/NEW_NAME
    download(NEW_COMMIT, NEW_NAME, new_path)
    new_sha = file_pins(new_path, NEW_BYTES, NEW_BLOB)
    new, new_audit = load_archives([new_path], expected_sha256={NEW_NAME:new_sha})
    records, targets = select_records(old,new)
    models = load_models()
    geometry = (ROOT/'fixtures/venue_geometry.json').read_bytes()
    check(sha256(geometry).hexdigest()==GEOMETRY, 'VENUE_BYTES_MISMATCH')
    store = VenueStore.from_records(json.loads(geometry))
    base = target_features(records)
    # Match the geometry assumption of the frozen study. The actual research
    # clock is not backdated or presented as a publication clock.
    context = augment_features(base, venue_store=store,
        as_of=datetime.now(timezone.utc).isoformat(), allow_current_geometry_assumption=True)
    full = augment_abilities(augment_agari(context))
    frames = {'initial':context, 'five_abilities':full}
    predictions = {}
    for name,model in models.items():
        rows = frames[name]
        check(all(tuple(row['feature_names'])==model.feature_names for row in rows),
              'FROZEN_FEATURE_SCHEMA_MISMATCH:'+name)
        predictions[name] = [forecast_row(model,row) for row in rows]
    # Commit all private predictions before invoking any scoring function.
    write_private_json(private/'frozen_predictions.private.json', predictions)
    frozen_sha = sha256((private/'frozen_predictions.private.json').read_bytes()).hexdigest()
    by_name = {name:{f['race_id']:f for f in fs} for name,fs in predictions.items()}
    common = [r for r in targets if _result_key(r) is not None and
              all(index[r['race_id']]['status']=='READY' for index in by_name.values())]
    common_ids = {r['race_id'] for r in common}
    report = {
        'schema':'dt-r1-frozen-followup-v1',
        'scope':'NEW_DATE_WINDOW_RETROSPECTIVE_NOT_PROSPECTIVE_NOT_OFFICIAL',
        'window':{'start':START,'end':END},
        'source':{'old_commit':SOURCE_COMMIT,'old_dataset_sha256':OLD_DATASET,
                  'new_commit':NEW_COMMIT,'new_git_blob':NEW_BLOB,'new_bytes':NEW_BYTES,
                  'new_sha256':new_sha,'new_dataset_sha256':new_audit['dataset_sha256']},
        'models':{k:v.to_dict()['model_sha256'] for k,v in models.items()},
        'baseline_runtime':'current compatible schema; external context and retired full-lap weights are zero; not original runtime byte identity',
        'model_weights_retrained':False,'selection_after_score':False,
        'history_policy':'original pinned history through November 22, then only earlier days of new window',
        'registered':len(targets),'common_evaluable':len(common),
        'registered_by_day':{d:sum(r['day']==d for r in targets) for d in DAYS},
        'private_forecast_bytes_sha256':frozen_sha,
        'private_forecasts_retained':False,
        'all_targets':{k:summarize_predictions(fs,targets) for k,fs in predictions.items()},
        'common_targets':{k:summarize_predictions([f for f in fs if f['race_id'] in common_ids],common)
                          for k,fs in predictions.items()},
        'confidence':'HOLD_UNVALIDATED_TRANSFER','odds':'NOT_EVALUATED',
        'reviewed_video_races':0,'prospective_races':0,'three_way_contest_races':0,
        'production_promoted':False,
    }
    write_private_json(out,report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('private',type=Path)
    args = parser.parse_args()
    private = args.private.resolve()
    check(private.is_dir() and not any((p/'.git').exists() for p in
          (private,*private.parents)), 'PRIVATE_RUNNER_PATH_REQUIRED')
    report = evaluate(private,private/'aggregate.json')
    print('DT_R1_FROZEN_FOLLOWUP '+json.dumps(report,sort_keys=True,allow_nan=False),flush=True)


if __name__=='__main__':
    main()
