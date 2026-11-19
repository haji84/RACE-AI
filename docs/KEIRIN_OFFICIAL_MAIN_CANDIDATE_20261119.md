# KEIRIN公式A/Bパイプライン: main向け導入候補

この文書は初回候補 `f77b6035` の準備時点の記録です。その後の排他・保存競合修正、PR #310の統合、17レースの実照合、readiness追加は [続きの検証記録](KEIRIN_OFFICIAL_PRODUCTION_CLOSURE_20261119.md) を参照してください。以下の「既存mainファイル変更なし」「既存workflow変更なし」は初回候補の範囲を述べています。

この候補は、全国A/Bの取得・暗号保存・公式結果照合・所有者向け閲覧を、既存RACE-AIのmainへ独立して導入するための変更である。実装とオフライン回帰は準備済みで、本番運転の受入れ完了を示すものではない。

## 固定した出所と変更範囲

- main基点: `4f6efd5207316a5f1ba3ab0255728224f00dcc53`。通常fetch後に固定した。
- 導入元: 公開済み研究コミット `f06b15aee0c6d615deed9dceda8cbdfe41042c98`。
- 導入元tree: `c4f119e1ecdb4f5c8582b959b1041bbc2be6f79a`。
- 上記コミットから74ファイルを内容変更なしで追加し、本書を加える。既存mainファイルの変更・削除はない。
- 内訳はPython 67、ワークフロー1、既存公開鍵・安全な検証資料4、今回の完了監査・安全な実結果receipt 2、本書1の計75ファイル。

依存閉包は、ワークフローの30テストモジュール、明示・ワイルドカードのコンパイル対象、関数内の遅延importまで追跡した。`race_ai/__init__.py` はmainと同一内容なので置き換えない。`tests/__init__.py` など既存のpackage設定も変更しない。

単に今回の新しい公式系モジュールだけを移すと、先に研究ブランチで追加されたA/B生成器・スコアラー・暗号保存・2ソース正規化・日次登録が欠ける。本候補はこれらの必要な依存を含む。研究PR全体に含まれる他競技、映像研究、既存ページ等の変更は持ち込まない。

## 実装されている動作

- 公式日程の原文bytesと出典を検証し、日程改訂をまたいだ登録レースの和集合を維持する。最新日程から消えたレースは採点せずHOLDとする。
- 当日の締切前だけにA/Bを生成し、所有者の既存公開鍵で暗号化して保存する。以前の原本は再予測・上書きしない。
- 取得対象は最も近い締切から10分以内の群で選択回数の少ない順にする。選択IDをGitへ保存し、失敗し続ける先頭群が後続を固定的に塞ぐのを防ぐ。選択記録はGET実行証明ではない。
- 別runnerが正確な暗号文SHAを読み戻す。公式結果照合ではGitHubのrun/job/artifact証拠も検証し、自己申告の保存時刻を独立証拠として扱わない。
- 現在日・前日・既存の過去日最大1日を再確認し、日別カーソルで結果・原本証拠の取得対象を巡回する。過去日の予測生成はしない。
- 提供元拒否を検出したら同じbatch内・観測日で再試行を止める。停止記録の保存失敗も停止条件とする。
- 公式資料・結果改訂・所有者向け表示を暗号化して履歴に残す。同一内容の単なる再読込では暗号revisionを増やさない。
- A/Bは同じ採点分母を使用する。未取得・未確認を外れにせず、中止・全返還は中立として区別する。Bの順位を校正済み確率とは表示しない。

## ワークフローと実行環境

ワークフローのパスは `.github/workflows/keirin-nationwide-ab-auto.yml` のまま維持する。正式経路のジョブ名は次のとおり。

1. `source-free-tests`
2. `github-only-owner-capture`
3. `github-only-independent-archive-readback`
4. `github-only-research-results`

GitHub原本証明はワークフローのパス、ジョブ名、artifact名、report名も照合する。これらを改名する場合は別途証明ポリシーと回帰テストを合わせてレビューする必要がある。

