# 実19枠の未来入力と、通信件数不明時の限定復旧

現行対象は30枠、実学習は19枠。リモートの所有者変更で除外された販売者1枠は、過去31枠の登録・MAC・SHAを保持し、学習済みへ加算しない。BOAT14とHORSE5は各8実レース・学習6／検証2、152原入力で学習した。実artifact `13565954830` を所有者キーで復元し、ローカルとの係数・支持数・holdout一致を確認した。[実CI候補の照合](evidence/2026-11-07/nineteen-native-model-ci-parity-counts.json)。全19モデルの432座標のうち支持174、変更171であり、支持不足の座標を無理に変更していない。[座標別の件数](evidence/2026-11-07/nineteen-native-parameter-support-counts.json)。既定registryは不変。

同runの全Python3,456件は成功（skip310）。全workflowは後段の合成動画fixtureのフレーム数不一致で失敗した。これを実学習失敗や全体CI成功へ読み替えない。[初回19枠CIの結果](evidence/2026-11-07/first-nineteen-ci-workflow-counts.json)。fixtureは6 packet／6復号画像／相異なる6画像・非ゼロPTSを固定し、並行変更を取り込んだ固定依存の動画461検査が成功した。後続の全体CIと実probeの結果は末尾の時刻別記録に示す。

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

当初の[準備件数](evidence/2026-11-07/reviewed-single-case-probe-preparation-counts.json)は、実capsule発行・再取得前のスナップショットである。その後の固定attempt 2による実probeは末尾に別記録する。新workflow・定期タスク・外部サービス・本番切替・購入は追加していない。

## 同一HEADの検証再利用と継続取得

新しいpreflightは、信頼するPR71のattempt 2に限定し、実capsule・全prior・元計画に加え、同じHEAD/runのattempt 1でfull Pythonとisolated videoが実行され成功したserver記録を確認する。全読取り後にも期限の残り180秒以上を確認する。成立した場合だけ、この2つの重い検査を再利用する。他の軽量検査・sourceの新しい認証・送信ごとの期限検査・実artifact読戻しは維持する。通常PR／初回／無効な記録では従来どおり検査する。再利用を新規テスト実行やデータ取得成功と報告しない。

復旧request V2の継続取得は、成功したprobeの元V1 capsule、完了journal、native原ZIP、raw RESULTの再認証と原文再解析を必須とする。最大8ケース・32要求、同じ元URLと原terms、全priorの終了から1時間以上、特定の新HEAD/run/attempt 2に限定する。旧実数不明／上限32は保持し、既知DENIEDや再中断を解除しない。通常RESULTを得た実probe・実継続取得はまだ成立していない。

結果取得用のrequest V3は取得日の実時計と1〜7日前の対象日を分離する。元plan・native入力・結果識別日は対象日のまま保持し、HTTP取得・生成・保存は実時刻を記録する。専用MAC付きの型付き許可なしでは標準collectorからも取得できない。公開された日付操作がない場合はHOLDとし、URL推測や入力時計の変更は行わない。AUTOの復旧request V1は当日1ケース／最大8要求の条件を維持する。


## 追加検証：11月7日20:28 JST

現行30枠中19枠が実学習済み、残AUTO6・KEIRIN5。最新c438／42364217725は初回・再実行とも全体SUCCESS（全Python3,614件、360 skip、動画283＋185件）。限定probeは8件・全200でもRESULT 0、上限到達HOLDである。旧UNKNOWN24／旧固定epoch上限32を保持し、新8件は別記録へ暗号化保存・元ZIP/metadata独立復元済み。3CSSの未cache消費を認証済み原本で確認し、元plan・最大8を変えない静的原本の再利用修正を進める。次の取得は12:09:07 UTC以降かつ新HEADの初回全体CI成功・新たな固定attempt 2の認証後に限る。

19候補3世代の実fit・暗号化Git保持・独立復元は完了。新19／全30の実未来PDCAは0。旧BOAT14の通常1レース・14組を流用しない。cash19 CLI接続は合成E2E成功、30候補の金額評価禁止は維持し、全30には順位目的だけの別CLI／Actions接続を実装し、合成35＋1件・独立レビューが成功。実未来30採点は未実施。新接続コードの全体CIと実未来採点は別の未完了条件である。

