"""A separate display recipient; invented packets, local Git, no state secret."""
import base64
from hashlib import sha256
import importlib
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest


class NoteFeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)

    def api(self):
        return importlib.import_module('race_ai.keirin_note_feed')

    def packet(self):
        return dict(schema='RACE_AI_KEIRIN_NOTE_VIEW_V1', dates=['2030-01-15'],
            files={}, formal_model_admission=False, production_weight_switch=False,
            original_files_preserved=True, source_commit='a'*40,
            imported_at='2030-01-15T00:00:00Z')

    def test_only_owner_private_key_decrypts_a_public_recipient_snapshot(self):
        api = self.api()
        recipient = api.create_recipient(self.root/'owner')
        public = recipient['public']
        self.assertEqual(set(public), {'schema','recipient_id','public_key'})
        snapshot = api.seal_snapshot(self.packet(), public, kind='import')
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        key = serialization.load_der_private_key(
            base64.urlsafe_b64decode(Path(recipient['private_key']).read_text().strip()+'=='),None)
        entry, wire = snapshot['entry'], snapshot['cipher']
        ephemeral = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),
            api.unb64(entry['ephemeral_public_key']))
        secret = key.exchange(ec.ECDH(), ephemeral)
        aes = HKDF(algorithm=hashes.SHA256(),length=32,salt=api.unb64(entry['salt']),
            info=api.INFO+public['recipient_id'].encode()).derive(secret)
        envelope = json.loads(wire)
        plain = AESGCM(aes).decrypt(base64.b64decode(envelope['nonce']),
            base64.b64decode(envelope['ciphertext']),api.canonical(envelope['header']))
        self.assertEqual(json.loads(plain),self.packet())
        self.assertEqual(sha256(wire).hexdigest(),entry['cipher_sha256'])
        self.assertNotIn(Path(recipient['private_key']).read_bytes().strip(),wire)
        self.assertIn('#notefeed=',Path(recipient['owner_url']).read_text())

    def test_index_is_append_only_and_provider_denial_cannot_be_reset(self):
        api=self.api();p=api.create_recipient(self.root/'owner')['public']
        a=api.seal_snapshot(self.packet(),p,kind='import')['entry']
        initial=api.append_index(None,p,entry=a)
        stopped=api.append_index(initial,p,denied=True)
        self.assertTrue(stopped['provider_denied'])
        with self.assertRaises(ValueError):api.append_index(stopped,p,entry=a)
        self.assertEqual(len(stopped['entries']),1)
        other=api.create_recipient(self.root/'other')['public']
        with self.assertRaises(ValueError):api.append_index(stopped,other)

    def test_public_index_rejects_secret_or_unapproved_fields(self):
        api=self.api();p=api.create_recipient(self.root/'owner')['public']
        index=api.append_index(None,p);index['key']='not-allowed'
        with self.assertRaises(ValueError):api.checked_index(index,p)
        with self.assertRaises(ValueError):api.create_recipient(self.root/'owner')

    def test_python_writer_and_webcrypto_reader_share_the_same_owner_capability(self):
        import shutil
        if not shutil.which('node'):self.skipTest('Node WebCrypto unavailable')
        api=self.api();cap=api.create_recipient(self.root/'owner')
        from race_ai.keirin_note_view import import_site
        folder=self.root/'site/data/2030-01-15';folder.mkdir(parents=True)
        (folder/'races.json').write_text(json.dumps({'races':[dict(
            race_id='203001159801',venue='Invented',race_no=1,riders=[])]}))
        note=import_site(self.root/'site',source_commit='a'*40)
        snap=api.seal_snapshot(note,cap['public'],kind='import')
        index=api.append_index(None,cap['public'],entry=snap['entry'])
        archive=api.seal_snapshot({**note,'files':{}},cap['public'],kind='archive')
        index=api.append_index(index,cap['public'],entry=archive['entry'])
        payload=dict(key=Path(cap['private_key']).read_text().strip(),
            index=index,cipher=list(snap['cipher']))
        script="""
        let raw='';process.stdin.on('data',x=>raw+=x);process.stdin.on('end',async()=>{
          try{const v=JSON.parse(raw),F=require('./web/keirin-note-feed.js');let calls=[];
            const data=await F.open(v.key,{fetcher:async(url,opt)=>{
              if(url.includes(v.key)||opt.credentials!=='omit')throw Error();calls.push(url);
              return new Response(url.endsWith('index.json')?JSON.stringify(v.index):new Uint8Array(v.cipher));
            }});
            if(data.days.get('2030-01-15').length!==1||calls.length!==2)throw Error();
            v.index.recipient_id='0'.repeat(64);
            try{F.checkIndex(v.index,'1'.repeat(64));process.exitCode=1;}catch{}
          }catch{process.exitCode=1;}
        });"""
        r=subprocess.run(['node','-e',script],input=json.dumps(payload).encode(),
            cwd=Path(__file__).resolve().parents[1],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.assertEqual(r.returncode,0,'Cross-language display decryption failed')
        self.assertEqual(r.stdout,b'')

    def test_git_write_preserves_previous_cipher_and_checkout_index(self):
        api=self.api();repo=self.root/'repo';remote=self.root/'origin.git'
        def git(*args,cwd=None):
            return subprocess.check_output(['git',*args],cwd=cwd,stderr=subprocess.DEVNULL)
        git('init','--bare',str(remote));git('init',str(repo));git('remote','add','origin',str(remote),cwd=repo)
        class LocalFeedGit(api.NoteFeedGit):
            def _remote(self):return 'origin'
        store=LocalFeedGit(repo)
        p=api.create_recipient(self.root/'owner')['public']
        a=api.seal_snapshot(self.packet(),p,kind='import')
        first=api.publish_snapshot(store,p,a,expected_parent=None)
        oldtree=git('ls-tree','-r',first['source_commit'],'--','views',cwd=repo)
        b=api.seal_snapshot(self.packet(),p,kind='research',captured_ids=['203001159801'])
        second=api.publish_snapshot(store,p,b,expected_parent=first['source_commit'])
        self.assertIn(oldtree.strip(),git('ls-tree','-r',second['source_commit'],'--','views',cwd=repo))
        self.assertFalse((repo/'.git/index').exists())
        with self.assertRaises(ValueError):api.publish_snapshot(store,p,b,expected_parent=first['source_commit'])
        index=api.checked_index(json.loads(store.read(second['source_commit'],'index.json')),p)
        self.assertEqual(len(index['entries']),2)

    def test_public_recipient_writer_rejects_an_alternate_push_destination(self):
        api=self.api();repo=self.root/'repo'
        def git(*args):return subprocess.check_output(['git',*args],cwd=repo,stderr=subprocess.DEVNULL)
        subprocess.check_call(['git','init',str(repo)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        git('remote','add','origin','https://github.com/haji84/RACE-AI.git')
        git('config','remote.origin.pushurl','https://github.com/example/another.git')
        with self.assertRaises(ValueError):api.NoteFeedGit(repo)


if __name__=='__main__':unittest.main()
