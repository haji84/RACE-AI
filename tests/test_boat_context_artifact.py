"""Import supplemental context only from authenticated existing artifact bytes."""
from hashlib import sha256
import tempfile
from pathlib import Path
import unittest
from race_ai import workflow_live_projection as projection
from tests.test_workflow_live_projection import packed
from tests.test_boat_context_store import context

class SupplementalArtifactTests(unittest.TestCase):
    def captured(self,change=False):
        raw=packed({'national.json':{'supplemental_boat_observations':[context()]}})
        meta=dict(id=123,name='boat-national-cutoff-99',expired=False,digest='sha256:'+sha256(raw).hexdigest(),workflow_run=dict(id=99,head_repository_id=1416489937))
        if change:meta['digest']='sha256:'+'0'*64
        return {123:(None,meta,raw)}

    def test_existing_artifact_context_is_imported_without_inference_or_forecast_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            result=projection.import_supplemental_contexts(self.captured(),Path(folder),day='2030-04-01')
            self.assertEqual(result,dict(accepted=1,rejected=0))
            from race_ai.boat_context_store import read_contexts
            saved=read_contexts(folder,day='2030-04-01')['contexts']
            self.assertEqual(saved['20300401-01-01']['beforeinfo']['source']['sha256'],'a'*64)

    def test_wrong_digest_is_not_a_supplemental_source(self):
        with tempfile.TemporaryDirectory() as folder:
            result=projection.import_supplemental_contexts(self.captured(True),Path(folder),day='2030-04-01')
            self.assertEqual(result,dict(accepted=0,rejected=1))
            self.assertFalse((Path(folder)/'boat-context').exists())
