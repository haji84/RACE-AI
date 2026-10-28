"""Development-only audit of retained predictions; never runs models or sources.

Shares EvaluationJournal's canonical identity digest, final-reveal.lock and
exposed-races protocol without importing its model-dependent modules. Clock,
source and publication claims remain claims. This is not a predeclared test or
an independently authenticated result/immutable storage service. A different
or deleted registry cannot establish non-exposure. Boat venue compatibility is
limited to official boatrace-jcd-XX / XX aliases (01..24).
"""
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import re
import stat

from .evaluation_metrics import retained_report

MAX_BYTES = 100_000_000
ROLES = {'facts', 'bundle', 'seal', 'manifest', 'proof', 'registry'}
JST = timezone(timedelta(hours=9))
ALIASES = {'name-bound-display':'official-beforeinfo-display-pl',
           'name-bound-original':'official-display-original-pl'}


class RetainedAuditError(ValueError):
    """Fixed local contract failures; no private payload in messages."""


def require(ok, code='RETAINED_AUDIT_REJECTED'):
    if not ok:
        raise RetainedAuditError(code)


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise RetainedAuditError('INVALID_JSON') from None


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def byte_sha(raw):
    return hashlib.sha256(raw).hexdigest()


def valid_sha(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def moment(value):
    require(type(value) is str and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)', value), 'INVALID_CLOCK')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(result.utcoffset() is not None, 'INVALID_CLOCK')
        return result.astimezone(timezone.utc)
    except ValueError:
        raise RetainedAuditError('INVALID_CLOCK') from None


def decode(raw):
    require(type(raw) is bytes and len(raw) <= MAX_BYTES, 'INPUT_SIZE')
    def unique(pairs):
        result = {}
        for k,v in pairs:
            require(k not in result, 'DUPLICATE_JSON_KEY')
            result[k] = v
        return result
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique,
                           parse_constant=lambda _: require(False, 'NONFINITE_JSON'))
        canonical(value)
        return value
    except RetainedAuditError:
        raise
    except (ValueError, UnicodeError, RecursionError):
        raise RetainedAuditError('INVALID_JSON') from None


def regular_bytes(path):
    path = Path(path)
    require(not path.is_symlink() and not getattr(path, 'is_junction', lambda:False)(), 'LINK_REJECTED')
    before = path.stat()
    require(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_BYTES, 'INPUT_SIZE_OR_TYPE')
    with path.open('rb') as stream:
        # BufferedReader may reserve the requested size even for a tiny file.
        # One byte beyond the checked size detects growth without allocating
        # the full100MB admission cap for every exposure marker.
        raw = stream.read(before.st_size+1)
        opened = os.fstat(stream.fileno())
    after = path.stat()
    identity = lambda s:(s.st_ino,s.st_size,s.st_mtime_ns)
    require(identity(before) == identity(opened) == identity(after) and len(raw) == before.st_size, 'INPUT_CHANGED')
    return raw


def _create_raw(path, raw):
    require(type(raw) is bytes and len(raw) <= MAX_BYTES, 'OUTPUT_SIZE')
    require(not path.is_symlink(), 'LINK_REJECTED')
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    require(regular_bytes(path) == raw, 'WRITE_READBACK_CHANGED')


def _create(path, value):
    _create_raw(path, canonical(value)+b'\n')


def _read(path):
    raw = regular_bytes(path); value = decode(raw)
    require(raw == canonical(value)+b'\n', 'NONCANONICAL_JOURNAL')
    return value


def _directory(path, *, create=False, parents=False):
    for part in [path, *path.parents]:
        require(not part.is_symlink() and not getattr(part, 'is_junction', lambda:False)(), 'LINK_REJECTED')
    if create:
        path.mkdir(parents=parents, exist_ok=True)
    require(path.is_dir(), 'DIRECTORY_REQUIRED')


def _ticket(value):
    if type(value) is str:
        require(re.fullmatch('[1-6]-[1-6]-[1-6]', value), 'INVALID_TICKET')
        value = [int(n) for n in value.split('-')]
    require(type(value) in (list,tuple) and len(value) == 3 and
            all(type(n) is int and 1 <= n <= 6 for n in value) and len(set(value)) == 3, 'INVALID_TICKET')
    return list(value)


def _race_identity(rid):
    require(type(rid) is str and re.fullmatch(r'\d{8}-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])', rid), 'RACE_IDENTITY')
    try:
        event_day = date.fromisoformat(f'{rid[:4]}-{rid[4:6]}-{rid[6:8]}').isoformat()
    except ValueError:
        raise RetainedAuditError('RACE_IDENTITY') from None
    return {'sport':'boat', 'venue':'boatrace-jcd-'+rid[9:11],
            'event_date_jst':event_day, 'race_no':int(rid[-2:])}


def _forbid_results(value):
    forbidden = {'results','labels','winning_combination','winning_triples','ordered_top3',
                 'payout','payouts','odds','hit','hit8','known_results','actual_result_values'}
    if type(value) is dict:
        require(not forbidden.intersection(value), 'RESULT_BEARING_IMPORT')
        for child in value.values(): _forbid_results(child)
    elif type(value) is list:
        for child in value: _forbid_results(child)


