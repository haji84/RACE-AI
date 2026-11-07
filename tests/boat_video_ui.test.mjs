import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, existsSync} from 'node:fs';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
const filename = fileURLToPath(new URL('../web/ui-model.js', import.meta.url));
const V = require(filename).boatVideoView;
const phases = ['turn', 'exit', 'runup', 'straight'];
function fixture() {
  const row = {sport:'boat', scope:'research', race_id:'20300401-01-01',
    event_date_jst:'2030-04-01', cutoff_at:'2030-04-01T12:00:00+09:00',
    participants:Array.from({length:6}, (_, i) => ({number:i+1, registration_no:String(4201+i)}))};
  const missing = () => ({status:'MISSING', reason:'PHASE_NOT_OBSERVED', metrics:[],
    sample_count:0, t_start:null, t_end:null, window_source:'AUTOMATIC_CANDIDATE',
    validation_status:'UNVALIDATED', identity_validated:false});
  const report = {schema_version:'RACE_AI_BOAT_VIDEO_EVALUATION_V1', report_sha256:'a'.repeat(64),
    race_id:row.race_id, cutoff_at:row.cutoff_at,
    roster:row.participants.map(p => ({lane:p.number, registration_number:p.registration_no})),
    source:{kind:'OWNER_LOCAL', identity_status:'OWNER_DECLARED', media_sha256:'b'.repeat(64),
      captured_at:'2030-04-01T11:40:00+09:00'},
    analysis_started_at:'2030-04-01T11:50:00+09:00', analysis_completed_at:'2030-04-01T11:50:02+09:00',
    analysis_parameters:{}, media:{sha256:'b'.repeat(64), width:320, height:240,
      duration_seconds:1, timeline_source:'MEDIA_PTS'},
    tracking:{schema_version:'RACE_AI_BOAT_VIDEO_TRACKS_V1', media_sha256:'b'.repeat(64),
      width:320, height:240, duration_seconds:1, timeline_source:'MEDIA_PTS', media_pts_origin_seconds:2.5,
      coordinate_space:'REFERENCE_IMAGE_PX', model_eligible:false, validation_status:'UNVALIDATED',
      tracks:Array.from({length:6}, (_, i) => ({lane:i+1, identity_status:'COLOR_CANDIDATE', samples:[]})),
      quality:{flags:['EXPERIMENTAL_TEST'], decoded_frame_count:10, camera_estimates:[], position_error_scope:'UNCERTIFIED'}},
    measurements:{schema_version:'RACE_AI_BOAT_VIDEO_MEASUREMENTS_V1', coordinate_space:'REFERENCE_IMAGE_PX',
      time_basis:'MEDIA_TIMELINE_SECONDS', model_eligible:false, validation_status:'UNVALIDATED',
      identity_validated:false, candidate_measurements:true, calibration_status:'IMAGE_COORDINATES_ONLY',
      physical_velocity:'NOT_ESTABLISHED', lanes:Array.from({length:6}, (_, i) => ({lane:i+1,
        identity_status:'COLOR_CANDIDATE', identity_validated:false,
        phases:Object.fromEntries(phases.map(name => [name, missing()]))}))},
    pre_cutoff_available:true, model_eligible:false, validation_status:'UNVALIDATED', dataset_status:'REAL_REPORTED'};
  report.tracking.tracks[0].samples = Array.from({length:6}, (_, i) => ({t:i/10, frame_index:i,
    scene:0, valid:true, x:i, y:0, position_error:0.1}));
  report.measurements.lanes[0].phases.straight = {status:'MEASURED', reason:null, sample_count:6,
    t_start:0, t_end:0.5, scene:0, window_source:'AUTOMATIC_CANDIDATE',
    validation_status:'UNVALIDATED', identity_validated:false,
    measurement_scope:'SAMPLED_CHORDS_AND_MEDIA_TIMELINE_ONLY', instantaneous_acceleration:'NOT_ESTIMATED',
    metrics:[{name:'window_duration', value:0.5, unit:'s'}, {name:'mean_interval_speed', value:10, unit:'px/s'},
      {name:'max_lateral_deviation', value:0, unit:'px'}, {name:'rms_lateral_deviation', value:0, unit:'px'}]};
  row.boat_video_evaluations = [report];
  return {row, report};
}

test('accepts separate image measurements without mutating saved row or claiming authentication', () => {
  assert.equal(typeof V.validateReport, 'function', 'experimental report validator is available');
  const {row, report} = fixture(), original = JSON.stringify(row);
  assert.equal(V.validateReport(report, row), true);
  assert.equal(JSON.stringify(row), original);
});

