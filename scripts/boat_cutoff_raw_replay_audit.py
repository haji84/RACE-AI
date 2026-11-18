"""Inspect fixed retained BOAT grids without changing audit or forecast authority.

Private inputs and saved pages stay in memory. Only the twelve fixed public
fields leave this module. The inspectors need not be the producer's parsers.
"""
from datetime import date, datetime, timedelta, timezone
from hashlib import sha1, sha256
from pathlib import Path
from types import ModuleType
from urllib.parse import parse_qs, urlsplit
import re

SCHEMA = 'RACE_AI_A74_SAVED_GRID_INSPECTION_COUNTS_V1'
COUNTERS = ('comparison_count', 'program_grid_match_count', 'result_grid_match_count',
            'missing_raw_side_count', 'inspector_rejected_side_count',
            'grid_clock_disagreed_side_count')
_REASONS = frozenset((
    'INPUT_OR_SCOPE_INVALID', 'UNSUPPORTED_SOURCE_REF',
    'CAPTURE_AUTHENTICATION_UNAVAILABLE', 'RESOURCE_BOUND_EXCEEDED',
    'RAW_CAPTURE_MISSING', 'GRID_INSPECTOR_REJECTED',
    'SAVED_CLOCK_DIFFERS_FROM_INSPECTED_GRID', 'UNEXPECTED_GRID_INSPECTION_FAILURE'))
_REF_KEYS = frozenset(('source_sha256', 'source_ref', 'captured_at', 'url_form', 'proof_path'))
_PROOF_PATHS = frozenset(('SOURCE_EVIDENCE', 'OBSERVED_RACE_SOURCE',
                         'ORIGINAL_SOURCE_EVIDENCE', 'ORIGINAL_OBSERVED_RACE_SOURCE'))
_RACE = re.compile(r'20[0-9]{6}-(?:0[1-9]|1[0-9]|2[0-4])-(?:0[1-9]|1[0-2])\Z')
_SHA = re.compile(r'[a-f0-9]{64}\Z')
_RUN = 44218343091
_OWNER = 'a74f1e940e7fc0852e63938f8138bdb58bd93163'
_COMMIT = 'a1c2c4ae588b5b31b3e653d14fcf41bc3fc0dabe'
_MONTH = '2026-11'
_MAX_RECORDS = 28
_MAX_RACES = 2
_MAX_SIDES = 56
_CAPTURE_LOCATORS = 26
_MAX_CAPTURES = 26 * 240
_MAX_BYTES = 185328217
_RAW_LIMIT = 4 * 1024 * 1024
_META_LIMIT = 16384
_PROGRAM_BLOB = '1cfed75add647d77f76936f24be33db0776266c4'
_RESULT_BLOB = '06ec8fba76767b6a56cd9d26dd7e568fc4b0f0e2'
_VAULT_BLOB = '582dd4933f81d3ef0c76dc5f5479c9617f57a902'
_INTAKE_BLOB = '56f7310f8a30c72aa223641f35605948bd6e9208'
_OBSERVED_BLOB = 'd37ce58025e358fee6189b632938ed088cf1c5a2'
_JST = timezone(timedelta(hours=9))


class _Stop(Exception):
    def __init__(self, reason):
        self.reason = reason


def _need(ok, reason):
    if not ok:
        raise _Stop(reason)


def _known(status, reason=None, counts=None):
    values = dict.fromkeys(COUNTERS, 0) if counts is None else dict(counts)
    return dict(schema=SCHEMA, status=status, reason=reason, **values,
                source_requests=0, originals_changed=False, broader_goals_proven=False)


def _hold(reason):
    if type(reason) is not str or reason not in _REASONS:
        reason = 'UNEXPECTED_GRID_INSPECTION_FAILURE'
    return _known('HOLD', reason, dict.fromkeys(COUNTERS))


def _hex(value):
    return type(value) is str and _SHA.fullmatch(value) is not None


