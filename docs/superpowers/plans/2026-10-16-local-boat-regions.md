# Local boat region OCR implementation plan

> Execute inline with executing-plans and TDD. Owner already authorized autonomous actual video analysis and separate forecast versions; no new approval, API key or hosting change is needed.

Goal: separate candidate vessel regions from text overlays before running number OCR, without certifying a hull identity, speed or forecast contribution.

Architecture: add an offline OpenCV NanoDet adapter and a composable region OCR observer for the existing explicit v5 callback. Use the official Apache-2.0 OpenCV model pinned by LFS SHA. Accept only bounded in-memory uint8 images, preserve caller pixels, return unverified candidate regions/markings, and make no network calls. Keep decoder defaults, storage routes, workflows, config and all frozen forecasts unchanged.

Observed prerequisite: current pinned OpenCV5 returns three classification heads followed by three distance heads. Pair exact shapes by stride, rather than relying on the upstream sample's alternating output ordering. Preserve source/model attribution and license. Existing v5 completed new Omura9 in post-close research, but five number observations yielded zero tracks and no certified identity.

Tasks:
- [x] Write failure tests for model hash/input/output limits, head permutation, nonfinite values, boat class selection, padding/resize mapping, exclusions, ROI OCR mapping and pixel/history isolation.
- [x] Implement the minimal offline detector and crop observer; run real bundled-model inference on a synthetic image and focused regressions.
- [x] Independent review including untested input classes and baseline default compatibility; resolve findings before real source use.
- [x] Inspect a new permitted exhibition once with this observer; retain derived evidence only, and keep physical clocks/body identity/performance/forecast gates unverified unless independently demonstrated.
- [ ] Full tests, Windows/Linux exact-head CI, protected Preview/unchanged APIs, complete backup restore and PR64/operations update.

Failure rules: reject changed/missing model, malformed/nonfinite tensor heads, incompatible shapes, source pixels/URLs/paths instead of an image array, corrupt detector/OCR rows and unbounded images. Exclude overlapping overlay boxes conservatively. Missing/ambiguous numbers do not inherit an identity. Clip/padding coordinate transforms are geometry only, not world calibration. A generic COCO boat detector requires real exhibition validation and does not establish a boat number by itself.
