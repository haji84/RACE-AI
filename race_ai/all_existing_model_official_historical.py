"""Explicit recent historical RESULT labels with actual current capture clocks.

This changes no native snapshot, forecast or publication clock. Navigation is
still the existing published date controls; unavailable dates remain HOLD.
"""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import re
from . import all_existing_model_official_recovery as recovery

REQUEST='RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V3'
MANIFEST='RACE_AI_OFFICIAL_RESULT_COLLECT_INPUT_V3'
PROBE_MODE='FIXED_ATTEMPT_TWO_HISTORICAL_SINGLE_NORMAL_UI_PROBE'
CONTINUATION_MODE='FIXED_ATTEMPT_TWO_HISTORICAL_AFTER_VERIFIED_SAME_HOST_PROBE'

def validate_window(request,issued_at,expires_at):
    if request.get('schema')!=REQUEST:return
    return validate_capture_window(request['manifest'],issued_at,expires_at)

def validate_capture_window(manifest,issued_at,expires_at):
    midnight=datetime.fromisoformat(manifest['execution_day']).replace(tzinfo=timezone(timedelta(hours=9)))+timedelta(days=1)
    recovery.need(recovery.clock(issued_at)<recovery.clock(expires_at)<=midnight,'HISTORICAL_CAPTURE_DAY_WINDOW')

def validate_request(value,now):
    from scripts import all_existing_model_official_result_collect as collector
    need=recovery.need
    base={'schema','repository_id','pull_request','mode','probe_sport','old_journal_artifact_id','manifest'}
    extra={'probe_journal_artifact_id','probe_result_artifact_id','probe_request_sha256'}
    need(type(value) is dict and value.get('schema')==REQUEST and value.get('mode') in (PROBE_MODE,CONTINUATION_MODE) and
        set(value)==(base|extra if value['mode']==CONTINUATION_MODE else base),'HISTORICAL_REQUEST')
    need(type(value['repository_id']) is int and value['repository_id']==recovery.REPOSITORY_ID and
        type(value['pull_request']) is int and value['pull_request']==71 and value['probe_sport'] in ('autorace','keirin') and
        value['old_journal_artifact_id']==recovery.OLD_ARTIFACT,'HISTORICAL_OWNER_SCOPE')
    manifest=collector._manifest(value['manifest'],recovery.clock(now))
    need(manifest['schema']==MANIFEST and manifest['allow_order_only'] is True,'HISTORICAL_MANIFEST_REQUIRED')
    old=[p for p in manifest['prior_journal_artifacts'] if p['id']==recovery.OLD_ARTIFACT]
    need(len(old)==1 and old[0]['run_id']==recovery.OLD_RUN and old[0]['head_sha']==recovery.OLD_HEAD,'FIXED_OLD_JOURNAL')
    if value['mode']==CONTINUATION_MODE:
        jp=[p for p in manifest['prior_journal_artifacts'] if p['id']==value['probe_journal_artifact_id']]
        rp=[p for p in manifest['checkpoint_artifacts'] if p['id']==value['probe_result_artifact_id']]
        need(type(value['probe_request_sha256']) is str and re.fullmatch('[a-f0-9]{64}',value['probe_request_sha256']) and
            len(jp)==len(rp)==1 and jp[0]['id']!=recovery.OLD_ARTIFACT and jp[0]['run_id']==rp[0]['run_id'] and
            jp[0]['head_sha']==rp[0]['head_sha'] and jp[0]['run_id']!=recovery.OLD_RUN,'HISTORICAL_PROBE_PINS')
    return deepcopy(value)

def issue_consume_capsule(data,key):
    request=validate_request(data['request'],recovery.clock(data['issued_at']))
    if request['mode']==PROBE_MODE:return recovery.issue_consume_capsule(data,key)
    from .all_existing_model_official_continuation import issue_consume_capsule as continuation
    return continuation(data,key)
