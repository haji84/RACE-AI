"""Encrypted runtime seller bytes use the real authenticated B bridge."""
import base64
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from race_ai.boat_seller_inputs import build_seller_native_inputs
from scripts import boat_all_model_cycle as cli
from tests.test_boat_seller_official_source import fixture,DAY,AT


class SellerRuntimeSourceTests(unittest.TestCase):
    def test_exact_b_is_loaded_without_fabricating_waku_or_mutating_originals(self):
        raw,document,receipt=fixture()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'metadata.json';path.write_text(json.dumps({'seller_official_source':{
                'raw_b_base64':base64.b64encode(raw).decode(),'day':DAY}}));path.chmod(0o600)
            marker={'runtime_files':{'metadata.json':str(path)}}
            sources=cli._seller_sources(marker,document,receipt,datetime.fromisoformat(AT))
            result=build_seller_native_inputs(sources['cards'],sources.get('waku10'),day=DAY,as_of=AT,
                expected_race_ids=[r['race_id'] for r in document['schedule']])
            self.assertEqual(result['readiness']['race_cards']['state'],'READY')
            self.assertEqual(result['readiness']['waku10']['state'],'INPUT_MISSING')
            path.write_text('{}')
            self.assertIsNone(cli._seller_sources(marker,document,receipt,datetime.fromisoformat(AT)))

    def test_corrupt_optional_bytes_are_rejected_by_seller_without_blocking_others(self):
        raw,document,receipt=fixture()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'metadata.json';path.write_text(json.dumps({'seller_official_source':{
                'raw_b_base64':base64.b64encode(raw+b'tamper').decode(),'day':DAY}}));path.chmod(0o600)
            sources=cli._seller_sources({'runtime_files':{'metadata.json':str(path)}},document,receipt,datetime.fromisoformat(AT))
            result=build_seller_native_inputs(sources['cards'],sources.get('waku10'),day=DAY,as_of=AT,
                expected_race_ids=[r['race_id'] for r in document['schedule']])
            self.assertEqual(result['readiness']['seller']['state'],'INPUT_REJECTED')

    def test_authenticated_day_cache_precedes_stale_runtime_and_corruption_does_not_fallback(self):
        from race_ai.boat_seller_inputs import official_b_cards_source
        raw,document,receipt=fixture();clock=datetime.fromisoformat(AT)
        typed=official_b_cards_source(raw,document,receipt,day=DAY,as_of=clock)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'metadata.json';path.write_text('{"seller_official_source":{"raw_b_base64":"invalid"}}');path.chmod(0o600)
            marker={'runtime_files':{'metadata.json':str(path)}}
            with patch.dict('os.environ',{'RACE_AI_PROGRAM_SOURCE_ENABLED':'true'}),\
                 patch('race_ai.boat_program_source.load_program_source',return_value=typed) as get:
                self.assertEqual(cli._seller_sources(marker,document,receipt,clock)['cards'],typed)
                get.assert_called_once()
            with patch.dict('os.environ',{'RACE_AI_PROGRAM_SOURCE_ENABLED':'true'}),\
                 patch('race_ai.boat_program_source.load_program_source',side_effect=ValueError('PROGRAM_SOURCE_HASH_INVALID')):
                with self.assertRaisesRegex(ValueError,'PROGRAM_SOURCE_HASH_INVALID'):
                    cli._seller_sources(marker,document,receipt,clock)


if __name__=='__main__':unittest.main()
