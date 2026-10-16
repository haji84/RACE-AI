# Exhibition boat vision implementation plan

Goal: process actual permitted exhibition pictures in RAM, retain separately versioned evidence, and prevent unverified boat identity or camera motion from silently changing forecasts.

Scope agreed by owner: actual chapter pictures, boat numbers, running analysis, all-race post-exhibition forecasts and immutable before/after comparison. Existing autonomous execution authorization applies; work remains on codex/race-ai-completion in the specified checkout.

Architecture: keep public LIVE chapter indices separate from actual video evidence. The observed LIVE/DVR references are unavailable in the current ordinary player; use a separately identified official exhibition VOD when available and label this fallback explicitly. A local OCR observer reads each sampled image without writing it or sending it to another service. Exact single digits are candidate markings only; overlays are not boat identities. Region, temporal association, human audit, camera/metric calibration and prospective evaluation remain distinct gates. Existing before/after and original numeric models are immutable.

Tasks:
- [x] Decode one new, explicitly identified exhibition in RAM and inspect actual frames; retain no raw frames/media/ephemeral URLs/keys.
- [x] Add opt-in OCR observations to the bounded decoder, with exact digit parsing, geometry/score limits, duplicate and overlay exclusion, and no automatic forecast eligibility. Write failure tests before product code.
- [x] Validate observations against independently read actual frames, document unresolved boat IDs and running metrics honestly.
- [ ] Run full relevant tests, fresh independent review, Windows/Linux CI, protected Preview and immutable API/backup verification; update PR64 and operations evidence.
- [ ] Continue toward all-race prospective collection and video-feature validation. No synthetic verification or completed post-deadline diagnostic may stand in for prospective all-race forecasting.

Failure cases: camera cuts reset associations; close-up overlays and scoreboard digits cannot become hull numbers; duplicate/conflicting numbers remain ambiguous; missed/occluded boats remain missing; absent calibration or independent time keeps performance/forecast gates closed. No retries of completed old media; failed new media attempts retain their actual request counts and cause uncertainty.

Research limits: UNVALIDATED/skip/[] until held-out calibration/adoption evidence exists. No Production, main merge, voting, payments, scope expansion or raw-media retention. Detailed observations remain private.

Ruling: an observed new individual exhibition clip requires exact start/end/vt variant fields; explicit clip_window=True supports only that bounded shape. Default remains unchanged. Its child has an unapproved key origin and m segment parameter, so processing stops before key/segment requests. Existing failures stay separate. No automatic body identities or video forecasts are certified.
