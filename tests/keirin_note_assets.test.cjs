'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
test('the combined guide preserves the existing BOAT source-free reader',()=>{
  const app=fs.readFileSync(require.resolve('../web/app.js'),'utf8');
  const boundary='\n"use strict";\n/* PR #62 page shell';
  const start=app.indexOf('/* Count-only visual attestation against the owner-approved 2026-11-12 AES audit.');
  const end=app.indexOf(boundary,start);
  assert.ok(start>=0&&end>start);
  const holder={exports:{}};
  vm.runInNewContext(app.slice(start,end),{module:holder,URL});
  assert.equal(holder.exports.DAY,'2026-11-12');
  assert.ok(holder.exports.EVIDENCE.endsWith('/43339230921'));
});

test('the note bundle contains only the reviewed growth aggregates',()=>{
  const app=fs.readFileSync(require.resolve('../web/app.js'),'utf8');
  const match=app.match(/^  const reviewedGrowth = (\{[^\n]+\});$/m);
  assert.ok(match,'private note view is missing its reviewed growth aggregates');
  const growth=JSON.parse(match[1]);
  const evidence='../docs/evidence/keirin-live-accuracy-closure-20261125/';
  const historical=require(evidence+'retrospective-score.json');
  const paired=historical.paired_day_bootstrap_95;
  const hitPairs=(a,b)=>Object.fromEntries(Object.keys(a).map(k=>[k,{baseline:a[k],challenger:b[k]}]));
  assert.deepEqual(growth,{
    historical:{from:'2026-10-01',to:'2026-11-22',races:3201,days:48,
      hits:hitPairs({top1_3t:401,top4_3t:928,top8_3t:1298,top2_2t:1237},
        {top1_3t:428,top4_3t:947,top8_3t:1323,top2_2t:1240}),
      intervals:{top4_3t:paired.top4_3t,top2_2t:paired.top2_2t}},
    forward:{day:'2026-11-25',registered:10,matched:10,
      hits:hitPairs({top1_3t:2,top4_3t:3,top8_3t:4,top2_2t:3},
        {top1_3t:2,top4_3t:4,top8_3t:4,top2_2t:3})},
    replay:{day:'2026-11-25',race:'武雄1R',frames:12,riders:6,agreed:65,
      correct:46,incorrect:7,abstained:12,unscorable:7,official_finish_positions:6,
      trial_training_segments:2}
  });
});