def _clock(value, parse_time, reason):
    _need(type(value) is str and 0 < len(value) <= 64, reason)
    try:
        clock = parse_time(value)
        _need(type(clock) is datetime and clock.utcoffset() is not None, reason)
        return clock.astimezone(timezone.utc)
    except _Stop:
        raise
    except Exception:
        raise _Stop(reason) from None


def _race_id(value, reason):
    _need(type(value) is str and _RACE.fullmatch(value) is not None, reason)
    try:
        date.fromisoformat(value[:4]+'-'+value[4:6]+'-'+value[6:8])
    except Exception:
        raise _Stop(reason) from None
    return value


def _exact_url(value, kind, race):
    if type(value) is not str or not 0 < len(value) <= 2048:
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == 'https' and parsed.netloc == 'www.boatrace.jp'
                and parsed.path == '/owpc/pc/race/'+kind and not parsed.fragment
                and parse_qs(parsed.query, keep_blank_values=True) ==
                dict(hd=[race[:8]], jcd=[race[9:11]], rno=[str(int(race[-2:]))]))
    except Exception:
        return False


def _bare_url(kind):
    return 'https://www.boatrace.jp/owpc/pc/race/'+kind


def _ref(value, race, parse_time):
    reason = 'UNSUPPORTED_SOURCE_REF'
    _need(type(value) is dict and set(value) == _REF_KEYS, reason)
    _need(_hex(value['source_sha256']), reason)
    form, path = value['url_form'], value['proof_path']
    _need(type(form) is str and form in ('EXACT', 'QUERY_FREE')
          and type(path) is str and path in _PROOF_PATHS, reason)
    at = _clock(value['captured_at'], parse_time, reason)
    if form == 'EXACT':
        _need(_exact_url(value['source_ref'], 'racelist', race), reason)
    else:
        _need(type(value['source_ref']) is str
              and value['source_ref'] == _bare_url('racelist')
              and path in ('OBSERVED_RACE_SOURCE', 'ORIGINAL_OBSERVED_RACE_SOURCE'), reason)
    return dict(sha=value['source_sha256'], ref=value['source_ref'],
                captured=at, captured_text=value['captured_at'], form=form)


