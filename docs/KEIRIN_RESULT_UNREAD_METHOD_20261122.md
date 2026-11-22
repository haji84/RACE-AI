# Current result-unread research method

The current displayed analysis uses `generate_evidence_analysis` in
`race_ai/keirin_nationwide_auto_generator.py`. Its sequence is source facts,
conditional six-phase scenarios, complete candidate pools, independent market
selection, then derived ticket counts. The current method ID is
`forward-phase-independent-pair-selection-20261122`. It corrects the preceding
display processor without changing the historical sealed-record entry point or
originals. This is a correction to the research method, not evidence of improved
prediction accuracy or profitability.

## Evidence and scenario constraints

The processor uses published points, marks, four-month win/place rates, H/B/S,
decisive moves, riding style, sourced affirmative attack intent, and a sourced
line hypothesis. Four-month aggregates are not a recent-form trend. Gear is
recorded without an unvalidated performance bonus. Missing points, including a
published zero, are unknown rather than zero ability. Unknown weather, bank
affinity, injury history and advancement rules are not invented.

Each tactical branch fixes INITIAL, BELL, FINAL_HOME, FINAL_BACK and
FOURTH_CORNER before any finishing candidate is considered. GOAL is derived by
replaying explicit adjacent overtakes from that corner; the ticket is GOAL's
first three cars. A simple follower pass keeps the original attacker second.
A fade branch preserves the attacking identity, places competing riders near
the front before the corner, then lets the two adjacent riders pass the fading
attacker. It no longer enumerates all hypothetical replacement winners/seconds.

After the branch's necessary pass, at most one additional evidenced adjacent
duel for second or third is represented. The challenger needs a stronger
published finishing indicator or explicit sashi evidence. This is a declared
untrained path restriction, not a claim that omitted race outcomes are
impossible. Remote riders cannot be moved to the front solely to match a ticket.
Missing lines stop B independently. A may still use ability evidence, but its
first five positions remain explicitly unknown and `attacking_car` is null for
`ABILITY_ONLY`. Its explanation does not claim a forward position or overtaking
path was generated.

## Independent ticket selection

Each branch scores its first/second pair before third-place alternatives are
created: head strength squared times second strength to power 1.3. A also
applies the square root of branch support; B applies full branch support and
local-movement fit. Thus A no longer gives a fade-only assumption the same
weight as an otherwise equal straightforward path. The coefficients remain
untrained research heuristics, explicitly recorded in the method metadata.

For three-car support, each branch's pair support is distributed among its
reachable thirds in proportion to third strength to power 0.8. Exact triples
use maximum support across branches. Two-car support independently uses the
maximum `pair_support_A/B` across branches for that pair; adding or duplicating
third-place candidates cannot raise it. Both pools are complete before either
market is selected. Neither support is a calibrated probability or expected
return, and current odds are not used to choose tickets.

There is no twelve-ticket cap or padding. One ticket and more than twelve are
both supported. The half-of-peak research window is retained, rather than tuned
to a desired count or to observed race results. If that window retains every
candidate in a multi-candidate pool, selection abstains with
`ABSTAIN_INSUFFICIENT_SEPARATION` instead of recommending the whole set. A field
of solo riders with identical effective scoring/role/start inputs also
abstains: car-number sorting and generated branch counts are not distinguishing
evidence. The signature uses computed head/second/third strengths,
`explicit_attack`, `explicit_sashi`, the effective lead/counter branch supports
and the S value actually used for initial ordering. Raw style, published mark or
comment metadata is already subsumed by those inputs and is not added again.
For example, removing a redundant attack comment from an otherwise identical
ALLROUND rider cannot turn an abstention into adopted tickets. All source facts
remain recorded in the feature audit. `selection_context.indistinguishable_solo_field` and
`selection.abstention_code` expose the reason for independent validation.

All candidates remain in `candidate_tickets` and `candidate_evidence`. Adopted
tickets alone appear in `ranked_tickets`, `ranked_2ren_tan` and `ticket_evidence`.
Selection reports candidate, excluded, held and adopted counts separately.
Above thirty adopted tickets, a review warning reports the amount at 100 yen
per ticket; it does not alter the count or recommend purchasing every candidate.

## Time, condition and confidence boundaries

`scripts/keirin_generate_result_unread_analysis.py` accepts a target date and
allowlisted local source files. It rejects target-result fields recursively,
preserves capture receipts, uses its actual generation clock and refuses an
existing output path. It does not fetch providers, create schedules, place bets,
or turn a retrospective calculation into a saved pre-cutoff original.

Condition notes bind race, car and name to the cited self-report. An explicitly
stated current-pain condition can create an independently labeled sensitivity
case excluding that rider from first place. Either independently selected
market can remain generated when the other market has no tickets. The baseline remains unchanged;
no diagnosis, medical recovery claim or numerical injury penalty is inferred.

`race_ai/keirin_research_stability.py` now connects the current forward research
route to the existing four-grade rule. New assessments use
`forward-research-coherence-20261122-v4`, identify the inherited threshold rule as
`research-coherence-v1`, and can return 低, 中, 高, or 激アツ. Missing or unsuitable
evidence remains 未評価. V3 introduced winner/pair/triple concentration and
selected-coverage criteria in place of v2's single-outcome stability metric.
V4 measures the leading four triples instead of six; it leaves the leading two
winner candidates, leading four pairs and all threshold percentages unchanged.
This is not a promotion of model weights or an accuracy claim.

