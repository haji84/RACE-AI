"""Read-only context snapshots use invented encrypted feeds and local bare Git."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from race_ai import saved_view_feed as F
from race_ai.boat_history_store import wire
from scripts import boat_saved_site_context as C
from tests.test_racer_result_bridge import saved_view
from tests.test_saved_view_history_publication import LocalFeed


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.remote=self.root/'remote.git';self.writer_root=self.root/'writer'
        self.writer_root.mkdir()
        for command in (['git','init','--bare',str(self.remote)],['git','init',str(self.writer_root)],
                        ['git','-C',str(self.writer_root),'remote','add','origin',self.remote.as_uri()]):
            subprocess.run(command,check=True,capture_output=True)
        self.writer=LocalFeed(self.writer_root);parent=None;self.irrelevant=[]
        for number in range(12):
            parent=self.writer.commit({'invented-unrelated.bin':bytes([number])*8192},parent)
            self.irrelevant.append(parent)
        self.unrelated_blob=self.writer._run(['rev-parse',parent+':invented-unrelated.bin']).decode().strip()
        self.view=saved_view(('2030-03-31','2030-04-01'))
        self.bootstrap=dict(key=b'x'*32,view_id='a'*64,cipher_sha256='c'*64,
            forecast_sha256=F.originals_sha(self.view),pages_commit='d'*40)
        raw=F.encrypt_view(self.view,self.bootstrap['key'],view_id=self.bootstrap['view_id'],
            source_sha='c'*64,generation=1,previous='d'*64)
        ident=F.sha(raw)
        seed=self.writer.commit_snapshot({'views/'+ident+'.json':raw,
            'latest.json':(wire(dict(header=json.loads(raw)['header'],cipher_sha256=ident))+'\n').encode()},parent)
        self.writer.push(seed,None)
        p,previous,generation,view=F.current_view(self.writer,self.bootstrap)
        published=F.publish_view(self.writer,self.bootstrap,view,parent=p,previous=previous,generation=generation,history=True)
        self.parent=published['commit'];self.generation=published['generation']

    def reader(self,name='reader',*,promisor=False):
        root=self.root/name;root.mkdir()
        for command in (['git','init',str(root)],['git','-C',str(root),'remote','add','origin',self.remote.as_uri()]):
            subprocess.run(command,check=True,capture_output=True)
        if promisor:
            subprocess.run(['git','--git-dir',str(self.remote),'config','uploadpack.allowFilter','true'],check=True,capture_output=True)
            subprocess.run(['git','-C',str(root),'fetch','--depth=1','--filter=blob:none','origin',self.parent],check=True,capture_output=True)
            for key,value in (('remote.origin.promisor','true'),('remote.origin.partialclonefilter','blob:none')):
                subprocess.run(['git','-C',str(root),'config',key,value],check=True,capture_output=True)
            objects=self.objects(root)
            latest=json.loads(self.writer.read(self.parent,'latest.json',4096))
            cipher_blob=self.writer._run(['rev-parse',self.parent+':views/'+latest['cipher_sha256']+'.json']).decode().strip()
            self.assertIn(self.parent,objects);self.assertNotIn(cipher_blob,objects,'the source must have a promised missing cipher blob')
        snapshot=self.root/(name+'-snapshot');snapshot.mkdir(mode=0o700)
        class LocalSnapshot(C.SnapshotFeedRepository):
            def _check_remote(inner):inner.fetch_url=inner.push_url=inner._run(['remote','get-url','origin']).decode().strip()
        return LocalSnapshot(root,snapshot=snapshot)

    def objects(self,root):
        return set(subprocess.run(['git','cat-file','--batch-all-objects','--batch-check=%(objectname)'],
            cwd=root,check=True,capture_output=True,text=True).stdout.splitlines())

    def missing(self,reader,object_id):
        return subprocess.run(['git','cat-file','-e',object_id],cwd=reader.repo,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE).returncode!=0

    def test_exact_day_snapshots_authenticate_without_fetching_irrelevant_ancestors(self):
        reader=self.reader()
        with patch('urllib.request.urlopen',side_effect=AssertionError('HTTP forbidden')):
            p,_,g,current=F.current_view(reader,self.bootstrap,day='2030-04-01')
            old_p,_,old_g,old=F.current_view(reader,self.bootstrap,day='2030-03-31')
        self.assertEqual((p,g),(self.parent,self.generation));self.assertEqual((old_p,old_g),(p,g))
        self.assertEqual(current['records'],[self.view['records'][1]])
        self.assertEqual(old['records'],[self.view['records'][0]])
        for commit in self.irrelevant:self.assertTrue(self.missing(reader,commit),'unneeded ancestor commit fetched')
        self.assertTrue(self.missing(reader,self.unrelated_blob),'unneeded ancestor blob fetched')

    def test_cached_exact_commit_skips_network_but_still_validates_tree_and_authentication(self):
        reader=self.reader();F.current_view(reader,self.bootstrap,day='2030-04-01')
        F.current_view(reader,self.bootstrap,day='2030-03-31')
        commands=[];original=reader._run
        def run(args,**kwargs):commands.append(args);return original(args,**kwargs)
        with patch.object(reader,'_run',side_effect=run),patch.object(reader,'validate_tree',wraps=reader.validate_tree) as validate:
            F.current_view(reader,self.bootstrap,day='2030-03-31')
        self.assertFalse(any(args[0] in ('fetch','ls-remote') for args in commands),'snapshot refetched or remote head reread')
        validate.assert_called_once_with(self.parent)
        with self.assertRaisesRegex(ValueError,'HISTORY_AUTH_FAILED'):
            F.current_view(reader,dict(self.bootstrap,key=b'z'*32),day='2030-04-01')

    def test_partial_clone_with_a_promised_cipher_blob_cannot_expand_snapshot_history(self):
        reader=self.reader('partial',promisor=True);source=self.root/'partial';before=self.objects(source)
        F.current_view(reader,self.bootstrap,day='2030-04-01')
        F.current_view(reader,self.bootstrap,day='2030-03-31')
        objects=self.objects(reader.repo)
        self.assertFalse(set(self.irrelevant)&objects,'a commit/path probe implicitly fetched full ancestry')
        self.assertNotIn(self.unrelated_blob,objects)
        self.assertEqual(self.objects(source),before,'reading snapshots must not lazily hydrate the source checkout')

    def test_prior_day_stays_at_selected_parent_if_remote_advances(self):
        reader=self.reader();p,_,g,_=F.current_view(reader,self.bootstrap,day='2030-04-01')
        parent,previous,generation,old=F.current_view(self.writer,self.bootstrap,day='2030-03-31')
        changed=deepcopy(old);changed['records'][0]['missing_reasons'].append('INVENTED_NEW_GENERATION')
        F.publish_view(self.writer,self.bootstrap,changed,parent=parent,previous=previous,generation=generation)
        self.assertNotEqual(self.writer.head(),p)
        old_p,_,old_g,still_old=F.current_view(reader,self.bootstrap,day='2030-03-31')
        self.assertEqual((old_p,old_g),(p,g));self.assertNotIn('INVENTED_NEW_GENERATION',still_old['records'][0]['missing_reasons'])

    def test_cipher_and_manifest_corruption_hold_even_for_cached_commits(self):
        for target in ('cipher','manifest'):
            reader=self.reader(target);F.current_view(reader,self.bootstrap,day='2030-04-01');original=reader.read
            def corrupt(commit,path,limit):
                raw=original(commit,path,limit)
                if target=='cipher' and path.startswith('views/'):return raw[:-1]+b' '
                if target=='manifest' and path=='latest.json':
                    value=json.loads(raw);value['header']['generation']+=1;return (wire(value)+'\n').encode()
                return raw
            with self.subTest(target=target),patch.object(reader,'read',side_effect=corrupt),self.assertRaisesRegex(ValueError,'FEED_HISTORY_HASH|FEED_CIPHER_HASH|FEED_MANIFEST_MISMATCH'):
                F.current_view(reader,self.bootstrap,day='2030-04-01')

    def test_readonly_transport_rejects_publication_invalid_sha_and_missing_ref(self):
        reader=self.reader()
        for operation,args in (('commit',({},self.parent)),('commit_snapshot',({},self.parent)),('push',(self.parent,None))):
            with self.subTest(operation=operation),self.assertRaisesRegex(ValueError,'SAVED_SITE_READ_ONLY'):
                getattr(reader,operation)(*args)
        for commit in ('--all','a'*39,'A'*40,None):
            with self.subTest(commit=commit),self.assertRaisesRegex(ValueError,'SAVED_SITE_SNAPSHOT_COMMIT_INVALID'):
                reader.fetch(commit)
        subprocess.run(['git','--git-dir',str(self.remote),'update-ref','-d','refs/heads/'+F.REF],check=True,capture_output=True)
        with self.assertRaisesRegex(ValueError,'SAVED_SITE_SNAPSHOT_REF_REQUIRED'):
            F.current_view(self.reader('missing'),self.bootstrap,day='2030-04-01')

    def test_existing_remote_and_rewrite_rejections_are_preserved(self):
        self.assertTrue(hasattr(C,'SnapshotFeedRepository'),'read-only snapshot transport is available')
        root=self.root/'unsafe';root.mkdir()
        snapshot=self.root/'unsafe-snapshot';snapshot.mkdir(mode=0o700)
        for command in (['git','init',str(root)],['git','-C',str(root),'remote','add','origin','https://example.invalid/foreign.git']):
            subprocess.run(command,check=True,capture_output=True)
        with self.assertRaisesRegex(ValueError,'STATE_GIT_REPOSITORY_REJECTED'):C.SnapshotFeedRepository(root,snapshot=snapshot)
        subprocess.run(['git','-C',str(root),'remote','set-url','origin','https://github.com/haji84/RACE-AI.git'],check=True,capture_output=True)
        subprocess.run(['git','-C',str(root),'config','url.https://example.invalid/.insteadOf','https://github.com/'],check=True,capture_output=True)
        with self.assertRaisesRegex(ValueError,'STATE_GIT_URL_REWRITES_REJECTED'):C.SnapshotFeedRepository(root,snapshot=snapshot)

    def test_private_snapshot_keeps_process_scoped_git_headers_and_configuration(self):
        header='http.https://github.com/haji84/RACE-AI.extraheader'
        environment=dict(GIT_CONFIG_COUNT='2',GIT_CONFIG_KEY_0=header,GIT_CONFIG_VALUE_0='PUBLIC_FIXTURE_AUTH_HEADER',
            GIT_CONFIG_KEY_1='credential.helper',GIT_CONFIG_VALUE_1='PUBLIC_FIXTURE_HELPER_UNUSED')
        with patch.dict(os.environ,environment):
            reader=self.reader('credentials')
            self.assertEqual(reader._run(['config','--get',header]),b'PUBLIC_FIXTURE_AUTH_HEADER\n')
            self.assertEqual(reader._run(['config','--get','credential.helper']),b'PUBLIC_FIXTURE_HELPER_UNUSED\n')
            self.assertEqual(F.current_view(reader,self.bootstrap,day='2030-04-01')[2],self.generation)


if __name__=='__main__':unittest.main()
