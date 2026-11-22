'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const M=require('../web/keirin-note-model.js');

function row(id,date,venue,number,name='山田 一郎'){
  return {id,date,venue,number,title:'架空の予選',cutoff:date+'T12:00:00+09:00',start:null,
    sourceUrl:null,raw:{},riders:[{number:1,name}],cars:new Set([1]),lines:[],
    original:{headline:'架空の分析'},two:{},flexible:{},reference:{},referenceEnvelope:{},quote:{},
    settlement:null,rollover:{},environment:null,bindings:{},referenceHistory:[],resultHistory:[],
    resultUpdate:null,researchResultHistory:[],latestResearchResult:null};
}
function data(){
  return {dates:['2030-01-15','2030-01-16'],days:new Map([
    ['2030-01-15',[row('a','2030-01-15','青葉',1),row('b','2030-01-15','青葉',11)]],
    ['2030-01-16',[row('c','2030-01-16','架空場',2,'佐藤 二郎')]]])};
}
const ids=rows=>rows.map(r=>r.id);

test('calendar chooses the requested saved day without substituting another date',()=>{
  const d=data();assert.deepEqual(ids(M.historyRows(d,{period:'day',day:'2030-01-15'})),['a','b']);
  assert.deepEqual(M.historyRows(d,{period:'day',day:'2030-01-14'}),[]);
});
test('inclusive range searches older dates and all-saved scope sorts newest dates first',()=>{
  const d=data(),before=JSON.stringify([...d.days]);
  assert.deepEqual(ids(M.historyRows(d,{period:'range',from:'2030-01-15',to:'2030-01-16'})),['c','a','b']);
  assert.deepEqual(ids(M.historyRows(d,{period:'range',from:'2030-01-15',to:'2030-01-15'})),['a','b']);
  assert.deepEqual(ids(M.historyRows(d,{period:'all'})),['c','a','b']);
  assert.equal(JSON.stringify([...d.days]),before);
});
test('reversed, incomplete and invalid calendar ranges do not silently search all history',()=>{
  const d=data();
  for(const scope of [{period:'range',from:'2030-01-16',to:'2030-01-15'},
    {period:'range',from:'2030-01-15',to:''},{period:'range',from:'2030-02-30',to:'2030-03-01'},
    {period:'day',day:''},{period:'unknown'}])assert.deepEqual(M.historyRows(d,scope),[]);
  assert.deepEqual(M.historyRows(null,{period:'all'}),[]);
});
test('full-width whitespace and race tokens combine venue and athlete terms using AND',()=>{
  const rows=M.historyRows(data(),{period:'all'});
  assert.deepEqual(ids(rows.filter(r=>M.matchesHistory(r,{query:'　青葉　山田　１Ｒ　'}))),['a']);
  assert.deepEqual(ids(rows.filter(r=>M.matchesHistory(r,{query:'青葉１１Ｒ'}))),['b']);
  assert.deepEqual(rows.filter(r=>M.matchesHistory(r,{query:'山田 佐藤'})),[]);
});
test('race number one cannot match race eleven and combines with an exact venue filter',()=>{
  const rows=M.historyRows(data(),{period:'all'});
  assert.deepEqual(ids(rows.filter(r=>M.matchesHistory(r,{query:'1R'}))),['a']);
  assert.deepEqual(ids(rows.filter(r=>M.matchesHistory(r,{raceNumber:'11',venue:'青葉'}))),['b']);
  assert.deepEqual(rows.filter(r=>M.matchesHistory(r,{raceNumber:'1',venue:'架空場'})),[]);
  assert.deepEqual(rows.filter(r=>M.matchesHistory(r,{query:'13R'})),[]);
});
test('date queries accept ISO and slash forms without matching a partial day',()=>{
  const rows=M.historyRows(data(),{period:'all'});
  assert.deepEqual(ids(rows.filter(r=>M.matchesHistory(r,{query:'2030/1/15 山田'}))),['a','b']);
  assert.deepEqual(ids(rows.filter(r=>M.matchesHistory(r,{query:'2030-01-16'}))),['c']);
  assert.deepEqual(rows.filter(r=>M.matchesHistory(r,{query:'1/1'})),[]);
  assert.deepEqual(rows.filter(r=>M.matchesHistory(r,{query:'2029/1/15'})),[]);
});
test('search treats regular-expression punctuation literally and keeps original row values',()=>{
  const r=row('a','2030-01-15','青葉',1),before=JSON.stringify(r);
  assert.equal(M.matchesHistory(r,{query:'.*'}),false);
  assert.equal(M.matchesHistory(r,{query:'架空 予選'}),true);
  assert.equal(JSON.stringify(r),before);
});
test('twenty-card pages traverse all fifty-three matches without losing or duplicating originals',()=>{
  const rows=Array.from({length:53},(_,i)=>({id:String(i+1)})),before=JSON.stringify(rows);
  const first=M.historyPage(rows,1),second=M.historyPage(rows,2),third=M.historyPage(rows,3);
  assert.deepEqual([first.items.length,second.items.length,third.items.length],[20,20,13]);
  assert.deepEqual([first.first,first.last,first.total,first.pages],[1,20,53,3]);
  assert.deepEqual([third.first,third.last,third.page],[41,53,3]);
  assert.deepEqual([...first.items,...second.items,...third.items].map(r=>r.id),rows.map(r=>r.id));
  assert.equal(first.items[0],rows[0]);assert.equal(JSON.stringify(rows),before);
});
test('filtering to a shorter result clamps an old page and empty results remain navigable',()=>{
  const rows=Array.from({length:3},(_,i)=>({id:String(i)}));
  assert.deepEqual(M.historyPage(rows,99).items,rows);assert.equal(M.historyPage(rows,-1).page,1);
  assert.equal(M.historyPage(rows,NaN).page,1);
  const empty=M.historyPage([],3);assert.deepEqual(empty.items,[]);
  assert.deepEqual([empty.page,empty.pages,empty.total,empty.first,empty.last],[1,1,0,0,0]);
});
