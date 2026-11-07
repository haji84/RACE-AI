"""Real source-backed name facts must reach the saved-model intake boundary."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import boat_saved_view_feed as cli
from race_ai.saved_view_feed import forecast_inventory
from race_ai.boat_saved_view_intake import append_views
from tests import test_boat_name_aliases as fixtures


class SavedNameAliasIntakeTests(unittest.TestCase):
    def setUp(self):
        self.source = fixtures.NameAliasTests('test_exact_sources_generate_scoped_pairs_without_prefix_heuristic')
        self.source.setUp(); self.addCleanup(self.source.doCleanups)
        self.root = Path(self.source.temp.name)
        self.metadata = self.root/'metadata.json'
        self.files = {'racers.sqlite':str(self.source.path), 'metadata.json':str(self.metadata)}

    def write_metadata(self, manifest):
        self.metadata.write_text(json.dumps({'name_alias_sources':manifest}) if manifest is not None else '{}')
        self.metadata.chmod(0o600)

    def test_real_alias_sources_unblock_full_name_intake_without_changing_saved_originals(self):
        self.write_metadata(self.source.manifest)
        base, extra = self.source.views(); before = deepcopy((base, extra))
        path = self.root/'native-view.json'; path.write_text(json.dumps(extra)); path.chmod(0o600)
        self.files['native-view.json'] = str(path)
        config = self.root/'audit/state/boat-model-runtime-input.json'
        config.parent.mkdir(parents=True); config.write_text('{}')
        source_aliases=cli._runtime_name_aliases
        with patch.object(cli,'ROOT',self.root), patch.dict(os.environ,{'RUNNER_TEMP':str(self.root),'RACE_AI_PROGRAM_SOURCE_ENABLED':'true'}), \
             patch('scripts.boat_all_model_cycle.prepare_runtime',return_value={'runtime_files':self.files}), \
             patch.object(cli,'_runtime_name_aliases',side_effect=lambda files,**kw:source_aliases(files,now=fixtures.CLOCK,**kw)), \
             patch('race_ai.boat_program_source.load_name_alias_source',create=True,side_effect=AssertionError('covered source must not be fetched')):
            out = cli.intake_saved_models(base)
        self.assertEqual((base, extra), before)
        self.assertEqual(out['records'][0]['participants'][0]['name'],self.source.full)
        self.assertEqual(out['records'][0]['participants'][0]['name_source']['kind'],'VERIFIED_RACER_REGISTRY')
        self.assertEqual(len(forecast_inventory(out)),2)
        self.assertTrue(all(forecast_inventory(out).get(k)==v for k,v in forecast_inventory(base).items()))
        self.assertTrue(any(s['participants']==base['records'][0]['participants'] for s in out['records'][0]['saved_participant_rosters']))
        self.assertEqual(append_views(out,[extra]),out)

    def test_current_day_can_use_the_authenticated_program_cache_without_new_source_requests(self):
        self.write_metadata(None)
        with patch.dict(os.environ,{'RACE_AI_PROGRAM_SOURCE_ENABLED':'true'}), \
             patch('race_ai.boat_program_source.load_name_alias_source',create=True,return_value=self.source.manifest['b_sources'][0]) as cache:
            facts = cli._runtime_name_aliases(self.files,now=fixtures.CLOCK)
        self.assertTrue(facts)
        cache.assert_called_once_with(fixtures.DAY,cli.ROOT,as_of=fixtures.CLOCK)

    def test_corrupt_declared_manifest_holds_before_any_cache_fallback(self):
        manifest=deepcopy(self.source.manifest);manifest['b_sources'][0]['source_sha256']='0'*64
        self.write_metadata(manifest)
        with patch.dict(os.environ,{'RACE_AI_PROGRAM_SOURCE_ENABLED':'true'}), \
             patch('race_ai.boat_program_source.load_name_alias_source',create=True,side_effect=AssertionError('no fallback after corruption')) as cache:
            with self.assertRaises(ValueError):cli._runtime_name_aliases(self.files,now=fixtures.CLOCK)
        cache.assert_not_called()

    def test_absent_disabled_cache_is_unchanged_but_corrupt_enabled_cache_holds(self):
        self.write_metadata(None)
        with patch.dict(os.environ,{'RACE_AI_PROGRAM_SOURCE_ENABLED':'false'}), \
             patch('race_ai.boat_program_source.load_name_alias_source',create=True,side_effect=AssertionError('disabled cache')) as cache:
            self.assertEqual(cli._runtime_name_aliases(self.files,now=fixtures.CLOCK),[])
        cache.assert_not_called()
        with patch.dict(os.environ,{'RACE_AI_PROGRAM_SOURCE_ENABLED':'true'}), \
             patch('race_ai.boat_program_source.load_name_alias_source',create=True,side_effect=ValueError('PROGRAM_SOURCE_CATALOG_AUTHENTICATION_FAILED')):
            with self.assertRaisesRegex(ValueError,'PROGRAM_SOURCE_CATALOG_AUTHENTICATION_FAILED'):
                cli._runtime_name_aliases(self.files,now=fixtures.CLOCK)


if __name__=='__main__':unittest.main()
