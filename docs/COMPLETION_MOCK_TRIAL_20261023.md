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
Exact-head run39927629558 at 22cea33c182919ad5d7218ecb881773b0427c74d passed the first six mock tests and fourteen existing controller/handoff tests. Independent static review found completed receipts needed revalidation; e46ac3fa5c682c8ba39c3d343ea4badd39f0fc4e fixes that and run39929030821 passes eight mock tests plus fourteen existing tests.

## Boundaries
- Local files are disposable Actions runner state, not cross-run durable service storage.
- Recovery reclaims a dead PID only on the same host. Different-host/uncertain owner and abandoned recovery locks fail closed.
- Controlled subprocess exit is tested, not machine loss, disk power loss, all possible interruption points, or automatic whole-workflow restart.
- An ambiguous effect without its result receipt is stopped, never replayed automatically.
- No general task executor, AI backend, adaptive parallel scheduler, formal review approval, main integration, real product completion, accuracy improvement or public release is claimed.
- Unit-test temporary files are removed. A separate checkpoint-producer now uploads only small synthetic JSON files with 1-day retention for controlled transfer testing. Existing AI09 advisory behavior is unchanged.
- Run: node --test tests/completion-mock-trial.test.mjs


## Bounded actual model connection (separate from the mock executor)
scripts/completion-ai-trial.py requests real loopback Ollama inference using the existing PR70 pinned runtime/model. It verifies two model-generated arithmetic functions with independent fixed tests, using a restricted AST interpreter (never exec/eval of generated code). No credentials, paid model API, live races, repository modifications or deployment are exposed to generated expressions.
At exact head e46ac3fa5c682c8ba39c3d343ea4badd39f0fc4e, job120332413441 in run39929030821 passed: add 4 cases, then sum_to 32 cases, two actual requests, each accepted first attempt. Actual request times were 4.599s and 1.731s, excluding setup. These tiny fixtures cannot establish real project development speed.
https://github.com/haji84/RACE-AI/actions/runs/39929030821/job/120332413441
Model qwen2.5-coder:3b digest f72c60cabf6237b07f6e632b2c48d533cef25eda2efbd34bed21c5e9c01e6225.
This is NOT a general developer agent, an implementation of the real task backlog, parallel development, CI repair, or autonomous integration. The real-model receipt is distinct from the deterministic stub self-test.

## Controlled distinct-run checkpoint trial
Source run39929030821, head e46ac3fa5c682c8ba39c3d343ea4badd39f0fc4e, immutable artifact12490811314. Source subprocess exits after fixture-a result save. Producer explicitly confirms exit and transfers only state/result/effects plus hashes, not its host PID lock.
The consumer job has only contents:read and newly owner-authorized actions:read, validates fixed source run/head/branch/workflow/status/artifact digest, then checks the manifest and current mock-runner hash before using JSON. No downloaded code executes. It must verify fixture-a and finish fixture-b with exactly two total effects.
Consumer PASSED at exact head86f1be3c96e3a7e7dc529eb6c55748a827eb7779 in run39929456215/job120333822462: source39929030821 -> destination39929456215, completed fixture-a/fixture-b with exactly2 total effects. The same head also passed real model generation again (two requests,4+32 test cases) in job120333822326 and mock8+existing14 in pilot. Its new run is triggered by this limited PR commit, not autonomous dispatch. No actions:write, main change, schedule or automatic restart trigger is added. This tests controlled saved-checkpoint transfer, not recovery from abrupt machine loss before upload. Artifacts expire and are not permanent state storage.


## One-shot lifecycle
After successful run39929456215, the three model/checkpoint jobs are gated to its exact trial head86f1be3c96e3a7e7dc529eb6c55748a827eb7779. Later PR updates intentionally SKIP them, avoiding repeated model downloads/storage and failure after the one-day source artifact expires. This is not new verification on later heads: use the linked successful runs as evidence. The mock8+existing14 unit/controller checks continue normally. No timer, continuing service or new execution authority is created.
https://github.com/haji84/RACE-AI/actions/runs/39929456215
Independent internal static review found no blocking issue in the bounded trial; this is not formal GitHub approval. Main integration remains unperformed.
