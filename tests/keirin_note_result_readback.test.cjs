'use strict';

const assert = require('node:assert/strict');
const {execFileSync, spawnSync} = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {before, after, test} = require('node:test');

const root = path.resolve(__dirname, '..');
const cli = path.join(root, 'scripts/keirin_note_result_readback.cjs');
const date = '2025-01-15';
const race = '202501159801';
const resultFs = require('./keirin_note_result_fixtures.cjs');
let folder, repo, keyPath, validRev, badRev, sealedIndex, documents;

function observation(state, previous, time) {
  const invented = resultFs.observation({state});
  const body = JSON.parse(JSON.stringify(invented).replaceAll('2030-01-15', date)
    .replaceAll('20300115', '20250115').replaceAll('03:10:00', time));
  body.previous_observation_sha256 = previous;
  const fact = {...body, provider_receipts: body.provider_receipts.map(
    ({provider, source_url}) => ({provider, source_url}))};
  for (const field of ['captured_at', 'observation_sha256', 'previous_observation_sha256']) {
    delete fact[field];
  }
  body.observation_sha256 = resultFs.sha(fact);
  return body;
}

function git(...args) {
  return execFileSync('git', ['-C', repo, ...args], {stdio:['ignore','pipe','pipe']}).toString().trim();
}

function commit(index) {
  fs.writeFileSync(path.join(repo, 'index.json'), JSON.stringify(index));
  git('add', '.');
  git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
      '-c', 'commit.gpgSign=false', 'commit', '-qm', 'test-only encrypted note result state');
  return git('rev-parse', 'HEAD');
}

before(() => {
  folder = fs.mkdtempSync(path.join(os.tmpdir(), 'keirin-result-readback-'));
  repo = path.join(folder, 'state');
  keyPath = path.join(folder, 'owner', 'display-key.txt');
  fs.mkdirSync(repo);
  git('init', '-q');
  const first = observation('SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL', null, '03:10:00');
  const second = observation('HOLD_SECONDARY_RESULT_DISAGREEMENT', first.observation_sha256, '03:20:00');
  documents = [first, second].map(value => ({
    schema:'RACE_AI_KEIRIN_NOTE_RESEARCH_RESULTS_V1', day_jst:date, observations:[value],
  }));
  const seal = `
from datetime import datetime
from hashlib import sha256
from pathlib import Path
import json
import sys
from race_ai import keirin_note_feed as feed

repo = Path(sys.argv[1])
owner = feed.create_recipient(Path(sys.argv[2]))['public']
(repo / 'views').mkdir()
index = None
for doc in json.load(sys.stdin):
    raw = feed.canonical(doc)
    date = doc['day_jst']
    observed = doc['observations'][0]
    at = observed['captured_at']
    state = 'MATCHED' if observed['winning_triple'] else 'HOLD'
    note = dict(schema=feed.SCHEMA, dates=[date], source_commit='a'*40, imported_at=at,
                formal_model_admission=False, production_weight_switch=False,
                files={f'data/{date}/research_results.json': dict(
                    text=raw.decode(), bytes=len(raw), sha256=sha256(raw).hexdigest())})
    sealed = feed.seal_snapshot(note, owner, kind='results', clock=lambda: datetime.fromisoformat(at))
    entry = sealed['entry']
    (repo / 'views' / (entry['cipher_sha256'] + '.json')).write_bytes(sealed['cipher'])
    index = feed.append_index(index, owner, entry=entry, result_checks={observed['race_id']: dict(
        checked_at=at, digest=observed['observation_sha256'], status=state)})
print(json.dumps(index))
`;
  sealedIndex = JSON.parse(execFileSync('python', ['-c', seal, repo, path.dirname(keyPath)], {
    cwd:root, input:JSON.stringify(documents), stdio:['pipe','pipe','pipe'],
  }));
  // The digest and metadata are valid but there is no local ciphertext for
  // this unrelated day. The reader must only open the selected date.
  sealedIndex.entries.push({...sealedIndex.entries[0], cipher_sha256:'f'.repeat(64), days:['2025-01-16']});
  sealedIndex.result_checks['202501169801'] = {checked_at:'2025-01-16T03:10:00Z',digest:'d'.repeat(64),status:'MATCHED'};
  validRev = commit(sealedIndex);
  const bad = structuredClone(sealedIndex);
  bad.result_checks[race].digest = first.observation_sha256;
  badRev = commit(bad);
});

