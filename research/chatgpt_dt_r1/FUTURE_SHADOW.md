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
commit. It reparses the saved registry and retains **every registered race** in
the denominator. The target-day reader consumes the registry and saved
pre-race originals. The separately scoped official history reader replays
only results from the seven earlier JST dates at the same archive commit.
The protected forecast job uses the existing GitHub access and does not
fetch provider pages or change the key, permissions or schedule.

History joins use official registration IDs and results independently replayed
from saved source bytes. A revision must have been sealed by the actual input
clock. Forecasts using official history seal the selection policy, history SHA,
and verification receipt in the encrypted shared material. Settlement rebuilds
it at the original input clock and archive commit. A pre-history original
replays through its original empty-history path. The report's `history_races`
counts the number of prior race records used across sealed forecasts, including
reuses. The `result_reads` counter refers to target-day results and remains zero.

For a matched history study the protected producer also runs the same frozen
model without prior history before sealing. The encrypted material includes the
matched ranks, input hash, and exact market-distribution hash. Settlement
recomputes both sides from the same snapshot and clock before opening any
target outcome. Its paired report uses fixed points and the same admissible
race set on both sides, and preserves the independently timed day denominator.

The existing protected `dt-r1-shadow` dispatch can additionally compare the
retained final-back candidate by selecting `dt_r1_compare_back`. Both the
back-conditioned and direct variants use the same official snapshot, clock,
and 148-column input. The producer encrypts the receipt and exact distribution
hashes. Owner settlement replays both predictions before reading the target
outcome and scores their common officially verified finishes. Measuring the
final-back leader itself requires an authenticated race-phase observation.

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

Official registration IDs come from the same admitted source bytes. New
originals use verified prior races for those IDs when available. Reviewed motion,
weather, and unobserved official timing or S/B fields remain explicitly missing.
Every forecast's confidence remains `HOLD`.

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

### 保護runner間の原本保存と同日の再開

既存の `keirin-result-live.yml` をmainから実行する。`dt-r1-shadow` で公式締切の近い順に暗号原本を出力し、別runの `dt-r1-readback` にproducerの `dt_r1_producer_run` を渡す。readerが完了した後、`dt-r1-retain` にproducerと `dt_r1_readback_run` を渡す。

保存runはActionsの実artifactと両runの時計を再認証し、producerの資料commitが公式アーカイブの現在の系譜にあることを確認する。T−15を満たした新規枠のmanifest、読戻しレシート、暗号文と初回参照を、既存の `state/keirin-encrypted-history` へ一度だけ追加する。保全する原本の復号鍵は不要。更新競合時は同じ原本を再読戻しし、先に採用された枠のバイトを維持する。

保護された `dt-r1-settle` に `dossier_day` を渡すと、指定したJST日の最新公式登録を分母とし、各枠の最初にT−15を満たした保全原本を採点する。該当日では従来形式の初回原本も対象に含める。保全したmanifestと独立読戻しを再認証し、所有者鍵で公式入力、特徴量、凍結予測を再現してから、同じstateの最新公式結果と既存PDCAを照合する。公開レシートは件数・固定点数の成績・保留内訳を返す。日付を省略すると従来の初回検証を再現する。

同日の同じ日・モデルでは一つのproducer→reader→retainを完了してから次のbatchを始める。同日の次のproducerは、初回追加時のGitバイト、現時点の暗号文、Actionsの実証跡を照合し、採用済み枠を `PREVIOUS_T15_ORIGINAL_PRESERVED` として登録分母に保持する。11月28日の既存初回原本も従来のpinと独立runから確認する。上限で保留した枠は、締切までの時間と公式資料がある場合に後続batchで扱う。未認証・時刻超過の枠を採用せず、通常のGit fast-forward以外の保存は行わない。日をまたぐ自動起動、一般化した公式結果照合と全国の稼働実績は別途検証する。

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
