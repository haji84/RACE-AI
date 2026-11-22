# Current result-unread research method

The current displayed analysis uses `generate_evidence_analysis` in
`race_ai/keirin_nationwide_auto_generator.py`. Its sequence is source facts,
conditional six-phase scenarios, complete candidate pools, independent market
selection, then derived ticket counts. It replaces the fixed-count display
processor without changing the historical sealed-record entry point or originals.

## Evidence and scenario constraints

The processor uses published points, marks, four-month win/place rates, H/B/S,
decisive moves, riding style, sourced affirmative attack intent, and a sourced
line hypothesis. Four-month aggregates are not a recent-form trend. Gear is
recorded without an unvalidated performance bonus. Missing points, including a
published zero, are unknown rather than zero ability. Unknown weather, bank
affinity, injury history and advancement rules are not invented.

Each scenario records all six phases and the original attacking car. A simple
follower pass keeps the attacker second. A separate attacker-fade branch moves
that actual attacker below the first two. Second and third candidates require
line-position or other-line-front routes; full-field arbitrary permutations do
not share a generic explanation. Missing lines stop B independently. A may still
use ability evidence, but its first five positions are explicitly unknown.

## Independent ticket selection

For an exact three-car finish, repeated scenario descriptions use the maximum
support rather than multiplying the same evidence. Two-car support is the sum
over distinct third-place alternatives in the complete candidate pool, before
any three-car selection. Both markets then retain candidates with at least half
their own maximum support. This is an explicit untrained research rule, not a
calibrated probability, expected-return calculation, or fitted accuracy claim.

There is no twelve-ticket cap or padding. One ticket and more than twelve are
both supported. Ties are not cut at an arbitrary count. Selection records its
candidate/excluded counts, rule, scenario IDs and reasons. Above thirty tickets,
a review warning reports the amount at 100 yen per ticket; it does not alter the
count or recommend purchasing every candidate.

## Time, condition and confidence boundaries

`scripts/keirin_generate_result_unread_analysis.py` accepts a target date and
allowlisted local source files. It rejects target-result fields recursively,
preserves capture receipts, uses its actual generation clock and refuses an
existing output path. It does not fetch providers, create schedules, place bets,
or turn a retrospective calculation into a saved pre-cutoff original.

Condition notes bind race, car and name to the cited self-report. An explicitly
stated current-pain condition can create an independently labeled sensitivity
case excluding that rider from first place. The baseline remains unchanged;
no diagnosis, medical recovery claim or numerical injury penalty is inferred.

`race_ai/keirin_research_stability.py` grades the complete candidate universe,
not selected ticket coverage. Adding tickets or rewording a scenario cannot raise
the grade. These are provisional hypothesis-stability grades. The current method
does not issue a hot grade without the missing condition and accuracy evidence.

## Source-only verification

All committed tests use synthetic riders, comments and scenarios. Actual source
captures, generated predictions and private originals are not committed.

```sh
python -m unittest tests.test_keirin_evidence_selection tests.test_keirin_result_unread_method tests.test_keirin_nationwide_auto_generator -v
python scripts/keirin_generate_result_unread_analysis.py --self-check
```

The existing persistent-core PR workflow runs these commands. No new workflow,
schedule, provider, permission or production weight promotion is introduced.
