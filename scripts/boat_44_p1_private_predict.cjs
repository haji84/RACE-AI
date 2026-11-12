"use strict";
/* Private, offline scorer. Calls the EXISTING BOAT 44-factor overlay and never
   collects sources, fits coefficients, overwrites original forecasts, or
   publishes private prediction rows. No untrained fallback is promoted. */
const fs = require("fs");
const path = require("path");
const overlay = require("../race_ai/boat_six_way_probability_overlay.cjs");

const SCHEMA = "RACE_AI_BOAT_44_P1_PRIVATE_BATCH_V1";
function check(value, reason) {
  if (!value) throw Error("BOAT_44_PRIVATE_" + reason);
}
function instant(value) {
  check(typeof value === "string" && /\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d/.test(value),
    "AWARE_TIMESTAMP_REQUIRED");
  check(/(?:Z|[+-]\d\d:\d\d)$/.test(value), "TIMEZONE_REQUIRED");
  const stamp = Date.parse(value);
  check(Number.isFinite(stamp), "INVALID_TIME");
  return stamp;
}

function scoreBatch(payload, options = {}) {
  check(payload && payload.schema === SCHEMA &&
    (payload.mode === "prospective" || payload.mode === "historical_replay") &&
    Array.isArray(payload.races) && payload.races.length >= 1 &&
    payload.races.length <= 288, "BATCH_CONTRACT");
  const now = options.now === undefined ? Date.now() : instant(options.now);
  const ids = new Set();
  const out = [];
  for (const source of payload.races) {
    const id = source && source.race_id;
    check(typeof id === "string" &&
          /^\d{8}-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])$/.test(id) &&
          !ids.has(id), "RACE_ID_UNIQUE_REQUIRED");
    ids.add(id);
    const receipt = {race_id: id, status: "HOLD_MISSING_SOURCE_FACTS",
      baseline_top8: null, tactical_top8: null, full_120: null,
      accepted_as_prospective_proof: false, source_authenticity_proven_here: false,
      model_improvement_proven: false, production_promotion: false};
    if (source.status !== "P1_CONTEXT_READY_UNVERIFIED" || !source.record) {
      receipt.reason = Array.isArray(source.missing) ? source.missing : [];
      out.push(receipt);
      continue;
    }
    if (!payload.frozen_44_model) {
      receipt.status = "HOLD_NO_FROZEN_TACTICAL_MODEL";
      out.push(receipt);
      continue;
    }
    const row = source.record;
    check(row.context && row.context.race_id === id &&
          row.baseline && row.baseline.race_id === id, "RACE_DATA_MISMATCH");
    const cutoff = instant(row.cutoff_at);
    const asof = instant(row.context.as_of);
    if (payload.mode === "prospective" && (now >= cutoff || now < asof)) {
      receipt.status = "HOLD_NOT_IN_PRE_CUTOFF_WINDOW";
      out.push(receipt);
      continue;
    }
    // Existing overlay validates its own 44 features, 120-ticket baseline,
    // frozen model identity, chronological training boundary, and identities.
    // A malformed or incomplete single-race snapshot must not halt the
    // remaining nationwide batch. Duplicate IDs and cross-race identity
    // mismatch above remain fatal rather than being silently accepted.
    let baseline, candidate;
    try {
      baseline = overlay.predict(row);
      candidate = overlay.predict(row, payload.frozen_44_model);
    } catch (_err) {
      receipt.status = "HOLD_TACTICAL_INPUT_OR_MODEL_INVALID";
      receipt.reason = ["overlay input, history, model, or time gate failed"];
      out.push(receipt);
      continue;
    }
    receipt.status = "EXPERIMENTAL_TACTICAL_REPLAY_NOT_CERTIFIED";
    receipt.baseline_top8 = baseline.top8;
    receipt.tactical_top8 = candidate.top8;
    receipt.full_120 = candidate.all_120;
    receipt.first_course_win_probability_uncalibrated =
      candidate.first_course_win_probability;
    receipt.trained_through_claim = payload.frozen_44_model.trained_through;
    receipt.evaluated_at = new Date(now).toISOString();
    if (payload.mode === "prospective") {
      receipt.status = "EXPERIMENTAL_PRE_CUTOFF_UNATTESTED";
    }
    out.push(receipt);
  }
  // Counts contain no raw sources and allow all-day completeness checking.
  const status_counts = {};
  for (const r of out) status_counts[r.status] = (status_counts[r.status] || 0) + 1;
  return {schema: "RACE_AI_BOAT_44_P1_PRIVATE_BATCH_RESULT_V1",
    mode: payload.mode, count: out.length, evaluated: out.filter(x =>
      x.full_120 !== null).length, status_counts, rows: out,
    independent_official_receipts_verified: false,
    model_better_than_baseline_proven: false,
    safe_to_promote_to_main: false,
    prediction_originals_frozen_externally: false};
}

function main(args) {
  check(args.length === 2 && args.every(x => path.isAbsolute(x)),
        "PRIVATE_ABSOLUTE_INPUT_AND_OUTPUT_REQUIRED");
  const [input, output] = args;
  const repo = path.resolve(__dirname, "..");
  const forbidden = p => p === repo || p.startsWith(repo + path.sep);
  check(!forbidden(path.resolve(input)) && !forbidden(path.resolve(output)),
        "PUBLIC_REPO_PATH_FORBIDDEN");
  const stat = fs.lstatSync(input);
  check(stat.isFile() && !stat.isSymbolicLink() &&
        stat.size > 0 && stat.size <= 8 * 1024 * 1024, "PRIVATE_INPUT_INVALID");
  const payload = JSON.parse(fs.readFileSync(input, "utf8"));
  const result = scoreBatch(payload);
  const flag = fs.constants.O_WRONLY | fs.constants.O_CREAT |
               fs.constants.O_EXCL | (fs.constants.O_NOFOLLOW || 0);
  const fd = fs.openSync(output, flag, 0o600);
  try {
    fs.writeFileSync(fd, JSON.stringify(result) + "\n", "utf8");
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
  process.stdout.write("BOAT_44_PRIVATE_BATCH_WRITTEN_COUNT=" +
    String(result.count) + " EVALUATED=" + String(result.evaluated) + "\n");
}
if (require.main === module) {
  try { main(process.argv.slice(2)); }
  catch (e) {
    process.stderr.write("BOAT_44_PRIVATE_BATCH_HOLD " +
      String(e.message).slice(0, 180) + "\n");
    process.exitCode = 2;
  }
}
module.exports = {SCHEMA, scoreBatch};
