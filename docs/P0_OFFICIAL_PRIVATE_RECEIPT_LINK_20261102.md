# P0 source-to-protected-forecast proof link, Issue #67 (2026-11-02)

**Status: implementation and fictional contract tests only. Not official four-sport data ingestion or pre-cutoff verification.**

## Purpose and reuse

The new `race_ai/official_private_receipt_link.py` joins the **existing**
`RACE_AI_FOUR_SPORT_COHORT_BRIDGE_V1` race rows to two separately admitted,
race-specific pieces of evidence:

1. A pre-race official-source snapshot with the exact race identity, source
   byte SHA-256, original publication/capture timestamps, authoritative
   sales cutoff and *purpose-specific* rights reference.
2. An owner-only, byte-exact prospective forecast record with model/stage/version,
   original hash and generation/persistence timestamps, its protected reader
   location and a race-bound GitHub external witness.

The actual verification chain is:

`bridge row -> independently verified source rights + cutoff -> protected private
bytes + unchanged hash -> pinned original forecast validator (<=8 unique picks)
-> existing race_bound_freeze_receipt.verify_bound_receipt -> audit status`.

This module **does not** implement another hash witness, model, stored prediction
journal or scorer. It delegates the external server-run/anchor and race ID
checks to the existing PR72 adapter and pinned PR71 legacy verifier. The
`source_attestor`, `protected_reader`, `forecast_validator`, GitHub API
reader and pinned GitHub legacy verifier must be provided by a **trusted owner
runtime**. Caller-provided fake callbacks and booleans are not trusted
production authority and cannot demonstrate a real licensed source.

## Fail-closed rules

- Source `published_at <= observed_at < official_cutoff_at` is required;
  the forecast must be generated after the observed source and its original
  private persistence must precede the same authenticated official cutoff.
- The purpose attestor must bind the exact race, source hash, permit reference,
  cutoff, and grant `schedule`, `pre_race`, `private_retention`. Merely
  supplying an official URL or writing `APPROVED` in JSON grants nothing.
- The protected reader returns at most 4 MiB of **original bytes**; their SHA
  must match the prospective record. A separate trusted validator checks
  original race/model/stage, byte hash and the maximum-eight prediction
  contract. Missing callbacks, mismatched hashes and wrong race receipts stop.
- A race previously recorded as `NO_FORECAST` is **not** backfilled. Archived
  retrospective/research seal slots are kept separate and never promoted.
- The output contains only race/model/verification state, no private Top8,
  credentials, raw source bodies or purchased-ticket data.
- Missing sports, source records and private records stay present. This layer
  **always** leaves `official_complete_denominator`, formal Hit@1, Hit@8,
  capture rate, payout ROI and calibration/Brier/Log Loss `null`.
  It returns no claim that the national five-provider calendar was complete.

## Existing real-world blockers checked 2026-11-02

- Source use rights: BOAT, KEIRIN, AUTORACE, JRA and NAR site availability and
  general viewing policies **do not constitute an established blanket license**
  for bulk ongoing machine collection, retention or model training. The
  earlier `P0_PROVIDER_RIGHTS_AND_FREEZE_GATE_20261022.md` remains unchanged.
  An older bounded one-shot official observation does not authorize a new
  nationwide ongoing collector. Do not start automated collection.
- Connected Cloudflare inspection (read-only) found one D1 database named
  `race-ai-odds-private-preview`; only odds-trial tables were visible. No
  formal saved-forecast or race-completeness tables were found. R2 list
  returned 403 / error 10042, requiring dashboard activation; activation was
  **not** requested or performed.
- The previous private October 27/28 BOAT retained archives were reported in
  Issue #68, but their original protected bytes, individual independent
  freeze receipts and authoritative final cutoffs are **not available through
  the current connector**. The earlier *bundle-level* witness cannot become
  individual certified pre-cutoff evidence retroactively.
- These facts block any legitimate **real** admitted forecast count or 98%
  completion claim from this session.

## Next authorized operational work

1. Obtain explicit source-purpose evidence or provider-sanctioned machine
   delivery, per organization, including authorized frequency and retention.
   Pin grants in a protected rights registry **outside** public GitHub.
2. Restore the *owner-protected* private forecast reader and pinned byte
   validator in the authorized execution environment; do not paste original
   forecast wires into public PRs, issues, job logs or fixtures.
3. Use a **future** cohort, authenticate every official cutoff and record
   each model's original protected readback and independently issued
   per-race GitHub receipt *before cutoff*. Do not re-run old predictions.
4. Once the complete eligible daily race universe and final official
   result/refund/payout revision evidence are authenticated, feed the existing
   result-journal/evaluator. Keep NO_FORECAST in the denominator and treat
   nonstandard settlement according to official rules. Prospective A/B only.

## Test and safety declaration

`python -m unittest discover -s tests -p test_evaluation_official_private_receipt_link.py -v`

The 12 synthetic tests check five categories, no-source/no-forecast preservation,
purpose-scoped denial before private reads, original byte and model identity
hash mismatch, cutoff ordering, duplicate rejections, external witness failure
and permanent separation from formal KPI. A passing test is **not** a real
provider or private-source E2E.

No new provider GETs, scheduled crawlers, private-data upload, cloud services,
fees, accounts, bets, production release, auth changes, original forecast
edits or main merge are included. Existing Draft PR #72 is the sole code
integration location; a formal independent review and full CI are still
required before any integration.
