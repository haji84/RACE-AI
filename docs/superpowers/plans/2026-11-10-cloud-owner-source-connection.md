# Existing owner-source connection implementation plan

## Goal
Connect the already approved owner-private WINTICKET/KEIRIN.JP acquisition and PR103 prior-input adapters to the existing GitHub PR71 workflow, without adding another scheduler or fabricating missing features.

## Root cause
Main was pinned at 97464792c2af28b39f9ffbe668019fb1482d5a8c. PR103 at9bb7e016e5200b5d25cbcc66b3ac6062b0c1aaa9 contains real-source EX and prior/weather adapters. Comparing those commits shows no four-model algorithm, AES codec, immutable forecast or licensed result ledger changes. Owner approval for private automated retrieval exists separately from a vendor-signed machine licence.

## Approach
Reuse the exact newer source pin and add a bounded orchestrator. Keep the fully configured licensed JSON feed as first priority. On missing licence-feed settings, an explicitly enabled owner profile may collect private source candidates; it cannot manufacture provider permission, complete inputs, pre/ packets or an empty production archive. No coefficient, cutoff, public ciphertext consent or result-scoring changes.

Rejected alternatives: another scheduler (does not supply data), duplicating a source parser (existing PR103 already works), inferred/zero/average missing inputs (changes semantics and creates unsupported values), forcing synthetic source records into production (false evidence).

## Tasks
1. Pure no-network regression before implementation: source-card SHA and identity, current day/cutoff, all eligible captured races,429 circuit, time budget, no public rider values, no false admission. Local11 tests completed.
2. New integration regressions: default unset profile stays offline; explicit profile uses existing collector; PR/push cannot access privileged production fallback; invalid configured licensed bundle does not bypass validation; partial source cannot create AES genesis. Confirm these fail against unchanged cloud wiring, then implement only that wiring.
3. Update the immutable source reference and run existing model, licensed result, AES, variable, gap and history/EX/weather regressions at the same SHA. Fix preflight import path without changing schedule.
4. Review diff and protections; no secrets on PR or source-only push smoke. Merge only after checks succeed. Inspect actual main source smoke metadata, not just fixture tests.
5. Preserve factual completion boundary: per-race full input, genuine four-model prospective freeze, durable encrypted original, independent readback and authenticated result comparison are separate live conditions. Missing mandatory sources remain HOLD; no retrospective fill.

## Review focus
- Provider denial never triggers alternative-site or retry bypass.
- Bad/partial licensed config cannot be labelled a provider grant.
- Partial history input remains outside production pre/ queue.
- Input pipeline clock advances; already-started or too-close races stay out.
- Temp source files are private and not durable; cleanup is not advertised as archive success.
