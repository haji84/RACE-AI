# Fresh official future cards in Actions

Approved scope: acquire one explicitly selected current-day AUTO card and one
KEIRIN card through the existing normal browser UI, using the existing local
32-request bound. This is not a published provider quota. No result navigation,
new model, schedule, source permission or financial evaluation is added.

The Actions-only entry point must authenticate real baseline and separate BOAT
carrier receipts before browser dispatch. Source requests start after both the
baseline receipt precision boundary and model creation. The capture's original
completion clock fixes every native input; subsequent encryption and readback
must not re-time it. Existing V1/V2 packet generation stays compatible.

All explicitly pinned prior source journals and actual terminal producer runs
are checked before dispatch. Only the historically fixed 32-request UNKNOWN
journal may remain unknown, with actual count null and upper bound 32. Every
other prior must have complete known outcomes; a denial always stops collection.
The next acquisition starts at least one hour after every prior save/terminal
precision boundary. Fresh-day acquisition does not resolve historical UNKNOWN.

Implementation and verification:

- [x] Add exact public current-day manifest and pure history/clock validation.
- [x] Extract existing selected-request encryption without changing defaults.
- [x] Add Actions wrapper with secret-filtered browser transport and immutable,
  encrypted source/checkpoint retention, including interrupted attempts.
- [x] Reuse authenticated baseline attachment and native artifact readback;
  independently require the current day and more than 600 seconds to cutoff.
- [x] Run RED/GREEN fixture tests, neighboring regressions and independent review.

No live provider request, real key access or real future save is part of these
tests. Synthetic fixtures establish code behavior only. The actual future-day
operation remains unverified.

## One experiment, one consumed reservation

The approved first forward cycle uses the existing transfer ref and the fixed
literal path
`future-source/all-thirty-first-forward-cycle-v1/autorace-keirin/consumed.enc`.
The path never depends on the manifest, date, HEAD, run, case or baseline.
Any existing bytes stop collection, including expired or malformed bytes.
Before dispatch, the dedicated Actions job publishes a create-only CAS and
independently reads back the identical ciphertext and complete MAC. Its separate
purpose/domain binds PR71, actual attempt one/run/HEAD/day, expiry, actual
baseline receipts/model clocks, original plan, all admitted history and the
permanent old UNKNOWN upper bound 32. Aborting capture does not reset it.
Further cycles require a separately reviewed scope; no automatic second cycle
is included. Legacy recovery capsule paths, MACs and source grants are unchanged.
The reservation expiry is also passed through the existing optional
`not_after` clock guard before each actual request and replayed against each
original request start. A later response does not acquire an earlier clock.

## Parent workflow interface

The existing Forecast audit workflow now contains a dedicated owner-PR71 job
after the complete Viewer, both-OS training tests, pinned PR64 bridge and
synthetic state producer/consumer succeed. It requires the existing state secret
and job-local `contents: write` for the one canonical Git reservation. Global
and Viewer permissions remain read-only. The wrapper has no workflow/rerun/issue
API. Only an `official-future-source-capture:` commit and the explicit public
input file enable its pinned setup and source steps; no input or marker is
created by this change.

The same public input path and job also accept
`RACE_AI_JRA_FUTURE_SOURCE_CAPTURE_INPUT_V1`. A key-free step first calls the
matching complete manifest validator; unknown or invalid schemas do not reach
the secret steps. AUTO/KEIRIN uses the existing CLI and native round 900003.
HORSE uses `scripts.jra_future_source_capture`, native round 900002 and source
name `official-jra-future-source-capture-RUN`. Native names are always taken from
the selected CLI's output. Both scopes use the same encrypted-only output
directories and source-only/dual-artifact readback flags. JRA skips browser
tooling, uses only its three validated literal current-day sources and keeps
its separate fixed horse once marker. This routing adds no job, workflow,
schedule, source permission or date-policy extension.

For AUTO/KEIRIN, Playwright 1.62.1 and its matching Chromium are installed outside the checkout.
The parent CLI passes Node only the single normalized, nonsymlink tooling path
`RUNNER_TEMP/race-ai-future-ui-tools/node_modules`; arbitrary resolver paths and
inherited credentials/options are rejected or removed before once consumption.
Source ciphertext and a count-only UNKNOWN sentinel use `always()` retention,
including interrupted runs; raw browser files and plaintext plans are excluded.

`scripts.all_existing_model_future_source_capture` accepts `--input` and a fresh
`--out-dir` under `RUNNER_TEMP`. The exact public input schema is
`RACE_AI_OFFICIAL_FUTURE_SOURCE_CAPTURE_INPUT_V1` with fields `execution_day`,
`cases`, `terms_manifest`, `maximum_requests` (exactly 32), `baseline_artifacts`,
`carrier_artifact`, and `prior_journal_artifacts`. There is exactly one explicit
AUTO case and one explicit KEIRIN case. Each has `sport`, `race_id`,
`ui_entry_url`, `expected_date`, `venue`, `race_no`, `cutoff_at`; the native UI
contract permits `ui_venue_name` and AUTO `place_code`. Pins use the existing
four-field `{id,digest,run_id,head_sha}` contract. Missing fitted native rankers
stop before collection; a 19-cell artifact has no AUTO/KEIRIN ranker.

Generation returns `source_artifact_name=official-future-source-capture-RUN` for
the `source/` directory (ciphertexts only), including bounded failed captures.
When native inputs are ready it also returns
`artifact_name=all-existing-model-pairs-RUN-900003` for `native/` (the existing
opaque partition layout). The sibling `.browser` directory and private plan
file are never uploaded. If the existing bound cannot preserve every raw file,
the encrypted inventory says so and native generation stays HOLD.

After actual uploads, invoke the same CLI with `--readback-native ID` and
`--readback-source ID`, preserving the original output directory. It authenticates
both actual ZIPs/metadata and the canonical Git marker, replays original source
bytes at index `completed_at`, and reuses V2 baseline/native member readback.
The current date and more than 600 seconds to every actual cutoff are required
again after independent receipts. `--readback-source ID` alone can verify a saved
failed/UNKNOWN capture while retaining `ready=false` and no pre-cutoff claim.

Final code verification: 103 focused Python tests passed, including fixture
MAC/AES -> eleven unchanged native inputs -> independent native/source ZIP and
canonical Git readback; 45 old/new Node tests passed. A separate reviewer cleared
the implementation and independently passed 26 focused tests including that
complete fixture integration. Actual provider requests, actual key use and
actual remote publication during this work were all zero. Live future capture,
all-sport future comparison and real PDCA remain unverified.

Follow-up job-hook verification passed 53 focused tests, including namespace
bootstrap/shell routing, isolated real-Node module resolution, failed-source
retention, and the complete fixture native/source readback. Independent review
cleared the hook and passed 24 focused tests plus all six shell syntax checks.
The YAML parsed successfully, and existing workflow content was unchanged
outside the added job. No public input, actual marker or source acquisition was
created during this follow-up.

The same-job JRA routing follow-up passed 50 focused tests against the committed
JRA wrapper, including its five-cell MAC/sidecar/native and dual-ZIP fixture.
Independent review cleared the routing with 11 focused tests and all seven
shell syntax checks. These remain fixture/code checks: no actual JRA source,
future native save or future PDCA completion is claimed.
