'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');

test('UI exposes the active Python catalog without the retired seller', () => {
  const file=path.resolve(__dirname,'../web/existing-model-catalog.js');
  assert.ok(fs.existsSync(file),'all fifteen active families must be visible in the product UI');
  const ui=require(file).models.map(({model_id,applicable_sports,required_input})=>({model_id,applicable_sports,required_input}));
  const python=JSON.parse(execFileSync('python3',['-c','import json; from race_ai.existing_model_coverage import active_catalog; print(json.dumps(active_catalog()))'],{cwd:path.resolve(__dirname,'..'),encoding:'utf8'}));
  assert.deepEqual(ui,python);
  assert.equal(ui.length,15);
  assert.equal(new Set(ui.map(m=>m.model_id)).size,15);
  assert.deepEqual(Object.fromEntries(['boat','keirin','autorace','horse'].map(s=>[s,ui.filter(m=>m.applicable_sports.includes(s)).length])),{boat:14,keirin:5,autorace:6,horse:5});
});


test('retired-only archives do not surface as current forecasts or extra models', () => {
  const catalog=require('../web/existing-model-catalog.js');
  const ui=require('../web/ui-model.js');
  const row={race_id:'20300115-18-08',sport:'boat',scope:'research',
    event_date_jst:'2030-01-15',cutoff_at:'2030-01-15T14:00:00+09:00',
    prediction:{model_id:'seller-shadow-v1-20261104',stage:'P0',ordered_top8:[[1,2,3]]},
    comparison_predictions:[],dispatch_slots:[{model_id:'seller-shadow-v1-20261104',status:'INPUT_MISSING'}]};
  const before=structuredClone(row),display=catalog.forDisplay(row);
  assert.deepEqual(row,before,'archival and budget inputs are never rewritten');
  assert.equal(display.prediction,null);
  assert.deepEqual(display.dispatch_slots,[]);
  assert.deepEqual(ui.modelCoverage([display],catalog.models,{sport:'boat'}).additional_model_ids,[]);
  assert.equal(ui.filterRaces([display],{sport:'boat',allDates:true,forecastOnly:true}).length,0);
  assert.equal(ui.raceInformation(display).find(value=>value.key==='outlook').available,false);
});

test('a retained active comparison is available without editing the original primary', () => {
  const catalog=require('../web/existing-model-catalog.js');
  const active={model_id:'boat-observed-pairwise-factor-v1',stage:'P0',ordered_top8:[[1,3,2]]};
  const row={prediction:{model_id:'seller-shadow-v1-20261104'},
    comparison_predictions:[active],dispatch_slots:[{model_id:active.model_id,status:'ORIGINAL_REUSED'}]};
  const before=structuredClone(row),display=catalog.forDisplay(row);
  assert.equal(display.prediction,active);
  assert.deepEqual(row,before);
  assert.equal(display.dispatch_slots.length,1);
});
