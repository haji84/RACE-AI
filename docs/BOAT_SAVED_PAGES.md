# 保存予想をGitHub Pagesで見る

既存の7ページと保存予想を、同じGitHubリポジトリの `gh-pages` から配信する。公開ファイルには画面コード、合成テスト例、暗号化した表示用JSON、件数とハッシュだけを含める。平文の予想・結果、SQLite、鍵は含めない。

本人向けの閲覧URLは、Git外の私有ディレクトリの `owner-url.txt` に保存する。リンクのfragmentをブラウザ内で読み、AES-256-GCMを検証して既存の画面に渡す。リンクを知っている人は閲覧できる。URLなしのログイン認証を実装したという意味ではない。秘密リンクをIssue・PR・公開文書に貼らない。

閲覧用の鍵は、原本保存用 `RACE_AI_STATE_KEY` と異なる。この処理はActionsのキーを読み出さず、原本の暗号化状態・モデル・実行中workerも変更しない。表示時のモデル実行、収集、採点はしない。

## 作成

既に同期・照合した私有stateの内容SHAを指定する。出力先はGit外の別々のディレクトリにする。

```sh
python -m scripts.boat_saved_pages build \
  --state /private/pdca.sqlite \
  --source-sha <照合済みstateの内容SHA256> \
  --public-dir /private/pages/public \
  --private-dir /private/pages/owner
```

標準出力には公開用manifestとハッシュだけを出す。`owner/viewer.json` と `owner/owner-url.txt` は0600のまま保持する。通常はビルドごとに別の秘密リンクを発行する。既存リンクを維持する更新では、`--viewer-from /private/previous/owner/viewer.json` を追加する。既存の閲覧専用鍵と認証済みview_idを再利用し、暗号文・nonce・配信ファイルのSHAは更新する。V1の初回リンクとV2の更新形式の両方を検証する。原本保存用の鍵は使用しない。

配信対象はそのビルドの保存済みスナップショットであり、ライブ予想や継続自動更新とは表示しない。

## 結果と日予算の試算

「レース結果・収支」で取得済みの結果、保存Top8との一致、結果待ちを表示する。モデル・版・時点・履歴条件ごとに照合し、研究用の参考照合を正式な評価成績へ加算しない。結果だけ取得済みのレースも一覧に残す。

「保存Top8的中率」は的中数÷（的中数＋不的中数）を％表示し、結果待ち・中止・照合不可・未予想を分母へ入れない。「購入予定分の的中率」は日予算で配分したレースだけを同じ方法で集計する。分母0は「算出対象なし」。回収率は収支を確定できた購入額に対する払戻・返還の割合で、未確定額を別に示す。モデル比較表にも購入予定分の的中率・確定分回収率を表示する。

1日予算は初期値10,000円、100円単位で変更できる。締切順・同時刻はレースID順に、締切前の保存時刻が記録された完全なTop8へ各100円、1レース800円を配分する。残額不足は見送り、払戻・返還を再投資せず、翌日は予算をリセットする。検索や結果の有無で購入順を選び直さない。実購入台帳とは独立した試算である。

確定分の収支と未確定購入額を分ける。的中していても払戻額が不明なレースは、その800円プラン全体を保留する。返還対象・同着時の個別払戻を確認できない場合も金額を推測しない。結果がないレースを不的中やゼロ円として集計しない。

## 配信

公開用manifestのSHAをビルド結果から固定し、初回だけ `--initialize` を使う。

```sh
python -m scripts.boat_saved_pages publish \
  --repo /path/to/RACE-AI \
  --public-dir /private/pages/public \
  --private-dir /private/pages/owner \
  --manifest-sha <ビルド結果のmanifest_sha256> \
  --initialize
```

2回目以降は `--initialize` を外し、独立して確認した `--expected-parent <gh-pagesのcommit>` を指定する。宛先は同じリポジトリの `gh-pages` 固定。既存の無関係なファイル、symlink、変更されたasset、平文ファイル、予期しない親commitを拒否する。検証したバイト列をそのままGitへ入れ、ネットワーク照会中のファイル変更で未検証データを混ぜない。

GitHub Pagesの設定はbranch方式の `gh-pages`・`/`。Actionsのcontents/pages/id-token権限を追加しない。Pages設定APIが拒否されたら、別の権限やプロバイダーで迂回しない。

公開成功は、PagesのHTTPS応答、配信されたasset・暗号文・manifestの一致、本人用リンクでの実予想表示まで確認する。コードCIやブランチへのpushだけで成功とは報告しない。
