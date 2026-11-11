"""Synthetic source lineage, private replay and existing B-input connections."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import os
import unittest

from race_ai.keirin_winticket_prior_events import observed_prior_candidates, PriorSourceError
from race_ai.keirin_prior_private_stage import (
    private_research_packet, stage_owner_private_prior_research,
    read_private_research_packet,
)
from tests.test_keirin_winticket_prior_events import PriorEventContractTests, CAPTURE, TARGET, CUTOFF, URL


def partial_card(riders, html_sha):
    from race_ai.keirin_winticket_embedded_racecard import SCHEMA
    from race_ai.keirin_preflight import expected_keys
    fields = {f'rider/{n}/race_score': 80 for n in range(1, 8)}
    fields.update({f'rider/{n}/top_three_rate': .3 for n in range(1, 8)})
    registry = set(expected_keys(list(range(1, 8))))
    return {'schema': SCHEMA, 'race_id': TARGET, 'source_url': URL,
            'source_capture_at_utc': CAPTURE,
            'source_published_cutoff_at_utc': CUTOFF,
            'html_sha256': html_sha,
            'riders': [{'car_number': n, 'source_player_id': rid}
                       for n, rid in enumerate(riders, 1)],
            'direct_verified_fields': fields,
            'verified_registry_keys': sorted(fields),
            'unavailable_registry_keys': sorted(registry - set(fields)),
            'registry_checked_count': len(registry),
            'registry_verified_count': len(fields),
            'registry_unavailable_count': len(registry) - len(fields),
            'full_347_or_437_verified': False, 'forecasts_created': False}


class PriorPrivateStagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reference = PriorEventContractTests().refs()
        self.events = [PriorEventContractTests().result()]
        self.derived = observed_prior_candidates(self.reference, self.events, as_of=CAPTURE)
        self.cardsha = sha256(b'FICTIONAL-RACECARD').hexdigest()
        self.idxsha = sha256(b'FICTIONAL-PUBLISHED-INDEX').hexdigest()

    def packet(self):
        return private_research_packet(self.reference, self.events, self.derived,
            racecard_sha256=self.cardsha, day_index_sha256=self.idxsha, as_of=CAPTURE)

    def test_private_original_bound_to_each_prior_source_sha_and_replayable(self):
        packet = self.packet()
        with patch.dict(os.environ, {'GITHUB_WORKSPACE': ''}):
            created = stage_owner_private_prior_research(self.root, packet)
            repeated = stage_owner_private_prior_research(self.root, packet)
        self.assertTrue(created['new_private_packet'])
        self.assertFalse(repeated['new_private_packet'])
        self.assertEqual(created['private_packet_sha256'], repeated['private_packet_sha256'])
        self.assertFalse(created['approved_for_pr71_input'])
        self.assertFalse(created['production_aes_archived'])
        self.assertFalse(created['official_predictions_generated'])
        self.assertEqual(created['past_results_preserved'], 1)
        record = self.root / 'keirin_prior_research' / (created['private_packet_sha256'] + '.json')
        read = read_private_research_packet(record, expected_sha256=created['private_packet_sha256'])
        self.assertEqual(read['target_race_id'], TARGET)
        self.assertEqual(read['candidate_snapshot'], self.derived)
        self.assertEqual(read['prior_events'], self.events)
        self.assertNotIn('fiction-', str(created))
        self.assertNotIn('12.1', str(created))
        self.assertEqual(len(list(record.parent.glob('*.json'))), 1)

    def test_public_git_checkout_private_storage_refused(self):
        root = self.root / 'public'
        root.mkdir()
        inside = root / 'evidence'
        inside.mkdir()
        with patch.dict(os.environ, {'GITHUB_WORKSPACE': str(root)}):
            with self.assertRaisesRegex(PriorSourceError, 'PUBLIC_GIT_CHECKOUT_PRIVATE_RESULTS_FORBIDDEN'):
                stage_owner_private_prior_research(inside, self.packet())
        self.assertFalse((inside / 'keirin_prior_research').exists())

    def test_tamper_existing_private_packet_rejected_not_overwritten(self):
        packet = self.packet()
        with patch.dict(os.environ, {'GITHUB_WORKSPACE': ''}):
            created = stage_owner_private_prior_research(self.root, packet)
            file = self.root / 'keirin_prior_research' / (created['private_packet_sha256'] + '.json')
            original = file.read_bytes()
            file.write_bytes(original + b' ')
            with self.assertRaises(PriorSourceError):
                stage_owner_private_prior_research(self.root, packet)
            self.assertEqual(file.read_bytes(), original + b' ')

    def test_source_cannot_forge_later_candidate_or_self_approve(self):
        injected = deepcopy(self.derived)
        injected['riders']['fiction-1']['features']['finishing_power']['candidate_value'] = .99
        with self.assertRaisesRegex(PriorSourceError, 'PRIOR_CANDIDATE_REPLAY_OR_ADMISSION_CONFLICT'):
            private_research_packet(self.reference, self.events, injected,
                racecard_sha256=self.cardsha, day_index_sha256=self.idxsha, as_of=CAPTURE)
        approved = deepcopy(self.derived)
        approved['model_input_admitted'] = True
        with self.assertRaises(PriorSourceError):
            private_research_packet(self.reference, self.events, approved,
                racecard_sha256=self.cardsha, day_index_sha256=self.idxsha, as_of=CAPTURE)

    def test_future_or_unrelated_prior_page_not_staged(self):
        future = deepcopy(self.events)
        future[0]['result_captured_at'] = '2030-01-15T09:26:00+09:00'
        with self.assertRaises(PriorSourceError):
            private_research_packet(self.reference, future, self.derived,
                racecard_sha256=self.cardsha, day_index_sha256=self.idxsha, as_of=CAPTURE)
        unrelated = deepcopy(self.events)
        unrelated[0]['result_source_url'] = 'https://example.invalid/unrelated'
        with self.assertRaisesRegex(PriorSourceError, 'PAST_RESULT_NOT_BOUND_TO_CAPTURED_REFERENCE'):
            private_research_packet(self.reference, unrelated, self.derived,
                racecard_sha256=self.cardsha, day_index_sha256=self.idxsha, as_of=CAPTURE)

    def test_source_url_and_race_identity_cannot_be_collusively_swapped(self):
        refs = deepcopy(self.reference)
        refs['references'][0]['url'] = 'https://example.invalid/old/result'
        events = deepcopy(self.events)
        events[0]['result_source_url'] = refs['references'][0]['url']
        with self.assertRaises(PriorSourceError):
            private_research_packet(refs, events, self.derived,
                racecard_sha256=self.cardsha, day_index_sha256=self.idxsha, as_of=CAPTURE)

    def test_source_probe_stage_returns_only_replay_counts_and_sha(self):
        from datetime import datetime
        from scripts import keirin_prior_real_input_probe as probe
        target_url = URL
        past_url = self.reference['references'][0]['url']
        pages = {target_url: b'FICTIONAL CARD',
                 'https://www.winticket.jp/keirin/odds/20300115': b'FICTIONAL INDEX',
                 past_url: b'FICTIONAL PAST RESULT'}
        requests = []
        def fake_get(url):
            requests.append(url)
            return pages[url]
        card = partial_card(self.reference['rider_ids'], sha256(pages[target_url]).hexdigest())
        with patch.dict(os.environ, {'GITHUB_WORKSPACE': ''}), patch.object(
                probe, 'racecard_from_public_html', return_value=card
        ), patch.object(probe, 'documents_from_html', return_value=[{'records': []}]
        ), patch.object(probe, 'history_references', return_value=self.reference
        ), patch.object(probe, 'normalize_result_event', return_value=self.events[0]):
            safe = probe.probe(race_id=TARGET, racecard_url=target_url, max_pages=3,
                fetch=fake_get, clock=lambda: datetime.fromisoformat(CAPTURE),
                private_evidence_dir=self.root)
        self.assertEqual(len(requests), 3)
        self.assertTrue(safe['private_candidate_packet_saved'])
        self.assertTrue(safe['private_candidate_replay_verified'])
        self.assertFalse(safe['private_candidate_encrypted_git_archived'])
        self.assertFalse(safe['actual_four_model_forecast_saved'])
        self.assertEqual(safe['prior_result_pages_verified'], 1)
        self.assertNotIn('fiction-', str(safe))
        self.assertNotIn('FICTIONAL PAST RESULT', str(safe))
        out = self.root / 'keirin_prior_research' / (safe['private_candidate_packet_sha256'] + '.json')
        private = read_private_research_packet(out, expected_sha256=safe['private_candidate_packet_sha256'])
        self.assertEqual(private['racecard_original_sha256'], sha256(pages[target_url]).hexdigest())
        self.assertEqual(private['day_index_original_sha256'], sha256(pages[requests[1]]).hexdigest())
        self.assertFalse(private['provider_automated_training_rights_verified'])

    def test_symlink_rejected_and_untrusted_full_public_payload_never_returned(self):
        with patch.dict(os.environ, {'GITHUB_WORKSPACE': ''}):
            root = self.root / 'owner'
            root.mkdir()
            (root / 'keirin_prior_research').symlink_to(self.root, target_is_directory=True)
            with self.assertRaisesRegex(PriorSourceError, 'PRIOR_PRIVATE_DIR_SYMLINK_FORBIDDEN'):
                stage_owner_private_prior_research(root, self.packet())
            self.assertFalse(list(self.root.glob('*.json')))


class PriorInputConnectionTests(unittest.TestCase):
    def setUp(self):
        PriorPrivateStagingTests.setUp(self)
        self.reference['references'] = []
        seed = deepcopy(self.events[0])
        self.events = []
        for index in range(3):
            day = 10 + index
            event = deepcopy(seed)
            event.update(race_id=f'203001{day:02d}1201',
                started_at=f'2030-01-{day:02d}T10:05:00+09:00',
                result_published_at=f'2030-01-{day:02d}T10:10:00+09:00',
                result_source_url=f'https://www.winticket.jp/keirin/aomori/raceresult/2030011012/{index+1}/1',
                result_source_sha256=sha256(f'FICTIONAL RESULT {index}'.encode()).hexdigest())
            self.events.append(event)
            self.reference['references'].append({'race_id': event['race_id'],
                'url': event['result_source_url'], 'rider_ids': list(self.reference['rider_ids'])})
        self.derived = observed_prior_candidates(self.reference, self.events, as_of=CAPTURE)
        self.card = partial_card(self.reference['rider_ids'], self.cardsha)

    packet = PriorPrivateStagingTests.packet

    def test_existing_B_finishing_slots_close_without_filling_A_acceleration_alias(self):
        from race_ai.keirin_prior_input_connection import attach_prior_finishing_input
        from race_ai.keirin_real_source_gap_report import inspect_source_gaps
        out = attach_prior_finishing_input(self.card, self.packet())
        report = inspect_source_gaps(out)
        self.assertEqual(report['model_A_source_coverage']['source_unobserved_required_slots'], 79)
        self.assertEqual(report['model_B_source_coverage']['source_unobserved_required_slots'], 72)
        self.assertEqual(len(out['prior_finishing_input_evidence']), 7)
        for no in range(1, 8):
            self.assertNotIn(f'rider/{no}/last_lap_acceleration', out['direct_verified_fields'])
            evidence = out['prior_finishing_input_evidence'][f'rider/{no}/late_lap_and_agari_time']
            self.assertEqual(evidence['sample_n'], 3)
            self.assertFalse(evidence['approved_for_pr71_input'])
        self.assertNotIn('prior_finishing_input_evidence', self.card)

    def test_ten_comparable_observed_history_events_connect_venue_and_form_B_only(self):
        """The pinned bank-fit formula needs five same and five away outcomes."""
        from race_ai.keirin_prior_input_connection import (
            attach_prior_finishing_input, stage_connected_prior_input)
        from race_ai.keirin_real_source_gap_report import inspect_source_gaps
        self.events = []
        self.reference['references'] = []
        seed = deepcopy(PriorEventContractTests().result())
        for index in range(10):
            day = index + 1
            same = index < 5
            venue = '12' if same else '25'
            slug = 'aomori' if same else 'another'
            rid = f'203001{day:02d}{venue}01'
            url = (f'https://www.winticket.jp/keirin/{slug}/raceresult/'
                   f'203001{day:02d}{venue}/1/1')
            event = deepcopy(seed)
            event.update(race_id=rid, venue=venue,
                started_at=f'2030-01-{day:02d}T10:05:00+09:00',
                result_published_at=f'2030-01-{day:02d}T10:10:00+09:00',
                result_source_url=url,
                result_source_sha256=sha256(f'FICTIONAL VERIFIED OLD {index}'.encode()).hexdigest())
            self.events.append(event)
            self.reference['references'].append({
                'race_id':rid,'url':url,'rider_ids':list(self.reference['rider_ids'])})
        self.derived = observed_prior_candidates(self.reference,self.events,as_of=CAPTURE)
        out = attach_prior_finishing_input(self.card, self.packet())
        report = inspect_source_gaps(out)
        self.assertEqual(len(out['prior_finishing_input_evidence']),7)
        self.assertEqual(len(out['prior_venue_compatibility_input_evidence']),7)
        self.assertEqual(len(out['prior_recent_form_input_evidence']),7)
        self.assertEqual(report['model_B_source_coverage']['source_unobserved_required_slots'],58)
        self.assertEqual(report['model_A_source_coverage']['source_unobserved_required_slots'],79)
        for n in range(1,8):
            key = f'rider/{n}/venue_and_distance_compatibility'
            info = out['prior_venue_compatibility_input_evidence'][key]
            self.assertEqual((info['same_venue_sample_n'],info['other_venue_sample_n']),(5,5))
            self.assertEqual(info['sample_n'],5)
            self.assertEqual(info['value'],.5)
            self.assertFalse(info['approved_for_pr71_input'])
            self.assertIsNone(info['source_published_at'])
            self.assertNotIn(f'rider/{n}/bank_positioning_and_traffic',out['direct_verified_fields'])
            self.assertNotIn(f'rider/{n}/last_lap_acceleration',out['direct_verified_fields'])
            self.assertNotIn(f'rider/{n}/teammate_pair_history',out['direct_verified_fields'])
            form_key = f'rider/{n}/recent_strength_or_form_change'
            form = out['prior_recent_form_input_evidence'][form_key]
            self.assertEqual(form['value'], 0.5)
            self.assertEqual(form['sample_n'], 6)
            self.assertEqual((form['recent_sample_n'],form['baseline_sample_n']),(3,3))
            self.assertFalse(form['approved_for_pr71_input'])
            self.assertIsNone(form['source_published_at'])
        packet = self.packet()
        with patch.dict(os.environ, {'GITHUB_WORKSPACE':''}):
            stage_owner_private_prior_research(self.root,packet)
            stage = stage_connected_prior_input(self.root,self.card,packet)
        self.assertEqual(stage['derived_venue_compatibility_slots'],7)
        self.assertEqual(stage['derived_form_trend_slots'],7)
        self.assertFalse(stage['live_model_invoked'])
        self.assertFalse(stage['production_aes_archived'])
        self.assertFalse((self.root/'pre').exists())
        self.assertNotIn('fiction-',str(stage))

    def test_form_rank_trend_uses_real_observed_result_position_order(self):
        """Latest vs previous three matched outcomes only, no target future."""
        from race_ai.keirin_prior_form_trend import compute_prior_form_trend
        seed = deepcopy(PriorEventContractTests().result())
        events = []
        for index in range(6):
            day = 4 + index
            event = deepcopy(seed)
            event.update(
                race_id=f'203001{day:02d}1201',
                started_at=f'2030-01-{day:02d}T10:05:00+09:00',
                result_published_at=f'2030-01-{day:02d}T10:10:00+09:00',
                result_source_sha256=sha256(f'FICTIONAL FORM {index}'.encode()).hexdigest())
            if index < 3:
                event['starters'][0]['finish_rank'] = 7
                event['starters'][6]['finish_rank'] = 1
            events.append(event)
        derived = compute_prior_form_trend(self.reference,events,as_of=CAPTURE)
        self.assertEqual(derived['candidate_count'], 7)
        self.assertAlmostEqual(derived['riders']['fiction-1']['candidate_value'],1)
        self.assertAlmostEqual(derived['riders']['fiction-7']['candidate_value'],0)
        self.assertEqual(derived['riders']['fiction-2']['candidate_value'],.5)
        self.assertFalse(derived['model_training_or_prediction_executed'])
        self.assertEqual(derived['provider_requests'],0)
        for entry in derived['riders'].values():
            self.assertFalse(entry['approved_for_pr71_input'])
        # A clock after the target result must never turn into a prior input.
        with self.assertRaises(PriorSourceError):
            compute_prior_form_trend(self.reference,events,as_of='2030-01-15T10:00:00+09:00')
        # One later event cannot be used even if a caller supplies it.
        events[-1]['race_id'] = TARGET
        with self.assertRaises(PriorSourceError):
            compute_prior_form_trend(self.reference,events,as_of=CAPTURE)

    def test_four_history_events_cannot_fake_six_sample_form(self):
        from race_ai.keirin_prior_form_trend import compute_prior_form_trend
        # Existing three-event synthetic evidence cannot pass the 3+3 rule.
        result = compute_prior_form_trend(self.reference,self.events,as_of=CAPTURE)
        self.assertEqual(result['candidate_count'],0)
        out = self.packet()
        self.assertFalse(out['permission_to_run_PR71'])
        self.assertFalse(out['real_forecast_frozen'])

    def test_existing_direct_venue_is_never_overwritten_and_no_shortcut_at_four_samples(self):
        from race_ai.keirin_prior_input_connection import attach_prior_finishing_input
        from race_ai.keirin_preflight import expected_keys
        self.assertEqual(attach_prior_finishing_input(
            self.card, self.packet())['prior_venue_compatibility_input_evidence'], {})
        card = deepcopy(self.card)
        key = 'rider/1/venue_and_distance_compatibility'
        card['direct_verified_fields'][key] = .91
        registry = set(expected_keys(list(range(1,8))))
        keys = set(card['direct_verified_fields'])
        card.update(verified_registry_keys=sorted(keys),
                    unavailable_registry_keys=sorted(registry-keys),
                    registry_verified_count=len(keys),
                    registry_unavailable_count=len(registry)-len(keys))
        out = attach_prior_finishing_input(card,self.packet())
        self.assertEqual(out['direct_verified_fields'][key],.91)
        self.assertNotIn(key,out['prior_venue_compatibility_input_evidence'])

    def test_missing_history_stays_missing_and_original_mismatch_is_rejected(self):
        from race_ai.keirin_prior_input_connection import attach_prior_finishing_input
        from race_ai.keirin_real_source_gap_report import inspect_source_gaps
        self.events = self.events[:1]
        self.derived = observed_prior_candidates(self.reference, self.events, as_of=CAPTURE)
        self.assertEqual(inspect_source_gaps(attach_prior_finishing_input(self.card, self.packet()))[
            'model_B_source_coverage']['source_unobserved_required_slots'], 79)
        wrong = deepcopy(self.card)
        wrong['html_sha256'] = '0' * 64
        with self.assertRaises(PriorSourceError):
            attach_prior_finishing_input(wrong, self.packet())
        wrong = deepcopy(self.card)
        wrong['riders'][0]['source_player_id'] = 'foreign-rider'
        with self.assertRaises(PriorSourceError):
            attach_prior_finishing_input(wrong, self.packet())

    def test_connected_input_is_private_create_once_and_never_a_forecast(self):
        from race_ai.keirin_prior_input_connection import stage_connected_prior_input
        packet = self.packet()
        with patch.dict(os.environ, {'GITHUB_WORKSPACE': ''}):
            stage_owner_private_prior_research(self.root, packet)
            first = stage_connected_prior_input(self.root, self.card, packet)
            second = stage_connected_prior_input(self.root, self.card, packet)
        self.assertTrue(first['new_partial_input'])
        self.assertFalse(second['new_partial_input'])
        self.assertEqual(first['derived_finishing_slots'], 7)
        self.assertFalse(first['live_model_invoked'])
        self.assertFalse((self.root / 'pre').exists())
        path = self.root / 'winticket_racecard_partial' / (first['connected_input_sha256'] + '.json')
        self.assertEqual(sha256(path.read_bytes()).hexdigest(), first['connected_input_sha256'])
        self.assertNotIn('fiction-', str(first))

    def test_existing_B_models_receive_derived_finish_separately_from_acceleration(self):
        from race_ai.keirin_prior_input_connection import attach_prior_finishing_input
        from tests.test_keirin_allowed_delivery import SeparateEvidenceProfileTests, CHECKED
        from race_ai.keirin_allowed_delivery import assemble_permitted_pre_race, DISTINCT_B_ID
        from race_ai.four_sport_model_suite import run_suite, verify_suite, ALL_MODELS
        connected = attach_prior_finishing_input(self.card, self.packet())
        delivery = SeparateEvidenceProfileTests().distinct_packet()
        for row in delivery['observations']:
            if row['key'] in connected['prior_finishing_input_evidence']:
                row['value'] = connected['direct_verified_fields'][row['key']]
                row['sample_n'] = 3
        assembled = assemble_permitted_pre_race(delivery, grant_check=lambda *_: True,
            checked_at=CHECKED, feature_source_profile=DISTINCT_B_ID)
        evidence = assembled['private_snapshot']['facts']['pr71_evidenced_snapshot']
        self.assertEqual(evidence['participants'][0]['features']['sprint_acceleration']['value'], .91)
        self.assertEqual(evidence['participants'][0]['features']['finishing_power']['value'], 1)
        suite = run_suite(evidence, allow_source=lambda *_: True)
        self.assertTrue(verify_suite(suite))
        self.assertEqual(set(suite['models']), set(ALL_MODELS))
        self.assertTrue(all(m['candidate_count'] == 210 for m in suite['models'].values()))


if __name__ == '__main__':
    unittest.main()