過去の日付固定の提供元取得ジョブと旧S3ジョブは、導入元と同じ `false` のまま保持する。それらの独立読み戻しジョブも、無効な取得ジョブの成功を条件にしている。現CIが参照する過去の診断コードは依存として含むが、本候補で実アクセスを再開しない。

ActionsはPython 3.11を使用する。明示する第三者依存は `cryptography>=44,<48` と `beautifulsoup4>=4.12,<5`。暗号文だけを読む独立読み戻しジョブは、導入元どおりcryptographyを導入する。新しいホストや有料サービスは不要である。

## 本番実行に必要な既存設定

以下はコードが要求する条件を記したもので、今回設定を変更・有効化したという意味ではない。

| 項目 | 必要な条件 | 用途 |
| --- | --- | --- |
| リポジトリ・ref | `haji84/RACE-AI`、repository ID `1416489937`、`refs/heads/main` | 保存処理と原本証明の実行元制限 |
| `RACE_AI_KEIRIN_AB_AUTOGEN_ENABLED` | repository variableが `true` | 自動生成の既存opt-in |
| `RACE_AI_AB_PUBLIC_CAPTURE_ENABLED` | repository variableが `true` | 公開ソース取得の既存opt-in |
| `RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED` | repository variableが `true` | 同じGitHubリポジトリへの暗号保存opt-in |
| `RACE_AI_AB_SOURCE_S3_PREFIX` | 空 | 旧外部ストレージ経路との分離 |
| `RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED` | 承認された公式取得経路を確認した上で `true` | 新しい公式定期取得の明示的な有効化 |
| `RACE_AI_KEIRIN_PRIVATE_RSA_PEM` | 所有者が別途設定済みの既存RSA秘密鍵Secret | 原本・保存済み証拠の復号。結果照合ジョブだけが参照 |
| `GITHUB_TOKEN` | 結果照合ジョブ内の既存自動発行token | GitHub原本証拠の読込 |

公開鍵は `docs/evidence/2026-11-18/keirin_owner_existing_rsa_public_spki3072.pem` を使用する。RSA3072、SPKI SHA256は `1963d13558d115ce261f224b97d385bd09c65a70c91fb23237f91aa9840bb3a1`。コードの既存所有者pinとの一致を確認した。新しい秘密鍵を生成せず、repository IDやtokenから鍵を作らない。既存のSQLite用 `RACE_AI_STATE_KEY` を置換・再設定する変更でもない。

ワークフロー内の権限宣言も導入元と同一である。既定は `contents: read`、保存を行うcapture・結果照合ジョブは `contents: write`、結果照合ジョブは加えて `actions: read` を要求する。既存ワークフローの権限、main保護、repository設定、可視性、Secret・variableは変更しない。

## 既存の状態ブランチと公開範囲

状態ブランチは既存の `state/keirin-encrypted-history` を使う。準備時にローカルで確認できた参照は `2c0f9edfe069ce8a190a348c4497c4ed906bd30a` で、既存の暗号化世代を保持していた。これは本番実行直前のremote head検証に代わるものではない。各実行が通常fetchで既存ブランチを検証し、見つからない場合は停止する。ブランチ新設、初期化、reset、force pushはしない。

既存PR71等のワークフロー設定は変更していない。同じ状態ブランチの別prefixへ書く既存writerと、新A/Bワークフローのconcurrency groupは異なる。将来両方を有効にした場合、通常pushの競合や、読み戻し時にheadの完全一致を要求する既存処理のHOLDが起こり得る。既存スケジュールとの同時稼働・競合後の再開を本番受入れ条件に含める。これは保存済みデータの破壊を確認したという意味ではなく、本候補の準備を妨げる不具合とも扱わない。

既存PR71の入力・鍵・設定条件と新A/Bのopt-inは独立しており、両者の実行条件に排他はない。条件次第で旧4モデル経路も別に動き得るため、保存競合に加えて、モデル系統と提供元取得の重複も本番前に確認する。現在のvariable・Secret値は本準備では取得しておらず、旧経路が実稼働しているとは確認していない。旧系統の停止・再設定は本候補では行っていない。

