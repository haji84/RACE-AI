# DT-R1 first future shadow

`scripts.keirin_dt_r1_future_shadow` makes **new DT-only private forecasts** from
the existing saved official-SP originals. The original A/B generation time is
never used as the new DT generation time. This does not establish a three-model
contest, a winner, improved accuracy, or production adoption. The approved
baseline recipe and independent new-forecast readback remain separate gates.

## Execution boundary

The entry point calls the unchanged
`keirin_official_nationwide_continuation._runtime(mode='study')`. Only a manual
dispatch on reviewed `main`, in the existing `keirin-result-live.yml` /
`observe-results` job with its existing owner key and source/store opt-in can
pass. It checks the actual checkout commit and pinned owner key pair. A branch,
scheduled invocation, different job/repository, invalid key or private output
under a Git checkout cannot pass. The requested day must also be the actual
current JST day; historical replay is not a mode of this script.

The script uses the existing `RecordStore`, pinned to one fetched archive
commit, and reads only its registry and original records. It reparses the saved
registry and retains **every registered race** in the denominator. It never
reads a result envelope, fetches a provider page, acquires a provider lease,
trains, changes a source-access gate, publishes state or schedules anything.
An index may contain results; their presence does not enable result reads.

Each usable original must pass the existing `records.admit_original` with the
real `GitHubEvidenceClient`. `official_inputs.prepare` then requires a second
re-admission and an exact digest comparison of its private source/normalized
input verification packet. The existing independent source proof's actual
server-evidence time is preserved. A new digest alone is never source admission.

## Frozen computation

| Item | Exact pin |
| --- | --- |
| Public model file | `evidence/20261128-resume/frozen_model.json` |
| Model file SHA256 | `dab8c7f014c41ac18e4fed1ae28ac9b36e994611d1fcf5992f8b06e31a4c618b` |
| Internal model SHA256 | `5e022092a35c0258954090c6f3d0f8fa14f03f22511b28d6aa9183f5a38c381c` |
| Venue sidecar | `fixtures/venue_geometry.json` |
| Venue sidecar SHA256 | `a7d832a2661c6f05167e7a412a55e51183c21e746447f91dac44e14eeb4dfe19` |

`RankModel.from_dict` verifies the internal model hash. Eleven inference-source
files must still match the model's frozen source hashes. The comparison module
is not part of this prediction path and is not called. The approved research
runtime is Python 3.12 with `research/chatgpt_dt_r1/requirements.txt` installed.

Official registration IDs come from the same admitted source bytes. The first
version deliberately has **zero admitted historical races**, no reviewed motion
records and no weather records. It does not join archive composite identities,
names or car numbers to histories. These inputs remain explicit missing values,
and every forecast's confidence remains `HOLD`.

The existing feature path is `official_inputs.prepare` (106 columns),
`augment_features` using the pinned `VenueStore`, `augment_agari`, then
`augment_abilities`. The final names must exactly match all 462 frozen model
columns. No padding or replacement feature code is used. Every venue-sidecar
retrieval clock must precede the input clock. The store's normal effective-date
rules apply with `allow_current_geometry_assumption=False`; an absent venue
retains its existing missing indicators and is counted in the safe report.
The 43 source records in the pinned sidecar were retrieved on
2026-11-27 from 15:59:53 to 16:01:05 UTC. Those declared retrieval clocks are not
an independent server-timed forecast admission.

The model's creation and information-end clocks must precede the new prediction.
The new completion clock is recorded after computation. The full trifecta and
exacta distributions and every rider's finish-position marginals remain inside
the encrypted payload; no ticket selection or new confidence policy is adopted.

## Actual clocks and output

The source/feature input, model computation start/completion, seal request and
actual post-save local readback clocks are distinct. The published cutoff must
be at least 15 minutes after generation and after the local save/read/decrypt
completion. A computation or save crossing the boundary becomes HOLD. A late
saved cipher remains as failed evidence; it cannot be relabelled timely.

