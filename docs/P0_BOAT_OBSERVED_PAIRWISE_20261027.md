# Missing-aware measured BOAT experiments and same-race comparisons
2026-10-27 JST. The Owner explicitly authorized autonomous implementation after
the coverage correction. This is a separate experiment, not replacement of FULL75,
the original four models, their coefficients, or stored predictions. The final
four-sport all-race/98% goal is unchanged and unachieved.

## Choice and scope
Reject making seven historical/exhibition blocks mandatory and reject filling
absent observations with average or zero data. Use fixed-weight **observed pair
contrasts** with explicit uncertainty and no dynamic weight normalization.
This is a new, untrained engineering hypothesis, not transferred validation from
the older coefficients. Independent design criticism: Race37 reviewer, retained
in the PR72 worktree artifacts/race37-critic-*.
Research inference is useful before formal external time authority exists, but
its output is permanently ineligible for official performance scoring.

## Input and mathematical contract
Exact JSON snapshot schema RACE_AI_BOAT_OBSERVED_PAIRWISE_V1; scope SYNTHETIC_ONLY
or OPERATOR_SUPPLIED_RESEARCH. Race: race_id (boat:YYYY-MM-DD:boatrace-jcd-XX:R),
event_date_jst, venue, race_revision, sales_cutoff_at, as_of, stage (P0 or P1),
race_source_id referencing one of the supplied sources. These are flat root keys.
Six distinct lane/registration identities. Root sources[] and participants[].
Each source: source_id, source_url, source_sha256, source_rights_ref,
published_at (nullable), captured_at, evidence_basis
(SOURCE_PUBLISHED_AT_CLAIM or CAPTURED_BY_CLAIM). Unique source IDs and hash/URL
identities. Evidence times are claims and must be <= as_of < scheduled cutoff;
when publication exists it must be <= captured_at. First basis requires nonnull
publication. Second basis keeps publication null. Source URL query/fragment and
userinfo prohibited; HTTPS, or synthetic://fixture for synthetic scope.
Research source permission callback must return exact True for analysis; no
input flag substitutes for it. Freeze/availability/source authenticity are never
granted here. Deep-copy inputs before any callback; callbacks cannot change the
detached scored/hashed snapshot.

Each entrant: lane, registration_no, features and missing maps. Features plus
missing keys exactly partition the eight names; a feature has value, sample_n,
source_id, transform_id. Each missing entry is one enum:
MISSING, NOT_YET_PUBLISHED, SOURCE_UNAVAILABLE, RIGHTS_BLOCKED,
UNRESOLVED_DISPOSITION, F, L, NO_PRIOR_SAMPLES, NO_VERIFIED_COURSE.
A source-backed historic mean has positive integer sample_n; B aggregate rates
may have sample_n=null when provider gives no denominator (never invent it);
exhibition instantaneous fields require sample_n=null.
History means are upstream strict measured projections, not fabricated ratings.
Each includes history={window_id,total_n,ok_n,f_n,l_n,missing_n,unresolved_n}.
Nonnegative disposition counts sum to total_n; sample_n=ok_n>0. The window ID
and counts are provenance claims, not independently authenticated membership.
The same entrant/source/window/transform cannot assert contradictory values or
counts across recent/course fields; distinct windows require distinct identities.
ST means must preserve upstream OK/F/L/MISSING counts; a bridge must not invent
lost finish dispositions or use a finish mean from a window with unknown finish.

Order, range, orientation, model A/B weights:
national_win_rate [0,10] up 1.25/.75;
motor_top2_rate [0,100] up .75/.50;
recent_mean_finish [1,6] down 1/.80;
course_mean_finish [1,6] down .65/.35;
recent_mean_st [0,1] down .35/.90;
course_mean_st [0,1] down .20/.35;
exhibition_time_seconds [1,20] down .35/.70;
exhibition_start_seconds [0,1] down .20/.50.
Map raw ranges linearly to z in [0,1], larger is favorable.
For each model, u_i = sum_k (w_k/6) sum_{j!=i, both values present}(z_ik-z_jk).
strength_i=exp(u_i). Reuse existing legacy_boat_rank.plackett_luce; sort all120
normalized model scores descending then lexical ticket; retain maximum8.
With complete data, centering cancels and PL equals the fixed weighted utility.
Missing pairs give no contrast, which is **a neutrality assumption**, not a
measured average. Asymmetric missingness can advantage sparse entrants; disclose
per-feature observed counts, per-entrant comparison counts and missing reasons.
No learned/calibrated probability, confidence, benefit, or accuracy claim.

