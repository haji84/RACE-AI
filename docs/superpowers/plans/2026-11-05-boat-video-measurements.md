# Boat exhibition video measurements implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans for the independent components below. This continues the owner's authorized PR #71 work; it creates no external development task.

**Goal:** Decode authorized local exhibition footage, retain reproducible experimental measurements of turns, turn exits, start approaches and straights, and inspect them beside preserved forecasts.

**Architecture:** Local-only decoding produces timestamped, camera-stabilized candidate tracks. Pure measurement functions keep missing evidence explicit. Sealed reports live outside Git and attach to a view only when race, cutoff and all six registrations match. The UI shows their experimental scope separately from official observations and saved predictions.

**Tech stack:** Python standard library, FFmpeg/FFprobe, isolated optional NumPy/OpenCV, existing JavaScript product UI and Node/Playwright tests.

**Spec:** Owner's current request and `docs/CODEX_RACE_AI_UI_PRODUCT_COMPLETION_20261104.md`. Later explicit owner instructions take precedence over historical limits in the document.

## Global constraints

- Preserve the running forecast server and existing automatic worker; no stop/restart/cancel.
- Existing Draft PR #71 only; no main merge, public deployment, paid service, wagering or production-model switch.
- No raw footage, private forecasts, signed media URLs or credentials in Git.
- Camera motion, cuts, ambiguous identities and occlusion must not become fabricated measurements.
- Image coordinates do not establish physical speed, boat identity, competitive strength or forecast improvement.
- Synthetic footage proves implementation behavior only. Real footage and independent annotations are separate acceptance gates.

## Review focus

- Cross-color overlap must not manufacture a second track: collision regression in tracking tests.
- Replays/camera movement must not imply physical acceleration: unit and scope assertions in measurement/report/UI tests.
- A hash reseal must not promote an experimental report: report validation tests.
- Foreign race/cutoff/roster or synthetic reports must not attach to saved real forecasts: enrichment tests.
- Untrusted imports and existing output files must preserve originals: CLI and UI rejection tests.

## Tasks

- [x] Investigate official parent-page playback and retain exact race/source identity evidence privately. Normal embedded playback still requires successful media initialization; an initial bare iframe 403 is not proof that the ordinary official route is denied.
- [x] `race_ai/boat_video_tracking.py`, `tests/test_boat_video_tracking.py`: local held-descriptor decode, actual display PTS, camera-quality diagnostics, candidate tracks and explicit continuity breaks. RED/GREEN synthetic tests include pan, VFR, cuts, overlap and unsafe inputs.
- [x] `race_ai/boat_video_measurements.py`, `tests/test_boat_video_measurements.py`: `measure_tracks(tracks, *, coordinate_space, phase_windows=None, start_gate=None, calibration_evidence=None, max_gap_seconds=0.3)`. Test known geometry, absent start reference, missing samples and conditional units.
- [x] `race_ai/boat_video_evaluation.py`, `tests/test_boat_video_evaluation.py`: `analyze_video(path, job, *, clock=None, extractor=None)`, immutable `save_evaluation`, verified `read_evaluations`, exact-identity `enrich_view`. Test clocks, seal, scope, paths and original preservation before implementation.
- [x] `scripts/boat_video_analyze.py`, `tests/test_boat_video_cli.py`, `requirements-video.txt`: local manifest-driven CLI, private report storage, optional new enriched view output. Test paired flags and non-overwrite before implementation. No network or live model input changes.
- [x] Optional UI helper in the already-served `web/ui-model.js` and `web/app.js`: validate/display experimental sidecars, per-phase units/missing reasons and evidence, without changing Top8/results or official observations. RED/GREEN Node tests then mobile/desktop browser interaction.
- [x] Run a full real-decoder synthetic integration with known trajectory, actual report store and browser view; label all evidence SYNTHETIC_ONLY.
- [ ] Obtain normal official replay playback and authorized target footage; independently annotate actual boat/phase examples before declaring real automatic assessment accepted. If unavailable, document the exact unresolved source/validation gate rather than claiming completion.
- [x] Independent review, integrated Python/Node checks, source SHA/evidence, live-worker continuity check, and `docs/RACE_AI_LATEST_STATUS.md` with completed versus uncompleted gates. Fetch latest PR HEAD before a non-force push to the existing branch.

Verification commands: isolated CV Python `-m unittest discover -s tests -v`; `node --test tests/*.test.js`; targeted browser checks with `/usr/bin/chromium`. Any tests added after a full-suite run require a fresh integrated run or an explicit limited-verification statement.

Implementation rulings: use the existing isolated PR71 checkout; the live server has a frozen asset whitelist, so the optional renderer is bundled once in already-served `ui-model.js`, avoiding a server restart. Historical replay acquisition can occur after race day and must stay visibly late. Two independent review waves reproduced and fixed six CV defects plus timestamp/scope parity defects; real-source and field-validation acceptance remain open. Existing PR updates are authorized; no new PR or integration-choice prompt is needed.
