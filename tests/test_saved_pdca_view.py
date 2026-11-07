"""Saved original UI only; invented records and no collectors or root secret."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_boat_pdca_github_handoff import invented_research_state
from tests.test_local_forecast_server import serving,request


class SavedPdcaViewTests(unittest.TestCase):
    def test_local_atlas_accepts_the_exact_renderer_version_url(self):
        from race_ai.racer_portraits import CATALOGUE
        from race_ai.saved_pdca_view import SavedPdcaService
        entry=next(p for p in CATALOGUE['people'] if p['state']=='READY' and p['atlas'])
        path='/'+entry['asset'];version=CATALOGUE['assets'][entry['asset']]['sha256'][:12]
        with serving(SavedPdcaService(self.state),automatic=False) as (server,_):
            plain=request(server,'GET',path)
            versioned=request(server,'GET',path+'?v='+version)
            self.assertEqual(versioned[0],200)
            self.assertEqual(versioned[2],plain[2])
            self.assertIn('image/webp',versioned[1]['Content-Type'])
            self.assertEqual(request(server,'GET',path+'?v=invalid')[0],404)
            self.assertEqual(request(server,'GET','/assets/racer-portraits/sheet-9999.webp?v='+version)[0],404)

    def test_portraits_are_served_locally_and_embedded_in_offline_export(self):
        from race_ai.racer_portraits import FILES
        from race_ai.saved_pdca_view import SavedPdcaService,export_view
        service=SavedPdcaService(self.state)
        with serving(service,automatic=False) as (server,_):
            for name in FILES:
                status,headers,body=request(server,'GET','/'+name)
                self.assertEqual(status,200,name)
                self.assertTrue(body)
                if name.endswith('.webp'):self.assertIn('image/webp',headers['Content-Type'])
            self.assertEqual(request(server,'GET','/assets/racer-portraits/boat-9999.webp')[0],404)
        view=service.saved_projection()
        view['records'][0]['participants']=[dict(number=1,registration_no='4238',name='毒島誠'),
            dict(number=2,registration_no='2538',name='高橋二朗'),dict(number=3,registration_no='2878',name='富山弘幸')]
        view['records'][0]['scope']='research'
        out=self.root/'portrait-export.html';export_view(view,out)
        html=out.read_text()
        self.assertNotIn('src="./racer-portraits.js"',html)
        self.assertEqual(html.count('data:image/webp;base64,'),2)

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
