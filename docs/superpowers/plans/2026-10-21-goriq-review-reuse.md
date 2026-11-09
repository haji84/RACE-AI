# Reuse GORIQ AI-09 for RACE-AI

Owner request: reuse GORIQ instead of rebuilding a reviewer. This local branch starts from PR69 head 070907dd335f1e0d64d31b49c2bb799e54010be3; PR64, PR65, PR69, main and the original dirty Cloudflare checkout stay untouched.

1. Retain four existing GORIQ review modules byte-for-byte at AI- main accf8294ff936b73b93e21667d92bc1b52aa8428. Record source blobs and SHA256; verify bytes before loading. No npm/model/API dependency is needed for local tests.
2. Add a thin RACE adapter for the existing Four sport synthetic E2E profile. Bind open same-repository PR/main base, exact head/base, successful run, suite and both OS plus unit checks. Recheck after review. Preserve GORIQ diff/chunk limits, grounding, incomplete-review HOLD and advisory-only authority.
3. Red/green local tests use the real reused engine and injected fixture inference. They prove integration/guards, not an AI-09 model judgment or real forecasting accuracy.
4. Prepare an inactive manual hosted workflow template using the same pinned loopback Ollama approach as GORIQ. No new scheduled workflow, model startup, cloud resource, write permission, main integration or paid fallback during development.
5. Independent technical review and targeted verification before delivery. Perform one public read-only preflight on existing PR69, without rerunning its completed CI or model. Report model review and formal approval separately.

Activation must use independently reviewed trusted source, remain on standard GitHub-hosted public-repository runners, and retain the owner's existing authorization/billing gates. No GitHub comment/approval, GORIQ Builder start, permission/trust expansion, production deploy or auto-merge is part of this patch.

Owner subsequently explicitly instructed: connect. V2 adds exact-head empty-file proof and complete two-level consolidation (max2batches/24each/48total), pinned plan,50minute inference budget and unchanged advisory authority. After local tests and independent technical review, publish a separate connection PR with owner-only opened/reopened one-shot execution on the confirmed public repository's standard runner. Pin reviewed adapter source independently from the target PR69. Keep the original paused automation paused and all main/old branches/data intact. Record actual model outcomes separately from fixture tests; investigate concrete failures before any retry.