def _original_case(fact, source, identity, as_of):
    """Check the pinned B bridge's input projection, without importing it.

    Only the original two B statistics are possible. This is validation of
    retained input evidence, never feature enrichment or model inference.
    """
    participants = []
    for boat in sorted(fact['boats'],key=lambda b:b['lane']):
        features = {}
        missing = {'recent_mean_finish':'NO_PRIOR_SAMPLES','recent_mean_st':'NO_PRIOR_SAMPLES',
            'course_mean_finish':'NO_VERIFIED_COURSE','course_mean_st':'NO_VERIFIED_COURSE',
            'exhibition_time_seconds':'MISSING','exhibition_start_seconds':'MISSING'}
        for key,maximum,transform in (('national_win_rate',10,'official_B_national_win_rate_points_v1'),
                                     ('motor_top2_rate',100,'official_B_motor_top2_percent_v1')):
            value = boat.get(key)
            if value is None: missing[key] = 'MISSING'
            else:
                try: finite = type(value) in (int,float) and math.isfinite(value)
                except (OverflowError,ValueError): finite = False
                require(finite and 0 <= value <= maximum, 'B_FEATURE_NUMBER')
                features[key] = {'value':value,'sample_n':None,'source_id':source['source_id'],'transform_id':transform}
        participants.append({'lane':boat['lane'],'registration_no':boat['racer_registration_id'],
                             'features':features,'missing':missing})
    snapshot = {'schema':'RACE_AI_BOAT_OBSERVED_PAIRWISE_V1','scope':'OPERATOR_SUPPLIED_RESEARCH',
        'race_id':f"boat:{identity['event_date_jst']}:{identity['venue']}:{identity['race_no']}",
        'event_date_jst':identity['event_date_jst'],'venue':identity['venue'],'race_revision':1,
        'race_source_id':source['source_id'],'sales_cutoff_at':fact['closed_at'],'as_of':as_of,
        'stage':'P0','sources':[source],'participants':participants}
    return {'case_id':fact['race_id'],'stage':'P0','legacy':{'boats':[
        {'lane':b['lane'],'national_win_rate':b.get('national_win_rate')} for b in fact['boats']]},
        'source_manifest_sha256':byte_sha(canonical(source)+b'\n'),'observed_pairwise_snapshot':snapshot}


