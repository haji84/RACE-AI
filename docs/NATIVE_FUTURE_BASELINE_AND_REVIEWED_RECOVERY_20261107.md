# 実19枠の未来入力と、通信件数不明時の限定復旧

実学習は19/31枠。BOAT14とHORSE5は各8実レース・学習6／検証2、152原入力で学習した。実artifact `13565954830` を所有者キーで復元し、ローカルとの係数・支持数・holdout一致を確認した。[実CI候補の照合](evidence/2026-11-07/nineteen-native-model-ci-parity-counts.json)。全19モデルの432座標のうち支持174、変更171であり、支持不足の座標を無理に変更していない。[座標別の件数](evidence/2026-11-07/nineteen-native-parameter-support-counts.json)。既定registryは不変。

同runの全Python3,456件は成功（skip310）。全workflowは後段の合成動画fixtureのフレーム数不一致で失敗した。これを実学習失敗や全体CI成功へ読み替えない。[初回19枠CIの結果](evidence/2026-11-07/first-nineteen-ci-workflow-counts.json)。fixtureは6 packet／6復号画像／相異なる6画像・非ゼロPTSを固定し、最新の並行変更を取り込んだ固定依存の動画461検査が成功した。Ubuntu上の全体再検証は次HEADで確認する。

## 未来入力の接続

新しいJRA凍結V3とsource packet V2は、過去に実保存された別のbaseline artifactを明示する。キャリアは旧BOAT12／14枠の実artifactへ別途固定し、入力だけの保存を、学習候補の変更で予想生成へ変化させない。旧形式は維持する。

- JRA V3は `horse_baseline_artifact` と `carrier_artifact`、packet V2は競技別 `baseline_artifacts` と `carrier_artifact` を指定する。run／head／digest／owner判断とモデル作成時刻を再認証する。
- baselineの実保存後に取得した新しいカードだけへ結合する。旧capsuleの時刻・特徴量を書き換えない。原文から元のas-ofで再計算した全native入力との一致を確認する。
- HORSEのV3用未来計画は `audit/state/manual-official-future-freeze-input.json`、AUTO／KEIRINのV2用計画は `audit/state/official-source-packet-future-freeze-input.json` が存在する場合に優先する。未作成の計画から取得成功を主張しない。
- 未来比較V4はBOAT14＋HORSE5に限定。各競技の共通8件・6/2分割、別baselineの保存が候補学習より前であること、元入力・owner判断・origin暗号文・実artifact読戻しを確認する。同じ重みなら同じ重みと記録し、改善を主張しない。
- 旧V1/V2/V3は従来の12／14／30枠の契約を維持する。現19候補にはAUTO／KEIRINの学習済みモデルがなく、新packetでもHOLDになる。

JRAの2026年日曜即PAT締切は、保存済み[公式発売時間](https://www.jra.go.jp/dento/soku/instructions/hatsubai/jra.html)の「当日発売」表、日曜の行、締切列とrowspanを検証して発走1分前とする。原文69,638 bytes、SHA `cb55c200a8c2be08014807608651053a1b70a6d005ddc7e3430576197c28bcb9`、取得時刻 `2026-11-07T01:46:03.024410Z`。土曜やWIN5・前日発売の記載を借用しない。これは規則原文の確認であり、実未来カードの取得・予想・PDCAではない。

## 旧UNKNOWNを消さない限定復旧

実journal `13565712487` は、JRA8 GETが200、browser予約24件の実数は不明のまま。新しい診断・隔離の実装では、この失われた実数を復元できない。元journalとSHAを保持し、既知8＋予約24＝上限32を計上する。

既定のcollectorは引き続き停止する。別入口の `official-result-recovery-request.json` は、同じ旧原本・通常UI・1競技1ケース・最大8リクエストだけを指定する。初回実行は提供元アクセス0のHOLDとする。

同じHEADのActions attempt 1が全体成功した後、操作者が全prior runの終了・attempt・head・時刻、実journal、原計画と新計画を確認し、専用MAC付き暗号capsuleを既存transfer refの一度限りの名前へ追加する。capsuleは特定のrun／HEAD／attempt 2へ消費済みとして結合する。全prior処理の最終動作可能時刻から1時間以上空け、期限前の各実送信を検査する。

同じrunのViewerジョブのattempt 2だけがこのcapsuleを読める。別HEAD・別attempt・別出力先への再消費、原本不一致、既知の401／403／429・DENIED・host停止は解除しない。再び実数不明なら停止する。新しいjournalと原文の暗号化隔離を別に保存し、旧UNKNOWNをCOMPLETEや実数0へ変えない。

現在は計画の準備までで、実capsule発行・再取得はまだ行っていない。[準備件数](evidence/2026-11-07/reviewed-single-case-probe-preparation-counts.json)。新workflow・定期タスク・外部サービス・本番切替・購入は追加していない。
