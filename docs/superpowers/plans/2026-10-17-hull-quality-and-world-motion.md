# Hull labels and conditional world-motion measurements

Owner instruction: keep the 33 pending baseline races stopped and independently prioritize hull-number recognition and running analysis. Continue the existing exhibition-boat-vision plan under its autonomous execution authorization. No source job, media download, old capture, forecast POST, trusted pin, protection or existing model is changed by this stage.

The next bounded step is two offline evidence processors. `video_hull_quality.py` compares complete frame labels approved by two distinct reviewers against a frozen detector output. It requires identical race/media/program/frame bindings, complete frame coverage, annotations frozen before candidate disclosure, foreground digit boxes, overlay exclusions and deterministic one-to-one hull matching. It reports observed TP/FP/FN and digit errors, separately from population accuracy or authenticated identities. Existing qualitative 33-frame notes are insufficient input and must not be silently converted into exhaustive geometric labels.

`video_world_motion.py` computes sampled geometry only from per-frame water-plane mappings, stable physical landmark references, separate check landmarks, an in-support water-contact point and explicitly referenced physical-clock correspondences. Declared camera cuts, missing samples in the explicitly declared frame stride, changing world references, excessive gaps, time uncertainty, bad calibration or nonfinite values reject the whole track. Polyline length, endpoint displacement rates, mean velocity vectors, finite-difference velocity changes and three-point circle geometry are conditional calculations. They do not estimate unobserved travelled distance, instantaneous speed, instantaneous acceleration or turn skill. A sampled frame stride does not prove source-frame completeness or unobserved continuity.

Total world-position error bounds must be explicitly supplied with their own evidence references and include both mapping and contact-point error. Sparse landmark residuals are only consistency diagnostics, never a global water-plane error bound. Neither self-hashes nor caller-provided error/clock/identity references authenticate that evidence. The error intervals apply to endpoint displacement and finite-difference quantities, not to the path between samples. A radius-1 quarter-circle regression distinguishes its 14.142m/s chord rate from the 15.708m/s true arc speed; no physical-speed upper bound is emitted.

Both processors are private research primitives. They perform no network or image I/O and always return prediction_eligible=false, automatic verified hull IDs=0 and boat_features=[]. No synthetic example or offline arithmetic test counts as a verified race. Actual independent field labels, metric/clock validation, held-out video contribution and prospective before/after receipts remain necessary before a separate forecast model may adopt features.

Execution:

- Write behavioral tests and observe the missing-contract failures.
- Implement the two isolated standard-library processors; preserve existing v1-v5 and forecast builders.
- Independently review malformed inputs, matching ambiguity, overlay leakage, moving cameras and unit/time mistakes.
- Run focused and full local suites once the change is stable, then latest-head Windows/Linux CI, protected Preview, immutable API evidence and full new-evidence restore.
- Record exact remaining gaps and keep the original 135/168 baseline hold and all 409 saved baselines unchanged.
