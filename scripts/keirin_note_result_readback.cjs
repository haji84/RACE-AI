'use strict';

const {execFileSync} = require('node:child_process');
const fs = require('node:fs');
const {parseArgs} = require('node:util');
const feed = require('../web/keirin-note-feed.js');
const note = require('../web/keirin-note-model.js');

const SCHEMA = 'KEIRIN_NOTE_COHORT_RESULT_READBACK_V1';
const WIRE_MAX = 90 * 1024 * 1024;

function requireCondition(ok, code) {
  if (!ok) {
    throw new Error(code);
  }
}

function readGit(repo, ...args) {
  return execFileSync('git', ['-C', repo, ...args], {
    maxBuffer:WIRE_MAX,
    stdio:['ignore','pipe','pipe'],
    env:{...process.env, GIT_NO_REPLACE_OBJECTS:'1', GIT_NO_LAZY_FETCH:'1',
         GIT_ALLOW_PROTOCOL:'', GIT_TERMINAL_PROMPT:'0'},
  });
}

function utcSortKey(value) {
  requireCondition(note.utc(value), 'INVALID_READBACK_CLOCK');
  const [second, fraction=''] = value.replace(/Z$|\+00:00$/, '').split('.');
  return second + '.' + fraction.padEnd(6, '0');
}

async function readback({repo, revision, date, capability}) {
  requireCondition(/^[a-f0-9]{40}$/.test(revision) && note.day(date), 'INVALID_REVISION_OR_DATE');
  const resolved = readGit(repo, 'rev-parse', '--verify', revision + '^{commit}').toString('ascii').trim();
  requireCondition(resolved === revision, 'INVALID_REVISION_OR_DATE');
  const blob = path => readGit(repo, 'cat-file', 'blob', revision + ':' + path);
  const cap = await feed.capability(capability);
  const index = feed.checkIndex(JSON.parse(blob('index.json')), cap.recipient);
  const stem = date.replaceAll('-', '');
  const dayChecks = Object.fromEntries(Object.entries(index.result_checks || {}).filter(([id]) => id.startsWith(stem)));
  const path = `data/${date}/research_results.json`;
  const parts = [];
  const packets = [];
  const sourcePackets = [];
  for (const entry of index.entries) {
    if (entry.kind !== 'results' || !entry.days.includes(date)) {
      continue;
    }
    let source;
    const opened = await feed.openEntry(blob(`views/${entry.cipher_sha256}.json`), entry, cap,
                                       {onSource: bytes => {source = Buffer.from(bytes).toString('base64');}});
    const packet = opened.files.get(path);
    requireCondition(packet, 'MISSING_DAY_PACKET');
    const created = utcSortKey(entry.created_at);
    requireCondition(packet.observations.every(row => utcSortKey(row.captured_at) <= created),
                     'INVALID_READBACK_CLOCK');
    packets.push(packet);
    sourcePackets.push(source);
    // A delta can also contain another day's observations. Predecessors for
    // that other day are outside this readback, so merge only the requested day.
    parts.push({...opened, results:new Map([...opened.results].filter(([id]) => id.startsWith(stem)))});
  }
  const checkedAt = new Date().toISOString();
  const checked = utcSortKey(checkedAt);
  requireCondition(Object.values(dayChecks).every(row => utcSortKey(row.checked_at) <= checked),
                   'INVALID_READBACK_CLOCK');
  if (parts.length) {
    const joined = feed.merge(parts, {resultChecks:dayChecks});
    requireCondition([...joined.results.keys()].every(id => Object.hasOwn(dayChecks, id)),
                     'MISSING_INDEX_RESULT_CHECK');
    for (const [id, observations] of joined.results) {
      let last;
      for (const {observation} of observations) {
        const captured = utcSortKey(observation.captured_at);
        requireCondition((last === undefined || last <= captured) && captured <= utcSortKey(dayChecks[id].checked_at),
                         'INVALID_READBACK_CLOCK');
        last = captured;
      }
    }
  } else {
    requireCondition(Object.values(dayChecks).every(row => row.digest === null), 'MISSING_DAY_PACKET');
  }

  return {schema:SCHEMA, date, checked_at:checkedAt, packets, result_checks:dayChecks, source_packets:sourcePackets};
}

function capabilityText(path) {
  if (!path) {
    requireCondition(!process.stdin.isTTY, 'PRIVATE_CAPABILITY_REQUIRED');
  }
  const fd = path ? fs.openSync(path, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK) : 0;
  const raw = Buffer.alloc(403);
  try {
    const stat = fs.fstatSync(fd);
    requireCondition((stat.isFile() && (stat.mode & 0o777) === 0o600) ||
                     (!path && (stat.isSocket() || stat.isFIFO())), 'PRIVATE_CAPABILITY_REQUIRED');
    let used = 0;
    while (used < raw.length) {
      const got = fs.readSync(fd, raw, used, raw.length - used, null);
      if (!got) {
        break;
      }
      used += got;
    }
    requireCondition(used < raw.length, 'PRIVATE_CAPABILITY_REQUIRED');
    return raw.toString('ascii', 0, used).trim();
  } finally {
    raw.fill(0);
    if (path) {
      fs.closeSync(fd);
    }
  }
}

function writePrivate(output, payload) {
  if (output === '-') {
    const target = fs.fstatSync(1);
    requireCondition(target.isFIFO() || target.isSocket(), 'PRIVATE_OUTPUT_REQUIRED');
    fs.writeFileSync(1, payload);
    return;
  }
  const fd = fs.openSync(output, 'wx', 0o600);
  try {
    fs.fchmodSync(fd, 0o600);
    fs.writeFileSync(fd, payload);
  } catch (error) {
    fs.unlinkSync(output);
    throw error;
  } finally {
    fs.closeSync(fd);
  }
}

async function main() {
  const {values} = parseArgs({options:{
    repo:{type:'string'},
    revision:{type:'string'},
    date:{type:'string'},
    output:{type:'string'},
    'capability-file':{type:'string'},
    help:{type:'boolean'},
  }});
  if (values.help) {
    process.stdout.write('Usage: node scripts/keirin_note_result_readback.cjs --repo LOCAL_REPO --revision COMMIT_SHA --date YYYY-MM-DD --output NEW_FILE [--capability-file PRIVATE_0600_FILE]\n'
      + 'Read the capability from stdin by default. Use --output - only with a private pipe.\n'
      + 'The readback records the actual UTC time after opening the local packets.\n');
    return;
  }
  requireCondition(values.repo && values.revision && values.date && values.output, 'REQUIRED_READBACK_OPTIONS');
  const result = await readback({...values, capability:capabilityText(values['capability-file'])});
  writePrivate(values.output, JSON.stringify(result) + '\n');
}

if (require.main === module) {
  main().catch(() => {
    process.stderr.write('KEIRIN_NOTE_RESULT_READBACK_FAILED\n');
    process.exitCode = 1;
  });
}

module.exports = {readback};
