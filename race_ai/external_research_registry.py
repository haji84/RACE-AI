"""Whitelist-only projection of private research originals, never formal scores.

A hash establishes integrity, not independently authenticated pre-cutoff time.
Private inputs, picks and storage URLs stay out of the GitHub manifest.
"""
from collections import Counter
from datetime import datetime,timezone,timedelta
import re
from .actions_contract import digest
from .autorace_personal_baseline import MODEL_ID, MODEL_VERSION

SCHEMA='RACE_AI_EXTERNAL_RESEARCH_MANIFEST_V1'
GRADE='RESEARCH_ORIGINAL_INTACT_PRE_CUTOFF_RECEIPT_UNVERIFIED'
FIELDS={'race_id','sport','model_id','model_version','phase','generated_at','cutoff_at',
        'original_prediction_sha256','input_sha256','evidence_grade','formal_hit_at_8_eligible',
        'independent_receipt_verified'}

def need(ok,why):
    if not ok:raise ValueError(why)

def moment(s):
    value=datetime.fromisoformat(s.replace('Z','+00:00'))
    need(value.utcoffset() is not None,'research time offset missing')
    return value

def validate_entry(row,day):
    need(set(row)==FIELDS,'research entry whitelist mismatch')
    need(row['sport']=='autorace' and row['model_id']==MODEL_ID and row['model_version']==MODEL_VERSION,'unadmitted research model')
    need(re.fullmatch(r'autorace:'+re.escape(day)+r':(?:sanyo|kawaguchi):(?:[1-9]|1[0-2])',row['race_id']) is not None,'research race/day mismatch')
    need(row['phase']=='A_PRE_TRIAL_INPUT_NO_SAME_DAY_TRIAL_USED','unadmitted research phase')
    need(row['evidence_grade']==GRADE and row['formal_hit_at_8_eligible'] is False and
         row['independent_receipt_verified'] is False,'research cannot be promoted by manifest')
    need(moment(row['generated_at'])<moment(row['cutoff_at']),'research generated after cutoff')
    need(moment(row['cutoff_at']).astimezone(timezone(timedelta(hours=9))).date().isoformat()==day,'research cutoff day mismatch')
    need(all(re.fullmatch('[a-f0-9]{64}',row[k]) for k in ('original_prediction_sha256','input_sha256')),'research SHA missing')

def build_manifest(originals,*,day):
    need(type(originals) is list and len(originals)<=1000,'bounded research import required')
    entries={}
    for original in originals:
        need(original.get('prediction_sha256')==digest({k:v for k,v in original.items() if k!='prediction_sha256'}),'research original hash mismatch')
        need(original.get('schema')=='RACE_AI_AUTORACE_ASSISTANT_SINGLE_RUN_RESEARCH_FORECAST_V1','unadmitted private original schema')
        need(original.get('input_sha256')==digest(original['source']),'research input hash mismatch')
        need(original.get('formal_hit_at_8_eligible') is False and original.get('external_pre_cutoff_receipt') is None and
             original.get('official_prediction') is False and original.get('bet_placed') is False,'private research grade must stay unverified')
        need(original['source']['race_id']==original['race_id'] and
             original['source']['cutoff_at_jst']==original['cutoff_at_jst'],'private source/race mismatch')
        row=dict(race_id=original['race_id'],sport='autorace',model_id=original['model_id'],model_version=original['model_version'],
            phase=original['phase'],generated_at=original['generated_at_jst'],cutoff_at=original['cutoff_at_jst'],
            original_prediction_sha256=original['prediction_sha256'],input_sha256=original['input_sha256'],
            evidence_grade=GRADE,formal_hit_at_8_eligible=False,independent_receipt_verified=False)
        validate_entry(row,day)
        key=(row['race_id'],row['model_id'],row['phase'])
        need(key not in entries or entries[key]==row,'conflicting research originals for one key')
        entries[key]=row
    out=dict(schema=SCHEMA,day_jst=day,entries=[entries[k] for k in sorted(entries)],
             scope='EXPLICITLY_AUDITED_PRIVATE_ORIGINALS_NOT_ALL_EXTERNAL_STORES',private_picks_included=False)
    out['manifest_sha256']=digest(out)
    return out

def summarize(manifest,*,day):
    need(manifest.get('schema')==SCHEMA and manifest.get('day_jst')==day and manifest.get('private_picks_included') is False,'research manifest scope mismatch')
    need(manifest.get('manifest_sha256')==digest({k:v for k,v in manifest.items() if k!='manifest_sha256'}),'research manifest hash mismatch')
    rows=manifest['entries'];need(type(rows) is list and len(rows)<=1000,'bounded manifest required')
    for row in rows:validate_entry(row,day)
    keys=[(r['race_id'],r['phase'],r['model_id']) for r in rows]
    need(len(keys)==len(set(keys)),'duplicate research manifest entry')
    return dict(schema='RACE_AI_EXTERNAL_RESEARCH_SUMMARY_V1',research_forecast_count=len(rows),
        distinct_research_races=len({r['race_id'] for r in rows}),model_count=len({r['model_id'] for r in rows}),
        by_model=dict(Counter(r['model_id'] for r in rows)),entries=rows,
        formal_forecast_count=0,formal_hit_rate=None,formal_roi=None,
        included_in_formal_scoreboard=False,evidence_grade=GRADE,manifest_sha256=manifest['manifest_sha256'],
        scope=manifest['scope'])


def attach_to_report(report,manifest,*,day):
    """Integrate visibility, not evidence grades or official performance denominators."""
    summary=summarize(manifest,day=day)
    report['external_research']=summary
    for model in report.get('model_coverage',{}).get('models',[]):
        model['external_research_forecasts']=summary['by_model'].get(model['model_id'],0)
        if model['external_research_forecasts']:
            model['external_research_evidence_grade']=GRADE
            model['external_research_in_formal_scoreboard']=False
    report['model_coverage']['external_research_count']=summary['research_forecast_count']
    report['model_coverage']['external_research_does_not_change_saved_forecasts']=True
    return report
