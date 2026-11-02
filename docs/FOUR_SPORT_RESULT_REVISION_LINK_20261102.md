# Four-sport offline result/revision link (development only, Issue #67)

This adds a **second, read-only step** after the existing four-sport cohort bridge on Draft PR #72. It does **not** collect live schedules/results, open a provider account, verify legal data rights, establish a pre-cutoff freeze, or score formal Hit@8. It reuses `four_sport_ledger_bridge` and, for an optional private synthetic/research seal, the existing `evaluation_experiment` scorer instead of implementing a competing model or result-scoring engine.

## What is added

- `race_ai/evaluation_result_revision_bridge.py` accepts a prior `RACE_AI_FOUR_SPORT_COHORT_BRIDGE_V1` and explicitly provided result observations. It joins by the exact physical key `sport:event_date_jst:venue:race_no` (boat, keirin, autorace, horse_jra, horse_local), rejects unlisted races, and retains all unmatched rows as `NO_RESULT_OBSERVATION`. No meeting, no race, no result observed, cancelled and non-offered are distinct.
- Each observation records a separate revision number, previous observation SHA-256, actual observation time with timezone, source URL/ID/claimed source-body hash, source publication time if known, explicit external revision reference if present, outcome state, complete winning 3-triples (including tie cases), exact positive **100-yen** payouts by combination, and refund status `NONE/PARTIAL/FULL/UNKNOWN`. Missing/nonstandard/withdrawn conditions are never interpreted as a miss.
- A changed result gets another numbered observation, never replaces the old one. Revisions must be contiguous and hash-linked, timestamps must not reverse, and later changes require a provider correction reference **or a different observed source SHA**. This is a structural consistency check, **not independent or tamper-proof external evidence**. Without source byte verification and independently authenticated provider corrections, result authenticity remains `false`.
- `race_ai/evaluation_result_revision_cli.py` loads strictly bounded JSON from local private paths, refuses to overwrite an existing output, writes a report without copying the original picks or full provider source text, and returns exit **2** for valid but unverified research, **3** for errors. No official PASS code exists. Results/sources are supplied by the operator and are not fetched by this CLI.
- Optionally, when the original local evaluation **seal** is also present, the CLI calls existing `verify_seal` / `score_seal` to produce clearly labelled **research-only** model Hit@1/Hit@8 based on observed normal finishes with no refund. Unobserved results, missing forecast slots, unsupported settlements and refund-affected races remain in the original research cohort. Seal SHA, race identities, model/stage/status and full expected slot matrix must match the prior bridge. A retroactively read seal, GitHub bundle witness, or declared provider URL is not a formal external pre-cutoff receipt.

## Private example (all names and results are fictional)

Create the **first** bridge using `four_sport_ledger_bridge_cli`. Its reference and ledger are manual/unverified until independently accepted. Then supply a result batch in private storage:

```json
{
  "schema": "RACE_AI_OFFLINE_RESULT_OBSERVATIONS_V1",
  "scope": "OPERATOR_SUPPLIED_UNAUTHENTICATED_RESEARCH",
  "event_date_jst": "2030-01-05",
  "observations": [{
    "race_id": "boat:2030-01-05:boatrace-jcd-01:1",
    "revision": 1,
    "previous_observation_sha256": null,
    "observed_at": "2030-01-05T15:00:00+09:00",
    "source_id": "OFFICIAL",
    "source_url": "https://www.boatrace.jp/result/fictional",
    "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "source_published_at": null,
    "provider_revision_ref": null,
    "status": "FINAL_NORMAL",
    "winning_triples": [[1,2,3]],
    "payouts_100yen": [{"triple":[1,2,3],"yen":1234}],
    "refund_status": "NONE"
  }]
}
```

```bash
python -m race_ai.evaluation_result_revision_cli \
  --bridge private/cohort-bridge.json \
  --observation-batch private/result-batch-000001.json \
  --research-seal private/unchanged-research-seal.json \
  --output private/new-result-link.json
```

To add an observed correction, create another distinct `--observation-batch` argument with revision 2 and `previous_observation_sha256` matching the SHA-256 of the **canonical sorted JSON of the complete prior observation**. Keep the previous batch intact, include actual later observation time, and provide changed source-body digest or a documented provider correction reference. The tool performs a read-only re-derivation of the chain; it does not itself provide durable append-only storage. Never generate a revision for data that was not actually observed.

## Statuses and remaining admission gates

| Layer | State after this change | Formal qualification |
| --- | --- | --- |
| Five category identity / missing schedule rows | Manual offline bridge exists | No proof of complete official denominator |
| Previous research forecasts | Linked by archived seal/retained research claims | No per-race authenticated pre-cutoff external receipt; no promotion |
| Official results / payouts / refund / changes | Strict **operator-supplied** result revision contract now joinable offline | Claims are **unverified** until permitted source admission / independent authentication / official finality |
| Research Hit@1 / Hit@8 | Optional existing `score_seal` with a verified local research seal | Not a new formal prospective score |
| Formal Hit@1 / Hit@8_all / coverage / ROI / Brier / Log Loss | **null** | Await complete schedule, eligible authoritative result and individual frozen proofs; real purchase receipts and pre-event calibrated probabilities required for respective metrics |

Use original provider policies for purpose-specific rights. As of this implementation, **no newly approved ongoing acquisition/training/republication licence is asserted** for BOATRACE, KEIRIN, AUTORACE, JRA or NAR. A site URL conforming to an official hostname is a shape check, not proof of permission, authenticity or completeness. Do not programmatically crawl on the basis of this module. Do not upload private prediction bytes, official source bodies, subscription credentials, or payout source archives to the public repository.

Existing held records, original prediction SHA, models/weights and recorded failure outcomes remain unchanged. No scheduled source jobs, paid resources, auto-bets, external publication, CI permissions or production merges are enabled here. This is a step toward #67, **not** completion of its all-races 98% target.