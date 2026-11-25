"""Append a verified Mac result to the existing encrypted owner note."""

import base64
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess

from race_ai.keirin_note_view import SCHEMA, _private_root, canonical
from scripts import keirin_mac_shadow_result as shadow
from scripts.keirin_line_version_study import write_private


APPROVAL = 'KEIRIN_MAC_SHADOW_PUBLICATION_APPROVAL_V1'
APPROVAL_FIELDS = {'schema', 'scope', 'race_id', 'original_sha256', 'schedule_sha256',
                   'archive_cipher_sha256', 'archive_readback_at', 'pages_commit'}


def prepare_record(root, request, archive_cipher_sha256, *, clock):
    """Replay saved evidence. An absent result never triggers another poll."""
    if not shadow.snapshot._digest(archive_cipher_sha256):
        raise ValueError('SHADOW_ARCHIVE_DIGEST_INVALID')
    now = shadow.official._aware(clock())
    schedule, race, start, cutoff, starters, books, pin, original = shadow._inputs(request, now)
    if now < start:
        return None

    race_id = race['race_id']
    day = schedule['day_jst']
    state = Path(root) / 'keirin-mac-shadow-results' / race_id
    official_path = state / 'official-result.json'
    github_path = state / 'github-public/published-result.json'
    secondary = state / 'site-two-source'
    secondary_path = secondary / 'result.json'
    result_path = next((path for path in (official_path, github_path, secondary_path)
                        if path.exists() or path.is_symlink()), None)
    if result_path is None:
        return None
    if shadow._read(state / 'request-pins.json', 4096) != pin:
        raise ValueError('SHADOW_SITE_PRE_CUTOFF_PIN_MISMATCH')

    receipt = shadow._read(result_path, shadow.MAX_RECEIPT_BYTES)
    before = shadow.snapshot._read_regular(result_path, shadow.MAX_RECEIPT_BYTES)
    if receipt != shadow.snapshot._json(before, 'SHADOW_SITE_RECEIPT_INVALID'):
        raise ValueError('SHADOW_SITE_RECEIPT_CHANGED')
    if result_path == official_path:
        official = shadow.restore_private_snapshot_json(receipt)
        score = shadow._score(state, official, schedule, race, starters, books)
        if score['state'] != 'SHADOW_RESULT_SCORED':
            return None
        observed = shadow.official._aware(score['official_observed_at'])
    elif result_path == github_path:
        score = shadow._public_score(receipt, day, race, cutoff, starters, books)
        if score is None:
            return None
        comparison = shadow.unique_races(receipt['results'])[race_id]['comparison']
        observed = shadow.official._aware(comparison['observed_at'])
    else:
        score = shadow._secondary_cycle(secondary, request=request, original=original, pin=pin,
                                       absence=None, day=day, race=race, score_cutoff=cutoff,
                                       starters=starters, books=books, clock=lambda: now)
        if score is None or score['state'] != 'SHADOW_SECONDARY_PODIUM_SCORED':
            return None
        observed = shadow.official._aware(receipt['outcome']['comparison']['observed_at'])

    if (not start <= observed <= now or before !=
            shadow.snapshot._read_regular(result_path, shadow.MAX_RECEIPT_BYTES)):
        raise ValueError('SHADOW_SITE_RECEIPT_OR_CLOCK_CHANGED')

    results = score['scores']
    if any(type(arm[key]) not in (int, bool) or arm[key] not in (0, 1)
           for arm in results.values() for key in ('top4_3t', 'top2_2t')):
        raise ValueError('SHADOW_SITE_SCORE_INVALID')
    return dict(schema='RACE_AI_KEIRIN_SHADOW_VERIFICATION_V1', day_jst=day, race_id=race_id,
                verified_at=now.isoformat(), start_at=start.isoformat(),
                original=dict(sha256=pin['original_sha256'], archive_cipher_sha256=archive_cipher_sha256,
                              generated_at=original['generated_at'], cutoff_at=cutoff.isoformat()),
                result=dict(evidence_sha256=sha256(before).hexdigest(), observed_at=observed.isoformat(),
                            scope=score['scope']),
                scores={market: dict(points=points, saved_hit=bool(results['saved'][key]),
                                     challenger_hit=bool(results['challenger'][key]))
                        for market, points, key in (('trifecta', 4, 'top4_3t'), ('exacta', 2, 'top2_2t'))},
                tracking_learning='HELD', production_weights_promoted=False)


def _record_identity(record):
    return {key: value for key, value in record.items() if key != 'verified_at'}


