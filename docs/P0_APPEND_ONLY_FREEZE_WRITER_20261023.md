# P0: create-only forecast hash anchor writer (2026-10-23)

`race_ai/append_only_freeze_writer.py` implements the previously missing writer interface. It generates a small `RACE_AI_GITHUB_FREEZE_ANCHOR_V1` containing only the expected PR71 model race ID, model forecast SHA256 and reported cutoff, with a deterministic path under `audit/freezes/YYYY-MM-DD/`. No raw race cards, licensed payloads, odds, person records, training examples or secrets are included. It never mutates an already saved prediction.

`prepare_anchor` is pure and accepts only the existing PR72 binding contract; `submit_anchor` is **opt-in** and requires a privately supplied GitHub token, an independently confirmed safe public release of the hash-only data, and an existing branch. It uses GitHub Contents API create-only semantics (no SHA update field); pins readback to returned commit SHA and compares identical bytes. **No scheduled production workflow, token or run permission is enabled here.** CI tests use fake HTTP only.

A remote commit alone is NOT an independently proven pre-cutoff freeze. The writer output is deliberately `COMMIT_EXISTS_BUT_PRE_CUTOFF_PROOF_UNVERIFIED`; it cannot count in Hit@8. To elevate, create an actual server-timestamped same-repository run associated with this commit and verify the run ID, head SHA, pinned path, exact race ID, forecast hash and independently checked official cutoff via PR71's verifier and PR72's race-bound wrapper. GitHub timestamps are not RFC3161 qualified evidence.

Without provider-allowed real data, authentic cutoff and external running evidence, no real race E2E has passed. No auto betting, paid contract, public release, or main integration.
