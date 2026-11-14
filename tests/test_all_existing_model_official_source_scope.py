"""Synthetic scope pairs; no provider requests or licence grants."""
import unittest
from datetime import datetime, timezone
from race_ai.all_existing_model_research import _source_refs


class OfficialSourceScopeTests(unittest.TestCase):
    def test_native_source_guard_keeps_nonboat_sport_and_capture_clock_bound(self):
        from race_ai.all_existing_model_source_derivations import _direct
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        source = dict(source_ref='https://autorace.jp/race_info/Program',
            source_rights_ref='OWNER_PERSONAL_OFFICIAL_AUTORACE_FACTUAL_ANALYSIS_20261107',
            source_sha256='a'*64, published_at=None, captured_at=now.isoformat())
        self.assertEqual(_direct(source, now, member=True), now)
        for field, value in (('source_ref', 'https://keirin.jp/pc/card'),
                             ('captured_at', '2030-01-02T00:00:00Z')):
            changed = dict(source, **{field: value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                _direct(changed, now, member=True)

    def test_retained_repository_artifact_is_a_storage_reference_not_provider_permission(self):
        rights = 'OWNER_PERSONAL_OFFICIAL_HTML_ANALYSIS_20261104'
        url = 'https://api.github.com/repos/haji84/RACE-AI/actions/artifacts/12345/zip'
        self.assertEqual(_source_refs([(url, rights)]), [(url, rights)])
        for changed in (url.replace('haji84', 'someone'), url+'?token=private',
                        url.replace('/12345/zip', '/12345'), url.replace('12345', '0'),
                        url.replace('https:', 'http:')):
            with self.subTest(url=changed), self.assertRaises(ValueError):
                _source_refs([(changed, rights)])

    def test_personal_scope_binds_each_official_sport_without_boat_relabelling(self):
        pairs = [
            ('https://keirin.jp/pc/dfw/portal/guest/index.html',
             'OWNER_PERSONAL_OFFICIAL_KEIRIN_FACTUAL_ANALYSIS_20261107'),
            ('https://autorace.jp/race_info/Program/kawaguchi/2026-11-07_1',
             'OWNER_PERSONAL_OFFICIAL_AUTORACE_FACTUAL_ANALYSIS_20261107'),
            ('https://www.jra.go.jp/keiba/',
             'OWNER_PERSONAL_OFFICIAL_HORSE_FACTUAL_ANALYSIS_20261107'),
        ]
        self.assertEqual(_source_refs(pairs), sorted(pairs))
        for url, rights in pairs:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    _source_refs([(url, 'OWNER_PERSONAL_OFFICIAL_B_ANALYSIS_20261104')])
                with self.assertRaises(ValueError):
                    _source_refs([('https://example.test/unreviewed', rights)])
        with self.assertRaises(ValueError):
            _source_refs([(pairs[0][0], pairs[1][1])])


if __name__ == '__main__':
    unittest.main()
