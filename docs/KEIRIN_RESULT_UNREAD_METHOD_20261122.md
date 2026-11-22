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

`race_ai/keirin_research_stability.py` grades the complete candidate universe,
not selected ticket coverage. Adding tickets or rewording a scenario cannot raise
the grade. Two-car confidence uses the same direct pair support as selection.
These are provisional hypothesis-stability grades. Current assessments use
`forward-scenario-stability-20261122-v2`. Version 1 imposed an unwanted blanket
medium ceiling; version 2 removes it without changing the existing concentration
thresholds or candidate support calculation. A high grade requires the most
supported single outcome to have at least 0.40 of the whole 3T candidate support,
or 0.55 for 2T, and the A/B top outcome must agree. The medium thresholds remain
0.15 for 3T and 0.25 for 2T. These are uncalibrated design rules, not hit-rate
boundaries. A high grade describes concentration in the modeled universe and
does not establish predictive accuracy. Each current explanation states its
observed support share and the applicable unchanged thresholds.

Essential source omissions or conflicts remain unassessed, the existing
condition-evidence caution still limits a grade to medium, and an abstention is
low. Adding or removing selected tickets does not change the grade. Historical
confidence records and the sealed baseline are preserved with their original
version; they are not relabeled as version 2.

This result-unread evaluator currently assigns low, medium, and high, plus
unassessed when necessary. Its hot-grade path is not implemented. The separate
four-grade evaluator in `race_ai/keirin_confidence.py` uses different metrics
and source/time contracts; it is not connected to this current research route.
Its four grades are also provisional research coherence, not calibrated winning
probabilities. Version 2 does not invent a hot threshold or substitute that
different evaluator merely to populate a high/hot filter. Removing the blanket
ceiling alone does not imply any real race will qualify as high.

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

The existing persistent-core PR workflow runs these commands. No new workflow,
schedule, provider, permission or production weight promotion is introduced.
