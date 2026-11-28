import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from race_ai import keirin_dossier_secondary as secondary
from race_ai import keirin_public_forecasts as public
from race_ai.keirin_note_feed import b64
from race_ai.keirin_note_view import attach_archive, canonical, import_site
from scripts import keirin_capture_public_two_sources as capture
from scripts.keirin_note_feed_cycle import source_archive
from scripts import keirin_publish_secondary_context as publisher
from tests.test_keirin_dossier_secondary import (
    CAPTURED, DAY, OFFICIAL_CUTOFF, PUBLISHED, RACE_ID, SOURCE_CUTOFF, performance_card, receipt, roster, saved_card,
)
from tests.test_keirin_result_unread_racecard import KDREAMS_URL, NETKEIRIN_URL


BEFORE = DAY + 'T14:59:00+09:00'
PUBLICATION = datetime.fromisoformat(PUBLISHED)


def bind_entry(note):
    return dict(cipher_sha256='a'*64,source_content_sha256=sha256(canonical(note)).hexdigest(),
                ephemeral_public_key=b64(bytes(65)),salt=b64(bytes(32)),created_at=CAPTURED,
                days=[DAY],kind='research',captured_race_ids=[],priority_window_race_ids=[])


def collected_note(folder, *, captured=BEFORE, archived_member=True, denied=False):
    root = Path(folder)
    raw = saved_card()
    observed = dict(receipt(raw),captured_at=captured)
    dated = root/'data'/DAY
    dated.mkdir(parents=True)
    document = dict(schema=publisher.INPUT_COLLECTION_SCHEMA,day_jst=DAY,
        source_manifest=dict(schema=capture.SCHEMA,day_jst=DAY,source_use_scope='OWNER_PERSONAL_RESEARCH_ONLY',
            races=[dict(race_id=RACE_ID,kdreams_url=KDREAMS_URL,netkeirin_url=NETKEIRIN_URL,cutoff_hint=SOURCE_CUTOFF)]),
        source_receipts=[observed],daily_coverage={},
        safe_report=dict(schema=publisher.INPUT_COLLECTION_SCHEMA,day_jst=DAY,provider_denied=denied,
            captured_race_ids=[],priority_window_race_ids=[]))
    (dated/'manifest.json').write_bytes(canonical(document))
    (dated/'reference_AB.json').write_bytes(b'[]')
    (root/'raw').mkdir()
    item = root/'raw'/f"{observed['bytes_sha256']}.html"
    if archived_member:
        item.write_bytes(raw)
    note = import_site(root,source_commit='b'*40,clock=lambda:datetime.fromisoformat(CAPTURED))
    note.update(scope='OWNER_MATCHED_SOURCE_RESEARCH_REFRESH',source_site=None,
                source_profile='owner-imported-kdreams-netkeirin-20261120',actual_four_model_forecast_saved=False)
    note = attach_archive(note,'source-inputs.tar.gz',source_archive(root))
    if not archived_member:
        item.write_bytes(raw)
    return root, note, bind_entry(note)