after(() => {
  if (folder) {
    fs.rmSync(folder, {recursive:true, force:true});
  }
});

function run(revision, output, {keyFile, day=date}={}) {
  const args = [cli, '--repo', repo, '--revision', revision, '--date', day, '--output', output];
  if (keyFile) {
    args.push('--capability-file', keyFile);
  }
  return spawnSync(process.execPath, args, {
    input: keyFile ? undefined : fs.readFileSync(keyPath), encoding:'utf8', stdio:['pipe','pipe','pipe'],
  });
}

test('an exact local revision emits both authenticated day packets in native order to a new 0600 file', () => {
  const target = path.join(folder, 'result-readback.json');
  const process = run(validRev, target);
  assert.equal(process.status, 0, process.stderr);
  assert.equal(process.stdout, '');
  assert.equal(process.stderr, '');
  assert.equal(fs.statSync(target).mode & 0o777, 0o600);
  const result = JSON.parse(fs.readFileSync(target));
  assert.deepEqual(Object.keys(result).sort(), ['checked_at','date','packets','result_checks','schema','source_packets']);
  assert.equal(result.schema, 'KEIRIN_NOTE_COHORT_RESULT_READBACK_V1');
  assert.equal(result.source_packets.length, result.packets.length);
  for (const [index, packet] of result.packets.entries()) {
    const source = JSON.parse(Buffer.from(result.source_packets[index], 'base64'));
    assert.deepEqual(JSON.parse(source.files[`data/${result.date}/research_results.json`].text), packet);
  }
  assert.equal(result.date, date);
  assert.match(result.checked_at, /^\d{4}-\d\d-\d\dT.*Z$/);
  assert.deepEqual(result.packets, documents);
  assert.deepEqual(result.result_checks, {[race]:sealedIndex.result_checks[race]});
});

test('a stale index check, unbound ciphertext, or symbolic revision produces no plaintext output', () => {
  const brokenCipher = structuredClone(sealedIndex);
  brokenCipher.entries[0].source_content_sha256 = 'e'.repeat(64);
  const badCipherRev = commit(brokenCipher);
  const missingPredecessor = structuredClone(sealedIndex);
  missingPredecessor.entries.shift();
  const missingPredecessorRev = commit(missingPredecessor);
  for (const revision of [badRev, badCipherRev, missingPredecessorRev, 'HEAD']) {
    const target = path.join(folder, 'rejected-' + revision);
    const failed = run(revision, target);
    assert.equal(failed.status, 1);
    assert.equal(failed.stdout, '');
    assert.equal(fs.existsSync(target), false);
  }
});

test('the whole selected date fails if a referenced local ciphertext is missing', () => {
  const target = path.join(folder, 'missing-ciphertext-readback.json');
  const failed = run(validRev, target, {day:'2025-01-16'});
  assert.equal(failed.status, 1);
  assert.equal(failed.stdout, '');
  assert.equal(fs.existsSync(target), false);
});

test('a private capability file may write to a pipe, and existing output or exposed capability is refused', () => {
  const piped = run(validRev, '-', {keyFile:keyPath});
  assert.equal(piped.status, 0, piped.stderr);
  assert.deepEqual(JSON.parse(piped.stdout).packets, documents);
  const existing = path.join(folder, 'existing-readback.json');
  fs.writeFileSync(existing, 'keep', {mode:0o600});
  assert.equal(run(validRev, existing, {keyFile:keyPath}).status, 1);
  assert.equal(fs.readFileSync(existing, 'utf8'), 'keep');
  const exposed = path.join(folder, 'permissive-key');
  fs.copyFileSync(keyPath, exposed);
  fs.chmodSync(exposed, 0o644);
  const target = path.join(folder, 'denied-key-readback.json');
  const failed = run(validRev, target, {keyFile:exposed});
  assert.equal(failed.status, 1);
  assert.equal(failed.stdout, '');
  assert.equal(fs.existsSync(target), false);
});