test('accepts six number and temporal candidates without promoting identity or eligibility', () => {
  const {row, report}=fixture();
  report.tracking.tracks.forEach(track => track.identity_status='NUMBER_TEMPORAL_CANDIDATE');
  report.measurements.lanes.forEach(lane => lane.identity_status='NUMBER_TEMPORAL_CANDIDATE');
  const original=JSON.stringify(row);
  assert.equal(V.validateReport(report,row),true);
  assert.equal(JSON.stringify(row),original);
  for (const mutate of [r => r.measurements.lanes[0].identity_status='NUMBER_COLOR_AGREEMENT',
    r => r.measurements.lanes[0].identity_validated=true,
    r => r.tracking.identity_validated=true, r => r.model_eligible=true]) {
    const value=structuredClone(report); mutate(value);
    assert.equal(V.validateReport(value,row),false);
  }
});

test('binds exact six lane registrations and saved cutoffs before allowing optional evidence', () => {
  assert.equal(typeof V.validateReport, 'function');
  for (const mutate of [r => r.participants.pop(), r => r.participants[0].registration_no='9999',
    r => r.participants[1].number=1, r => r.race_id='20300401-01-02',
    r => r.cutoff_at='2030-04-01T12:01:00+09:00',
    r => r.saved_cutoff_variants=['2030-04-01T12:01:00+09:00']]) {
    const {row, report} = fixture(); mutate(row);
    assert.equal(V.validateReport(report, row), false);
  }
});

test('rejects unzoned, impossible, reordered and falsely claimed cutoff clocks', () => {
  assert.equal(typeof V.validateReport, 'function');
  for (const mutate of [r => r.source.captured_at='2030-04-01T11:40:00',
    r => r.source.captured_at='2030-04-01T11:40:00.0000001+09:00',
    r => r.analysis_started_at='2030-02-30T11:50:00+09:00',
    r => r.analysis_started_at='2030-04-01T11:30:00+09:00',
    r => r.analysis_completed_at='2030-04-01T11:49:00+09:00',
    r => r.analysis_completed_at=r.cutoff_at, r => r.pre_cutoff_available=false]) {
    const {row, report} = fixture(); mutate(report);
    assert.equal(V.validateReport(report, row), false);
  }
  const {row, report} = fixture(); report.analysis_completed_at=report.cutoff_at;
  report.pre_cutoff_available=false;
  assert.equal(V.validateReport(report, row), true, 'late evidence remains displayable with late label');
});

test('synthetic reports cannot enter real views and official source metadata cannot smuggle media URLs', () => {
  assert.equal(typeof V.validateReport, 'function');
  const {row, report} = fixture(); report.source.kind='SYNTHETIC_TEST';
  report.source.identity_status='SYNTHETIC'; report.dataset_status='SYNTHETIC_ONLY';
  assert.equal(V.validateReport(report, row), false);
  row.scope='synthetic'; assert.equal(V.validateReport(report, row), true);
  for (const url of ['https://media.example/signed.mp4?token=secret',
    'https://www.boatrace.jp/owpc/pc/race/beforeinfo?hd=20300401&jcd=02&rno=1',
    'https://user:secret@www.boatrace.jp/owpc/pc/race/beforeinfo?hd=20300401&jcd=01&rno=1',
    'https://www.boatrace.jp/owpc/pc/race/beforeinfo?hd=20300401&jcd=01&rno=1&token=secret']) {
    const value=fixture(); value.report.source.public_page_url=url;
    assert.equal(V.validateReport(value.report,value.row),false);
  }
  const value=fixture(); value.report.source.kind='OFFICIAL_BROWSER_CAPTURE';
  value.report.source.identity_status='SOURCE_METADATA_LINKED'; value.report.source.source_metadata_sha256='c'.repeat(64);
  value.report.source.public_page_url='https://www.boatrace.jp/owpc/pc/race/beforeinfo?hd=20300401&jcd=01&rno=1';
  assert.equal(V.validateReport(value.report,value.row),true);
});

