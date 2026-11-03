# Owner-private original-byte readback, Issue #67 / Draft PR #72

**Status: one real owner-Library source was checked read-only in an isolated runtime on 2026-11-03 JST.** This is NOT proof that a GitHub Action has permanent access to that source, an independent pre-cutoff receipt, licensed official data ingest, or formal Hit@8.

## Reuse existing PR #72 instead of building another scorer

The new Python module race_ai/owner_private_file_reader.py implements the protected_reader(private_ref) callback in race_ai/official_private_receipt_link.py. It reads owner-local file bytes, requiring an owner-supplied private root and pinned per-ref manifest (relative_file, original_wire_SHA256). It rejects path traversal, symlinks, duplicate bindings and mismatched SHA; it does not make network calls, write original predictions, create official data evidence, generate new model predictions, publish receipts or score results.

The **private manifest and full original bytes must remain outside public GitHub**. Do not put original picks, private absolute paths, tokens, private manifests or original source records in public PRs/issues/logs. The owner-controlled directory must not be writable by untrusted processes.

Example on the owner's trusted machine, using independently pinned original per-race files:

~~~python
from race_ai.owner_private_file_reader import OwnerPrivateFileReader
from race_ai.official_private_receipt_link import link_protected_receipts

reader = OwnerPrivateFileReader(
    "/OWNER_CONTROLLED_PRIVATE_DIRECTORY",
    {"race-model-stage-ref": ("unchanged-original-wire.json", "<original-sha256>")},
)
# Existing PR72 linker still needs independently verified source purpose,
# a pinned original forecast validator, PR71 verifier and trusted GitHub reader.
report = link_protected_receipts(
    bridge, sources, forecasts,
    source_attestor=independent_source_attestor,
    protected_reader=reader,
    forecast_validator=pinned_original_validator,
    trusted_legacy_verifier=pinned_pr71_verifier,
    github_fetch=trusted_github_api_reader,
)
~~~

Example values are placeholders, never evidence of authorization. Do not feed whole-bundle data as if it were a per-race originally frozen forecast.

## Real owner-library readback (private temporary working copy)

The original Library file named keirin_20261103_forecasts.json was copied unchanged to a temporary isolated private workspace. Original bytes: **58,754**. Original whole-file SHA-256:

0a5d1d244e86ba98ab37640a9da83fb825cf2021b15eb2a05899d8fcf94eb4e2

The new adapter read and verified these actual bytes and checked a 76-race research bundle with 8 ordered predictions per race, unique race IDs, and the self-declared flags officially_frozen=false and calibrated=false. An incorrect expected SHA was rejected.

Local owner-only command:

~~~bash
python -m race_ai.owner_private_file_reader \
  --root /OWNER_DIRECTORY \
  --file keirin_20261103_forecasts.json \
  --expected-sha256 0a5d1d244e86ba98ab37640a9da83fb825cf2021b15eb2a05899d8fcf94eb4e2
~~~

Exit code 2 means verified research bundle readback, **not formally accepted per-race frozen predictions**. Exit 3 denotes rejection. The bundle SHA does not authenticate a separate original wire or original external receipt for each race, and must not be retroactively split into certified original records. Availability of an isolated copy does not mean GitHub Actions or PR72 production runtime has direct access to ChatGPT Library.

## Remaining acceptance gates

1. Identify the original owner-private per-race/model/stage forecast wires with pre-existing SHA pins. The MacBook/original research journals are not mounted into this session, so their existence and status are unknown.
2. Independently attest legal source-purpose authorization, source publication/capture time, and actual official sales cutoff for each race. Fixture callbacks and a user-written approved flag are not enough.
3. For a **future race**, obtain and read back the genuine independently timestamped race+model+SHA-bound GitHub receipt **before** the true cutoff. A historical whole-bundle witness cannot be promoted after results.
4. Obtain authorized official finalized results/return/payout revisions and complete daily eligibility denominators. Formal Hit@1, Hit@8, capture rate, purchase ROI and Brier/Log Loss remain null until these gates are satisfied. Preserve original NO_FORECAST rows.

Run the new offline synthetic checks:

~~~bash
python -m unittest discover -s tests -p test_owner_private_file_reader.py -v
~~~

No new PR, main merge, production changes, Secrets or permissions changes, automatic betting, provider scraping, charge, model modification or original forecast modification were performed by this work.
