# BOAT current, next and previous grade plus observed return research (2026-11-09)

This source-free research addition prevents the model and user interface from
mistaking an officially published B1 current grade for a full assessment of
a competitor's ability.

## Evidence and precise dates

The BOAT RACE official grade guide establishes two application periods:
January 1 - June 30 and July 1 - December 31. The corresponding assessment
periods are May 1 - October 31 and November 1 - April 30.

On November 1 2026 the organizing body announced grades for the
2027-1 application period (January 1 through June 30 2027), following
assessment May 1 - October 31 2026. Its own release explicitly said
formal finalization followed a November 1-7 review and an allocation
committee meeting. Publication is not by itself proof that an individual's
grade was finally certified on November 1.

Official sources:
https://www.boatrace.jp/owpc/pc/extra/enjoy/guide/jiten/07/y_048.html
https://www.boatrace.jp/owpc/pc/site/news/2026/11/52229/

## Existing RACE-AI source, no extra provider GET

Existing race_ai/boat_racer_term.py already parses the source-native official
fan-term fixed-width records. Each has:
- racer_id, recorded_class, term / assessment-period start/end,
- previous_classes (3 unassigned historical grade slots),
- national win rate, 2-ren, mean ST, actual course counts,
- source document identity and record SHA.

**Assessment period != application period.** At 2026-11-09, application term
is 2026-2. The newly announced next application term is 2027-1. Code must
never take the most recently published term alone and claim it is the
CURRENT grade. Read stored snapshots by term + application dates + as-of.

The new pure Node module receives only source-delivered normalized rows,
requires 6 unique registered racer IDs matching their boat numbers, and
separates: CURRENT grade, NEXT grade ANNOUNCED_PENDING versus
OFFICIALLY_CONFIRMED, past A-grade evidence from earlier official terms and
the current term's previous_classes slots, and recorded previous/next
application windows. The prior three slots can prove "former A", but without
a dated history they cannot support an invented period or exact date.

## Long recorded race gap is not a known medical leave

From authenticated retained actual starts only, compute consecutive start
dates and detect a long observed interval (research threshold configurable;
60 days is a RESEARCH setting, not an official leave rule).
A recent subsequent race with a short post-gap sample marks
RECENT_RETURN_AFTER_OBSERVED_START_GAP, NOT a confirmed illness, leave,
penalty or direct reason for demotion. Incomplete historical archive coverage
can create artificial gaps; the module explicitly marks lack of independent
coverage proof. Finish F/L/other non-numeric cases do not enter 1st/3rd rate.
Current B2 after former A is flagged as well as B1.

## Acceptance checklist

Source: race_ai/boat_grade_transition_research.cjs.
Tests: tests/boat_grade_transition_research.test.cjs;
       tests/test_boat_six_way_node_contract.py
Display: standalone local-only six-course research viewer. Never publish
private URL, key, raw records or entrant history.

- Local V8 synthetic cases must reject after-as-of announcements,
  premature confirmation, duplicate official term versions, current
  grade conflict with the saved program, future results, and forged gaps.
- Existing native BOAT forecast, P0/P1 coefficient and model families stay
  byte-exact; do not introduce an automatic B1->A1 ability boost.
- At owner-controlled safe source window, independently authenticate existing
  official fan-term snapshots, as-of availability and previous term records
  inside existing GitHub Actions key/vault. No new GET or cap resets.
- Test both partial and complete historical coverage and publish counts of
  CURRENT/NEXT/FORMER_A/OBSERVED_GAP/UNKNOWN per race without names.
- Separately evaluate added flags on time-frozen pre-cutoff real races,
  controlling for recent 10/30 starts, grade, sample volume, motor and ST.
  Promote no probability/Top8 improvement without holdout and real
  prospective comparison. Never claim a long race gap is the proven
  cause of a lower class.

This is an analysis feature, NOT a new betting prediction family, producer,
workflow, cron, PR, source collector or production auto-promotion.
