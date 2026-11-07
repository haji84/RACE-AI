"""Typed confirmed-order research labels with no monetary evaluation.

This pure validator grants no source permission and authenticates no capture.
The official parser and owner archive reader must independently bind original
source bytes, the complete normal finish, and the matching trifecta selection.
"""
from copy import deepcopy
from datetime import datetime
import re

from .manual_official_capture import official_rights_ref, validate_source_pair

SCHEMA = 'RACE_AI_OFFICIAL_ORDER_ONLY_RESULT_V1'
EVALUATION_SCOPE = 'ORDER_ONLY_NO_MONETARY_EVALUATION'
STATUS = 'rank_confirmed'
REASON = 'ORDER_CONFIRMED_PAYOUT_UNIT_UNVERIFIED'
LEGACY_OBSERVATION_FIELDS = frozenset(('race_id','sport','status','ordered_top3','roster',
    'identity_verified','captured_at','published_at','source_ref','source_rights_ref','source_sha256',
    'payout_per_100_yen','refund_numbers','closed_at','reason'))
OBSERVATION_FIELDS = LEGACY_OBSERVATION_FIELDS | frozenset(('schema','published_payout_yen',
    'payout_unit_verified','evaluation_scope'))
FIELDS = OBSERVATION_FIELDS
SPORT_MAXIMUM = {'horse':18, 'autorace':8, 'keirin':9}


def _need(ok, reason):
    if not ok: raise ValueError('OFFICIAL_ORDER_ONLY_'+reason)


def _time(value):
    _need(type(value) is str and 0 < len(value) <= 64, 'AWARE_CLOCK')
    try: parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError: raise ValueError('OFFICIAL_ORDER_ONLY_AWARE_CLOCK') from None
    _need(parsed.utcoffset() is not None, 'AWARE_CLOCK')
    return parsed


def has_order_only_markers(value):
    """Keep malformed typed labels from falling through the legacy cash path."""
    return type(value) is dict and (value.get('schema') == SCHEMA or value.get('status') == STATUS or
        bool({'published_payout_yen','payout_unit_verified','evaluation_scope'} & value.keys()))


def validate_order_only(observation, *, sport=None, roster=None, race_id=None):
    """Return an unchanged deep copy of one exact, nonmonetary normal label."""
    _need(type(observation) is dict and set(observation) == OBSERVATION_FIELDS, 'FIELDS')
    value = observation; actual_sport = value['sport']
    _need(type(actual_sport) is str and actual_sport in SPORT_MAXIMUM and
          (sport is None or type(sport) is str and sport == actual_sport), 'SPORT')
    _need(value['schema'] == SCHEMA and value['status'] == STATUS and value['reason'] == REASON and
          value['evaluation_scope'] == EVALUATION_SCOPE and value['payout_unit_verified'] is False and
          value['payout_per_100_yen'] is None, 'ORDER_ONLY_CONTRACT')
    amount = value['published_payout_yen']
    _need(amount is None or type(amount) is int and amount > 0, 'PUBLISHED_PAYOUT')
    rid = value['race_id']
    _need(type(rid) is str and 8 <= len(rid) <= 200 and not any(ord(c) < 32 or c.isspace() for c in rid), 'RACE_ID')
    if race_id is not None:
        from .existing_model_dispatch import _race_key
        _need(type(race_id) is str and _race_key(rid,actual_sport) == _race_key(race_id,actual_sport), 'RACE_ID_MISMATCH')
    actual_roster = value['roster']; maximum = SPORT_MAXIMUM[actual_sport]
    _need(type(actual_roster) is dict and 3 <= len(actual_roster) <= maximum and
          (actual_sport != 'keirin' or len(actual_roster) in (7,9)), 'FULL_ROSTER')
    _need(all(type(slot) is str and re.fullmatch(r'[1-9][0-9]?',slot) is not None and int(slot) <= maximum and
              type(identity) is str and 0 < len(identity) <= 100 and identity.strip() == identity and
              not any(ord(c) < 32 for c in identity) for slot,identity in actual_roster.items()) and
          len(set(actual_roster.values())) == len(actual_roster), 'REGISTERED_ROSTER')
    _need(roster is None or type(roster) is dict and roster == actual_roster, 'ROSTER_MISMATCH')
    order = value['ordered_top3']
    _need(type(order) is list and len(order) == 3 and all(type(n) is int and str(n) in actual_roster for n in order) and
          len(set(order)) == 3 and value['identity_verified'] is True and
          type(value['refund_numbers']) is list and not value['refund_numbers'], 'NORMAL_CONFIRMED_ORDER')
    cutoff = _time(value['closed_at']); captured = _time(value['captured_at'])
    _need(cutoff < captured, 'RESULT_CAPTURE_CLOCK')
    published = value['published_at']
    _need(published is None or cutoff < _time(published) <= captured, 'RESULT_PUBLICATION_CLOCK')
    _need(type(value['source_sha256']) is str and re.fullmatch(r'[a-f0-9]{64}',value['source_sha256']) is not None,
          'SOURCE_SHA256')
    _need(value['source_rights_ref'] == official_rights_ref(actual_sport), 'SOURCE_SPORT_RIGHTS')
    validate_source_pair(value['source_ref'],value['source_rights_ref'])
    return deepcopy(value)
