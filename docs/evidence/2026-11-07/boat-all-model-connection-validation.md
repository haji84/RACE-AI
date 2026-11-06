# BOAT active entrants, native model execution and owner view

The requested path uses the existing GitHub-only deployment. It does not
restart the active source worker or change canonical PDCA state. New runtime
inputs and additional model outputs are encrypted for the existing owner key.

## Source and model validation

- The owned racecard adapter parsed 26 actual saved official pages spanning
  all 24 venue codes. These are layout/identity replays, captured after those
  historical deadlines, and are not new pre-cutoff forecasts.
- The two former Nov 6 failures at venues 12 and 14 came from additional SG
  navigation tabs. The owned parser binds the selected race and accepts that
  layout without weakening the day, registration or cutoff checks.
- An explicit withdrawal selects the physical lanes that remain entered.
  Missing exhibition data for an entered racer remains pending. Three to six
  active entrants are supported, with P(N,3) ordered tickets and up to eight
  displayed picks. Existing six-entrant calculations remain compatible.
- The retained history has 270 imports over 90 event days (2026-08-07 through
  2026-11-04). All logical tables match the canonical retained private source.
  The racer registry has 1,643 records and 9,858 course records.
- The genuine sparse ranker was fitted on 105 actual labelled races. Another
  35 were excluded from fitting and used only for retrospective validation
  ordered by actual capture availability. This is not proof of prospective
  accuracy improvement.
- A private execution using the actual Nov 7 P0 inputs produced 660 native
  outputs across 132 races (four shared families plus the fitted ranker).
  This local dry run is not an independent physical save receipt.
- The seller strategy still requires genuine national and same-frame rating
  points. The BOATERS placing fractions inspected in this session do not have
  the required metric semantics. Missing data are reported rather than
  converting percentages into invented rating points.

## Preservation and display

- The initial unified private view contains 288 races and 1,754 retained
  forecast originals, including 134 already-saved learned research shadows.
  It binds names to all 1,728 participant entries using actual official B
  program archives and verified registration identities.
- Nov 6 retains 144 final results and 12 cancellations after union. Seven
  rows with two original one-minute cutoff variants have explicit raw-source
  display reconciliation; the original clocks and formal scoring stay intact.
- The V4 encrypted feed retains the initial forecast anchor and an inventory
  of every full saved prediction. An update may append originals and enrich
  names, but cannot remove or alter a prior saved prediction dictionary.
- P0 and P1 issued-model inventories are separate. A saved morning forecast
  cannot suppress that family's exhibition forecast. A saved five-model
  baseline cannot suppress missing additional families for the same race.
- Actual generation time, artifact save time and source code identity are
  retained separately. Saving after the deadline does not become an eligible
  pre-cutoff forecast. Older forecasts without a recorded model version retain
  that unknown value and use a verified saved-code identity for display.

## Live verification

The existing active source run remains untouched. New collector behavior can
only apply to a successor using the reviewed source commit. Current exhibition
predictions require the official exhibition to be published before the cutoff.
The display-only publication path makes no requests to official race sources.
Its real encrypted execution/save/readback and browser results are recorded
after publication, rather than inferred from this document.

### Verified live publication

The exact implementation `89a7c46688317e908022b261ca8cada3a0655155`
completed [Actions 42280037707](https://github.com/haji84/RACE-AI/actions/runs/42280037707).
It executed the actual retained Nov 7 inputs for 132 races and saved 660 new
P0 forecasts from five native families. Artifact `13534587867` contains only
owner ciphertext; its ZIP digest is
`133f8b0d46c71b98a3dc46f615b522061695ae3f376671dcc948c5a4d6f93b21`
and actual GitHub creation time is `2026-11-06T19:30:27Z`. Independent
readback verified that ciphertext before admitting the display projections.
All 660 displayed save clocks match that actual artifact time and precede
their race cutoffs. Old source snapshots retain their original capture times;
the additional forecasts have a new actual generation/as-of time.

The existing owner URL loaded feed generation 4, commit
`2101323772c89ca4f986e2ad37fa2b2e22b075bb`, cipher
`d003f85be14a874579e59448c4c8ddac1333d0839bae7dedc80196fc06d4877c`.
It contains 2,414 originals over 288 races. Nov 7 has seven P0 families for
each of 132 races; Nov 6 retains 144 final results and 12 cancellations.
Every initial saved-original dictionary remains unchanged. Actual browser
checks at 390 and 1440 pixels verified names, generation 4, editable day
budgets and the 1,000-yen race simulation, with no view key in requests or
browser storage.

The same display-only job restored the existing first P0 and all required
earlier original archives using its current Actions identity. This was a
read-only GitHub recovery check, with no official source GET, regenerated
forecast, replacement state or source-worker restart. The source job was
skipped. This demonstrates current restore access and does not diagnose the
HTTP status of the earlier failed workers.

The exact-head [Viewer CI 42280047254](https://github.com/haji84/RACE-AI/actions/runs/42280047254)
and [AUTORACE CI 42280047180](https://github.com/haji84/RACE-AI/actions/runs/42280047180)
passed. Local verification also passed 94 affected Node tests and the real
saved-view simulations (260 model/budget combinations plus browser scenarios).
The separate private progress-runner initially contaminated one stdout-capture
test; the unmodified affected CLI module and new auth tests passed on rerun.
The real CI uses the normal test runner and passed its full Python discovery.

### Source original protection before activation

The bounded national source path now protects all five public producer steps:
first P0, supplement P0, five-model P1, the entire result folder (including
nested original ZIPs and CSV), and the entire continuity folder. Public
artifacts contain only `private-original.enc`. The existing configured owner
key is used in a dedicated archive encryption domain, with no key replacement.

All forecast/recovery/history/training/private-capture/feed readers accept the
new wrapper after authenticating the actual outer GitHub ZIP digest and its
repository/run/head/kind. Original native member bytes, member SHA and actual
GitHub save time stay unchanged. Legacy artifacts remain readable; legacy
reading also works when the optional cryptography runtime is unavailable.
Protection failures stop uploads rather than fall back to clear originals.

The affected archive, recovery, history, private-view, workflow and checkpoint
regression set passed 274 tests. An independent read-only review passed 18
focused crypto/reader tests and found no remaining blocker after the optional
import fix. Dormant one-shot workflows use separate triggers and are not
reactivated or covered by this national source activation.
