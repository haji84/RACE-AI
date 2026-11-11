# KEIRIN PR71 2026-11-10: licensed-source connection and 79-slot evidence gate

## Scope and observed facts

- Production target: 8 venues × 78 scheduled races × 4 existing models = 312 prospective model-race originals.
- Trusted, automatic GitHub schedule already observed: [PR71 run 42726853547](https://github.com/haji84/RACE-AI/actions/runs/42726853547), event `schedule`, 2026-11-10 09:15 JST.
- Its source-only public preflight observed 78 races and 72 future candidates as of that invocation; 347 checklist items examined, 74 directly observed, and 79 / 93 **required model feature slots** still missing for the sampled 7-rider race. It recorded 57 missing critical checklist slots separately.
- Its production cycle returned `SOURCE_FEED_NOT_CONFIGURED` and `HOLD_NO_LICENSED_FUTURE_SOURCE_AND_NO_PRODUCTION_ORIGINAL`.
- `state/keirin/pr71-production/v1/latest.json` was absent on the existing state branch at the audit time. Thus no live original/official settlement can be certified from this evidence. A green workflow result means a **safe HOLD**, not a successful prediction.
- The source-only public preflight can validate an odds *shape* but is NOT an automated-use rights grant, model inference input, official result attestation, or license.

## A practical 79 → 65 reconciliation, not a shortcut

The existing PR71 model's required input universe is **12 rider feature slots × 7 riders + 9 environmental slots = 93**.
The observed sample has 14 filled model feature slots and 79 missing slots.

Two required pairs reuse the **same underlying source field** per rider in the current A adapter:

| Underlying source family | Missing model feature slots | Distinct missing original observations |
| --- | ---: | ---: |
| `last_lap_acceleration` | 14 | 7 |
| `venue_and_distance_compatibility` | 14 | 7 |

Every other listed missing source family is referenced once per missing model feature. Therefore the missing 79 feature slots correspond to **65 distinct missing source instances across 17 source families**, not 79 independent pieces of raw data.

This accounting does **not** fill any slot, prove that a historical statistic exists, or make source access legal. The new `scripts/keirin_source_gap_plan.py` independently checks this accounting against the pinned model map on each source-only probe, and prints counts only. It cannot silently substitute zeros or synthesize data.

### Missing families from the 2026-11-10 sampled 7-rider race

Rider fields: `last_lap_acceleration` (14 slots), `venue_and_distance_compatibility` (14), `lead_attempt_and_success` (7), `position_flexibility_and_solo_behavior` (7), `recent_strength_or_form_change` (7), `stamina_and_pace_resilience` (7), `start_or_line_reliability` (7), `teammate_pair_history` (7).

Race/track fields (one each): `air_temperature`, `bank_cant_and_corner_shape`, `humidity`, `line_competition_and_lead_candidates`, `rainfall`, `surface_wetness`, `track_surface_and_condition`, `track_weather_effect_history`, `wind_speed`.

Use existing `keirin_field_acquisition.kind()` to distinguish *published source facts*, *time-conditional observations*, *historically derived metrics*, and *forecast hypotheses*. In particular `line_competition_and_lead_candidates` is a hypothesis and must NOT be fabricated as a fetched source fact. A real derivation pipeline would require approved rules, authorized underlying evidence, as-of time proof and a separate review, rather than a changed model weight or guessed ratio.

## Required operator-held feed contract (already implemented)

The existing `race_ai.keirin_licensed_api_ingest` accepts a **provider-authorized HTTPS JSON export**, not arbitrary scraped HTML. The following credentials and proofs are required **only for the optional licensed-export path that admits complete data into the four-model production forecaster**, not for the already owner-approved personal public-page *research candidate acquisition* path. For the licensed-export path to begin:

1. Identify a *real* data rights holder and a permissible delivery method, with permission for `automated_fetch`, `schedule`, `pre_race`, `analysis`, `model_inference`, `private_retention` and, if results are included, `result_collection` and `result_analysis`. Check that those rights cover historical/statistical transformations used by each required source family. Do not infer data rights from public accessibility or personal subscription.
2. Store a provider rights document privately and build its SHA-256-bound `RACE_AI_KEIRIN_OPERATOR_LICENSE_MANIFEST_V1` bundle with exact URL prefix, scope, validity period and rights reference.
3. Configure exactly these GitHub Actions Secrets (never post their values in issues, pull requests or chat):
   - `RACE_AI_KEIRIN_FEED_ENDPOINT`
   - `RACE_AI_KEIRIN_FEED_RIGHTS_REF`
   - `RACE_AI_KEIRIN_LICENSE_MANIFEST_B64`
   - `RACE_AI_KEIRIN_LICENSE_DOCUMENT_B64`

   The optional `RACE_AI_KEIRIN_FEED_TOKEN` is separate and should be set only when the actual authorized provider requires authentication. The preexisting production AES key stays unchanged.

4. The supplied V1/V2/V3 export must use the existing delivery schema and include each source observation's actual value, `source_url`, `rights_ref`, `published_at`, `captured_at`, and `sample_n`. The code validates every item, the cutoff, roster, full model feature coverage and the actual license bundle. Any missing/late/inconsistent field remains HOLD.
5. The same existing PR71 cycle performs the four independent predictions, immutable SHA-bound AES snapshot and separate-runner readback. Only previously frozen models may receive licensed result revisions. Formal result authenticity must be independently established; provider headers and API credentials alone do not certify it.

## Distinct existing owner-approved non-API path (reconciled November 11)

`scripts/keirin_cloud_owner_inputs.py` has the explicit
`owner-approved-winticket-keirinjp-20261109` profile. With no optional
licensed-feed Secrets, `scripts/keirin_cloud_pr71_state.py::_licensed_inputs`
uses that already-approved owner-private public-page path to collect bounded
candidate observations. See PR #134 for correction of the later erroneous
API-mandatory schedule gate.

The 2026-11-11 main smoke `42927694949` confirms this mode with all four
optional provider-feed Secrets absent, 84 discovered races and 13 partial
cards; **no complete four-model forecast was saved**. The source collector
explicitly sets `provider_machine_rights_independently_verified=False` and
`new_pre_race_inputs=0`. Personal owner approval does not independently
attest a third-party site permission, and a partial card must not be marked
as a formal pre-cutoff model forecast.

## No fabricated shortcut

WINTICKET's [terms](https://www.winticket.jp/terms) and KEIRIN.JP's [site policy](https://keirin.jp/pc/dfw/portal/guest/policy/index.html) do not, by themselves, establish permission for this **unattended GitHub bulk ingestion and retention**. Source-by-source legal permission remains to be checked.

The provider connection and all 65 missing distinct observations remain **not yet independently demonstrated**. When permissions cannot be verified, do not add an unauthorized scraper, backfill after start, treat synthetic AES checkpoints as real, or compute hit-rate/ROI with no genuine frozen denominator.

## Acceptance evidence

- Exact GitHub main SHA, real `schedule` and producer run IDs.
- Provider grant validity, source SHA, observed/published clock and full 93 required feature slots for each 7-rider race (or corresponding 9-rider requirements).
- 78 actual races accounted for; 312 model-race records where pre-cutoff evidence exists; missing/expired/changed races labeled HOLD, never retroactively reconstructed.
- Model-by-model Top8 / Top12 / 0-12 decision, original SHA, model version, input SHA, persisted and deadline times.
- Encrypted Git state generation and independent fresh-runner SHA readback.
- Later authenticated official result (including payout, refund, revision) and existing PDCA by model, with conditional denominators and coverage across **all** scheduled races.

Do not call this complete until those live receipts actually exist.
