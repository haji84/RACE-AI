'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const path = require('node:path');
const M = require('../web/keirin-note-model.js'), F = require('../web/keirin-note-feed.js'), C = require('../web/confidence.js');

// All inputs, owner keys and ciphertext below are created for this test only.
// The Python producer is exercised directly; no live URL or private state is read.
const fixture = String.raw`
import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from race_ai import keirin_authored_confidence as authored
from race_ai import keirin_confidence as confidence
from race_ai import keirin_note_feed as feed
from race_ai import keirin_nationwide_forecast_view as nationwide
from tests.test_keirin_authored_confidence import request_fixture, fixed_clock
from tests.test_keirin_confidence import baseline_fixture, ASSESSED_AT

def packet(files, dates, at):
    entries = {}
    for name, value in files.items():
        text = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        raw = text.encode('utf-8')
        entries[name] = dict(text=text, bytes=len(raw), sha256=sha256(raw).hexdigest())
    return dict(schema='RACE_AI_KEIRIN_NOTE_VIEW_V1', formal_model_admission=False,
                production_weight_switch=False, source_commit='a'*40,
                imported_at=at, dates=dates, files=entries)

files = authored.create_files(request_fixture(), clock=fixed_clock)
authored_packet = packet(files, ['2030-01-15'], '2030-01-15T01:00:00+00:00')
snapshot, baseline = baseline_fixture('hot')
assessment = confidence.assess_baseline(snapshot, baseline, assessed_at=ASSESSED_AT)
rid = baseline['race_id']
reference_packet = packet({'data/2099-01-01/reference_AB.json': [
    dict(input=snapshot, output=baseline, confidence_assessment=assessment)]},
    ['2099-01-01'], ASSESSED_AT)
original = dict(race_id=rid, revision='e'*64, baseline_cipher_sha256='f'*64,
    conditioned_cipher_sha256=None, baseline_sealed_at='2099-01-01T09:02:01+09:00',
    conditioned_sealed_at=None,
    facts={k:snapshot[k] for k in ('competition', 'line_groups', 'riders')},
    baseline=baseline, conditioned=None, confidence_assessment=assessment)
doc = dict(schema=nationwide.SCHEMA, day_jst='2099-01-01', revision='1'*64,
    observed_at='2099-01-01T09:03:00+09:00', registry_available=True,
    inventory_complete=True, missing_venues=[], disappeared_race_ids=[], races=[
    dict(race_id=rid, venue_code=26, race_no=1, cutoff_at=baseline['published_cutoff_at'],
         state='A_B_AUTHENTICATED_PRE_CUTOFF', condition_state='NO_CONDITIONED_ORIGINAL',
         original_identity=dict(baseline='a'*64, conditioned=None), original=original)])
national_packet = nationwide.note_packet(doc, 'a'*40)
with TemporaryDirectory() as directory:
    root = Path(directory);root.chmod(0o700)
    recipient = feed.create_recipient(root/'owner')
    index, wires = None, {}
    for note, kind, ids in [(authored_packet, 'import', ()),
                             (reference_packet, 'research', (rid,)),
                             (national_packet, 'nationwide', ())]:
        sealed = feed.seal_snapshot(note, recipient['public'], kind=kind, captured_ids=ids,
            clock=lambda:datetime(2099, 1, 1, 0, 4, tzinfo=timezone.utc))
        index = feed.append_index(index, recipient['public'], entry=sealed['entry'])
        wires[sealed['entry']['cipher_sha256']] = sealed['cipher'].decode('utf-8')
    print(json.dumps(dict(capability=Path(recipient['private_key']).read_text().strip(),
        index=index, wires=wires, baseline_grades={k:v['grade'] for k,v in assessment['evaluations'].items()})))
`;

test('actual Python generation and encrypted NoteFeed reach the JS high-grade views without changing market or strategy', async () => {
  const produced = JSON.parse(execFileSync('python3', ['-c', fixture], {
    cwd: path.resolve(__dirname, '..'), encoding: 'utf8', maxBuffer: 8 * 1024 * 1024, timeout: 30000,
  }));
  let requested = 0;
  const session = await F.createSession(produced.capability, { fetcher: async url => {
    requested++;
    if (url.endsWith('/index.json')) return new Response(JSON.stringify(produced.index));
    const match = /\/([a-f0-9]{64})\.json$/.exec(url);
    assert.ok(match && Object.hasOwn(produced.wires, match[1]));
    return new Response(produced.wires[match[1]]);
  } });
  try {
    const data = await session.refresh(), row = M.rows(data, '2030-01-15')[0], saved = M.rows(data, '2099-01-01')[0];
    assert.equal(requested, 4);
    assert.equal(M.forecast(row, '3t', 'original').confidence, '激アツ');
    for (const market of ['3t', '2t']) for (const variant of ['original', 'rollover']) {
      const prediction = M.forecast(row, market, variant);
      assert.equal(prediction.confidenceAssessment.market, market);
      assert.equal(prediction.confidenceAssessment.strategy, variant === 'rollover' ? 'rollover' : 'normal');
      assert.ok(prediction.confidenceBundle.source_prediction_sha256);
    }
    for (const name of ['A', 'B']) {
      assert.equal(M.forecast(saved, '3t', name).confidence, produced.baseline_grades[name]);
      assert.equal(M.frozenArm(saved, name).confidence, produced.baseline_grades[name]);
      assert.equal(M.forecast(saved, '2t', name).confidence, null);
    }
    assert.equal(M.frozenArm(saved, 'B').confidence, '激アツ');
    assert.equal(C.predictionMatches(M.frozenArm(saved, 'B'), 'high_plus'), true);
    assert.equal(M.frozenArm(saved, 'adjusted_B'), null);
  } finally { session.close(); }
});

