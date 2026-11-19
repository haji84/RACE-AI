# Current-day official KEIRIN SP input corrections

The completed trusted-main source job
[44553849928 / 135664465763](https://github.com/haji84/RACE-AI/actions/runs/44553849928)
used main `6306a6fd59f9a7b2df46eb8640d9ad5966c6a59e`. All 102 responses were
HTTP 200, with zero provider denials, blocked requests or unknown status counts.
It parsed 73 calendar meetings, then held before the first list was verified.
The wrapper's success is not race acquisition or forecast completion.
Decoded completed-log SHA-256:
`5512ef76a7e69f79df84a3617ff749b3ea6cdb7ce6c5b2a652b91c0dd7a3f42c`.

The long Actions step was dependency setup: browser installation completed at
15:26:22 UTC and the source report appeared at 15:26:28. A local unchanged-code
capture reproduced the exact 102-response hold. The source's current-day group
had nine valid race controls, but its future-day placeholders lacked confirmed
links. Validating every date group as if it were current incorrectly rejected
the normal page. The fix binds every group label/order and the unique selected
day first, retaining the exact number/path/token/three-input checks for that
day. It neither navigates future placeholders nor borrows another date's clocks.

With that correction, a local ordinary browser verified all six selected
current-day meeting lists and 57 race identities. All 796 responses were HTTP
200, including the first race detail. That detail held at the reader because
one of seven rider records contained the published `imgTyosiName` / `imgTyosiPath`
presentation pair. The saved official rendering script uses them as image
alt/src. The reader now accepts only that explicit bounded string pair and
discards it from output. Removing the pair from the saved source produces
identical rider values: no score, calibrated strength, model feature or admission
is derived from the image. Unknown extras, incomplete pairs and malformed values
still reject. The saved actual detail then verifies all seven riders offline.

The next local capture verified four details and 28 riders before encountering
nine-rider frame metadata in the fifth detail. Its 1,527 received responses were
HTTP 200, with one transmitted request's status still unknown at cleanup; that
unknown is retained. The reader now accepts only the additionally published
`wakuban` and `kyuhanSpecialColor` display keys. Frames are optional, empty or
1–6; all values retain the bounded-string guard. The full allowed rider-key set
exactly matches the 21 property names used by the saved official rendering JS.
Neither frame nor CSS values become output/model fields. All five saved actual
details then reparse as 7, 7, 7, 7 and 9 riders, with unchanged rider outputs when
all presentation fields are removed. This is offline readback of saved source,
not five new runner forecasts or proof of complete day coverage.

Separately, an actual loopback browser test proved that Playwright 1.56's
`Response.body()` has no timeout: a three-second delayed body exceeded a
one-second collector budget. An unfinished body now waits for the exact
request's documented completion event within the existing remaining budget,
before its body is read. The same loopback control holds after about one second,
preserving its known HTTP 200 and zero unknown-status count. This was a real
budget gap, not the cause of the above dependency-installation delay. No source
retry, new timeout definition, header/cookie/fingerprint change or request is
introduced by the wait.

Raw documents, DOM, rider values and source-derived records remain private.
All model/source admission flags and new-forecast counts remain false/zero.
Actual acquisition after all corrections must be checked separately; offline
and local parsing are not proof of GitHub runner operation, all models, all-day
coverage or the T15-to-T10 persistence window. WINTICKET's own 403 remains a
separate unresolved source condition.

The original PR #103 head and all 132 original changed path modes/blobs remain
recorded in `pr103-original-preservation.json`. Its original EV/model proposal
is preserved through immutable Git history, not applied as a runtime change.
No new PR, service, model family, UI deployment, cost, wager, weight switch or
workflow definition is included. The existing owner workflow is byte-identical.
