# Actual fixed-race completion and nationwide continuation evidence

The fixed race is `202611208105` (2026-11-20 Kokura 5R). The result was collected on 2026-11-21 JST. Its forecasts were not regenerated after the race.

## Completed production gate

- Protected change: [PR317](https://github.com/haji84/RACE-AI/pull/317), merged as `3b9758b8b561605bea1d01ca6a369e713876c42a`.
- Real official collection and four-arm comparison: [run 44784648369](https://github.com/haji84/RACE-AI/actions/runs/44784648369), successful `form-canary-settle` job `136457334722`.
- The eight permitted requests all returned HTTP 200. Official finishing order and the 100-yen payout basis were validated separately.
- The existing pre-cutoff A/B and condition-adjusted A/B were authenticated, scored under the same conditions and archived. New forecasts created in the result job: zero.
- Archived comparison ciphertext SHA-256: `d6a1d3fcf346ce9947f9e1d41c21b8c32eef4b94fb25de7d0a64a79c698515fe`.
- The single-use reconciliation finished `FOUR_ARMS_ARCHIVED`. Its `general_source_release` and `legacy_incident_resolved` values remain false; the original stop marker is unchanged.

`actual-canary-settlement.json` is the exact safe report content from artifact `14654221091`, reformatted as JSON. It contains no raw source document, private prediction, key or query token.

## Independent saved-only replay

[Run 44786003895](https://github.com/haji84/RACE-AI/actions/runs/44786003895) completed successfully in the existing result observer. The saved evidence was decrypted and revalidated with the configured owner key. Both original and result publications were acknowledged as already present.

The safe report records zero provider requests, zero newly published originals, zero newly published result races and zero new snapshots. `independent-saved-replay.json` retains the safe content from artifact `14653398873`.

## Existing owner display

Pages deployment [44784534215](https://github.com/haji84/RACE-AI/actions/runs/44784534215) succeeded at Pages commit `ef04473dfde160275263fef31b993545b2fb5c61`. Only `app.js` and `style.css` changed; other live files and encrypted state were preserved. Both assets returned HTTP 200 and matched the reviewed local bytes:

- `app.js`: `96197f94aad351907b7a7ea4d2053afde8a0eadcf2dc7983133d0339c6d0a8b9`.
- `style.css`: `22881f9e6eefd98c6a1b745a367c229b141d87cb66b8b37d1ebf136a206e5982`.

The existing encrypted owner feed contains the separate original and result packets for the race. The owner recipient and private capability link were not changed. A/B, adjusted A/B and pending C remain independent; imported reference predictions and secondary-source histories remain distinct.

## Scope of this evidence

This proves completion of the actual single-race gate and its saved-only replay. It does not prove nationwide prediction coverage, future race outcomes, a model accuracy rate or a guaranteed publication latency. Nationwide execution must retain all registered races and explicit holds, authenticate each future original before its cutoff, and enforce the source-specific continuation guard. A new provider denial still stops source calls.
