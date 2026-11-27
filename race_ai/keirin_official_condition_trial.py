"""Preregistered, read-only paired prediction using the original tactical scenarios."""
from dataclasses import dataclass
from datetime import date, timedelta
from hashlib import sha256
from itertools import permutations
from math import exp, fsum, isfinite
import re

from . import keirin_dossier_conditions as dossier
from . import keirin_joint_forecast as joint_forecast
from . import keirin_nationwide_auto_generator as model
from . import keirin_public_forecasts as public
from .keirin_joint_finish import JointFinish

SCHEMA = 'RACE_AI_KEIRIN_OFFICIAL_CONDITION_TRIAL_V1'
BASELINE = 'official-b-scenarios-with-full-support-v1'
CHALLENGER = 'official-b-scenarios-with-meeting-round-history-v1'
COMBINED_MODEL = 'official-and-research-ensemble-v1'
FORM_MODELS = ('baseline-plus-documented-form-v1', 'six-phase-plus-documented-form-v1')
MIN_STARTS = 10
WITNESS_MARGIN = timedelta(minutes=15)
FULL_SUPPORT = 0.20
STUDY_FIRST_DAY = date(2026, 11, 27)
STUDY_DAYS = 180


def study_is_open(day):
    return STUDY_FIRST_DAY <= date.fromisoformat(day) < STUDY_FIRST_DAY + timedelta(days=STUDY_DAYS)


def _need(ok, reason):
    if not ok:
        raise ValueError('OFFICIAL_CONDITION_TRIAL_' + reason)


@dataclass(frozen=True)
class HistoryPacket:
    commit: str
    sha256: str
    day: str
    published_at: str
    races: dict
    cells: dict

    @classmethod
    def read(cls, commit, raw):
        _need(type(commit) is str and re.fullmatch(r'[0-9a-f]{40}', commit) and
              type(raw) is bytes and 0 < len(raw) <= dossier.MAX_BYTES, 'HISTORY_BYTES')
        packet = dossier.checked_day(public._json(raw))
        return cls(commit, sha256(raw).hexdigest(), packet['day'], packet['published_at'],
                   {row['race_id']: row for row in packet['races']},
                   {(row['registration'], cell['meeting_grade'], cell['round_stage']): cell
                    for row in packet['riders'] for cell in row['cells']
                    if cell['meeting_grade'] is not None and cell['round_stage'] is not None})

    @classmethod
    def from_repository(cls, repo, day, *, pinned_commit=None, allow_previous=False):
        store = public.PublicForecastGit(repo)
        head = pinned_commit or store.head()
        if head is None:
            return None
        store.fetch(head)
        recent = [day]
        if allow_previous:
            recent.append((date.fromisoformat(day) - timedelta(days=1)).isoformat())
        for dated in recent:
            raw = store.read_previous(head, f'rider-conditions/{dated}.json')
            if raw is not None:
                packet = cls.read(head, raw)
                _need(packet.day == dated, 'HISTORY_DAY')
                return packet
        return None


def build_from_official_card(snapshot, baseline, arguments, history):
    from scripts.keirin_public_rider_projection import project_sp_starter_row

    if history is None:
        return None
    condition = dossier.condition_for_card(arguments, now=model.when(baseline['generated_at']))
    origins = project_sp_starter_row(arguments, snapshot)['riders']
    roster = [dict(car=row['number'], name=row['name'], registration=row['registration']) for row in origins]
    return build_pair(snapshot, baseline, condition, roster, history)


def _reference_mass(snapshot, baseline):
    powers = {car: exp(2 * strength) for car, strength in model._strengths(snapshot['riders']).items()}
    total = fsum(powers.values())
    mass = {}
    for a, b, c in permutations(sorted(powers), 3):
        first = powers[a] / total
        second = powers[b] / (total - powers[a])
        third = powers[c] / (total - powers[a] - powers[b])
        mass[a, b, c] = FULL_SUPPORT * first * second * third
    for scenario in baseline['B']['six_phase_scenarios']:
        order = tuple(scenario['projected_3ren_tan'])
        mass[order] += (1 - FULL_SUPPORT) * scenario['relative_research_weight']
    return powers, mass


