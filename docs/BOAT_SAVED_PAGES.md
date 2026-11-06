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

標準出力には公開用manifestとハッシュだけを出す。`owner/viewer.json` と `owner/owner-url.txt` は0600のまま保持する。ビルドごとに別の秘密リンクを発行する。配信対象はそのビルドの保存済みスナップショットであり、ライブ予想や継続自動更新とは表示しない。更新時は新しい閲覧リンクを使う。

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
