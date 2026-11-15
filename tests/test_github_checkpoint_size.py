"""Invented SQLite-shaped bytes exercise the codec's advertised size boundary."""
import subprocess
import unittest


class CheckpointSizeTests(unittest.TestCase):
    def test_maximum_snapshot_round_trip_and_strict_base64(self):
        result = subprocess.run(['node', '--input-type=module', '-e', r'''
import assert from 'node:assert/strict';
import {seal,unseal,syntheticKey} from './scripts/keirin_github_checkpoint.mjs';
const scope={schema:'RACE_AI_GITHUB_SQLITE_V1',repository_id:'1416489937',
 mode:'synthetic',generation:1,previous_cipher_sha256:null};
const plain=Buffer.alloc(8*1024*1024,17);
Buffer.from('SQLite format 3\0').copy(plain);
const key=syntheticKey(), envelope=seal(plain,key,scope);
assert.deepEqual(unseal(envelope,key,scope),plain);
const base=JSON.parse(envelope);
for(const value of [base.ciphertext+'A',base.ciphertext.slice(0,-1)+' ',
 base.ciphertext.slice(0,100)+'!'+base.ciphertext.slice(101),
 base.ciphertext.slice(0,-2)+'F=']){
 assert.throws(()=>unseal(Buffer.from(JSON.stringify({...base,ciphertext:value})),key,scope),
  {message:'INVALID_BASE64'});
}
assert.throws(()=>seal(Buffer.concat([plain,Buffer.alloc(1)]),key,scope),
 {message:'SQLITE_SNAPSHOT_SIZE_INVALID'});
'''], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