test('rejects promoted, physical, nonfinite and internally inconsistent measurement evidence safely', () => {
  assert.equal(typeof V.validateReport, 'function');
  for (const mutate of [r => r.model_eligible=true, r => r.validation_status='VALIDATED',
    r => r.measurements.coordinate_space='WATER_PLANE_METRES',
    r => r.measurements.lanes[0].identity_validated=true,
    r => r.measurements.lanes[0].phases.straight.metrics[1].value=Infinity,
    r => r.measurements.lanes[0].phases.straight.metrics[1].unit='m/s',
    r => r.measurements.lanes[0].phases.straight.metrics[1].name='verified_score',
    r => r.measurements.lanes[0].phases.straight.t_end=2,
    r => r.measurements.lanes[0].phases.straight.sample_count=8,
    r => r.tracking.tracks[0].samples[0].x=null,
    r => r.tracking.media_sha256='f'.repeat(64), r => r.media.width=true,
    r => r.measurements.lanes[1].phases.turn.metrics=[{name:'window_duration', value:0,unit:'s'}]]) {
    const {row, report}=fixture(); mutate(report);
    assert.equal(V.validateReport(report,row),false);
  }
  for (const bad of [null, {}, [], 'untrusted', {get schema_version() {throw new Error('bad input');}}])
    assert.equal(V.validateReport(bad,fixture().row),false);
});

test('next-day replay remains post-cutoff and malformed start-crossing evidence is rejected', () => {
  const {row,report}=fixture();
  report.source.captured_at='2030-04-02T11:40:00+09:00';
  report.analysis_started_at='2030-04-02T11:50:00+09:00';
  report.analysis_completed_at='2030-04-02T11:50:02+09:00';
  report.pre_cutoff_available=false;
  assert.equal(V.validateReport(report,row),true);
  for (const bad of ['untrusted',[-1,5],[5,4],[4,999]]) {
    const value=fixture();
    value.report.measurements.lanes[0].phases.straight.gate_crossing_frame_indices=bad;
    assert.equal(V.validateReport(value.report,value.row),false,'start-crossing evidence belongs only to observed runup brackets');
  }
});

test('clock ordering and cutoff binding retain microseconds from Python reports', () => {
  let value=fixture();
  value.report.source.captured_at='2030-04-01T11:50:00.000002+09:00';
  value.report.analysis_started_at='2030-04-01T11:50:00.000001+09:00';
  assert.equal(V.validateReport(value.report,value.row),false);
  value=fixture(); value.row.cutoff_at='2030-04-01T12:00:00.000001+09:00';
  assert.equal(V.validateReport(value.report,value.row),false,'different sub-millisecond cutoffs do not bind');
  value=fixture(); value.report.cutoff_at=value.row.cutoff_at='2030-04-01T12:00:00.000002+09:00';
  value.report.analysis_completed_at='2030-04-01T12:00:00.000001+09:00';
  assert.equal(V.validateReport(value.report,value.row),true,'completion a microsecond before cutoff remains pre-cutoff');
});

