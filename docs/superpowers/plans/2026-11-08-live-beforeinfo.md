# Live beforeinfo repair implementation plan

> Implement inline with the existing isolated worktree and one independent final code review.

**Goal:** Show automatically collected official exhibition and weather facts instead of leaving the pre-race tab at the morning forecast's empty fields.

**Architecture:** Reuse the official HTML parser, authenticated incremental state, existing five-minute Actions workflow and encrypted saved-view feed. Retain new captures in the incremental encrypted packets and attach a separate mutable `live_boat_observation` record; no original forecast field or existing sidecar is rewritten. Share the existing 12-request run budget and source waits with result collection.

**Constraints:** GitHub only; no provider, permissions, model execution or financial changes. Preserve forecast inventory, result observations/history, all portraits and current UI. Public verification contains counts only. Official identity and all six registrations must match before attaching facts. Future information must not enter an earlier forecast.

**Review focus:** Wrong race/registration cannot attach; empty exhibition retains available weather and retries; rate limits survive the next run; a failed fetch retains clearly timestamped previous facts; older encrypted views and model/budget selections remain readable.

- [x] Trace production collection, private state, feed and preview rendering. Reproduce the missing connection; baseline 40 context tests pass. A bounded official capture parses six exhibition times and weather with the existing parser.
- [x] Add failing parser/collector/bridge tests using invented official HTML, including retry fairness, shared source waits and unchanged original hashes.
- [x] Add `race_ai/racer_beforeinfo.py`: bounded current-day target selection, source capture retention, verified context projection and retry status. Reuse `IntradayState` retention and `OfficialClient`, extending only its exact beforeinfo GET allowlist.
- [x] Connect `scripts/racer_intraday_refresh.py` and `SavedResultBridge.publish`: up to four beforeinfo GETs and the remaining result budget, preserving a total maximum of 12 and existing source delays. Add `live_boat_observation` as the sole new mutable record field in Python/browser crypto.
- [x] Render verified live facts first in the pre-race tab, use the same context for racer cards and availability links, and distinguish exhibition not published from fetch failure. Keep source audit on Research and retain saved forecast values.
- [x] Run affected Python, Node and real WebCrypto/browser/history tests. Obtain independent review; publish compatible frontend first, then integrate a narrow workflow/runtime change through normal required CI.
- [x] Run the real collector, prove encrypted readback and live displayed exhibition/weather without exposing owner data, and retain count-only evidence. Preserve unrelated draft work.
