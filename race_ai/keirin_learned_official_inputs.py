"""Adapt one independently admitted official A/B original to the frozen learned model."""

from copy import deepcopy
import re

from . import keirin_dossier_conditions as conditions
from . import keirin_dossier_race_context as context
from . import keirin_github_origin_evidence as origin
from . import keirin_nationwide_auto_generator as model
from . import keirin_official_form_history as form
from . import keirin_official_nationwide_extension as extension
from . import keirin_official_sp_receipt as receipt


def _need(ok, reason):
    if not ok:
        raise ValueError('KEIRIN_LEARNED_OFFICIAL_' + reason)


def _bound_original(payload, original):
    race_id, snapshot, baseline = original['race_id'], original['snapshot'], original['baseline']
    generation = model.when(baseline['generated_at'])
    cutoff = model.when(baseline['published_cutoff_at'])
    proof = original['origin_receipts']['baseline_origin']
    _need(context._race_day(race_id) == original['day_jst'] == payload['day_jst'] ==
          cutoff.astimezone(form.JST).date().isoformat() and
          race_id == snapshot['race_id'] == baseline['race_id'] == proof['race_id'] == payload['race_id'] and
          baseline == payload['baseline'] and snapshot == payload['snapshot'] and
          baseline['source_facts_sha256'] == model.digest(snapshot) and
          baseline['prediction_sha256'] == model.digest({k: v for k, v in baseline.items() if k != 'prediction_sha256'}) and
          proof['schema'] == origin.SCHEMA and proof['state'] == 'GITHUB_PRE_CUTOFF_ORIGIN_VERIFIED' and
          proof['cipher_sha256'] == original['baseline_cipher_sha256'] == payload['baseline_cipher_sha256'] and
          proof['evidence_sha256'] == model.digest({k: v for k, v in proof.items() if k != 'evidence_sha256'}) and
          model.when(proof['official_cutoff_at']) == cutoff and
          model.when(payload['baseline_sealed_at']) == model.when(original['baseline_sealed_at']) and
          generation <= model.when(original['baseline_sealed_at']) <= model.when(proof['latest_server_evidence_at']) < cutoff,
          'ORIGINAL_BINDING')
    model.validate_snapshot(snapshot, computed_at=baseline['generated_at'])
    return race_id, snapshot, generation, cutoff


def _page(snapshot, kind, url, digest, at):
    return sum(page['kind'] == kind and page['url'] == url and page['bytes_sha256'] == digest and
               model.when(page['captured_at']) == at for page in snapshot['source_pages']) == 1


def _labelled(document, labels):
    # Only a closed, dedicated heading/value pair supplies these extra fields.
    # Unlabelled numeric spans (including undocumented IDs) are insufficient.
    values = {label: [] for label in labels}
    for node in document.nodes:
        if node.tag != 'tr' or not node.closed:
            continue
        cells = [child for child in node.children if child.tag in ('th', 'td')]
        for heading, value in zip(cells, cells[1:]):
            if heading.closed and value.closed and heading.tag == 'th' and value.tag == 'td':
                label = receipt._norm(form._text(heading))
                if label in values:
                    values[label].append(receipt._norm(form._text(value)))
    return {label: found[0] if len(found) == 1 else '' for label, found in values.items()}


def _profile_features(source, snapshot, rider, card_rider, generation):
    registration = rider['athlete_id']
    url = 'https://keirin.jp/sp/racerracentrecord?snum=' + registration
    observed = form._aware(source['observed_at'])
    digest = source['expected_sha256']
    _need(source['registration_id'] == registration and source['source_url'] == url and
          type(source['http_status']) is int and source['http_status'] == 200 and observed <= generation and
          _page(snapshot, 'PROGRAM', url, digest, observed), 'PROFILE_BINDING')
    document = form._document(extension._source(source['raw_bytes'], digest))
    _need(form._text(form._one(document, 'regnum')) == registration and
          receipt._norm(form._text(form._one(document, 'UNQ_orlabel_1'))) == receipt._norm(card_rider['name']) and
          form._updated(form._text(form._one(document, 'UNQ_orlabel_99')), observed) <= observed,
          'PROFILE_IDENTITY_OR_CLOCK')
    values = _labelled(document, ('年齢', '2連対率', '3連対率'))
    age = re.fullmatch(r'([0-9]{2})(?:歳)?', values['年齢'])
    age = int(age[1]) if age and 18 <= int(age[1]) <= 80 else None
    rates = {}
    for feature, label in (('top2_rate', '2連対率'), ('top3_rate', '3連対率')):
        value = re.fullmatch(r'([0-9]{1,3}(?:\.[0-9]{1,3})?)%?', values[label])
        rates[feature] = (float(value[1]) if value and
                          round(rider['recent_form_score'] * 100, 8) <= float(value[1]) <= 100 else None)
    if None not in rates.values() and rates['top2_rate'] > rates['top3_rate']:
        rates = dict.fromkeys(rates)
    return dict(age=age, gear=None, **rates)


