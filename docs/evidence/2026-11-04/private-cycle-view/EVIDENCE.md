# 保存巡回JSON → 操作画面の検証（合成のみ）

2026-11-04 JST。既存Draft PR71に追加。実予想原本の取得成功や製品全体の完成を意味しない。

## 実装

- `private_cycle_capture`：既存認証で選択artifactを読み、元ZIP/metadataのバイトを非Git私有領域へ排他的に保存。ネットワーク本文上限・時間上限・元digest・所属repo・ID・期限を確認。
- `private_cycle_restore`：ローカルmanifest/ZIP/memberのピン、日付・締切・取得時刻を検査して読取専用復元。原本書換え、学習・予想・採点の再実行、HTTPなし。
- `private_cycle_projection`：保存済みP0/P1/学習版のTop8・全順位・SHAを投影。欠けた版・生成時刻・入力SHAはnull、結果観測は公式改訂/公式確定時刻と分離。
- `product-data.js` / `app.js`：専用schemaのみ追加、旧監査schemaの受付条件は維持。私有viewは研究/合成へ固定し、正式率へ加算しない。
- 既存viewer CI job内の同じ操作試験へ結合fixtureを追加。新workflow/巡回/taskなし。

## 失敗と修正

初回はcaptureモジュール未接続を7失敗で確認後に実装。独立レビューで「ダウンロード中に親ディレクトリを差し替えるとGit配下へ原本保存され得る」問題を合成データで再現し、親inode照合・O_NOFOLLOW・ディレクトリ参照経由の排他的書込へ変更した。Gitマーカー後付けも拒否する。取得・復元のrepo ID検査も揃えた。

復元ではP1締切のJST日付矛盾と、締切前の結果取得を拒否する回帰試験を追加。投影では結果JSON配列/補助status/training原本も保持し、予想原本以外のschemaを誤って予想として解釈しないようにした。別レースのlearning_snapshot、明示版と原本版の矛盾、実readerのサーバー秒精度も試験した。保存済み学習版の表示時には学習器を再実行しない。

ブラウザの初回追加試験は読込完了文言の待機条件が不一致で停止した。成功文言を待つよう修正し全幅で再試験した。比較画像のsticky headerがスクロール位置に残る問題は、保存前にページ先頭へ戻し位置を検査してから再撮影した。

## 検証結果

Python **661**、Node **169**、失敗/skip **0**。全Pythonは`TMPDIR=/var/tmp`で実行し、私有ファイルのGit/リンク保護を無効化していない。独立技術レビューの修正後再確認に重大指摘なし。

Playwright Chromiumで320/390/1440/1920の**29操作グループ・36PNG**を保存。7ページ×4幅に加え、保存巡回の詳細/履歴×4幅。2レース・14保存予想・2保存済み学習版・2結果観測を、ローカルの元ZIP → capture → restore → projection → ブラウザへ通した。全保存Top8/SHA、P0/P1と学習版選択、結果の取得履歴、未取得の公式確定時刻、正式率への非加算、ブラウザ永続化なし、外部source request0、page error0を検査。

添付の8参考画面と前工程の画面比較を継続し、今回もスマホ詳細とPC履歴を目視確認した。青緑/白/濃紺、ナビゲーション、カード、詳細タブ、PC右カラムを維持。実名・顔写真・架空の確率/評価数値を参考画像から実データへ転用しない。今回のキャプチャは合成表示と分かるラベル付き。実機Safari検証とは呼ばない。

[検証件数](validation-summary.json)、[ブラウザ操作ログ](browser-tests.log)、[Python全件](python-unittest.log)、[Node全件](node-tests.log)、[画面/ログSHA](sha256.json)。代表：[スマホ保存予想](390-saved-cycle-detail.png)、[PC結果観測](1440-saved-cycle-history.png)。

## 残る外部条件

この環境で実原本読戻しは0件。実行中環境のapi.github.comは許可未適用、Library接続なし。別writerによる既存BOAT実runの監査更新は保全しており、今回の合成試験結果とは混同しない。全16/全4競技のライブ全レース継続運転、期限なし本人専用保管、実機Safari、前向き精度改善は未達。公開・投票・main統合・本番採用なし。