def adapt_race39(files, expected_sha256):
    """Validate only the six outcome-free original byte files. No result files."""
    require(type(files) is dict and type(expected_sha256) is dict and set(files) == set(expected_sha256) == ROLES, 'ORIGIN_CLOSURE')
    values = {}
    for role in sorted(ROLES):
        require(valid_sha(expected_sha256[role]) and type(files[role]) is bytes and
                byte_sha(files[role]) == expected_sha256[role], 'ORIGIN_HASH_CHANGED')
        values[role] = decode(files[role]); require(type(values[role]) is dict, 'ORIGIN_OBJECT')
        _forbid_results(values[role])
    f,b,s,m,p,inventory = [values[k] for k in ('facts','bundle','seal','manifest','proof','registry')]
    for value,schema in ((f,'RACE39_TODAY_PRIVATE_NORMALIZED_FACTS_V1'),(b,'RACE39_TODAY_ALL19_PRIVATE_PREDICTION_BUNDLE_V1'),
                         (s,'RACE39_TODAY_LOCAL_READBACK_SEAL_V1'),(m,'RACE39_TODAY_CALLER_MANIFEST_V1'),
                         (p,'RACE39_TODAY_EXECUTION_PROOF_V1'),
                         (inventory,'RACE38_SOURCE_ONLY_MODEL_INVENTORY_V1')):
        require(value.get('schema') == schema, 'ORIGIN_SCHEMA')
    observation_id = m.get('observation_id')
    require(type(observation_id) is str and 1 <= len(observation_id) <= 200 and
            all(value.get('observation_id') == observation_id for value in (f,b,s,p)), 'ORIGINAL_OBSERVATION_BINDING')
    require(p.get('manifest_sha256') == expected_sha256['manifest'] and valid_sha(m.get('caller_sha256')) and
            p.get('caller_sha256') == m['caller_sha256'], 'EXECUTION_PROOF_BINDING')
    require(set(inventory) <= {'schema','review_date_jst','roots','pins','actual_result_values_read','network_used',
                              'models','counts','profiles','duplicates','archived_boat_subset'}, 'REGISTRY_FIELDS')
    require(inventory.get('actual_result_values_read',False) is False and inventory.get('network_used',False) is False, 'REGISTRY_NOT_SOURCE_ONLY')
    model_fields = {'model_id','model_version','source_root','source_pin','source_file','entrypoint','line','kind','required_input_profile','top8','notes'}
    require(type(inventory.get('models')) is list and all(type(x) is dict and set(x) <= model_fields for x in inventory['models']), 'REGISTRY_FIELDS')
    registry = [x for x in inventory['models'] if x['kind'] != 'synthetic_test_only']
    require(b['model_registry'] == registry and len(registry) == 19, 'REGISTRY_CHANGED')
    mids = [x['model_id'] for x in registry]
    require(all(type(x) is str and re.fullmatch('[A-Za-z0-9_.-]{1,200}',x) for x in mids) and len(set(mids)) == 19, 'MODEL_IDENTITY')
    require(all(type(x['model_version']) is str and 1 <= len(x['model_version']) <= 200 for x in registry), 'MODEL_VERSION')
    require(m['registry_sha256'] == expected_sha256['registry'] and b['manifest_sha256'] == expected_sha256['manifest'], 'MANIFEST_BINDING')
    require(b['model_code_sha256'] == m['model_source_sha256'] and type(b['model_code_sha256']) is dict and
            b['model_code_sha256'] and all(valid_sha(v) for v in b['model_code_sha256'].values()), 'CODE_BINDING')
    require(b['normalized_facts_sha256'] == s['normalized_facts_sha256'] == p['normalized_facts_sha256'] == expected_sha256['facts'], 'FACTS_BINDING')
    require(s['bundle_sha256'] == p['bundle_sha256'] == expected_sha256['bundle'] and p['seal_sha256'] == expected_sha256['seal'], 'SEAL_BINDING')
    require(p['phase'] == 'COMPLETE' and b['stage'] == 'P0' and b['no_outcome_or_odds_input'] is True, 'ORIGIN_NOT_COMPLETE')
    require(all(value.get(flag) is False for value,flags in ((b,('external_timestamp_verified','formal_prospective_forecast')),
        (s,('external_timestamp_verified','formal_prospective_forecast','local_storage_immutable'))) for flag in flags), 'UNSUPPORTED_ORIGIN_AUTHORITY')
    require(f['source'] == b['source'] and f['source_publication_at'] is None and f['raw_lzh_or_text_retained'] is False and
            f['independent_capture_timestamp'] is False, 'SOURCE_BINDING')
    source = b['source']; n = f['normalized']
    require(set(source) == {'source_id','source_url','source_sha256','source_rights_ref','published_at','captured_at','evidence_basis'} and
            source['source_id'] == observation_id and m['source_url'] == source['source_url'] and m['day_jst'] == n['date_jst'], 'SOURCE_IDENTITY_BINDING')
    require(source['source_sha256'] == n['source_sha256'] == p['source_archive_sha256'] and valid_sha(source['source_sha256']), 'SOURCE_BINDING')
    require(source['published_at'] is None and source['evidence_basis'] == 'CAPTURED_BY_CLAIM' and
            source['captured_at'] == n['first_observed_at'] and source['source_url'] == n['source_url'], 'SOURCE_CLOCK_BINDING')
    capture = moment(source['captured_at']); written = moment(b['before_write_local_clock_claimed'])
    readback = moment(s['readback_at_local_clock_claimed']); completed = moment(p['completed_at_local_clock_claimed'])
    require(capture <= written <= readback <= completed, 'ORIGINAL_CLOCK_ORDER')
    normalized = [r for venue in n['venues'] for r in venue['races']]
    require(len(normalized) == n['races'] == n['complete_six_boat_races'] == len(b['races']) == len(s['races']) == 168, 'FULL_COHORT_REQUIRED')
    fact_map = {r['race_id']:r for r in normalized}; seal_map = {r['race_id']:r for r in s['races']}
    require(len(fact_map) == len(seal_map) == 168 and set(fact_map) == set(seal_map) == {r['race_id'] for r in b['races']}, 'RACE_SET_CHANGED')
    all_tickets = set(itertools.permutations(range(1,7),3)); out = []; forecasts = 0
    for race in b['races']:
        rid = race['race_id']; identity = _race_identity(rid); fact = fact_map[rid]; seal = seal_map[rid]
        require(identity['event_date_jst'] == n['date_jst'] and race['stage'] == 'P0', 'RACE_DAY_OR_STAGE')
        require(set(race) == {'race_id','planned_cutoff_at','race_revision_claim','stage','as_of','input','input_sha256','generated_at',
                             'state','models','actual_cutoff_verified','roster_withdrawals_verified','formal_prospective_forecast'} and
                type(race['race_revision_claim']) is int and race['race_revision_claim'] == 1 and
                all(race[k] is False for k in ('actual_cutoff_verified','roster_withdrawals_verified','formal_prospective_forecast')), 'RACE_EVIDENCE_FIELDS')
        require(set(fact) == {'race_id','boats','closed_at','preview_available'} and fact['preview_available'] is False, 'B_RACE_FIELDS')
        cutoff = moment(race['planned_cutoff_at']); asof = moment(race['as_of'])
        require(cutoff.astimezone(JST).date().isoformat() == n['date_jst'] and capture <= asof <= written, 'RACE_CLOCK_ORDER')
        require(fact['closed_at'] == seal['planned_cutoff_at'] == race['planned_cutoff_at'] and seal['bundle_sha256'] == expected_sha256['bundle'], 'CUTOFF_BINDING')
        boats = fact['boats']; require(type(boats) is list and len(boats) == 6 and {x['lane'] for x in boats} == set(range(1,7)), 'SIX_PARTICIPANTS_REQUIRED')
        boat_fields = {'lane','racer_registration_id','motor_no','boat_no','name','grade','national_win_rate','local_win_rate',
            'national_top2_rate','local_top2_rate','motor_top2_rate','boat_top2_rate','average_st','display_time','preview_course','entry_status'}
        require(all(type(x) is dict and set(x) <= boat_fields and
                    all(x.get(k) is None for k in ('average_st','display_time','preview_course')) and
                    x.get('entry_status','listed') == 'listed' for x in boats), 'B_BOAT_FIELDS')
        for field in ('motor_no','boat_no'):
            require(all(type(x.get(field)) is int and 1 <= x[field] <= 999 for x in boats) and
                    len({x[field] for x in boats}) == 6, 'B_ALLOCATION_IDENTITY')
        registrations = {str(x['lane']):x['racer_registration_id'] for x in boats}
        require(all(type(x) is str and re.fullmatch(r'\d{4}',x) for x in registrations.values()) and len(set(registrations.values())) == 6, 'REGISTRATION_IDENTITY')
        closed = race['state'] == 'CLOSED_BEFORE_INFERENCE'
        require(closed or race['state'] == 'COMPUTED_BEFORE_PLANNED_CUTOFF', 'UNSUPPORTED_ORIGINAL_STATE')
        if closed:
            require(race['generated_at'] is None and race['input'] is None and race['input_sha256'] is None and asof >= cutoff, 'NULL_CLOCKS_REQUIRED')
        else:
            generated = moment(race['generated_at']); case = race['input']
            require(asof <= generated < cutoff and generated <= written and type(case) is dict, 'FORECAST_CLOCK_ORDER')
            require(set(case) == {'case_id','stage','legacy','source_manifest_sha256','observed_pairwise_snapshot'} and
                    case['case_id'] == rid and case['stage'] == 'P0' and case['source_manifest_sha256'] == byte_sha(canonical(source)+b'\n'), 'INPUT_BINDING')
            require(valid_sha(race['input_sha256']) and race['input_sha256'] == byte_sha(canonical(case)+b'\n'), 'INPUT_HASH_CHANGED')
            require(case == _original_case(fact,source,identity,race['as_of']), 'ORIGINAL_B_PROJECTION_CHANGED')
            snap = case['observed_pairwise_snapshot']
            require(snap['race_id'] == f"boat:{n['date_jst']}:{identity['venue']}:{identity['race_no']}" and
                    snap['venue'] == identity['venue'] and snap['as_of'] == race['as_of'] and snap['stage'] == 'P0' and
                    snap['sales_cutoff_at'] == race['planned_cutoff_at'] and snap['sources'] == [source], 'SNAPSHOT_BINDING')
            require({str(x['lane']):x['registration_no'] for x in snap['participants']} == registrations and len(snap['participants']) == 6, 'SNAPSHOT_PARTICIPANTS')
        timely = not closed and readback < cutoff
        require(type(seal['local_pre_cutoff_readback']) is bool and seal['local_pre_cutoff_readback'] == timely, 'READBACK_FLAG_CHANGED')
        require(len(race['models']) == 19 and [x['model_id'] for x in race['models']] == mids, 'MODEL_MATRIX_CHANGED')
        models = []
        for entry,registered in zip(race['models'],registry):
            require(entry['stage'] == 'P0' and entry['model_version'] == registered['model_version'] and entry['status'] in ('FORECAST','NO_FORECAST'), 'MODEL_VERSION_OR_STATE')
            model = deepcopy(entry); model['numerical_alias_of'] = ALIASES.get(entry['model_id'])
            if entry['status'] == 'FORECAST':
                require(not closed and valid_sha(entry.get('forecast_sha256')), 'FORECAST_EVIDENCE')
                rows = entry['scores120']; require(type(rows) is list and len(rows) == 120, 'COMPLETE_SCORE_ARRAY')
                pairs = []
                for row in rows:
                    require(type(row) is dict and set(row) == {'combination','score'} and type(row['score']) in (int,float), 'SCORE_FIELDS')
                    try: finite = math.isfinite(row['score'])
                    except (OverflowError,ValueError): finite = False
                    require(finite and 0 <= row['score'] <= 1, 'SCORE_NUMBER')
                    pairs.append((_ticket(row['combination']),row['score']))
                require({tuple(t) for t,_ in pairs} == all_tickets and pairs == sorted(pairs,key=lambda x:(-x[1],x[0])), 'SCORE_ORDER_OR_COVERAGE')
                top8 = [_ticket(t) for t in entry['top8']]
                require(len(top8) == 8 and top8 == [t for t,_ in pairs[:8]], 'TOP8_SCORE_MISMATCH')
                model['top8'] = top8; model['score_array_sha256'] = digest(rows)
                model.pop('scores120')  # Exact original arrays remain in the byte-bound origin bundle.
                model['inner_digest_verification'] = 'FULL_SOURCE_MODEL_PREIMAGE_NOT_RETAINED'
                if entry.get('method') == 'PINNED_LEGACY_NUMERIC_FORMULA_AND_PL_KERNEL':
                    require(digest({k:v for k,v in entry.items() if k != 'forecast_sha256'}) == entry['forecast_sha256'], 'LEGACY_INNER_DIGEST_CHANGED')
                    model['inner_digest_verification'] = 'LEGACY_PREIMAGE_VERIFIED'
                forecasts += 1
            else:
                require(entry['top8'] is None and entry['scores120'] is None and type(entry.get('reason')) is str and entry['reason'], 'MISSING_FORECAST_REASON')
                model['inner_digest_verification'] = 'NO_FORECAST'
            models.append(model)
        out.append({'race_id':rid, 'identity':identity, 'registration_ids':registrations, 'stage':'P0',
            'planned_cutoff_at':race['planned_cutoff_at'], 'as_of':race['as_of'], 'generated_at':race['generated_at'],
            'input_sha256':race['input_sha256'], 'state':race['state'], 'models':models,
            'local_pre_cutoff_readback':timely, 'actual_cutoff_verified':race['actual_cutoff_verified'],
            'roster_withdrawals_verified':race['roster_withdrawals_verified']})
    counts = Counter(r['state'] for r in out)
    require(counts == {'CLOSED_BEFORE_INFERENCE':37,'COMPUTED_BEFORE_PLANNED_CUTOFF':131} and forecasts == 524, 'SOURCE_COHORT_COUNTS')
    require(sorted(sum(m['status']=='FORECAST' for r in out for m in r['models'] if m['model_id']==mid) for mid in mids) == [0]*15+[131]*4, 'FOUR_RUNNING_MODEL_COVERAGE')
    require(p['total_races'] == 168 and p['registry_models'] == 19 and p['model_slots'] == 3192 and
            p['actual_forecasts'] == forecasts and p['races_computed'] == 131 and
            p['races_local_pre_cutoff_readback'] == sum(r['local_pre_cutoff_readback'] for r in out), 'ORIGINAL_PROOF_COUNTS')
    return {'models':[{**deepcopy(x),'numerical_alias_of':ALIASES.get(x['model_id'])} for x in registry],
        'races':out, 'original_completed_at':p['completed_at_local_clock_claimed'],
        'original_readback_at':s['readback_at_local_clock_claimed'], 'original_model_code_sha256':b['model_code_sha256'],
        'original_source_code_sha256':m['source_code_sha256'], 'source':source,
        'execution_code_identity_for_missing_models':'NOT_ESTABLISHED_BY_EXECUTED_CODE_SET'}


