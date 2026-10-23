# Offline continuation mock trial (2026-10-23)
Scope: existing PR65 only. This is a fixed synthetic executor trial, not an AI developer, production controller or deployment.
The runner reuses completion-controller.plan() with a visibly synthetic two-item catalog, saves an intent, runs a fixed local-file action, verifies its result, and advances without a second user instruction.
A real subprocess exits with code43 after result persistence and before completion persistence; the next subprocess reconciles the receipt and continues without duplicating the completed action.
The tests also reject missing receipts after a crash, altered receipts, and a second live owner.
No network calls, model/API keys, real race input, Cloudflare resources, Vercel deployment commands, GitHub writes or automatic merge are implemented in the runner.
A branch-specific Vercel git deployment suppression is included at repository root and web/ for feat/completion-controller-pilot-20261016 only; other branches retain default behavior.

## Evidence
The initial missing-runner assertion failed on GitHub Actions at exact head f3dc8861a08aaf441b08791b32c8eecd5deb5aff:
https://github.com/haji84/RACE-AI/actions/runs/39927142601/job/120326210711
The subsequent implementation must pass the exact-head Actions run before being described as verified.

## Boundaries
- Local files are disposable Actions runner state, not cross-run durable service storage.
- Recovery reclaims a dead PID only on the same host. Different-host/uncertain owner and abandoned recovery locks fail closed.
- Controlled subprocess exit is tested, not machine loss, disk power loss, all possible interruption points, or automatic whole-workflow restart.
- An ambiguous effect without its result receipt is stopped, never replayed automatically.
- No general task executor, AI backend, adaptive parallel scheduler, formal review approval, main integration, real product completion, accuracy improvement or public release is claimed.
- Synthetic checkpoint/result files are removed by the test harness; no new artifact upload is introduced by this trial. Existing AI09 advisory artifact behavior is unchanged.
- Run: node --test tests/completion-mock-trial.test.mjs
