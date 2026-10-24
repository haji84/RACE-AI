# P0 (2026-10-24): RACE-AI Cloudflare owner-only odds preview acceptance

**Status update after first real pilot (2026-10-24 10:43 JST):**

- The original 0-row status below is **historical (before the actual source pilot)** and has now been superseded: the owner-only D1 contains **one real official 芦屋7R 2026-10-24 120/120 odds snapshot**. Hash readback succeeded.
- Three bounded, manual first-party Browser Rendering snapshots at JST **10:40:01 / 10:41:57 / 10:43:21** with published source update time consistently **10:36**. The provider values did **not** change, so a 60-second upstream value refresh is **not yet proven**. All three requests are accounted in D1 quota ledger. The latest odds row is deliberately not rewritten when unchanged.
- All three observations and D1 SHA are documented in [actual one-race evidence](./evidence/2026-10-24-boatrace-ashiya-7r-real-odds-pilot.md). Cloudflare Access remains owner-only; auto source polling/Cron and Worker ingest remain disabled. Owner iPhone Safari acceptance still pending.

---

Goal: one authorized real BOATRACE 3連単 page (120 exact ordered quotes),
private D1 storage, and 60-second refresh visible on an iPhone. This
document **separates a deployed protected infrastructure from the missing
genuine provider acquisition and phone acceptance**.

## Actual connected Cloudflare account changes

The existing Cloudflare account was discovered with the connected provider.
The following new resources were created specifically for RACE-AI on
2026-10-24 (JST) without changing the pre-existing `ai` or
`goriq-verification-gate` Workers, other Access apps, or paid plans.

- D1 `race-ai-odds-private-preview`: created in APAC; schema
  `workers/odds_schema.sql` applied and table/index presence verified.
  Server-side `SELECT COUNT(*) FROM odds_latest` returned **0**. No raw
  proprietary odds, personal data, actual tickets, or fictional prices were
  populated.
- Worker `race-ai-odds-private-preview`: GitHub-reviewed module
  `workers/odds_feed_worker.mjs` uploaded and bound to D1. No Cron trigger,
  official-provider HTTP fetcher, cost-increasing plan, automated betting,
  public Vercel release or new production API route was installed.
- Cloudflare Access `RACE-AI Odds Preview - Owner only`: created with
  destination type **worker** targeting this Worker; allow policy restricted
  to a single email inherited securely from the already-existing owner-only
  Access app. The email is not committed to this repository.
- Worker code additionally requires **Cloudflare-verified `ctx.access`**
  and the matching owner identity. It rejects arbitrary client-provided
  `Cf-Access-Jwt-Assertion` header strings and returns 403 without the
  Cloudflare-injected context. It also checks an independent
  `ODDS_ALLOWED_EMAIL` environment binding, not a query parameter.
- Subdomain `race-ai-odds-private-preview.qq-1130034.workers.dev` was
  enabled only after Access destination and allow policy were verified.
  **Preview version URLs remain disabled.**
- Bindings: `ODDS_REQUIRE_ACCESS=true`,
  `ODDS_PREVIEW_READ_ENABLED=true`,
  `ODDS_PREVIEW_INGEST_ENABLED=false`. No live quote writer secret or
  upstream odds rate schedule was provisioned.
- Browser UI: the existing reviewed `web/full-odds.html`,
  `web/full-odds-model.js`, `web/full-odds.js` and CSS are copied into
  `workers/odds_preview_assets.mjs`, and served only through the
  Access-authorized Worker. `GET /health` checks D1 and says
  `EMPTY_WAITING_FOR_APPROVED_ODDS` when the DB is empty.
  The owner-only page is:
  `https://race-ai-odds-private-preview.qq-1130034.workers.dev/full-odds.html?race_id=20261024-21-01`
  and the health endpoint is
  `https://race-ai-odds-private-preview.qq-1130034.workers.dev/health`.
  **An HTML endpoint being enabled does not constitute a verified iPhone
  login, rendering or 60-second live odds update.**

## Evidence and known gaps

- GitHub Actions runs on PR #71 prove offline syntax/unit contracts with
  synthetic prices and mock D1/Access contexts, **not** an actual browser
  login or authentic data delivery.
- Cloudflare API readback verified: Worker exists; Access application
  destination type worker with owner email only; Worker subdomain enabled;
  script settings include D1 and all expected bindings; the database
  holds **0** odds race rows.
- Official 2026-10-24 morning BOATRACE fixtures include the 芦屋 KBCラジオ杯
  second day, with published morning 1R scheduled cutoff 08:43 JST.
  The exact current first-party page URL
  `https://www.boatrace.jp/owpc/pc/race/odds3t?hd=20261024&jcd=21&rno=1`
  could not be fetched by the available source reader, and the offline
  execution environment returned DNS resolution failure. **No genuine
  120-quote HTML has been fetched or validated in this session.**
- `source_published_at` remains unknown for sources lacking a trustworthy
  provider update time. Screen must show an update-time warning even when
  the Worker acknowledges a recent ingestion.
- The right to automatically copy, persist and **redistribute all 120 odds**
  from a source, and any provider-specific request-rate limit, is not
  independently established by a public website or by this Cloudflare
  Access app. Source authorization is a separate gate.
- The owner has **not yet provided a successful iPhone Safari acceptance
  result**. We cannot claim that Access login/rendering worked on the actual
  phone from API configuration alone.

## Actual next acceptance checks (do not fake)

1. Operator opens the protected `/health` and `/full-odds.html` URL on
   iPhone Safari; verify the owner-only Access login and no data disclosure
   to unauthenticated users. Capture success/failure status without
   disclosing credentials. If blocked, check app destination and `ctx.access`.
2. A legally usable *one-race* full 120-odds snapshot must be obtained
   from the original provider with rights/purpose/rate confirmation or an
   independently reviewed applicable statutory exception and source
   access agreement; verify source bytes, current grid layout and
   official race/cutoff. Refuse to fabricate unavailable values.
3. Enable private `POST /internal/odds` only when authorized data,
   publication rights and a short-lived ingest token are all provisioned.
   Persist and read back hash with D1. Keep the Worker owner-only.
4. For this first race, measure at least three successive source publish
   timestamps, Worker received timestamps, browser confirmed timestamps,
   and server/browser refresh intervals >=60s. Log 403/429 or DNS/HTML
   failure as a failed attempt rather than a fresh update.
5. Do not extend the source request budget to all races until a
   licensed batch provider or clear source rate limitation and reliable
   persistence budget are verified.
6. Separately verify official sales cutoff T-10 user-visible frozen forecast
   and official result; odds never enters the model.

**Current release classification:** PROTECTED_INFRASTRUCTURE_STAGED;
REAL_ODDS_E2E_INCOMPLETE; MAIN_NOT_MERGED; NO_AUTO_POLL; NO_BET.
