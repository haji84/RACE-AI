# First forward official results interface

This is an explicit separate purpose after an actual complete thirty-cell future
forecast has been independently saved. It does not create predictions, fit models,
retime inputs or reuse old result recovery authority. No operational input or
consumed marker has been created by this implementation.

The public input schema is `RACE_AI_ALL_NATIVE_FUTURE_RESULT_CAPTURE_INPUT_V1`.
Its exact fields are `schema`, `execution_day`, `target_event_day`,
`forecast_artifact`, `origin_artifact`, `cases`, `terms_manifest`,
`prior_journal_artifacts`, `maximum_requests: 32`, and `allow_order_only: true`.
The two artifact pins use the existing `{id,digest,run_id,head_sha}` contract.
The forecast must contain all original BOAT14/AUTO6/KEIRIN5/HORSE5 cells, its
generic V3 origin, and independently authenticated original native-input pins.

There is exactly one AUTO, KEIRIN and HORSE case, each with
`{sport,race_id,route}`. AUTO/KEIRIN use the existing `NORMAL_UI` route with a
published `ui_entry_url`, `ui_venue_name`, and AUTO's actual optional `place_code`.
HORSE uses `{kind: JRA_CARD_PUBLISHED_GET,card_url}` with the original frozen
literal card URL. A fresh card must publish the matching result href. A result
endpoint or checksum is never generated. The target day is the original event
day, at most seven days before the actual execution/capture day.

The prior pins must retain the fixed old UNKNOWN/upper32 and every later actual
result and A/K/JRA future-source journal. All other outcomes must be known,
without any denial, with a full hour after all actual terminal/save clocks.
Original source-input receipts join the exact source journal's native generation,
fixed as-of and independent save margin. Original expired capture markers replay
at their original clocks; they never grant a new request. Missing forecasts,
sources, prior pins or not-yet-due cases stop before dispatch.

The Actions-only CLI is:

```sh
python -m scripts.all_existing_model_future_result_capture \
  --input "$PUBLIC_INPUT" --out-dir "$RUNNER_TEMP/future-result-capture"
```

Its existing trusted PR71 environment checks run before owner-secret access.
The result purpose consumes one literal create-only marker on the existing
transfer ref: `future-result/all-thirty-first-forward-cycle-v1/official/consumed.enc`.
It cannot be reset by changing date, HEAD, run, manifest or output directory.
The one-hour expiry is capped at actual JST midnight. Every source start must
also be after the original cutoff plus 120 seconds. The browser receives at most
30 wires; JRA receives only the global remaining two, with the existing spacing
across that boundary. This 32-wire bound is local accounting, not a provider quota.

`GITHUB_OUTPUT` contains `ready`, `result_artifact_name`, `source_artifact_name`,
`result_path`, and `source_path`. Upload only the returned encrypted directories:

- Source: `official-future-result-capture-RUN`, containing `source/*.enc`.
- Result when ready: `all-existing-official-results-RUN-900030`, containing
  `result/results.enc`.

`counts.json` is an optional aggregate proof outside both upload directories.
Do not upload the sibling browser directory or its plan. Failures retain bounded
raw/index/checkpoint ciphertext, including UNKNOWN counts. An incomplete/opened
wire cannot become a known zero or a complete raw archive. A denial is permanent
HOLD for later acquisition. Source-only readback is available even without a
normal result:

```sh
python -m scripts.all_existing_model_future_result_capture \
  --input "$PUBLIC_INPUT" --out-dir "$RUNNER_TEMP/future-result-capture" \
  --readback-source "$ACTUAL_SOURCE_ARTIFACT_ID"
python -m scripts.all_existing_model_future_result_capture \
  --input "$PUBLIC_INPUT" --out-dir "$RUNNER_TEMP/future-result-capture" \
  --readback-source "$ACTUAL_SOURCE_ARTIFACT_ID" \
  --readback-result "$ACTUAL_RESULT_ARTIFACT_ID"
```

Readback fetches actual metadata/ZIPs, replays the original once MAC at its stored
epoch, checks immutable Git marker bytes, original thirty forecasts, full source
wires and published-link/parser decisions. No source is fetched during readback.
Original settled HORSE and nineteen-field rank_confirmed A/K labels remain
unchanged. The result can feed the existing mixed-label thirty-cell order-only
PDCA alongside the existing BOAT result archive. No monetary metric is produced.
`ready` means encrypted RESULT exists; only `all_requested_cases_confirmed: true`
means all three non-BOAT cases are normal. Pending/special/missing are never losses.

The same existing dedicated future job accepts the explicit commit prefix
`official-future-result-capture:` and the public input path
`audit/state/official-future-source-capture-input.json`. Its full key-free RESULT
schema validation runs before the secret-bearing capture step. The original
`official-future-source-capture:` prefix remains restricted to its original two
input schemas. Crossing these purposes is rejected. The existing owner, PR71,
same-branch, attempt-one and five successful dependency gates remain in force.

The RESULT route installs the same pinned browser tooling as A/K, uploads only
the fixed `result/results.enc` path under the standard 900030 name, and uses
`--readback-result` with the actual result/source upload IDs. A RESULT HOLD uses
source-only readback. The existing always-upload source ciphertext and safe
sibling `.status.json` proof remain separate from browser plaintext. Successful
RESULT CLI/readback replaces that 0600 status proof with its count-only result.

There is no new workflow or schedule, and no operational public input or marker
is created here. Actual forecast/native/source receipts must exist first.
Authored test success is not an actual future RESULT or thirty-cell PDCA
completion claim.
