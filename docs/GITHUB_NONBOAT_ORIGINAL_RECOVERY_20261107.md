# GitHub上の非BOAT学習原本の回復調査（2026-11-07 JST）

所有者の「どこにあるかわかんないよ。GitHubにないかな。」を受け、`haji84/RACE-AI` のブランチ・保存状態・過去履歴・Actionsを実際に読み取り調査した。**今回確認した範囲では、非BOAT16枠の学習に使える実入力原本は回復できなかった。** 見つかったSHA参照、事後監査、合成データを実入力に読み替えていない。

[公開可能な調査件数・保存物識別子](evidence/2026-11-07/github-nonboat-original-recovery-counts.json)を別途記録する。生データ、選手別値、私有保管先、鍵、学習係数、買い目は掲載しない。

## 実際に調べた範囲

| 対象 | 実確認 | 結果 |
| --- | ---: | --- |
| GitHubの観測時点の全ブランチ先端 | 108本 | 再帰tree取得108件すべて成功、切り詰め0件 |
| 上記tree中の候補データ | `(path, blob SHA)` 単位で1,247件 | 非BOATの実native入力コホートを回復できず |
| 既知の原本ファイル名 | AUTO20件とKEIRIN1件の計21名 | 全ブランチ先端のbasename一致0件 |
| ローカルに存在するcommit object | 到達可能1,136件＋未到達663件＝1,799件 | 既知の原本path一致0件、削除済みの適格な非BOAT原本も回復できず |
| 選定した関連Actions run | 15件 | 確認時点のartifact一覧はすべて空 |
| 新たに回復した適格な非BOAT学習レコード | 0件 | 各競技・各モデルの最低8レースを満たさず |

GitHubのref/state確認snapshotは **2026-11-06 23:35:33 UTC（11月7日08:35:33 JST）**。Actionsは11月3〜7日の関連workflowと既知の10月24日source-format runを対象に絞った。15 run IDと、別経路の`gh`でも0件を確認した7 run IDは集計JSONに残す。実行中jobや今後のrunが後から作る保存物まで0件と断定しない。

既知の探索名は公開監査に既出の `autorace_20261104_sanyo_{1..12}R_A_assistant_observed_RESEARCH.json`、`autorace_20261104_kawaguchi_{1..8}R_A_assistant_observed_RESEARCH.json`、`keirin_20261103_forecasts.json`。現在のブランチ名だけの検索で終えず、全108先端のファイル一覧とローカルの未到達objectも調べた。

## 実際に見つかった保存物と、その限界

### KEIRIN：暗号文は合成データ1世代

`state/keirin-encrypted-history` の観測HEADは `2c0f9edfe069ce8a190a348c4497c4ed906bd30a`。`state/keirin/v1/latest.json` とscopeは `mode=synthetic`、`generation=1`、producer run `41661810084`。proofも `synthetic_only=true` である。

残る暗号文は `state/keirin/v1/snapshots/g000001-c1bddac6a6b18b7a88a5eac1509ec27dcead28f4ecdb1a0b5fc9503dac84885b.enc`、103,986 bytes、cipher SHA256 `c1bddac6a6b18b7a88a5eac1509ec27dcead28f4ecdb1a0b5fc9503dac84885b`。これは回復可能な合成fixtureであり、実レースの学習資料として使わない。復号は行っていない。

実upload logから特定したartifact `13243000928` は `keirin-synthetic-encrypted-checkpoint`。producer run `41661810084`、job `126006642035`、保持期間3日。今回の実照会でメタデータはHTTP404、ZIPはHTTP410（期限切れ）だった。workflowも架空選手の入力を明記しており、期限切れ以前から実原本ではない。

過去commit `7a432e5acc4d3495a0e82bd79726929e2f8085fe` の `audit/sha-only/2026-11-03/keirin-aomori8r-9d42869e.json` は `RACE_AI_PRE_CUTOFF_SHA_ONLY_ANCHOR_V1`。wire SHA・bytes・買い目件数の参照で、私有原本をアップロードしていない旨を明記する。SHAは照合には使えるが、そこから失われた本文、本人名簿、特徴量を復元できない。

別の結果専用run `41683958185`（job `126084623493`）も確認したが、native入力原本のartifactはなかった。旧76レースbundleの存在記録も、買い目・順位スコアから入力特徴量を逆算する根拠にはならない。

### AUTORACE：私有原本参照・事後監査はあるが、学習入力本文はない

11月4日の原本20件はSHA・私有原本参照として残る。`docs/evidence/2026-11-04/autorace-research-import.json` は実際に監査した2件のsource/prediction SHAと時計を持つmanifestであり、元入力本文や独立した締切前receiptではない。`independent_receipt_verified=false` を維持する。

古い伊勢崎11Rの同一レース5回観測は、各回の `numeric_trial_car_count=0`。5回の観測を5レースに数えたり、取得できなかった試走を数字で埋めたりしない。11月6日の事後監査も、当時の全選手入力や独立保存済み予想を作り直す材料にはしない。

### HORSEと3競技公式ページ検査：取得証跡だけでは原本にならない

過去の `docs/evidence/P0_NONBOAT_FIRSTPARTY_3SPORT_REAL_AUDIT_20261024.json` を実GitHubバイトで確認した。例示refは `9a919373264e6828698f89ba598f49bb309030ac`。source-format run `40068720296`（job `120797338745`）は `prediction_executed=false`、`raw_provider_html_persisted=false`、3競技すべて本人識別・モデル入力内容の確認がfalseである。

JRA charset再確認run `40068909171` も `raw_html_stored=false`、馬に結合した当日値の確認はfalse。ページに接続した事実や内容SHAだけでは、馬ID付きの入力・実締切・元本文・8レースの教師例を回復できない。

## 調査範囲を越えた不存在は主張しない

全108ブランチ先端については取得成功・切り詰めなしを確認した。一方、1,799件は**この環境に存在する**到達可能・未到達commit objectであり、GitHubサーバーに残るすべての過去・未到達objectではない。Actionsも選定した15 runの実確認であり、全1,745 runを一件ずつ検査したという主張はしない。期限切れartifactや別の私有保管先の内容を確認済みとは扱わない。

したがって結論は「今回確認したGitHubの範囲では、適格な実非BOAT原本を回復できなかった」である。ChatGPT Library、別端末、別の未接続保管先まで原本が存在しないという断定ではない。

## 非BOAT16枠と次の最小工程

不足するのはKEIRIN共通5枠、AUTORACE共通5枠＋personal1枠、HORSE共通5枠の計16枠。BOATで実学習できた入力や結果は競技固有の本人名簿・特徴量契約を満たさず、これら16枠へ転用できない。公開プロフィールを今取得しても、その現在値や取得時計を昔の締切前へ戻せない。

次の最小工程は、既知の私有原本を既存の本人用保管経路から回復できる場合に元SHA・実保存メタデータを照合すること、または既存の承認済み経路で**これから**native入力を締切前に保存し、別に確定結果を受け取ることである。各枠につき最低8異なるレース、時系列の学習6・holdout2、真正な本人ID・出典・実締切・独立保存・結果/返還/revisionの一致を確認してから学習する。

本人IDを車番・枠番で偽造せず、買い目からratingを作らず、結果を事前特徴量へ混ぜず、時計や保存証拠を後付けしない。新しい許諾質問、アップロード依頼、新提供元の取得、復号、外部メッセージ、Git書込み、課金・クラウド追加は本調査で行っていない。4競技すべての実学習・未来PDCAの完了とは報告しない。
