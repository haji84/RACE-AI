"""One-shot owner-requested pinned public archive study. Aggregate stdout only."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
from contextlib import redirect_stdout, redirect_stderr
from hashlib import sha256

from .data import SOURCE_COMMIT, PINNED_SOURCE_SHA256, PINNED_SOURCE_BYTES, _verify_file
from .pipeline import run_study, DEFAULT_SPLITS
from .model import digest

OLD = {'trifecta': {'1':421,'2':681,'4':982,'9':1473,'12':1683},
       'exacta': {'1':840,'2':1312}}
OLD_N = 3480
EXPECTED_DATASET = '9bc3fbda8339b32ba178f5c9c39d6623216ad5c2d5519774870ac5491ba0a847'


def public_summary(report):
    audit = report['source_audit']
    final = report['final_period']
    if audit['dataset_sha256'] != EXPECTED_DATASET or audit['unique_races'] != 30713 or final['evaluable'] != OLD_N:
        raise ValueError('SAME_ARCHIVE_AND_TEST_DENOMINATOR_REQUIRED')
    if report.get('production_promoted') is not False:
        raise ValueError('RESEARCH_ONLY_REQUIRED')
    metrics = {}
    for market, ks in OLD.items():
        metrics[market] = {}
        for k, old in ks.items():
            hits = final[market][k]['hits']
            metrics[market][k] = {'hits': hits, 'n': OLD_N, 'rate': hits/OLD_N,
                                  'old_hits': old, 'delta_percentage_points': (hits-old)*100/OLD_N}
    labels = {}
    for key, counts in report['fixed_policy_confidence_test'].items():
        labels[key] = {label: {'n': counts.get(label,{}).get('n',0),
                               'hits': counts.get(label,{}).get('hits',0)} for label in ('HOT','HIGH','MEDIUM','LOW','HOLD')}
    return {'scope': 'REUSED_RETROSPECTIVE_ARCHIVE_NOT_FUTURE_PROOF', 'code_commit': os.environ.get('GITHUB_SHA'),
            'dataset_sha256': audit['dataset_sha256'], 'registered_archive': audit['unique_races'],
            'split_counts': report['split_counts'], 'selected_candidate': report['selected_candidate'],
            'model_sha256': report['model_sha256'], 'contract_sha256': report['evaluation_contract']['contract_sha256'],
            'feature_count': report['feature_count'], 'agari_interactions': report['agari_interactions'],
            'selection_losses': {k:v['tune_joint_top3_log_loss'] for k,v in report['candidate_selection'].items()},
            'test_registered': final['registered'], 'test_evaluable': final['evaluable'],
            'test_predicted_evaluable':final['predicted_evaluable'], 'metrics':metrics,
            'proper_scores':final['proper_scores'], 'confidence':labels,
            'runtime_seconds':report['runtime']['seconds'], 'production_promoted':False,
            'video_labels_supplied':0, 'historical_weather_sidecar_supplied':False,
            'forecast_originals_published':False, 'three_way_contest_proven':False}


def main():
    private = Path(sys.argv[1]).resolve()
    if not private.is_dir() or any((p/'.git').exists() for p in (private,*private.parents)):
        raise ValueError('PRIVATE_RUNNER_PATH_REQUIRED')
    paths=[]
    for name in PINNED_SOURCE_SHA256:
        url=f'https://raw.githubusercontent.com/sumidatadayoshi/keirin-data/{SOURCE_COMMIT}/data/{name}'
        path=private/name
        print(f'ACQUIRE {name}: pinned public source',flush=True)
        proc=subprocess.run(['curl','--fail','--silent','--show-error','--location',
                             '--proto','=https','--proto-redir','=https','--retry','2',
                             '--connect-timeout','15','--max-time','180','--output',str(path),url],
                            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if proc.returncode:
            print(f'HOLD_SOURCE_DOWNLOAD {name} curl_exit={proc.returncode}',flush=True)
            return 2
        try:
            _verify_file(path,PINNED_SOURCE_SHA256)
        except ValueError as err:
            print(f'HOLD_SOURCE_INTEGRITY {name} {err}',flush=True); return 3
        print(f'SOURCE_VERIFIED {name} bytes={PINNED_SOURCE_BYTES[name]} sha256={PINNED_SOURCE_SHA256[name]}',flush=True)
        paths.append(path)
    print('BEGIN_REAL_RETRAIN: chronological fit/tune/calibration/audit/test; no raw output',flush=True)
    with (private/'private-process.log').open('w',encoding='utf-8') as log:
        try:
            with redirect_stdout(log), redirect_stderr(log):
                report=run_study(paths,private/'study',splits=DEFAULT_SPLITS,
                    venue_path=Path(__file__).with_name('fixtures')/'venue_geometry.json',
                    allow_current_geometry_assumption=True,progress=lambda s:print(s,flush=True))
                summary=public_summary(report)
        except Exception as exc:
            print('HOLD_STUDY_FAILED '+type(exc).__name__,file=sys.__stdout__,flush=True)
            return 4
    print('DT_R1_AGGREGATE '+json.dumps(summary,ensure_ascii=False,sort_keys=True,allow_nan=False),flush=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as out:
            out.write('## DT-R1 pinned archive retrospective result\n\n```json\n'+json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+'\n```\n')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
