"""Python result writer and real WebCrypto reader; invented records, no network."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest

from race_ai import keirin_note_feed as feed
from race_ai import keirin_result_updates as updates
from race_ai.keirin_result_diagnostics import make_diagnostic


class NoteResultReaderTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node WebCrypto unavailable')
    def test_python_result_encryption_metadata_and_webcrypto_overlay_agree(self):
        day, rid = '2030-01-15', '203001159801'
        now = datetime(2030, 1, 15, 4, tzinfo=timezone.utc)
        at = now.isoformat()
        arms = {name: updates.pending_arm() for name in updates.ARMS}
        arms['A'] = dict(state='hit', points=4, stake_yen=None, return_yen=None)
        arms['B'] = dict(state='miss', points=6, stake_yen=None, return_yen=None)
        diagnostics = [make_diagnostic(purpose=purpose, stage='PARSE_RESULT',
            reason='RESULT_VALIDATED', http_status=200, observed_at=at)
            for purpose in ('OFFICIAL_JSON_CALENDAR', 'OFFICIAL_JSON_DAY_LIST',
                'OFFICIAL_JSON_RESULT_SUMMARY', 'OFFICIAL_JSON_HEADER', 'OFFICIAL_JSON_DETAIL')]
        doc = dict(schema=updates.SCHEMA, observed_at=at, races=[dict(
            race_id=rid, revision='c'*64, observed_at=at, authority='official',
            order_status='confirmed', payout_status='pending', winning_triples=['1-2-3'],
            payouts_100yen={}, source_comparison=[dict(source_id='official_json', state='matched')],
            diagnostics=diagnostics, arms=arms)])
        note = updates.note_packet(doc, source_commit='a'*40)
        card_text = json.dumps([dict(race_id=rid, venue='Invented', race_no=1, riders=[])])
        card_bytes = card_text.encode()
        card = {**note, 'files': {f'data/{day}/races.json': dict(
            text=card_text, bytes=len(card_bytes), sha256=sha256(card_bytes).hexdigest())}}
        with TemporaryDirectory() as folder:
            root = Path(folder); root.chmod(0o700)
            cap = feed.create_recipient(root/'owner')
            seed = feed.seal_snapshot(card, cap['public'], kind='import', clock=lambda: now)
            result = feed.seal_snapshot(note, cap['public'], kind='result', clock=lambda: now)
            index = feed.append_index(None, cap['public'], entry=seed['entry'], denied=True)
            index = feed.append_index(index, cap['public'], entry=result['entry'])
            self.assertEqual(result['entry']['result_revisions'], {rid: 'c'*64})
            self.assertEqual(result['entry']['captured_race_ids'], [])
            payload = dict(key=Path(cap['private_key']).read_text().strip(), index=index,
                day=day, rid=rid, ciphers={item['entry']['cipher_sha256']: list(item['cipher'])
                    for item in (seed, result)})
            script = """
            let raw='';process.stdin.on('data',x=>raw+=x);process.stdin.on('end',async()=>{
              try{
                const v=JSON.parse(raw),F=require('./web/keirin-note-feed.js');let calls=0;
                const data=await F.open(v.key,{fetcher:async(url,opt)=>{
                  if(url.includes(v.key)||opt.credentials!=='omit'||opt.redirect!=='error')throw Error();
                  calls++;
                  if(url.endsWith('index.json'))return new Response(JSON.stringify(v.index));
                  const sha=url.split('/').at(-1).replace('.json','');
                  if(!v.ciphers[sha])throw Error();
                  return new Response(new Uint8Array(v.ciphers[sha]));
                }});
                const rows=data.days.get(v.day),r=rows[0]?.resultUpdate;
                if(rows.length!==1||rows[0].id!==v.rid||calls!==3||!data.feed.providerDenied)throw Error();
                if(r.authority!=='official'||r.payout_status!=='pending'||r.arms.A.state!=='hit'||
                  r.arms.B.state!=='miss'||r.arms.C.state!=='pending'||r.arms.A.return_yen!==null||
                  Object.keys(r.arms).length!==5||r.diagnostics.length!==5)throw Error();
              }catch{process.exitCode=1;}
            });"""
            process = subprocess.run(['node', '-e', script], input=json.dumps(payload).encode(),
                cwd=Path(__file__).resolve().parents[1], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=30)
            self.assertEqual(process.returncode, 0, 'Python result → WebCrypto display failed')
            self.assertEqual(process.stdout, b'')


if __name__ == '__main__':
    unittest.main()