def build_pair(snapshot, baseline, condition, roster, history):
    """Use the same immutable A/B input and vary only a supported exact condition."""
    rid, generated = snapshot['race_id'], baseline['generated_at']
    model.validate_snapshot(snapshot, computed_at=generated)
    _need(baseline['race_id'] == rid and baseline['source_facts_sha256'] == model.digest(snapshot) and
          baseline['prediction_sha256'] == model.digest({key: value for key, value in baseline.items()
                                                         if key != 'prediction_sha256'}), 'BASELINE')
    cutoff = model.when(snapshot['published_cutoff_at'])
    observed = model.when(generated)
    if history is None or cutoff - observed < WITNESS_MARGIN or model.when(history.published_at) > observed:
        return None
    race_day = date.fromisoformat(f'{rid[:4]}-{rid[4:6]}-{rid[6:8]}')
    days_behind = (race_day - date.fromisoformat(history.day)).days
    if (days_behind not in (0, 1) or condition['race_id'] != rid or
            condition['round_label'] != snapshot['round_stage']):
        return None
    grade, stage = condition['meeting_grade'], condition['round_stage']
    if grade is None or stage is None or model.when(condition['source_at']) > observed:
        return None
    if days_behind == 0:
        previous_card = history.races.get(rid)
        fields = ('meeting_grade', 'round_stage', 'round_label')
        if previous_card is None or any(condition[key] != previous_card[key] for key in fields):
            return None
    bindings = {row['car']: row['athlete_id'] for row in snapshot['riders']}
    _need(len(roster) == len(bindings) and {r['car']: r['registration'] for r in roster} == bindings, 'ROSTER')
    corrections = {}
    for rider in snapshot['riders']:
        cell = history.cells.get((rider['athlete_id'], grade, stage))
        if cell is None or cell['numeric_finishes'] < MIN_STARTS:
            continue
        starts = cell['numeric_finishes']
        difference = cell['wins'] / starts - rider['recent_form_score']
        corrections[rider['car']] = max(-0.12, min(0.12, 0.8 * difference * starts / (starts + 30)))
    if not corrections:
        return None
    powers, base_mass = _reference_mass(snapshot, baseline)
    delta = {car: corrections.get(car, 0.0) for car in powers}
    tilted = {(a, b, c): value * exp(2 * delta[a] + delta[b] + 0.5 * delta[c])
              for (a, b, c), value in base_mass.items()}
    total = fsum(tilted.values())
    input_sha = model.digest(dict(snapshot_sha256=model.digest(snapshot), condition=condition,
                                  historical_release=history.commit, historical_packet_sha256=history.sha256))
    identification = dict(race_id=rid, generated_at=generated, cutoff_at=snapshot['published_cutoff_at'],
                          source_as_of=max(map(model.when, (snapshot['as_of'], history.published_at,
                                                             condition['source_at']))).isoformat(),
                          model_version=SCHEMA, input_sha256=input_sha, source_packet_sha256=history.sha256,
                          source_forecast_generated_at=generated, riders=roster)
    original = joint_forecast.build_forecast(JointFinish(sorted(powers), base_mass, tail=(0.0, 0.0)),
                                             model_id=BASELINE, **identification)
    candidate = joint_forecast.build_forecast(JointFinish(sorted(powers),
                                              {key: value / total for key, value in tilted.items()}, tail=(0.0, 0.0)),
                                              model_id=CHALLENGER, **identification)
    return dict(schema=SCHEMA, race_id=rid, baseline_prediction_sha256=baseline['prediction_sha256'],
                historical_release=history.commit, historical_packet_sha256=history.sha256,
                historical_packet_day=history.day,
                meeting_grade=grade, round_stage=stage, covered_riders=len(corrections),
                baseline=original, challenger=candidate)


def _rank_mass(tickets, outcomes):
    mass = {tuple(order): 1.0 / rank for rank, order in enumerate(tickets, 1)}
    _need(1 <= len(tickets) <= 12 and len(mass) == len(tickets) and
          mass.keys() <= outcomes, 'COMBINED_RANKING')
    total = fsum(mass.values())
    return {order: value / total for order, value in mass.items()}


def _display_models(snapshot, outcomes):
    try:
        analysis = model.generate_evidence_analysis(snapshot)
    except model.AutomaticForecastError:
        return {}
    models = {}
    for arm in ('A', 'B'):
        forecast = analysis[arm]
        # The display model may abstain even though it lists candidate support.
        if not forecast['ranked_tickets']:
            continue
        rows = forecast['candidate_evidence']['3t']
        mass = {tuple(row['ticket']): row['support'] for row in rows}
        _need(len(mass) == len(rows) and mass.keys() <= outcomes and
              all(isfinite(value) and value > 0 for value in mass.values()), 'COMBINED_DISPLAY_SUPPORT')
        total = fsum(mass.values())
        models[forecast['model']] = {order: value / total for order, value in mass.items()}
    return models