def validate_policy(policy, origin, now):
    require(type(policy) is dict and set(policy) == {'schema','mode','declared_at','prior_result_exposure','result_source_id','authorization_ref','settlement_policy'}, 'POLICY_FIELDS')
    require(policy['schema'] == 'RACE_AI_RETAINED_AUDIT_POLICY_V1' and policy['mode'] == 'RETAINED_PREDICTION_AUDIT', 'POLICY_MODE')
    require(policy['prior_result_exposure'] in ('UNKNOWN','ALREADY_EXPOSED_RESEARCH') and
            all(type(policy[k]) is str and re.fullmatch('[A-Za-z0-9_.:/-]{1,200}',policy[k]) for k in ('result_source_id','authorization_ref')), 'POLICY_AUTHORITY')
    require(policy['settlement_policy'] in ('NORMAL_FINISH_ONLY','OFFICIAL_REVISIONS_WITH_CANCELLATION_AND_DEAD_HEAT'), 'SETTLEMENT_POLICY')
    require(moment(origin['original_completed_at']) < moment(policy['declared_at']) <= moment(now), 'CURRENT_POLICY_CLOCK')
    return deepcopy(policy)


def validate_label_request(request, imported, expected_sha256):
    require(valid_sha(expected_sha256) and digest(request) == expected_sha256, 'LABEL_REQUEST_HASH_CHANGED')
    require(type(request) is dict and set(request) == {'schema','observations'} and
            request['schema'] == 'RACE_AI_RETAINED_LABEL_REQUEST_V1', 'LABEL_REQUEST_FIELDS')
    entries = request['observations']; races = {r['race_id'] for r in imported['origin']['races']}
    require(type(entries) is list and len(entries) <= 168, 'LABEL_REQUEST_SIZE')
    seen = set(); paths = set()
    for item in entries:
        require(type(item) is dict and set(item) == {'race_id','revision','source_id','file_sha256','path'}, 'LABEL_REQUEST_FIELDS')
        require(type(item['race_id']) is str and item['race_id'] in races and item['race_id'] not in seen and
                type(item['revision']) is int and 1 <= item['revision'] <= 1000, 'LABEL_REQUEST_IDENTITY')
        require(item['source_id'] == imported['policy']['result_source_id'] and valid_sha(item['file_sha256']) and
                type(item['path']) is str and 1 <= len(item['path']) <= 4096 and '\x00' not in item['path'] and item['path'] not in paths, 'LABEL_REQUEST_SOURCE')
        seen.add(item['race_id']); paths.add(item['path'])
    return deepcopy(request)


