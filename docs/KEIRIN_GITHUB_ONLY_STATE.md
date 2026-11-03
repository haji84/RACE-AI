# GitHub-only state continuation

## Decision

The owner selected GitHub after explicitly prohibiting Cloudflare. Vercel is also excluded. This change reuses the existing actual PR71 model, SQLite and result/revision processing. It does not create a new model, provider service, repository or API key.

## Implemented

- `scripts/keirin_github_checkpoint.mjs`: bounded AES-256-GCM snapshots using Node built-in crypto, with random nonces and authenticated repository ID, mode, generation and previous ciphertext digest. Production reads a 32-byte base64 key from `RACE_AI_STATE_KEY`. Missing, weak or public fixture keys are rejected. Decryption requires an expected ciphertext SHA. Writes are create-only with mode 0600.
- `scripts/keirin_github_sqlite_snapshot.py`: consistent SQLite backup including committed WAL rows, read-only integrity verification, no overwrite, no silent empty database creation.
- `scripts/keirin_github_checkpoint_fixture.py`: existing PR71 algorithm on invented 2030 riders, private local SQLite, encrypted artifact, restoration, comparison with a fictional final result and another actual-model prediction. Original prediction hashes and idempotent replay are checked.
- `.github/workflows/keirin-github-state-proof.yml`: tests and producer/consumer on separate GitHub-hosted runners. Uploads only three allowlisted fixture files, never the plaintext DB.
- `.github/workflows/keirin-github-state-resume.yml`: separate workflow_run execution reads the successful main producer's exact artifact, validates producer run/commit and repeats restoration/continuation. No real secret is supplied to this consumer and no untrusted PR code is eligible.

## Key configuration

A real-data snapshot needs one dedicated GitHub Actions repository secret named `RACE_AI_STATE_KEY`. It must contain base64 of 32 cryptographically random bytes. Do not paste it in a chat, issue, commit, workflow input or log. Keep a protected recovery copy: losing the key loses access to encrypted history. Do not rotate it casually once data exists.

On an owner machine with authenticated GitHub CLI, create it once without printing it:

```sh
openssl rand -base64 32 | gh secret set RACE_AI_STATE_KEY --repo haji84/RACE-AI
```

This command overwrites an existing secret, so first check the repository's secret *name* list and do not run it if this key already exists. The current connector does not offer repository-secret creation; the main readiness job reports only whether a valid key is present, never its value.

## What is not complete

The proof uses a PUBLIC fixture key and SYNTHETIC data only. Production never accepts that key. Passing this test demonstrates actual GitHub artifact transport, byte-preserving restoration and executable model continuation, NOT real-race accuracy or official-time evidence.

The fixture artifact expires after three days. Production requires a retention/recovery policy and a separately approved permanent encrypted store within GitHub; an artifact-only handoff must not be called indefinite backup. Never treat an absent/expired artifact as permission to discard old predictions and restart an empty database.

No full live rider-feature/result feeder is enabled by this change. Real prediction generation, official settlement, pre-cutoff external evidence, all-race scheduling and prospective A/B model adoption remain distinct gates. Scheduled Actions can be delayed. No guarantee of zero missed deadlines is made.

Cloudflare shutdown is preserved; no Cloudflare/Vercel code is executed. No purchase, deployment, account permission or paid plan is changed.

References checked: https://docs.github.com/en/actions/reference/runners/github-hosted-runners ; https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows ; https://docs.github.com/en/rest/actions/artifacts ; https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets


## 2026-11-04: Git history for encrypted checkpoint retention

GitHub Actions artifacts in public repositories have a maximum retention of 90 days; the existing 3-day synthetic proof was therefore not permanent archival. Git documentation: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository

Only the SAME GitHub repository is used. A dedicated branch state/keirin-encrypted-history retains AES-256-GCM ciphertext and non-sensitive scope metadata in fast-forward-only Git commits. The main/latest pointer contains its generation, prior ciphertext hash, exact producer commit and run ID. The code rejects tampered ciphertext, unknown producer, missing predecessor, branch rewind and overwriting an existing generation.

Archive producer workflow keirin-github-git-archive.yml uses a job-only contents:write token, after verifying the successful trusted main producer and its exact encrypted artifact. The follow-up workflow keirin-github-git-restore.yml uses a different GitHub Actions runner to fetch the encrypted Git history, decrypt it locally and continue the existing fictional PR71 model without relying on the original 3-day artifact.

IMPORTANT: RACE-AI is public. Ciphertexts, file sizes and commit times are publicly observable. This is NOT as private as a private GitHub repository. The owner has not authorized creating a new private repository. The long-term safety of public ciphertext, the production encryption key and a separate backup require explicit review before enabling real forecast writes.

The first experiment archives SYNTHETIC data only with its clearly public fixture key. Production archiving remains disabled, with no plaintext Git commits and no new external cloud provider. Git history is not an independent certified timestamp or an everlasting-backup guarantee; deletion, repository loss, force pushes and repository-growth limits remain possible.

Live racer-data ingestion, independently confirmed race results, before-cutoff forecasting, prospective A/B PDCA and complete unattended all-race operations remain NOT DONE.