async function withPreview(data, run) {
  const {chromium}=require('playwright'), web=fileURLToPath(new URL('../web/',import.meta.url));
  const browser=await chromium.launch({headless:true,args:['--no-sandbox'],
    ...(process.env.CHROMIUM_PATH ? {executablePath:process.env.CHROMIUM_PATH} :
      existsSync('/usr/bin/chromium') ? {executablePath:'/usr/bin/chromium'} : {})});
  try {
    const page=await browser.newPage({viewport:{width:390,height:844}}), errors=[];
    page.on('pageerror',error => errors.push(error.message));
    await page.route('**/*',async route => {
      const url=new URL(route.request().url()); assert.equal(url.origin,'https://boat-video.test');
      const file=path.resolve(web,url.pathname==='/'?'index.html':url.pathname.slice(1));
      if(!file.startsWith(web)||!existsSync(file)) return route.fulfill({status:404,body:''});
      await route.fulfill({status:200,contentType:{'.html':'text/html','.js':'text/javascript','.css':'text/css'}[path.extname(file)],body:readFileSync(file)});
    });
    await page.clock.install({time:new Date('2030-04-01T00:30:00Z')});
    await page.goto('https://boat-video.test/');
    await page.locator('#race-file').setInputFiles({name:'synthetic-video-context.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(data))});
    await page.waitForFunction(() => document.querySelector('#file-message').textContent.includes('端末内で読み込みました'));
    await page.locator('#page-home [data-open-race]').first().click();
    await page.locator('[data-detail-tab="preview"]').click();
    await run(page); assert.deepEqual(errors,[]);
  } finally {await browser.close();}
}
function importFixture() {
  const data=JSON.parse(readFileSync(new URL('../web/data/example-synthetic-forecast-audit.json',import.meta.url)));
  data.records=data.records.filter(r => r.sport==='boat').slice(0,1);
  const {row,report}=fixture(); row.scope='synthetic'; report.source.kind='SYNTHETIC_TEST';
  report.source.identity_status='SYNTHETIC'; report.dataset_status='SYNTHETIC_ONLY';
  Object.assign(data.records[0],row); data.records[0].participants[0].display_time=6.91;
  return data;
}

test('preview expands experimental evidence, preserves original observations and saved Top8, and makes no external request',async () => {
  const data=importFixture();
  await withPreview(data,async page => {
    const panel=page.locator('#boat-video-evaluations'); assert.equal(await panel.count(),1);
    await panel.locator('summary').first().click();
    for(const summary of await panel.locator('details details > summary').all()) await summary.click();
    const rendered=await panel.innerText();
    for(const label of ['ターン','出足（ターン出口）','行き足（スタート助走）','伸び（直線）',
      'px/s','COLOR_CANDIDATE','未検証','形式照合','フレーム','0, 1, 2, 3, 4, 5',
      '11:40','11:50','12:00','a'.repeat(64),'b'.repeat(64)]) {
      assert.ok(rendered.includes(label),`visible evidence: ${label}`);
    }
    assert.match(rendered,/画像/); assert.match(rendered,/PHASE_NOT_OBSERVED/);
    assert.match(rendered,/本番予想への採用は未実施/);
    assert.match(rendered,/研究版への使用状況はモデル版・入力証拠を確認/);
    assert.equal(await panel.locator('video,img,iframe,a').count(),0);
    assert.match(await page.getByRole('tabpanel',{name:'直前情報',exact:true}).getByRole('article').first().innerText(),/6\.91/);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth>innerWidth),false);
    await page.locator('[data-detail-tab="outlook"]').click();
    const tickets=await page.locator('#detail-tab-content .saved-ticket .combo').evaluateAll(nodes =>
      nodes.map(n => [...n.querySelectorAll('.lane')].map(lane => Number(lane.textContent))));
    assert.deepEqual(tickets,data.records[0].prediction.ordered_top8);
  });
});

test('malformed optional reports show a local notice while original preview stays usable',async () => {
  const data=importFixture(); data.records[0].boat_video_evaluations={arbitrary:'<img src=x onerror=alert(1)>'};
  await withPreview(data,async page => {
    assert.match(await page.locator('#boat-video-evaluations').innerText(),/照合できません/);
    assert.equal(await page.locator('#boat-video-evaluations img').count(),0);
    assert.match(await page.locator('#detail-tab-content').innerText(),/6\.91/);
  });
});

test('all six digit and temporal candidates display measured and missing evidence while preserving saved predictions',async () => {
  const data=importFixture(), report=data.records[0].boat_video_evaluations[0];
  report.tracking.tracks.forEach(track => track.identity_status='NUMBER_TEMPORAL_CANDIDATE');
  report.measurements.lanes.forEach(lane => lane.identity_status='NUMBER_TEMPORAL_CANDIDATE');
  await withPreview(data,async page => {
    const panel=page.locator('#boat-video-evaluations');
    await panel.locator('summary').first().click();
    const lanes=panel.locator('details details');
    assert.equal(await lanes.count(),6);
    for (let i=0;i<6;i++) {
      await lanes.nth(i).locator('summary').click();
      assert.match(await lanes.nth(i).innerText(),new RegExp(`${i+1}号艇.*NUMBER_TEMPORAL_CANDIDATE`));
      assert.match(await lanes.nth(i).innerText(),/欠測:/);
    }
    assert.match(await lanes.first().innerText(),/px\/s/);
    assert.match(await panel.innerText(),/数字.*時系列.*艇番候補/);
    assert.match(await panel.innerText(),/本番予想への採用は未実施/);
    assert.match(await panel.innerText(),/研究版への使用状況はモデル版・入力証拠を確認/);
    assert.match(await page.getByRole('tabpanel',{name:'直前情報',exact:true}).getByRole('article').first().innerText(),/6\.91/);
    await page.locator('[data-detail-tab="outlook"]').click();
    const tickets=await page.locator('#detail-tab-content .saved-ticket .combo').evaluateAll(nodes =>
      nodes.map(n => [...n.querySelectorAll('.lane')].map(lane => Number(lane.textContent))));
    assert.deepEqual(tickets,data.records[0].prediction.ordered_top8);
  });
});

test('absent optional reports add no video panel to the original preview',async () => {
  const data=importFixture(); delete data.records[0].boat_video_evaluations;
  await withPreview(data,async page => assert.equal(await page.locator('#boat-video-evaluations').count(),0));
});