def project(payload, original):
    """Return model inputs only after the caller has independently admitted the original.

    Outcome, odds and conditioned-history fields are never used. Optional facts
    come only from the source receipts already attached at A/B generation.
    """
    race_id, snapshot, generation, cutoff = _bound_original(payload, original)
    args = payload['baseline_arguments']
    card_args = args['card_arguments']
    card = extension.parse_extension_card(**card_args, now=generation)
    observed = form._aware(card['source_observed_at'])
    digest = card['source_sha256']
    _need(race_id == card['race_id'] and model.when(card['official_cutoff_at']) == cutoff and
          card['competition'] == snapshot['competition'] and card['round_stage_raw'] == snapshot['round_stage'] and
          card['line_prediction']['groups'] == snapshot['line_groups'] and
          snapshot['cutoff_source']['bytes_sha256'] == digest and
          model.when(snapshot['cutoff_source']['captured_at']) == observed and
          _page(snapshot, 'RACECARD', card['source_url'], digest, observed), 'CARD_BINDING')
    marks = args['prediction_source']
    marks_at = form._aware(marks['observed_at'])
    _need(observed <= marks_at <= generation and
          _page(snapshot, 'MARKS', marks['request_url'], marks['expected_sha256'], marks_at), 'MARKS_BINDING')
    extension._source(marks['raw_bytes'], marks['expected_sha256'])
    roster = context._identity(snapshot['riders'], 'car', 'athlete_id')
    _need(roster == context._identity(card['riders'], 'car', 'registration_id'), 'ROSTER_BINDING')
    embedded = receipt._embedded(receipt._body(card_args['detail_raw'], digest))['SJ0315']['sensyuTypeInfo']
    classes = {int(row['syaban']): receipt._norm(row['kyuhan']).replace('級', '').removesuffix('班')
               for row in embedded}
    profile_sources = args['profile_sources']
    profiles = {source['registration_id']: source for source in profile_sources}
    _need(len(profiles) == len(profile_sources) == len(roster) and set(profiles) == set(roster.values()),
          'PROFILE_ROSTER_BINDING')
    card_rows = {row['car']: row for row in card['riders']}
    riders = []
    for rider in sorted(snapshot['riders'], key=lambda row: row['car']):
        car, mark = rider['car'], rider['mark_rank']
        # parse_extension_card already validates the published class pattern.
        rider_class = classes[car]
        style = None if rider['style'] == 'UNKNOWN' else rider['style']
        optional = _profile_features(profiles[roster[car]], snapshot, rider, card_rows[car], generation)
        riders.append(dict(car=car, mark_rank=len(roster) + 1 if mark == 'UNMARKED' else mark,
                           points=rider['competition_points'], win_rate=round(rider['recent_form_score'] * 100, 8),
                           style=style, rider_class=rider_class, **optional))
    try:
        grades = conditions.calendar_meeting_grades(card_args['calendar_receipt'], day=card['event_date_jst'], now=generation)
    except (ValueError, KeyError):
        grades = {}
    return dict(race_id=race_id, riders=riders, line_groups=deepcopy(snapshot['line_groups']),
                competition=snapshot['competition'], meeting_grade=grades.get(card['venue_code']),
                round_stage=conditions.round_stage(snapshot['round_stage']))


def availability(projected):
    """Count present features, with rider denominators and race-level indicators."""
    riders = projected['riders']
    counts = {key: sum(row[key] is not None for row in riders) for key in riders[0] if key != 'car'}
    return dict(counts, races=1, riders=len(riders), **{
        key: int(projected[key] is not None) for key in ('line_groups', 'competition', 'meeting_grade', 'round_stage')})
