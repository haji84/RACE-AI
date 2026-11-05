# Actual video validation implementation plan

**Goal:** Execute the owner's request for actual-footage identification, measurements and existing-model evaluation, recording measured results and remaining acceptance conditions separately.

**Spec:** Owner continuation plus `docs/CODEX_RACE_AI_UI_PRODUCT_COMPLETION_20261104.md`; existing video design in `2026-11-05-video-model-connection.md`.

**Architecture:** Preserve original media, reports, forecast families and the live forecast process. Evaluate frozen tracker observations against separately prepared references through a pure benchmark. Real media, prediction engine provenance, AI visual reference, human authentication, within-clip holdout, and unseen-media holdout are separate properties. No benchmark number implies strength or prospective predictive improvement.

**Constraints:** Existing Draft PR71 only; no new external task/Issue/PR/workflow/service/model family/fees. Keep PIDs157669 and271439 and existing forecast workers running. No main merge/publication/wager/production-model replacement. Preserve proxy, CA and TLS; do not bypass playback denials. All media/reference bytes remain private; Git contains code, contracts and sanitized evidence only.

## Work

- [x] Inspect latest HEAD/runtime and fast-forward independent audit/continuity changes to960bdea without replacing source.
- [x] Obtain actual public race footage through ordinary Commons access (CC BY-SA4.0), and actual exhibition material through Fukuoka's ordinary published player. Keep race number/cutoff/registrations unknown when unestablished; never fabricate JOB_V1 metadata.
- [x] Freeze independent AI visual references before model outputs. Bind source SHA, exact displayed frame index/PTS and canonical decoded BGR24 SHA; retain exported-image SHA separately. Keep references immutable; label any corrected derivative explicitly. Use separate media for actual heldout claims.
- [x] Implement `race_ai/boat_video_benchmark.py` and focused contract tests first RED then GREEN. Accept TRACKS_V1 and validated references. Match boxes one-to-one using geometry before claimed identities. Report correct-ID precision/coverage numerators and denominators, wrong IDs, missing/false detections, confusion, track switches/fragmentation, all-six opportunities and unlabeled exclusions. Zero denominators remain null. No observations means unavailable; observed empty regions mean genuine misses on exhaustive labeled frames.
- [x] Run both unchanged local engines on actual footage; preserve failures and measured baseline. Investigate runtime/recognition failures before any minimal fix. Do not tune heldout media or count controlled predictions as pinned-engine success.
- [ ] Compare supported measurements against independent references only. Same-transform localization error does not certify camera compensation; configured windows cannot validate themselves. Keep calibration/clock/common-phase restrictions until real evidence supports any change.
- [ ] Audit and complete any necessary research archive/comparison wiring only with authenticated pre-cutoff source data. An archival tutorial without verified race identity is not a prospective prediction. Future improvement requires saved baseline/experimental pairs and later official results; do not backdate or infer success.
- [x] Run appropriate local regression suite and independent review; preserve actual source counts, baseline/improvement counts, evidence provenance, uncompleted gates and live continuity in `docs/RACE_AI_LATEST_STATUS.md`. Integrated CV suite:1559 PASS/0 skip; later concurrent change is a separate fixture test and docs only, fixture1 PASS.
- [x] Verify existing CI on pushed implementation HEADa6615ee: Viewer42129603918 and AUTORACE42129604000 SUCCESS. General Python1559 run/56 optionalCV skips, isolatedCV116 PASS/0skip including12 OCR cases; browser39 PASS markers and12 videoUI tests. Save exact receipts and limitations. Later receipt-only documentation commit leaves product/test/workflow trees identical.

## Review focus

PNG/JPEG hashes must not masquerade as decoded BGR hashes. Ambiguous numbers stay unknown. Spatial matches must not favor a correct claimed label. Sparse/unlabeled frames must not manufacture false positives or recall. Shared-media frame splits do not establish new-footage generalization. A persistent wrong label can have zero track switches. Actual video with injected predictions is not measured engine accuracy. Source403, missing labels/calibration, missing independent receipts and future result availability remain explicit conditions.

## Current execution evidence and rulings

The Commons source is actual historical race footage (Nesnad, CC BY-SA4.0), 25.859s/775 frames, SHA `1ac1f0c27f58d8d64ebb1cfc13c2c4e9133cf7bbcce04052f23c28bf2e37f194`. Fukuoka's official historical exhibition tutorial is145.903s, SHA `7821356af29809c5da4a40eb06586896a8723d9068aba8e0b8a9e005dc535b70`; private analysis only, no training/reuse license asserted. Today's Fukuoka race-replay resource returned403 in normal playback and was stopped. A packet-copy first15s tutorial derivative preserves all three selected reference pixel hashes/relative PTS and has its own source/provenance SHA. Never conflate it with the denied dated race.

The initial unchanged full tracker attempt failed at local OCR, and its partial observations were frozen. A separate complete raw sweep produced no digits meeting0.90 and four explicit YOLOX Tesseract timeouts. The scoped fix preserves0.90 and the3s deadline, permits low-confidence PSM11 to fall through to PSM10, and records typed OCR failures as missing hull identities without stale transfer. Independent review reproduced and fixed one moving-hull stale-ID case. Default HSV processing is untouched.

Both fixed full Commons runs returned775 decoded/97 sampled frames, with zero valid lane positions; execution completion is not identity success. The frozen AI visual reference has nine video frames,30 boat boxes and19 readable numeral observations. At the frozen4fps configuration, six reference frames are sampled, with ten readable numeral instances; three references are explicitly unsampled. Both source/engine provenance and these denominators must accompany any result.

Ruling: retain the existing forecast models, all pre-cutoff/roster/camera/common-window constraints and unvalidated status. Archival media with unknown race number/roster cannot become a fabricated JOB_V1, training row, or forward result. A pure hull-candidate benchmark is separate from numbered-region accuracy. A bounded development-only MSER/component/deskew OCR spike may be investigated without inspecting heldout outputs; it is not deployed or certified. A single correctly read development digit is not six-boat recognition or predictive improvement.

The brief environment-starting notice resolved with the original PIDs and original DB SHA intact; no restart or environment publication was performed. Code changes remain on existing PR71's branch, with no external task/service/workflow added.

One frozen raw FP32 component transfer batch was executed by a separate worker before reading labels. Within-clip video unique raw agreement2/9 (baseline sampled frames1/7), separate still4/6; normalization views are duplicates, one video proposal is unmatched geometry. Accepted temporal identities remain0. One hull crossed the3s soft budget (3.831s) before three later views were skipped; no hard deadline claim. No production integration or post-holdout tuning. The separately published current LIVE screen explicitly showed outside broadcast hours08:16JST, unlike the stopped403 archive; neither current race media nor future authorization is established.