def _request_matches(request, observations):
    selected = {(x['race_id'],x['revision'],x['source_id'],x['file_sha256']) for x in request['observations']}
    actual = {(x['race_id'],x['revision'],x['source_id'],x['file_sha256']) for x in observations}
    require(len(observations) == len(request['observations']) and selected == actual, 'LABEL_REQUEST_RESPONSE_CHANGED')


def _label_evidence(items):
    require(type(items) is list and len(items) <= 1680, 'BOUNDED_LABEL_BATCH')
    retained = []
    for item in items:
        require(type(item) is dict and set(item) == {'expected_sha256','raw'} and valid_sha(item['expected_sha256']) and
                type(item['raw']) is bytes and byte_sha(item['raw']) == item['expected_sha256'], 'LABEL_BYTE_BINDING')
        decode(item['raw'])
        retained.append({'file_sha256':item['expected_sha256'],'utf8':item['raw'].decode('utf-8')})
    return retained


def adapt_labels(evidence, imported, read_at):
    races = {r['race_id']:r for r in imported['origin']['races']}; output = []
    for retained in evidence:
        require(type(retained) is dict and set(retained) == {'file_sha256','utf8'} and type(retained['utf8']) is str, 'LABEL_EVIDENCE_FIELDS')
        raw = retained['utf8'].encode('utf-8'); require(byte_sha(raw) == retained['file_sha256'], 'LABEL_BYTE_BINDING')
        label = decode(raw); require(type(label) is dict and type(label.get('race_id')) is str and label['race_id'] in races, 'LABEL_RACE')
        common = {'schema','observation_id','result_observation_revision','supersedes_observation_id','race_id','status',
            'source_url','source_sha256','captured_at','source_published_at','planned_cutoff_at','bundle_sha256','seal_sha256',
            'formal_hit_at_8_all_eligible','official_final_cutoff_authenticated','raw_html_retained','payout_amounts_retained'}
        require(all(label.get(k) is False for k in ('formal_hit_at_8_all_eligible','official_final_cutoff_authenticated',
                                                  'raw_html_retained','payout_amounts_retained')), 'LABEL_AUTHORITY_OR_RAW_RETENTION')
        if label.get('schema') == 'RACE39_TODAY_RESULT_LABEL_V1':
            required = common | {'source_page_cutoff_at','winning_combination','individual_model_receipt','correction_policy'}
            optional = {'batch_id','source_status','body_identity_verified','source_result_status','finish_status_counts',
                        'refunded_boat_count','entry_reconciliation','frozen_registration_identity_joined'}
            require(required <= set(label) <= required | optional and label['individual_model_receipt'] is False and
                    label['correction_policy'] == 'NEW_EXPLICIT_APPEND_ONLY_REVISION_REQUIRED', 'LEGACY_LABEL_FIELDS')
        elif label.get('schema') == 'RACE_AI_RETAINED_OFFICIAL_OBSERVATION_V1':
            required = common | {'source_id','registration_ids','official_cutoff_at','winning_triples',
                'supersedes_file_sha256','provider_revision_reference','body_identity_verified','frozen_registration_identity_joined',
                'source_result_status','finish_status_counts','refunded_boat_count'}
            require(set(label) == required, 'OFFICIAL_LABEL_FIELDS')
        else:
            raise RetainedAuditError('LABEL_SCHEMA')
        # Allowed metadata names do not authorize arbitrary nested content.
        # These are the original parser's small scalar/aggregate claims only.
        require(type(label.get('status')) is str, 'LABEL_STATUS_TYPE')
        if 'batch_id' in label:
            require(label['batch_id'] == 'race39-today-results-batch2', 'LABEL_BATCH_ID')
        if 'source_status' in label:
            require(type(label['source_status']) is str and label['source_status'] in ('AVAILABLE','PENDING'), 'LABEL_SOURCE_STATUS')
        for flag in ('body_identity_verified','frozen_registration_identity_joined'):
            if flag in label: require(type(label[flag]) is bool, 'LABEL_BOOLEAN_METADATA')
        if 'entry_reconciliation' in label:
            require(label['entry_reconciliation'] is None or label['entry_reconciliation'] ==
                    'RESULT_EVIDENCE_JOINED_NOT_INDEPENDENTLY_REVIEWED', 'LABEL_RECONCILIATION')
        if 'source_result_status' in label:
            allowed = ('settled','special','dead_heat') if label['schema']=='RACE39_TODAY_RESULT_LABEL_V1' else (
                'settled','special','dead_heat','cancelled','not_offered','unresolved','unsupported')
            require(type(label['source_result_status']) is str and label['source_result_status'] in allowed, 'LABEL_RESULT_STATUS')
        if 'finish_status_counts' in label:
            counts = label['finish_status_counts']
            require(type(counts) is dict and len(counts) <= 6 and set(counts) <= {'FINISHED','欠','転','落','沈','失','妨','不','F','L','エ'} and
                    all(type(v) is int and 1 <= v <= 6 for v in counts.values()) and sum(counts.values()) <= 6, 'LABEL_FINISH_COUNTS')
        if 'refunded_boat_count' in label:
            require(type(label['refunded_boat_count']) is int and 0 <= label['refunded_boat_count'] <= 6, 'LABEL_REFUND_COUNT')
        if label.get('source_page_cutoff_at') is not None:
            moment(label['source_page_cutoff_at'])
        rid = label['race_id']; race = races[rid]; cutoff = moment(race['planned_cutoff_at'])
        expected_url = f"https://www.boatrace.jp/owpc/pc/race/raceresult?rno={race['identity']['race_no']}&jcd={rid[9:11]}&hd={rid[:8]}"
        require(label.get('source_url') == expected_url and label.get('bundle_sha256') == imported['original_file_sha256']['bundle'] and
                label.get('seal_sha256') == imported['original_file_sha256']['seal'] and label.get('planned_cutoff_at') == race['planned_cutoff_at'], 'LABEL_ORIGIN_BINDING')
        captured = label.get('captured_at'); source_sha = label.get('source_sha256')
        if captured is not None:
            require(cutoff < moment(captured) <= moment(read_at) and valid_sha(source_sha), 'LABEL_SOURCE_CLOCK')
        else:
            require(source_sha is None, 'UNOBSERVED_SOURCE_HASH')
        require(label.get('source_published_at') is None, 'UNSUPPORTED_PUBLICATION_CLAIM')
        require(type(label.get('result_observation_revision')) is int and 1 <= label['result_observation_revision'] <= 1000 and
                type(label.get('observation_id')) is str and re.fullmatch('[A-Za-z0-9_.:/-]{1,300}',label['observation_id']), 'LABEL_REVISION')
        revision = label['result_observation_revision']; status = label['status']; wins = []
        schema = label.get('schema')
        if schema == 'RACE39_TODAY_RESULT_LABEL_V1':
            require(revision == 1, 'LEGACY_REVISION_REQUIRES_EXPLICIT_CORRECTION')
            require(status in {'SCORABLE_NORMAL_FINISH','RESULT_PENDING','SOURCE_UNAVAILABLE_OR_INVALID','STOPPED_BEFORE_REQUEST',
                               'CUTOFF_REVISION_REQUIRES_REVIEW','UNSUPPORTED_NONSTANDARD_RESULT'}, 'LABEL_STATUS')
            require(label.get('formal_hit_at_8_all_eligible') is False and label.get('official_final_cutoff_authenticated') is False, 'LABEL_AUTHORITY')
            if status == 'SCORABLE_NORMAL_FINISH':
                require(captured is not None and label.get('body_identity_verified') is True and
                        label.get('frozen_registration_identity_joined') is True and label.get('source_page_cutoff_at') == race['planned_cutoff_at'] and
                        label.get('entry_reconciliation') == 'RESULT_EVIDENCE_JOINED_NOT_INDEPENDENTLY_REVIEWED' and
                        label.get('source_status') == 'AVAILABLE' and label.get('source_result_status') == 'settled' and label.get('finish_status_counts') == {'FINISHED':6} and
                        type(label.get('refunded_boat_count')) is int and label['refunded_boat_count'] == 0, 'LABEL_SETTLEMENT')
                wins = [_ticket(label['winning_combination'])]; settlement = 'FINAL'
            else:
                require(label.get('winning_combination') is None, 'UNSCORED_WINNING_TICKET')
                require(captured is not None or status in ('SOURCE_UNAVAILABLE_OR_INVALID','STOPPED_BEFORE_REQUEST'), 'LABEL_SOURCE_MISSING')
                settlement = 'UNSUPPORTED' if status in ('CUTOFF_REVISION_REQUIRES_REVIEW','UNSUPPORTED_NONSTANDARD_RESULT') else 'UNRESOLVED'
            registration_basis = 'ORIGINAL_BYTE_BOUND_CALLER_JOIN_CLAIM'
        elif schema == 'RACE_AI_RETAINED_OFFICIAL_OBSERVATION_V1':
            require(status in ('FINAL','CANCELLED','NOT_OFFERED','UNRESOLVED','UNSUPPORTED') and captured is not None and
                    label.get('registration_ids') == race['registration_ids'] and label.get('source_id') == imported['policy']['result_source_id'], 'NEW_OFFICIAL_OBSERVATION')
            require(label.get('official_cutoff_at') == race['planned_cutoff_at'], 'CUTOFF_REVISION_UNSUPPORTED')
            if status == 'FINAL':
                require(label['body_identity_verified'] is True and label['frozen_registration_identity_joined'] is True and
                        label['source_result_status'] == 'settled' and label['finish_status_counts'] == {'FINISHED':6} and
                        type(label['refunded_boat_count']) is int and label['refunded_boat_count'] == 0, 'NONSTANDARD_FINAL_NOT_ADMITTED')
                require(type(label.get('winning_triples')) is list and 1 <= len(label['winning_triples']) <= 6, 'WINNING_TRIPLES')
                wins = [_ticket(t) for t in label['winning_triples']]
                require(len({tuple(t) for t in wins}) == len(wins), 'DUPLICATE_WINNING_TICKET')
            else: require(label.get('winning_triples') == [], 'UNSCORED_WINNING_TICKET')
            if status in ('CANCELLED','NOT_OFFERED') or len(wins) > 1:
                require(imported['policy']['settlement_policy'] == 'OFFICIAL_REVISIONS_WITH_CANCELLATION_AND_DEAD_HEAT', 'SETTLEMENT_NOT_ADMITTED')
            if revision > 1:
                require(valid_sha(label.get('supersedes_file_sha256')) and type(label.get('provider_revision_reference')) is str and
                        re.fullmatch('[A-Za-z0-9_.:/#?=&%-]{1,300}',label['provider_revision_reference']), 'CORRECTION_EVIDENCE_REQUIRED')
            settlement = status; registration_basis = 'SUPPLIED_SIX_REGISTRATION_IDENTITY_MATCH'
        else:
            raise RetainedAuditError('LABEL_SCHEMA')
        output.append({'race_id':rid, 'revision':revision, 'status':settlement, 'winning_triples':wins,
            'unscored_reason':status if settlement in ('UNRESOLVED','UNSUPPORTED') else None,
            'original_status':status, 'source_id':imported['policy']['result_source_id'], 'source_sha256':source_sha,
            'source_url':expected_url, 'observed_at':captured, 'source_published_at':None, 'read_at':read_at,
            'file_sha256':retained['file_sha256'], 'observation_id':label['observation_id'],
            'supersedes_observation_id':label.get('supersedes_observation_id'),
            'supersedes_file_sha256':label.get('supersedes_file_sha256'),
            'provider_revision_reference':label.get('provider_revision_reference'), 'registration_basis':registration_basis})
    return output