この確認には既存 `.github/workflows/keirin-daily-discovery.yml` も含める。既存 `race_ai/keirin_discovery.py` と新 `scripts/keirin_register_public_day.py` は、同じ日付のKdreams開催一覧を取得し得る。新しい公式source flagはリポジトリ全体の取得停止スイッチではなく、既存PR71のSourceSessionによる403/429停止もそのjob内の状態である。本番前に、既存discoveryを含めた取得の重複と、提供元拒否後の停止範囲を確認する。

| 保存領域 | 保存するもの |
| --- | --- |
| `state/keirin/ab/v1` | 作成済みA/B暗号原本とSHA receipt |
| `state/keirin/ab/official-results/v1` | 暗号化した公式証拠・結果改訂と最小receipt |
| `state/keirin/ab/provider-stop/v1` | 日付・固定停止コード・観測時刻 |
| `state/keirin/ab/capture-selections/v1` | 選択ID・選択時刻・workflow実行識別子 |
| `state/keirin/ab/poll-progress/v1` | 過去日を含む巡回の進捗metadata |

GitHub artifactに載せるのはallowlist対象の安全なreceiptと、RSA暗号化済み `owner-view.sealed.json` だけである。原文、平文racecard、平文買い目、秘密鍵、SQLite、平文 `owner-report.html` は公開しない。平文は権限を制限したrunnerの一時領域で扱い、終了時に削除する。artifactの21日保持を恒久バックアップと呼ばず、暗号化した継続状態は既存Gitブランチに残す。

所有者は暗号viewを既存秘密鍵でローカル復号できる。

```bash
python -m scripts.keirin_official_owner_view \
  --cipher /absolute/private/owner-view.sealed.json \
  --owner-private-pem /absolute/private/existing-owner.pem \
  --out /absolute/private-output/report.html
```

このCLIはネットワークを使わず、新しい権限制限済み出力のみを許可する。Git作業領域やsymlinkへの平文出力を拒否する。単独のDELTA証拠は完全なレース表示を再構成できないため受け付けず、結果照合ジョブが作る完全viewを使う。

## 検証結果と実運用で残る確認

- 変更前のクリーンなmain基点と移植後の両方で、既存persistent core/private spool関連9モジュール・72テストが成功。
- 移植後の現行source-free CI 30モジュール・315テストが成功（41.968秒）。実RSA/AES、ローカルbare Git、独立clone、競合、改訂再開、拒否停止、選択公平性を含む。提供元への追加GETは行っていない。
- 追加するPython 67ファイルのコンパイルが成功。導入元74ファイルのbytes一致を検証。
- main基点に対するGitHub combined-status APIとPR起点run一覧APIは記録を返さなかった。これは失敗という判定でも、GitHub上の必須チェック成功の証明でもない。候補PRで既存の必須チェックを通常どおり確認する。

公式取得の利用可能条件は未確定である。導入元監査に記録した公式robotsの観測では `/pc/json` はAllow対象に含まれていなかったため、本候補の準備で定期取得を有効化していない。robotsと法的な利用権限を同一視せず、設定flagだけで許諾済みとも扱わない。

本番のmain Actionsで既存秘密鍵が一致すること、提供元の承認された継続取得経路、未知の返還等の形式、実際の未来開催日に全国対象を一巡すること、保存・停止・再開の実receiptは別途確認する。10分cronは遅延し得るため、選択公平性の修正を全レース取得保証とはしない。確認できない結果は引き続きHOLDであり、外れにはしない。

関連資料:

- [実装と受入れ状況の監査](KEIRIN_OFFICIAL_AUTOMATION_COMPLETION_AUDIT_20261119.md)
- [実レース照合の安全なreceipt](evidence/2026-11-19/keirin_utsunomiya1r_official_AB_settlement_safe_v1.json)
- [固定した導入元コミット](https://github.com/haji84/RACE-AI/commit/f06b15aee0c6d615deed9dceda8cbdfe41042c98)
- [固定したmain基点](https://github.com/haji84/RACE-AI/commit/4f6efd5207316a5f1ba3ab0255728224f00dcc53)
