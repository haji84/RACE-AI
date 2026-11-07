"""Invented originals only: public Pages bytes contain no plaintext or keys."""
import base64
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from race_ai.boat_pdca_state import PdcaState,sha
from race_ai.boat_history_store import wire
from tests.test_boat_pdca_github_handoff import invented_research_state


class SavedPagesTests(unittest.TestCase):
    def test_daily_catalogue_survives_both_ui_refresh_and_new_forecast_publication(self):
        from race_ai.racer_daily import API_FILE,PUBLIC_PATH,DailyStore
        from tests.test_racer_daily import ROSTER,NOW
        from tests.test_boat_venue_history import archive
        built=self.build();public=self.root/'public'
        self.assertTrue((public/API_FILE).is_file(),'daily card API must be included in ordinary and encrypted views')
        store=DailyStore(clock=lambda:NOW);self.addCleanup(store.close);store.record('2026-11-04',archive(),captured_at='2026-11-05T00:00:00Z')
        daily=(wire(store.catalogue(ROSTER,as_of=NOW.isoformat()))+'\n').encode()
        class LocalPages(self.m.PagesRepository):
            def _check_remote(inner):inner.fetch_url=inner.push_url=inner._run(['remote','get-url','origin']).decode().strip()
        repo=self.root/'daily-repo';remote=self.root/'daily-remote.git';repo.mkdir()
        for args in (['git','init','--bare',str(remote)],['git','init',str(repo)],['git','-C',str(repo),'remote','add','origin',str(remote)]):subprocess.run(args,check=True,capture_output=True)
        git=LocalPages(repo);manifest=json.loads((public/'site-build.json').read_text())
        files={name:(public/name).read_bytes() for name in manifest['files']};files['site-build.json']=(public/'site-build.json').read_bytes()
        parent=git.commit(files,None);git.push(parent,None);before=git._run(['ls-tree','-r',parent,'--','views'])
        from race_ai.racer_daily_handoff import publish_daily_catalogue
        catalogue=json.loads(daily)
        with self.assertRaises(ValueError):publish_daily_catalogue(repo,{**catalogue,'private_prediction':{}},transport=git)
        unexpected=deepcopy(catalogue);unexpected['source']['private_document']='INVENTED_DO_NOT_PUBLISH'
        with self.assertRaises(ValueError):publish_daily_catalogue(repo,unexpected,transport=git)
        published_daily=publish_daily_catalogue(repo,catalogue,transport=git);parent=published_daily['pages_commit']
        self.assertEqual(published_daily.get('public_url'),'https://raw.githubusercontent.com/haji84/RACE-AI/gh-pages/data/racer-daily.json','scheduled data must be readable without relying on a GITHUB_TOKEN Pages build')
        self.assertEqual(git.read(parent,PUBLIC_PATH,4000000),daily)
        status_path='data/racer-live-status.json'
        self.assertTrue(git.exists(parent,status_path),'the browser must be able to check a small status without downloading all profiles')
        status=json.loads(git.read(parent,status_path,16000));self.assertEqual(status['catalogue_sha256'],sha(daily))
        refreshed=self.m.refresh_site_assets(repo,expected_parent=parent,transport=git)
        self.assertEqual(git.read(refreshed['source_commit'],PUBLIC_PATH,4000000),daily)
        published=self.m.publish_site(repo,public,expected_manifest_sha256=built['manifest_sha256'],expected_parent=refreshed['source_commit'],transport=git)
        self.assertEqual(git.read(published['source_commit'],PUBLIC_PATH,4000000),daily)
        self.assertEqual(git.read(published['source_commit'],status_path,16000),git.read(parent,status_path,16000))
        self.assertEqual(git._run(['ls-tree','-r',published['source_commit'],'--','views']),before)
        from datetime import timedelta
        from race_ai.racer_intraday import IntradayState
        from tests.intraday_fixture import day_index,packet
        live=IntradayState()
        def source(url):return (day_index() if '/race/index?' in url else packet()[0]),NOW.isoformat()
        live.advance(store,now=NOW,fetch=source,max_requests=2);store.clock=lambda:NOW+timedelta(minutes=5)
        current=store.catalogue(ROSTER,as_of=store.clock().isoformat(),extra_rows=live.extra_rows(store,now=NOW),live=live.metadata(NOW))
        accepted=publish_daily_catalogue(repo,current,transport=git)
        self.assertEqual(json.loads(git.read(accepted['pages_commit'],PUBLIC_PATH,4000000))['people'][0]['summary']['starts'],4)
        legacy=deepcopy(catalogue);legacy['generated_at']=(NOW+timedelta(minutes=10)).isoformat()
        with self.assertRaises(ValueError):publish_daily_catalogue(repo,legacy,transport=git)

    def test_official_profiles_migrate_into_old_pages_without_changing_any_cipher(self):
        from race_ai.racer_profiles import FILES
        built=self.build();public=self.root/'public'
        for name in FILES:self.assertTrue((public/name).is_file(),name)
        class LocalPages(self.m.PagesRepository):
            def _check_remote(inner):inner.fetch_url=inner.push_url=inner._run(['remote','get-url','origin']).decode().strip()
        repo=self.root/'profile-repo';remote=self.root/'profile-remote.git';repo.mkdir()
        for args in (['git','init','--bare',str(remote)],['git','init',str(repo)],['git','-C',str(repo),'remote','add','origin',str(remote)]):
            subprocess.run(args,check=True,capture_output=True)
        git=LocalPages(repo);legacy=json.loads((public/'site-build.json').read_text())
        legacy['files']={k:v for k,v in legacy['files'].items() if k not in FILES}
        files={name:(public/name).read_bytes() for name in legacy['files']}
        files['site-build.json']=(wire(legacy)+'\n').encode()
        parent=git.commit(files,None);git.push(parent,None);before=git._run(['ls-tree','-r',parent,'--','views'])
        report=self.m.refresh_site_assets(repo,expected_parent=parent,transport=git)
        self.assertEqual(git._run(['ls-tree','-r',report['source_commit'],'--','views']),before)
        for name in FILES:self.assertEqual(git.read(report['source_commit'],name,self.m.MAX_WIRE),(public/name).read_bytes())

    def test_portrait_assets_are_packaged_and_can_refresh_without_private_state(self):
        from race_ai.racer_portraits import FILES
        built=self.build();public=self.root/'public'
        for name in FILES:self.assertTrue((public/name).is_file(),name)
        self.assertIn('racer-portraits.js?v=',(public/'index.html').read_text())
        class LocalPages(self.m.PagesRepository):
            def _check_remote(inner):inner.fetch_url=inner.push_url=inner._run(['remote','get-url','origin']).decode().strip()
        repo=self.root/'repo';remote=self.root/'remote.git';repo.mkdir()
        for args in (['git','init','--bare',str(remote)],['git','init',str(repo)],['git','-C',str(repo),'remote','add','origin',str(remote)]):
            subprocess.run(args,check=True,capture_output=True)
        git=LocalPages(repo)
        first=self.m.publish_site(repo,public,expected_manifest_sha256=built['manifest_sha256'],initialize=True,transport=git)
        parent=first['source_commit']
        ciphertext=git.read(parent,built['cipher_path'],self.m.MAX_WIRE)
        prior=json.loads(git.read(parent,'site-build.json',32768))
        before=git._run(['ls-tree','-r',parent,'--','views'])
        # There are no original SQLite files, keys or owner URL inputs to refresh.
        report=self.m.refresh_site_assets(repo,expected_parent=parent,transport=git)
        current=report['source_commit']
        self.assertEqual(git.read(current,built['cipher_path'],self.m.MAX_WIRE),ciphertext)
        self.assertEqual(git._run(['ls-tree','-r',current,'--','views']),before)
        after=json.loads(git.read(current,'site-build.json',32768))
        self.assertEqual({k:v for k,v in prior.items() if k!='files'}, {k:v for k,v in after.items() if k!='files'})
        for name in FILES:self.assertEqual(git.read(current,name,self.m.MAX_WIRE),(public/name).read_bytes())
        self.assertEqual(report['portrait_count'],len(self.m.REGISTRATIONS))
        with self.assertRaises(ValueError):self.m.refresh_site_assets(repo,expected_parent=parent,transport=git)
        # A partial manifest cannot silently adopt a damaged Pages deployment.
        damaged=deepcopy(after);damaged['files']={built['cipher_path']:after['files'][built['cipher_path']]}
        bad=git.commit({'site-build.json':(wire(damaged)+'\n').encode()},current);git.push(bad,current)
        with self.assertRaises(ValueError):self.m.refresh_site_assets(repo,expected_parent=bad,transport=git)

    def setUp(self):
        from race_ai import saved_pages
        self.m=saved_pages;self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.state,self.pair=invented_research_state(self.root)
        state=PdcaState(self.state)
        try:self.content=state.content_sha256()
        finally:state.close()

    def build(self):
        return self.m.build_site(self.state,self.root/'public',self.root/'private',expected_source_sha256=self.content)

    def test_public_bundle_decrypts_to_the_same_four_originals_without_a_root_key(self):
        report=self.build();private=self.root/'private';public=self.root/'public'
        keydoc=json.loads((private/'viewer.json').read_text());key=base64.urlsafe_b64decode(keydoc['key']+'=')
        self.assertEqual(len(key),32);self.assertFalse((private/'viewer.json').stat().st_mode&0o077)
        self.assertEqual(report['races'],1);self.assertEqual(report['predictions'],4)
        envelope=json.loads((public/report['cipher_path']).read_text())
        raw=AESGCM(key).decrypt(base64.b64decode(envelope['nonce']),base64.b64decode(envelope['ciphertext']),wire(envelope['header']).encode())
        view=json.loads(raw);row=view['records'][0]
        for p in [row['prediction'],*row['comparison_predictions']]:
            variant='baseline' if p['variant']=='HISTORY_BASELINE' else 'history'
            original=self.pair[variant]['suite']['models'][p['model_id']]
            self.assertEqual(p['ordered_top8'],original['ordered_top8'])
            self.assertEqual(p['prediction_sha256'],original['prediction_sha256'])
        for path in public.rglob('*'):
            if path.is_file():
                body=path.read_bytes();self.assertNotIn(keydoc['key'].encode(),body)
                self.assertNotIn(self.pair['pair_sha256'].encode(),body)
        self.assertTrue((public/'.nojekyll').is_file())
        self.assertIn('app.js?v=',(public/'index.html').read_text())
        self.assertIn('#saved='+report['cipher_sha256']+'.'+keydoc['key'],(private/'owner-url.txt').read_text())
        self.assertTrue((private/'owner-url.txt').read_text().startswith('https://haji84.github.io/RACE-AI/'))

    def test_wrong_source_pin_or_overlapping_outputs_fail_without_publication(self):
        with self.assertRaises(ValueError):
            self.m.build_site(self.state,self.root/'public',self.root/'private',expected_source_sha256='0'*64)
        self.assertFalse((self.root/'public/index.html').exists())
        with self.assertRaises(ValueError):
            self.m.build_site(self.state,self.root/'same',self.root/'same/private',expected_source_sha256=self.content)

    def test_updated_payload_reuses_only_the_existing_private_view_key_and_url(self):
        original=self.build();old_url=(self.root/'private/owner-url.txt').read_bytes()
        report=self.m.build_site(self.state,self.root/'updated-public',self.root/'updated-private',
            expected_source_sha256=self.content,viewer_from=self.root/'private/viewer.json')
        self.assertNotEqual(report['cipher_sha256'],original['cipher_sha256'])
        self.assertEqual(report['view_id'],original['cipher_sha256'])
        self.assertEqual((self.root/'updated-private/owner-url.txt').read_bytes(),old_url)
        private=json.loads((self.root/'updated-private/viewer.json').read_text())
        envelope=json.loads((self.root/'updated-public'/report['cipher_path']).read_text())
        self.assertEqual(envelope['header']['schema'],'RACE_AI_SAVED_WEB_VIEW_V2')
        self.assertEqual(envelope['header']['view_id'],original['cipher_sha256'])
        key=base64.urlsafe_b64decode(private['key']+'=')
        self.assertTrue(AESGCM(key).decrypt(base64.b64decode(envelope['nonce']),base64.b64decode(envelope['ciphertext']),wire(envelope['header']).encode()))
        for path in (self.root/'updated-public').rglob('*'):
            if path.is_file():self.assertNotIn(private['key'].encode(),path.read_bytes())

    def test_viewer_reuse_rejects_public_or_malformed_key_files(self):
        self.build();p=self.root/'private/viewer.json';p.chmod(0o644)
        with self.assertRaises(ValueError):
            self.m.build_site(self.state,self.root/'new-public',self.root/'new-private',expected_source_sha256=self.content,viewer_from=p)
        p.chmod(0o600);data=json.loads(p.read_text());data['key']='invalid';p.write_text(wire(data))
        with self.assertRaises(ValueError):
            self.m.build_site(self.state,self.root/'new-public',self.root/'new-private',expected_source_sha256=self.content,viewer_from=p)

    def test_extra_plaintext_symlink_and_modified_assets_are_rejected(self):
        self.build();public=self.root/'public'
        extra=public/'original.json';extra.write_text('{"private_original":true}')
        with self.assertRaises(ValueError):self.m.validate_bundle(public)
        extra.unlink();asset=public/'app.js';original=asset.read_bytes();asset.write_bytes(original+b'\n// modified')
        with self.assertRaises(ValueError):self.m.validate_bundle(public)
        asset.write_bytes(original);asset.unlink();asset.symlink_to(self.root/'state.sqlite')
        with self.assertRaises(ValueError):self.m.validate_bundle(public)

    def test_changed_cipher_or_manifest_cannot_be_published(self):
        r=self.build();public=self.root/'public';path=public/r['cipher_path'];raw=path.read_bytes()
        path.write_bytes(raw+b' ')
        with self.assertRaises(ValueError):self.m.validate_bundle(public)
        path.write_bytes(raw);manifest=json.loads((public/'site-build.json').read_text());manifest['private_key']='not-allowed'
        (public/'site-build.json').write_text(wire(manifest))
        with self.assertRaises(ValueError):self.m.validate_bundle(public)

    def test_files_changed_during_git_lookup_cannot_replace_validated_public_bytes(self):
        public=self.root/'public';marker=b'fictional-view-key-must-not-be-published'
        class LocalPages(self.m.PagesRepository):
            changed=False
            def _check_remote(inner):inner.fetch_url=inner.push_url=inner._run(['remote','get-url','origin']).decode().strip()
            def head(inner):
                value=super().head()
                if not inner.changed:
                    inner.changed=True;(public/'app.js').write_bytes(marker)
                return value
        repo=self.root/'repo';remote=self.root/'remote.git';repo.mkdir()
        for args in (['git','init','--bare',str(remote)],['git','init',str(repo)],['git','-C',str(repo),'remote','add','origin',str(remote)]):
            subprocess.run(args,check=True,capture_output=True)
        built=self.build();original=(public/'app.js').read_bytes();transport=LocalPages(repo)
        result=self.m.publish_site(repo,public,expected_manifest_sha256=built['manifest_sha256'],initialize=True,transport=transport)
        self.assertEqual(transport.read(result['source_commit'],'app.js',1000000),original)

    def test_same_repo_pages_ref_and_cas_publication_preserve_prior_commit(self):
        from race_ai.boat_pdca_github_handoff import GitStateRepository
        class LocalPages(self.m.PagesRepository):
            def _check_remote(inner):inner.fetch_url=inner.push_url=inner._run(['remote','get-url','origin']).decode().strip()
        repo=self.root/'repo';remote=self.root/'remote.git';repo.mkdir()
        for args in (['git','init','--bare',str(remote)],['git','init',str(repo)],['git','-C',str(repo),'remote','add','origin',str(remote)]):
            subprocess.run(args,check=True,capture_output=True)
        built=self.build();transport=LocalPages(repo)
        first=self.m.publish_site(repo,self.root/'public',expected_manifest_sha256=built['manifest_sha256'],initialize=True,transport=transport)
        self.assertEqual(transport.ref,'gh-pages')
        self.assertEqual(transport.head(),first['source_commit'])
        self.assertEqual(transport.read(first['source_commit'],'index.html',100000),(self.root/'public/index.html').read_bytes())
        with self.assertRaises(ValueError):self.m.publish_site(repo,self.root/'public',expected_manifest_sha256=built['manifest_sha256'],expected_parent='b'*40,transport=transport)
        with self.assertRaises(ValueError):GitStateRepository(repo,ref='gh-pages')
        # A view from a previous deployment may not be inherited as a symlink.
        with tempfile.TemporaryDirectory() as index_dir:
            import os
            env=dict(os.environ,GIT_INDEX_FILE=str(Path(index_dir)/'index'))
            transport._run(['read-tree',first['source_commit']],env=env)
            cipher_path=built['cipher_path'];blob=transport._run(['rev-parse',first['source_commit']+':'+cipher_path]).decode().strip()
            transport._run(['update-index','--cacheinfo','120000,'+blob+','+cipher_path],env=env)
            tree=transport._run(['write-tree'],env=env).decode().strip()
            bad=transport._run(['-c','user.name=invented','-c','user.email=test@example.invalid','-c','commit.gpgSign=false',
                'commit-tree',tree,'-p',first['source_commit']],body=b'invented unsafe mode\n',env=env).decode().strip()
            transport.push(bad,first['source_commit'])
        with self.assertRaises(ValueError):self.m.publish_site(repo,self.root/'public',expected_manifest_sha256=built['manifest_sha256'],expected_parent=bad,transport=transport)
        # An unrelated existing Pages branch is never adopted by a matching SHA alone.
        transport._run(['config','user.name','invented']);transport._run(['config','user.email','test@example.invalid'])
        unrelated=transport.commit({'unrelated.txt':b'existing other site'},bad);transport.push(unrelated,bad)
        with self.assertRaises(ValueError):self.m.publish_site(repo,self.root/'public',expected_manifest_sha256=built['manifest_sha256'],expected_parent=unrelated,transport=transport)