会場別履歴は11月6日原本を1 GETで追加し、7,003,764出走行・1,167,294レース・2,643選手×24場を再集計、既存Git commit505800f55176867e8a5a06491fcc18eadca8e070から原本群とgridを独立復元した。既存152学習原入力へ新履歴を遡って混ぜない。未掲載17日・未報告156会場日などは残る。日付延長CLIの既存検証記録の継承不具合を修正し、保存済みmenu/indexの再GET 0で新日1 GETを実行した。11月7日は公表待ち1日で成績加算0。暗号目録／新世代はcommit244a7312f1ad32ecf471e35be1c4247e46c5b8efへ保持し新8ファイルを独立復元、全旧世代込みの新commit Actions読戻しは確認待ち。詳細と指定12項目は[最新報告](REMAINING_MODEL_COMPLETION_20261107.md)、件数は[全CIとprobe](evidence/2026-11-07/c438-full-ci-and-bounded-probe-counts.json)・[11月6日grid](evidence/2026-11-07/nov6-all-racer-venue-grid-counts.json)を参照する。


## 復元の実CIと中断時の修正（11月7日21:00 JST）

29eca042／run42369144075は履歴のGit全祖先fetchが180秒上限となって復元job失敗。未発行capsuleのまま後続をcancelし、providerstepはSKIPPED・提供元アクセス0だった。[停止証跡](evidence/2026-11-07/29eca-cancelled-before-provider-counts.json)。履歴・gridの読取りだけを既存VaultGitRepositoryのshallow metadata／必要blob取得へ接続し、writerと保存形式は保持した。[実GitHubの固定manifest読取](evidence/2026-11-07/bounded-history-git-readback-transport-counts.json)は0.893秒・Git object891,789 bytes・鍵読取0・提供元アクセス0で一致。これは全原本群の復元完了ではなく、その新HEAD全体CIは再検証する。

独立reviewで、目録の暗号保存からV2 progress保存までの中断が同じ目録を再取得することも合成で再現した。未commitの既存要求は取得前HOLDとし、保存済み証拠を維持する。完成済みV2と認証済みHTTP待機の既存再開は維持する。新3再現テストをRED→GREEN、履歴・grid・暗号Git境界70件が成功。判定不能な中断を空の新規収集として再試行しない。

## 最新確認：11月7日21:39:30 JST

`901fb57d2d0f1d0fa0b4051285dca399654a4738`／[run 42371023982](https://github.com/haji84/RACE-AI/actions/runs/42371023982)はattempt 1／2とも全体SUCCESS。初回の全Python3,714件は失敗0・skip360（1,427.474秒）、動画283＋185件、UI31件が成功した。attempt 2では同じHEADの初回実成功を認証し、重い2検証を再利用した。[全CIと第2回限定probeの件数](evidence/2026-11-07/901-full-ci-and-second-bounded-probe-counts.json)。全体CIの成功と実RESULTの確保は別である。

第2回AUTO probeは実8 GET・全HTTP 200、document 1件＋背景取得7件で上限に達し、`HOLD_UI_OR_SOURCE_UNAVAILABLE`／`REQUEST_LIMIT`、新RESULT 0だった。認証済み過去原本からCSS 3件をcache再利用できた。`NORMAL_READ_IDENTITY`によるPOST拒否は2件だが、そのendpointはjournalに保持されておらず、原因URLや操作を推測しない。[原journal認証](evidence/2026-11-07/901-probe-journal-authenticated-counts.json)。artifact `13574582081`、digest `sha256:72d1b53eec547a73cff15955e6b7f179f1391283c28d218ca48be95e36e35c79` の元ZIP／metadata／暗号文をcommit `710b7437740ae38c05c68fb3a26cb00f4e54a374`へ保持し、独立Git読戻しと元バイト一致を確認した。[保持証拠](evidence/2026-11-07/901-probe-journal-retention-counts.json)。旧browser UNKNOWN24・旧固定epoch上限32は維持し、第2回の既知8件を別epochとして保持する。

実学習は19/30、残AUTO6・KEIRIN5、新19候補と全30枠の実未来PDCAは0のまま。次の提供元送信の最早時刻は、このrunの最終終了12:39:30 UTC＋1秒＋1時間による **13:39:31 UTC（22:39:31 JST）**。第3回requestは最大8の未発行準備であり、live planは変更していない。実時計・全prior終了・新しい同HEAD初回全体成功・固定attempt 2への認証を満たすまでは送信しない。

履歴／gridは、先行b569／[run 42370578793](https://github.com/haji84/RACE-AI/actions/runs/42370578793)の実Actions jobで全旧世代込みの読戻しが成功した。履歴263か月・掲載7,964日＝解析7,846＋部分原本117＋公表待ち1、gridは7,963原本・2,643選手×24場＝63,432セル。提供元アクセス0であり、公表待ちを成績へ加算しない。[全原本群とgridの実CI読戻し](evidence/2026-11-07/b569-full-history-grid-ci-readback-counts.json)。このjob成功をb569の全workflow成功へ読み替えない。
