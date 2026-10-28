"""Explicit captured-history development journal; legacy imports stay separate.

Reservations cover declared identities only, not arbitrary payload identity or
prior non-exposure. Actual callers must independently check and pin the complete
descriptor. A failed import remains pending; no automatic cleanup or retry.
"""
from copy import deepcopy
from datetime import timedelta
import math
from pathlib import Path

from .evaluation_metrics import retained_report
from .retained_prediction_audit import (MAX_BYTES, RetainedAuditJournal, require,
    digest, byte_sha, valid_sha, moment, regular_bytes, validate_policy,
    _race_identity, _create_raw, _create, _read, _directory)

PROFILE = 'RACE41_CAPTURED_HISTORY_V1'
ROLES = {'facts','bundle','seal','manifest','proof','registry','history','parent','witness','witness_source'}
PROTECTION = 'DECLARED_IDENTITIES_ONLY_NOT_PAYLOAD_AUTHENTICATION'


def adapt_race41(files, pins):
    # Lazy import prevents the default CLI profile from loading the new bridge.
    from .retained_captured_origin import adapt_race41 as adapt
    return adapt(files, pins)


def validate_request(request, expected):
    require(valid_sha(expected) and digest(request) == expected, 'CAPTURED_REQUEST_HASH')
    require(type(request) is dict and set(request) == {'schema','profile','files','target_race_ids','history_race_ids'} and
        request['schema'] == 'RACE_AI_CAPTURED_ORIGIN_REQUEST_V1' and request['profile'] == PROFILE, 'CAPTURED_REQUEST_FIELDS')
    require(type(request['files']) is dict and set(request['files']) == ROLES, 'CAPTURED_ROLE_SET')
    paths = []
    for value in request['files'].values():
        require(type(value) is dict and set(value) == {'path','sha256'} and valid_sha(value['sha256']) and
            type(value['path']) is str and 1 <= len(value['path']) <= 4096 and '\x00' not in value['path'], 'CAPTURED_FILE_DESCRIPTOR')
        paths.append(str(Path(value['path']).resolve()).casefold())
    require(len(set(paths)) == len(ROLES), 'CAPTURED_PATH_ALIAS')
    days = []
    for key in ('target_race_ids','history_race_ids'):
        ids = request[key]
        require(type(ids) is list and 1 <= len(ids) <= 288 and all(type(r) is str and r.isascii() for r in ids) and
                ids == sorted(set(ids)), 'CAPTURED_IDENTITY_LIST')
        identities = [_race_identity(r) for r in ids]
        date_set = {r['event_date_jst'] for r in identities}
        require(len(date_set) == 1, 'CAPTURED_SOURCE_DAY')
        days.append(next(iter(date_set)))
    require(days[1] < days[0], 'CAPTURED_HISTORY_NOT_PRIOR')
    return deepcopy(request)


def read_origin(request):
    """Call only inside import_captured's reserved lazy reader."""
    files = {}; total = 0
    for role in sorted(ROLES):
        raw = regular_bytes(request['files'][role]['path']); total += len(raw)
        require(total <= MAX_BYTES, 'ORIGIN_TOTAL_SIZE')
        files[role] = raw
    return files


def _pins(request):
    return {r:request['files'][r]['sha256'] for r in ROLES}


def _file_binding(files, request):
    require(type(files) is dict and set(files) == ROLES and all(type(v) is bytes for v in files.values()), 'ORIGIN_CLOSURE')
    require(sum(map(len,files.values())) <= MAX_BYTES, 'ORIGIN_TOTAL_SIZE')
    require(all(byte_sha(files[r]) == request['files'][r]['sha256'] for r in ROLES), 'ORIGIN_HASH_CHANGED')


def _scope(origin, request):
    require(origin['profile'] == PROFILE and sorted(r['race_id'] for r in origin['races']) == request['target_race_ids'] and
            sorted(origin['history_race_ids']) == request['history_race_ids'], 'CAPTURED_SCOPE_CHANGED')


def _identities(request):
    return [_race_identity(r) for r in request['target_race_ids']+request['history_race_ids']]


def _expected_refs(request):
    result = {}
    for identity in _identities(request):
        for venue in (identity['venue'],identity['venue'][-2:]):
            alias = {**identity,'venue':venue}; result[digest(alias)+'.json'] = alias
    return result


