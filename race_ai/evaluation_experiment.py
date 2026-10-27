"""Frozen same-cohort research evaluation; no network, fitting or authority.

All clocks/source IDs here are supplied claims. The journal protects ordering,
not the honesty/completeness of those claims. Formal prospective performance
requires the existing independently verified external receipts as a separate
acceptance step. Retrospective computation is never backdated.
"""
from collections import Counter
from copy import deepcopy
from datetime import date, timedelta, timezone
import math
import re
from .actions_contract import canonical, digest, stamp

JST = timezone(timedelta(hours=9))
STAGES = {'P0', 'P1'}
SPLITS = ('train', 'validation', 'test')
FORBIDDEN = {'odds', 'popularity', 'market', 'market_implied_win_probability',
             'result', 'results', 'outcome', 'ordered_top3', 'winning_triples',
             'payout', 'payouts', 'other_predictions'}


class EvaluationError(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise EvaluationError(message)


def exact(value, keys):
    require(type(value) is dict and set(value) == set(keys.split()), 'unsupported evaluation fields')


def name(value):
    return type(value) is str and re.fullmatch(r'[A-Za-z0-9_.:/-]{1,200}', value) is not None


def sha(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def day(value):
    require(type(value) is str, 'day string required')
    try:
        result = date.fromisoformat(value)
    except ValueError as exc:
        raise EvaluationError('invalid day') from exc
    require(value == result.isoformat(), 'canonical day required')
    return result


def moment(value):
    try:
        return stamp(value)
    except ValueError as exc:
        raise EvaluationError('invalid evaluation clock') from exc


def split_for(plan, race):
    d = day(race['event_date_jst'])
    for role in SPLITS:
        if d <= day(plan['windows'][role + '_end']):
            return role
    raise EvaluationError('race outside predeclared date windows')


def validate_plan(raw):
    p = deepcopy(raw)
    canonical(p)
    exact(p, 'schema experiment_id declared_at mode cohort_rule discovery_sha256 windows seen_race_ids stages result_source_ids models comparison_groups races feature_policy eligibility')
    require(p['schema'] == 'RACE_AI_EVALUATION_PLAN_V1' and name(p['experiment_id']), 'plan identity invalid')
    moment(p['declared_at'])
    require(p['mode'] in ('RETROSPECTIVE_RESEARCH', 'PROSPECTIVE_LOCAL'), 'unsupported evidence mode')
    require(type(p['cohort_rule']) is str and 1 <= len(p['cohort_rule']) <= 2000 and sha(p['discovery_sha256']), 'cohort discovery rule/hash required')
    exact(p['windows'], 'train_end validation_end test_end')
    ends = [day(p['windows'][k + '_end']) for k in SPLITS]
    require(ends[0] < ends[1] < ends[2], 'chronological windows must be disjoint')
    for k in ('seen_race_ids', 'stages', 'result_source_ids'):
        require(type(p[k]) is list and all(name(v) for v in p[k]) and len(set(p[k])) == len(p[k]), 'unique explicit registry required')
    require(0 < len(p['stages']) <= 2 and set(p['stages']) <= STAGES, 'P0/P1 stages required')
    require(0 < len(p['result_source_ids']) <= 32, 'predeclared label source policy required')
    policy = p['feature_policy']
    exact(policy, 'schema_id transform_sha256 allowed_fields')
    require(name(policy['schema_id']) and sha(policy['transform_sha256']), 'feature schema/transform identity required')
    fields = policy['allowed_fields']
    require(type(fields) is list and 0 < len(fields) <= 256 and all(type(f) is str and re.fullmatch('[a-z][a-z0-9_]{0,99}',f) and f not in FORBIDDEN for f in fields) and len(set(fields)) == len(fields), 'predeclared numeric feature allowlist required')
    require(type(p['models']) is list and 1 <= len(p['models']) <= 64, 'bounded model roster required')
    mids = set()
    for m in p['models']:
        exact(m, 'model_id version code_sha256 artifact_sha256 trained_until created_at')
        require(name(m['model_id']) and name(m['version']) and sha(m['code_sha256']) and m['model_id'] not in mids, 'model identity/code collision')
        mids.add(m['model_id'])
        if m['artifact_sha256'] is None:
            require(m['trained_until'] is None and m['created_at'] is None, 'fixed model cannot claim training')
        else:
            require(sha(m['artifact_sha256']), 'artifact hash required')
            trained, created = moment(m['trained_until']), moment(m['created_at'])
            require(trained <= created and trained.astimezone(JST).date() <= ends[0], 'training overlaps validation/test')
    require(type(p['comparison_groups']) is list and len(p['comparison_groups']) <= 64, 'bounded comparison groups required')
    groups = set()
    for group in p['comparison_groups']:
        require(type(group) is list and 2 <= len(group) <= len(mids) and all(type(m) is str and m in mids for m in group) and len(set(group)) == len(group), 'explicit model comparison group required')
        key = tuple(sorted(group))
        require(key not in groups, 'duplicate comparison group')
        groups.add(key)
    require(type(p['races']) is list and 0 < len(p['races']) <= 100000, 'bounded complete cohort required')
    ids = set(); identities = set()
    for race in p['races']:
        exact(race, 'race_id sport venue race_no event_date_jst cutoff_at participants')
        require(name(race['race_id']) and race['race_id'] not in ids and name(race['venue']) and race['sport'] in ('boat', 'keirin', 'autorace', 'horse'), 'race identity invalid')
        ids.add(race['race_id'])
        require(type(race['race_no']) is int and 1 <= race['race_no'] <= 99, 'race number invalid')
        identity = (race['sport'], race['venue'], race['event_date_jst'], race['race_no'])
        require(identity not in identities, 'duplicate race with renamed ID')
        identities.add(identity)
        require(moment(race['cutoff_at']).astimezone(JST).date() == day(race['event_date_jst']), 'race cutoff/JST date mismatch')
        numbers = race['participants']
        require(type(numbers) is list and 3 <= len(numbers) <= 18 and all(type(n) is int and 1 <= n <= 99 for n in numbers) and len(set(numbers)) == len(numbers), 'unique participants required')
        if split_for(p, race) == 'test':
            require(race['race_id'] not in p['seen_race_ids'], 'already exposed race cannot be final test')
    require(type(p['eligibility']) is list and len(p['eligibility']) == len(ids)*len(mids)*len(p['stages']), 'complete pre-inference eligibility matrix required')
    eligible_keys = set()
    for e in p['eligibility']:
        exact(e, 'race_id stage model_id eligible reason')
        require(type(e['race_id']) is str and e['race_id'] in ids and type(e['model_id']) is str and e['model_id'] in mids and type(e['stage']) is str and e['stage'] in p['stages'], 'unlisted eligibility row')
        key = e['race_id'],e['stage'],e['model_id']
        require(key not in eligible_keys and type(e['eligible']) is bool, 'duplicate/nonboolean eligibility')
        eligible_keys.add(key)
        require(e['reason'] is None if e['eligible'] else name(e['reason']), 'ineligible feature reason required')
    return p


def _check_features(value):
    # Numeric projections only; source metadata/labels cannot hide in objects.
    if type(value) is list:
        require(len(value) <= 10000, 'feature vector bound')
        for v in value:
            _check_features(v)
    else:
        if value is None:
            return
        require(type(value) in (int,float), 'numeric projected features required')
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        require(finite, 'finite representable numeric projected features required')


def _ticket(t, numbers):
    return type(t) is list and len(t) == 3 and all(type(n) is int and n in numbers for n in t) and len(set(t)) == 3


def seal_predictions(raw_plan, raw_contexts, raw_outputs, *, sealed_at):
    p = validate_plan(raw_plan)
    contexts, outputs = deepcopy((raw_contexts, raw_outputs))
    canonical([contexts, outputs])
    sealed = moment(sealed_at)
    require(moment(p['declared_at']) <= sealed, 'seal predates plan')
    races = {r['race_id']: r for r in p['races']}
    models = {m['model_id']: m for m in p['models']}
    require(type(contexts) is list and len(contexts) <= len(races)*len(p['stages']), 'too many contexts')
    cm = {}
    for c in contexts:
        exact(c, 'race_id stage as_of features sources')
        require(type(c['race_id']) is str and c['race_id'] in races and type(c['stage']) is str and c['stage'] in p['stages'], 'unlisted context')
        key = c['race_id'], c['stage']
        require(key not in cm, 'two information cutoffs for one race/stage')
        asof = moment(c['as_of'])
        require(asof < moment(races[key[0]]['cutoff_at']) and asof <= sealed, 'context as-of outside cutoff/seal')
        require(type(c['features']) is dict, 'explicit feature projection required')
        require(set(c['features']) <= set(p['feature_policy']['allowed_fields']), 'unregistered feature projection')
        for feature in c['features'].values():
            _check_features(feature)
        require(type(c['sources']) is list and 0 < len(c['sources']) <= 128, 'source observations required')
        source_ids = set()
        for src in c['sources']:
            exact(src, 'source_id sha256 captured_at published_at')
            require(name(src['source_id']) and src['source_id'] not in source_ids and sha(src['sha256']), 'source identity/hash invalid')
            source_ids.add(src['source_id'])
            captured = moment(src['captured_at'])
            require(captured <= asof, 'source observed after information cutoff')
            if src['published_at'] is not None:
                require(moment(src['published_at']) <= captured, 'publication after capture')
        cm[key] = c
    for rid in races:
        p0, p1 = cm.get((rid, 'P0')), cm.get((rid, 'P1'))
        if p0 and p1:
            require(moment(p0['as_of']) <= moment(p1['as_of']), 'P1 predates P0')
    require(type(outputs) is list and len(outputs) == len(races)*len(models)*len(p['stages']), 'complete race/model/stage matrix required')
    seen = set()
    eligibility = {(e['race_id'],e['stage'],e['model_id']):e for e in p['eligibility']}
    for out in outputs:
        exact(out, 'race_id stage model_id context_sha256 code_sha256 artifact_sha256 generated_at status top8 reason')
        require(type(out['race_id']) is str and out['race_id'] in races and type(out['stage']) is str and out['stage'] in p['stages'] and type(out['model_id']) is str and out['model_id'] in models, 'unlisted output')
        key = out['race_id'], out['stage'], out['model_id']
        require(key not in seen, 'duplicate output')
        seen.add(key)
        model, race = models[key[2]], races[key[0]]
        require(out['code_sha256'] == model['code_sha256'] and out['artifact_sha256'] == model['artifact_sha256'], 'model or artifact switched after declaration')
        generated = moment(out['generated_at'])
        require(moment(p['declared_at']) <= generated <= sealed, 'output generation outside plan/seal')
        c = cm.get(key[:2])
        require(out['context_sha256'] == (digest(c) if c else None), 'models must use identical race/stage context')
        if out['status'] == 'PREDICTED':
            require(eligibility[key]['eligible'], 'ineligible model emitted a forecast')
            require(c is not None and moment(c['as_of']) <= generated, 'missing input or generation before as-of')
            require(type(out['top8']) is list and 1 <= len(out['top8']) <= 8 and all(_ticket(t, race['participants']) for t in out['top8']) and len({tuple(t) for t in out['top8']}) == len(out['top8']) and out['reason'] is None, 'invalid maximum-eight prediction')
            if model['artifact_sha256'] is not None:
                require(moment(model['trained_until']) < moment(c['as_of']) and moment(model['created_at']) <= generated, 'fitted model not available before prediction')
            if p['mode'] == 'PROSPECTIVE_LOCAL':
                require(generated <= sealed < moment(race['cutoff_at']), 'prospective save missed cutoff')
                if model['created_at'] is not None:
                    require(moment(model['created_at']) <= moment(c['as_of']), 'prospective model unavailable at as-of')
        else:
            require(out['status'] == 'NO_FORECAST' and out['top8'] == [] and name(out['reason']), 'missing forecast needs explicit reason')
    bundle = {'schema':'RACE_AI_EVALUATION_SEAL_V1', 'plan':p, 'plan_sha256':digest(p),
              'contexts':contexts, 'outputs':outputs, 'sealed_at':sealed_at}
    bundle['seal_sha256'] = digest(bundle)
    return bundle


def verify_seal(value):
    exact(value, 'schema plan plan_sha256 contexts outputs sealed_at seal_sha256')
    require(value['schema'] == 'RACE_AI_EVALUATION_SEAL_V1' and sha(value['seal_sha256']) and digest({k:v for k,v in value.items() if k != 'seal_sha256'}) == value['seal_sha256'], 'prediction seal changed')
    rebuilt = seal_predictions(value['plan'], value['contexts'], value['outputs'], sealed_at=value['sealed_at'])
    require(canonical(rebuilt) == canonical(value), 'invalid sealed evaluation')
    return deepcopy(value)


def score_seal(raw_seal, raw_labels):
    s = verify_seal(raw_seal)
    p = s['plan']; races = {r['race_id']:r for r in p['races']}
    labels = deepcopy(raw_labels); canonical(labels)
    require(type(labels) is list and len(labels) <= 10*len(races), 'bounded result revisions required')
    latest = {}; revision_keys = set()
    # Input order is immaterial; provider revision and observation chronology must agree.
    for label in labels:
        exact(label, 'race_id revision status winning_triples source_id source_sha256 observed_at')
        rid = label['race_id']
        require(type(rid) is str and rid in races and type(label['revision']) is int and label['revision'] >= 1, 'invalid result identity/revision')
        require(type(label['source_id']) is str and label['source_id'] in p['result_source_ids'] and sha(label['source_sha256']), 'unregistered result source')
        require(moment(label['observed_at']) > moment(races[rid]['cutoff_at']), 'result observation before cutoff')
        key = rid, label['revision']; require(key not in revision_keys, 'duplicate result revision')
        revision_keys.add(key)
        status, tickets = label['status'], label['winning_triples']
        require(status in ('FINAL','CANCELLED','NOT_OFFERED','UNRESOLVED','UNSUPPORTED'), 'unsupported settlement status')
        if status == 'FINAL':
            require(type(tickets) is list and 1 <= len(tickets) <= 6 and all(_ticket(t,races[rid]['participants']) for t in tickets) and len({tuple(t) for t in tickets}) == len(tickets), 'official winning combinations invalid')
        else:
            require(tickets == [], 'nonfinal result cannot supply winning tickets')
    for label in sorted(labels, key=lambda x:(x['race_id'],x['revision'])):
        prior = latest.get(label['race_id'])
        if prior:
            require(moment(prior['observed_at']) <= moment(label['observed_at']), 'revision observation time reversed')
        latest[label['race_id']] = label
    table = {(o['race_id'],o['stage'],o['model_id']):o for o in s['outputs']}
    def metrics(ids, mid, stage):
        known = [rid for rid in ids if latest.get(rid,{}).get('status') == 'FINAL']
        excluded = [rid for rid in ids if latest.get(rid,{}).get('status') in ('CANCELLED','NOT_OFFERED')]
        predicted = [rid for rid in ids if table[rid,stage,mid]['status'] == 'PREDICTED']
        available = set(predicted) & set(known)
        hit8 = sum(any(t in latest[rid]['winning_triples'] for t in table[rid,stage,mid]['top8']) for rid in available)
        hit1 = sum(table[rid,stage,mid]['top8'][0] in latest[rid]['winning_triples'] for rid in available)
        reasons = Counter(table[rid,stage,mid]['reason'] for rid in ids if table[rid,stage,mid]['status'] == 'NO_FORECAST')
        return {'model_id':mid,'stage':stage,'cohort':len(ids),'known_results':len(known),
                'unknown_results':len(ids)-len(known)-len(excluded),'excluded_results':len(excluded),
                'predicted':len(predicted),'missing_prediction_known':len(known)-len(available),
                'hit1':hit1,'hit8':hit8,'hit8_all_known':hit8/len(known) if known else None,
                'hit8_predicted_known':hit8/len(available) if available else None,
                'missing_reasons':dict(sorted(reasons.items()))}
    ids = list(races); comparisons = []; intersections = []
    eligibility = {(e['race_id'],e['stage'],e['model_id']):e for e in p['eligibility']}
    for stage in p['stages']:
        for group in p['comparison_groups']:
            common = [rid for rid in ids if all(eligibility[rid,stage,mid]['eligible'] for mid in group)]
            comparisons.append({'stage':stage,'model_ids':group,'race_ids':common,
                'selection':'PREDECLARED_FEATURE_ELIGIBILITY_RUNTIME_FAILURES_REMAIN',
                'known_results':sum(latest.get(rid,{}).get('status') == 'FINAL' for rid in common),
                'models':[metrics(common,mid,stage) for mid in group]})
            successful = [rid for rid in common if all(table[rid,stage,mid]['status'] == 'PREDICTED' for mid in group)]
            intersections.append({'stage':stage,'model_ids':group,'race_ids':successful,
                'selection':'DESCRIPTIVE_SUCCESS_ONLY_SURVIVOR_SUBSET_NOT_PRIMARY',
                'models':[metrics(successful,mid,stage) for mid in group]})
    split_ids = {role:[rid for rid,r in races.items() if split_for(p,r) == role] for role in SPLITS}
    sport_ids = {sport:[rid for rid,r in races.items() if r['sport'] == sport] for sport in ('boat','keirin','autorace','horse')}
    return {'schema':'RACE_AI_EVALUATION_REPORT_V1','seal_sha256':s['seal_sha256'],
            'label_revision_sha256':digest(labels),'formal_hit_at_8_all':None,
            'independent_pre_cutoff_proof':False,'unseen_data_authentication':False,
            'mode':p['mode'],'result_authentication':'CALLER_SUPPLIED_CLAIMS',
            'split_counts':{role:len(v) for role,v in split_ids.items()},
            'models':[metrics(ids,m['model_id'],stage) for stage in p['stages'] for m in p['models']],
            'by_split':{role:[metrics(rids,m['model_id'],stage) for stage in p['stages'] for m in p['models']] for role,rids in split_ids.items()},
            'by_sport':{sport:[metrics(rids,m['model_id'],stage) for stage in p['stages'] for m in p['models']] for sport,rids in sport_ids.items()},
            'comparisons':comparisons,'successful_prediction_intersections':intersections}