def _validate_revisions(delta, previous, *, allow_empty=False):
    require(type(delta) is list and (delta or allow_empty), 'EMPTY_UPDATE')
    latest = {x['race_id']:x for x in previous}; seen = set()
    for value in delta:
        rid = value['race_id']; require(rid not in seen, 'DUPLICATE_RACE_OBSERVATION_IN_BATCH'); seen.add(rid)
        prior = latest.get(rid)
        require(value['revision'] == (prior['revision']+1 if prior else 1), 'REVISION_SEQUENCE')
        require(value['supersedes_observation_id'] == (prior['observation_id'] if prior else None), 'REVISION_PARENT')
        if prior:
            require(value['observation_id'] != prior['observation_id'] and value['supersedes_file_sha256'] == prior['file_sha256'] and
                    value['source_id'] == prior['source_id'] and value['source_url'] == prior['source_url'] and
                    value['source_sha256'] is not None and value['source_sha256'] != prior['source_sha256'], 'CORRECTION_SOURCE_BINDING')
        else:
            require(value['supersedes_file_sha256'] is None and value['provider_revision_reference'] is None, 'UNEXPECTED_CORRECTION_PARENT')
        if prior and prior['observed_at'] is not None and value['observed_at'] is not None:
            require(moment(value['observed_at']) >= moment(prior['observed_at']), 'SOURCE_REVISION_CLOCK_REVERSED')


