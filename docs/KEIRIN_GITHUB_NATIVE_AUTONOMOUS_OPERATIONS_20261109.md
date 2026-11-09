# GitHub単独定期実行：全国競輪の動画録画、暗号化、研究学習、安全な予想比較

## 実際の自動起動
- GitHub Actionsの `schedule` は **デフォルトブランチ main に存在するworkflowだけが動く**。このファイルをmainへ統合して初めてGitHub自身が毎日起動する。
- `.github/workflows/keirin-github-autonomous.yml` のGitHub cron（UTC） `21 0-19 * * *` は日本時間 **毎日09:21〜翌04:21** の1時間ごと。ジョブはGitHub Actionsの負荷で遅延・一部ドロップがあり得る。
- 日本時間の **毎日04:50**（UTC `50 19 * * *`）に前日分を集め、持ち主用非公開研究処理を起動。`workflow_dispatch` の smoke/capture/nightly も用意。
- mainのworkflowのみ統合し、未完成のDraft PR102/PR71/PR103は**mainに統合しない**。実行するPythonコードはPR102にあるレビュー対象SHAで固定。別コードへの自動すり替えを禁止。

## 自律録画フロー
1. WINTICKETの通常公開当日出走一覧と結果一覧から、開催場数・レース数を実測。固定83Rを将来日に流用しない。通常結果ページに出た終了レースだけをブラウザで再生し、再生自然終了まで画面録画。全周回動画があれば優先、短いリプレイも候補。結果や後日映像を同じレースの締切前予測に逆流させない。
2. ブラウザ録画は作業専用の一時ディレクトリで扱い、RSA 3072公開鍵でラップしたAES-256-GCM鍵を使って暗号化。生映像・個人の秘密鍵をGitHub公開コードや公開成果物へ置かない。
3. 暗号化前の同一一時実映像から、2秒間隔の画面HSV・輪郭・画面変化などの196次元特徴量を取得。TRAIN用だけから無教師シーンモデルを学習し、HOLDOUTは検証専用に分離。結果は全部RSA/AES暗号化して保存。**この学習で自動認識できるのは画面表現だけで、捲り・差し・選手番号の正解ではない**。
4. GitHub Actionsの未期限切れの暗号artifactと対になるmetadataのSHAをGitHub APIで検査し、一時保存の範囲だけ重複録画を回避。暗号artifactが期限切れになったら永続保存したと偽らず再取得対象に戻す。
5. 日付変更直後は前日の実際の出走一覧を直近の証拠artifactから復元して、前日の残り未録画レースを回収する。未来日の発走は先に処理しない。

## 自動保存の重要な未接続条件
RACE-AIのGitHubリポジトリは **public**。Actions artifactの保存上限はpublicで90日、このworkflowでは14日。期限があるので、これは**永続保存ではない**。本物の永続化には所有者が用意する非公開のS3互換オブジェクト保存先が必要。

GitHub Repository Settings > Secrets and variables > Actions で設定できる（値を公開チャットに貼らないこと）：

| 名称 | 種類 | 必要な条件 |
|---|---|---|
| `RACE_AI_KEIRIN_PRIVATE_RSA_PEM` | Repository secret | 毎朝のGitHub自体による復号・学習を有効にする。公開鍵 `docs/keirin-historical-batch-20261109-public.pem` に対応する持ち主秘密鍵。未設定時は録画暗号化のみ、夜間の秘密研究はスキップ。 |
| `RACE_AI_KEIRIN_S3_BUCKET` | Repository secret | owner-privateで永続的なS3互換バケットの名前 |
| `RACE_AI_KEIRIN_S3_ACCESS_KEY_ID` | Repository secret | 当該バケットだけに書込み・読戻しできる最小権限キー |
| `RACE_AI_KEIRIN_S3_SECRET_ACCESS_KEY` | Repository secret | 秘密のアクセス鍵 |
| `RACE_AI_KEIRIN_AWS_REGION` | Repository variable | AWS使用時のリージョン（既定ap-northeast-1） |
| `RACE_AI_KEIRIN_S3_ENDPOINT` | Repository variable | S3互換サービス使用時のHTTPSエンドポイント。未設定なら通常AWS S3 |

秘密鍵・認証情報の実際のセットアップはこの実行環境にGitHub Secrets変更APIがないため自動完了できない。使用権限も別途ユーザー確認の範囲を超えて推測しない。**秘密鍵は既にChatGPTの非公開Libraryにあるが、GitHub Actionsはそれを自動で読むことができない**。

永続化が設定された場合のみ、毎回の暗号化ZIPをS3互換保存先にPUTし、その後HEADのバイト長・SHAメタデータ確認、再GETしてSHA一致が取れた時に `DURABLE_CIPHERTEXT_READBACK_VERIFIED` と記録。それまでは期限付きのGitHub成果物と明確に区別する。

## 毎朝のモデル学習
- 夜間ジョブは前日分の未期限切れRSA/AES source artifactsをGitHub APIから集め、元録画SHAを照合する。owner秘密鍵のGitHub secretがある場合のみ一時復号してフレーム抽出・匿名研究モデルを再学習し、出力を公開RSA鍵で再暗号化してからアップロード。生フレーム・特徴量・鍵はアップロードしない。
- 独立目視で選手番号・仕掛け・捲り・差し等を裏づけられる映像ラベルが無い限り、真の選手別戦術モデルの自動正解学習と呼ばない。未観測はUNKNOWNであり0にしない。
- 正式な予想改善を証明するには、同じ未来レースのPR71既存A予想原本と映像B予想が締切前の同時刻に独立SHA凍結され、実結果・払戻を後から別取得し、Top8・対数損失・Brier・期待回収率が未見で改善したことを検証する必要がある。
- **現段階では事前A/Bの完全な証拠を毎日自動で揃える機能は未完成**。自動で本番重みへ昇格させる安全な根拠がないため、正式予想原本とmainモデルを変更しない。

## 証拠とテスト
- 動的開催発見8場83R、実青森1〜3R暗号録画と非公開Library再読戻し、無教師研究モデルの実フレーム学習はPR102で既に確認。
- PR102 `scripts/keirin_autonomous_artifact_recovery.py`, `race_ai/keirin_private_sealed_payload.py`, `scripts/keirin_github_private_s3_archive.py`, `scripts/keirin_github_seal_owner_research.py` を追加し、合成データの鍵/整合性/欠落/期限切れの拒否テストを実施。
- 本mainスケジューラーが実際にデフォルトブランチのscheduleで少なくとも1回起動し、公開結果がある未来のレースを暗号保存できることと、任意の外部永続保存先にAES ciphertextが独立読戻しできることは別々の合格条件。scheduleに書いたこと自体を完成としない。

## 費用・障害
- 1日数十レースをブラウザ再生するジョブと暗号artifactはGitHub Actionsの実行時間・容量・保存料金の対象となり得る。利用プランと支払い上限を確認する。バケット認証が無ければ長期保存保証なし。
- GitHub公式：GitHub Actionsのscheduleはmainのみ、cronの遅延やドロップがあり、public repoは60日活動が無いと自動無効化される。手動の `workflow_dispatch` で回復確認できる。
- GitHub Actionsの臨時失敗・源のリンク不足・開催中止・著作権や利用条件の範囲外は失敗記録を残し、推測で映像や正解を生成しない。

**判定**：GitHub単独の日次**起動・録画・RSA暗号化・無教師画面学習**までの仕組みを実装。毎日全レースの永久保存、実選手の捲り/差しの自動教師認識、既存A対学習Bの予想精度向上実証、危険な自動モデル昇格は、確認可能な実証結果が出るまでは未完成として扱う。
