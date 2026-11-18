# RACE-AI 最新状況 — 2026-11-18 10:12 UTC

**GOALは未達。** この文書は現在の事実だけをまとめる。従来の全文は[履歴](history/RACE_AI_STATUS_HISTORY_THROUGH_20261118_0928.md)へ、同じGit blobのまま保全した。実予想原本・モデル重み・元の判定を変更しない。

## 実行環境・HEAD・保全

- main実装: `39fec2df5ab68920d7cd4f0388307b07925409c5`、tree `927eafc67fbe3ebc4290518c4879c1085fa8e193`。既存PR32の通常mergeでtested tree一致。359件/127.452秒、15checks＝8success/7skip/失敗0。
- source: `c979aeb678538d99e277f26726047dccbdc982af`、tree `766b8a3ea5d9d3b85e0f399523ede2eb8f1b688b`。PR34の通常mergeでtested tree一致。877/38/165/46件等が成功。mainの現行参照は同期済み。
- 選択実行環境はfailed。実コマンド再試行も利用不可。公開WebのSign in表示ページからrepo/READMEのread成功（cacheでありHEAD証明には使わない）。別にGitHub管理接続の認証済みread・write・通常保護mergeは実成功しており、ローカルCLI認証の検証とは区別する。キーはActions内だけ。
- 元offline変更PR70 `b7380fe6a377e6ccf2b96331f2126c52549bbe17`、PR292 `daae4c10167224b7730006d8ada5ade398aaa64b`は、08:40:39 UTC正規APIが両方422 No commit foundで**未復元**。別環境のファイル移転を仮定しない。
- 新PR・モデル系統・課金・job・workflow input・cron・runner・timeout・権限・marker名・UI公開・投票・本番重み切替を増やさない。既存OFF pilot/PR290/291/main308・legacy KEIRIN-AIも維持する。

## 自動予想と原本

元run43829249080のP0保管失敗と24巡skipは履歴として残す。修正後のA74 run44218343091は24巡success/skip0。正規別runner44268654165と再実行44276148160で24巡の最終control・73AES archive・ALL_MODEL 23 ZIPを認証し、P1 **513行**がsaved AES viewと一致、欠落0。公式P0 scheduleは132レースとして認証した。513行は固有レース数・完全P0/P1 union・適格分母ではない。

round4/19のALL_MODEL ZIPが欠けるため `HOLD_ALL_MODEL_ARCHIVE_ABSENT_UNEXPLAINED`。締切適格数0は全体HOLDの監査結果であり、全行が締切後という証拠ではない。旧実行の正規完了ログではr4はcontexts=0/generated=0の明示分岐、r19は保持locator未選択のartifact metadata/ZIP読取404だった。r4の入力網羅性、r19の対象・404根因は不明で、HOLDを解除しない。[各巡の固定証拠](evidence/boat-a74-round04-round19-source-facts-20261118.json)。以前のr0=660、A74 r0=585、reused285、retained264/waiting924などは対象が異なり、単純合算しない。[実独立監査](evidence/boat-main-sync-closed-a74-actual-20261118.json)。

10:17 UTC現在、後続run44252479726は旧A74のまま1〜7巡success/8巡実行中/failed0。停止・hotswap・counter resetをしていない。cacheと固定理由診断は次の正規source workerからで、実速度改善・T15〜10全件充足は未確認。

## ペア監査の実際の拒否理由

固定理由一覧に不足していた12定数を補い、359件の実CIを再通過した。実再監査44280659186/job134720142693はsuccess、認証済み原本との結合で **`PAIR_RESULT_JOIN / ALL_MODEL_INTAKE_RESULT_ACTUAL_CUTOFF_MISMATCH`** を確認した。予想に保存した締切と結果journalの`closed_at`が一致しない。coreの23ZIP/513行一致と4/19欠落HOLDは維持される。ペア件数・適格分母はnullのまま。[正規ログの固定理由証拠](evidence/boat-current-pair-cutoff-rejection-20261118.json)。

コード追跡では、両方とも公式ページの「締切予定時刻」を入力としている。結果の後の予定時刻改定か読取不具合か、実原因はまだ未確定。予想締切・結果原本を書き換えず、既に認証したメモリ上のレコードから不一致件数/方向だけを診断する変更を既存PR31で実装した。先行364件/128.768秒は未実装APIの想定5assert失敗/errors0、既存359件と新正常系は成功。新実装の最終CI・実原本での追加件数は未確認。現行の拒否、正常HOLD、cutoff/roster/結果/保存時刻の全条件は維持する。[固定契約](evidence/boat-current-pair-cutoff-diagnostic-contract-20261118.json)。

固定vault indexには当該runのSOURCE_CAPTURES参照26件があるが、必要なraw本文の認証済み存在はUNKNOWN。A74の既存reader・対応8groupのraw source SHA参照・元parserを使う[再解析の読取手順](evidence/boat-current-pair-raw-replay-recipe-20261118.json)を保存した。metadataの宣言値・重複captureを実原本件数や再現成功にしない。

## 画面・4競技・映像・精度

| 完成条件 | 実確認と残件 |
| --- | --- |
| スマホ/PC・Safari | 実Mac26.6/run44258108084で11/18世代433、結果79/native原本9group、2model原本比較、browser AES成功。固定暗号文loopback再生でありGitHub暗号feed直接配送の証明ではない。物理iPhone・本人login・全8参考画面目視はfalse。ed904候補の28PNGは合成のみ、公開UI f603を変更していない。 |
| 全レース×全適用既存model | BOATは上記の部分実証。完全union/全日/T15〜10/継続日跨ぎは未証明。AUTOの個車入力、JRAとNARの適用区別、4競技全日の独立証明も未完。 |
| 競輪 | 最新canary44236121551は日次indexHTTP403。discovery44222760913の79リンク/8会場はidentity-only。capture/PR71のjob成功もskipまたは入力不完備HOLDで、予想・結果件数はnull。[実4run](evidence/keirin-current-automatic-blockers-20261118.json)。 |
| 6艇の継続識別・校正・予想接続 | 同時6艇の独立GT/承認済み映像/実race結合が未確認。既知Commons映像は2〜3艇で、6艇精度や校正を証明しない。 |
| 前向き精度改善 | 11/3方針073379は事前に存在（100matched/5日/10会場日）。今回nativeセルとの適用は未判定。574 PDCA pairsや過去holdoutを適格分母へしない。本番重み変更0、改善・98%は未実証。 |

競輪の承認は[WINTICKET/KEIRIN.JP限定](https://github.com/haji84/RACE-AI/blob/fe7e5581263b2b31fbd45536ac6a611c2779fa65/docs/KEIRIN_WINTICKET_KEIRINJP_OWNER_SOURCE_APPROVAL_20261109.md)でKdreamsを除外する。許可済みraw/JSON/CSV、7/9人roster・公式締切・critical入力・目的別grantが必要。既存offline取込はある。保管先/設定名だけを本人へ質問済みで、鍵やpasswordをチャットへ要求していない。

既存Actionsの正規実行と通常保護mergeの承認は継続しており、完了したコードを再承認待ちにしない。UI公開・投票・本番重み切替は別であり未実施。未確認を完成扱いしない。