def _proper(model_rows, origin_races, observations):
    latest = {x['race_id']:x for x in sorted(observations,key=lambda x:(x['race_id'],x['revision']))}
    scored = []; zero = 0; unsupported = 0
    by_race = {r['race_id']:r for r in origin_races}
    for row in model_rows:
        label = latest.get(row['race_id'])
        if label is None or label['status'] != 'FINAL' or row['prediction_status'] != 'FORECAST':continue
        if len(label['winning_triples']) != 1:
            unsupported += 1; continue
        model = next(m for m in by_race[row['race_id']]['models'] if m['model_id'] == row['model_id'])
        winner = label['winning_triples'][0]
        probabilities = model['scores120']
        p = next(x['score'] for x in probabilities if x['combination'] == winner)
        brier = math.fsum((x['score']-int(x['combination']==winner))**2 for x in probabilities)
        loss = -math.log(p) if p > 0 else None
        zero += int(p == 0); scored.append((brier,loss))
    return {'definition':'BRIER_SUM_120_AND_NEGATIVE_NATURAL_LOG_TRUE_PROBABILITY_NO_RENORMALIZATION',
        'scored_predictions':len(scored),'unsupported_multiple_winners':unsupported,'zero_true_probability':zero,
        'mean_brier':math.fsum(x[0] for x in scored)/len(scored) if scored else None,
        'mean_log_loss':math.fsum(x[1] for x in scored)/len(scored) if scored and not zero else None,
        'log_loss_state':'POSITIVE_INFINITY' if zero else 'FINITE' if scored else 'NO_SCORED_PREDICTIONS'}


def captured_report(imported, observations, *, batch_number):
    """New report only. The legacy report function and output are unchanged."""
    report = retained_report(imported,observations,batch_number=batch_number)
    report.update(schema='RACE_AI_RETAINED_AUDIT_REPORT_V2',origin_profile=PROFILE,
        exposure_protection=PROTECTION, history_races=len(imported['origin']['history_race_ids']))
    races = imported['origin']['races']; mapping = {r['race_id']:r for r in races}
    for row in report['rows']:
        race = mapping[row['race_id']]
        row['hash_witness_state'] = race['witness_state']
        row['hash_witness_before_planned_cutoff'] = race['hash_witness_before_planned_cutoff']
    def add_scores(models, rows):
        for model in models:
            selected = [r for r in rows if r['model_id'] == model['model_id']]
            model['proper_scores'] = _proper(selected,races,observations)
    add_scores(report['models'],report['rows'])
    add_scores(report['descriptive_timing_cohort']['models'],[r for r in report['rows'] if r['original_readback_before_planned_cutoff']])
    groups = {}
    for state in ('TIMELY_HASH_WITNESS','LATE_HASH_WITNESS','NO_ANCHOR'):
        selected = [r for r in races if r['witness_state'] == state]
        sub = {**imported,'origin':{**imported['origin'],'races':selected}}
        group = retained_report(sub,observations,batch_number=batch_number)
        add_scores(group['models'],group['rows'])
        groups[state] = {'selection':'RETAINED_HASH_WITNESS_PLANNED_CUTOFF_NOT_PREDECLARED',
            'race_ids':[r['race_id']for r in selected], 'models':group['models']}
    report['hash_witness_cohorts'] = groups
    return report


