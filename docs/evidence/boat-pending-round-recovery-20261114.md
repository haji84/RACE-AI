# Pending-round recovery candidate, 2026-11-14 JST

User explicitly requested durable recovery after bounded read retries fail.

The previous release retries a GitHub read within one job only. This candidate adds a separate source-free recovery phase: restore the failed owner's final checkpoint, decrypt and authenticate its already-saved P1 and RESULT, check the exact nested P1 and report/session counters, retain the unchanged originals in the existing AES vault and independently read them back. A separate derived control completes the pending round without rewriting the original run or predictions. Request counters and day baseline remain unchanged. A subsequent owner independently repeats the same verification before its source session.

The existing main launcher must be wired to call this recovery before dispatch, then independently re-read current history/control. Recovery failure must emit no dispatch permission and is retried by the existing schedule, not by rerunning an old forecast job. No new provider, model, scorer or scheduler is intended.

Scope is a same-day failed owner with uploaded P1 and RESULT and an authentic final checkpoint. Missing, corrupt or mismatched originals, source waits/refusals, unknown counters, cancelled runs, other SHAs and active writers remain HOLD. Past races are not regenerated. Video prediction and nationwide P1 completeness are unchanged.

Thirteen distinct local tests passed, including real encrypted fixture archives, local Git retention/readback and idempotence, a failed recovery invocation followed by a separate successful invocation, preserved 88-request history before the next charged request, source holds, foreign identity, missing/corrupt data and stale-day rejection. Full GitHub CI and main integration are still required; no live recovery success is claimed by this document.

Assembly note: a one-time isolated-branch workflow applies a seven-line hook only to the exact known original blob, tests it, commits only that hook and removes its own workflow. It cannot update main/production. Final PR CI must run on the resulting actual head, not merely the assembly commit.
