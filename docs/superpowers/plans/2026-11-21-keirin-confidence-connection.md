# Connect saved KEIRIN confidence to daily forecasts

## Goal

Connect newly created pre-race forecasts to a reproducible four-tier confidence assessment, save its evidence beside the original, and display/filter that saved assessment in the canonical reader and the existing owner-selected Site.

## Architecture

One Python research evaluator owns the rules. A versioned `confidence_assessment` sidecar binds its timestamp, evidence, ticket selection, source facts, and original prediction digest. Existing encrypted records and feed files carry it. JavaScript validates and displays the saved assessment; it never generates a new grade. Normal and rollover selections retain the same complete scenario denominator. Two-car selections are assessed as two-car selections, never by copying a three-car grade.

## Tech stack

Existing Python generation, RSA/AES-GCM storage and GitHub Actions; existing JavaScript reader and Sites publication workflow. No new backend or persistence provider.

## Specification and global constraints

- Grades: 激アツ, 高, 中, 低; missing evidence remains 未評価.
- These are provisional scenario-robustness grades, not calibrated hit probabilities or proof of improved returns.
- The fixed A/B generator, its prediction bytes, arm shapes, weights, ticket order, and digest remain unchanged.
- Evaluate only during a new forecast's creation, before sealing and at least 65 seconds before its published cutoff.
- Validate new sidecars strictly; accept explicitly recognized legacy records without retroactive assessment.
- Preserve original archives and create-once ciphertexts. Never use race outcomes in the assessment.
- Assess each arm/market/strategy separately. Adjusted forecasts do not inherit baseline grades.
- Use independent complete six-phase scenario outcomes. Legacy ticket-derived `goal_candidates` do not establish coverage.
- Removing tickets alone cannot increase the grade.
- All committed fixtures are synthetic. Private source data, forecasts, credentials, and keys remain out of public Git/logs.
- Preserve Site audience and GitHub branch protections.

## Interfaces and ownership

1. Evaluator: `race_ai/keirin_confidence.py`, focused evaluator tests. Public baseline interfaces: `assess_baseline(snapshot, baseline, assessed_at=...)` and `checked_assessment(bundle, snapshot=..., baseline=..., sealed_at=None)`.
2. Backend: existing collector, batch forecast and official continuation producers; storage/readback; frozen/nationwide view builders and focused round-trip tests.
3. Canonical UI: common confidence adapter, model/feed integration, per-arm filter/display, asset registration and focused JavaScript tests.
4. Integration: new authored forecast creation adapter, Site daily reader synchronization/port, immutable archive checks, documentation, source publication, and Site deployment.

## Implementation sequence

- [x] Inspect producer/storage/reader boundaries and isolate an implementation worktree.
- [x] Preserve a verified base commit and identify the generator hash constraint.
- [x] Finalize evaluator schema and documented provisional thresholds.
- [x] Implement independent evaluator with reachable high/hot synthetic cases and negative cases.
- [x] Connect creation, encrypted persistence, strict readback, and feed export.
- [x] Connect new authored normal/rollover and two-/three-car selections without retrofitting old records.
- [x] Display saved reasons and filter high-or-above in canonical and Site readers.
- [x] Verify round trips, legacy compatibility, tamper/time rejection, and original archive hashes.
- [ ] Review source changes; publish through existing repository/Site workflows and verify the delivered UI.

## Review focus and evidence

The highest risks are self-referential prediction hashes, retroactive timestamps, ticket-derived scenario denominators, cross-arm/market inheritance, and reader/schema drift. Tests must show valid new grades reach the UI, invalid or missing evidence cannot masquerade as high confidence, and narrowing a selection never raises its grade. Existing archive labels and saved packet bytes must remain unchanged. Build and test output is recorded after implementation; a failed environment dependency check is not counted as a product regression or a passing test.

Implementation verification on 2026-11-21: 218 related Python tests, 141 canonical JavaScript tests, and 68 existing-Site tests passed. The final Site model sync additionally passed the affected 23 display/archive tests. Independent review led to regressions for grade/metric inconsistency, microsecond cutoff boundaries, and mutation after validation; those were fixed before publication. The original generator and dated archive bytes remain unchanged. Source publication and deployment are the final normal workflow steps.
