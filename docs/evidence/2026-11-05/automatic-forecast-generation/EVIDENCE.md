# ボタン不要の自動予想 — 2026-11-05 JST

既存PR71の個人用アプリに、HTTPサーバーの起動に従う自動巡回を接続した。ブラウザの生成操作は不要。最初にP0、以後は締切順のP1を確認し、既存nativeモデル・私有journalを使う。画面は180秒ごとの読取だけで保存済み原本を更新する。別cron/workflow/外部サービス/モデル系統は追加していない。

## 実予想とソフトウェア試験

| 確認対象 | 実測と範囲 |
| --- | --- |
| 既存GitHub自動運転 | run41929106428、実行コード63bc3ec、第11巡回までActions成功。11/05 08:23 JST保存時点で144レース、P0 288件＋P1 5件＝293件 |
| 展示後の独立保存 | P1は1レース×5既存モデル。artifact13372622656のZIP/API digest一致、GitHub保存08:23:52 JST、締切08:35。全5件が締切668秒前、生成時刻も保存より前 |
| ローカル自動起動 | 画面操作なしで巡回開始。4巡完了、保存済みP0再利用288、新規P1 0、取得カウンター3。既存GitHub writerを確認して追加巡回を停止 |
| ローカル画面 | 初回GETだけで288原本を読戻し。390/1440幅で12モデル選択/96点のTop8とSHAを照合。生成POST・外部ブラウザ通信・page/consoleエラー0 |
| 実native経路の自動試験 | 合成入力で実HTTP→自動controller→既存nativeモデル→SQLite→GET表示を検証。架空入力の4予想を実レース件数に加算しない |
| 全体試験 | Python877件・Node179件、失敗/skip0。合成ブラウザ4幅、37操作グループ、58PNG、page error0。独立最終レビュー40件成功 |

canonical293件を元ZIPから厳格にrestore/projectし、全SHA/Top8/時刻が一致。390/1440幅で新規P1の5モデルを各幅すべて表示し、計10選択/80点・SHA一致を確認した。予想生成POST・ブラウザ外部通信・page/console error0。これは保存JSONの表示であり、ローカル自動処理を再起動して取得・生成したものではない。

[canonical投影](canonical-view-summary.json) / [実P1画面](remote-browser-summary.json)。

[既存自動運転・保存時刻](remote-original-summary.json) / [ローカル実観測](local-observation-summary.json) / [原本の別来歴](separate-provenance-summary.json) / [試験記録](verification-summary.json) / [合成ブラウザ](synthetic-browser-summary.json) / [コードSHA](source-sha256.json)。実予想・公式原文・実画面・元ZIPはGit外の本人用領域で保持する。このフォルダのPNGは明示された合成データだけ。

## 停止・原本・表示の保全

180秒・最大24巡/65分・240GET/JST日・日付境界停止を維持し、同日再起動で開始時刻/回数/P0完了状態をリセットしない。P1は既存22分前対象選定・最大3新規レース/巡、210秒余裕と各GET前の終了時刻確認を使う。4xx/真正性エラー等の停止を迂回しない。65分後に次セッションへ自動移行する仕組みはない。全日常駐運転の完成とはしない。

ローカルとGitHubのP0は全288nativeキー/Top8が一致する一方、全原本SHAと生成時刻が異なる。ローカルの早い原本をGitHub受領済みと読み替えず、2来歴を別々に保持する。今回のローカル停止後、元288原本は不変。既存GitHub処理のrerun/cancel/追加起動は行っていない。

私有profileの単一writer lockは別マシンのGitHub workerと共通ではない。既存run稼働を見つけた後、ローカルの新規取得を再開していない。第5巡起動とSIGINTの競合を保全し、再起動時に`INTERRUPTED_ROUND_REQUIRES_REVIEW`で停止することを取得/推論0で確認した。同梱seedもこの停止状態を保持する。

表示はjournalの原本から再構築し、派生JSONを根拠として再予想しない。保存原文が同じ場合だけdecodeを再利用し、各読戻しのnative SHA検証を維持する。自動更新で入力中の金額・候補確定・原本選択・タブを失わず、手動JSON表示を上書きしない。P1待機中はP0を保持する。

## 再現した失敗と修正

1. サーバー終了時の1秒joinでdaemon巡回を置き去りにする競合を実観測。終了は進行中のcheckpointを待ち、STOPPINGで次の取得/保存を止める。有限240秒で未完了なら失敗を明示し、writer lockを解放した成功としない。1秒超の実行をブロックする回帰、timeout、繰返し終了による後続writerの状態上書き防止を追加。controller23件成功。
2. Nodeの返還試験が実時計の朝の予想windowに入り、予定外の取得を数えることを再現。既存の注入時計を昼に固定し、本番workerは変更せず、179件全成功。
3. 並行bootstrapの取り込み後、古いworkflow試験が「contents read・取得計上より先に補完」という旧手順を要求して失敗。現行のcreate-only初回索引、読戻し→初回B計上→補完→巡回を調査し、試験を現在の保全契約へ更新。workflow/bootstrap/day16件と全877件が成功。並行writerのworkflow本体をこの修正で変更していない。

初期871件成功、停止修正/並行取り込み後877件中1件失敗、契約試験修正後877件成功という各時点を混同しない。ログ本体は作業領域、最終ログSHAは検証JSONに保持する。

## 本人用配布物

`RACE_AI_20261105_automatic_app.zip`は12,762,191バイト/319ファイル。SHA256 `78aa10f498ee4d10eb5c7a96a72748a59224f34a87c5e7d517ce9479bcbfc81f`。ZIP CRCと全格納ファイルSHAを照合し、cache/symlink0。現行コード/固定参照276件、manifest付きseed20件、LOCAL288件と別来歴のGITHUB293件のJSON2個（各4MiB未満）、GitHub原本3ZIP/メタデータ/実画面証跡を本人用領域へ保存した。旧配布物は上書きしていない。

別の私有ディレクトリへのisolated起動確認は`LOCAL_FORECAST_READY: saved_predictions=288`、追加GET/推論0。seedにはsource/automatic lockと中断後の停止状態を含め、当日再起動で上限や停止を消さない。READMEでその状態、Linux/WSL2要件、クラウドのlocalhostと手元PCの違い、GitHub後続原本の自動同期なし、2来歴を合算しない閲覧を説明した。これは配布用ZIP作成でありアプリ/環境/リポジトリの公開ではない。[配布物照合](package-delivery-summary.json)。 独立再審査でも全member SHA/現行コード/seedを検証し、同梱3ZIPから293予想を新たにstrict restoreして全Top8/SHA/時刻/受領証拠の一致を確認。[独立配布物審査](independent-package-review.json)。

## 残る条件

競輪・オート・競馬の適格な当日入力、BOATの不足モデル、全レースP1、全日の単一writer継続、全原本の恒久私有保管、実機Safari、公式結果/学習版の十分な未来比較は未達。第11巡時点の結果・採点・学習版・同条件比較は0。ローカルアプリに新しい結果collectorを追加したとはしない。正式確率/回収率/精度改善/本番昇格は認定しない。

公開PR HEAD ab57ae2までをローカルで取り込み、mainは変更していない。今回の自動アプリ修正は未pushであり、既存GitHub runの成功をこの新コードのCI成功とは呼ばない。新PR/Issue/開発タスク/課金/環境公開/一般公開/実投票/本番モデル切替なし。
