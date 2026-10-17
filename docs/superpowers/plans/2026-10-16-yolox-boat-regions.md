# Separate YOLOX boat-candidate comparison

Owner intent: improve actual exhibition body/number analysis after NanoDet missed all six clear Omura10 introduction frames. Keep all old observations and forecasts immutable. This bounded change composes a new offline detector with the existing explicit v5 crop-OCR callback; no forecast eligibility is granted.

Use official OpenCV Zoo YOLOX_s at commit ea593dd89b88d4b3978273a16f0d8cfe93d2e3ea, exact LFS size/SHA and Apache-2.0 license. Model is a generic COCO candidate, not a race-trained/verified hull detector. RGB uint8 top-left letterboxing with 114 padding follows the primary demo; decoded boxes invert actual integer resize dimensions. Validate the exact 8400x85 head, probabilities, finite values, image bounds, IoU suppression and 12-candidate cap. No automatic downloads, URLs/images on disk, uploads or new dependencies.

- [x] Fail first on the absent module, pinned-model load, real synthetic inference, output/geometry limits, class/object score, NMS and pixel isolation.
- [x] Implement new module/model attribution without changing NanoDet, v1-v5 defaults, workflows, config or web.
- [x] Independent offline review and resolve findings.
- [x] Review a one-use caller for one new eligible race; original frames stay RAM-only for bounded inspection. Unknown source shapes stop; closed races remain research only.
- [ ] Actual candidate/number/body inspection, full tests, exact-head Windows/Linux CI, protected Preview/unchanged APIs, full evidence restore, PR64 and operations/automation update.

No broad accuracy claim from selected frames, no inherited identities across cuts, no color/overlay number promotion, no physical/world/performance/adoption claim. Existing completed9/10/7/8 and daily19:08 are not reacquired. Future per-race forecast integration requires own independent name proof, pre-cutoff input storage and validated features.

Recorded actual12 inspection and1090/203 local tests. Exact new-head delivery and full evidence restore remain pending at this snapshot; later PR64/private final-proof is authoritative.
