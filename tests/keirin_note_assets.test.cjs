'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
test('the combined guide preserves the existing BOAT source-free reader',()=>{
  const app=fs.readFileSync(require.resolve('../web/app.js'),'utf8');
  const boundary='\n"use strict";\n/* PR #62 page shell';
  assert.ok(app.includes(boundary));
  const holder={exports:{}};
  vm.runInNewContext(app.split(boundary)[0],{module:holder,URL});
  assert.equal(holder.exports.DAY,'2026-11-12');
  assert.ok(holder.exports.EVIDENCE.endsWith('/43339230921'));
});