def _program_ref_for_pair(payload, *, info, registry, parse_time):
    """Select only the declared raw PROGRAM proof in an already admitted pair."""
    try:
        if type(payload) is not dict or type(info) is not dict:
            return None
        key, native = payload.get('cell_key'), payload.get('native_payload')
        if type(key) is not str or not key.startswith('boat/') or type(native) is not dict:
            return None
        group = registry.group(key[5:])
        if group not in ('boat_ab', 'boat_clite', 'boat_tactical', 'boat_full',
                         'boat_observed', 'shared', 'shared_learned', 'boat_pdca'):
            return None
        race = _race_id(info.get('race_id'), 'UNSUPPORTED_SOURCE_REF')
        expected = _clock(info.get('race_cutoff_at'), parse_time, 'UNSUPPORTED_SOURCE_REF')
        current = registry.identity(key[5:], 'boat', native, race_id=race)
        if (registry._race_key(current['race_id'], 'boat') != registry._race_key(race, 'boat')
                or _clock(current['race_cutoff_at'], parse_time, 'UNSUPPORTED_SOURCE_REF') != expected
                or current['roster'] != info['roster']
                or payload.get('source_sha256') != registry.digest(native)
                or type(payload.get('pair')) is not dict
                or payload['pair'].get('input_sha256') != payload['source_sha256']):
            return None
        original = False
        if 'original_native_payload' in native or 'original_input_sha256' in native:
            if group != 'boat_observed':
                return None
            prior = native.get('original_native_payload')
            if (type(prior) is not dict or 'original_native_payload' in prior
                    or native.get('original_input_sha256') != registry.digest(prior)):
                return None
            previous = registry.identity(key[5:], 'boat', prior, race_id=race)
            if (registry._race_key(previous['race_id'], 'boat') != registry._race_key(race, 'boat')
                    or _clock(previous['race_cutoff_at'], parse_time, 'UNSUPPORTED_SOURCE_REF') != expected
                    or previous['roster'] != info['roster']
                    or _clock(previous['as_of'], parse_time, 'UNSUPPORTED_SOURCE_REF') >
                       _clock(current['as_of'], parse_time, 'UNSUPPORTED_SOURCE_REF')):
                return None
            native, current, original = prior, previous, True
        asof = _clock(current['as_of'], parse_time, 'UNSUPPORTED_SOURCE_REF')

        def direct(wanted=None):
            evidence = native.get('source_evidence')
            if evidence is None:
                return []
            if type(evidence) is not list:
                raise _Stop('UNSUPPORTED_SOURCE_REF')
            matches = {}
            for proof in evidence:
                if type(proof) is not dict:
                    raise _Stop('UNSUPPORTED_SOURCE_REF')
                url, digest = proof.get('source_ref'), proof.get('source_sha256')
                if not _exact_url(url, 'racelist', race):
                    continue
                if wanted is not None and digest != wanted:
                    continue
                if (not _hex(digest) or type(proof.get('source_rights_ref')) is not str
                        or not proof['source_rights_ref']):
                    raise _Stop('UNSUPPORTED_SOURCE_REF')
                at = _clock(proof.get('captured_at'), parse_time, 'UNSUPPORTED_SOURCE_REF')
                if at > asof:
                    raise _Stop('UNSUPPORTED_SOURCE_REF')
                result = dict(source_sha256=digest, source_ref=url,
                    captured_at=proof['captured_at'], url_form='EXACT',
                    proof_path='ORIGINAL_SOURCE_EVIDENCE' if original else 'SOURCE_EVIDENCE')
                matches[(digest, url, at)] = result
            return list(matches.values())

        if group == 'boat_observed':
            snapshot = native.get('snapshot')
            if type(snapshot) is not dict or type(snapshot.get('sources')) is not list:
                return None
            sid = snapshot.get('race_source_id')
            if type(sid) is not str:
                return None
            sources = [source for source in snapshot['sources']
                       if type(source) is dict and source.get('source_id') == sid]
            if len(sources) != 1:
                return None
            source = sources[0]
            at = _clock(source.get('captured_at'), parse_time, 'UNSUPPORTED_SOURCE_REF')
            if (not _hex(source.get('source_sha256'))
                    or type(source.get('source_url')) is not str
                    or source['source_url'] != _bare_url('racelist') or at > asof):
                return None
            proofs = direct(source['source_sha256'])
            if 'source_evidence' in native:
                if (len(proofs) != 1 or
                        _clock(proofs[0]['captured_at'], parse_time, 'UNSUPPORTED_SOURCE_REF') != at):
                    return None
            return dict(source_sha256=source['source_sha256'], source_ref=source['source_url'],
                captured_at=source['captured_at'], url_form='QUERY_FREE',
                proof_path='ORIGINAL_OBSERVED_RACE_SOURCE' if original else 'OBSERVED_RACE_SOURCE')
        if group in ('boat_ab', 'boat_tactical'):
            wanted = native['source']['program_source_sha256']
        elif group == 'boat_clite':
            wanted = native['base_source']['program_source_sha256']
        elif group == 'boat_pdca':
            wanted = native['facts']['program_sha256']
        else:
            wanted = None
        if wanted is not None and not _hex(wanted):
            return None
        proofs = direct(wanted)
        return proofs[0] if len(proofs) == 1 else None
    except Exception:
        return None


