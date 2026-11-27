# Owner-key restoration in the existing protected main job

The owner requested completion of the remaining work. The existing development
specification §25 permits implementation and actual-data verification while
preserving the approval gates for major specification, destructive and
permission changes. This scoped verification uses the already approved key and
existing `keirin-result-live.yml` / `observe-results` manual job after normal
protected review and required CI. It does not expose the key to a research ref.

The new manual mode is `dt-r1-restore`. It verifies and restores:

1. The retained 24-file DT-R1 study from immutable state commit
   `410596da678beddcef6f8ca645cdc4e970f2d0fb`, externally pinned manifest
   `497154664f90725024836fbfe7cc84def152ccadb13868ccae0edb7b14c8cc4f`.
2. The existing Codex candidate through its unchanged frozen-model loader.
3. The newly retained B candidate from immutable state commit
   `b33be58a4b0920003f40fd75157ecbd79272c9ad`, with the strict checked-in
   `evidence/20261128-continuation/back-retention.json` receipt.

The exact repository, main ref, manual event, workflow/job, checkout commit and
owner-key pair checks remain in `continuation._runtime(mode='study')`. This
operation performs no provider requests, training, scoring, forecast creation,
remote state writes, model adoption, permission changes or schedule changes.
Plaintext exists only in a temporary private directory, removed before reporting.
Only bounded component identities, counts and status enter the safe receipt.

After merging the reviewed change, dispatch the existing workflow on `main`:

```bash
gh workflow run keirin-result-live.yml --repo haji84/RACE-AI --ref main \
  -f mode=dt-r1-restore -f dossier_day=2026-11-28
```

Read the actual run, `observe-results` job and safe receipt independently.
The acceptance is `OWNER_MODELS_RESTORED_AND_VERIFIED`, three restored
components, exact retained identities and `ephemeral_plaintext_removed=true`.
A component HOLD must remain a failure for that component. CI or ciphertext
integrity alone does not satisfy this gate. Successful restoration still does
not authenticate historical sources, validate future accuracy or promote a model.
