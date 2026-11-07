# Opt-in private delivery transport V1 — 2026-10-25

This additive PR71 codec is a local transport proposal based on `8f19d0afdb5dad50a1e8f5e1a75252de09c1d708`. It is not a main/production, source-rights, producer-execution, pre-cutoff-freeze or accuracy claim. All observed fixtures below are fictional, including their source permissions and timestamps.

## Purpose and explicit entry points

Ordinary sorted JSON loses Python dictionary key types and insertion order. Existing PR71 model diagnostics use integer participant keys, and the suite and PR72 binding also check the model dictionary's order. An ordinary JSON reload therefore changes all sports' roster order; horse runner keys 10+ additionally change legacy hash ordering.

`race_ai.private_delivery_codec` provides two explicit functions:

```python
serialize_private_delivery(delivery) -> bytes
deserialize_private_delivery(raw, *, expected_delivery_sha256=None) -> dict
```

Serialization returns bytes only. It does not write files or alter the supplied object. Decoding returns fresh V1 containers with their original dictionary order, key types and scalar types. Repeated references become separate equal containers; preservation of an alias graph is not promised. Cycles and custom objects are rejected.

The accepted delivery is the existing `RACE_AI_PRIVATE_DELIVERY_V1` record produced by `deliver`: its exact known root fields, operator-research scope, four fixed untrained model families, consistent identities and original hash chain are required. Unknown root fields and promotion flags are rejected. The codec compares the existing snapshot/delivery hashes and invokes the existing `verify_suite` on both sides. It never recalculates a claimed hash and replaces that claim.

The default producer, CLI, `_private_write`, `read_json_bytes`, model outputs, model versions, coefficients and legacy canonical/hash functions remain unchanged. Plain V1 files are rejected by this decoder, with no implicit repair or alternate hash fallback.

## Wire format

The exact outer fields are:

```json
{"schema":"RACE_AI_PRIVATE_DELIVERY_TRANSPORT_V1","delivery_sha256":"<original V1 delivery SHA>","body":"<typed node>","transport_sha256":"<separate transport SHA>"}
```

`body` is a typed node, not the illustrative string above. The complete grammar is:

| Original value | Typed node |
| --- | --- |
| None | `["null"]` |
| exact bool | `["bool", value]` |
| exact int | `["int", value]` |
| exact finite float | `["float", value]` |
| string | `["str", value]` |
| list | `["list", [node, ...]]` |
| dictionary | `["dict", [[key_node, value_node], ...]]` |

Dictionary entries retain insertion order. Key nodes must be exact strings or integers; Boolean, float and custom keys are forbidden. Duplicate decoded keys are rejected before insertion. JSON floats remain floats, including `1.0`, negative zero and finite subnormals. Float strings, hexadecimal encodings and nonfinite values are not accepted. Strings undergo no Unicode normalization.

The wire is UTF-8 JSON with sorted outer object keys, compact separators, `ensure_ascii=False`, finite numbers and exactly one trailing LF. The transport digest is:

```text
SHA256(schema_ASCII + NUL + canonical_UTF8(envelope_without_transport_sha256))
```

There is no LF inside this digest preimage. The transport digest is separate from every original snapshot, suite, prediction and delivery hash, and from a checksum of the complete wire file.

The decoder rejects duplicate JSON object members, unknown fields/schemas, noncanonical JSON, BOMs, extra whitespace/newlines, malformed tags/arities and wrong scalar types. It accepts exact `bytes`, not text, bytearrays or memoryviews. Failures use a generic `PrivateDeliveryCodecError` without echoing private material.

## Resource limits

Limits apply before legacy digest validation:

- 4,194,304 wire bytes, including the LF.
- Semantic depth at most 32, with the original root at depth zero.
- At most 500,000 semantic nodes, including dictionary keys and repeated occurrences.
- At most 16,384 UTF-8 bytes per original string, including keys.

