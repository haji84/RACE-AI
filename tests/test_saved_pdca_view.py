"""Saved original UI only; invented records and no collectors or root secret."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_boat_pdca_github_handoff import invented_research_state
from tests.test_local_forecast_server import serving,request


class SavedPdcaViewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.state,self.pair=invented_research_state(self.root)

    def test_existing_loopback_ui_reads_saved_originals_without_generation(self):
        from race_ai.saved_pdca_view import SavedPdcaService
        original=self.state.read_bytes();service=SavedPdcaService(self.state)
        with serving(service,automatic=False) as (server,_):
            status,_,html=request(server,'GET','/')
            self.assertEqual(status,200)
            self.assertIn(b'race-ai-private-saved-view',html)
            self.assertNotIn(b'name="race-ai-generation-api"',html)
            status,headers,body=request(server,'GET','/api/forecast/saved')
            self.assertEqual(status,200);self.assertEqual(headers['Cache-Control'],'no-store')
            view=json.loads(body);self.assertEqual(len(view['records']),1)
            self.assertEqual(view['records'][0]['prediction']['pair_sha256'],self.pair['pair_sha256'])
            self.assertEqual(request(server,'GET','/api/forecast/saved',headers={'Host':'attacker.invalid'})[0],403)
            self.assertFalse(service.status()['ready'])
            with self.assertRaises(PermissionError):service.generate('boat','P0')
        self.assertEqual(original,self.state.read_bytes())

    def test_offline_export_contains_only_safe_projection_and_exact_csp_hashes(self):
        from race_ai.saved_pdca_view import export_view
        from race_ai.boat_pdca_projection import project_pdca
        from race_ai.boat_pdca_state import PdcaState
        import base64,re
        state=PdcaState(self.state)
        try:view=project_pdca(state)
        finally:state.close()
        view['records'][0]['venue']='</script><script>alert(1)</script>'
        out=self.root/'private-view.html';export_view(view,out)
        html=out.read_text()
        self.assertFalse(out.stat().st_mode & 0o077)
        self.assertIn('id="race-ai-private-saved-data"',html)
        self.assertNotIn('<script>alert(1)</script>',html)
        self.assertNotIn('RACE_AI_STATE_KEY',html)
        self.assertNotIn('src="./',html);self.assertNotIn('href="./style.css"',html)
        for script in re.findall(r'<script>(.*?)</script>',html,re.S):
            pin=base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
            self.assertIn("'sha256-"+pin+"'",html)
        self.assertIn("connect-src 'none'",html)
