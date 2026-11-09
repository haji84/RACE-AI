# KEIRIN video capture: production activation and acceptance (GitHub-only runner)

**Status: NOT ACCEPTED AS COMPLETE.** Synthetic CI does not demonstrate daily
capture, gap recovery or a durable private archive. The code is in a Draft PR.

## Execution boundary

- Public repository: `haji84/RACE-AI`; the workflow itself runs only after
  merging reviewed changes into `main`.
- Primary entrypoint: `.github/workflows/keirin-github-autonomous.yml`,
  schedule. The separate existing hourly canary can invoke that same worker
  as an optional backup. Never schedule a second independent recording engine.
- Both entrypoints use the `keirin-github-independent-main` concurrency
  group. Temporary GitHub artifacts are NOT long-term storage.
- The worker records only ordinarily playable result-page browser videos.
  Never bypass DRM, login, per-site restrictions, or label unseen tactics as 0.
  Exact permission scope for long-term copies must be independently confirmed.

## Private durable storage that must be set by the owner

Set these **repository Actions Secrets** (not in public code, PR comments,
workflow logs or ChatGPT messages):

- `RACE_AI_KEIRIN_S3_BUCKET`: owner-controlled private S3-compatible bucket
  (the workflow's archival step fails if absent)
- `RACE_AI_KEIRIN_S3_ACCESS_KEY_ID`
- `RACE_AI_KEIRIN_S3_SECRET_ACCESS_KEY`

Optional **repository Actions Variables**:

- `RACE_AI_KEIRIN_S3_ENDPOINT`: `https://` URL for S3-compatible providers
- `RACE_AI_KEIRIN_AWS_REGION`: defaults to `ap-northeast-1`

The owner must provision the object-storage account, bucket, restricted
credentials and appropriate retention policy; this cannot be inferred from
the presence of an S3 step. Restrict the credential to the intended bucket
and path (`keirin/*`) with GET/PUT/HEAD only as required, disable public ACL,
turn on encryption and budget alarms, and verify provider pricing and rights.
Rotate secrets after any suspected disclosure.

## What must be shown by real scheduled runs

1. Actual GitHub Actions `event=schedule` on `main`, with a real
   `capture-completed-races` job. A push/PR `unit` success is insufficient.
2. The observed JST day's race listing, per-race URL and count; do not equate
   a partial public index with guaranteed nationwide completeness.
3. For every available race, `ENCRYPTED_COMPLETE_PLAYER` with matching
   non-expired AES manifest and byte SHA. Missing/late/cancelled races stay
   individually UNKNOWN, with a reason and a bounded retry opportunity.
4. Previous-day metadata restoration using independently validated source
   evidence. An index with zero clips must not create fake capture receipts.
   The approved Nov 9 historical PR evidence is a *source catalog only*.
5. Private S3 PUT, HEAD and independent GET with byte-identical SHA. Confirm
   `DURABLE_CIPHERTEXT_READBACK_VERIFIED` in that exact run's archive logs.
   An Actions artifact, a file listing or an existing Library ZIP does not
   satisfy this gate.
6. Independently recover the preserved encrypted archive again from the
   private store on a different run and compare its SHA against the earlier
   attestation; do not decrypt or publish owner keys in GitHub.
7. Compare distinct races versus repeats and unresolved races by actual
   discovered day. Never claim 100% if the index, source rights, or replay
   player cannot be verified. Keep PR71 forecasts and rider tactic labels
   unchanged until their separate independent-review gates pass.

## Known limits

- GitHub scheduled events can be delayed or skipped; a backup schedule
  reduces the risk but cannot make an absolute uninterrupted guarantee.
- The initial main run on 2026-11-10 03:53 JST,
  https://github.com/haji84/RACE-AI/actions/runs/42678096029,
  fired on `schedule` but failed with
  `PREVIOUS_DAY_VERIFIED_SOURCE_MANIFEST_MISSING`. It recorded no clip.
- Until bucket/credentials exist and a real PUT/GET/SHA succeeds, call the
  S3 state **NOT VERIFIED**, even if all synthetic tests pass.
- Merging the backup recording schedule may increase GitHub Actions usage
  and storage cost; obtain owner approval before enabling it on `main`.
