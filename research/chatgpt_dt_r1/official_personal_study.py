"""Private research comparison of independently admitted personal profile finishes."""
from collections import Counter
from itertools import groupby

from race_ai.keirin_rider_form_evidence import _finish_index

from . import official_inputs
from .abilities import augment_abilities
from .agari import augment_agari
from .context import augment_features
from .features import FEATURE_INDEX, FeatureBuilder, _bind_feature_input
from .pipeline import summarize_predictions
from .policy import checked_day, clock, digest


SCOPE = 'AFTER_THE_FACT_PROFILE_REPLAY'
BASELINE_ONLY = [FEATURE_INDEX[name] for name in (
    'history_starts_log', 'history_numeric_fraction', 'history_rest_days_log', 'history_rest_missing',
    'history_starts_7d', 'history_starts_30d', 'history_incident_rate', 'history_incident_missing',
    'history_same_class_form', 'history_same_class_log', 'history_same_class_missing')]


def add_to_builder(builder, events):
    """Update only the riders actually observed, using the official field size."""
    observed = set()
    for item in events:
        identity, rid = item['identity_key'], item['race_id']
        key = identity, rid
        previous = builder.history.get(identity, ())
        if key in observed or any(event['race_id'] == rid for event in previous):
            raise ValueError('DUPLICATE_PERSONAL_HISTORY_FINISH')
        observed.add(key)
        stamp = checked_day(f'{rid[:4]}-{rid[4:6]}-{rid[6:8]}')
        row = dict(day=stamp.isoformat(), race_id=rid, venue_code=rid[8:10], race_class=None,
            rank=item['rank'], form=_finish_index(dict(place=item['rank'], field_size=item['field_size'])),
            started=True, incident=False, half_lap_seconds=None, final_lap_seconds=None, sb_mark=None,
            source_sha256=item['source_sha256'], published_at=item['published_at'])
        builder.history[identity].append(dict(row, date=stamp, event_sha256=digest(row)))


def _paired_score(forecasts, outcomes):
    score = summarize_predictions(forecasts, outcomes)
    score.pop('proper_scores')
    return score


def personal_trial(*, trained, venues, payload, original, baseline, prior, prediction_at):
    """Compute one private comparison from a matched, independently replayable baseline.

    The input clock limits evidence. The caller separately proves actual generation
    time and sealing when this computation is used for a prospective trial.
    """
    from .official_personal_history import profile_finishes

    support = baseline['history_evidence'].get('official_support', {})
    if prior is None or not support.get('history_races'):
        return None, 'NO_REPLAYED_SEVEN_DAY_HISTORY'
    try:
        target = official_inputs.verification_payload(payload, original,
            prediction_at=prediction_at)['normalized_input']
        if (target['input_sha256'] != baseline['input_sha256'] or
                clock(target['context_as_of']) != clock(baseline['context_as_of'])):
            raise ValueError('PROFILE_TARGET_INPUT_CHANGED')
        selected = profile_finishes(original, target, prediction_at=prediction_at)
        if selected['status'] != 'READY':
            return None, selected['status']
        args = prior.arguments(payload, original, prediction_at)
        history, replay = official_inputs._history(args['history_records'], target, prediction_at,
                                                  args['history_verifier'])
        if replay != support:
            raise ValueError('PROFILE_BASELINE_HISTORY_CHANGED')
        for field in ('source_attestation_sha256', 'source_verified_at', 'source_available_at_verified',
                      'source_admission_status', 'pre_cutoff_authenticated', 'source_proof'):
            target[field] = baseline[field]
        builder = FeatureBuilder()
        for _, items in groupby(history, key=lambda row: row['day']):
            builder.update_day(items)
        add_to_builder(builder, selected['events'])
        row = builder.transform(target)
        # This source has only normal finishes. Preserve full-start, incident and class measures.
        row['features'][:, BASELINE_ONLY] = baseline['features'][:, BASELINE_ONLY]
        row['history_evidence'].update(identities_are_unresolved=False,
            identity_namespace=official_inputs.IDENTITY_NAMESPACE, official_support=support,
            personal_profile_policy=selected['policy'], personal_profile_proof_sha256=selected['proof_sha256'])
        for item in row['history_evidence']['rider_evidence'].values():
            item['official_identity_verified'] = True
        featured = augment_abilities(augment_agari(augment_features([_bind_feature_input(row)],
            venue_store=venues, as_of=prediction_at, allow_current_geometry_assumption=False)))[0]
        if featured['feature_status'] != 'READY' or featured['feature_names'] != trained.feature_names:
            raise ValueError('PROFILE_FEATURE_SCHEMA_CHANGED')
        law = trained.distribution(featured, full=True)
        forecast = dict(race_id=target['race_id'], input_sha256=target['input_sha256'], status='READY',
                        trifectas=law['trifectas'], exactas=law['exactas'])
        return dict(row=featured, forecast=forecast, used_finishes=len(selected['events'])), None
    except (ValueError, KeyError, TypeError, OverflowError):
        return None, 'PROFILE_EVIDENCE_OR_FEATURE_REPLAY_UNVERIFIED'


class OfficialPersonalStudy:
    def __init__(self, trained, venues):
        self._trained, self._venues = trained, venues
        self._candidates, self._holds = {}, Counter()
        self._used_events = 0

    def add(self, *, payload, original, baseline, prior, prediction_at):
        """Compare only after the normal settlement replays the frozen baseline."""
        computed, hold = personal_trial(trained=self._trained, venues=self._venues,
            payload=payload, original=original, baseline=baseline, prior=prior, prediction_at=prediction_at)
        if hold is not None:
            self._holds[hold] += 1
            return
        forecast = computed['forecast']
        self._candidates[forecast['race_id']] = forecast
        self._used_events += computed['used_finishes']

    def report(self, admitted, outcomes):
        pairs = admitted.keys() & self._candidates.keys()
        if len(pairs) + sum(self._holds.values()) != len(admitted):
            raise ValueError('PROFILE_FORECAST_PAIR_COUNT')
        paired_rows = [row for row in outcomes if row['race_id'] in pairs]
        scorable = [row for row in paired_rows if row['result_status'] == 'VERIFIED_NORMAL']
        baseline = _paired_score([admitted[rid] for rid in sorted(pairs)], scorable)
        candidate = _paired_score([self._candidates[rid] for rid in sorted(pairs)], scorable)
        if baseline['predicted_evaluable'] != candidate['predicted_evaluable']:
            raise ValueError('PROFILE_RESULT_PAIR_COUNT')
        return dict(scope=SCOPE, prospectively_sealed=False, production_promoted=False,
            registered_races=len(outcomes), independently_replayed_originals=len(admitted),
            replayed_pairs=len(pairs), held=dict(self._holds), official_prior_personal_finish_exposures=self._used_events,
            pair_result_states=dict(Counter(row['result_status'] for row in paired_rows)),
            official_scorable_pairs=baseline['predicted_evaluable'], archive_seven=baseline,
            seven_and_personal_days_8_to_30=candidate)
