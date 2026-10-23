# P0: BOATRACE B/K distribution permission and timing gate

Verified 2026-10-23 JST. Governing product goal: Issue #67, execution Issue #68.
This document contains **public official-site findings**, not a grant or a live source
capture. Source permissions are `UNKNOWN` until an independent rightsholder
response or applicable legal exception is assessed and documented.

## Public official information

- [Official download portal](https://www.boatrace.jp/owpc/pc/extra/data/download.html)
  currently advertises 24-venue `番組表ダウンロード` and
  `競走成績ダウンロード`. Links lead to
  [B index](https://www1.mbrace.or.jp/od2/B/dindex.html) and
  [K index](https://www1.mbrace.or.jp/od2/K/dindex.html).
  **The index pages existing does not prove that an individual day's LZH was
  reachable, current, immutable, or usable under a machine-collection grant.**
- [March 5, 2025 shutdown bulletin](https://www.boatrace.jp/owsp/sp/site/news/2025/03/41685/)
  lists `番組表閲覧`, `オッズ情報・結果`,
  and `競走成績閲覧` as discontinued; it does not explicitly state that
  B/K *download archives* were discontinued.
- [Official site/about/update guide](https://www.boatrace.jp/owpc/pc/extra/about.html):
  following-day **website race information is displayed approximately
  18:00 ordinary / 20:00 summer-time / 22:00 night-racing JST**, per venue
  and subject to delays. THIS IS NOT B-ARCHIVE RELEASE TIME.
  The site normally closes 04:00–04:30 daily. No particular B/K file release
  hour, file replacement history, maximum polling rate, or data-retention
  period has been documented by this research.
- [Official site policy](https://www.boatrace.jp/owpc/pc/extra/policy.html):
  the publisher does not grant blanket rights to protected content; use
  beyond applicable statutory exceptions/individual terms needs attention,
  and requests/transfers that disrupt operations are prohibited. **A
  numerical request-rate allowance and permission for RACE-AI's specific
  automatic collection, private retention, model fitting and derivative
  output have not been established.** Do not treat public visibility,
  a file suffix or competitors' usage as a license.
- [Official inquiry/contact](https://www.boatrace.jp/owpc/pc/support/opinion):
  BOATRACE official WEB telephone **03-5539-8696, 10:00–18:00 JST**.
  The online `ご意見・ご要望` form states that questions generally cannot
  receive replies; it is not reliable for an affirmative permission answer.
  Ask that office for the actual B/K distribution rights administrator and
  a written response. No call or submission was performed here.

## Japanese copyright exception: do not invent an absolute ban

Japan's [Copyright Act Article 30-4](https://laws.e-gov.go.jp/law/345AC0000000048)
and [Agency for Cultural Affairs AI/copyright guidance](https://www.bunka.go.jp/seisaku/chosakuken/aiandcopyright.html)
recognize some non-consumptive information-analysis and AI-training acts
without individually obtained permission, within their conditions and subject
to the exception when use would unduly harm the rightsholder's interests.
The [Agency's 2024 explanation](https://www.bunka.go.jp/seisaku/chosakuken/hokaisei/h30_hokaisei/)
also describes information analysis among the relevant categories.

**Consequently do not state that every personal offline statistical analysis
categorically requires a written license.** A real policy reviewer may admit
a precisely scoped legally applicable exception rather than an explicit
rightsholder grant, but must document the factual legal basis and its
limitations. This does not grant automated access against technical controls,
override website or service contracts, authorize excessive/disruptive traffic,
or automatically authorize public republication or commercial derivatives.
The current project has no such external legal assessment recorded, so its
machine-collection/storage/analysis gate remains **unverified**, not prohibited
for all possible legal circumstances.

## Purpose-by-purpose evidence and admission gate

| Purpose | Verified right | Required concrete record before live operation |
|---|---|---|
| Human viewing/index discovery | Official index and download landing pages verified | Preserve source URL and retrieval date; no heavy polling |
| Automated B/K download | UNKNOWN; disabled | Rights holder or competent review of exact mode, rate/volume and evidence reference |
| Private retention/copy | UNKNOWN; disabled in production | Approved period, protected material scope, backup/deletion policy |
| Statistical/ML feature computation | UNKNOWN; disabled in production | Authorized collection/analysis scope or verified applicable exception |
| Training on historical B/K data | UNKNOWN; disabled | Separate analysis/training authorization or legally reviewed exception |
| Derived predictions displayed privately | UNKNOWN | Approved purpose and attribution/distribution conditions |
| Public re-publication of raw/derived data | NOT APPROVED | Separate written approval; no public source bytes |
| Daily official sales cutoff & as-of | B parser *can parse a listed cutoff* when raw verified | Actual approved B file and independent cutoff comparison (never infer from start) |
| True pre-cutoff immutable forecast | NO real attestation yet | Exact forecast hash + external receipt before cutoff + readback |
| Official post-race revisions | NO live K integration yet | Authorized result source, stable race/entrant IDs, append-only history |

## Ready implementation boundary, without network collection

- PR #64: `official_lzh_extract.extract_daily_lzh` performs bounded, safe
  LZH extraction; `official_b_snapshot_adapter.normalize_b_snapshot`
  parses B program detail, six racer IDs and closing schedule.
- PR #71: `boat_b_offline_archive_intake.stage_supplied_b_archive`
  consumes a **separately provided** local archive, validates per-purpose
  reviewed permission policy and limits, delegates exclusively to an
  explicitly pinned PR #64 extractor and B normalizer, verifies SHA-256 for
  exact raw bytes and extracted text, and passes to
  `boat_b_program_bridge.stage_official_b_handoff`.
  It returns only a private research staging result; no upstream GET,
  cloud upload, fabricated features, model fitting, remote clock witness,
  betting, billing or public deployment.
- For an actual B event, `boat_b_program_bridge.link_b_stage_to_features`
  still requires an independently sourced normalized feature feed with
  full required observations, timestamps and rights.
- Unit tests use imaginary 2030 cases and callbacks that explicitly do
  **not** parse authentic LZH; a test PASS is not a real-source verification.

### The exact written questions to confirm with the distributor

1. Who owns the use permissions for both B and K archives distributed at
   `www1.mbrace.or.jp`? Is there a specific license or written notice for
   recurring automated retrieval at a bounded low frequency?
2. May the files be temporarily or durably stored on private devices/cloud
   for a personal statistical model? Is independent analysis/ML training
   covered? Under what limitations regarding public/private derivative
   forecasts and attribution?
3. When and how often is the daily B file first posted or revised, and K
   results/revisions first published? Does the host publish timestamps,
   version IDs or ETags? What is the permitted rate, concurrency, traffic
   budget, and retry/backoff schedule?
4. Are sales-cutoff times in the B file authoritative after day-of changes?
   What is the authoritative independent correction channel?
5. Does the answer differ for personal research, a public GitHub project,
   publication of derived forecasts, or prospective commercial use?

**Until verified:** `RIGHTS_UNVERIFIED` and `B_ARCHIVE_RELEASE_TIME_UNVERIFIED`.
Do not silently turn these into `ALLOW` or schedule repeated downloads.
The signed internal reviewer record authenticates the record, not the rightsholder's grant.

## Real E2E gates still pending

(1) approve one real source/purpose, (2) acquire one prospective official
archive before close, (3) check racer IDs/sales cutoff and source hash,
(4) obtain complete authorized pre-race inputs and odds-free Top8,
(5) independently persist the prediction hash before cutoff and verify
readback, (6) reconcile the official K result without changing the forecast.

No real archive was downloaded, no trusted time anchor was created and
no actual measured Hit@8 is claimed by this source audit.
