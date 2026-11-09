"""Connect replayable measured-history candidates to the existing B input map.

An adapter, not a new model. Legacy A incorrectly aliases final-half-lap
performance with acceleration; this adapter NEVER fills that alias. It only
supplies B's existing late_lap_and_agari_time field from the fixed historical
percentile formula. Partial input, source rights and live model readiness
remain separate. No missing data, publication timestamp or score is invented.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import math

from .keirin_allowed_delivery import RIDER_MAP_DISTINCT_B, DISTINCT_B_ID
from .keirin_preflight import expected_keys
from .keirin_result_delivery import canonical, utc
from .keirin_real_source_gap_report import inspect_source_gaps
from .keirin_prior_private_stage import (
    private_research_packet, _private_root, read_private_research_packet,
)
from .keirin_permissioned_owner import _write_private_once
from .keirin_winticket_prior_events import PriorSourceError


def need(ok, code):
    if not ok:
        raise PriorSourceError(code)


def attach_prior_finishing_input(card, packet):
    """Return a new partial packet with actual computation time and lineage."""
    inspect_source_gaps(card)
    expected = private_research_packet(
        packet['source_reference'], packet['prior_events'],
        packet['candidate_snapshot'],
        racecard_sha256=packet['racecard_original_sha256'],
        day_index_sha256=packet['day_index_original_sha256'],
        as_of=packet['calculated_as_of'])
    need(packet == expected, 'PRIOR_INPUT_REPLAY_PACKET_CHANGED')
    target = packet['source_reference']['target']
    roster = packet['source_reference']['rider_ids']
    need(card['html_sha256'] == packet['racecard_original_sha256'] and
         card['race_id'] == packet['target_race_id'] and
         utc(card['source_published_cutoff_at_utc']) == utc(target['cutoff']) and
         utc(card['source_capture_at_utc']) <= utc(packet['calculated_as_of']) <
         utc(target['cutoff']), 'PRIOR_INPUT_ORIGINAL_OR_TIME_MISMATCH')
    need({r['source_player_id'] for r in card['riders']} == set(roster),
         'PRIOR_INPUT_RIDER_IDENTITY_MISMATCH')
    need(RIDER_MAP_DISTINCT_B['finishing_power'] == ('late_lap_and_agari_time', 'ratio'),
         'EXISTING_DISTINCT_B_INPUT_MAPPING_CHANGED')
    out = deepcopy(card)
    evidence = {}
    packet_sha = sha256(canonical(packet)).hexdigest()
    for rider in card['riders']:
        item = packet['candidate_snapshot']['riders'][rider['source_player_id']][
            'features']['finishing_power']
        value = item['candidate_value']
        if value is None:
            continue
        need(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1 and
             type(item['sample_count']) is int and
             item['sample_count'] >= item['minimum_required'] and
             item['approved_for_pr71_input'] is False,
             'PRIOR_INPUT_UNSUPPORTED_OR_SELF_APPROVED_VALUE')
        key = f"rider/{rider['car_number']}/late_lap_and_agari_time"
        need(key not in out['direct_verified_fields'],
             'EXISTING_FINISHING_SOURCE_OVERWRITE_FORBIDDEN')
        out['direct_verified_fields'][key] = value
        evidence[key] = {
            'value': value, 'sample_n': item['sample_count'],
            'feature_source_profile': DISTINCT_B_ID,
            'model_feature': 'finishing_power',
            'formula_version': packet['candidate_snapshot']['formula_version'],
            'private_prior_packet_sha256': packet_sha,
            'original_racecard_html_sha256': card['html_sha256'],
            'calculated_at': packet['calculated_as_of'],
            'source_published_at': None,
            'definition': 'within-prior-race half-lap-time percentile, not acceleration',
            'approved_for_pr71_input': False,
            'independent_source_rights_verified': False,
        }
    registry = set(expected_keys([r['car_number'] for r in out['riders']]))
    keys = set(out['direct_verified_fields'])
    need(keys <= registry, 'PRIOR_UNREGISTERED_INPUT_FIELD')
    out.update({
        'verified_registry_keys': sorted(keys),
        'unavailable_registry_keys': sorted(registry - keys),
        'registry_verified_count': len(keys),
        'registry_unavailable_count': len(registry - keys),
        'full_347_or_437_verified': keys == registry,
        'prior_finishing_input_evidence': evidence,
        'derived_input_as_of': packet['calculated_as_of'],
        'derived_input_partial_only': True,
    })
    inspect_source_gaps(out)
    return out


def stage_connected_prior_input(root, source_card, packet):
    """Reuse the existing private partial-racecard folder, never the pre/ queue.

    The matching replayable prior packet must already exist in private storage.
    An incomplete source stays out of live forecasts and production AES history.
    """
    owner = _private_root(root)
    packet_sha = sha256(canonical(packet)).hexdigest()
    prior_file = owner / 'keirin_prior_research' / (packet_sha + '.json')
    replay = read_private_research_packet(prior_file, expected_sha256=packet_sha)
    need(replay == packet, 'PRIOR_SOURCE_READBACK_MISMATCH')
    connected = attach_prior_finishing_input(source_card, replay)
    folder = owner / 'winticket_racecard_partial'
    need(not folder.is_symlink(), 'PRIOR_INPUT_OUTPUT_SYMLINK')
    folder.mkdir(mode=0o700, exist_ok=True)
    digest = sha256(canonical(connected)).hexdigest()
    path = folder / (digest + '.json')
    created = _write_private_once(path, connected)
    raw = path.read_bytes()
    need(sha256(raw).hexdigest() == digest and json.loads(raw) == connected and
         attach_prior_finishing_input(source_card, replay) == connected,
         'PRIOR_CONNECTED_INPUT_READBACK_FAILED')
    return {
        'state': 'PRIVATE_DISTINCT_B_PARTIAL_INPUT_REPLAYED',
        'connected_input_sha256': digest,
        'prior_packet_sha256': packet_sha,
        'new_partial_input': created,
        'derived_finishing_slots': len(connected['prior_finishing_input_evidence']),
        'public_plaintext_written': False,
        'production_aes_archived': False,
        'live_model_invoked': False,
    }
