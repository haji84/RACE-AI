# 選手イラスト

オーナーが承認した、公式プロフィール写真を元にする自然なイラスト調・ヘルメットなし・背景透過の画風を使う。髪型、表情、年齢や顔立ちは各選手自身の写真に合わせる。別の選手のイラストは画風の参考だけに使用する。

初回対応は松井繁（3415）、白井英治（3897）、池田浩二（3941）、毒島誠（4238）、峰竜太（4320）、桐生順平（4444）の6名。全選手のイラスト作成が完了したものではない。対応数と参照元は設定画面の「選手イラスト」から確認できる。

## 表示

`web/racer-portraits.js` は競技と登録番号で画像を選ぶ。氏名・複数の登録番号フィールドが矛盾する場合、未知の登録、合成表示、他競技には実選手の顔を割り当てない。未作成は「イラスト準備中」、画像エラーは「イラスト読込待ち」としてカードを保つ。

画像は同じサイトの `assets/racer-portraits/boat-<登録番号>.webp` から読み込む。閲覧中に公式写真サーバーへ通信しない。元の生成PNGは作業領域に保持し、Web配信には画素を変更しないlossless WebPエンコードを使用する。

## 追加

1. 公式プロフィールの登録番号・氏名と実際の写真URLを照合する。
2. その選手の写真だけを本人の参照とし、承認画風で画像を生成・確認する。
3. WebPとJSのレジストリに追加し、`race_ai/racer_portraits.py` の固定配信リストも更新する。
4. `node --test tests/racer_portraits.test.cjs` と `node tests/racer_portraits_browser.test.cjs` で本人対応・欠測・表示を確認する。

## 保存済みサイトの画面だけを更新する

`race_ai.saved_pages.refresh_site_assets(repo, expected_parent=<独立確認したgh-pagesのSHA>)` は既存の公開manifestを検査し、画面・画像とそのハッシュだけを更新する。暗号文ファイルのGit blob、予想のハッシュ、表示ID、保存件数は保持する。復号鍵・SQLite・本人用URLを引数にしない。

親commitが変わった場合は更新を拒否する。最新状態を確認し直し、他の変更を保持してから更新する。main統合、アクセス設定変更、予想生成、公式データ収集、追加サービスの導入はこの操作に含めない。

検証コマンド:

```sh
node --test tests/racer_portraits.test.cjs
node tests/racer_portraits_browser.test.cjs
python -m unittest tests.test_saved_pages tests.test_saved_pdca_view tests.test_local_forecast_server -v
```
