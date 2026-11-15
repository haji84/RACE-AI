"""Fictional HTML currency representations must not make refunds pending."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class OfficialPayoutCurrencyTest(unittest.TestCase):
    def test_encoded_yen_matches_plain_yen_for_confirmed_refund(self):
        js = r'''
import assert from 'node:assert/strict';
import {parseResultDetails} from './workers/boat_official_html.mjs';
const links=Array.from({length:12},(_,i)=>`<a href="/owpc/pc/race/raceresult?rno=${i+1}&jcd=17&hd=20301103">R</a>`).join('');
const table=(head,rows)=>'<table><thead><tr>'+head.map(x=>'<th>'+x+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(x=>'<td>'+x+'</td>').join('')+'</tr>').join('')+'</tbody></table>';
const finish=table(['着','枠','ボートレーサー','レースタイム'],Array.from({length:6},(_,i)=>[i===4?'F':String(i+1),String(i+1),String(4201+i)+' Sample','1.50.0']));
for(const price of ['¥980','&yen;980','&#165;980','&#xA5;980']){
 const html=links+finish+table(['勝式','組番','払戻金'],[['3連単','1-2-3',price]])+table(['返還'],[['5']]);
 const result=parseResultDetails(html,'20301103','17',1);
 assert.equal(result.payout_per_100_yen,980,price);
 assert.deepEqual(result.refund_boats,[5]);
}
'''
        done = subprocess.run(['node', '--input-type=module', '-e', js], cwd=ROOT,
                              capture_output=True, text=True, timeout=15)
        self.assertEqual(done.returncode, 0, done.stderr)

if __name__ == '__main__':
    unittest.main()
