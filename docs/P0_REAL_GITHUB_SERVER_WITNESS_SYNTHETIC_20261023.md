# P0 real GitHub-hosted witness, FICTIONAL race (2026-10-23 JST)

## What was done (real external GitHub evidence, not a real race)
- Created a non-production testing branch: `audit/freeze-synthetic-witness-20261023` from the then-PR72 head `1a5be8d2eba6a739322c69c9f2d633b5ab7d0653`.
- Committed **fictional-only, hash-only** file at `audit/freezes/2030-01-15/32399c88e64e24ba21bc034d615861c70c7396829b48cf54ac1ae9ed5441c5b8.json`:
  - race_id: `boat:2030-01-15:fictional-venue:1`
  - prediction_sha256: 64 lowercase `a` characters (a test value, NOT a genuine model output)
  - cutoff_at: `2030-01-15T10:00:00+09:00` (a fictional future deadline)
  - schema: `RACE_AI_GITHUB_FREEZE_ANCHOR_V1`.
- GitHub commit: [`9b9938800ea715abb5d7035e83cf1e2e50986423`](https://github.com/haji84/RACE-AI/commit/9b9938800ea715abb5d7035e83cf1e2e50986423).
- Real GitHub Actions push run: [`39953083646`](https://github.com/haji84/RACE-AI/actions/runs/39953083646); event `push`; `created_at=2026-10-23T12:24:35Z` (21:24:35 JST); head_sha matches the test commit; `repository.full_name=haji84/RACE-AI`; completed/success.
- Real hosted `witness` job `120412119662` logs include `STRUCTURE_OK_NOT_INDEPENDENT_CUTOFF_PROOF`, the same RUN_ID and COMMIT SHA.
- After the run, independently fetched the Actions run JSON and anchor bytes pinned by the commit SHA through the GitHub repository connection. Verified exact run ID/head, push event, repo, schema, test race ID/hash/cutoff; real GitHub-created_at is earlier than **fictional 2030 cutoff**.

## Interpretation

**PASS**: the system can create a test anchor in the repository, trigger the real GitHub-hosted, read-only push workflow on the intended branch, and obtain an independently retrievable server-generated run time and commit-SHA-pinned original anchor.

**NOT PASS**: actual pre-cutoff prediction for a real race, independently proven real sales cutoff, provider source access rights, real measured Hit@8, human/law-reviewed data source, official refund/payback/settlement, actual complete venue/discipline coverage, main merge, website release or autonomous forecast schedule. The anchor hash `aaaaaaaa...` has NO prediction payload behind it. This is a wiring E2E **infrastructure test** only.

No user betting, charges, external provider crawling, production publishing or real frozen prediction modification was performed. The extra `audit/freeze-synthetic-witness-20261023` branch is a test evidence branch, not a production record. Keep synthetic data conspicuously excluded from the main metrics and future PDCA.

## Next real-data acceptance

1. Resolve each official provider's exact retrieval method, site-terms interpretation, and automated access restrictions separately for private information analysis versus limited public comparison.
2. Obtain a real future race schedule, entrants, pre-race observed features and independent published sales-cutoff evidence, all before cutoff. PR71 models must not be force-fed invented required inputs.
3. Bind those inputs through PR72 race ID mapping + PR71 model suite, store the real forecast immutable hash via the gated writer, and independently verify run.created_at/head SHA/anchor/real cutoff/identity. No backdated timestamps.
4. Independently verify official result revisions, refunds and payouts, then publish honest missing-inclusive denominators; expand all five categories (boat, keirin, autorace, horse_jra, horse_local). No auto wagers.

All separate PR #71 model work is unchanged. Existing PR #72 stays Draft and main is still not deployed.
