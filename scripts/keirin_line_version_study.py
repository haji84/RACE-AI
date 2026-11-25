"""Compare two source-verified racecard observations before their shared cutoff."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

from scripts import keirin_generate_result_unread_analysis as ingest
from scripts.keirin_capture_public_two_sources import _allow_url


def lineup(groups, cars):
    if groups is None:
        return None
    if not groups or any(not group for group in groups):
        raise ValueError('An available lineup must contain nonempty lines.')
    starters = [car for group in groups for car in group]
    if len(set(starters)) != len(starters) or set(starters) != cars:
        raise ValueError('The lineup must contain each starter once.')
    return tuple(sorted(tuple(group) for group in groups))


def roster(card):
    rows = card['riders']
    if any(type(r.get('number')) is not int or not 1 <= r['number'] <= 9
           or not isinstance(r.get('name'), str) for r in rows):
        raise ValueError('Invalid starter name or car number.')
    field = {row['number']: ingest.person_key(row['name']) for row in rows}
    if (len(field) != len(rows) or not 5 <= len(field) <= 9 or not all(field.values())
            or len(set(field.values())) != len(field)):
        raise ValueError('The same full field is required in each version.')
    return field


def compare(earlier, later):
    day = earlier['date']
    if day != later['date'] or earlier['race_id'] != later['race_id']:
        raise ValueError('Versions must describe the same race.')
    close = ingest.published_cutoff(day, earlier['deadline_time'])
    captures = [ingest.instant(row['fetched_at']) for row in (earlier, later)]
    if close is None or close != ingest.published_cutoff(day, later['deadline_time']) or not captures[0] < captures[1] < close:
        raise ValueError('Both observations must be ordered before the same cutoff.')
    field = roster(earlier)
    if field != roster(later):
        raise ValueError('The same full field is required in each version.')
    old, new = (lineup(row['lines'], set(field)) for row in (earlier, later))
    if old == new:
        return 'unpublished' if old is None else 'unchanged'
    if old is None:
        return 'newly_listed'
    if new is None:
        return 'no_longer_listed'
    prior = {frozenset(group) for group in old}
    replacement = {frozenset(group) for group in new}
    if prior == replacement:
        return 'within_line_order'
    if all(any(line <= previous for previous in prior) for line in replacement):
        return 'split'
    if all(any(line <= current for current in replacement) for line in prior):
        return 'merge'
    return 'regrouped'


# The collector's restored races.json can also contain comments, previous
# results, odds and authored output. Pass only model inputs to a rerun.
RIDER_FIELDS = ('number', 'name', 'prefecture', 'term', 'class', 'style', 'score',
                'win_rate', 'top2_rate', 'top3_rate', 'S', 'H', 'B',
                'nige', 'makuri', 'sashi', 'mark', 'source_tip')


def restored_packet(directory, day):
    """Read a private, decrypted owner snapshot with its original recovery receipt."""
    meta = json.loads((directory / 'provenance.json').read_bytes())
    expected = meta['file_hashes']['data/' + day + '/races.json']
    owner_bytes = (directory / 'owner-races.json').read_bytes()
    if sha256(owner_bytes).hexdigest() != expected:
        raise ValueError('Restored races.json digest mismatch.')
    packet = json.loads(owner_bytes)
    if (packet['date'] != day or not re.fullmatch(r'[0-9a-f]{40}', meta['ref'])
            or not re.fullmatch(r'[0-9a-f]{64}', meta['cipher_sha256'])):
        raise ValueError('Invalid restored packet receipt.')
    indexed = {r['race_id']: r for r in packet['races']}
    if len(indexed) != len(packet['races']):
        raise ValueError('Duplicate race in one packet.')
    covered = set(meta.get('captured_race_ids', indexed))
    return [(card, meta) for key, card in indexed.items() if key in covered]


class IneligibleRevision(ValueError):
    """A latest observation which cannot safely be used for re-ranking."""


def revision_fields(base, card, receipt):
    rid = base['race_id']
    day = card['date']
    close = ingest.published_cutoff(day, card['deadline_time'])
    captured = ingest.instant(card['fetched_at'])
    sealed = ingest.instant(receipt['captured_at'])
    if (rid[:8] != day.replace('-', '') or close != ingest.instant(base['cutoff_at'])
            or card.get('no_today_results_used') is not True
            or not captured <= sealed < close):
        raise ValueError('Source date, cutoff or observation mismatch.')
    if any(r.get('is_absent') for r in card['riders']):
        raise IneligibleRevision('withdrawal_reported')
    field = roster(card)
    if roster(base) != field:
        raise IneligibleRevision('starter_or_identity_changed')
    if not card['lines'] or not card['listed_lines']:
        raise IneligibleRevision('latest_line_unavailable')
    groups = lineup(card['lines'], set(field))
    if groups != lineup(card['listed_lines'], set(field)):
        raise IneligibleRevision('latest_line_sources_disagree')
    _allow_url(card['source_url'], 'kd', rid)
    target = urlsplit(card['source_url'])
    if target.query or target.fragment:
        raise ValueError('Ordinary pre-race card URL required.')
    if not re.fullmatch(r'[0-9a-f]{64}', card['source_sha256']):
        raise ValueError('Racecard source digest missing.')
    riders = []
    for r in card['riders']:
        if not 1 <= r['number'] <= 9:
            raise ValueError('Inactive starter.')
        kd = r['field_sources']['statistics']
        net = r['field_sources']['H']
        if (kd['url'] != card['source_url'] or kd['bytes_sha256'] != card['source_sha256']
                or ingest.instant(kd['captured_at']) != captured):
            raise ValueError('Statistics source mismatch.')
        _allow_url(net['url'], 'net', rid)
        if (not re.fullmatch(r'[0-9a-f]{64}', net['bytes_sha256'])
                or net['url'] != 'https://keirin.netkeiba.com/race/entry/?race_id=' + rid
                or ingest.instant(net['captured_at']) > sealed
                or type(r['H']) is not int or r['H'] < 0):
            raise ValueError('H source mismatch.')
        riders.append({key: r[key] for key in RIDER_FIELDS})
    lines = [list(line) for line in groups]
    return dict(race_id=rid, riders=sorted(riders, key=lambda row: row['number']), lines=lines,
                published_cutoff_at=base['cutoff_at'], captured_at=card['fetched_at'],
                source_sha256=card['source_sha256'], source_url=card['source_url'],
                sealed_at=receipt['captured_at'], packet_commit=receipt['ref'],
                packet_sha256=receipt['cipher_sha256'])


def select_revisions(published, sources, as_of):
    """Select the newest available revision of each open published race, as of an aware datetime."""
    if as_of.utcoffset() is None:
        raise ValueError('An as-of time with a timezone is required.')
    day = published['date']
    if published['schema'] not in ('KEIRIN_PUBLISHED_LINE_RANK_V2', 'KEIRIN_PUBLISHED_LINE_RANK_V3'):
        raise ValueError('Ranked daily forecast with original freeze times required.')
    original = {r['race_id']: r for r in published['races']}
    if len(original) != len(published['races']):
        raise ValueError('Duplicate public race.')
    by_race = defaultdict(list)
    for card, receipt in sources:
        rid = card['race_id']
        if rid not in original or card['date'] != day:
            continue
        sealed = ingest.instant(receipt['captured_at'])
        captured = ingest.instant(card['fetched_at'])
        if captured <= as_of and sealed <= as_of:
            by_race[rid].append((captured, card, receipt))
    revisions = {}
    states = Counter()
    for rid, base in sorted(original.items()):
        cutoff = ingest.instant(base['cutoff_at'])
        original_at = ingest.instant(base['forecast_generated_at'])
        # A newer observation can arrive while the original model is running
        # or in a packet sealed after the original forecast was frozen.
        original_source = ingest.instant(base.get('source_as_of', base['forecast_generated_at']))
        if rid[:8] != day.replace('-', '') or not original_source <= original_at < cutoff:
            raise ValueError('Invalid original race date, source time or freeze time.')
        if not original_at <= as_of < cutoff:
            states['outside_open_window'] += 1
            continue
        later = [v for v in by_race[rid] if v[0] > original_source]
        if not later:
            states['no_new_observation'] += 1
            continue
        newest = max(v[0] for v in later)
        views = [(card, receipt) for t, card, receipt in later if t == newest]
        try:
            versions = [revision_fields(base, card, receipt) for card, receipt in views]
        except IneligibleRevision as error:
            states[str(error)] += 1
            continue
        except (ValueError, TypeError, KeyError):
            states['unverified_latest_observation'] += 1
            continue
        # Duplicated observations can arrive in separate encrypted packets.
        # Conflicting fields at the same observed time cannot establish a revision.
        signatures = {json.dumps([v['riders'], v['lines']], sort_keys=True) for v in versions}
        if len(signatures) != 1:
            states['conflicting_latest_observation'] += 1
            continue
        view = min(versions, key=lambda v: (ingest.instant(v['sealed_at']), v['packet_sha256']))
        base_groups = lineup(base['lines'], set(roster(base)))
        if base_groups == lineup(view['lines'], set(roster(base))):
            states['unchanged'] += 1
            continue
        reason = 'newly_listed' if base_groups is None else 'changed'
        states[reason] += 1
        revisions[rid] = dict(view, reason=reason)
    return dict(schema='KEIRIN_PRIVATE_LINE_REVISIONS_V1', date=day, as_of=as_of.isoformat(),
                states=dict(states), races=revisions)


def write_private(path, payload):
    """A revision file becomes visible only once the complete bytes have been flushed."""
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.line-revision-', delete=False) as tmp:
        staging = Path(tmp.name)
        try:
            packed = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
            tmp.write(packed + b'\n')
            tmp.flush()
            os.fsync(tmp.fileno())
            os.link(staging, path)
        finally:
            staging.unlink(missing_ok=True)


def verified_public_weights(published, source, fallback_weights):
    """Check the local frozen model bytes before deserializing them."""
    if published['schema'] != 'KEIRIN_PUBLISHED_LINE_RANK_V3' or published['model_id'] != 'video_line_ordered':
        raise ValueError('Unsupported frozen public model.')
    weights = (source / 'coefficients.owner.pkl').read_bytes()
    if (sha256(weights).hexdigest() != published['weights_sha256']
            or sha256(fallback_weights.read_bytes()).hexdigest() != published['fallback_weights_sha256']):
        raise ValueError('Public model weights do not match the local frozen files.')
    receipt = json.loads((source / 'forward-commitment.json').read_bytes())
    for name, field in [('snapshot_inputs.owner.json', 'inputs_sha256'),
                        ('snapshot_predictions.owner.json', 'prediction_sha256')]:
        if sha256((source / name).read_bytes()).hexdigest() != receipt[field]:
            raise ValueError('Frozen source or forecast snapshot does not match its receipt.')
    return weights


def registered_program_riders(riders, bind):
    """Return one distinct registration per car or hold this field."""
    try:
        registrations = [bind(rider) for rider in riders]
    except (ValueError, TypeError, KeyError):
        return None
    if not all(registrations) or len(set(registrations)) != len(riders):
        return None
    return registrations


def freeze_private_rankings(path, rows, *, context, packet_hashes, clock=None):
    """Publish private forecast bytes once, and attest when they were durably read back.

    Rows closing during the write are discarded and the remaining set is staged
    again. A reader must check the companion receipt to accept the output.
    """
    clock = clock or (lambda: datetime.now(timezone.utc))
    receipt_path = path.with_name(path.name + '.receipt.json')
    if path.exists() or receipt_path.exists():
        raise FileExistsError('A private forecast or receipt already exists.')
    to_check = list(rows)
    while True:
        started = clock()
        eligible = [r for r in to_check if ingest.instant(r['cutoff_at']) > started]
        payload = dict(context, schema='KEIRIN_FORWARD_PREDICTIONS_V1', races=eligible,
                       expired_during_inference=len(rows) - len(eligible),
                       source_packets={r['race_id']: packet_hashes[r['race_id']] for r in eligible})
        with tempfile.TemporaryDirectory(dir=path.parent, prefix='.keirin-private-') as tmp:
            stage = Path(tmp) / 'predictions.json'
            write_private(stage, payload)
            expected = stage.read_bytes()
            if json.loads(expected) != payload:
                raise ValueError('Staged predictions could not be verified.')
            os.link(stage, path)
            try:
                with path.open('rb') as stream:
                    verified = stream.read()
                if verified != expected:
                    raise ValueError('Frozen predictions could not be verified.')
                folder = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(folder)
                finally:
                    os.close(folder)
                frozen = clock()
                if frozen < started:
                    raise ValueError('Clock moved backwards during freeze.')
                to_check = [r for r in eligible if ingest.instant(r['cutoff_at']) > frozen]
                if len(to_check) != len(eligible):
                    path.unlink()
                    continue
                receipt = dict(schema='KEIRIN_FORWARD_RECEIPT_V1', frozen_at=frozen.isoformat(),
                               prediction_sha256=sha256(verified).hexdigest(),
                               comparators={'published':'site', 'trial':'revised_pre_cutoff_line'},
                               registered=len(eligible), expired=len(rows) - len(eligible))
                write_private(receipt_path, receipt)
            except BaseException:
                path.unlink(missing_ok=True)
                raise
            return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description='Select verified pre-cutoff lineup updates for private re-ranking.')
    parser.add_argument('--published', required=True, type=Path, help='Original daily ranked public JSON or gzip.')
    parser.add_argument('--restored', required=True, nargs='+', type=Path,
                        help='Verified owner directories containing owner-races.json and provenance.json.')
    parser.add_argument('--output', required=True, type=Path, help='New private revision filename.')
    parser.add_argument('--as-of', help='Historical as-of time including timezone. Defaults to now.')
    args = parser.parse_args(argv)
    try:
        now = datetime.now(timezone.utc)
        as_of = ingest.instant(args.as_of) if args.as_of else now
        if as_of > now:
            raise ValueError('Future as-of time.')
        raw = args.published.read_bytes()
        pub = json.loads(gzip.decompress(raw) if raw.startswith(b'\x1f\x8b') else raw)
        sources = []
        for folder in args.restored:
            sources.extend(restored_packet(folder, pub['date']))
        if not args.as_of:
            as_of = datetime.now(timezone.utc)
        result = select_revisions(pub, sources, as_of)
        result['published_sha256'] = sha256(raw).hexdigest()
        write_private(args.output, result)
    except (ValueError, TypeError, KeyError, OSError) as error:
        parser.exit(1, f'Cannot prepare private lineup revisions: {error}\n')
    print(json.dumps(dict(date=result['date'], states=result['states']), sort_keys=True))
    return 0


if __name__ == '__main__':
    main()
