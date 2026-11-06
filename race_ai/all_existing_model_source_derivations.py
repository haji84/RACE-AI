"""Replay the existing builders' local source manifests without granting use.

Only the caller-authenticated native payload is examined. A local URN is a
content reference, never an HTTP receipt, publication time or permission. The
returned pairs cover validated local derivations only; direct providers retain
the existing official-host and owner-GitHub restrictions.
"""
from datetime import datetime
from hashlib import sha256
import json
import re

from .actions_contract import canonical, digest, stamp
from .boat_venue_research import RIGHTS as LEGACY_RIGHTS, _refs as _legacy_refs
from .observed_p1_connection import RIGHTS, locator

NAMESPACES = frozenset(('boat-native-inputs', 'boat-clite-extra', 'official-history', 'pdca-history-report',
                        'seller-race_cards', 'seller-waku10'))
MAX_DEPTH = 32
MAX_NODES = 200000
MAX_DERIVATIONS = 4096
MAX_MEMBERS = 4096
BASE_FIELDS = {'source_ref', 'source_sha256', 'source_rights_ref', 'captured_at', 'published_at'}
_LOCAL = re.compile(r'urn:race-ai:('+'|'.join(re.escape(n) for n in sorted(NAMESPACES))+r'):([a-f0-9]{64})\Z')


def _need(ok, reason):
    if not ok:
        raise ValueError('ALL_MODEL_SOURCE_DERIVATION_'+reason)


def _time(value):
    _need(type(value) is str, 'AWARE_CLOCK_REQUIRED')
    return stamp(value)


def _clock(payload):
    snapshot = payload.get('snapshot', {})
    race = snapshot.get('race', snapshot) if type(snapshot) is dict else {}
    values = [payload.get('as_of'), race.get('as_of')]
    values.extend(payload.get(key, {}).get('captured_at') for key in ('source', 'base_source', 'facts')
                  if type(payload.get(key, {})) is dict)
    candidates = [_time(value) for value in values if value is not None]
    _need(candidates, 'NATIVE_AS_OF_REQUIRED')
    return min(candidates)


def _direct(source, clock, *, member=False, seller=False):
    _need(type(source) is dict, 'SOURCE_MEMBER_INVALID')
    url = source.get('source_ref', source.get('source_url'))
    rights = source.get('source_rights_ref')
    _need(type(url) is str and type(rights) is str and
          (rights in LEGACY_RIGHTS or rights == RIGHTS), 'DIRECT_SOURCE_SCOPE_INVALID')
    guard = 'OWNER_PERSONAL_OFFICIAL_B_ANALYSIS_20261104' if rights == RIGHTS else rights
    _legacy_refs([(url, guard)])
    if member:
        allowed = BASE_FIELDS | ({'event_date_jst', 'dataset_kind', 'metric_semantics'} if seller else set())
        _need(set(source) == allowed, 'SOURCE_MEMBER_FIELDS_INVALID')
    if member or 'source_sha256' in source:
        _need(type(source.get('source_sha256')) is str and
              re.fullmatch('[a-f0-9]{64}', source['source_sha256']), 'SOURCE_HASH_INVALID')
    captured = _time(source['captured_at']) if member or 'captured_at' in source else None
    if captured is not None:
        _need(captured <= clock, 'SOURCE_AFTER_NATIVE_AS_OF')
    if source.get('published_at') is not None:
        _need(captured is not None and _time(source['published_at']) <= captured,
              'SOURCE_PUBLICATION_CLOCK_INVALID')
    return captured


