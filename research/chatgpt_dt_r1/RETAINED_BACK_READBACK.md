# Independent B ciphertext readback

`retained_back_readback.py` reads exactly `manifest.json` and `candidate.sealed.json` from `haji84/RACE-AI` at a full immutable Git commit. It verifies the external receipt, exact response byte lengths and SHA-256 values, then calls the existing `back_candidate.verify_candidate_bundle`. It compares the verified manifest's candidate-byte, artifact/model and dataset identities with the external receipt. Temporary files contain only public metadata and ciphertext and are deleted when verification ends.

This operation reads no owner key, decrypts no candidate, downloads no race source, retrains no model and writes no remote or durable state. Its successful output keeps `owner_decryption_verified`, `candidate_plaintext_verified`, `source_authenticated`, `production_promoted`, `private_key_used` and `independent_run_verified` false. Actual independent-run acceptance requires a separate observer to inspect the GitHub run and this output. A local run identifies itself as local.

## Command

```bash
python -m research.chatgpt_dt_r1.retained_back_readback \
  --receipt research/chatgpt_dt_r1/evidence/20261128-continuation/back-retention.json
```

The only stdout record is `DT_R1_RETAINED_BACK_READBACK` followed by safe aggregate JSON. It contains the receipt-file byte SHA, archive commit/path, two file pins, candidate/model/dataset pins, source-code reference, verification counts and reader metadata. No plaintext model, prediction, source record or key is printed.

## External receipt format

The receipt has exactly these top-level fields. Its size is bounded at 64 KiB. Duplicate JSON keys, nonfinite values, unregistered fields and symlink receipt files are rejected. Whitespace formatting is allowed; the output retains the hash of the receipt's exact bytes.

| Field | Required value or format |
| --- | --- |
| `schema` | `DT_R1_RETAINED_BACK_RECEIPT_V1` |
| `repository` | Exactly `haji84/RACE-AI` |
| `archive_commit` | Full 40-character lowercase hexadecimal commit |
| `path` | `research/chatgpt-dt-r1/<bucket>/<manifest SHA-256>` |
| `source_code_commit` | Full 40-character lowercase hexadecimal training-code commit |
| `source_code_sha256` | Exact mapping for every `back_candidate.SOURCE_FILES` member; each value is a lowercase SHA-256 |
| `manifest` | Exactly `{"file":"manifest.json","bytes":N,"sha256":"..."}` |
| `cipher` | Exactly `{"file":"candidate.sealed.json","bytes":N,"sha256":"..."}` |
| `candidate_bytes_sha256` | SHA-256 of the exact private `back_candidate.json` bytes, as pinned in the manifest inventory |
| `artifact_sha256` | Composite candidate/model identity from the training receipt and manifest |
| `dataset_sha256` | Dataset identity from the training evidence and manifest |

The bucket starts with an ASCII letter or digit and otherwise contains only letters, digits, hyphens or underscores, up to 64 characters. The retained B path uses `research/chatgpt-dt-r1/20261128-back/<manifest SHA-256>`. Branch names, short SHAs, percent escapes, query strings, fragments, duplicate slashes, dot segments, filename substitutions and other repositories are rejected.

`manifest.bytes` must be a positive integer at most 64 KiB. `cipher.bytes` must be a positive integer at most the existing codec's `MAX_CIPHER_BYTES` limit. Boolean values are not byte counts. Both files must match the externally declared size and SHA; truncation, extra bytes and altered bytes fail. HTTP must be 200 at the exact requested URL. Redirects are rejected before a second request is sent. Nonidentity content encoding and ambiguous/mismatched framing headers fail.

## Source and reader commits

The twelve local B source/dependency-file hashes must equal `source_code_sha256`. The reader's current `GITHUB_SHA` is deliberately **not** required to equal `source_code_commit`: documentation and this reader may be added after training while the twelve B source files remain unchanged.

`source_code_commit` is retained external evidence; the public encrypted-bundle manifest does not expose the candidate's embedded source map. Output therefore states `source_code_commit_basis=external_receipt`. Local source-file matching and ciphertext verification do not claim decryption or independently prove that the encrypted model was trained by that commit. The source pin mapping must be established from the verified training commit/run before authoring the receipt.

On GitHub Actions, the reader additionally checks the canonical repository, numeric run ID and full reader commit before reporting that metadata. These self-reported fields do not certify their own run independently.

## Reuse by an approved owner restore path

The module exposes a context manager so the existing owner-key workflow can reuse the same strict readback without weakening it:

```python
from research.chatgpt_dt_r1.retained_back_readback import verified_bundle
from research.chatgpt_dt_r1.back_candidate import restore_candidate

with verified_bundle(receipt_path) as verified:
    result = restore_candidate(
        verified["directory"],
        new_private_destination,
        expected_manifest_sha256=verified["receipt"]["manifest"]["sha256"],
        owner_private_pem=already_approved_owner_key,
    )
```

The context yields `directory` (a temporary Path), `manifest`, `receipt` and `receipt_file_sha256` only after all ciphertext and external pin checks pass. It deletes the temporary folder on normal exit or exception. Obtaining the existing key, authorizing that environment and reporting real decryption belong to the separate owner restore path. The readback module itself never performs them.

Focused tests cover a real synthetic owner-encrypted envelope, exact-file readback, context cleanup, unequal training/reader commits, external identity conflicts, altered/truncated/oversized responses, strict receipt paths and sizes, duplicate keys, and a local HTTP redirect server proving that no second request occurs. These are contract tests, not evidence that actual owner restoration or prospective prediction has completed.
