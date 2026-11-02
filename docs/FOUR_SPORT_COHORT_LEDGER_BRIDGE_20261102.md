# Four-sport schedule-to-frozen-forecast identity bridge (research-only)

Issue #67 / existing Draft PR #72. This is a read-only *structural connection*, not a new model, a live source collector, an official completeness claim, or a certified pre-cutoff receipt. `main`, original predictions, historical research journals and halted cohorts are not modified.

## Reused contracts

- `discovery_audit_cli.audit` and `discovery_reconcile.compare_daily`: strict manual-reference and AUDIT_ONLY daily source/ledger comparison, including absent venues, unknown race counts and unverified source/cutoff claims.
- `evaluation_experiment.verify_seal`: checks the existing local immutable-plan-and-forecast bundle. Model/stage matrix, all unforecast rows and predictions retain original bytes and identity. Local seal does not authenticate external time, source availability, final sale cutoff, or provider permissions.
- `CapturedHistoryAuditJournal.read_report`: the CLI optionally loads an existing private research journal, verifying original source bytes, exposure registry and result-batch hash chain. The expected import SHA and expected report SHA are mandatory. This is *development-only*, not a prospective accuracy trial. The CLI never reads source websites, regenerates forecasts or exposes original Top8 in stdout.

Physical join key is `(sport, event_date_jst, venue, race_no)`, not model ID or a friendly venue alias. `horse` in existing evaluation archives lacks the JRA/NAR authority, so `--horse-authorities` must explicitly map each horse `race_id` to `horse_jra` or `horse_local`, otherwise the join rejects it. Official BOATRACE JCD codes `01..24` are the only accepted translation for retained private race IDs, `YYYYMMDD-JCD-RNO` to `boatrace-jcd-JCD`. No other venue aliases are silently inferred.

The output contains *all explicitly listed reference races plus ledger-only and archived-only races*, with each model/stage slot, `NO_FORECAST` reason, archive source SHA, gap status and collision checks. A venue with unknown race count remains unknown. Five scope categories (`boat`, `keirin`, `autorace`, `horse_jra`, `horse_local`) are reported separately. The supplied manual reference **does not prove** that an official daily racing programme is complete, so `official_complete_denominator`, official Hit@1, Hit@8, capture rate, payout ROI and proper scores remain `null`; no research counts are promoted to formal statistics.

## Private offline command

```bash
python -m race_ai.four_sport_ledger_bridge_cli \
  --reference private/manual-reference-YYYY-MM-DD.json \
  --ledger private/audit-ledger-YYYY-MM-DD.json \
  --secondary-reference private/manual-secondary-YYYY-MM-DD.json \
  --seal private/predictions-original-seal.json \
  --horse-authorities private/horse-authorities.json \
  --output private/new-cohort-bridge-YYYY-MM-DD.json
```

Alternatively, for the existing retained BOAT research **only**, omit `--seal` and supply `--retained-root`, `--retained-audit`, `--retained-import-sha`, `--retained-report-sha` (and optional `--retained-through-batch`). Never copy private forecast raw bytes to the public repo. The CLI creates the output exclusively and fails if it already exists. A successful structural join returns exit code **2** (still unverified), input errors **3**; no code path returns official PASS. It performs no network I/O.

## Next operational gates (not passed here)

1. Authoritatively discover and freeze the *entire* daily eligible trifecta cohort for all five categories, with provider-specific rights for automatic acquisition, retention and scoring. Explicitly represent no-meeting and unknown source cases. Do not convert manual list matching into `complete=true`.
2. Bind each archived model Top8 to an individually authenticated, independently time-stamped pre-cutoff receipt, source/publication time, official final sales cutoff and venue identity, validating readback with the existing `race_bound_freeze_receipt` gate. The existing retained research bundles only have whole-bundle anchors and cannot be upgraded retrospectively.
3. Join official final result *revisions*, refund, dead heat/invalid/cancellation and per-ticket 100-yen payouts after permitted acquisition. Revisions append, never replace prior results or Top8.
4. Only once the full eligible denominator and valid receipt/result pairs are established, compute formal Hit@1, Hit@8_all and capture rate with missing forecasts **in** the denominator. Report actual-stake ROI solely if original paid stakes/refunds exist; Brier/Log Loss only if calibrated pre-event probabilities were saved. Test improvements in untouched future cohorts.

No Actions workflow, schedules, cloud permissions, access policy, public deployment, paid services or betting operations are enabled by this work.
