# P0 Offline discovery gate (Issue #67)

This is an implementation on top of PR #69's existing `race_ai.discovery_reconcile`. It does **not** modify PR #69 or PR #64, whose old held POST/nonce must never be replayed.

```shell
python -m unittest tests.test_discovery_audit_cli -v
python -m race_ai.discovery_audit_cli --reference local-reference.json --ledger local-audit.json --output new-report.json
```

Inputs must have the documented `MANUAL_REFERENCE_ONLY` reference schema and `AUDIT_ONLY` viewer schema. Only use references that may lawfully be supplied. This command never downloads, sends, mines or creates race/participant material. `--output` creates an exclusive local new file, refusing to overwrite existing evidence.

The report lists missing and unexpected venues and race numbers, unknown reference counts, missing NO_FORECAST reasons, unverified cutoffs and untrusted prediction claims; it also flags every sport absent from the supplied reference. Missing a sport may mean **no meeting** or **missing coverage**: without independent dated source proof, neither can be assumed.

Exit code **2** means gaps or uncertainty. **3** means invalid or unsafe input/output. **0** only means supplied manual fields aligned, **never** that official completeness, automated ingestion authority, prediction receipt or real pre-cutoff forecast has been proved. All such admission flags are hard false.

Operational next gates: obtain date-, source- and purpose-scoped collection/storage/training terms; retrieve authorized venue/number/cutoff witnesses; produce immutable independent timestamped receipts; run one prospective real race end-to-end. No scheduled network jobs, publishing, paid services, odds, results, betting, or Production changes are introduced here.
