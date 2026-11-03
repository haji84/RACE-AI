# RACE-AI encrypted research checkpoints

This ref is for **encrypted ciphertext only**, not plaintext SQLite, forecast tickets, source pages or keys.

GitHub Actions artifacts can expire. This branch is intended to retain authenticated AES-256-GCM SQLite snapshots as create-once Git commits, with an immutable history chain and a mutable latest pointer. The repository is PUBLIC: ciphertext length, time and branch history are publicly visible. This approach is NOT a guarantee of permanent retention or safety after key compromise.

Production archives are disabled pending a valid `RACE_AI_STATE_KEY` GitHub Actions secret, a scoped production writer, and real-race source validation. Synthetic fixture archives must never be scored as real Hit@8.

Do not force push, delete checkpoint commits or replace old ciphertext. Never add plaintext files.