test('real producer records with incomplete phases or absent market evidence remain unrated in JS', async () => {
  const { createHash } = require('node:crypto');
  const script = String.raw`
import json
from race_ai import keirin_authored_confidence as authored
from tests.test_keirin_authored_confidence import request_fixture, fixed_clock
cases=[]
for case in ('phases', '2t_goals', 'lineup'):
    request=request_fixture()
    universe=request['races'][0]['universe']
    if case=='phases': universe['scenarios'][0]['phases'].pop()
    if case=='2t_goals':
        for scenario in universe['scenarios']: del scenario['goal_candidates']['2t']
    if case=='lineup': universe['source_status']['lineup']='unknown'
    cases.append(dict(case=case,files=authored.create_files(request,clock=fixed_clock)))
print(json.dumps(cases,ensure_ascii=False))
`;
  const cases = JSON.parse(execFileSync('python3', ['-c', script], { cwd: path.resolve(__dirname, '..'), encoding: 'utf8', maxBuffer: 8 * 1024 * 1024, timeout: 30000 }));
  for (const item of cases) {
    const files = Object.fromEntries(Object.entries(item.files).map(([name, value]) => {
      const text = JSON.stringify(value);return [name, { text, bytes: Buffer.byteLength(text), sha256: createHash('sha256').update(text).digest('hex') }];
    }));
    const packet = { schema: M.SCHEMA, formal_model_admission: false, production_weight_switch: false, source_commit: 'a'.repeat(40), imported_at: '2030-01-15T01:00:00Z', dates: ['2030-01-15'], files };
    const row = M.rows(await M.openPacket(packet), '2030-01-15')[0];
    for (const market of item.case === '2t_goals' ? ['2t'] : ['3t', '2t']) {
      const prediction = M.forecast(row, market, 'original');
      assert.equal(prediction.confidence, '未評価');assert.equal(prediction.confidenceAssessment.rank, 0);
      assert.equal(C.predictionMatches(prediction, 'high_plus'), false);
      assert.equal(C.predictionMatches(prediction, 'unrated'), true);
    }
    if (item.case === '2t_goals') assert.equal(M.forecast(row, '3t', 'original').confidence, '激アツ');
  }
});

test('a real Python high assessment rejects grade promotion and sub-millisecond cutoff or sealing violations', async () => {
  const script = String.raw`
import json
from race_ai import keirin_confidence as confidence
from tests.test_keirin_confidence import baseline_fixture, ASSESSED_AT
snapshot,baseline=baseline_fixture('high')
bundle=confidence.assess_baseline(snapshot,baseline,assessed_at=ASSESSED_AT)
print(json.dumps(dict(snapshot=snapshot,baseline=baseline,bundle=bundle),ensure_ascii=False))
`;
  const fixture = JSON.parse(execFileSync('python3', ['-c', script], { cwd: path.resolve(__dirname, '..'), encoding: 'utf8', maxBuffer: 4 * 1024 * 1024, timeout: 30000 }));
  assert.equal(fixture.bundle.evaluations.B.grade, '高');
  await C.validateBaseline(fixture.bundle, fixture.baseline, { source: fixture.snapshot });
  const changed = structuredClone(fixture.bundle);
  changed.evaluations.B.grade = '激アツ';changed.evaluations.B.rank = 4;
  await assert.rejects(() => C.validateBaseline(changed, fixture.baseline, { source: fixture.snapshot }));
  const tooLate = structuredClone(fixture.bundle);tooLate.assessed_at = '2099-01-01T11:58:55.000001+09:00';
  await assert.rejects(() => C.validateBaseline(tooLate, fixture.baseline, { source: fixture.snapshot }));
  const boundary = structuredClone(fixture.bundle);boundary.assessed_at = '2099-01-01T11:58:55.000000+09:00';
  await C.validateBaseline(boundary, fixture.baseline, { source: fixture.snapshot });
  const afterSeal = structuredClone(fixture.bundle);afterSeal.assessed_at = '2099-01-01T09:02:00.000001+09:00';
  await assert.rejects(() => C.validateBaseline(afterSeal, fixture.baseline, { source: fixture.snapshot, sealedAt: '2099-01-01T09:02:00.000000+09:00' }));
  await assert.rejects(() => C.validateBaseline(fixture.bundle, { ...fixture.baseline, generated_at: '2099-01-01T09:02:00.000001+09:00' }, { source: fixture.snapshot }));
});