The output directory must not already exist. It is created outside Git with
0700 permissions; files use the existing create-once 0600 writer. The only
output files are:

- `manifest.json`: strict schema `DT_R1_FUTURE_SHADOW_MANIFEST_V1`.
- `<slot_sha256>.sealed.json` for each encrypted forecast, using the existing
  pinned-owner RSA/AES `keirin_official_run_history` codec.

The private payload schema is `DT_R1_FUTURE_SHADOW_ORIGINAL_V1`. It contains the
actual forecast, complete feature row, exact source-projection hash/schema,
source receipt, common material, original/registry archive references, run/code identity, and a
safe report. It exists in memory and encrypted form, never as plaintext output.

Raw source documents are already retained in the existing official original at
the pinned `source_archive_commit` and source-original evidence/cipher hashes.
The new cipher does not duplicate those documents. Its
`shared_material.source_projection_sha256` is computed from the exact full
`official_inputs.source_projection(payload, original)` during prediction.
A later owner reader must load that saved original, independently re-admit it,
recompute the projection and compare the exact hash/schema. Missing original
state or a mismatch is HOLD, never permission to replace the source. The retained
reference preserves source evidence while keeping new ciphertext artifacts
within the existing transport's bounded size; it does not authorize raising that
transport limit.

The manifest contains hashes, timestamps, counts and finite status codes only.
Every registered race has an entry keyed by
`digest({'day_jst': day, 'race_id': race_id})`; raw race/registration IDs, source
documents, features, ranks, probabilities and private keys are excluded from
the public manifest and stdout. Its registry cipher/plaintext hashes plus
`summary.source_archive_commit` bind the saved registry, so a later owner reader
can recover all scheduled IDs without publishing them. Missing original,
unverified source/input, unsupported model/context, insufficient time and local
readback failure are never omitted from the declared denominator.

`verify_output(directory, expected_manifest_sha256=...)` checks exact manifest
fields/types, counts, fixed model/context identity, all listed ciphertext files,
their hashes/owner-envelope bindings and clocks. It refuses extra output files
or unknown public fields. It does **not** establish the server time of a newly
saved forecast or independence from its producer. Successful entries remain
`SEALED_PENDING_INDEPENDENT_READBACK`, and
`independently_admitted_new_forecasts` remains zero.

Create-once applies to **this output bundle**. A caller can create another bundle
in a different directory/run. The durable integration must pin the first
accepted `(day, race slot, model)` original, preserve that ciphertext and reject
replacement or duplicate performance counting across runs. This module does not
invent a second canonical state/PDCA authority. A fixed manifest and independent
GitHub producer/readback evidence must be retained before any later scoring can
admit a future original. An expiring Actions artifact alone is not indefinite
retention.

## Existing-job call

Use only inside the existing eligible protected job, with its unchanged owner
secret scope. The CLI consumes the existing private-key environment variable
before launching the archive subprocesses. Dependency installation must occur
with the private-key environment variable unset, as in the owner-restore mode.

```sh
python -m scripts.keirin_dt_r1_future_shadow \
  --repo . \
  --private-root "$RUNNER_TEMP/dt-private" \
  --output "$RUNNER_TEMP/dt-safe/future" \
  --owner-public-pem docs/evidence/2026-11-18/keirin_owner_existing_rsa_public_spki3072.pem \
  --day 2026-11-28
```

The parent directories must already exist, and `--day` must match the actual
JST date. Stdout is a safe aggregate with the manifest hash/byte count and total
cipher file/byte counts. Exit 0 means at least one locally timely encrypted
shadow awaits independent readback. Exit 2 means HOLD; a valid all-HOLD manifest
may still exist and should be retained as diagnostics. Exceptions never print
source text, private identifiers or raw key errors. No real owner operation is
proved by the synthetic tests.

Focused verification:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_keirin_dt_r1_future_shadow -q
```