The shared pure `grade_coherence_metrics` function in
`race_ai/keirin_confidence.py` owns the unchanged thresholds:

| Grade | Top-two winner share | Top-four pair share | Top-four triple share (3t) | Selected coverage |
| --- | ---: | ---: | ---: | ---: |
| 激アツ | 0.85 | 0.85 | 0.90 | 0.90 |
| 高 | 0.70 | 0.70 | 0.80 | 0.80 |
| 中 | 0.50 | 0.50 | 0.60 | 0.50 |
| 低 | Below the medium requirements | | | |

High and hot additionally require every major represented branch to be covered.
Two-car evaluations do not use the triple requirement. Every share refers to
this saved research representation, not a frequency observed in actual races.
V4 emits `triple_top4_share` (null for 2t), with no `triple_top6_share` field.
It passes that metric name explicitly to the shared grader and next-level
explanation. The shared grader's default and the formal sidecar stay on top six.

The forward adapter keeps the existing complete market pools. Exact triples use
the maximum existing `support_A/B` among their supporting scenarios. Pairs use
the maximum existing `pair_support_A/B`; they are not formed by summing third
alternatives. Normalize that complete market pool once, before consulting
selected tickets. Winner concentration sums this normalized support by first
car; pair and triple concentration sum the leading four pairs and four triples.
Selected coverage sums the same fixed support only for the actual saved tickets.
No ticket, scenario, model coefficient, or source support value is changed.
Four is a concentration window, not a cap of four adopted tickets.

The major-branch adapter is explicit because forward scenarios can contain
duplicate goals and multiple thirds. Each distinct market candidate with at
least 10% of fixed-pool support is major. Represent it by the actual supporting
scenario with the highest raw market support, breaking ties by `scenario_id`.
Also retain the highest-support actual scenario in each present counter family,
with the same tie rule. `HOLD` is the main branch; `COUNTER`, `FOLLOWER_PASS`,
`ATTACKER_FADE`, and `LATE_FINISH` map respectively to counterattack, follower
sashi, pace fade, and late sprint. The sorted union is `major_scenario_ids`;
those whose market goal is not selected form `major_uncovered_ids`. Both steps
use direct pair support for 2t. Extra third variants cannot inflate pair
concentration, coverage, or the grade. A tied representative ID can change, but
its represented pair and covered/uncovered state cannot change merely because
another third is described.

The evaluator requires complete, valid six-phase car orders, consistent goals,
distinct scenarios, and actual main/counter branches. It does not fill missing
positions or invent a counter branch. Essential source omissions, unavailable
lines, and unresolved line conflicts remain unassessed. The existing condition
evidence caution still limits a grade to medium; abstention remains low. A/B
agreement remains visible as a diagnostic, not an independent-evidence bonus.

Ticket count itself earns no bonus. Removing tickets cannot improve coverage or
the grade, and adding tickets outside the modeled pool cannot improve either.
Adding a supported outcome can improve actual coverage; therefore the former
v2 claim that all additions/removals leave the grade unchanged does not apply
to v3/v4. Strong concentration alone is insufficient when selected tickets omit
important branches. No real race is guaranteed to receive high or hot.

The result-unread envelope remains separate from the formal pre-cutoff sidecar.
It retains actual creation/assessment times and its original source/cutoff facts,
with `official_pre_cutoff_assessment_created`, guard-modification and result-use
flags false. No call to formal `assess_baseline` or `evaluate_ticket_set` is made,
and the formal 65-second guard is unchanged. Historical v1/v2/v3 packets and
sealed baselines retain their original version and bytes. Historical v3 replay
uses its original top-six metric, grade and explanation. A new v4 assessment
uses the actual assessment time, preserving the source analysis's generation
time and tickets; it is not backdated into an old forecast.

## Source-only verification

All committed tests use synthetic riders, comments and scenarios. Actual source
captures, generated predictions and private originals are not committed.
Historical replay tests use the exact public generator-source fixture
`tests/fixtures/keirin_generator_source_9aa01431.txt`, retained from canonical
commit `51bec791cc5be2b56f996934b4df8b51894d67d8`. Its SHA256 remains
`9aa0143192707733a9666f8d0dad70e589451f67943130796d3ed4af0387f413`.
The production historical verifier still rejects any different source bytes,
including the current extended module; its integrity check is not relaxed.

```sh
python -m unittest tests.test_keirin_evidence_selection tests.test_keirin_forward_scenarios tests.test_keirin_result_unread_method tests.test_keirin_nationwide_auto_generator -v
python scripts/keirin_generate_result_unread_analysis.py --self-check
```

The synthetic tests include a single-line source fixture that reaches hot for
both arms and both markets through the unchanged forward generator and ticket
selection. They also cover missing orders, omitted major branches, separate
markets, fixed-denominator subset behavior, actual timestamps, and an isolated
direct CLI check of the shared confidence import. This establishes reachable
software paths, not real-race accuracy or profitability.

The top-four regression uses six synthetic triples with top-six support of
100% and top-four support of 82%. With all major branches covered, v3 grades it
hot while v4 grades it high. The 90% hot boundary is unchanged. Separate checks
pin historical v1/v2/v3 output digests and confirm two-car entries change only
the unused null triple metric's name.

The existing persistent-core PR workflow runs these commands. No new workflow,
schedule, provider, permission or production weight promotion is introduced.