Calculate conservative utility completion bounds by allowing missing z in[0,1]:
known/unknown [z-1,z], unknown/known [-z,1-z], both unknown [-1,1], both known
exact contrast. Add weighted bounds/6. These are domain-completion sensitivity
bounds, not total measurement-error or calibrated confidence intervals.
P0 rejects all present exhibition features. P1 requires >=1 numeric exhibition
feature but may have zero exhibition contrasts. Neither stage label proves
physical exhibition chronology. A new P1 never rewrites P0.
No discriminatory utility (including all equal observed values) -> uniform scores, deterministic Top8, status
UNINFORMATIVE_TIE_BREAK; report informative coverage separately from output rate.
Informative means the exact resulting utilities differ, not merely that an
observed feature or nonzero pair contrast exists. Opposing contributions may cancel.
Missing optional data alone never raises NO_FORECAST. Malformed identity, source,
schema, permissions, race revision or time remains an explicit hold/error.

## Outputs, reuse and immutable comparison
Two new IDs boat-observed-pairwise-factor-v1 and boat-observed-pairwise-start-v1,
version0.1.0-UNTRAINED. Both bind SAME snapshot hash, race/revision/as_of/stage.
Pure function predict_pair(snapshot, *, allow_source=None). No networking/storage.
Output includes original missing states, source evidence basis, model spec digest,
candidate scores, Top8, utilities/completion bounds and contrasts. All output
hashes canonical. Always trained=false, calibrated=false, official_prediction=false,
source_authentication=false, independent_availability_verified=false,
result_or_cutoff_proof_eligible=false, purchase_decision=NO_BET.
An eventual proof-admitted profile needs a new invocation, not flipping these flags.

Comparison predeclares the common target race and model roster and result revision
policy. Later each stage fixes one as_of/snapshot for both models, and both use the
same actually issued result revision. Future outcome content is not known in advance.
P0 A vs B and P1 A vs B are algorithm comparisons;
P0 vs P1 is later-information change. Never select a different race/as_of to
complete a pair. Existing ledger/result audit semantics are reused. Missing or
late forecasts remain in the all-eligible denominator; paired subset supplementary.
Research summaries clearly cannot become formal Hit@8_all through caller flags.

## Acceptance and deferred work
Test complete-data equivalence, each missing field/entrant, all-missing, F/L,
zero-ST, invalid/nonfinite/bool, callbacks mutating input, late sources/cutoff,
odds/result schema injection, deterministic120/8, no input mutation, P0/P1,
paired same-race scope/full denominator, rejected incompatible stages/revisions.
Reuse fresh lawful B/current-racelist source for one bounded real research inference
after independent caller review; retain hashes and aggregate outcomes privately.
No old completed K24/source/CI/backup replays.
Formal real prospective E2E still requires audited independent availability and
private immutable retention/time/readback. No cloud resources, schedules, paid
services, Access/secret changes, production, betting, or self-approved main merge.
Device and account cost acceptance remain deferred by Owner.

## Local validation record
New candidate25 tests pass after separately recorded output-alias and same-window
lineage regressions. Independent arithmetic probes covered24 fictional inputs and
1824 numerical comparisons. Actual pinned candidate/bridge/comparator integration
passed complete/partial/all-missing/no-output fictional scenarios.
The final Windows full suite ran276 tests in21.564s:274 passed; two unchanged
POSIX-mode assertions expected0600 but Windows reported0666. These failures are
retained, not skipped or presented as a passing Windows suite. Exact-head Linux
CI is tracked separately in Issue68. None of this verifies real prediction accuracy.
