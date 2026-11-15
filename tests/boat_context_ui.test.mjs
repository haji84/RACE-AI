import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, existsSync} from 'node:fs';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
const {chromium} = require('playwright');
const web = fileURLToPath(new URL('../web/', import.meta.url));
const fixture = () => {
  const data = JSON.parse(readFileSync(path.join(web, 'data/example-synthetic-forecast-audit.json')));
  data.records = data.records.filter(row => row.sport === 'boat');
  const row = data.records[0];
  row.event_date_jst = '2030-01-01';
  row.participants = [{number:1, registration_no:'4201', name:'合成選手', display_time:6.91}];
  return data;
};

async function withPreview(data, run) {
  const browser = await chromium.launch({headless:true, args:['--no-sandbox'],
    ...(process.env.CHROMIUM_PATH ? {executablePath:process.env.CHROMIUM_PATH} :
      existsSync('/usr/bin/chromium') ? {executablePath:'/usr/bin/chromium'} : {})});
  try {
    const page = await browser.newPage({viewport:{width:390, height:844}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      assert.equal(url.origin, 'https://boat-context.test', 'preview does not request external media or sources');
      const name = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
      const file = path.resolve(web, name);
      if (!file.startsWith(web) || !existsSync(file)) return route.fulfill({status:404, body:''});
      const contentType = {'.html':'text/html', '.js':'text/javascript', '.css':'text/css'}[path.extname(file)];
      await route.fulfill({status:200, contentType, body:readFileSync(file)});
    });
    await page.clock.install({time:new Date('2030-01-01T00:30:00Z')});
    await page.goto('https://boat-context.test/');
    await page.locator('#race-file').setInputFiles({name:'synthetic-context.json', mimeType:'application/json', buffer:Buffer.from(JSON.stringify(data))});
    await page.waitForFunction(() => document.querySelector('#file-message').textContent.includes('端末内で読み込みました'));
    await page.locator('#page-home [data-open-race]').first().click();
    await page.locator('[data-detail-tab="preview"]').click();
    for (const summary of await page.locator('.context-source-details > summary').all()) await summary.click();
    await run(page);
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
}

function contextFixture(row) {
  return {
    forecast_inputs_used:false,
    beforeinfo:{schema:'RACE_AI_BOAT_OBSERVATION_CONTEXT_V1', kind:'beforeinfo', race_id:row.race_id,
      status:'PARSED', roster_binding_status:'VERIFIED', forecast_ready:false,
      source_cutoff_at:'2030-01-01T10:00:00+09:00',
      cutoff_eligibility:{captured_before_cutoff:true, pre_cutoff_eligible:true, reason:'CAPTURED_BEFORE_CUTOFF'},
      source:{source_url:'https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno=1&jcd=01&hd=20300101',
        sha256:'a'.repeat(64), captured_at:'2030-01-01T09:21:00+09:00', published_at:null,
        published_time_raw:null, freshness_status:'UNKNOWN'},
      participants:[{lane:1, registration_number:'4201', name:'合成選手', bodyweight_kg:52.3, tilt:0,
        adjustmentweight_kg:null, display_time:null, propeller_change_marker:null,
        propeller_change_status:'NOT_PUBLISHED', parts_replacement:null, exhibition_st:0.04,
        exhibition_st_status:'F', exhibition_st_raw:'F.04', exhibition_source_position_number:2,
        exhibition_course:null}, {lane:2, registration_number:'4202', name:'合成選手2', bodyweight_kg:null,
        tilt:null, adjustmentweight_kg:0, display_time:6.74, propeller_change_marker:'新',
        propeller_change_status:'REPORTED_NEW', parts_replacement:['リング×２'], exhibition_st:null,
        exhibition_st_status:'NOT_PUBLISHED', exhibition_st_raw:null, exhibition_source_position_number:null,
        exhibition_course:null}],
      weather:{air_temperature_c:17.5, water_temperature_c:19, wind_speed_mps:0, wave_height_cm:2,
        wind_direction_source_code:17, weather_label:'晴', reported_race_no:6,
        source_reported_local_time:'9:15現在', reported_at:null, freshness_status:'UNKNOWN_SOURCE_TIME_HAS_NO_DATE'}},
    pitreport:null, entry_history:null
  };
}

function liveFixture() {
  const data=fixture(),row=data.records[0];row.race_id='20300101-01-01';row.race_no=1;
  row.participants=Array.from({length:6},(_,i)=>({number:i+1,registration_no:String(4201+i),name:'合成選手'+(i+1)}));
  delete row.weather;delete row.weather_preview;
  const context=contextFixture(row);
  context.schema='RACE_AI_BOAT_SUPPLEMENTAL_CONTEXT_V1';context.race_id=row.race_id;context.cutoff_at=context.beforeinfo.source_cutoff_at;
  context.roster=row.participants.map(p=>({lane:p.number,registration_number:p.registration_no}));
  context.beforeinfo.body_identity_verified=true;
  const template=context.beforeinfo.participants[0];
  context.beforeinfo.participants=row.participants.map((p,i)=>({...template,lane:p.number,registration_number:p.registration_no,name:p.name,display_time:6.71+i/100,exhibition_st_raw:i?'.12':'F.04',exhibition_st_status:i?'OK':'F'}));
  row.live_boat_observation={schema:'RACE_AI_LIVE_BOAT_OBSERVATION_V1',state:'READY',checked_at:'2030-01-01T09:22:00+09:00',context,forecast_inputs_used:false};
  return data;
}
function registeredLiveFixture() {
  const data=liveFixture(),row=data.records[0];data.dataset_status='REAL_REPORTED';row.scope='research';row.source_provenance='INVENTED_CONTEXT_TEST_ONLY';
  const identities=[['4320','峰竜太'],['3415','松井繁'],['3897','白井英治'],['3941','池田浩二'],['4238','毒島誠'],['4444','桐生順平']];
  row.participants=identities.map(([registration_no,name],i)=>({number:i+1,registration_no,name}));
  const context=row.live_boat_observation.context;
  context.roster=row.participants.map(p=>({lane:p.number,registration_number:p.registration_no}));
  context.beforeinfo.participants=row.participants.map((p,i)=>({...context.beforeinfo.participants[i],lane:p.number,registration_number:p.registration_no,name:p.name}));
  return data;
}

test('live official facts lead the pre-race tab when the original forecast has no exhibition',async()=>{
  const data=liveFixture(),tickets=structuredClone(data.records[0].prediction.ordered_top8);
  await withPreview(data,async page=>{
    for(const width of [320,390,1440]){
      await page.setViewportSize({width,height:1000});
      const panel=page.locator('#live-beforeinfo');assert.equal(await panel.count(),1);
      const text=await panel.innerText();assert.match(text,/6\.71/);assert.match(text,/F\.04/);assert.match(text,/09:21/);assert.match(text,/0 m\/s/);
      assert.doesNotMatch(await page.locator('#detail-tab-content').innerText(),/保存予想原本の気象・直前情報は未取得|元ページSHA/);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    }
    await page.locator('[data-detail-tab="outlook"]').click();
    const rendered=await page.locator('#detail-tab-content .saved-ticket .combo').evaluateAll(nodes=>nodes.map(n=>[...n.querySelectorAll('.lane')].map(e=>Number(e.textContent))));
    assert.deepEqual(rendered,tickets);
  });
});

test('live unpublished exhibition shows weather and the publication state instead of a total missing notice',async()=>{
  const data=liveFixture(),live=data.records[0].live_boat_observation;live.state='AWAITING_EXHIBITION';
  for(const p of live.context.beforeinfo.participants){p.display_time=null;p.exhibition_st=null;p.exhibition_st_raw=null;p.exhibition_st_status='NOT_PUBLISHED';}
  await withPreview(data,async page=>{
    const text=await page.locator('#live-beforeinfo').innerText();assert.match(text,/展示発表待ち/);assert.match(text,/17\.5/);assert.match(text,/0 m\/s/);
  });
});

test('a live context for a different registered racer never reaches the visible preview',async()=>{
  const data=liveFixture();data.records[0].live_boat_observation.context.beforeinfo.participants[0].registration_number='4999';
  await withPreview(data,async page=>{assert.equal(await page.locator('#live-beforeinfo').count(),0);assert.doesNotMatch(await page.locator('#detail-tab-content').innerText(),/6\.71|F\.04/);});
});

test('course scenarios use live exhibition only when captured before both saved and official cutoffs',async()=>{
  for(const [officialLater,early] of [[false,false],[true,false],[false,true]]){
    const data=registeredLiveFixture(),row=data.records[0];row.cutoff_at='2030-01-01T10:00:00+09:00';
    const live=row.live_boat_observation,context=live.context,page=context.beforeinfo;
    live.checked_at='2030-01-01T10:06:00+09:00';context.cutoff_at=page.source_cutoff_at=officialLater?'2030-01-01T10:20:00+09:00':row.cutoff_at;
    page.source.captured_at=early?'2030-01-01T09:21:00+09:00':'2030-01-01T10:05:00+09:00';page.cutoff_eligibility={captured_before_cutoff:officialLater||early,pre_cutoff_eligible:officialLater||early};
    context.roster=row.participants.map(p=>({lane:p.number,registration_number:p.registration_no}));
    page.participants=row.participants.map((p,i)=>({...page.participants[i],lane:p.number,registration_number:p.registration_no,name:p.name,exhibition_course:[2,1,3,4,5,6][i]}));
    await withPreview(data,async browser=>{
      await browser.clock.setFixedTime(new Date('2030-01-01T01:10:00Z'));
      assert.match(await browser.locator('#live-beforeinfo').innerText(),early?/09:21/:/10:05/);
      await browser.locator('#live-beforeinfo [data-open-participant="4320"]').click();
      const scenario=await browser.locator('.reference-scenario').first().innerText();
      if(early)assert.match(scenario,/展示進入の並びを参照/);else assert.doesNotMatch(scenario,/展示進入の並びを参照/);
      assert.equal(await browser.locator('[data-study-course][aria-pressed="true"]').first().getAttribute('data-study-course'),early?'2':'1');
      assert.match(await browser.locator('#profile-supplement').innerText(),early?/09:21/:/10:05/);
    });
  }
});

test('live exhibition preserves independently captured comments and their original source time',async()=>{
  const data=registeredLiveFixture(),row=data.records[0],legacy=structuredClone(row.live_boat_observation.context);
  legacy.cutoff_at='2030-01-01T09:00:00+09:00';legacy.beforeinfo=null;
  const page=structuredClone(row.live_boat_observation.context.beforeinfo);
  Object.assign(page,{kind:'pitreport',source_cutoff_at:legacy.cutoff_at,cutoff_eligibility:{captured_before_cutoff:false,pre_cutoff_eligible:false},reporter:'架空記者'});
  page.source={...page.source,source_url:page.source.source_url.replace('/beforeinfo?','/pitreport?'),captured_at:'2030-01-01T09:10:00+09:00',sha256:'c'.repeat(64)};
  page.participants=[{lane:1,registration_number:'4320',name:'峰竜太',comment:'架空の保存済みコメント',comment_status:'REPORTED',comment_attribution:{racer_name:'峰竜太',reporter:'架空記者',kind:'OFFICIAL_PIT_REPORT'}}];
  legacy.pitreport=page;row.boat_observation_context=legacy;
  await withPreview(data,async browser=>{
    await browser.locator('#live-beforeinfo [data-open-participant="4320"]').click();
    const text=await browser.locator('#profile-supplement').innerText();assert.match(text,/架空の保存済みコメント/);assert.match(text,/09:10/);assert.match(text,/締切後/);assert.match(text,/09:21/);
    await browser.locator('#participant-dialog').evaluate(dialog=>dialog.close());
    await browser.locator('[data-page="research"]').filter({visible:true}).first().click();
    const audit=browser.locator('#research-race-audit');assert.match(await audit.innerText(),/架空の保存済みコメント/);
  });
});

test('preview renders separately captured BOAT context without changing saved forecast order', async () => {
  const data = fixture(), row = data.records[0];
  row.boat_observation_context = contextFixture(row);
  await withPreview(data, async page => {
    const supplemental = page.locator('#boat-observation-context');
    assert.equal(await supplemental.count(), 1, 'optional context appears in the preview tab');
    const rendered = await supplemental.innerText();
    assert.match(rendered, /補足観測/);
    assert.ok(rendered.includes('a'.repeat(64)), 'own source digest is visible');
    assert.match(rendered, /09:21/);
    assert.match(rendered, /締切前に取得（入力への反映は別確認）/);
    assert.match(await page.locator('#boat-context-beforeinfo').innerText(), /10:00/,
      'official page cutoff remains visible beside its own capture time');
    assert.match(rendered, /52\.3/);
    assert.match(rendered, /未取得/);
    assert.match(rendered, /未検証/);
    assert.match(await page.locator('#detail-tab-content > .empty-state h3').innerText(), /保存予想原本/,
      'missing original weather must not claim the separately captured weather is missing');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.locator('[data-detail-tab="outlook"]').click();
    const tickets = await page.locator('#detail-tab-content .saved-ticket .combo').evaluateAll(nodes =>
      nodes.map(n => [...n.querySelectorAll('.lane')].map(lane => Number(lane.textContent))));
    assert.deepEqual(tickets, row.prediction.ordered_top8);
  });
});

test('preview preserves zero, ST flags, comment attribution and observed history denominators', async () => {
  const data = fixture(), row = data.records[0], context = contextFixture(row);
  context.pitreport = {schema:'RACE_AI_BOAT_OBSERVATION_CONTEXT_V1', kind:'pitreport', race_id:row.race_id,
    status:'PARSED', roster_binding_status:'VERIFIED', forecast_ready:false,
    source_cutoff_at:'2030-01-01T09:20:00+09:00', captured_before_cutoff:false,
    source:{source_url:'https://www.boatrace.jp/owpc/pc/race/pitreport?rno=1&jcd=01&hd=20300101',
      sha256:'b'.repeat(64), captured_at:'2030-01-01T09:22:00+09:00', published_at:null,
      published_time_raw:null, freshness_status:'UNKNOWN'}, reporter:'合成記者',
    participants:[{lane:1, registration_number:'4201', name:'合成選手', comment:'出足はまだ分からない。<img src=x onerror="alert(1)">',
      comment_status:'REPORTED', comment_attribution:{racer_name:'合成選手', reporter:'合成記者', kind:'OFFICIAL_PIT_REPORT'}}]};
  const sample = {starts:2, wins:1, top2:1, top3:1, denominator:2, win_rate:0.5, top2_rate:0.5, top3_rate:0.5};
  const noSample = {starts:0, wins:0, top2:0, top3:0, denominator:0, win_rate:null, top2_rate:null, top3_rate:null};
  context.entry_history = {profiles:[{racer_id:'4201', as_of:'2030-01-01T09:20:00+09:00', sample_races:4,
    conditional_buckets:{inward:sample, outer_to_inner3:noSample, displaced:sample,
      crossed_by_outer_frame:sample, any_inward_mover_present:sample},
    actual_course_when_inward_mover_present:{'1':sample, '2':noSample, '3':noSample, '4':noSample, '5':noSample, '6':noSample},
    source_proofs:[{date_jst:'2029-12-31', B:{source_url:'https://www.boatrace.jp/b.zip', source_sha256:'c'.repeat(64),
      extracted_text_sha256:'d'.repeat(64), captured_at:'2029-12-31T09:00:00+09:00'},
      K:{source_url:'https://www.boatrace.jp/k.zip', source_sha256:'e'.repeat(64),
        extracted_text_sha256:'f'.repeat(64), captured_at:'2029-12-31T17:00:00+09:00'}}]}]};
  row.boat_observation_context = context;
  await withPreview(data, async page => {
    const supplemental = page.locator('#boat-observation-context');
    const rendered = await supplemental.innerText();
    assert.match(rendered, /F\.04/);
    assert.match(rendered, /リング×２/);
    assert.match(rendered, /出足はまだ分からない。<img/);
    assert.match(rendered, /合成記者/);
    assert.equal(await supplemental.locator('img').count(), 0, 'official comment is literal text');
    assert.ok(rendered.includes('b'.repeat(64)), 'comment capture has its own digest');
    assert.match(await page.locator('#boat-context-pitreport').innerText(), /締切後に取得（保存予想への後付けなし）/,
      'a top-level false capture flag is displayed as late');
    assert.match(rendered, /50\.0%/);
    assert.match(rendered, /内へ入った/);
    assert.match(rendered, /外枠艇が内側/);
    const metricRows = await page.locator('#boat-context-beforeinfo tbody tr').allTextContents();
    assert.match(metricRows[0], /52\.3/);
    const values = await page.locator('#boat-context-beforeinfo tbody tr').first().locator('td').allTextContents();
    assert.ok(values.includes('0'), 'reported zero tilt remains a zero');
    assert.ok(values.includes('未取得'), 'missing adjustment weight remains missing');
    const historyRows = await page.locator('#boat-context-entry-history tbody tr').allTextContents();
    assert.ok(historyRows.some(value => value.includes('外枠から1〜3コース') && value.includes('未取得')),
      'zero-sample descriptive rate is not rendered as a measured zero percent');
    assert.match(rendered, /ターン.*未取得/s);
    assert.match(rendered, /出足.*未取得/s);
    assert.match(rendered, /行き足.*未取得/s);
    assert.match(rendered, /直線.*未取得/s);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await supplemental.locator('details').evaluateAll(nodes => nodes.forEach(n => n.open = true));
    const expanded = await supplemental.innerText();
    assert.ok(expanded.includes('e'.repeat(64)), 'historical result source digest is inspectable');
    assert.ok(expanded.includes('f'.repeat(64)), 'extracted historical text digest is inspectable');
  });
});

test('late supplemental capture stays visibly late when nested cutoff eligibility is false', async () => {
  const data = fixture(), row = data.records[0], context = contextFixture(row);
  context.beforeinfo.source_cutoff_at = '2030-01-01T17:46:00+09:00';
  context.beforeinfo.source.captured_at = '2030-01-01T18:10:00+09:00';
  context.beforeinfo.captured_before_cutoff = true;
  context.beforeinfo.cutoff_eligibility = {captured_before_cutoff:false, pre_cutoff_eligible:false,
    reason:'CAPTURED_AT_OR_AFTER_CUTOFF'};
  row.boat_observation_context = context;
  await withPreview(data, async page => {
    const observed = await page.locator('#boat-context-beforeinfo').innerText();
    assert.match(observed, /締切後に取得（保存予想への後付けなし）/,
      'nested false remains authoritative over a stale top-level true flag');
    assert.match(observed, /17:46/);
    assert.match(observed, /18:10/);
    assert.doesNotMatch(observed, /締切前に取得/);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  });
});

test('supplement without an eligibility flag keeps cutoff availability unconfirmed', async () => {
  const data = fixture(), row = data.records[0], context = contextFixture(row);
  delete context.beforeinfo.cutoff_eligibility;
  row.boat_observation_context = context;
  await withPreview(data, async page => {
    const availability = page.locator('#boat-context-beforeinfo dt').filter({hasText:'締切と取得の関係'});
    assert.equal(await availability.count(), 1, 'cutoff availability is a visible source fact');
    assert.equal(await availability.evaluate(n => n.nextElementSibling.textContent), '未確認');
  });
});

test('Python-parsed official-structure context renders its integer wind code and exhibition data', async () => {
  const parsed = JSON.parse(execFileSync('python', ['-c', `
import json
from race_ai.boat_observation_context import parse_beforeinfo
from tests.test_boat_observation_context import frame, before_table, starts, weather, url, ROSTER
raw = frame(before_table(display="6.82", tilt="-0.5") + starts(populated=True, flying=True) + weather())
raw = raw.replace(b"20300401", b"20300101")
result = parse_beforeinfo(raw, source_url=url().replace("20300401", "20300101"),
    captured_at="2030-01-01T09:21:00+09:00", expected_race_id="20300101-12-12", roster=ROSTER)
print(json.dumps(result, ensure_ascii=False, allow_nan=False))
`], {cwd:path.resolve(web, '..'), encoding:'utf8'}));
  assert.equal(parsed.status, 'PARSED');
  assert.equal(parsed.weather.wind_direction_source_code, 17);
  const data = fixture(), row = data.records[0];
  row.race_id = parsed.race_id;
  row.race_no = 12;
  row.participants = parsed.participants.map(person => ({number:person.lane,
    registration_no:person.registration_number, name:person.name}));
  row.boat_observation_context = contextFixture(row);
  row.boat_observation_context.beforeinfo = parsed;
  await withPreview(data, async page => {
    const observed = page.locator('#boat-context-beforeinfo');
    assert.equal(await observed.count(), 1, 'real parser JSON passes the UI validation gate');
    assert.match(await observed.innerText(), /6\.82/);
    assert.match(await observed.innerText(), /F\.03/);
    const direction = observed.locator('dt').filter({hasText:'風向の公式表示コード'});
    assert.equal(await direction.evaluate(n => n.nextElementSibling.textContent), '17');
    assert.doesNotMatch(await page.locator('#boat-observation-context').innerText(), /補足観測を照合できません/);
  });
});

async function assertRejectedSupplement(data) {
  await withPreview(data, async page => {
    assert.equal(await page.locator('#boat-observation-context').count(), 1,
      'malformed supplemental input still renders a bounded rejection notice');
    assert.match(await page.locator('#boat-observation-context').innerText(), /補足観測を照合できません/);
    assert.doesNotMatch(await page.locator('#detail-tab-content').innerText(), /9900(?:\.0)?%/);
    assert.match(await page.locator('#detail-tab-content').innerText(), /6\.91/,
      'saved original preview remains usable after supplemental rejection');
    await page.locator('[data-detail-tab="outlook"]').click();
    const tickets = await page.locator('#detail-tab-content .saved-ticket .combo').evaluateAll(nodes =>
      nodes.map(n => [...n.querySelectorAll('.lane')].map(lane => Number(lane.textContent))));
    assert.deepEqual(tickets, data.records[0].prediction.ordered_top8,
      'supplemental validation cannot discard or replace the saved forecast');
  });
}

test('malformed supplemental participant is rejected while the original preview and forecast remain usable', async () => {
  const data = fixture(), row = data.records[0];
  row.boat_observation_context = contextFixture(row);
  row.boat_observation_context.beforeinfo.participants = [null];
  await assertRejectedSupplement(data);
});

test('claimed pre-cutoff capture cannot override earlier official or wrapper cutoff timestamps', async () => {
  for (const earlierCutoff of ['official', 'wrapper']) {
    const data = fixture(), row = data.records[0];
    row.boat_observation_context = contextFixture(row);
    if (earlierCutoff === 'official') row.boat_observation_context.beforeinfo.source_cutoff_at = '2030-01-01T09:20:00+09:00';
    else row.boat_observation_context.cutoff_at = '2030-01-01T09:20:00+09:00';
    await assertRejectedSupplement(data);
  }
});

function historicalFixture() {
  const data = fixture(), row = data.records[0];
  row.boat_observation_context = contextFixture(row);
  const bucket = () => ({starts:1, wins:0, top2:0, top3:0, denominator:1, win_rate:0, top2_rate:0, top3_rate:0});
  row.boat_observation_context.entry_history = {profiles:[{racer_id:'4201',
    as_of:'2030-01-01T09:20:00+09:00', sample_races:1,
    conditional_buckets:{inward:bucket(), outer_to_inner3:bucket(), displaced:bucket(),
      crossed_by_outer_frame:bucket(), any_inward_mover_present:bucket()},
    source_proofs:[{date_jst:'2029-12-31', B:{source_url:'https://www.boatrace.jp/b.zip',
      source_sha256:'c'.repeat(64), extracted_text_sha256:'d'.repeat(64), captured_at:'2029-12-31T09:00:00+09:00'},
      K:{source_url:'https://www.boatrace.jp/k.zip', source_sha256:'e'.repeat(64),
        extracted_text_sha256:'f'.repeat(64), captured_at:'2029-12-31T17:00:00+09:00'}}]}]};
  return data;
}

test('forged historical rate is rejected instead of displaying an impossible observed percentage', async () => {
  const data = historicalFixture();
  data.records[0].boat_observation_context.entry_history.profiles[0].conditional_buckets.inward.top3_rate = 99;
  await assertRejectedSupplement(data);
});

test('inconsistent historical finish counts are rejected even when their provided rates agree', async () => {
  const data = historicalFixture();
  const bucket = data.records[0].boat_observation_context.entry_history.profiles[0].conditional_buckets.inward;
  bucket.wins = 1;
  bucket.win_rate = 1;
  await assertRejectedSupplement(data);
});

test('positive historical sample with a null source proof cannot render as observed evidence', async () => {
  const data = historicalFixture();
  data.records[0].boat_observation_context.entry_history.profiles[0].source_proofs = [null];
  await assertRejectedSupplement(data);
});

test('preview without supplemental context keeps the saved original values', async () => {
  await withPreview(fixture(), async page => {
    assert.equal(await page.locator('#boat-observation-context').count(), 0);
    assert.match(await page.locator('#detail-tab-content').innerText(), /6\.91/);
  });
});