class PublishSecondaryContextTest(unittest.TestCase):
    def store(self, *, published=True, cutoff=OFFICIAL_CUTOFF):
        store = Mock()
        store.head.return_value = 'a' * 40
        store.commit.return_value = 'b' * 40
        path = f'rider-context-secondary/{DAY}.json'
        store.run.return_value = (path + '\n').encode()
        files = {}
        if published:
            files[f'starters/{DAY}.json'] = dict(schema=secondary.context.STARTERS_SCHEMA,
                day=DAY, published_at=CAPTURED, races=[roster()])
            files[f'forecasts/{DAY}.json'] = dict(schema=public.SCHEMA, day=DAY, published_at=CAPTURED, races=[
                dict(race_id=RACE_ID, cutoff_at=cutoff, status='pending', saved_at=None, a=[], b=[])])

        def read(commit, requested):
            if commit == 'b' * 40:
                return store.commit.call_args.args[0][requested]
            return json.dumps(files[requested]).encode() if requested in files else None

        store.read_previous.side_effect = read
        return store, path

    def test_publishes_only_bound_derived_race_data(self):
        store, path = self.store()
        raw = saved_card()
        with patch.object(publisher, '_national_identities') as directory:
            report = publisher.publish_cards(None, DAY, [(RACE_ID, raw, receipt(raw), None)],
                published_at=datetime.fromisoformat(PUBLISHED), published_only=True, store=store)
        self.assertEqual(report['state'], 'PUBLIC_RIDER_CONTEXT_SECONDARY_UPDATED')
        self.assertEqual(report['coverage']['verified_riders'], 5)
        self.assertEqual(report['provider_requests'], 0)
        directory.assert_not_called()
        files = store.commit.call_args.args[0]
        self.assertEqual(list(files), [path])
        decoded = secondary.checked_day(json.loads(files[path]))
        self.assertEqual(public.when(decoded['races'][0]['cutoff_at']), public.when(OFFICIAL_CUTOFF))
        self.assertNotIn('私的記述'.encode(), files[path])

    def test_performance_tab_supplements_the_bound_card_regardless_of_input_order(self):
        store, path = self.store()
        raw, tab = saved_card(), performance_card()
        performance = dict(receipt(tab), url=KDREAMS_URL + '?pageType=yoso')
        report = publisher.publish_cards(None, DAY, [
            (RACE_ID, tab, performance, None), (RACE_ID, raw, receipt(raw), None)],
            published_at=PUBLICATION, published_only=True, store=store)
        self.assertEqual(report['coverage']['verified_races'], 1)
        row = secondary.checked_day(json.loads(store.commit.call_args.args[0][path]))['races'][0]
        self.assertEqual(row['source_sha256'], receipt(raw)['bytes_sha256'])
        self.assertEqual(row['performance']['source_sha256'], performance['bytes_sha256'])

    def test_early_capture_requires_unique_verified_directory_identities(self):
        store, path = self.store(published=False)
        raw = saved_card()
        cards = [(RACE_ID, raw, dict(receipt(raw),captured_at=BEFORE), SOURCE_CUTOFF)]
        clock = {'published_at':datetime.fromisoformat(PUBLISHED),'published_only':False,'store':store}
        roster_ids = {publisher._person(row['name']): row['registration'] for row in roster()['riders']}
        with patch.object(publisher, '_national_identities', return_value={}):
            held = publisher.publish_cards(None, DAY, cards, **clock)
        self.assertEqual(held['state'], 'PUBLIC_RIDER_CONTEXT_SECONDARY_NO_QUALIFYING_ROWS')
        store.push.assert_not_called()
        with patch.object(publisher, '_national_identities', return_value=roster_ids):
            report = publisher.publish_cards(None, DAY, cards, **clock)
        self.assertEqual(report['coverage']['verified_riders'], 5)
        row = json.loads(store.commit.call_args.args[0][path])['races'][0]
        self.assertEqual(row['source_cutoff_at'], row['cutoff_at'])

    def test_projects_an_archived_kdreams_capture_with_no_normalized_ab(self):
        with TemporaryDirectory() as folder, patch.object(publisher,'publish_cards') as publish:
            root,note,entry = collected_note(folder)
            self.assertEqual(entry['captured_race_ids'],[])
            publisher.publish_saved_reference(None,root,note,entry,published_at=PUBLICATION)
            self.assertEqual(publish.call_args.args[:2],(None,DAY))
            self.assertEqual(publish.call_args.args[2],[(RACE_ID,saved_card(),
                dict(receipt(saved_card()),captured_at=BEFORE),SOURCE_CUTOFF)])
            self.assertEqual(publish.call_args.kwargs,dict(published_at=PUBLICATION,published_only=False))

    def test_neither_same_cutoff_capture_nor_provider_denial_is_reused(self):
        with TemporaryDirectory() as folder, patch.object(publisher,'publish_cards') as publish:
            root,note,entry = collected_note(folder,captured=SOURCE_CUTOFF)
            publisher.publish_saved_reference(None,root,note,entry,published_at=PUBLICATION)
            self.assertEqual(publish.call_args.args[2],[])
        with TemporaryDirectory() as folder, patch.object(publisher,'publish_cards') as publish:
            root,note,entry = collected_note(folder,denied=True)
            with self.assertRaisesRegex(ValueError,'MANIFEST_RECEIPT'):
                publisher.publish_saved_reference(None,root,note,entry,published_at=PUBLICATION)
            publish.assert_not_called()

    def test_saved_card_must_precede_earlier_registered_cutoff(self):
        store,_ = self.store(cutoff=BEFORE)
        raw = saved_card()
        report = publisher.publish_cards(None,DAY,[(RACE_ID,raw,dict(receipt(raw),captured_at=BEFORE),SOURCE_CUTOFF)],
            published_at=PUBLICATION,published_only=False,store=store)
        self.assertEqual(report['state'],'PUBLIC_RIDER_CONTEXT_SECONDARY_NO_QUALIFYING_ROWS')
        self.assertEqual(report['holds'],{'KEIRIN_PUBLIC_SECONDARY_DOSSIER_REGISTRY_PRE_CUTOFF':1})
        store.push.assert_not_called()

    def test_authenticated_note_file_and_raw_archive_member_are_both_required(self):
        with TemporaryDirectory() as folder, patch.object(publisher,'publish_cards') as publish:
            root,note,entry = collected_note(folder,archived_member=False)
            with self.assertRaisesRegex(ValueError,'ARCHIVE_SOURCE_MISSING'):
                publisher.publish_saved_reference(None,root,note,entry,published_at=PUBLICATION)
            publish.assert_not_called()
        with TemporaryDirectory() as folder, patch.object(publisher,'publish_cards') as publish:
            root,note,entry = collected_note(folder)
            note['files'][f'data/{DAY}/manifest.json']['text'] += ' '
            with self.assertRaisesRegex(ValueError,'REFERENCE_NOTE_BINDING'):
                publisher.publish_saved_reference(None,root,note,entry,published_at=PUBLICATION)
            with self.assertRaisesRegex(ValueError,'MANIFEST_SHA'):
                publisher.publish_saved_reference(None,root,note,bind_entry(note),published_at=PUBLICATION)
            publish.assert_not_called()
