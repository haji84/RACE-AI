"""Pure retained-cohort arithmetic. No model, source, filesystem or clock imports."""
from collections import Counter


def retained_report(imported, observations, *, batch_number):
    """Consume validated import/observations; retain absent forecasts and labels."""
    origin = imported['origin']
    latest = {}
    for observation in sorted(observations, key=lambda x: (x['race_id'], x['revision'])):
        latest[observation['race_id']] = observation
    rows = []
    for race in origin['races']:
        label = latest.get(race['race_id'])
        state = 'UNOBSERVED' if label is None else label['status']
        known = state == 'FINAL'
        excluded = state in ('CANCELLED', 'NOT_OFFERED')
        wins = [] if label is None else label['winning_triples']
        for model in race['models']:
            predicted = model['status'] == 'FORECAST'
            top8 = model['top8'] or []
            rows.append({'race_id':race['race_id'], 'model_id':model['model_id'],
                'model_version':model['model_version'], 'numerical_alias_of':model['numerical_alias_of'],
                'stage':'P0', 'prediction_status':model['status'], 'missing_reason':model.get('reason'),
                'input_sha256':race['input_sha256'], 'forecast_sha256':model.get('forecast_sha256'),
                'original_generated_at':race['generated_at'], 'original_state':race['state'],
                'original_readback_before_planned_cutoff':race['local_pre_cutoff_readback'],
                'result_state':state, 'unscored_reason':None if label is None else label['unscored_reason'],
                'result_revision':None if label is None else label['revision'],
                'result_file_sha256':None if label is None else label['file_sha256'],
                'cohort_denominator':1, 'known_result_denominator':int(known),
                'excluded_result':excluded,
                'hit1':None if not known else bool(predicted and top8[0] in wins),
                'hit8':None if not known else bool(predicted and any(t in wins for t in top8))})

    def metrics(selected, model):
        group = [r for r in selected if r['model_id'] == model['model_id']]
        known = [r for r in group if r['known_result_denominator']]
        unobserved = sum(r['result_state'] == 'UNOBSERVED' for r in group)
        unresolved = [r for r in group if r['result_state'] in ('UNRESOLVED', 'UNSUPPORTED')]
        excluded = sum(r['excluded_result'] for r in group)
        predicted = [r for r in group if r['prediction_status'] == 'FORECAST']
        available = [r for r in known if r['prediction_status'] == 'FORECAST']
        hits = sum(r['hit8'] is True for r in known)
        return {'model_id':model['model_id'], 'model_version':model['model_version'],
            'numerical_alias_of':model['numerical_alias_of'], 'stage':'P0', 'cohort':len(group),
            'known_results':len(known), 'unobserved_results':unobserved,
            'observed_unscored_results':len(unresolved), 'unknown_results':unobserved+len(unresolved),
            'observed_unscored_reasons':dict(sorted(Counter(r['unscored_reason'] for r in unresolved).items())),
            'excluded_results':excluded, 'predicted':len(predicted), 'missing_predictions':len(group)-len(predicted),
            'known_result_predictions':len(available), 'missing_prediction_known':len(known)-len(available),
            'hit1':sum(r['hit1'] is True for r in known), 'hit8':hits,
            'hit8_all_known':hits/len(known) if known else None,
            'hit8_predicted_known':hits/len(available) if available else None,
            'missing_reasons':dict(sorted(Counter(r['missing_reason'] for r in group if r['prediction_status']=='NO_FORECAST').items()))}

    descriptive = [r for r in rows if r['original_readback_before_planned_cutoff']]
    return {'schema':'RACE_AI_RETAINED_AUDIT_REPORT_V1', 'mode':'RETAINED_PREDICTION_AUDIT',
        'cohort_role':'DEVELOPMENT_AUDIT', 'final_test_eligible':False,
        'comparison_policy_declared_after_forecast':True, 'formal_hit_at_8_all':None,
        'unseen_data_authentication':False, 'result_authentication':'CALLER_SUPPLIED_RETAINED_SOURCE_CLAIMS',
        'import_sha256':imported['import_sha256'], 'policy_sha256':imported['policy_sha256'],
        'original_file_sha256':imported['original_file_sha256'], 'imported_at':imported['imported_at'],
        'prior_result_exposure':imported['policy']['prior_result_exposure'], 'through_batch':batch_number,
        'cohort_races':len(origin['races']), 'model_slots':len(rows), 'label_observations':len(observations),
        'sport':'boat', 'other_sports_real_evidence':False,
        'models':[metrics(rows,m) for m in origin['models']], 'rows':rows,
        'descriptive_timing_cohort':{'selection':'ORIGINAL_LOCAL_READBACK_BEFORE_PLANNED_CUTOFF_NOT_PREDECLARED',
            'race_ids':[r['race_id'] for r in origin['races'] if r['local_pre_cutoff_readback']],
            'models':[metrics(descriptive,m) for m in origin['models']]}}
