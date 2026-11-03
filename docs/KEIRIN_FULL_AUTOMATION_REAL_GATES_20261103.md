# KEIRIN all-race automation: verified current state / acceptance (2026-11-03 JST)

## User goal
All races, every day: auto-discovery -> pre-cutoff no-odds forecast (maximum 8 fixed picks) -> immutable private forecast receipt -> official finalized result -> unchanged forecast comparison -> PDCA -> next race forecast. No reliance on ChatGPT hourly tasks, no auto-wagering.

## What actually passed
- Protected main [PR #74](https://github.com/haji84/RACE-AI/pull/74) merge `5fe507f84eecdeb4a7f3143c4c42e3b036cb006f`: dynamic daily discovery from one dated Kdreams index GET. Unit 11/11, plus main required unit 24/24 passed. Cron at 05:08 and 07:08 JST; first `event=schedule` successful runtime has not yet been observed as of 2026-11-03 11:32 JST.
- First-party formatted day roster verification run [#41565520165](https://github.com/haji84/RACE-AI/actions/runs/41565520165): 2026-11-03 8 venues, 76 races, venue counts {12:12,36:7,38:7,45:12,53:7,63:12,83:12,84:7}. The generated daily output deliberately marks missing official cutoff, forecast, and result separately. It is NOT independent nationwide completeness proof.
- Legacy single-result technical probe [#41558697314](https://github.com/haji84/RACE-AI/actions/runs/41558697314): 2026-11-03 Odawara 1R third-party candidate 6-1-5, 11,480 yen/100 yen; NOT independently authenticated by official organiser. This does not establish recurring feed rights.
- Actual PR71 algorithm on synthetic riders -> PR72 owner private callback storage passed [#41561632885](https://github.com/haji84/RACE-AI/actions/runs/41561632885): synthetic 36/36. This did NOT execute a real race's pre-cutoff prediction or external timestamp receipt.

## Hard runtime blockers observed rather than assumed
- RACE-AI is public. A writable **private** durable artifact or encrypted forecast state cannot be faked using public plaintext. One-time GH Actions private-store readiness run [#41566843301](https://github.com/haji84/RACE-AI/actions/runs/41566843301) confirmed `RACE_AI_STATE_KEY_PRESENT=false` and `RACE_AI_PRIVATE_STORAGE_TOKEN_PRESENT=false` as of 2026-11-03 11:33 JST. Tool connection does not expose GitHub Secret management; do not commit raw forecasts to the public repo.
- PR71 requires 8 common + 4 KEIRIN rider features, environmental observations, timestamps and source refs. 2026-11-03 Kdreams racecard one-page [#41566174728](https://github.com/haji84/RACE-AI/actions/runs/41566174728) returned HTML and some labels but a complete valid per-rider as-of snapshot has not been authenticated and was NOT transformed into a model input. Invented substitutes forbidden.
- No live official confirmed 3連単 (with refund/tie/correction chain) ingested from an independently checked source and tied to an immutable original. Third-party result candidates remain research only.
- Main scheduled workflows `event=schedule` had zero recorded runs at 2026-11-03 11:32 JST; a YAML cron setting is not proof the platform actually executed it. Verify future scheduled run independently.

## Required first real complete pass
1. Private owner-runner for forecast originals: preferably encrypted artifact state with a valid Actions Secret, or an already owner-authorized private storage backend. Do not use `habuAI-eval-vault` for unrelated keirin work without owner authorization; don't expose private forecasts on GitHub public branch.
2. A real 7/9-rider pre-cutoff observation set with all strict PR71 fields and official cutoff. Read source terms separately from the personal research scope. Reject missing critical data, do not fabricate.
3. Actual PR71 forecast before future official cutoff, private append-only persistence and external timestamp readback before cutoff.
4. Independently confirmed official/authorized result + 100-yen payout with source identity/date, refund and revision, compare original unchanged Top8, then dispatch next forecast if enough time; fail closed otherwise.
5. Multi-day automated schedule, event state across runs, 0 missing target-race records; A/B forward test and proper missing-denominator treatment.

## Rule
Do not declare FULLY_AUTOMATED until an actual future race has executed 1-4 and at least one scheduled GitHub run is independently checked. Current status: DAILY_DISCOVERY_ON_MAIN, REAL_FORECAST_PDCA_E2E_NOT_PASSED.