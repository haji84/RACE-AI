"""Authenticate the owner's exact all-family personal research decision.

This record is separate from the old two-family decision and never grants a
provider licence, publishes originals, promotes a candidate or issues itself
while fitting. Only an explicit operator invocation creates this record.
"""
import hashlib
import hmac
import re

from .actions_contract import digest
from .boat_pdca_state import state_key
from .boat_venue_research import _bindings, _refs as _legacy_refs, _time
from .boat_venue_research import RIGHTS as LEGACY_RIGHTS
from .existing_model_coverage import catalog
from .observed_p1_connection import RIGHTS as HTML_RIGHTS


SCHEMA = 'RACE_AI_ALL_EXISTING_MODEL_OWNER_PERSONAL_RESEARCH_V1'
PURPOSE = 'EXISTING_ALL_FAMILIES_SHADOW_FIT'
INSTRUCTION = 'OWNER_INSTRUCTION_20261107_ALL_MODELS'
DOMAIN = b'RACE_AI_ALL_EXISTING_MODEL_OWNER_PERSONAL_RESEARCH_DECISION_V1'
FALSE_FIELDS = ('provider_permission_confirmed', 'production_promoted',
                'commercial_use_permitted', 'public_raw_data_permitted')
FIELDS = frozenset(('repository_id', 'basis', 'purpose', 'instruction_ref',
    'issued_at', 'expires_at', 'source_pointer_sha256', 'source_content_sha256',
    'dataset_pointer_sha256', 'source_refs_sha256', 'intake_sha256',
    'registry_sha256', 'registered_model_ids', 'model_cells', *FALSE_FIELDS))


def _need(ok, reason):
    if not ok:
        raise ValueError('ALL_MODEL_OWNER_RESEARCH_'+reason)


def _scope(registry_hash):
    # The active native registry is bound as well as the public family/sport
    # roster. A caller cannot sign a different parameter/adapter registry.
    from .all_existing_model_registry import registry_sha256
    _need(type(registry_hash) is str and re.fullmatch('[a-f0-9]{64}', registry_hash) and
          registry_hash == registry_sha256(), 'REGISTRY_MISMATCH')
    rows = catalog()
    ids = [row['model_id'] for row in rows]
    cells = sorted(sport+'/'+row['model_id']
                   for row in rows for sport in row['applicable_sports'])
    _need(len(ids) == len(set(ids)) == 16 and len(cells) == len(set(cells)) == 31,
          'REGISTRY_ROSTER_INVALID')
    return dict(registry_sha256=registry_hash, registered_model_ids=ids, model_cells=cells)


def _source_refs(values):
    """Bind exact reviewed source pairs, including existing current P1 HTML.

    Reuse the legacy official-host and owner-GitHub URL guard. Mapping the new
    right for that guard does not alter the actual pair retained in the MAC.
    """
    _need(isinstance(values, (list, tuple, set, frozenset)) and values, 'SOURCE_SCOPE')
    pairs = set()
    for item in values:
        _need(isinstance(item, (list, tuple)) and len(item) == 2 and
              all(type(value) is str for value in item), 'SOURCE_SCOPE')
        url, rights = item
        _need(rights in LEGACY_RIGHTS or rights == HTML_RIGHTS, 'SOURCE_SCOPE')
        guard_right = 'OWNER_PERSONAL_OFFICIAL_B_ANALYSIS_20261104' if rights == HTML_RIGHTS else rights
        _legacy_refs([(url, guard_right)])
        pairs.add((url, rights))
    return sorted(pairs)


def _bound(source_pointer, state_content_sha256, dataset_pointer, source_refs,
           intake_sha256, registry_sha256):
    _need(type(intake_sha256) is str and re.fullmatch('[a-f0-9]{64}', intake_sha256),
          'INTAKE_HASH_INVALID')
    _need(type(state_content_sha256) is str and
          re.fullmatch('[a-f0-9]{64}', state_content_sha256), 'SOURCE_CONTENT_HASH_INVALID')
    for pointer, hash_field in ((source_pointer, 'cipher_sha256'),
                                (dataset_pointer, 'dataset_sha256')):
        _need(type(pointer) is dict and type(pointer.get('source_commit')) is str and
              re.fullmatch('[a-f0-9]{40}', pointer['source_commit']) and
              type(pointer.get(hash_field)) is str and
              re.fullmatch('[a-f0-9]{64}', pointer[hash_field]), 'POINTER_HASH_INVALID')
    return dict(**_bindings(source_pointer, state_content_sha256, dataset_pointer),
                source_refs_sha256=digest(_source_refs(source_refs)), intake_sha256=intake_sha256,
                **_scope(registry_sha256))


def _mac(decision):
    key = hmac.digest(state_key('production'), DOMAIN, 'sha256')
    return hmac.new(key, digest(decision).encode('ascii'), hashlib.sha256).hexdigest()


def issue_decision(*, source_pointer, state_content_sha256, dataset_pointer,
                   source_refs, intake_sha256, registry_sha256, now, expires_at):
    """Explicitly authenticate owner intent for one fixed private intake."""
    state_key('production')  # A missing key fails before inspecting any input.
    started = _time(now); expires = _time(expires_at)
    _need(started < expires, 'EXPIRY_INVALID')
    decision = dict(repository_id='1416489937', basis='OWNER_PERSONAL_RESEARCH',
        purpose=PURPOSE, instruction_ref=INSTRUCTION, issued_at=started.isoformat(),
        expires_at=expires.isoformat(),
        **_bound(source_pointer, state_content_sha256, dataset_pointer, source_refs,
                 intake_sha256, registry_sha256),
        **{field: False for field in FALSE_FIELDS})
    return dict(schema=SCHEMA, decision=decision, mac=_mac(decision))


def verify_decision(record, *, source_pointer, state_content_sha256, dataset_pointer,
                    source_refs, intake_sha256, registry_sha256, now):
    """Verify all scope fields; a legacy two-family MAC is never accepted."""
    state_key('production')
    _need(type(record) is dict and set(record) == {'schema', 'decision', 'mac'} and
          record['schema'] == SCHEMA and type(record['decision']) is dict and
          set(record['decision']) == FIELDS, 'RECORD_INVALID')
    decision = record['decision']
    _need(type(record['mac']) is str and re.fullmatch('[a-f0-9]{64}', record['mac']) and
          hmac.compare_digest(record['mac'], _mac(decision)), 'SIGNATURE_INVALID')
    _need(decision['repository_id'] == '1416489937' and
          decision['basis'] == 'OWNER_PERSONAL_RESEARCH' and decision['purpose'] == PURPOSE and
          decision['instruction_ref'] == INSTRUCTION and
          all(decision[field] is False for field in FALSE_FIELDS), 'USE_SCOPE_INVALID')
    current = _time(now); issued = _time(decision['issued_at']); expires = _time(decision['expires_at'])
    _need(issued < expires, 'EXPIRY_INVALID')
    _need(issued <= current, 'DECISION_FROM_FUTURE')
    _need(current < expires, 'DECISION_EXPIRED')
    expected = _bound(source_pointer, state_content_sha256, dataset_pointer, source_refs,
                      intake_sha256, registry_sha256)
    _need(all(decision[field] == value for field, value in expected.items()), 'SCOPE_CHANGED')
    return digest(record)