def build_combined(snapshot, original, pair, *, generated_at, form_shadow=None, supplement=None):
    """Fuse live and research forecasts on the same verified pre-race inputs."""
    model.validate_snapshot(snapshot, computed_at=original['generated_at'])
    prediction_sha = original['prediction_sha256']
    snapshot_sha = model.digest(snapshot)
    _need(original['schema'] == model.PREDICTION and pair['schema'] == SCHEMA and
          original['A']['model'] == model.MODEL_A and original['B']['model'] == model.MODEL_B and
          original['source_facts_sha256'] == snapshot_sha and original['race_id'] == snapshot['race_id'] and
          pair['baseline_prediction_sha256'] == prediction_sha and
          model.digest({k: v for k, v in original.items() if k != 'prediction_sha256'}) == prediction_sha,
          'COMBINED_ORIGINAL')
    baseline, challenger = pair['baseline'], pair['challenger']
    fields = ('cars', 'race_id', 'input_sha256', 'source_packet_sha256', 'generated_at', 'cutoff_at',
              'source_as_of', 'source_forecast_generated_at')
    for record, identity in ((baseline, BASELINE), (challenger, CHALLENGER)):
        joint_forecast.validate_forecast(record)
        _need(record['model_id'] == identity and record['model_version'] == SCHEMA and
              record['scope'] == 'PROSPECTIVE_RESEARCH', 'COMBINED_COMPONENT')
    roster = [{key: row[key] for key in ('car', 'name', 'registration')} for row in baseline['riders']]
    research_roster = [{key: row[key] for key in ('car', 'name', 'registration')} for row in challenger['riders']]
    _need(all(baseline[field] == challenger[field] for field in fields) and roster == research_roster and
          {row['car']: row['registration'] for row in roster} ==
          {rider['car']: rider['athlete_id'] for rider in snapshot['riders']} and
          baseline['race_id'] == pair['race_id'] == original['race_id'] and
          baseline['generated_at'] == baseline['source_forecast_generated_at'] == original['generated_at'] and
          baseline['cutoff_at'] == original['published_cutoff_at'] and
          baseline['source_packet_sha256'] == pair['historical_packet_sha256'], 'COMBINED_INPUTS')

    base_mass, research_mass = ({tuple(row['order']): row['probability'] for row in record['trifectas']}
                                for record in (baseline, challenger))
    outcomes = base_mass.keys()
    current = {identity: _rank_mass(original[arm]['ranked_tickets'], outcomes)
               for arm, identity in (('A', model.MODEL_A), ('B', model.MODEL_B))}
    research = [{BASELINE: base_mass, CHALLENGER: research_mass}]
    held = {}
    sources = [model.when(baseline['source_as_of'])]
    if form_shadow is not None:
        form_sha = form_shadow['sha256']
        _need(form_shadow['baseline_prediction_sha256'] == prediction_sha and
              form_shadow['baseline_source_sha256'] == snapshot_sha and
              form_shadow['condition_supplement_sha256'] == model.digest(supplement) and
              form_shadow['race_id'] == original['race_id'] and
              form_shadow['generated_at'] == original['generated_at'] and
              form_shadow['published_cutoff_at'] == original['published_cutoff_at'] and
              model.digest({k: v for k, v in form_shadow.items() if k != 'sha256'}) == form_sha,
              'COMBINED_FORM_INPUTS')
        forms = {}
        for arm, identity in zip(('A_research', 'B_research'), FORM_MODELS, strict=True):
            _need(form_shadow[arm]['model'] == identity, 'COMBINED_FORM_MODEL')
            forms[identity] = _rank_mass(form_shadow[arm]['ranked_tickets'], outcomes)
        sources.extend(model.when(page['captured_at']) for page in supplement['source_pages'])
        research.append(forms)
    else:
        form_sha = None
        held.update(dict.fromkeys(FORM_MODELS, 'NO_AUTHENTICATED_FORM_ORIGINAL'))
    display = _display_models(snapshot, outcomes)
    if display:
        research.append(display)
    for identity in (model.EVIDENCE_A, model.EVIDENCE_B):
        if identity not in display:
            held[identity] = 'DISPLAY_MODEL_ABSTAINED_OR_INPUT_UNAVAILABLE'

    # Current forecasts get half the mass. Available research families share
    # the other half equally, with equal weight for arms within each family.
    weighted = [(identity, distribution, 0.25) for identity, distribution in current.items()]
    for family in research:
        share = 0.5 / len(research) / len(family)
        weighted.extend((identity, distribution, share) for identity, distribution in family.items())
    weights = {identity: weight for identity, _, weight in weighted}
    mass = {order: fsum(weight * distribution.get(order, 0.0)
                        for _, distribution, weight in weighted) for order in outcomes}
    law = JointFinish(baseline['cars'], mass, tail=(0.0, 0.0))
    forecast = joint_forecast.build_forecast(
        law, race_id=baseline['race_id'], generated_at=generated_at, cutoff_at=baseline['cutoff_at'],
        source_as_of=max(sources).isoformat(), model_id=COMBINED_MODEL, model_version='v1',
        input_sha256=model.digest(dict(original_sha256=prediction_sha, condition_trial_sha256=model.digest(pair),
                                      form_sha256=form_sha, model_id=COMBINED_MODEL, weights=weights, held=held)),
        source_packet_sha256=baseline['source_packet_sha256'],
        source_forecast_generated_at=original['generated_at'], riders=roster)
    return dict(forecast, component_weights=weights, component_holds=held)
