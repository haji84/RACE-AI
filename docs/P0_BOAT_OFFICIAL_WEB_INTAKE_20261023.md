# BOAT RACE official Web screen -> AUDIT_ONLY intake (2026-10-23)

This adds \`race_ai/boat_official_web_adapter.py\` to the **existing** PR #72 (no PR #71 model changes). It accepts locally saved UTF-8 HTML from an *official race-card URL* of the precise form:
\`https://www.boatrace.jp/owpc/pc/race/racelist?hd=YYYYMMDD&jcd=NN&rno=N\`.
A structured HTML table with a \`レース\` row immediately followed by \`締切予定時刻\` is required. Its race numbers and announced times become the existing \`RACE_AI_FORECAST_AUDIT_V1\` index via \`operator_export_intake.transform\`. Unexpected hosts, forged URL fields, invalid times, missing/ambiguous layout and duplicate races are rejected. The source page itself is not retained or pushed in public Git; the resulting private audit retains only the original URL, source SHA256, claimed capture time, and announced times.

**IMPORTANT**: Scheduled closing times appearing on an HTML screen are only *announced* times. \`cutoff_verified=false\`, \`prediction=null\`, \`result=null\`, \`dataset_status=AUDIT_ONLY\`, \`automatic_site_collection_authorized=false\`. A screen capture does NOT prove when or under what license the page was fetched, nor that its HTML truly came from the URL, or that the organizer has not later revised the cutoff. The current parser has been exercised using **synthetic HTML only**; it is not evidence of compatibility with a live saved BOAT RACE page. It does not accept the live post-result odds, payout, result, or third-party forecasts as prediction features. Real HTML schema may vary and would be rejected until audited.

Example for a separately and lawfully saved HTML (no programmatic fetch here):
\`\`\`sh
python -m race_ai.boat_official_web_adapter \
  --html /private/saved-boatrace-racelist.html \
  --source-url 'https://www.boatrace.jp/owpc/pc/race/racelist?hd=20300115&jcd=16&rno=2' \
  --captured-at '2030-01-15T08:00:00+09:00' \
  --source-rights-ref UNVERIFIED \
  --output /private/audit-20300115-boat-16.json
\`\`\`

This is an *alternative input path*, not a blanket public-Web crawling authorization. Any automated web requester must separately verify the source's site terms, legal basis, robots/access restrictions, request rate, cache, cumulative quotas, data retention and allowed purposes. The BOAT RACE site policy prohibits mass requests that disrupt the service: https://www.boatrace.jp/owsp/sp/extra/policy.html . Distinguish factual data analysis from verbatim republication of protected graphics, tables and content.

**Next independent admission gates**: operator-approved actual source page parsing; current official race-specific start/sales cutoff in a second trusted publication; rights-compliant bounded live fetch; pre-cutoff model snapshot; secure append-only remote prediction hash/time receipt; official result + refund + payout revision; and 4-sport unattended discovery/capture. None of these are fulfilled by this synthetic screen parser.
