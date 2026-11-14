# RACE-AI: source -> model delivery (P0, 2026-10-23)

Owner goals: [Issue #67](https://github.com/haji84/RACE-AI/issues/67), [Issue #68](https://github.com/haji84/RACE-AI/issues/68). Implemented on existing Draft [PR #71](https://github.com/haji84/RACE-AI/pull/71), not main. No new betting, pricing, public deployment, unauthorized web scraping or source licensing claims.

## What is now connected

`race_ai/permissioned_source_delivery.py` implements a **real data transport seam** (not a newly fitted model):

1. Choose **one explicitly supplied** local normalized JSON file or **one exact, separately reviewed HTTPS JSON endpoint**.
2. Load an independent, HMAC-authenticated purpose-scoped reviewer policy from outside the source payload. Reject missing key, bad signature, expired permission, unauthorized purpose, paid source, redirect, private/literal IP address, oversized response, excessive fetch count, duplicate JSON keys or odds/results in prediction input.
3. Require every participant and environment observation to be timestamped and mapped to an authenticated `(source_ref, source_rights_ref)`. Validate source publication/capture/as-of, race identity/official cutoff, and no later information through the existing four-sport snapshot validator.
4. Call the **existing** `four_sport_model_suite.run_suite`. This returns four untrained research rankings of **all valid trifectas** and up to 8 choices for boat, keirin, autorace or horse from the *same* snapshot. Do not substitute fabricated feature values when source fields are absent.
5. Write the **full input snapshot plus source SHA, signed reviewer-policy SHA, model predictions and hashes** into a new mode-0600 **local file outside a Git checkout**, refusing to overwrite any previous record. No auto-post to GitHub, no public hosting, and no training or betting.
6. Report `PRIVATE_RESEARCH_ONLY_NOT_EXTERNAL_FROZEN`. A local output file or an HMAC policy is **not** a trusted independent pre-cutoff timestamp. The separate existing `github_freeze_receipt` validator still requires a genuine remote anchor/run and identity verification before any result can count toward Hit@8_all.

### IMPORTANT: authentication is not legal rights

The HMAC certifies *only* that a separately managed reviewer policy was not changed. It cannot establish that a rightsholder actually granted a license; a human reviewer must obtain the exact written agreement/terms and assess the permitted collection, storage, analytics, derivatives and rate/cost caps **before signing**. The user cannot safely elevate a source simply by setting an `approved=true` field.

**No live production source is admitted or connected by default.** This PR does not auto-configure bookmaker, race, weather, HTML/CSV/PDF or video fetches. Public access to a race website is not authorization to collect/train. A native JSON provider or separately reviewed adapter converting a rightsholder-approved raw feed to the strict normalized snapshot is necessary for real inputs. The feed reader does not infer missing races, fill missing features, manufacture timestamps, or parse an unknown web page.

## Signed policy contract

A separately reviewed local file `reviewed-policy.json` (never the provider payload) has:

```json
{
  "schema":"RACE_AI_REVIEWED_SOURCE_POLICY_V1",
  "policy":{
    "authority":"external-reviewer-identity",
    "grants":[{
      "source_ref":"https://approved.example/race-data.json",
      "rights_ref":"contract-reference",
      "transport_url":"https://approved.example/race-data.json",
      "purposes":["collection","analysis","private_storage","private_derived"],
      "evidence_url":"https://approved.example/agreement",
      "reviewer":"independent-rights-reviewer",
      "checked_at":"2030-01-10T00:00:00+09:00",
      "expires_at":"2030-02-01T00:00:00+09:00",
      "max_bytes":2000000,
      "max_requests":1,
      "max_cost_jpy":0
    }]
  },
  "signature":"64 lowercase hexadecimal HMAC-SHA256 over ascii SHA256 of canonical policy"
}
```

**This is schema illustration only: these endpoints, dates and reviewer entries are fictional and NOT approved real providers.** For local file ingestion, the purpose `collection` is not needed, but `analysis`, `private_storage`, and `private_derived` still must be admitted for that source. Every single feature must refer to a grant. All HTTPS endpoints are exact matches; never silently follow redirects or use wildcard hosts. Policy signatures are only issued using a key that is absent from public GitHub and the fetched data itself.

The source must return (or the local file must contain):

```json
{
  "schema":"RACE_AI_NORMALIZED_FEATURE_FEED_V1",
  "snapshot":{
    "schema":"RACE_AI_FOUR_SPORT_EVIDENCED_SNAPSHOT_V1",
    "scope":"OPERATOR_SUPPLIED_RESEARCH",
    "race":{"...":"existing exact time-aware race contract"},
    "participants":[{"...":"existing required participant features"}],
    "environment":{"...":"existing required environment values"}
  }
}
```

Use `race_ai.comprehensive_four_sport_models.feature_inventory(sport)` for the exact required/optional keys. Every observation is `{value,published_at,captured_at,source_ref,source_rights_ref,sample_n,transform_id}`. The adapter requires documented pre-result normalized scores rather than guessing how raw provider columns should translate into [0,1].

### Opt-in invocation, **only after real written permission review**

```sh
# Offline operator-provided normalized file (no provider HTTP call)
export RACE_AI_SOURCE_REVIEW_KEY='<provided securely via external secret store>'
python -m race_ai.permissioned_source_delivery \
  --policy /private/reviewed-policy.json \
  --file /private/normalized-provider-race.json \
  --output /private/unique-delivery-2026-10-23.json

# A single exact HTTPS endpoint (requires collection permission too)
python -m race_ai.permissioned_source_delivery \
  --policy /private/reviewed-policy.json \
  --fetch https://approved.example/race-data.json \
  --output /private/unique-delivery-2026-10-23.json
```

Never commit `reviewed-policy.json`, signing secrets, external raw source bytes or new private delivery outputs to this public repo. The test file `tests/test_permissioned_source_delivery.py` contains **fictional 2030 source/permission fixtures**, not a real approval.

## Advanced context captured without making false accuracy claims

An optional `supplemental` array can accompany `snapshot`. It preserves **reviewed, pre-cutoff** feature observations for the new design ideas without changing the existing model coefficients. Each observation has exactly `feature_key`, `subject_number` (null for race-wide context), `value`, `published_at`, `captured_at`, `source_ref`, `source_rights_ref`, `sample_n`, and `transform_id`.

The allowlist `SUPPLEMENTAL_KEYS` supports: common time-band/illumination/meeting-day/opponent-strength/track-bias/weather-trend features; boat historical 1M→2M and 2M→finish transitions; autorace same-handicap internal starting position and traffic; keirin daypart performance, line changes and race-format differences; horse pace, corner transitions, gate, race category and course bias.

All entries must have grants for analysis + private storage + private derived use, be observed no later than the forecast snapshot's as-of time, and refer to a known participating number or the whole race. An actual **in-progress position from the current race** is not an acceptable forecast input. This information is **preserved only**, not currently used by `run_suite`; `supplemental_features_used_by_models=false` makes this explicit. Future model versions may add individual features only after legitimate historical data and prospective verification.

Example illustration only:

```json
{
  "feature_key": "historical_1m_to_2m_transition",
  "subject_number": 1,
  "value": 0.61,
  "published_at": "2030-01-15T08:00:00+09:00",
  "captured_at": "2030-01-15T08:01:00+09:00",
  "source_ref": "https://example.org/fictional/races/2030-01-15.json",
  "source_rights_ref": "fictional-permission-1",
  "sample_n": 18,
  "transform_id": "synthetic-historical-precutoff-only"
}
```

Actual historical video-annotated transition rates must have their own legally admissible data provenance and historical label timing. None were obtained here.

## Acceptance state and blockers

| Deliverable | Status |
|---|---|
| Permissioned JSON/file transport, strict source scope and bounded HTTPS GET | **Implemented, synthetic test only** |
| Four-sport normalized snapshot → **existing** 4 research models → private output + SHA | **Implemented, synthetic test only** |
| Unknown/expired rights, cutoff, future input, odds/result, redirect, host, budget, duplicate, overwrite guards | **Implemented / contract-tested** |
| Native official provider JSON/CSV/HTML adapters and reviewed per-purpose rights evidence | **NOT CONNECTED** |
| Actual current-day schedule and per-feature authorized data for even one live race | **NOT VERIFIED** |
| Independent GitHub/third-party freeze receipt with server-time readback | **NOT CONNECTED** to this delivery |
| Official results ingestion, revision reconciliation and continuous schedules | **NOT CONNECTED** |
| main integration, protected deployment, real measured Hit@8 | **NOT DONE** |

Next minimal vertical slice: select one actually permitted provider, implement its **format-specific** source-to-snapshot adapter, capture a real current pre-cutoff race in this bridge, then wire a separate authenticated append-only remote writer and readback to the already existing receipt verifier. Do not label private local model output as official prediction.

No unattended network schedule, new billing, auto-betting or public release.