def _prepared_snapshot(work, record, recipient, source_commit, *, clock):
    from race_ai.keirin_note_feed import checked_entry, seal_snapshot

    pending = work / 'prepared.json'
    if not pending.exists() and not pending.is_symlink():
        day = record['day_jst']
        raw = canonical(record) + b'\n'
        note = dict(schema=SCHEMA, scope='OWNER_MAC_SHADOW_VERIFICATION', source_site=None,
                    source_commit=source_commit, imported_at=record['verified_at'], dates=[day],
                    files={f'data/{day}/shadow_verification.json':
                           dict(text=raw.decode(), bytes=len(raw), sha256=sha256(raw).hexdigest())},
                    formal_model_admission=False, production_weight_switch=False, wagers_placed=False)
        sealed = seal_snapshot(note, recipient, kind='shadow-verification', clock=clock)
        write_private(pending, dict(record=record, entry=sealed['entry'],
                                   cipher=base64.b64encode(sealed['cipher']).decode('ascii')))

    saved = shadow._read(pending, 48 * 1024)
    if _record_identity(saved['record']) != _record_identity(record):
        raise ValueError('SHADOW_PUBLICATION_EVIDENCE_CHANGED')
    entry = checked_entry(saved['entry'])
    cipher = base64.b64decode(saved['cipher'], validate=True)
    if sha256(cipher).hexdigest() != entry['cipher_sha256'] or entry['kind'] != 'shadow-verification':
        raise ValueError('SHADOW_PUBLICATION_CIPHER_CHANGED')
    return dict(entry=entry, cipher=cipher), saved['record']


def _publish(root, record, *, clock, store, recipient, source_commit):
    from race_ai.keirin_note_feed import load_index, publish_snapshot
    from race_ai.keirin_shadow_verification import checked_archive_binding, checked_record

    race_id = record['race_id']
    checked_record(record, record['day_jst'])
    work = _private_root(Path(root) / 'keirin-mac-shadow-results' / race_id / 'site-publication')
    acknowledged = work / 'published.json'
    identity = sha256(canonical(_record_identity(record))).hexdigest()
    if acknowledged.exists() or acknowledged.is_symlink():
        previous = shadow._read(acknowledged, 4096)
        if previous['record_sha256'] != identity:
            raise ValueError('SHADOW_PUBLICATION_EVIDENCE_CHANGED')
        return previous['report']

    parent = store.head()
    prior = load_index(store, recipient, parent)
    if prior is None:
        raise ValueError('SHADOW_PUBLICATION_FEED_MISSING')
    archive = next((row for row in prior['entries']
                    if row['cipher_sha256'] == record['original']['archive_cipher_sha256']), None)
    checked_archive_binding(record, archive, clock().isoformat())
    sealed, prepared_record = _prepared_snapshot(work, record, recipient, source_commit, clock=clock)
    checked_archive_binding(prepared_record, archive, sealed['entry']['created_at'])
    if sealed['entry'] not in prior['entries']:
        verified = publish_snapshot(store, recipient, sealed, expected_parent=parent)
        parent = verified['source_commit']
    report = dict(state='SHADOW_ENCRYPTED_NOTE_READBACK_VERIFIED', race_id=race_id,
                  source_commit=parent, cipher_sha256=sealed['entry']['cipher_sha256'],
                  production_weights_promoted=False)
    write_private(acknowledged, dict(record_sha256=identity, report=report))
    return report


def run(root, request, *, clock):
    approval = Path(request).with_name('shadow-publication-approval.json')
    if not approval.exists() and not approval.is_symlink():
        return {'state': 'SHADOW_PUBLICATION_NOT_CONFIGURED'}
    try:
        permitted = shadow._read(approval, 4096)
        if (set(permitted) != APPROVAL_FIELDS or permitted['schema'] != APPROVAL
                or permitted['scope'] != 'OWNER_ENCRYPTED_NOTE_GROWTH'
                or not re.fullmatch('[a-f0-9]{40}', permitted['pages_commit'])):
            raise ValueError('SHADOW_PUBLICATION_APPROVAL_INVALID')
        record = prepare_record(root, request, permitted['archive_cipher_sha256'], clock=clock)
        if record is None:
            return {'state': 'WAITING_FOR_SAVED_SHADOW_RESULT'}
        pins = shadow._read(request, 4096)
        first = record['original']
        observed = shadow.official._aware(permitted['archive_readback_at'])
        if (permitted['race_id'] != record['race_id']
                or permitted['original_sha256'] != first['sha256']
                or permitted['schedule_sha256'] != pins['schedule_sha256']
                or not shadow.official._aware(first['generated_at']) <= observed <
                shadow.official._aware(first['cutoff_at'])):
            raise ValueError('SHADOW_PUBLICATION_APPROVAL_MISMATCH')

        from race_ai.keirin_note_feed import NoteFeedGit

        repo = Path(__file__).resolve().parents[1]
        source_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo,
                                                timeout=10, text=True).strip()
        recipient = json.loads((repo / 'config/keirin-note-recipient.json').read_bytes())
        feed_repo = shadow.snapshot._private(Path(root).parent / 'owner-note-git')
        store = NoteFeedGit(feed_repo)
        return _publish(root, record, clock=clock, store=store, recipient=recipient, source_commit=source_commit)
    except (ImportError, KeyError, OSError, TypeError, ValueError, RuntimeError, subprocess.SubprocessError):
        return {'state': 'HOLD_SHADOW_NOTE_PUBLICATION'}
