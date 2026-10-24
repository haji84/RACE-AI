# Bounded controller repair trial

This trial uses the already pinned local model to propose changes to the existing completion controller, not a racing algorithm. It is not a general autonomous developer.

Two dependent targets: reject empty/malformed acceptance in the exported completion predicate; then reject whitespace-only evidence references. The existing catalog validator requires nonempty acceptance, so the standalone predicate must not certify an empty list through vacuous truth.

Independent tests first reproduce each defect. Model responses are restricted expressions in strict JSON, parsed against a fixed boolean-expression grammar. Only two exact source sites in an isolated copy may change. No generated patch is committed or deployed. Existing controller tests and cumulative acceptance tests must pass before selecting the next task. At most two attempts per task; an unverified result blocks progression.

The fixed model/runtime pins and loopback transport are reused. Tests run without credentials; no Actions write, repository writeback, external data, deployment, new model/service or main merge. The existing canonical file remains unchanged. Artifacts, if produced, are bounded test evidence rather than permanent canonical state.

Verification: expected RED on the unchanged source, parser rejection/transport self-tests, independent review, then one bounded live-model trial and current-head regression. A successful patch remains a candidate awaiting separate review/integration.
