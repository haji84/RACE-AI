# Video identity and existing-model connection implementation plan

**Goal:** Continue the owner's request to complete automatic video intake, all-six boat identification and performance features, then connect them to versions of the two existing observed model families.

**Scope:** Existing Draft PR #71 only. Preserve forecast originals and the running app/supervisor PID157669. Current worker42066504421 continues at its pinned HEAD. No new external task, workflow, model family, paid service, deployment, wagering or production-model replacement. The owner has already requested execution through completion; this continuation adds no approval round.

**Architecture:** Keep frozen official eight-feature snapshots unchanged. Add a color-independent hull detector, local digit OCR and temporal candidate identities to the optional video extractor. A separate typed adapter provides experimental comparable video measurements with explicit missing reasons. Existing model IDs and contrast/PL equations receive a versioned, trainable extension with zero initial video weights and independently authenticated source receipts. Video capture/decoding, measurement comparison, prediction fitting and prospective improvement are different acceptance gates.

## Current evidence and decisions

- HEAD0b400636041f435754d8d6c0c2c48ef7faaf6ab4 and a clean working tree at task start. Existing automatic forecasts remain RUNNING.
- Current enforced network policy is unrestricted; no VPN or outbound identities. Preserve proxy/CA/TLS and don't bypass source denials.
- Additional normal official exhibition selections at Tamagawa and Tokuyama initialize, then return application-shaped403/REQUEST_FAILED/「この動画の視聴は許可されていません。」. The known denied Suminoe and YouTube routes are not retried. No real exhibition footage or human-labelled dataset is available locally. This is an external acceptance blocker, not a missing Python dependency.
- Existing local OpenCV YOLOX/NanoDet assets and Tesseract can supply a color-independent candidate route. They are existing generic CV assets, not a new forecast family. Retain hashes/licenses and don't vendor large binaries or download new models unnecessarily.
- A raw report is always UNVALIDATED. Never rewrite it with verified/eligible flags. Pixel motion, a smaller turn radius, numeric OCR confidence or a local hash alone do not establish boat strength or real forecast accuracy.
- Retain both existing model IDs and all V1 default outputs. Additional feature direction is learned from supported observations, not assumed from turn radius. Missing data contributes no invented average or ranking grade.

## Tasks and ownership

- [x] Read current source/runtime/HEAD and investigate independent normal official routes. Save private denial proof; don't describe all venues as inaccessible.
- [x] `race_ai/boat_video_identity.py`, `tests/test_boat_video_identity.py`: hash-pinned local detector and bounded digit OCR, anonymous temporal association using camera transforms, repeated digit evidence for all six numbers, scene/gap/ambiguity resets, explicit candidate status. Test six achromatic labelled fixtures, duplicate/conflicting numbers, crossing, cuts, gaps, overlays and no invented coasting. Optional local-asset smoke is not field validation.
- [x] `race_ai/boat_video_tracking.py` plus measurement/report/UI enum compatibility: optional identity provider, all-hull background exclusions, same existing decoder/PTS/limit checks, existing default HSV output unchanged. Test real decoding of controlled all-six candidate fixtures and camera/identity discontinuities before implementation.
- [x] `race_ai/boat_video_model_context.py`, `tests/test_boat_video_model_context.py`: `prepare_video_context(report, identity_evidence, *, race_id, cutoff_at, roster, as_of)`. Recompute measurement integrity, bind media/report/roster/frame evidence and comparable phase contexts; output four raw typed cells or explicit missing reasons, preserve uncertainty, no strength grades or normalized probability. Independent field validation remains a separately reported gap.
- [x] `race_ai/boat_video_learning.py`, `tests/test_boat_video_learning.py`: versioned training/inference extension of existing families using existing contrast/6, PL and gradient math. Zero initial video coefficients, signed learned directions, minimum observed TRAIN support, race-based temporal holdout, immutable source lineage, caller-owned independent receipt verification and no future/target leakage. No V1 edits until optional interfaces are stable and regression-tested.
- [x] Connect optional local intake/analysis and model hooks to existing command paths, without stopping the running forecast service or adding a cron/workflow. Missing source/validation/training support must remain visible and inactive. Document actual automatic operation separately from configurable, unactivated code.
- [x] Run integrated decoder→all-six candidates→measurement→context→existing-family tests, preserve originals, compare mobile/PC display, and request independent review. All synthetic results remain labelled synthetic.
- [ ] Obtain authorized actual exhibition footage, independently label/review all-six identities and phases, quantify ID switches/missingness/measurement errors, then save pre-cutoff shadow predictions and compare future official results. **Cannot mark complete from synthetic tests, generic model smoke, local hashes or source403 responses.**
- [x] Record completed, uncompleted and external gates in `docs/RACE_AI_LATEST_STATUS.md`, source/evidence hashes, current worker state, latest PR HEAD and exact-code CI. Non-force updates to existing PR only.

## Review focus

White/black are distinguishable only with actual number evidence, not a forced six-box count. Hull masks must exclude unnumbered boats from camera fitting. OCR ambiguity/occlusion must reset the relevant temporal evidence. Comparison contexts must not mix camera reference planes, playback clocks or units. Rehashed numeric/scope changes cannot become trusted inputs. Duplicate receipt JSON is not external authentication. Signed video weights never change old training schemas or baseline hashes. A successful software path does not prove field accuracy or complete automatic real-source operation.
