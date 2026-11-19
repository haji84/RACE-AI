"""Synthetic PDF review controls; no real source documents or forecasts here."""
from copy import deepcopy
from hashlib import sha256
from importlib.util import find_spec
from unittest.mock import patch
import json
import unittest

from tests.test_keirin_official_public_source import fixtures
from race_ai import keirin_official_public_source as official
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':'), allow_nan=False) + '\n').encode()


class ReviewedPdfResults(unittest.TestCase):
    def setUp(self):
        data = fixtures()
        get = lambda url: json.dumps(data[parse_qs(urlsplit(url).query)['type'][0]]).encode()
        self.schedule = official.fetch_day_schedule('2026-10-02', fetcher=get,
            clock=lambda: datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc))
        row = self.schedule['races'][0]
        self.rid = row['race_id']
        cars = [r['car'] for r in row['starters']]
        self.pdf = b'%PDF-1.7\nSYNTHETIC TEST DOCUMENT ONLY\n%%EOF'
        self.unit = '払戻金額は100円あたりの金額で発表され'.encode()
        self.pdf_sha, self.unit_sha = [sha256(x).hexdigest() for x in (self.pdf, self.unit)]
        self.sources = {self.pdf_sha: self.pdf, self.unit_sha: self.unit}
        self.doc = {
            'schema': 'RACE_AI_KEIRIN_KNOWN_PDF_VISUAL_REVIEW_V1',
            'race_day': '2026-10-02', 'reviewed_at': '2026-10-03T12:00:00+09:00',
            'review_method': 'TWO_ASSISTANT_VISUAL_READS_OF_SAME_OFFICIAL_PDF',
            'literal_review_sha256': 'a'*64,
            'sources': {'test': {
                'url': 'https://www.keirin-saitama.jp/seibuen/wp-content/uploads/pdf/page.pdf',
                'source_sha256': self.pdf_sha, 'observed_at': '2026-10-03T11:00:00+09:00',
                'source_available_no_later_than': '2026-10-03T11:00:00+09:00',
                'source_published_at': None, 'publication_time_basis': 'UNKNOWN',
                'document_issue_day': '2026-10-03', 'result_table_day': '2026-10-02',
                'result_table_page_1based': 4}},
            'unit_basis': [{'url': 'https://www.hofukeirin.jp/ticket/',
                'source_sha256': self.unit_sha, 'observed_at': '2026-10-03T11:10:00+09:00',
                'exact_excerpt': self.unit.decode(), 'verified_payout_basis_yen': 100}],
            'rows': [{'race_id': self.rid, 'race_no': int(self.rid[-2:]),
                'race_day': '2026-10-02', 'source_id': 'test', 'source_page_1based': 4,
                'winning_triple_displayed': cars[:3], 'payout_yen_displayed': 1230,
                'payout_basis_yen': 100, 'payout_basis_kind': 'EXTERNAL_OFFICIAL_VENUE_GUIDES',
                'finish_rows_displayed': [{'car': c, 'rank': i+1, 'status_label': None}
                                         for i,c in enumerate(cars)],
                'official_cutoff_at_from_saved_schedule': row['official_cutoff_at'],
                'scheduled_starters': cars}],
        }

    def implementation(self):
        self.assertIsNotNone(find_spec('race_ai.keirin_official_reviewed_pdf'),
                             'A reviewed PDF must not be re-labelled as official JSON')
        from race_ai import keirin_official_reviewed_pdf
        return keirin_official_reviewed_pdf

    def verify(self, doc=None, sources=None, schedule=None, *, pin=True):
        mod = self.implementation()
        raw = canonical(self.doc if doc is None else doc)
        approved = {sha256(raw).hexdigest()} if pin else set()
        with patch.object(mod, 'APPROVED_REVIEW_SHA256', approved):
            return mod.verify_reviewed_pdf_results(
                review_raw=raw, source_bytes_by_sha=self.sources if sources is None else sources,
                schedule=self.schedule if schedule is None else schedule)

    def test_exact_review_retains_unknown_publication_and_manual_evidence_scope(self):
        result = self.verify()['results_by_race'][self.rid]
        self.assertIsNone(result['source_published_at'])
        self.assertEqual(result['publication_time_basis'], 'UNKNOWN')
        self.assertEqual(result['source_available_no_later_than'], '2026-10-03T11:00:00+09:00')
        self.assertEqual(result['payouts_100yen'][0]['yen'], 1230)
        self.assertEqual(result['verification_method'], 'PINNED_VISUAL_PDF_REVIEW')
        self.assertFalse(result['automated_result_parser'])

    def test_unreviewed_values_cannot_be_promoted_by_self_reported_review_flags(self):
        with self.assertRaisesRegex(ValueError, 'REVIEW_NOT_APPROVED'):
            self.verify(pin=False)
        mod = self.implementation()
        raw = canonical(self.doc)
        changed = deepcopy(self.doc)
        changed['rows'][0]['payout_yen_displayed'] = 9990
        with patch.object(mod, 'APPROVED_REVIEW_SHA256', {sha256(raw).hexdigest()}):
            with self.assertRaisesRegex(ValueError, 'REVIEW_NOT_APPROVED'):
                mod.verify_reviewed_pdf_results(review_raw=canonical(changed),
                    source_bytes_by_sha=self.sources, schedule=self.schedule)

    def test_changed_pdf_or_missing_unit_evidence_cannot_score(self):
        for sources in ({self.pdf_sha: self.pdf+b'changed', self.unit_sha: self.unit},
                        {self.pdf_sha: self.pdf}):
            with self.subTest(sources=list(sources)):
                with self.assertRaisesRegex(ValueError, 'SOURCE_BYTES'):
                    self.verify(sources=sources)

    def test_fabricated_publication_and_wrong_day_are_rejected(self):
        for field,value in (('source_published_at','2026-10-03T11:00:00+09:00'),
                            ('result_table_day','2026-10-01'),
                            ('url','https://example.com/official.pdf')):
            doc=deepcopy(self.doc)
            doc['sources']['test'][field]=value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify(doc=doc)

    def test_source_observed_before_cutoff_is_not_a_post_race_result(self):
        doc=deepcopy(self.doc)
        doc['sources']['test']['observed_at']='2026-10-02T00:00:00+09:00'
        doc['sources']['test']['source_available_no_later_than']='2026-10-02T00:00:00+09:00'
        with self.assertRaisesRegex(ValueError, 'OBSERVATION_ORDER'):
            self.verify(doc=doc)

    def test_duplicate_race_missing_starter_or_wrong_winner_never_silently_scores(self):
        changes=[lambda d:d['rows'].append(deepcopy(d['rows'][0])),
                 lambda d:d['rows'][0]['finish_rows_displayed'].pop(),
                 lambda d:d['rows'][0].update(winning_triple_displayed=[9,8,7])]
        for change in changes:
            doc=deepcopy(self.doc); change(doc)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.verify(doc=doc)

    def test_schedule_raw_and_cutoff_are_rechecked(self):
        schedule=deepcopy(self.schedule)
        schedule['races'][0]['official_cutoff_at']='2026-10-02T01:00:00+09:00'
        with self.assertRaisesRegex(ValueError, 'SCHEDULE'):
            self.verify(schedule=schedule)
        doc=deepcopy(self.doc)
        doc['rows'][0]['official_cutoff_at_from_saved_schedule']='2026-10-02T01:00:00+09:00'
        with self.assertRaisesRegex(ValueError, 'CUTOFF'):
            self.verify(doc=doc)

    def test_withdrawn_or_unknown_finish_status_does_not_imply_no_refund(self):
        doc=deepcopy(self.doc)
        doc['rows'][0]['finish_rows_displayed'][-1].update(rank=None,status_label='欠')
        with self.assertRaisesRegex(ValueError, 'FINISH'):
            self.verify(doc=doc)


if __name__ == '__main__':
    unittest.main()
