# Bounded sixteen-request probe: approved spec and implementation plan

**Goal:** Add one explicit fixed-attempt normal-UI probe profile capped at16
requests, within the existing collector maximum32, without changing legacy8.

**Authorization:** The owner requested continued implementation. The parent
approved this design and its current-day and historical modes on2026-11-07;
there is no further design-approval gate for this scoped implementation.

**Architecture:** A new V4 request and distinct sixteen-probe AES schema, MAC
domain and round bind one original case, exact normal URL/terms/native/checkpoint
pins, budget16 and actual owner/run/save clocks. Existing readers and the runtime
collector are reused. Legacy V1/V3 probes remain exactly8; old MACs, evidence shapes,
request digests and defaults remain compatible. No new model, workflow or schedule.

**Spec:** The approved parent task is preserved here: current-day16 uses collector
manifestV2; explicit historical16 uses manifestV3 with actual acquisition day,
  original event day1..7 days earlier. Both new modes use the existing capture-day
  midnight expiry rule; initial authorization must have at least600seconds. The
sixteen limit is fixed, not a parameter admitting12/32 or arbitrary budgets.

## Constraints and evidence boundary

- One original same-sport case/normal URL; original terms, four native pins,
  checkpoint/prior supersets and exact allowed static-cache bytes are preserved.
- The new pure issuer authenticates every actual prior journal and completed
  producer receipt. Only the exact fixed old UNKNOWN is exempt from known-outcome
  requirements; it permanently retains actual_count=None and upper_bound32.
- All known401/403/429, DENIED/host-stop markers, any new uncertainty, missing
  journal/outcome or changed original blocks issuance and runtime admission.
- Require at least1h after the latest actual prior terminal/save boundary+1s,
  actual current issuance, at most1h expiry, same-HEAD/run successful full first
  attempt, exact attempt2, fresh consumed path and create-only parent publication.
- Runtime consumes existing authority only. No provider calls, owner-key reads,
  grant issuance, public request/plan change or remote operation is part of tests.
- Keep maximum32, .825s spacing,85s elapsed cap,12s timeout,2MiB per response,
  route policy, eight-race limit and separate8MiB quarantine bound unchanged.
- Continuation derives8 or16 only from the authenticated original capsule's
  explicit profile. It must not infer authority from a journal's budget. The
  exact limit is replayed through complete ledger, raw wire, case/RESULT joins
  and later validate_prior. Zero-result probes cannot unlock continuation.
- Observed offline wire counts establish only that8 was insufficient for the
  observed normal UI.16 is an internal reviewed cap, not a claimed provider quota
  or proof of a successful real result. NET0 and synthetic fixtures are not live
  source acquisition, real teacher availability or completion of the remaining11.

## Files and test sequence

1. New `race_ai/all_existing_model_official_probe16.py` owns strict V4 request,
   pure issuer, distinct codec/MAC and retained-evidence validation. Reuse narrow
   existing binding helpers with legacy defaults unchanged. Add failing tests
   for current/historical16, all-prior receipts, clocks and profile mismatches.
2. Update existing recovery dispatcher/runtime wrapper and collector capability
   admission only. First attempt remains HOLD/zero dispatch; fixed attempt2 and
   preflight/readback use actual new-profile authority. Test before implementation.
3. Extend continuation with an explicit authenticated-source profile branch,
   retaining exact legacy evidence output for8. Pass the verified limit through
   ledger/wire/proof checks and later validate_prior; test a real fixture MAC/AES
   complete16 probe with actual requests above8 and a matching normal raw RESULT.
4. Run focused old/new Python and unchanged Node policy/budget regressions, check
   compile/diff, obtain independent review, and make a local commit for parent
   integration. No remote publication or real source execution.

## Review focus

- Wrong profile/plan/body/reservation/raw-index cap or count above16 must reject.
- Legacy8 cannot acquire16 by changing a field or using a new request as an alias.
- Prior journal arrays must exactly cover pinned IDs; no denial/UNKNOWN omission.
- Original label/case/roster/cutoff/source and full raw RESULT proof must agree;
  pending/special/corrected later revisions cannot become a normal probe.
- Historical true capture/target-day and midnight rules, expiry before each wire,
  stale first-attempt receipts and replayed consumed paths remain fail-closed.
