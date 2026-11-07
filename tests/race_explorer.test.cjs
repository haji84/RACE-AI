'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const U=require('../web/ui-model.js');
const now=Date.parse('2030-01-01T01:00:00Z');
test('venue overview puts favorites first and finds the next known cutoff without rewriting races',()=>{
  const records=Object.freeze([
    Object.freeze({race_id:'past',sport:'boat',venue:'場コード01',cutoff_at:'2030-01-01T09:00:00+09:00'}),
    Object.freeze({race_id:'later',sport:'boat',venue:'場コード24',cutoff_at:'2030-01-01T12:00:00+09:00'}),
    Object.freeze({race_id:'next',sport:'boat',venue:'大村',cutoff_at:'2030-01-01T11:00:00+09:00'}),
    Object.freeze({race_id:'unknown',sport:'boat',venue:'読込テスト場',cutoff_at:null}),
    Object.freeze({race_id:'horse',sport:'horse',venue:'東京',cutoff_at:'2030-01-01T10:30:00+09:00'})
  ]),before=JSON.stringify(records);
  const venues=U.venueOverview(records,{sport:'boat',now,favorites:['boat:大村']});
  assert.equal(venues.length,25);assert.equal(venues[0].venue,'大村');assert.equal(venues[0].favorite,true);
  assert.equal(venues[0].count,2);assert.equal(venues[0].nextRace,records[2]);
  assert.equal(venues.find(v=>v.venue==='桐生').nextRace,null);
  assert.equal(venues.find(v=>v.venue==='読込テスト場').nextRace,null);
  assert.equal(JSON.stringify(records),before);
  assert.deepEqual(U.venueOverview(records,{sport:'horse',now}).map(v=>v.venue),['東京']);
});
test('all 24 boat venues remain selectable with no imported schedule',()=>{
  const venues=U.venueOverview([],{sport:'boat',now,favorites:null});
  assert.equal(venues.length,24);assert.ok(venues.every(v=>v.count===0&&v.nextRace===null&&!v.favorite));
  assert.ok(venues.some(v=>v.venue==='江戸川'));assert.ok(venues.some(v=>v.venue==='びわこ'));
});
test('information states describe partial saved values, preserving zero and avoiding unvalidated supplements',()=>{
  const row={participants:[{preview_st:0}],prediction:{ordered_top8:[[1,2,3]]},comparison_predictions:[{}],result:{status:'pending'},
    boat_observation_context:{beforeinfo:{status:'PARSED'}}};
  const states=Object.fromEntries(U.raceInformation(row).map(s=>[s.key,s]));
  assert.equal(states.participants.available,true);assert.equal(states.preview.available,true);
  assert.equal(states.outlook.detail,'2原本');assert.equal(states.history.available,false);
  assert.equal(U.raceInformation({boat_observation_context:row.boat_observation_context}).find(s=>s.key==='preview').available,false);
  assert.equal(U.raceInformation({}, {supplementalPreview:true}).find(s=>s.key==='preview').available,true);
  assert.ok(U.raceInformation({}).every(s=>!s.available));
  assert.equal(U.raceInformation({result:{status:'void'}}).find(s=>s.key==='history').available,true);
});
test('official race links bind each of the 24 venues to the exact saved day and race',()=>{
  for(let i=1;i<=24;i++){
    const code=String(i).padStart(2,'0'),row={race_id:`20300101-${code}-07`,sport:'boat',venue:'場コード'+code,race_no:7,event_date_jst:'2030-01-01',scope:'research'};
    const links=U.boatRaceLinks(row);assert.equal(links.length,4);
    assert.deepEqual(links.map(l=>l.kind),['participants','preview','odds','history']);
    for(const link of links){const url=new URL(link.url);assert.equal(url.origin,'https://www.boatrace.jp');assert.equal(url.searchParams.get('hd'),'20300101');assert.equal(url.searchParams.get('jcd'),code);assert.equal(url.searchParams.get('rno'),'7');}
    assert.equal(new URL(links[1].url).pathname,'/owpc/pc/race/beforeinfo');
  }
  assert.equal(new URL(U.boatRaceLinks({sport:'boat',venue:'江戸川',race_no:1,event_date_jst:'2030-01-01'})[0].url).searchParams.get('jcd'),'03');
});
test('official race links reject conflicting identities, unknown metadata and synthetic or other-sport races',()=>{
  const row={race_id:'20300101-03-01',sport:'boat',venue:'江戸川',race_no:1,event_date_jst:'2030-01-01'};
  for(const patch of [{venue:'桐生'},{race_no:2},{event_date_jst:'2030-01-02'},{event_date_jst:'2030-02-30'},
    {race_no:null},{race_no:'1'},{venue:null},{venue:'未知の会場'},{sport:'horse'},{scope:'synthetic'},{synthetic:true}]){
    assert.deepEqual(U.boatRaceLinks({...row,...patch}),[],JSON.stringify(patch));
  }
});
