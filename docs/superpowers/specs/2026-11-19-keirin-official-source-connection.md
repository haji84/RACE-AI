# Official KEIRIN source connection

The latest completed WINTICKET collector fails at its first ordinary Chrome
racecard-index request with `DAILY_INDEX_HTTP_403`. The existing PR71 owner
collector separately fails at the WINTICKET day index before obtaining inputs.
Existing KEIRIN.JP public SP calendar/list/detail navigation has a verified
HTTP-200 example. This change connects that already approved official source
to the existing partial-input collector. It does not claim to remove a
WINTICKET server restriction or to obtain missing full-model features.

Use the existing reviewed SP parsers and ordinary Playwright 1.56.0 Chromium.
Follow published DOM controls only: calendar GET, the displayed meeting's
read-only `/sp/racelist` POST (`SJ0301`), and selected race's `/sp/race` POST
(`SJ0315`). Bind form values to the freshly rendered controls. Never guess
URLs/tokens, send another POST, change UA/headers, borrow cookies, use stealth,
rotate networks, or retry a denial. A fresh nonpersistent session may keep its
own ordinary cookies. Stop on denial/challenge/redirect/unknown navigation.

The browser component exposes `collect_official_sp(inbox, *, clock=None,
monotonic=None, budget_seconds=240, browser_factory=None) -> dict`. The inbox
is private 0700 outside the checkout; raw receipts are create-only 0600.
The returned report contains only fixed codes/counts/hashes. Its keys include
`state`, `calendar_meetings_observed`, `day_venue_count`, `day_race_count`
(null until all selected meeting lists are verified), `race_lists_verified`,
`details_verified`, `riders_verified`, `future_detail_count`,
`expired_detail_count`, `http_status_counts`, `navigation_request_count`,
`resource_request_count`, `unknown_transmitted_status_count`,
`provider_denied`, `provider_denial_http_status_counts`, `budget_exhausted`,
`private_source_files_saved`, `source_admission=false`,
`model_input_admission=false`, `new_forecasts=0`, and `winticket_requests=0`.
No total race/request quota is introduced; retain the existing job work-time
budget and parser/individual-response size bounds. Preserve verified prefix
counts when time runs out; unknown coverage remains null.

Only the default owner public collection chooses this source. Explicit legacy
injected transports and independently configured licensed exports retain their
existing contracts. No WINTICKET-labelled partial folder receives official
data. Full PR71/model/forecast admission stays closed for incomplete inputs;
no empty production AES generation is created. Production keys remain inside
Actions. Forecast originals and result history are preserved.

Reuse existing workflow steps and Playwright dependency version. Do not add a
workflow/job/step/input/cron/runner/timeout/permission/marker or change source
pins, production weights, public UI, paid services, or branch protection.
Keep all repository model code and the BOAT source SHA unchanged.

Validate with invented offline browser/HTTP fixtures, the saved private source
example, independent review, normal protected CI/integration through an
existing PR, then one trusted actual Actions acquisition. Record the actual
HTTP and parsed-record result, including a genuine HOLD if access is refused.