def _targets(first, latest, parse_time):
    reason = 'INPUT_OR_SCOPE_INVALID'
    _need(type(first) is dict and type(latest) is dict, reason)
    targets, races = [], set()
    for key, descriptor in first.items():
        _need(type(key) is tuple and len(key) == 4 and type(descriptor) is dict, reason)
        race_pair, info = descriptor.get('race'), descriptor.get('info')
        _need(type(race_pair) is tuple and len(race_pair) == 2
              and race_pair[0] == 'boat' and type(info) is dict, reason)
        race = _race_id(race_pair[1], reason)
        _need(key[0] == 'boat' and key[1] == race and key[2] == 'P1'
              and info.get('race_id') == race, reason)
        observation = latest.get(race)
        if observation is None:
            continue
        _need(type(observation) is dict, reason)
        if observation.get('closed_at') is None:
            continue
        before = _clock(info.get('race_cutoff_at'), parse_time, reason)
        after = _clock(observation['closed_at'], parse_time, reason)
        if before == after:
            continue
        races.add(race)
        _need(len(targets) < _MAX_RECORDS and len(races) <= _MAX_RACES,
              'RESOURCE_BOUND_EXCEEDED')
        reference = _ref(descriptor.get('_raw_program_ref'), race, parse_time)
        _need(observation.get('race_id') == race and _hex(observation.get('source_sha256'))
              and _exact_url(observation.get('source_url'), 'raceresult', race), reason)
        result_at = _clock(observation.get('captured_at'), parse_time, reason)
        result = dict(sha=observation['source_sha256'], ref=observation['source_url'],
                      captured=result_at, captured_text=observation['captured_at'], form='EXACT')
        targets.append(dict(race=race, before=before, after=after, program=reference, result=result))
    return targets


def _capture_pairs(captures, parsers, parse_time):
    reason = 'CAPTURE_AUTHENTICATION_UNAVAILABLE'
    _need(type(captures) is tuple, reason)
    _need(len(captures) <= _MAX_CAPTURES, 'RESOURCE_BOUND_EXCEEDED')
    total, found = 0, {}
    for pair in captures:
        _need(type(pair) in (tuple, list) and len(pair) == 2, reason)
        raw, metadata_raw = pair
        _need(type(raw) is bytes and type(metadata_raw) is bytes, reason)
        _need(len(raw) <= _RAW_LIMIT and len(metadata_raw) <= _META_LIMIT,
              'RESOURCE_BOUND_EXCEEDED')
        total += len(raw) + len(metadata_raw)
        _need(total <= _MAX_BYTES, 'RESOURCE_BOUND_EXCEEDED')
        _need(len(raw) > 0 and len(metadata_raw) > 0, reason)
        try:
            metadata = parsers['receipt_json'](metadata_raw, _META_LIMIT)
        except Exception:
            raise _Stop(reason) from None
        _need(type(metadata) is dict and type(metadata.get('http_status')) is int
              and metadata['http_status'] == 200 and _hex(metadata.get('source_sha256'))
              and metadata['source_sha256'] == sha256(raw).hexdigest(), reason)
        at = _clock(metadata.get('captured_at'), parse_time, reason)
        url = metadata.get('source_url')
        _need(type(url) is str and 0 < len(url) <= 2048, reason)
        try:
            parsed = urlsplit(url)
            query = parse_qs(parsed.query, keep_blank_values=True)
            _need(parsed.scheme == 'https' and parsed.netloc == 'www.boatrace.jp'
                  and not parsed.fragment and parsed.path in
                  ('/owpc/pc/race/racelist', '/owpc/pc/race/beforeinfo', '/owpc/pc/race/raceresult')
                  and set(query) == {'hd', 'jcd', 'rno'}
                  and all(len(value) == 1 for value in query.values()), reason)
            day, venue, number = query['hd'][0], query['jcd'][0], query['rno'][0]
            _need(re.fullmatch(r'20[0-9]{6}', day) is not None
                  and re.fullmatch(r'0[1-9]|1[0-9]|2[0-4]', venue) is not None
                  and re.fullmatch(r'[1-9]|1[0-2]', number) is not None, reason)
            race = _race_id(day+'-'+venue+'-'+number.zfill(2), reason)
        except _Stop:
            raise
        except Exception:
            raise _Stop(reason) from None
        kind = parsed.path.rsplit('/', 1)[-1]
        item = dict(raw=raw, sha=metadata['source_sha256'], url=url, captured=at,
                    captured_text=metadata['captured_at'], race=race, kind=kind)
        identity = (item['sha'], url, at, 200)
        if identity in found:
            _need(found[identity]['raw'] == raw, reason)
        else:
            found[identity] = item
    return tuple(found.values())


