# Name-bound official result labels

The owner requests completion autonomously, preserving frozen forecasts and independent labels. The next scoped increment connects alias-bearing races (Marugame7R) without relaxing legacy name checks. Existing dedicated workflow authorization includes bounded official facts; no new trust, secrets, Production or main change is allowed. Work remains in the owner-selected completion checkout. Use SDD with sequential implementers and independent reviews under the existing autonomous execution instruction.

## Selected design

Use a separate label contract/store, rather than rewriting B names or weakening legacy race ingestion. A finalized name-bound forecast supplies its own validated baseline and name proof. Its explicit full-name projection is used solely to validate one newly fetched postclose result. The original race, forecast, binding, legacy records and all completed source targets remain immutable. A separate immutable label is linked to the exact forecast envelope, with actual source, memory-store, runner, cloud and receipt clocks.

The new result GET returns its complete envelope. Evaluation validates the envelope against the exact frozen forecast before converting it to the existing strict cloud result bundle. The evaluation report and UI contract stay schema1: result source hash/clock, projected program identity, selected forecast proof and three scores remain unchanged. The full new label nonce/link/finalization are independently available through its own GET and retained backup. This prevents a source-label acquisition subsystem from changing old4R reports or purchase behavior.

Alternatives rejected: (a) B prefix matching or rewriting old B names loses independent identity proof; (b) publishing projected names into the shared legacy race store changes unrelated consumers' identity context. Cost of separate storage is another immutable envelope/API and a forecast-scoped latest pointer.

## Pure contract

`web/name_bound_result.py`, standard library only, dual package/standalone imports like adjacent contracts:

- `result_context(race, forecast, now)` returns `(clock, day, closed, projected, forecast_link)` after full finalized forecast validation and `_context` replay. Current JST day required; now must be after or at close.
- `build_name_bound_result(record, race, forecast, *, parents_read_at, generated_at, now)` and `validate_name_bound_result(packet, race, forecast, *, now)` return detached strict packets.
- `validate_name_bound_result_envelope(envelope, race, forecast, *, now)` validates exact receipt/marker schema and returns a detached envelope.
- `result_bundle(envelope, race, forecast, *, now)` returns the unchanged schema1 cloud race bundle (exact race_contract fields, one raceresult receipt) for read-only evaluation.

Packet exact fields: `schema_version kind race_id date_jst closed_at program_identity_sha256 validation_program_identity_sha256 forecast_link parents_read_at generated_at result_storage_scope result_record snapshot_id`. schema_version literal int1, kind `NAME_BOUND_OFFICIAL_RESULT_LABEL`, result_storage_scope `SQLITE_MEMORY_NOT_DURABLE`. B program digest and full-name validation digest are both retained. snapshot_id is SHA256 of canonical unsigned packet. MAX_BYTES=256000, nonces use the existing strict request_identifier pattern.

forecast_link exact fields: `request_id snapshot_id envelope_sha256 baseline_request_id name_binding_request_id receipt_confirmed_at`; every field recomputes from the supplied fully validated forecast and own parents. Request ID alone is insufficient.

The unmodified record must pass `race_contract.validate_record(... require_same_day=True)` against projected names, kind raceresult, AVAILABLE, body_identity_verified=true, six full result rows, rights_review `user-confirmation-2026-10-15-official-facts`, eligible_pre_race=false and storage_eligible_pre_race=false. Results remain separate labels. All returned outcomes/payout data keep strict existing validation; a label does not imply financial action or model adoption. Pending or empty result responses stop before POST.

Canonical actual UTC microsecond stamps and same-JST day required. `forecast.finalization.receipt_confirmed_at <= closed <= parents_read_at <= captured_at <= saved_at <= generated_at <= now`. No timestamp substitution or backdating. Full-name comparisons remain strict after independent registration-bound projection; prefix-only matching is never introduced.

Envelope exact fields: `receipt finalization`.
Receipt fields: `schema_version request_id forecast_request_id snapshot runner_saved_at cloud_saved_at cloud_eligible_pre_race` (literal false). `generated_at <= runner_saved_at <= cloud_saved_at <= now` with same day, after close.
Marker fields: `schema_version race_id request_id forecast_request_id snapshot_id receipt_sha256 receipt_confirmed_at`. All links/hash match; `cloud_saved_at <= receipt_confirmed_at <= now`. Receipt confirmed is measured after actual receipt readback. Orphan/unfinalized receipts never become readable/adopted. Cloud bundle uses receipt cloud_saved_at and marker confirmed_at as published_at, projected program digest and the original packet record without rewriting it.

## Single bounded source

`race_ai/name_bound_result_source.py`: `collect_name_bound_result(race, forecast, *, parents_read_at, facts_review, execute=False, transport=None, clock=utc_now)` returns `{status, official_source_requests}` and only for COLLECTED also `snapshot`.

Dry-run no transport. Validate own forecast/clock/rights before transport. Current JST and postclose required at every clock tick; rollback rejects. Exactly one attempt to the existing official raceresult endpoint, timeout10s and max_bytes1000000 (official HTML limits), no redirects/retries/other sources. Count a thrown transport attempt. Validate response object/URL/200/html/byte bound, measure capture after response; parse through the strict existing parser with projected entries. Save/read through actual SQLite memory store without replacing saved_at. Build packet at actual generation clock. No source body, frames, keys, credentials or transport error detail leaves the worker. Fixed statuses: DRY_RUN, INPUT_INVALID, DAY_INVALID, CUTOFF_NOT_REACHED, RIGHTS_BLOCKED, SOURCE_UNAVAILABLE, SOURCE_INVALID, RESULT_PENDING, COLLECTED.

## Private immutable store and API