class CapturedHistoryAuditJournal(RetainedAuditJournal):
    _report = staticmethod(captured_report)

    def _import_floor(self, imported):
        return _read(self.directory/'import-completed.json')['completed_at']

    @staticmethod
    def _adapt_labels(evidence, imported, read_at):
        from .retained_captured_labels import adapt_captured_labels
        return adapt_captured_labels(evidence,imported,read_at)

    def import_bundle(self, *args, **kwargs):
        require(False, 'CAPTURED_LAZY_IMPORT_REQUIRED')

    def import_captured(self, reader, *, request, expected_request_sha256, policy, expected_policy_sha256):
        require(callable(reader), 'CAPTURED_READER')
        request = validate_request(request,expected_request_sha256)
        require(valid_sha(expected_policy_sha256) and digest(policy) == expected_policy_sha256 and
                policy.get('prior_result_exposure') == 'ALREADY_EXPOSED_RESEARCH' and
                policy.get('settlement_policy') == 'NORMAL_FINISH_ONLY', 'CAPTURED_POLICY')
        now = self._now()
        # Validate policy shape/clock before reading; compare actual source completion after admission.
        before = (moment(policy['declared_at'])-timedelta(microseconds=1)).isoformat()
        policy = validate_policy(policy,{'original_completed_at':before},now)
        physical = len(_identities(request)); expected = _expected_refs(request)
        intent = {'audit_id':self.audit_id,'reserved_at':now,'origin_request_sha256':expected_request_sha256,
            'policy_sha256':expected_policy_sha256,'potentially_exposed_physical_races':physical,
            'potentially_exposed_registry_keys':len(expected),'exposure_protection':PROTECTION}
        with self._lock():
            _directory(self.root/'retained-audits',create=True); self.directory.mkdir()
            _create(self.directory/'origin-request.json',request)
            _create(self.directory/'import-intent.json',intent)
            exposed = self.root/'exposed-races'; _directory(exposed,create=True)
            references = []
            for name,identity in sorted(expected.items()):
                path = exposed/name
                if path.exists():require(_read(path).get('race_identity') == identity, 'EXPOSURE_IDENTITY_CHANGED')
                else:_create(path,{'schema':'RACE_AI_RETAINED_POTENTIAL_EXPOSURE_V1','experiment_id':self.audit_id,
                    'reserved_at':now,'origin_request_sha256':expected_request_sha256,'race_identity':identity,
                    'canonical_race_identity':{**identity,'venue':'boatrace-jcd-'+identity['venue'][-2:]},
                    'first_phase':'DEVELOPMENT_AUDIT','prior_result_exposure':'ALREADY_EXPOSED_RESEARCH'})
                references.append({'key':name,'sha256':byte_sha(regular_bytes(path))})
            _create(self.directory/'exposure-references.json',references)
            files = reader(); _file_binding(files,request)
            origin = adapt_race41(files,_pins(request)); _scope(origin,request)
            validate_policy(policy,origin,now)
            imported = {'schema':'RACE_AI_RETAINED_IMPORT_V2','origin_profile':PROFILE,'mode':'RETAINED_PREDICTION_AUDIT',
                'audit_id':self.audit_id,'imported_at':now,'policy':policy,'policy_sha256':expected_policy_sha256,
                'origin_request_sha256':expected_request_sha256,'original_file_sha256':_pins(request),'origin':origin,
                'cohort_role':'DEVELOPMENT_AUDIT','comparison_policy_declared_after_forecast':True,
                'final_test_eligible':False,'unseen_data_authentication':False,'exposure_protection':PROTECTION,
                'potentially_exposed_physical_races':physical,'potentially_exposed_registry_keys':len(expected)}
            imported['import_sha256'] = digest(imported)
            _directory(self.directory/'origin',create=True)
            for role in sorted(ROLES):_create_raw(self.directory/'origin'/(role+'.json'),files[role])
            _create(self.directory/'import.json',imported)
            completed = self._now(); require(moment(completed) >= moment(now), 'CLOCK_REVERSED')
            _create(self.directory/'import-completed.json',{'import_sha256':imported['import_sha256'],
                'origin_request_sha256':expected_request_sha256,'exposure_references_sha256':digest(references),'completed_at':completed})
        return imported

    def _verified(self, expected_import_sha256):
        _directory(self.directory)
        imported = _read(self.directory/'import.json'); done = _read(self.directory/'import-completed.json')
        require(valid_sha(expected_import_sha256) and imported.get('import_sha256') == expected_import_sha256 and
            digest({k:v for k,v in imported.items()if k!='import_sha256'}) == expected_import_sha256, 'IMPORT_HASH_CHANGED')
        require(imported.get('schema') == 'RACE_AI_RETAINED_IMPORT_V2' and imported.get('origin_profile') == PROFILE and
            imported['audit_id'] == self.audit_id and imported['exposure_protection'] == PROTECTION and
            imported['final_test_eligible'] is False and imported['unseen_data_authentication'] is False, 'CAPTURED_IMPORT_PROFILE')
        request = validate_request(_read(self.directory/'origin-request.json'),imported['origin_request_sha256'])
        expected = _expected_refs(request); refs = _read(self.directory/'exposure-references.json')
        require(len(refs) == len(expected) and {r['key']for r in refs} == set(expected), 'EXPOSURE_REFERENCES_CHANGED')
        _directory(self.root/'exposed-races')
        for ref in refs:
            path = self.root/'exposed-races'/ref['key']; value = _read(path)
            require(byte_sha(regular_bytes(path)) == ref['sha256'] and value['race_identity'] == expected[ref['key']], 'EXPOSURE_CHANGED')
        require(done == {'import_sha256':expected_import_sha256,'origin_request_sha256':imported['origin_request_sha256'],
            'exposure_references_sha256':digest(refs),'completed_at':done['completed_at']} and
            moment(done['completed_at']) >= moment(imported['imported_at']), 'IMPORT_COMPLETION')
        physical = len(_identities(request))
        require(imported['potentially_exposed_physical_races'] == physical and imported['potentially_exposed_registry_keys'] == len(expected), 'EXPOSURE_COUNTS')
        require(_read(self.directory/'import-intent.json') == {'audit_id':self.audit_id,'reserved_at':imported['imported_at'],
            'origin_request_sha256':imported['origin_request_sha256'],'policy_sha256':imported['policy_sha256'],
            'potentially_exposed_physical_races':physical,'potentially_exposed_registry_keys':len(expected),
            'exposure_protection':PROTECTION}, 'IMPORT_INTENT_CHANGED')
        files = {role:regular_bytes(self.directory/'origin'/(role+'.json')) for role in ROLES}
        _file_binding(files,request); require(imported['original_file_sha256'] == _pins(request), 'IMPORT_PINS_CHANGED')
        origin = adapt_race41(files,_pins(request)); _scope(origin,request)
        require(origin == imported['origin'] and digest(imported['policy']) == imported['policy_sha256'] and
                imported['policy']['prior_result_exposure'] == 'ALREADY_EXPOSED_RESEARCH' and
                imported['policy']['settlement_policy'] == 'NORMAL_FINISH_ONLY', 'IMPORT_ORIGIN_CHANGED')
        validate_policy(imported['policy'],origin,imported['imported_at'])
        return imported