def _select_capture(items, source, kind, race):
    matches = []
    for item in items:
        if (item['sha'] != source['sha'] or item['captured'] != source['captured']
                or item['race'] != race or item['kind'] != kind):
            continue
        if source['form'] == 'EXACT' and item['url'] != source['ref']:
            continue
        if source['form'] == 'QUERY_FREE' and _bare_url(kind) != source['ref']:
            continue
        matches.append(item)
    if not matches:
        return None, ('MISSING', kind, race, source['sha'], source['form'],
                      source['ref'], source['captured'])
    first = matches[0]
    _need(all(item['raw'] == first['raw'] and item['url'] == first['url']
              and item['captured'] == first['captured'] for item in matches),
          'CAPTURE_AUTHENTICATION_UNAVAILABLE')
    return first, ('FOUND', kind, race, first['sha'], first['url'], first['captured'], 200)


def _inspect(item, kind, race, saved, parsers, parse_time):
    module = parsers['A74_PROGRAM'] if kind == 'racelist' else parsers['PR64_RESULT']
    error_type = module.BoatProgramError if kind == 'racelist' else module.SourceError
    day = date.fromisoformat(race[:4]+'-'+race[4:6]+'-'+race[6:8])
    options = dict(day=day, venue=race[9:11], race_no=int(race[-2:]),
                   source_url=item['url'], captured_at=item['captured_text'])
    try:
        if kind == 'racelist':
            inspected = module.parse_program(item['raw'], **options)
        else:
            inspected = module.parse_update(item['raw'], kind='raceresult', entries=None, **options)
    except Exception as error:
        if type(error) is error_type:
            return 'inspector_rejected_side_count'
        raise _Stop('UNEXPECTED_GRID_INSPECTION_FAILURE') from None
    reason = 'UNEXPECTED_GRID_INSPECTION_FAILURE'
    _need(type(inspected) is dict and inspected.get('race_id') == race
          and inspected.get('source_sha256') == item['sha'], reason)
    clock = _clock(inspected.get('closed_at'), parse_time, reason)
    if clock != saved:
        return 'grid_clock_disagreed_side_count'
    return 'program_grid_match_count' if kind == 'racelist' else 'result_grid_match_count'


def diagnose_saved_cutoff_raw_replay(first, latest, captures, *, parsers, parse_time):
    """Compare saved clocks with the two declared fixed, independent inspectors."""
    try:
        _need(type(parsers) is dict and set(parsers) ==
              {'A74_PROGRAM', 'PR64_RESULT', 'receipt_json'}
              and type(parsers['A74_PROGRAM']) is ModuleType
              and type(parsers['PR64_RESULT']) is ModuleType
              and callable(parsers['receipt_json']) and callable(parse_time),
              'INPUT_OR_SCOPE_INVALID')
        targets = _targets(first, latest, parse_time)
        if not targets:
            return _known('NO_MISMATCH_TARGETS')
        items = _capture_pairs(captures, parsers, parse_time)
        counts = dict.fromkeys(COUNTERS, 0)
        seen = set()
        for target in targets:
            program, program_binding = _select_capture(items, target['program'], 'racelist', target['race'])
            result, result_binding = _select_capture(items, target['result'], 'raceresult', target['race'])
            identity = (_PROGRAM_BLOB, _RESULT_BLOB, target['race'], target['before'], target['after'],
                        program_binding, result_binding)
            if identity in seen:
                continue
            seen.add(identity)
            _need(len(seen) <= _MAX_RECORDS, 'RESOURCE_BOUND_EXCEEDED')
            counts['comparison_count'] += 1
            for item, kind, saved in ((program, 'racelist', target['before']),
                                      (result, 'raceresult', target['after'])):
                outcome = 'missing_raw_side_count' if item is None else _inspect(
                    item, kind, target['race'], saved, parsers, parse_time)
                counts[outcome] += 1
        if counts['missing_raw_side_count']:
            return _known('HOLD', 'RAW_CAPTURE_MISSING', counts)
        if counts['inspector_rejected_side_count']:
            return _known('HOLD', 'GRID_INSPECTOR_REJECTED', counts)
        if counts['grid_clock_disagreed_side_count']:
            return _known('HOLD', 'SAVED_CLOCK_DIFFERS_FROM_INSPECTED_GRID', counts)
        return _known('SAVED_CLOCKS_MATCH_INSPECTED_GRIDS', counts=counts)
    except _Stop as error:
        return _hold(error.reason if type(error) is _Stop else None)
    except Exception:
        return _hold('UNEXPECTED_GRID_INSPECTION_FAILURE')


