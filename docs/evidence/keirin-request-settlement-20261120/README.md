# Settle admitted source requests before public navigation

Current main `bfd8de04b8e6bb7fefc6a910f1d2aae2f536e40f` acquired the official
day scope of six meetings and 57 race identities on GitHub Actions. Completed
run `44560531226` first held before a detail; its controlled transport recheck
verified one detail and seven riders. Four transmitted statuses remained
unknown in each attempt. All received responses were HTTP 200, with no observed
provider denial. These are partial acquisitions, not complete forecasts.

The same Playwright 1.56 / bundled Chromium 141 locally verified 14 details and
102 rider records within about 120 seconds. Its final navigation timeout was
reported as transport rather than budget exhaustion. The two runner outcomes
and this local prefix must stay separate.

A provider-free, real Chromium 141 loopback test proved a collector failure:
ordinary document navigation can abort a previously admitted, still-pending
image or font with `net::ERR_ABORTED`. The existing callback then stops the
collector. Page closure and fragment changes did not reproduce that event.
This mechanism fits the runner's early stop, but the original runner log has
no failure callsite, so it does not establish its sole cause.

The correction settles already-transmitted requests inside the existing budget
before an ordinary public navigation or old-page replacement. It preserves
request/response counts, unknown outcomes, denial handling, fresh DOM scope and
private body validation. It adds no retry, network request, source, fingerprint,
header, cookie, workflow definition, timeout value, model or forecast admission.
Unexpected failures receive only a fixed local callsite/category diagnostic;
exception text, provider documents, tokens and selectors are not logged.

The old PR #72 source-gate proposal and all 331 original changed path modes,
blobs and immutable URLs are preserved in `pr72-original-preservation.json`.
Its old tree is not activated. Existing PR #62 remains the UI/evidence draft;
its original 82 web blobs and tree `5cbbfe05a2971485b5c32a84a8ddf7b2539604cc`
remain at immutable head `86d832bdb8377055f9e84df15e62680396e2eebb`. No UI
deployment, wager, production-weight switch, service, charge or new PR is part
of this correction.

New trusted-main acquisition must still be verified separately. WINTICKET's own
403, all-model/T15 coverage and the remaining product acceptance gates remain
unverified.
