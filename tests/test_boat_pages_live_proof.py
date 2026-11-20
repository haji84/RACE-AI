"""Approved presentation updates keep immutable forecast and delivery checks."""
from copy import deepcopy
from hashlib import sha256
import importlib
import unittest
from unittest.mock import patch


def entry(raw):return dict(bytes=len(raw),sha256=sha256(raw).hexdigest())


class PagesProofTests(unittest.TestCase):
    def setUp(self):
        self.core=b'/* preserved BOAT core */window.RaceOwnerFormal={};\n'
        self.template=('<!doctype html><head>\n'
            '<link rel="stylesheet" href="./style.css">\n'
            '<script defer src="./app.js"></script>\n'
            '</head><body><section id="boat-owner-formal-proof"></section></body>').encode()
        self.assets={'app.js':b'/* note capture */\n'+self.core+b'/* approved Note */',
            'saved-performance.js':b'/* unchanged scorer */',
            'saved-view-crypto.js':b'/* unchanged crypto */','style.css':b'/* current styles */'}
        cipher=b'invented encrypted bytes';identity=sha256(cipher).hexdigest()
        self.identity=dict(schema='RACE_AI_SAVED_PAGES_BUILD_V1',source_content_sha256='a'*64,
            cipher_path='views/'+identity+'.json',cipher_sha256=identity,
            forecast_sha256='b'*64,races=2,predictions=4)
        # This literal is independent of the production template renderer.
        self.html=('<!doctype html><head>\n'
            '<link rel="stylesheet" href="./style.css?v='+sha256(self.assets['style.css']).hexdigest()[:12]+'">\n'
            '<script defer src="./saved-view-crypto.js?v='+sha256(self.assets['saved-view-crypto.js']).hexdigest()[:12]+'"></script>\n  '
            '<script defer src="./app.js?v='+sha256(self.assets['app.js']).hexdigest()[:12]+'"></script>\n'
            '<meta name="referrer" content="no-referrer">\n'
            '<meta name="race-ai-saved-view-forecast-sha" content="'+'b'*64+'">\n'
            '<meta name="race-ai-encrypted-saved-view" content="./views/'+identity+'.json">\n'
            '</head><body><section id="boat-owner-formal-proof"></section></body>').encode()
        self.deployed={**self.assets,'index.html':self.html,'.nojekyll':b'',self.identity['cipher_path']:cipher}
        self.manifest={**self.identity,'files':{p:entry(b) for p,b in self.deployed.items()}}
        self.reference=deepcopy(self.manifest)
        self.reference['files']['app.js']=entry(self.core)
        self.calls=[]

    def api(self):return importlib.import_module('scripts.boat_pages_live_proof')

    def check(self,*,manifest=None,deployed=None,assets=None,fetch=None):
        def public(path,limit):
            self.calls.append(path)
            return (deployed or self.deployed)[path]
        return self.api().verify_bytes(reference=self.reference,manifest=manifest or self.manifest,
            deployed=deployed or self.deployed,source_assets=assets or self.assets,
            source_template=self.template,reference_app=self.core,fetch=fetch or public)

    def test_approved_app_append_passes_without_requiring_old_full_app_hash(self):
        report=self.check()
        self.assertEqual(report['status'],'BOAT_APPROVED_PRESENTATION_AND_HTTP_VERIFIED')
        self.assertEqual(len(self.calls),5)
        self.assertEqual(report['original_forecast_rewrites'],0)

    def test_changed_forecast_identity_is_not_an_approved_presentation_update(self):
        manifest=deepcopy(self.manifest);manifest['forecast_sha256']='c'*64
        with self.assertRaises(ValueError):self.check(manifest=manifest)
        self.assertEqual(self.calls,[])

    def test_self_consistent_changed_app_cannot_authorize_itself(self):
        deployed=dict(self.deployed);deployed['app.js']+=b'/* unreviewed */'
        manifest=deepcopy(self.manifest);manifest['files']['app.js']=entry(deployed['app.js'])
        with self.assertRaises(ValueError):self.check(deployed=deployed,manifest=manifest)

    def test_legacy_core_or_crypto_cannot_be_replaced_by_a_new_source_file(self):
        for name,body in [('app.js',b'/* core removed */'),('saved-view-crypto.js',b'/* changed crypto */')]:
            with self.subTest(name=name):
                assets=dict(self.assets);assets[name]=body
                deployed=dict(self.deployed);deployed[name]=body
                manifest=deepcopy(self.manifest);manifest['files'][name]=entry(body)
                with self.assertRaises(ValueError):self.check(assets=assets,deployed=deployed,manifest=manifest)

    def test_wrong_script_version_is_rejected_even_with_matching_manifest_bytes(self):
        deployed=dict(self.deployed);deployed['index.html']=self.html.replace(b'?v=',b'?old=')
        manifest=deepcopy(self.manifest);manifest['files']['index.html']=entry(deployed['index.html'])
        with self.assertRaises(ValueError):self.check(deployed=deployed,manifest=manifest)

    def test_stale_http_and_new_asset_paths_are_not_silently_accepted(self):
        with self.assertRaises(ValueError):self.check(fetch=lambda path,limit:b'stale old bytes')
        deployed=dict(self.deployed);deployed['new.js']=b'new'
        manifest=deepcopy(self.manifest);manifest['files']['new.js']=entry(b'new')
        with self.assertRaises(ValueError):self.check(deployed=deployed,manifest=manifest)

    def test_other_registered_scripts_also_require_exact_git_and_http_bytes(self):
        self.assets['product-data.js']=b'/* approved product data */'
        self.deployed['product-data.js']=self.assets['product-data.js']
        self.manifest['files']['product-data.js']=entry(self.assets['product-data.js'])
        self.reference['files']['product-data.js']=entry(b'/* older product data */')
        self.assertEqual(self.check()['assets'],6)
        self.assertIn('product-data.js',self.calls)
        with self.assertRaises(ValueError):
            self.check(fetch=lambda path,limit:b'stale' if path=='product-data.js' else self.deployed[path])

    def test_foreign_remote_or_http_path_is_rejected_before_network(self):
        api=self.api()
        with patch.object(api.GitRead,'run',return_value=b'https://github.com/other/repository.git\n'):
            with self.assertRaisesRegex(ValueError,'REPOSITORY'):api.GitRead('.')
        with patch.object(api,'build_opener') as opener:
            for path in ('../other.js','https://other.invalid/app.js','views/private.json'):
                with self.subTest(path=path),self.assertRaisesRegex(ValueError,'HTTP_PATH'):
                    api.http_bytes(path,10,'a'*40)
            opener.assert_not_called()


if __name__=='__main__':unittest.main()