def _pinned(module, expected):
    _need(type(module) is ModuleType, 'INPUT_OR_SCOPE_INVALID')
    try:
        path = Path(module.__file__)
        _need(path.is_file() and not path.is_symlink(), 'INPUT_OR_SCOPE_INVALID')
        raw = path.read_bytes()
        actual = sha1(b'blob '+str(len(raw)).encode('ascii')+b'\0'+raw).hexdigest()
        _need(actual == expected, 'INPUT_OR_SCOPE_INVALID')
    except _Stop:
        raise
    except Exception:
        raise _Stop('INPUT_OR_SCOPE_INVALID') from None


def _retained_captures(targets, repo, vault, program_locator):
    """Use unchanged signed-header and AEAD readers on one fixed vault snapshot."""
    reason = 'CAPTURE_AUTHENTICATION_UNAVAILABLE'
    wanted = {target[role]['sha'] for target in targets for role in ('program', 'result')}
    _need(len(wanted) <= _MAX_SIDES, 'RESOURCE_BOUND_EXCEEDED')
    try:
        git = vault.VaultGitRepository(repo, ref=vault.VAULT_REF)
        locators = vault.list_originals(_MONTH, repo, source_commit=_COMMIT,
                                       run_id=_RUN, transport=git)
        _need(type(locators) is list, reason)
        selected = [locator for locator in locators
                    if type(locator) is dict and locator.get('kind') == 'SOURCE_CAPTURES']
        _need(len(selected) == _CAPTURE_LOCATORS, reason)
        mac_key = vault._keys(None)[1]
        candidates, seen, cipher_total = [], set(), 0
        for locator in selected:
            vault._validate_locator(locator)
            _need(locator['ref'] == vault.VAULT_REF and locator['source_commit'] == _COMMIT
                  and locator['artifact_id'] is None, reason)
            identity = (locator['batch_path'], locator['entry_sha256'])
            _need(identity not in seen, reason)
            seen.add(identity)
            reference = {name: locator[name] for name in
                         ('batch_path', 'batch_sha256', 'entry_sha256', 'artifact_id', 'kind')}
            entry = vault._batch_entry(git, _COMMIT, reference, mac_key)
            header, files = entry['header'], entry['header']['files']
            summary = header['summary']
            _need(summary['kind'] == 'SOURCE_CAPTURES'
                  and type(summary['run_id']) is int and summary['run_id'] == _RUN
                  and type(summary['head_sha']) is str and summary['head_sha'] == _OWNER
                  and summary['month'] == _MONTH
                  and vault._time(header['archived_at']).astimezone(_JST).strftime('%Y-%m') == _MONTH,
                  reason)
            count = summary['capture_count']
            _need(type(count) is int and 0 < count <= 240, reason)
            expected = {f'capture-{number:04d}.{suffix}' for number in range(count)
                        for suffix in ('raw', 'json')}
            _need(set(files) == expected and len(files) == 2 * count, reason)
            for number in range(count):
                _need(0 < files[f'capture-{number:04d}.raw']['size'] <= _RAW_LIMIT
                      and 0 < files[f'capture-{number:04d}.json']['size'] <= _META_LIMIT, reason)
            cipher_total += entry['cipher_size']
            _need(cipher_total <= _MAX_BYTES, 'RESOURCE_BOUND_EXCEEDED')
            if any(files[f'capture-{number:04d}.raw']['sha256'] in wanted for number in range(count)):
                candidates.append(locator)
        # Authenticate every header before opening any candidate. No early match
        # can turn an unreadable later descriptor into verified absence.
        captures, bodies, total = [], {}, 0
        for locator in candidates:
            restored = vault.restore_capture_bundle(locator, repo, transport=git)
            for raw, metadata_raw in restored['captures']:
                digest = sha256(raw).hexdigest()
                if digest not in wanted:
                    continue
                metadata = vault._json(metadata_raw, _META_LIMIT)
                at = vault._time(metadata['captured_at']).astimezone(timezone.utc)
                matched = False
                for target in targets:
                    for role in ('program', 'result'):
                        source = target[role]
                        if digest != source['sha'] or at != source['captured']:
                            continue
                        if source['form'] == 'QUERY_FREE':
                            try:
                                actual = program_locator(metadata['source_url'], 'racelist', target['race'])
                            except ValueError:
                                continue
                            _need(type(actual) is str and actual == source['ref'], reason)
                        elif metadata['source_url'] != source['ref']:
                            continue
                        matched = True
                        break
                    if matched:
                        break
                if not matched:
                    continue
                if digest in bodies:
                    _need(bodies[digest] == raw, reason)
                else:
                    bodies[digest] = raw
                total += len(raw) + len(metadata_raw)
                _need(len(captures) < _MAX_CAPTURES and total <= _MAX_BYTES,
                      'RESOURCE_BOUND_EXCEEDED')
                captures.append((bodies[digest], metadata_raw))
            del restored
        return tuple(captures)
    except _Stop:
        raise
    except Exception:
        raise _Stop(reason) from None


