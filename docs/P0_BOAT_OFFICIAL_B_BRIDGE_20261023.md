# P0: BOATRACE official B program -> four-sport forecast input (2026-10-23)

Source of truth: [Issue #67](https://github.com/haji84/RACE-AI/issues/67), [Issue #68](https://github.com/haji84/RACE-AI/issues/68).
Implementation: existing **Draft PR #71**, extending the **previously implemented** official B parser in **unmerged PR #64**. No new model family, official-source HTTP request, remote forecast post, public deployment or purchase was made.

## Real source / legal status

BOAT RACE's official [download page](https://www.boatrace.jp/owpc/pc/extra/data/download.html) publishes program and race-result downloads. Its [site policy](https://www.boatrace.jp/owpc/pc/extra/policy.html) reserves intellectual property and restricts uses outside permission/legal exceptions; abusive traffic is disallowed. The availability of the files alone **does not establish automated collection, private long-term retention, AI training or public-derivative permissions**. The PR #64 owner-approved factual collection record is source/purpose-scoped and **is not automatically a new training/prediction grant**. There is no newly established independent grant in this work, so **no official archive was downloaded or fed into training**.

## What is genuinely implemented

Existing PR #64:
- [official_b_snapshot_adapter.py](https://github.com/haji84/RACE-AI/blob/codex/race-ai-completion/race_ai/official_b_snapshot_adapter.py) parses supplied, already extracted BOATRACE B text and yields a structured race/boat snapshot, including source hashes, an observed timestamp, racer registration IDs, lane assignments, motor/boat allocations, and the B-program closing schedule. It does **not** supply authentic exhibition and average-ST observations. Raw B archive acquisition and rights review remain a **separate** process.
- [official_lzh_extract.py](https://github.com/haji84/RACE-AI/blob/codex/race-ai-completion/race_ai/official_lzh_extract.py) can safely unpack a supplied LZH archive offline under strict entry/size checks; this PR **does not duplicate or replace it**.

New PR #71:
- \`race_ai/boat_b_program_bridge.py\`: \`stage_official_b_handoff(handoff, policy, now, race_id)\` audits the **existing B parser's JSON export**. Exact event date/venue/1..12R, 6 unique lanes and registration IDs, allocations, totals, official program closing times, source SHA-256, observation time and independent reviewed-source purpose gates are checked. It refuses result/market and fabricated exhibition fields. The returned stage retains raw available pre-race facts; it explicitly lists missing required model features and never promotes them to a forecast.
- \`link_b_stage_to_features(stage, normalized_feed_bytes, policy, at)\`: joins the PR #64 program identity against a **separately authorized and normalized** full \`RACE_AI_FOUR_SPORT_EVIDENCED_SNAPSHOT_V1\`. It rejects mismatching race IDs, racer IDs, lane draws, venue, day, cutoff, source permissions or capture time, then reuses \`permissioned_source_delivery.deliver()\` and the existing four-model research suite. Missing model features are **not** invented from the B statistics.
- \`race_ai/boat_b_handoff_cli.py\`: offline operator command for staged B only or B+evidenced features. Output is a new private file, mode 0600, outside a Git worktree, using exclusive create; no overwrite, no external provider calls.
- \`tests/test_boat_b_program_bridge.py\` + \`tests/test_boat_b_handoff_cli.py\`: fictional 2030 data, including matching program/snapshot and refusals for registration changes, duplicate lanes/motors, wrong day/cutoff, no source rights, stale forecasts, forged receipt claims and repeated output.

## Input handoff

The JSON for \`--b-handoff\` must have exactly:

\`\`\`json
{
  "schema":"RACE_AI_OFFICIAL_B_EXTRACT_HANDOFF_V1",
  "parser_ref":"haji84/RACE-AI@<exact-reviewed-SHA>:official_b_snapshot_adapter",
  "rights_ref":"<exact-independent-rights-review-reference>",
  "extract":{
    "date_jst":"YYYY-MM-DD",
    "source_url":"<actual approved official B archive URL>",
    "source_sha256":"<SHA-256-of-original-archive-or-text>",
    "extracted_text_sha256":"<SHA-256-of-extracted-text>",
    "source_hash_scope":"downloaded_archive",
    "first_observed_at":"<captured ISO-8601 timestamp with timezone>",
    "venues":[{"venue":"01","races":[
      {"race_id":"YYYYMMDD-01-01","boats":[{"lane":1,"racer_registration_id":"0000"}],
       "closed_at":"<actual official cutoff ISO-8601>","preview_available":false}
    ]}],
    "races":1,
    "complete_six_boat_races":1
  }
}
\`\`\`

The single-boat / single-race example above illustrates **shape only**, deliberately **fails strict validation**, and is **not a real source or licensable file**. An actual record must contain all 6 boats and the exact other B fields produced by PR #64. Do not fill a real date, receipt, permission ID, archive bytes or motor statistic from guesses.

The input extractor must independently verify raw source bytes, official identity and lawful provenance. **The bridge only validates the handed-off object's shape and declared SHA strings; it cannot prove the upstream HTML/archive bytes actually came from BOATRACE.** Each grant must independently authorize analysis, private storage and private derived results, and must be in the HMAC-authenticated \`PermissionPolicy\`; the signature itself does not prove actual legal entitlement.

## Operator usage after source-use approval

\`\`\`sh
# Run offline in the PR #71 source checkout. Signing secret and real documents
# must live in a private secret/files location, never GitHub public.
export RACE_AI_SOURCE_REVIEW_KEY='<independent external secret>'

# 1. Stage the real B parser output, preserving explicit missing features
python -m race_ai.boat_b_handoff_cli \
  --b-handoff /private/extracted-b-program-handoff.json \
  --policy /private/reviewed-policy.json \
  --race-id YYYYMMDD-01-01 \
  --output /private/new-b-stage.json

# 2. Only when each required feature was supplied from properly reviewed,
# timestamped sources, check the identities and run the existing models.
python -m race_ai.boat_b_handoff_cli \
  --b-handoff /private/extracted-b-program-handoff.json \
  --policy /private/reviewed-policy.json \
  --feature-feed /private/normalized-feature-feed.json \
  --race-id YYYYMMDD-01-01 \
  --output /private/new-model-evaluation.json
\`\`\`

Do not execute these commands with invented keys or real source material lacking actual usage approval. The current code has no live provider-specific authenticated transport credentials or native automated raw B download in PR #71. No new PR or runner is allowed to secretly override PR #64's STOPPED_UNCERTAIN_POST/nonce.

## Complete acceptance boundaries

| Step | Verified here | Still needed |
|---|---|---|
| B program parsing | Existing PR #64 parser examined/reused by export contract | Exact PR #64 artifact with independently verified current program bytes/rights |
| Program-to-model identity bridge | Synthetic unit/contract tests | Real signed-purpose-grant and authorized current source record |
| Actual racer skills, motor, history, exhibition and environment | B stats retained as raw when present; no fabricated values | Missing required as-of values, transform/sample size provenance, approved source adapters |
| Full 120 combinations and max 8 in four research models | Synthetic B + fully evidenced normalized research feed | Qualified real inputs; selected main model, training/calibration |
| Pre-cutoff immutable externally witnessed freeze | **Not done** | Genuine writer and independent receipt/readback linked to the same input/prediction hashes and cutoff |
| Official results and revision settlement | **Not done** | Independently admitted authoritative result source, append-only result revisions |
| 4-sport automated schedule / main | **Not done** | Four-sport source-by-source rights, scheduler, delivery, formal review and integration |

Historical B input obtained after the real race is **not** a prospectively frozen live forecast. All 2026-10-23 numeric tests use fictional 2030 fixtures. The finished local bridge is a verified intermediate **transport component**, not the user-facing product goal. Measured Hit@8 remains unverified, and 98% is an unproven target.
