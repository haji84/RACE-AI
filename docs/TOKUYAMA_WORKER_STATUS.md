# Tokuyama day worker status — 2026-10-15 JST

## Implemented boundary

`race_ai.tokuyama_day_worker.collect_tokuyama_day(day, rights=..., now=..., transport=..., details=...)`
performs one current-JST-day index request only after an independently reviewed
`facts_ingest=allowed` record covers its exact URL or the fixed `SOURCE_SCOPE`
race-index page across dates. An operator can configure the latter once when
permission evidence genuinely covers that collection scope; no per-day manual
SHA review is required. No allowed records were added to this repository.

The default transport allows only the canonical HTTPS Tokuyama index endpoint,
uses a 10 second timeout and 1,000,000 byte body cap, rejects every redirect,
and makes no retries. Response origin/status/content type/UTF-8 and the existing
12-race six-lane parser must pass. Each parsed race row's first cell must contain
exactly one official race-list link carrying the requested day, venue 18, and
that row's race number. Navigation/racer-cell links cannot date a race row.
A correctly labeled request
URL cannot relabel yesterday's body. SHA-256 is computed from received bytes.

An index alone returns `PARTIAL_INDEX_DETAILS_REQUIRED`, with no snapshot or
entries field. It has names/lanes, while registration IDs, motors, and closing
times remain missing. Separately acquired, independently verified same-day
details use `join_verified_details` to produce a publisher-schema candidate.
That candidate remains `NORMALIZED_REQUIRES_PUBLICATION_APPROVAL` with
`redistribution_authorized=false`; the existing publisher rejects it without
separate approval. Review must cover every contributing source, including detail
sources, before a separate publisher is invoked. This worker never invokes a
publisher, writes source/output files, uploads, schedules, or modifies access.

Other terminal states: `DAY_INVALID`, `SOURCE_RIGHTS_BLOCKED`,
`SOURCE_UNAVAILABLE`, `SOURCE_INVALID`, `SOURCE_DATE_UNVERIFIED`, and
`DETAILS_INVALID`. An empty/not-yet-published page is not certified as a
no-race day. This slice intentionally covers full 12-race days only.

## Primary-source observations

These were bounded read-only observations, not collection authorization. Web
extractions included cached 10/14 headers while the allocation page refreshed
to 10/15; body race identities and meet periods must govern data acceptance.

| Source | Verified observation | Consequence |
| --- | --- | --- |
| https://www.boatrace-tokuyama.jp/modules/raceinfo/ | Series index shows prior meet 2026/10/10–10/14 and next meet 2026/10/18–10/23. | A latest/default completed page must not become 10/15 data. |
| https://www.boatrace-tokuyama.jp/modules/raceinfo/?page=index_raceindex&targetday=20261014 | Single raw HTML audit returned HTTP 200, UTF-8, 34,381 bytes. Existing parser produced 12 races with six names/lanes each. Race links target official `racelist` URLs with `hd=20261014`, `jcd=18`, and race numbers. Racer hyperlinks point to official profile URLs with `toban`; existing parser deliberately does not extract them. | Existing parsing works for the checked real page; new worker verifies body date links. No raw HTML was retained or committed. |
| https://www.boatrace-tokuyama.jp/modules/raceinfo/?page=index_resultlist | Completed 10/14 payout list links to official per-race results. | Payout parser is already present; payouts do not imply all six finishes or actual courses. |
| https://www.boatrace-tokuyama.jp/modules/raceinfo/?page=index_timerank | Refreshed page says 10/15 and asks visitors to wait until next meet; no current allocation table. | Cannot demonstrate current-day motor allocation E2E. |
| https://www.boatrace-tokuyama.jp/modules/datafile/ | Motor aggregate shows as-of 2026/10/13 and current motor usage start 2026/04/20. | Aggregate inventory is distinct from same-day racer allocation. |
| https://www.boatrace.jp/owpc/pc/race/raceresult?hd=20261014&jcd=18&rno=01 | Official result page includes six finishes, registration IDs, start information, payouts, weather, and scheduled closing times. | Actual-course extraction needs verified start-order mapping; existing result bridge intentionally keeps course unknown. |

## Factual data terms, separately from media

BOATRACE's site policy is available at
https://www.boatrace.jp/owsp/sp/extra/policy.html. It says content is protected,
use beyond legally permitted uses needs rights-holder permission except where
individual conditions apply, grants no rights, and prohibits disruptive bulk
access. It also warns content may lag and URLs/content may change. This is not
an explicit license for RACE AI automated factual ingestion, retained datasets,
or public redistribution. The applicability of legal exceptions to this use
was not established; do not infer blanket permission or a blanket prohibition
on every individual factual datum from this investigation.

https://www.boatrace.jp/owpc/pc/extra/data/download.html explicitly offers racer
period-statistics downloads and links to official program/result downloads at
`www1.mbrace.or.jp`. Offering downloads does not establish a redistribution
license for this product. Existing B/K archive fetching/parsing already exists
and is not duplicated by this change.

Tokuyama's visible footer identifies copyright and links to a privacy policy.
The inspected privacy policy concerns visitor personal information; no grant
covering automated race-data acquisition, retention, or redistribution was
found there. Homepage https://www.boatrace-tokuyama.jp/ lists the operator's
contact. No contact message was sent.

| Purpose | Tokuyama factual source | BOATRACE factual source |
| --- | --- | --- |
| Automatic acquisition and storage (`facts_ingest`) | unknown; independent scope evidence needed | unknown for this product; site policy/download availability alone is insufficient |
| Public factual redistribution (`facts_publish`) | unknown; separate evidence needed | unknown for this product; separate evidence needed |
| Photos/video/derived features | unchanged; not granted by factual processing | unchanged; not granted by factual processing |

## Verification and remaining work

Synthetic tests cover denied/unknown/duplicate/unrelated ingestion rights,
configured cross-date source scope, clock mismatch, stale body links, missing
date proof, incomplete races, HTTP errors, redirects, size/type/encoding bounds,
timeouts, conflicting/stale details, duplicate racers/motors within a race,
observation after acquisition and midnight crossing, partial state, and publisher compatibility
without granting publication. No factual rights were changed for tests; allowed
test records are explicit synthetic fixtures.

Targeted suite: 20 tests passed. Full repository command:
`python -m unittest discover -s tests -v` — 181 tests, OK, one existing skip
(`opencv not installed`). Initial missing-module RED was observed, then GREEN;
source-scope and malformed-header regressions also observed RED before changes.
Author self-review is complete; parent review/integration remains external to
this branch. No push, PR, deployment, or public data publication occurred.

Independent review identified that a global date-link set could let detached
current-day navigation label an undated previous-day table. The fix reuses the
index parser's row/cell boundaries and requires first-cell race-link association.
Three regressions observed RED then GREEN: detached current-day navigation,
current-day links in racer cells, and swapped race-link numbers between rows.

The next useful slice is an official per-race program detail adapter proving
registration ID, lane, motor, and closing time directly from same-day official
HTML, with a collector under independently established source-use permission.
The worker can consume those verified detail rows. Today's Tokuyama meet gap,
missing allocation page, and unestablished factual ingestion/redistribution
rights prevent a live complete public-feed E2E claim.