Encoding walks exact built-in types with cycle, depth, node and string checks. Strings exceeding the byte ceiling in character count are rejected before UTF-8 encoding; the bounded remaining strings are then checked for their actual UTF-8 byte length. It uses bounded `JSONEncoder.iterencode` chunks and stops before accumulating more than the wire cap; it does not first allocate an arbitrarily large JSON string. Decode checks raw byte length first and applies typed-tree budgets before legacy hashing. Limits are fixed; this slice does not expand storage, cloud quotas or provider request allowances.

## Verification observed locally

Python 3.12 with the existing root virtual environment was used. TDD began with 17 expected missing-module failures, followed by 17 passing codec tests. An independent review then identified the oversized-scalar allocation below; its regression increased the codec cases to 18, with two existing producer/permission cases included in the 20-test focused run. These execute the existing four-family research suite through the authored fictional delivery fixtures, without provider or cloud calls.

| Fixture | Wire bytes | Semantic nodes | Depth |
| --- | ---: | ---: | ---: |
| Boat, 6 entrants | 120,925 | 6,201 | 7 |
| Keirin, 7 entrants | 174,802 | 9,458 | 7 |
| Autorace, 8 entrants | 243,597 | 13,635 | 7 |
| Horse, 18 entrants | 2,685,258 | 163,485 | 7 |

All four original deliveries, model order, full candidate arrays, Top8 and original hashes remained unchanged, and `verify_suite` passed after decode. Re-serialization reproduced the identical transport bytes. A compact DAG repeating one 16 KiB string 1,024 times was rejected before legacy hashing; its observed peak traced allocation was 5,171,725 bytes, below the test's 12 MiB ceiling. This is a bounded synthetic observation, not a universal memory or performance guarantee.

Independent review reproduced an 8 MiB ASCII scalar being fully UTF-8 encoded before the byte check. The new regression allocated that caller input before tracing and observed 8,563,016 additional traced bytes in the RED run. The length precheck reduced the measured extra allocation to 176,107 bytes; the test requires less than 1 MiB and verifies that legacy hashing is never called. The subsequent UTF-8 check still rejects multibyte strings exceeding the same 16 KiB byte ceiling.

Other tests cover scalar types, negative zero, subnormals, Unicode, fresh containers, cycles, unsupported objects/keys, hash-chain tampering, rehashed identity mismatches, false promotion flags, caller identity binding, duplicate members/keys, malformed nodes and wire/tree resource limits. The original private writer's V1 bytes are also checked unchanged.

Ignored local evidence: `artifacts/private-delivery-codec-red.txt`, `artifacts/private-delivery-codec-green-initial.txt`, `artifacts/private-delivery-codec-size-and-limits.json`, `artifacts/private-delivery-codec-oversized-scalar-red.txt`, `artifacts/private-delivery-codec-oversized-scalar-green.txt`, and `artifacts/private-delivery-codec-oversized-scalar-probe.json`. Earlier test evidence remains a historical pre-fix snapshot.

## Authority and integration boundaries

With no caller-provided `expected_delivery_sha256`, decoding establishes self-consistency only. Supplying an independently obtained expected hash binds the requested delivery identity. Neither mode proves the rightsholder's permission, the actual model producer, input truth, calibration, full ranking correctness or a time of persistence. Existing full input, permission, binding and settlement checks remain required.

The codec does not add or change any publication, generation, ingestion or persistence timestamp. It grants no source rights or scoring eligibility. Model version values remain unchanged because this is a separate transport schema; prospective model ID/version/source-commit declarations still belong to the independent downstream admission process and are never inferred or approved by this codec.

The current GitHub freeze reader accepts its existing hash-anchor schema and original prediction hash. This transport is not a replacement anchor and has no new external receipt support. Persisted transport through PR72 binding/settlement requires separate cross-PR verification; genuine external immutable storage and pre-cutoff witnessing remain separate acceptance work.

No default CLI change, data migration, cloud write, deployment, source retrieval or public data release is included. Independent implementation review and exact-head CI are required before integration.
