# KEIRIN.JP official per-race result connection check, 2026-11-03

## Intent
Owner requested a real official result connection for event-driven result -> PDCA -> next prediction. This is one-race, private-research, technical transport observation. **It is not a continuing provider feed, a grant for commercial ML training or a completed 24h pipeline.**

## Confirmed official linked endpoint
Kokura Keirin's official website publicly links to this exact official result route:
`https://keirin.jp/pc/dfw/dataplaza/guest/raceresult?KCD=81&KBI=20260321&RNO=11`
Original host link from https://www.kokurakeirin.com/ (its 2026-03-21 result announcement).

KEIRIN.JP official policy: https://keirin.jp/pc/dfw/portal/guest/policy/index.html
It permits uses within copyright-law exceptions including private copying, but disallows unlicensed copying/repurposing beyond them and unlicensed commercial extraction. **No verified bulk harvesting/training permission**.

## Implemented on existing Draft PR #72
- `race_ai/keirin_official_result_page.py` validates only the KEIRIN.JP result route; bounded 600KB, 8-second, 1GET, no redirect, no cookie or odds, no retries, no raw HTML stored.
- `scripts/keirin_official_result_probe_once.py` CLI for explicit, one-race, private research checks. Logs only response metadata and safe structural markers, never raw result text.
- `tests/test_keirin_official_result_page.py` offline checks, including explicit user intent, date/venue/race validation, bad redirects, MIME limits, legacy Japanese encoding and safe HTTP error code.
- `.github/workflows/keirin-official-one-shot-probe.yml` a one-shot GitHub branch workflow (only triggered when its own file changes), **not a recurring collector**.

## Actual GitHub Actions observations
- https://github.com/haji84/RACE-AI/actions/runs/41556970324 : 11/11 synthetic transport checks passed; **real official result GET returned HTTPError** (the first diagnostic did not include HTTP status). Overall workflow failed.
- https://github.com/haji84/RACE-AI/actions/runs/41557206587 : 12/12 synthetic transport checks passed; **real official result GET returned HTTP 500** for the historically linked URL. Overall workflow failed; source body was not captured or copied.

Thus **technical connection to the individual-result endpoint from this GitHub runner is NOT working**. We did not forge an official result or release a forecast refresh.

## How this fits existing RACE-AI
The already implemented `race_ai/keirin_result_delivery.py` can normalize an authorized delivered result JSON input into existing append-only revisions; `race_ai/keirin_result_reactor.py` produces an idempotent next-race outbox intent on independently validated confirmed result events. These are separate from the HTTP probe, because the legacy endpoint returned HTTP 500 and its HTML structure was not retrieved.

Next verified action: obtain a stable, authorized machine-readable result stream or an accessible official single-race response; test and implement a provider-specific body-to-normalized-result adapter with a real fixture, then connect its authenticated event to the existing result-delivery and reactor contracts. Verify source URLs, data rights, allowed frequency and storage/analysis/training, and one future race from original pre-cutoff freeze to final result. Do not turn on unattended polling or assert formal Hit@8 until passed.

Restrictions kept: no new PR, no main merge, no automatic betting, no provider bypass, no secrets/source records on public GitHub, no prediction rewriting, no new external charges.