def audit_fixed_a74_cutoff_raw_replay(*, get, repo, now):
    """Additional fixed Actions readback; never replace the public pair audit."""
    try:
        _need(callable(get) and type(now) is datetime and now.utcoffset() is not None,
              'INPUT_OR_SCOPE_INVALID')
        from race_ai import boat_private_original_vault as vault
        from race_ai import boat_official_program as program
        from race_ai import official_race_updates as result
        from race_ai import all_existing_model_intake as intake
        from race_ai import observed_p1_connection as observed
        from scripts import boat_current_pair_eligibility_audit as pairs
        for module, expected in ((vault, _VAULT_BLOB), (program, _PROGRAM_BLOB),
                                  (result, _RESULT_BLOB), (intake, _INTAKE_BLOB),
                                  (observed, _OBSERVED_BLOB)):
            _pinned(module, expected)
        parsers = {'A74_PROGRAM': program, 'PR64_RESULT': result, 'receipt_json': vault._json}
        report = None

        def sink(first, latest):
            nonlocal report
            try:
                targets = _targets(first, latest, intake._time)
                if not targets:
                    report = _known('NO_MISMATCH_TARGETS')
                    return
                captures = _retained_captures(targets, repo, vault, observed.locator)
                report = diagnose_saved_cutoff_raw_replay(
                    first, latest, captures, parsers=parsers, parse_time=intake._time)
            except _Stop as error:
                report = _hold(error.reason if type(error) is _Stop else None)
            except Exception:
                report = _hold('UNEXPECTED_GRID_INSPECTION_FAILURE')

        try:
            pairs._audit(get, _RUN, now, _OWNER, _raw_cutoff_sink=sink)
        except Exception as error:
            if pairs._current_pair_exact_cutoff_error(error) and report is not None:
                return report
            return _hold('INPUT_OR_SCOPE_INVALID')
        return _known('NO_MISMATCH_TARGETS') if report is None else _hold('INPUT_OR_SCOPE_INVALID')
    except _Stop as error:
        return _hold(error.reason if type(error) is _Stop else None)
    except Exception:
        return _hold('INPUT_OR_SCOPE_INVALID')