def _validate(native_payload):
    """Return verified local ``(URN, rights)`` pairs; make no permission grant.

    Future captures are compared with the native input's own observation clock.
    The enclosing record validator separately checks that clock against actual
    physical time and authenticates the saved input. Unknown or unmanifested
    URNs fail even when they appear only in a lightweight feature reference.
    """
    _need(type(native_payload) is dict, 'NATIVE_PAYLOAD_REQUIRED')
    nodes = []; references = set(); definitions = {}; count = 0
    def visit(value, depth=0, ancestors=frozenset()):
        nonlocal count
        count += 1
        _need(count <= MAX_NODES and depth <= MAX_DEPTH, 'PAYLOAD_BOUND_EXCEEDED')
        if type(value) is str:
            if value.lower().startswith('urn:'):
                _need(_LOCAL.fullmatch(value), 'UNKNOWN_LOCAL_SOURCE')
                references.add(value)
            return
        if type(value) not in (dict, list, tuple):
            return
        marker = id(value)
        _need(marker not in ancestors, 'CYCLIC_PAYLOAD')
        branch = ancestors | {marker}
        if type(value) is dict:
            nodes.append(value)
            if 'source_ref' in value and 'source_url' in value:
                _need(value['source_ref'] == value['source_url'], 'CONFLICTING_SOURCE_ALIASES')
            local = value.get('source_ref')
            if type(local) is str and local.lower().startswith('urn:') and 'source_members' in value:
                _need(_LOCAL.fullmatch(local), 'UNKNOWN_LOCAL_SOURCE')
                if local in definitions:
                    _need(canonical(definitions[local]) == canonical(value), 'CONFLICTING_LOCAL_MANIFEST')
                else:
                    _need(len(definitions) < MAX_DERIVATIONS, 'DERIVATION_BOUND_EXCEEDED')
                    definitions[local] = value
            for key, child in value.items():
                _need(type(key) is str, 'JSON_OBJECT_KEY_INVALID')
                visit(child, depth+1, branch)
        else:
            for child in value: visit(child, depth+1, branch)
    visit(native_payload)
    if not references:
        return set()
    _need(references <= definitions.keys(), 'LOCAL_MANIFEST_REQUIRED')
    clock = _clock(native_payload)
    # Freeze identity comparisons only after bounded traversal ruled out cycles.
    reports = {}
    rows = native_payload.get('rows', [])
    if any(_LOCAL.fullmatch(ref).group(1) == 'pdca-history-report' for ref in references):
        _need(type(rows) is list and 0 < len(rows) <= 240, 'PDCA_REPORT_ROWS_REQUIRED')
        order = []
        for row in rows:
            _need(type(row) is dict and set(row) == {'report_json', 'report_sha256', 'db_saved_at'} and
                  type(row['report_json']) is str and 0 < len(row['report_json'].encode()) <= 65536,
                  'PDCA_REPORT_ROW_INVALID')
            report = json.loads(row['report_json'])
            _need(type(report) is dict and canonical(report) == row['report_json'] and
                  digest(report) == sha256(row['report_json'].encode()).hexdigest() == row['report_sha256'],
                  'PDCA_REPORT_HASH_INVALID')
            _need(row['report_sha256'] not in reports, 'DUPLICATE_PDCA_REPORT')
            reports[row['report_sha256']] = (report, row)
            order.append(report.get('race_id'))
        _need(all(type(rid) is str for rid in order) and order == sorted(set(order)), 'PDCA_REPORT_ORDER_INVALID')
    verified = {}; visiting = set()
    def verify(ref):
        if ref in verified: return verified[ref]
        _need(ref not in visiting, 'CYCLIC_LOCAL_MANIFEST')
        visiting.add(ref)
        source = definitions[ref]; namespace, expected = _LOCAL.fullmatch(ref).groups()
        _need(source.get('source_sha256') == expected, 'LOCAL_SOURCE_HASH_MISMATCH')
        rights = source.get('source_rights_ref')
        _need(type(rights) is str and (rights in LEGACY_RIGHTS or rights == RIGHTS), 'LOCAL_RIGHTS_INVALID')
        members = source.get('source_members')
        _need(type(members) is list and 0 < len(members) <= MAX_MEMBERS and
              all(type(member) is dict for member in members), 'SOURCE_MEMBERS_REQUIRED')
        times = []
        for member in members:
            upstream = member.get('source_ref')
            if type(upstream) is str and upstream.lower().startswith('urn:'):
                _need(upstream in definitions, 'UPSTREAM_MANIFEST_REQUIRED')
                at = verify(upstream)
                _need(canonical(member) == canonical(definitions[upstream]), 'UPSTREAM_MANIFEST_MISMATCH')
            else:
                at = _direct(member, clock, member=True, seller=namespace.startswith('seller-'))
            _need(at is not None and at <= clock, 'UPSTREAM_CLOCK_INVALID')
            times.append(at)
        captured = max(times)
        if namespace in ('boat-native-inputs', 'official-history'):
            _need(set(source) == BASE_FIELDS | {'source_members'} and rights == RIGHTS and
                  source['published_at'] is None and _time(source['captured_at']) == captured,
                  'COMPOSITE_FIELDS_OR_CLOCK_INVALID')
            expected_members = sorted(members, key=lambda item:(item['source_ref'], item['source_sha256'], item['captured_at']))
            _need(members == expected_members and len({canonical(item) for item in members}) == len(members),
                  'COMPOSITE_MEMBER_ORDER_INVALID')
            _need(digest(members) == expected, 'COMPOSITE_HASH_MISMATCH')
        elif namespace == 'boat-clite-extra':
            _need(set(source) == BASE_FIELDS | {'source_members', 'transform_id'} and rights == RIGHTS and
                  source['published_at'] is None and len(members) == 2 and
                  source['transform_id'] == 'SHA256_UTF8_CONCAT_PROGRAM_AND_BEFOREINFO_HEX_V1',
                  'CLITE_COMPOSITE_FIELDS_INVALID')
            snapshot = native_payload.get('snapshot', {})
            race = snapshot.get('race', snapshot) if type(snapshot) is dict else {}
            rid = race.get('race_id')
            for name in ('source', 'base_source', 'facts'):
                if type(native_payload.get(name)) is dict:
                    rid = native_payload[name].get('race_id', rid)
            if type(rid) is str and rid.startswith('boat:'):
                from .frozen_day_cycle import official_id
                rid = official_id(rid)
            _need(type(rid) is str, 'CLITE_NATIVE_RACE_REQUIRED')
            for member, kind in zip(members, ('racelist', 'beforeinfo')):
                locator(member['source_ref'], kind, rid)
            program, preview = members
            _need(times[0] <= times[1] and _time(source['captured_at']) == times[1] and
                  sha256((program['source_sha256']+preview['source_sha256']).encode()).hexdigest() == expected,
                  'CLITE_COMPOSITE_HASH_OR_CLOCK_INVALID')
        elif namespace == 'pdca-history-report':
            _need(set(source) == {'source_ref', 'source_sha256', 'source_rights_ref', 'source_members'} and
                  rights == RIGHTS and expected in reports, 'PDCA_REPORT_MANIFEST_INVALID')
            report, row = reports[expected]
            _need(set(report) == {'race_id', 'official_top3', 'source_sha256', 'captured_at',
                                  'source_url', 'availability_basis'} and
                  report['availability_basis'] == 'VERIFIED_ARCHIVE_CAPTURE_BOUND', 'PDCA_REPORT_SEMANTICS_INVALID')
            rid = report['race_id']
            _need(type(rid) is str and re.fullmatch(r'[0-9]{8}-(?:0[1-9]|1[0-9]|2[0-4])-(?:0[1-9]|1[0-2])', rid),
                  'PDCA_REPORT_RACE_INVALID')
            datetime.strptime(rid[:8], '%Y%m%d')
            top = report['official_top3']
            _need(type(top) is list and len(top) == len(set(top)) == 3 and
                  all(type(number) is int and 1 <= number <= 6 for number in top), 'PDCA_REPORT_ORDER_INVALID')
            report_at = _time(report['captured_at'])
            _need(any(member['source_ref'] == report['source_url'] and
                      member['source_sha256'] == report['source_sha256'] and
                      _time(member['captured_at']) == report_at for member in members) and
                  _time(row['db_saved_at']) == captured <= clock and report_at <= captured,
                  'PDCA_REPORT_UPSTREAM_BINDING_INVALID')
        else:
            kind = namespace.removeprefix('seller-')
            _need(set(source) == {'source_ref', 'source_sha256', 'source_rights_ref', 'source_members', 'transform_id'} and
                  source['transform_id'] == 'NATIVE_CSV_DAY_AND_LANE_PROJECTION_V1' and len(members) == 1,
                  'SELLER_PROJECTION_MANIFEST_INVALID')
            projection = native_payload.get('cards' if kind == 'race_cards' else 'waku')
            _need(type(projection) is dict and 0 < len(projection) <= 288 and digest(projection) == expected,
                  'SELLER_PROJECTION_HASH_INVALID')
            proof = members[0]
            semantics = 'NATIONAL_WIN_RATING_POINTS_0_10' if kind == 'race_cards' else 'SAME_FRAME_WIN_RATING_POINTS_0_10'
            day = native_payload.get('day')
            _need(type(day) is str and datetime.fromisoformat(day).date().isoformat() == day and
                  proof['event_date_jst'] == day and proof['dataset_kind'] == kind and
                  proof['metric_semantics'] == semantics and proof['source_rights_ref'] == rights,
                  'SELLER_PROJECTION_SEMANTICS_INVALID')
            for rid, card in projection.items():
                _need(type(rid) is str and re.fullmatch(day.replace('-', '')+r'(?:0[1-9]|1[0-9]|2[0-4])(?:0[1-9]|1[0-2])', rid) and
                      type(card) is dict and card.get('レースコード') == rid, 'SELLER_PROJECTION_RACE_INVALID')
        visiting.remove(ref); verified[ref] = captured
        return captured
    for ref in sorted(references): verify(ref)
    direct_bindings = {}
    for node in nodes:
        ref = node.get('source_ref', node.get('source_url'))
        if type(ref) is not str:
            continue
        if ref in verified:
            definition = definitions[ref]
            for key in ('source_sha256', 'source_rights_ref'):
                if key in node:
                    _need(node[key] == definition[key], 'LOCAL_REFERENCE_MISMATCH')
            if 'captured_at' in node:
                _need(_time(node['captured_at']) == verified[ref], 'LOCAL_REFERENCE_CLOCK_MISMATCH')
            if 'published_at' in node:
                _need(node['published_at'] is None, 'LOCAL_PUBLICATION_TIME_INVENTED')
        elif not ref.lower().startswith('urn:') and 'source_rights_ref' in node:
            _direct(node, clock)
            if 'captured_at' in node and 'source_sha256' in node:
                identity = (ref, node['source_rights_ref'], _time(node['captured_at']))
                binding = (node['source_sha256'], node.get('published_at'))
                _need(identity not in direct_bindings or direct_bindings[identity] == binding,
                      'CONFLICTING_UPSTREAM_SOURCE')
                direct_bindings[identity] = binding
    if reports:
        _need(set(reports) == {_LOCAL.fullmatch(ref).group(2) for ref in verified
                              if _LOCAL.fullmatch(ref).group(1) == 'pdca-history-report'}, 'PDCA_REPORT_CLOSURE_INVALID')
    return {(ref, definitions[ref]['source_rights_ref']) for ref in verified}


def validate_source_derivations(native_payload):
    """Validate bounded builder manifests; return local pairs, never grants."""
    try:
        return _validate(native_payload)
    except (KeyError, TypeError, AttributeError, IndexError, RecursionError, OverflowError) as exc:
        raise ValueError('ALL_MODEL_SOURCE_DERIVATION_PAYLOAD_INVALID') from exc
