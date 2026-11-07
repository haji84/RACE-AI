# 選手イラスト

オーナーが承認した、公式プロフィール写真を元にする自然なイラスト調・ヘルメットなし・背景透過の画風を使う。髪型、表情、年齢や顔立ちは各選手自身の写真に合わせる。別の選手のイラストは画風の参考だけに使用する。

対象1,669名全員分を作成した。公式期別台帳2026-2の1,643名と、2026-11-07取得の公式検索一覧1,657名の和集合で、検索一覧の追加26名も含む。初回承認済みの松井繁（3415）、白井英治（3897）、池田浩二（3941）、毒島誠（4238）、峰竜太（4320）、桐生順平（4444）の6名は同一バイトのまま保持した。対象と名簿の根拠は `docs/evidence/2026-11-07/racer-portrait-roster.json`、48シートの作成・確認記録は同日の `racer-illustration-batches.json` に保存する。対応数・氏名検索・参照元は設定画面の「選手イラスト」から確認できる。

## 表示

`web/racer-portraits.js` は競技と登録番号で画像を選ぶ。氏名・複数の登録番号フィールドが矛盾する場合、未知の登録、合成表示、他競技には実選手の顔を割り当てない。未作成は「イラスト準備中」、画像エラーは「イラスト読込待ち」としてカードを保つ。

初回6名は同じサイトの `assets/racer-portraits/boat-<登録番号>.webp`、追加1,663名は `sheet-<連番>.webp` から読み込む。最初の3シートは5×5、残りは6×6で、CSSが該当選手のセルだけを表示する。閲覧中に公式写真サーバーへ通信しない。元の生成PNGと参照写真は私有作業領域に保持する。Web配信には初回6名はlossless、追加シートは品質90のWebPエンコードを使用する。オフライン書出しは対象レースで必要な画像を重複なく埋め込む。

## 追加

1. 公式プロフィールの登録番号・氏名と実際の写真URLを照合する。
2. その選手の写真だけを本人の参照とし、承認画風で画像を生成・確認する。
3. WebPと、本人の参照写真SHA・公式プロフィールURL・画像/セル対応を `web/data/racer-portraits.json` に追加する。同JSONから `web/racer-portraits-data.js` を生成する。Pythonの検証済み配信リストもJSONから導出される。
4. `node --test tests/racer_portraits.test.cjs` と `node tests/racer_portraits_browser.test.cjs` で本人対応・欠測・表示を確認する。

## 公式出走表の省略名

公式B出走表では、5文字以上の氏名が4文字で記載されることがある。登録番号と公式原文の氏名を照合した表記を `aliases` に保持し、同じ選手のイラストへ対応させる。2026-11-07の再確認では52日分・1,620名の公式表記を検査し、169名分の省略表記を追加した。根拠は `docs/evidence/2026-11-07/racer-portrait-official-name-aliases.json` に保存する。カタログやブラウザ用データを再生成するときも、この確認済み表記を保持する。画像54点と各選手のセル対応は変更していない。

## 保存済みサイトの画面だけを更新する

`race_ai.saved_pages.refresh_site_assets(repo, expected_parent=<独立確認したgh-pagesのSHA>)` は既存の公開manifestを検査し、画面・画像とそのハッシュだけを更新する。暗号文ファイルのGit blob、予想のハッシュ、表示ID、保存件数は保持する。復号鍵・SQLite・本人用URLを引数にしない。

親commitが変わった場合は更新を拒否する。最新状態を確認し直し、他の変更を保持してから更新する。main統合、アクセス設定変更、予想生成、公式データ収集、追加サービスの導入はこの操作に含めない。

検証コマンド:

```sh
node --test tests/racer_portraits.test.cjs tests/racer_portrait_atlas.test.cjs
node tests/racer_portraits_browser.test.cjs
python -m unittest tests.test_racer_portrait_catalog tests.test_saved_pages tests.test_saved_pdca_view tests.test_local_forecast_server -v
```
