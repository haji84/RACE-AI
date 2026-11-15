"""Exercise the public codec's supported size and strict Base64 boundary offline."""
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GithubCheckpointBoundsTests(unittest.TestCase):
    def node(self, code):
        result = subprocess.run(
            ['node', '--input-type=module', '-e', code], cwd=ROOT,
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_supported_eight_mib_snapshot_roundtrips_without_stack_overflow(self):
        self.node("""
import assert from 'node:assert/strict';
import {randomBytes} from 'node:crypto';
import {seal,unseal} from './scripts/keirin_github_checkpoint.mjs';
const scope={schema:'RACE_AI_GITHUB_SQLITE_V1',repository_id:'1416489937',
 mode:'production',generation:1,previous_cipher_sha256:null};
// Invented payload only; this ephemeral key never encrypts actual racer data.
const plain=Buffer.alloc(8*1024*1024);
Buffer.from('SQLite format 3\\0').copy(plain);
const key=randomBytes(32), cipher=seal(plain,key,scope);
assert.deepEqual(unseal(cipher,key,scope),plain);
assert.throws(()=>unseal(cipher,randomBytes(32),scope),
 {name:'CheckpointError',message:'CHECKPOINT_AUTHENTICATION_FAILED'});
assert.throws(()=>seal(Buffer.concat([plain,Buffer.from([0])]),key,scope),
 {name:'CheckpointError',message:'SQLITE_SNAPSHOT_SIZE_INVALID'});
""")

    def test_noncanonical_or_oversized_base64_remains_rejected(self):
        self.node("""
import assert from 'node:assert/strict';
import {randomBytes} from 'node:crypto';
import {seal,unseal} from './scripts/keirin_github_checkpoint.mjs';
const scope={schema:'RACE_AI_GITHUB_SQLITE_V1',repository_id:'1416489937',
 mode:'production',generation:1,previous_cipher_sha256:null};
const plain=Buffer.alloc(1025);Buffer.from('SQLite format 3\\0').copy(plain);
const key=randomBytes(32), original=JSON.parse(seal(plain,key,scope));
for(const change of [
 x=>{x.ciphertext+='\\n'},
 x=>{x.ciphertext=x.ciphertext.slice(0,-1)},
 x=>{x.ciphertext='!'+x.ciphertext.slice(1)},
 x=>{x.nonce='AB=='}, // Nonzero unused bits must not become canonical AA==.
 x=>{x.ciphertext='A'.repeat(4*Math.ceil(8*1024*1024/3)+4)},
]) {
 const bad=structuredClone(original);change(bad);
 assert.throws(()=>unseal(Buffer.from(JSON.stringify(bad)),key,scope),
  {name:'CheckpointError',message:'INVALID_BASE64'});
}
const changed=structuredClone(original);
changed.ciphertext=(changed.ciphertext[0]==='A'?'B':'A')+changed.ciphertext.slice(1);
assert.throws(()=>unseal(Buffer.from(JSON.stringify(changed)),key,scope),
 {name:'CheckpointError',message:'CHECKPOINT_AUTHENTICATION_FAILED'});
""")
