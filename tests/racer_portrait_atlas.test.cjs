'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const R=require('../web/racer-portraits.js');
const data=JSON.parse(fs.readFileSync(path.join(__dirname,'../web/data/racer-portraits.json')));

test('completed athlete cells resolve to their exact verified atlas position',()=>{
  const people=data.people.filter(p=>p.state==='READY'&&p.atlas);
  assert.ok(people.length>=25);
  for(const p of people){
    const found=R.get({sport:'boat',scope:'research'},{registration_no:p.registration,name:p.name});
    assert.equal(found?.registration,p.registration);
    assert.equal(found?.atlas?.column,p.atlas.slot%p.atlas.columns);
    assert.equal(found?.atlas?.row,Math.floor(p.atlas.slot/p.atlas.columns));
    assert.equal(found?.atlas?.columns,p.atlas.columns);
    assert.equal(found?.src.split('?')[0],'./'+p.asset);
  }
});

test('coverage reports the whole target and never treats a pending athlete as created',()=>{
  assert.equal(R.coverage?.total,1669);
  assert.equal(R.coverage?.ready,data.people.filter(p=>p.state==='READY').length);
  assert.equal(R.coverage?.complete,R.coverage?.ready===1669);
  for(const p of data.people.filter(p=>p.state!=='READY'))assert.equal(R.get({sport:'boat'},{registration_no:p.registration}),null);
});

test('browser catalogue preserves six-by-six last-cell geometry and official name aliases',()=>{
  const person={registration:'9001',name:'架空選手',aliases:['架空選手','旧姓選手'],state:'READY',asset:'assets/racer-portraits/sheet-9000.webp',source_url:'https://www.boatrace.jp/owpc/pc/data/racersearch/profile?toban=9001',atlas:{columns:6,rows:6,slot:35}};
  const context={RaceRacerPortraitData:{total:2,people:[person,{registration:'9002',name:'未作成',aliases:['未作成'],state:'PENDING'}],assets:{[person.asset]:{sha256:'a'.repeat(64),bytes:1234}}}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web/racer-portraits.js'),'utf8'),context);
  const actual=context.RaceRacerPortraits.get({sport:'boat'},{participant_id:'9001',name:'旧姓 選手'});
  assert.equal(actual?.atlas?.row,5);assert.equal(actual?.atlas?.column,5);
  assert.equal(context.RaceRacerPortraits.coverage.complete,false);
});