`web/api/name_bound_result_store.py` reuses bounded canonical read/put helpers and pinned forecast lookup. All writes restricted to new `race-ai/name-bound-result-*` namespaces:
packet `{race}/{snapshot_id}.json`, receipt/finalization `{race}/{forecast_request_id}/{request_id}.json`, latest `{race}/{forecast_request_id}.json`. Exact nonces/hashes checked. Existing old B/predictions/names/race/v1 paths never written.

`publish_name_bound_result(request, race, *, client, now, clock=None)` exact request fields `publication_review race_id request_id forecast_request_id snapshot runner_saved_at`. Server resolves that exact finalized forecast, validates every context/link/clock before first write. New packet and receipt are exclusive, readback checked, actual cloud clock measured after packet readback, actual confirmation after receipt readback. Marker finalizes only after full aggregate replay. Same request retries return identical complete metadata only when all content/IDs/runner clocks match; partial/orphan retries reject. Latest pointer uses lexicographic `(captured_at, generated_at, cloud_saved_at, request_id)` only to advance within the exact forecast. Check actual same-day/postclose/monotonic clocks across I/O and final return; no `max(now, stored)` timestamp repair.

`read_name_bound_result(race, forecast, *, client, now, request_id=None)` validates pinned/full receipt/marker/packet against the supplied exact forecast and canonical bytes. Latest manifest strict fields `schema_version race_id forecast_request_id request_id snapshot_id published_at`, published actual same-day after confirmation. Metadata fields: `status race_id request_id forecast_request_id snapshot_id cloud_saved_at receipt_confirmed_at sha256 research_only validation_status purchase_decision purchase_recommendations`; status verified, SHA256 full envelope.

New `/api/publish-name-bound-result` uses the identical Preview-only OIDC verifier, commit header and bounded/strict JSON contract as existing publisher; no auth configuration changes. New GET `/api/name-bound-result?race_id=...&forecast_request_id=...` has optional single request_id. Reject duplicate/blank/extra/oversized query; no network sources/writes. Fully unavailable parent or store fails closed. Missing label returns exactly404 `{error: NAME_BOUND_RESULT_NOT_SAVED}`. All readers preserve no-store/noindex/nosniff and postread midnight guard.

Existing name-bound-evaluation first reads the separate label for its exact forecast. If none exists, use the unchanged legacy result path for old4R. Invalid supplied separate label must reject, never fallback. Fully validated conversion uses existing pure scoring; no model/forecast/report/UI schema change. Exercise legacy absence parity and new label path without any real network sources in tests.

## Bounded dedicated caller/workflow

`scripts/publish_name_bound_result.py`: `run(race_id, forecast_request_id, output_dir, *, execute=False)` and `verify_backups(folder, manifest)`. Request nonce is the existing GitHub run_id-run_attempt; no CLI/default dated target. Dry-run no filesystem, authentication or network. Existing workflow_session, trusted headers and exact Preview URL/commit validation only.

Max240 seconds monotonic including authentication and all final write/close/verify I/O, max5 application GET, max1 POST, max1 official transport attempt, each normalized file <=256000 bytes. Flow: approved today -> exact pinned forecast -> exact latest separate label preflight -> one result source -> exclusive canonical request -> POST -> pinned own result GET -> evaluation GET/replay. Existing label stops before official GET/POST. Only the exact expected404 code means absent; auth/network/malformed errors are not absence. Preserve measured source/runner/server times. POST failures retain normalized request. No retry.

Six exclusive canonical files: program.json, forecast.json, request.json, result.json (full new envelope), evaluation.json, manifest.json. Completed backups replay request/label/own parents and evaluation at unchanged report.as_of; remote report skew only existing60s. Exact inventory and byte/hash/types/counters checked. Result_bundle derives label-only bundle; caller does not use legacy/race for an abbreviated target.

Manifest exact fields: `schema_version operation race_id forecast_request_id request_id commit_sha status failure_reason backups reads_used posts_attempted official_source_requests max_seconds validation_status purchase_decision purchase_recommendations`; operation `NAME_BOUND_RESULT_PUBLICATION`. COMPLETED only with5GET/1POST/1official and all five payloads; STOPPED/TIME_LIMIT_REACHED preserve actual partial inventory and static existing failure codes. Reuse the reviewed final-manifest ownership/close recovery helper with optional inventory_fn/verify_fn callbacks rather than duplicating its algorithm. Defaults preserve all existing read-only-caller behavior/tests.

Workflow new manual mode `name-bound-result` uses existing blank name_bound_race_id and name_bound_forecast_request_id inputs (update descriptions for both usages), unchanged subject/env/permissions/concurrency/default/probe-only push. Add only dedicated caller/normalized upload/restore/full replay steps using existing pinned artifact actions,14-day retention. Do not repin or publish trusted workflow during implementation; root verifies reviewed code CI/READY first, then updates only reviewed workflow code/pins with the established trusted lease. Before every push confirm BOTH source-smoke manual-only files.

## Live and completion gate

Root independently reviews exact latest code/Windows+Linux CI, unchanged trust/protection, all active workflow states and trusted branch lease. Only if exact current-day7R is still absent and closed, run the new manual mode once using its own forecast38708771146-1/proof38703196877-1. Never reacquire completed3/4/7 racelists or4/7 numeric sources, old4 result/evaluation, day refresh before23:32JST, old118 baselines or completed video. Restore every normalized byte, compare full APIs, independent label/identity/clock/three-score audit, protected current UI and preserve old4/v1/full chosen parent APIs. Result factual label, physical phase/precision/adoption/video remain UNVALIDATED/skip/[]. If day changes, do not backdate or fetch past-day using current route; document next eligible evidence instead.
