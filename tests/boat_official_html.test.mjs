
import test from 'node:test';
import assert from 'node:assert/strict';
import {parseRacelist,parseExhibition,parseResult,parseResultDetails,parseSchedule} from '../workers/boat_official_html.mjs';
const day='20301103',venue='18',race=5;
const links=kind=>Array.from({length:12},(_,i)=>'<a href="/owpc/pc/race/'+kind+'?rno='+(i+1)+'&jcd='+venue+'&hd='+day+'">'+(i+1)+'R</a>').join('');
const table=(header,rows)=>'<table><thead><tr>'+header.map(x=>'<th>'+x+'</th>').join('')+'</tr></thead><tbody>'+
 rows.map(r=>'<tr>'+r.map(x=>'<td>'+x+'</td>').join('')+'</tr>').join('')+'</tbody></table>';
const registry=Array.from({length:6},(_,i)=>[String(i+1),'x','<a href="/owpc/pc/data/racersearch/profile?toban='+(4201+i)+'">'+(4201+i)+' / Racer</a>',
 'F0 L0 0.15','5.50 33.0 44.0','5.20 30.0 40.0','11 30.00 42.0','22 31.00 45.0']);
const exposure=Array.from({length:6},(_,i)=>[String(i+1),'x','<a href="/owpc/pc/data/racersearch/profile?toban='+(4201+i)+'">Racer</a>','-','6.8'+i,'-0.5']);
const racelist=links('racelist')+table(['枠','x','ボートレーサー','x','全国','当地','モーター','ボート'],registry);
const before=links('beforeinfo')+table(['枠','x','ボートレーサー','x','展示','チルト'],exposure);
const result=links('raceresult')+table(['着','枠','ボートレーサー','レースタイム'],
 Array.from({length:6},(_,i)=>[String(i+1),String(i+1),String(4201+i)+' Racer','1:49.00']))+
 table(['勝式','組番','払戻金'],[['3連単','1-2-3','￥930']])+table(['返還'],[['']]);
test('six official racer identities and exhibition match',()=>{
 const roster=parseRacelist(racelist,day,venue,race);
 assert.equal(roster.length,6);assert.equal(roster[0].registration_no,'4201');
 const data=parseExhibition(before,day,venue,race,roster);
 assert.equal(data.length,6);assert.equal(data[0].exhibition_time_seconds,6.8);
 assert.deepEqual(parseResult(result,day,venue,race,roster),[1,2,3]);
});
test('wrong source venue, missing exhibition, refunded and finish conflict reject',()=>{
 const roster=parseRacelist(racelist,day,venue,race);
 assert.throws(()=>parseRacelist(racelist.replace('jcd=18','jcd=17'),day,venue,race));
 assert.throws(()=>parseExhibition(before.replace('6.80','--'),day,venue,race,roster));
 assert.throws(()=>parseResult(result.replace('1-2-3','1-3-2'),day,venue,race,roster));
 assert.throws(()=>parseResult(result.replace("<td></td>","<td>1</td>"),day,venue,race));
});


test('PR64 style six tbody racer groups each with four display rows',()=>{
 const multi=(head,rows)=>'<table><thead><tr>'+head.map(x=>'<th>'+x+'</th>').join('')+'</tr></thead>'+
 rows.map(r=>'<tbody><tr>'+r.map(x=>'<td>'+x+'</td>').join('')+'</tr>'+
 '<tr><td>extra display detail</td></tr><tr><td>stats</td></tr><tr><td>blank</td></tr></tbody>').join('')+'</table>';
 const html=links('racelist')+multi(['枠','x','ボートレーサー','x','全国','当地','モーター','ボート'],registry);
 const preview=links('beforeinfo')+multi(['枠','x','ボートレーサー','x','展示','チルト'],exposure);
 const a=parseRacelist(html,day,venue,race);
 assert.equal(a.length,6);
 assert.equal(parseExhibition(preview,day,venue,race,a).length,6);
});

test('trifecta payout is audit-only and missing price remains unknown',()=>{
 const roster=parseRacelist(racelist,day,venue,race);
 assert.deepEqual(parseResultDetails(result,day,venue,race,roster),{top3:[1,2,3],payout_per_100_yen:930});
 assert.equal(parseResultDetails(result.replace('￥930','￥1,280'),day,venue,race,roster).payout_per_100_yen,1280);
 assert.equal(parseResultDetails(result.replace('￥930','未掲載'),day,venue,race,roster).payout_per_100_yen,null);
});

test('real official HTML may print fullwidth racer lane numbers',()=>{
 const wide=x=>x.replace(/<td>([1-6])<\/td>/g,(_,n)=>'<td>'+String.fromCharCode(0xFF10+Number(n))+'</td>');
 const reg=parseRacelist(wide(racelist),day,venue,race);
 assert.equal(reg.length,6);
 assert.deepEqual(reg.map(x=>x.lane),[1,2,3,4,5,6]);
 const measured=parseExhibition(wide(before),day,venue,race,reg);
 assert.equal(measured.length,6);
 assert.deepEqual(parseResult(wide(result),day,venue,race,reg),[1,2,3]);
});
