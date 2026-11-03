"""Explicit original Race41 labels, never schema-renamed historical evidence."""
import re
from datetime import timedelta

from .retained_prediction_audit import require, decode, byte_sha, valid_sha, moment, _ticket, adapt_labels


def adapt_captured_labels(evidence, imported, read_at):
    races = {r['race_id']:r for r in imported['origin']['races']}; out = []
    for retained in evidence:
        require(type(retained) is dict and set(retained) == {'file_sha256','utf8'} and type(retained['utf8']) is str, 'LABEL_EVIDENCE_FIELDS')
        raw = retained['utf8'].encode('utf-8'); require(byte_sha(raw) == retained['file_sha256'], 'LABEL_BYTE_BINDING')
        label = decode(raw); require(type(label) is dict and type(label.get('race_id')) is str and label['race_id'] in races, 'LABEL_RACE')
        if label.get('schema') == 'RACE_AI_RETAINED_OFFICIAL_OBSERVATION_V1':
            # Already explicit correction/settlement contract, with original bytes.
            out.extend(adapt_labels([retained],imported,read_at)); continue
        require(label.get('schema') == 'RACE41_TODAY_RESULT_LABEL_V1', 'CAPTURED_LABEL_SCHEMA')
        common = {'schema','observation_id','result_observation_revision','supersedes_observation_id','race_id','status',
            'source_url','source_sha256','captured_at','source_published_at','planned_cutoff_at','bundle_sha256','seal_sha256',
            'formal_hit_at_8_all_eligible','official_final_cutoff_authenticated','raw_html_retained','payout_amounts_retained',
            'source_page_cutoff_at','winning_combination','individual_model_receipt','correction_policy',
            'hash_witness_before_planned_cutoff','comparison_subset'}
        optional = {'source_status','body_identity_verified','source_result_status','finish_status_counts',
            'refunded_boat_count','entry_reconciliation','frozen_registration_identity_joined'}
        require(common <= set(label) <= common|optional, 'CAPTURED_LABEL_FIELDS')
        require(all(label[k] is False for k in ('formal_hit_at_8_all_eligible','official_final_cutoff_authenticated',
            'raw_html_retained','payout_amounts_retained','individual_model_receipt')) and
            label['correction_policy'] == 'NEW_EXPLICIT_APPEND_ONLY_REVISION_REQUIRED', 'CAPTURED_LABEL_AUTHORITY')
        race = races[label['race_id']]; rid = race['race_id']; flag = race['hash_witness_before_planned_cutoff']
        require(type(flag) is bool and type(label['hash_witness_before_planned_cutoff']) is bool and
            label['hash_witness_before_planned_cutoff'] == flag and label['comparison_subset'] ==
            ('TIMELY_HASH_WITNESSED_PLANNED_CUTOFF' if flag else 'LATE_HASH_WITNESS_RESEARCH_ONLY'), 'LABEL_WITNESS_CHANGED')
        require(type(label['result_observation_revision']) is int and label['result_observation_revision'] == 1 and
            label['supersedes_observation_id'] is None and type(label['observation_id']) is str and
            re.fullmatch('[A-Za-z0-9_.:/-]{1,300}',label['observation_id']), 'CAPTURED_LABEL_REVISION')
        url = f"https://www.boatrace.jp/owpc/pc/race/raceresult?rno={race['identity']['race_no']}&jcd={rid[9:11]}&hd={rid[:8]}"
        require(label['source_url'] == url and label['planned_cutoff_at'] == race['planned_cutoff_at'] and
            label['bundle_sha256'] == imported['original_file_sha256']['bundle'] and
            label['seal_sha256'] == imported['original_file_sha256']['seal'] and label['source_published_at'] is None, 'CAPTURED_LABEL_BINDING')
        captured = label['captured_at']; source_sha = label['source_sha256']; cutoff = moment(race['planned_cutoff_at'])
        if captured is None:require(source_sha is None, 'UNOBSERVED_SOURCE_HASH')
        else:require(cutoff+timedelta(seconds=120) <= moment(captured) <= moment(read_at) and valid_sha(source_sha), 'LABEL_SOURCE_CLOCK')
        for name in ('body_identity_verified','frozen_registration_identity_joined'):
            if name in label:require(type(label[name]) is bool, 'LABEL_BOOLEAN_METADATA')
        if 'source_status' in label:require(label['source_status'] in ('AVAILABLE','PENDING'), 'LABEL_SOURCE_STATUS')
        if 'source_result_status' in label:require(label['source_result_status'] in ('settled','special','dead_heat'), 'LABEL_RESULT_STATUS')
        if 'entry_reconciliation' in label:require(label['entry_reconciliation'] in (None,'RESULT_EVIDENCE_JOINED_NOT_INDEPENDENTLY_REVIEWED'), 'LABEL_RECONCILIATION')
        if 'finish_status_counts' in label:
            counts=label['finish_status_counts']
            require(type(counts) is dict and set(counts) <= {'FINISHED','欠','転','落','沈','失','妨','不','F','L','エ'} and
                all(type(v) is int and 1 <= v <= 6 for v in counts.values()) and sum(counts.values()) <= 6, 'LABEL_FINISH_COUNTS')
        if 'refunded_boat_count' in label:require(type(label['refunded_boat_count']) is int and 0 <= label['refunded_boat_count'] <= 6, 'LABEL_REFUND_COUNT')
        if label['source_page_cutoff_at'] is not None:moment(label['source_page_cutoff_at'])
        status=label['status']; wins=[]
        require(type(status) is str and status in ('SCORABLE_NORMAL_FINISH','RESULT_PENDING','SOURCE_UNAVAILABLE_OR_INVALID',
            'STOPPED_BEFORE_REQUEST','CUTOFF_REVISION_REQUIRES_REVIEW','UNSUPPORTED_NONSTANDARD_RESULT'), 'LABEL_STATUS')
        if status == 'SCORABLE_NORMAL_FINISH':
            require(captured is not None and label.get('body_identity_verified') is True and
                label.get('frozen_registration_identity_joined') is True and label['source_page_cutoff_at'] == race['planned_cutoff_at'] and
                label.get('entry_reconciliation') == 'RESULT_EVIDENCE_JOINED_NOT_INDEPENDENTLY_REVIEWED' and
                label.get('source_status') == 'AVAILABLE' and label.get('source_result_status') == 'settled' and
                label.get('finish_status_counts') == {'FINISHED':6} and type(label.get('refunded_boat_count')) is int and
                label['refunded_boat_count'] == 0, 'LABEL_SETTLEMENT')
            wins=[_ticket(label['winning_combination'])]; settlement='FINAL'
        else:
            require(label['winning_combination'] is None and (captured is not None or
                status in ('SOURCE_UNAVAILABLE_OR_INVALID','STOPPED_BEFORE_REQUEST')), 'UNSCORED_LABEL')
            settlement='UNSUPPORTED' if status in ('CUTOFF_REVISION_REQUIRES_REVIEW','UNSUPPORTED_NONSTANDARD_RESULT') else 'UNRESOLVED'
        out.append({'race_id':rid,'revision':1,'status':settlement,'winning_triples':wins,
            'unscored_reason':status if settlement != 'FINAL' else None,'original_status':status,
            'source_id':imported['policy']['result_source_id'],'source_sha256':source_sha,'source_url':url,
            'observed_at':captured,'source_published_at':None,'read_at':read_at,'file_sha256':retained['file_sha256'],
            'observation_id':label['observation_id'],'supersedes_observation_id':None,'supersedes_file_sha256':None,
            'provider_revision_reference':None,'registration_basis':'ORIGINAL_BYTE_BOUND_CALLER_JOIN_CLAIM'})
    return out