class RetainedAuditJournal:
    _adapt_labels = staticmethod(adapt_labels)
    _report = staticmethod(retained_report)

    def _import_floor(self, imported):
        return imported['imported_at']

    def __init__(self, root, audit_id, *, clock=None):
        require(type(audit_id) is str and re.fullmatch('[A-Za-z0-9_-]{1,100}',audit_id), 'AUDIT_ID')
        self.root = Path(root); self.audit_id = audit_id
        self.directory = self.root/'retained-audits'/audit_id
        self.clock = clock or (lambda:datetime.now(timezone.utc))

    def _now(self):
        value = self.clock()
        require(isinstance(value,datetime) and value.utcoffset() is not None, 'INVALID_CLOCK')
        return value.astimezone(timezone.utc).isoformat()

    @contextmanager
    def _lock(self):
        _directory(self.root,create=True,parents=True)
        path = self.root/'final-reveal.lock'
        _create_raw(path, self.audit_id.encode('ascii'))
        try: yield
        finally: path.unlink()

    def import_bundle(self, files, *, expected_sha256, policy, expected_policy_sha256):
        origin = adapt_race39(files,expected_sha256); now = self._now()
        require(valid_sha(expected_policy_sha256) and digest(policy) == expected_policy_sha256, 'POLICY_HASH_CHANGED')
        policy = validate_policy(policy,origin,now)
        imported = {'schema':'RACE_AI_RETAINED_IMPORT_V1','mode':'RETAINED_PREDICTION_AUDIT',
            'audit_id':self.audit_id,'imported_at':now,'policy':policy,'policy_sha256':expected_policy_sha256,
            'original_file_sha256':dict(expected_sha256),'origin':origin,'cohort_role':'DEVELOPMENT_AUDIT',
            'comparison_policy_declared_after_forecast':True,'final_test_eligible':False,'unseen_data_authentication':False,
            'potentially_exposed_physical_races':168,'potentially_exposed_registry_keys':336}
        imported['import_sha256'] = digest(imported)
        with self._lock():
            _directory(self.root/'retained-audits',create=True)
            self.directory.mkdir()
            _create(self.directory/'import-intent.json', {'audit_id':self.audit_id,'reserved_at':now,'import_sha256':imported['import_sha256'],
                'potentially_exposed_physical_races':168,'potentially_exposed_registry_keys':336})
            exposed = self.root/'exposed-races'; _directory(exposed,create=True)
            references = []
            for race in origin['races']:
                identity = race['identity']
                for venue in (identity['venue'],identity['venue'][-2:]):
                    alias = {**identity,'venue':venue}; path = exposed/(digest(alias)+'.json')
                    if path.exists():
                        existing = _read(path); require(existing.get('race_identity') == alias, 'EXPOSURE_IDENTITY_CHANGED')
                    else:
                        _create(path, {'schema':'RACE_AI_RETAINED_POTENTIAL_EXPOSURE_V1','experiment_id':self.audit_id,
                            'reserved_at':now,'import_sha256':imported['import_sha256'],'race_identity':alias,
                            'canonical_race_identity':identity,'first_phase':'DEVELOPMENT_AUDIT',
                            'prior_result_exposure':policy['prior_result_exposure']})
                    references.append({'key':path.name,'sha256':byte_sha(regular_bytes(path))})
            _directory(self.directory/'origin',create=True)
            for role in sorted(ROLES): _create_raw(self.directory/'origin'/(role+'.json'),files[role])
            _create(self.directory/'exposure-references.json',references)
            _create(self.directory/'import.json',imported)
            completed_at = self._now(); require(moment(completed_at) >= moment(now), 'CLOCK_REVERSED')
            _create(self.directory/'import-completed.json',{'import_sha256':imported['import_sha256'],'exposure_references_sha256':digest(references),'completed_at':completed_at})
        return imported

    def _verified(self, expected_import_sha256):
        _directory(self.directory)
        imported = _read(self.directory/'import.json'); done = _read(self.directory/'import-completed.json')
        require(valid_sha(expected_import_sha256) and imported['import_sha256'] == expected_import_sha256 and
                digest({k:v for k,v in imported.items() if k != 'import_sha256'}) == expected_import_sha256, 'IMPORT_HASH_CHANGED')
        require(imported['audit_id'] == self.audit_id and done['import_sha256'] == expected_import_sha256 and
                moment(done['completed_at']) >= moment(imported['imported_at']), 'IMPORT_COMPLETION')
        require(_read(self.directory/'import-intent.json') == {'audit_id':self.audit_id,'reserved_at':imported['imported_at'],
            'import_sha256':expected_import_sha256,'potentially_exposed_physical_races':168,'potentially_exposed_registry_keys':336}, 'IMPORT_INTENT_CHANGED')
        origin = adapt_race39({role:regular_bytes(self.directory/'origin'/(role+'.json')) for role in ROLES},imported['original_file_sha256'])
        require(origin == imported['origin'] and digest(imported['policy']) == imported['policy_sha256'], 'IMPORT_ORIGIN_CHANGED')
        validate_policy(imported['policy'],origin,imported['imported_at'])
        refs = _read(self.directory/'exposure-references.json')
        require(len(refs) == 336 and digest(refs) == done['exposure_references_sha256'], 'EXPOSURE_REFERENCES_CHANGED')
        expected = {}
        for race in origin['races']:
            for venue in (race['identity']['venue'],race['identity']['venue'][-2:]):
                identity = {**race['identity'],'venue':venue}; expected[digest(identity)+'.json'] = identity
        require({r['key'] for r in refs} == set(expected), 'EXPOSURE_KEY_SET')
        _directory(self.root/'exposed-races')
        for ref in refs:
            path = self.root/'exposed-races'/ref['key']; value = _read(path)
            require(byte_sha(regular_bytes(path)) == ref['sha256'] and value['race_identity'] == expected[ref['key']], 'EXPOSURE_CHANGED')
        return imported

    def _state(self, expected_import_sha256, through_batch=None):
        require(through_batch is None or type(through_batch) is int and 0 <= through_batch <= 1000, 'BATCH_SELECTOR')
        imported = self._verified(expected_import_sha256)
        directory = self.directory/'result-batches'; _directory(directory)
        paths = sorted(directory.iterdir())
        require(paths and (through_batch is None or through_batch < len(paths)), 'REPORT_NOT_AVAILABLE')
        if through_batch is not None: paths = paths[:through_batch+1]
        observations = []; report = None; previous_at = self._import_floor(imported); count = -1
        for count,path in enumerate(paths):
            require(path.name == f'{count:06d}', 'BATCH_SEQUENCE'); _directory(path)
            intent = _read(path/'intent.json'); done = _read(path/'completed.json')
            request = validate_label_request(intent['label_request'],imported,intent['label_request_sha256'])
            require(intent == {'batch_number':count,'import_sha256':expected_import_sha256,
                'previous_report_sha256':None if report is None else digest(report),'reserved_at':intent['reserved_at'],
                'label_request':request,'label_request_sha256':digest(request)}, 'BATCH_PARENT_CHANGED')
            require(moment(previous_at) <= moment(intent['reserved_at']) <= moment(done['read_completed_at']), 'BATCH_CLOCK_REVERSED')
            evidence = _read(path/'evidence.json'); delta = self._adapt_labels(evidence,imported,done['read_completed_at'])
            _request_matches(request,delta)
            _validate_revisions(delta,observations,allow_empty=count==0)
            require(_read(path/'observations.json') == delta, 'OBSERVATION_CHANGED')
            observations += delta
            current = self._report(imported,observations,batch_number=count)
            require(current == _read(path/'report.json') and done == {'import_sha256':expected_import_sha256,
                'evidence_sha256':digest(evidence),'observations_sha256':digest(observations),'report_sha256':digest(current),
                'read_completed_at':done['read_completed_at']}, 'BATCH_COMPLETION_CHANGED')
            report = current; previous_at = done['read_completed_at']
        return imported,observations,report,previous_at,count

    def _observe(self, reader, *, expected_import_sha256, batch_number, expected_report_sha256, label_request, expected_request_sha256):
        require(callable(reader) and type(batch_number) is int and 0 <= batch_number <= 1000, 'BATCH_OR_READER')
        with self._lock():
            if batch_number == 0:
                imported = self._verified(expected_import_sha256); previous = []; prior = None
                previous_at = self._import_floor(imported)
            else:
                imported,previous,prior,previous_at,count = self._state(expected_import_sha256)
                require(batch_number == count+1 and valid_sha(expected_report_sha256) and digest(prior) == expected_report_sha256, 'EXPECTED_REPORT_CHANGED')
            request = validate_label_request(label_request,imported,expected_request_sha256)
            revisions = {x['race_id']:x['revision'] for x in previous}
            require(all(x['revision'] == revisions.get(x['race_id'],0)+1 for x in request['observations']), 'REQUEST_REVISION_SEQUENCE')
            now = self._now(); require(moment(now) >= moment(previous_at), 'CLOCK_REVERSED')
            batches = self.directory/'result-batches'; _directory(batches,create=True)
            path = batches/f'{batch_number:06d}'; path.mkdir()
            _create(path/'intent.json',{'batch_number':batch_number,'import_sha256':expected_import_sha256,
                'previous_report_sha256':None if prior is None else digest(prior),'reserved_at':now,
                'label_request':request,'label_request_sha256':expected_request_sha256})
            # No reader invocation precedes the shared lock, complete import, all
            # exposure markers, expected parent check and durable batch intent.
            evidence = _label_evidence(reader()); read_at = self._now()
            require(moment(read_at) >= moment(now), 'CLOCK_REVERSED')
            delta = self._adapt_labels(evidence,imported,read_at)
            _request_matches(request,delta)
            _validate_revisions(delta,previous,allow_empty=batch_number==0)
            combined = previous+delta; report = self._report(imported,combined,batch_number=batch_number)
            _create(path/'evidence.json',evidence); _create(path/'observations.json',delta); _create(path/'report.json',report)
            _create(path/'completed.json',{'import_sha256':expected_import_sha256,'evidence_sha256':digest(evidence),
                'observations_sha256':digest(combined),'report_sha256':digest(report),'read_completed_at':read_at})
            return report

    def observe(self, label_reader, *, expected_import_sha256, label_request, expected_request_sha256):
        return self._observe(label_reader,expected_import_sha256=expected_import_sha256,batch_number=0,expected_report_sha256=None,
                             label_request=label_request,expected_request_sha256=expected_request_sha256)

    def append_results(self, label_reader, *, batch_number, expected_import_sha256, expected_report_sha256, label_request, expected_request_sha256):
        require(type(batch_number) is int and batch_number >= 1, 'APPEND_BATCH_NUMBER')
        return self._observe(label_reader,expected_import_sha256=expected_import_sha256,batch_number=batch_number,expected_report_sha256=expected_report_sha256,
                             label_request=label_request,expected_request_sha256=expected_request_sha256)

    def read_report(self, *, expected_import_sha256, through_batch=None):
        return self._state(expected_import_sha256,through_batch)[2]
