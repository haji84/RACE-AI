'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');

test('UI exposes exactly the existing Python catalog, including missing model families', () => {
  const file=path.resolve(__dirname,'../web/existing-model-catalog.js');
  assert.ok(fs.existsSync(file),'all sixteen existing families must be visible in the product UI');
  const ui=require(file).models.map(({model_id,applicable_sports,required_input})=>({model_id,applicable_sports,required_input}));
  const python=JSON.parse(execFileSync('python3',['-c','import json; from race_ai.existing_model_coverage import catalog; print(json.dumps(catalog()))'],{cwd:path.resolve(__dirname,'..'),encoding:'utf8'}));
  assert.deepEqual(ui,python);
  assert.equal(ui.length,16);
  assert.equal(new Set(ui.map(m=>m.model_id)).size,16);
  assert.deepEqual(Object.fromEntries(['boat','keirin','autorace','horse'].map(s=>[s,ui.filter(m=>m.applicable_sports.includes(s)).length])),{boat:15,keirin:5,autorace:6,horse:5});
});
