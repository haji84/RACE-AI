# 松山7R：保護mainへの限定適用・実RSA復号と結果取得の前段ゲート（2026-11-17）

## 目的と位置づけ
オーナーの要求は「2026-11-17 松山7Rを、結果取得→予想照合→暗号保存→別runner読戻し→HTML表示の5工程すべて、実際のGitHub Actions Run IDで証明。これが合格するまで全71Rへ拡大しない」。

既存の [PR #291](https://github.com/haji84/RACE-AI/pull/291) には研究・動画・6局面・入力復旧の変更87ファイルが混在する。**無関係な研究変更を保護mainに一括統合しないため**、本リポジトリの**同じ既存ワークフロー**へ、読取専用の単一レース事前確認だけを追加したmain宛の別Draft PRを作成した。新しいワークフローファイル、新しいSecrets、新しいrepo/実行基盤、外部課金、自動購入を追加しない。

## 分離した読取専用実装
- `.github/workflows/keirin-pr71-owner-autonomous.yml` の `workflow_dispatch` に `manual71_pilot` (boolean, default `false`) を追加。明示的に `true` で **main** に対して実行した時だけ `manual71-owner-one-race-preflight` が動く。通常のschedule、PR、単なるdispatchでは起動しない。
- 同一dispatchで既存 `public-preflight`、`config_readiness`、`github-hosted-pr71-cycle` へ処理を伝播させない。結果取得と予想本番ワーカーの二重起動や権限変更を避ける。既存5分scheduleの動作は不変。
- `race_ai/keirin_manual71_owner_encrypted_intake.py`：既存PR102の不変SHAヘルパーを使用し、暗号ペイロード/4つの元ファイルのSHAを照合。原本データを後付け改変・捏造しない。
- `scripts/keirin_manual71_owner_intake_cli.py`：既存 `RACE_AI_KEIRIN_PRIVATE_RSA_PEM` Secretを本番の単一stepからだけ渡し、公開鍵Fingerprint・暗号文バイトSHA・AES GCMタグ・原本SHAを検査。`RUNNER_TEMP` のprivate 0700/0600へ出して終了時破棄。鍵未設定/別鍵/誤SHAはHOLD。
- `scripts/keirin_manual71_matsuyama7_preflight.py`：原本V3が71件存在し、松山7R（`75-07`）の車番と優先順位が妥当なことを確認。その後、**既存** `race_ai.keirin_mobile_one_shot.probe_one` を **1回だけ**呼び、2026-11-17 松山7Rの第三者提供元研究候補を確認（HTTP拒否や不一致時に別経路の再試行なし）。候補が一致すれば私有原本と内側で比較する。外部HTMLは生保存・公開しない。
- 候補の正しさと正式認証は別。既存probeは `result_officially_authenticated=False`、`machine_collection_rights_verified=False` を返す設計であり、**今回の結果取得はあくまで個人研究用の1回試行**。主催者の真正な公式結果の取得・許諾・有効締切を証明しない。返還・同着・失格・確定後訂正などはこの単発probeでは正式処理しない。
- 出力は私有予想の正解/不正解・車番・払戻額・秘密鍵を印字せず、`private_decryption`、`source_check`、実際に取得できた時の `third_party_source_sha256` だけ。実主催者結果・AES本番保存・独立reader・ブラウザ表示は常に未合格フラグ。
- `tests/test_keirin_manual71_owner_encrypted_intake.py`、`tests/test_keirin_manual71_owner_intake_cli.py`、`tests/test_keirin_manual71_matsuyama7_preflight.py`、`tests/test_keirin_manual71_workflow_isolation.py` に架空RSA・架空結果・既存公開鍵の暗号文だけを使ったsource-freeテストを用意。PR CIは所有者秘密鍵を用いない。

## 予想原本の正本
- 原本V3 SHA-256: `4cd7e88d9ab7880702180bcbab248ebda2a8078a721fab5a08fe47323de21d68`。
- 4点bundleの暗号化ファイル: [sealed owner 71R](./evidence/2026-11-17/keirin_owner_manual71_20261117_sealed_v1.json)
- GitHub保存暗号ファイル185,773 bytes SHA-256: `164bd98caf06deb2308626d0f6343c074db9e85b9517378ac60119af21b3375e`。
- 中身のAES ciphertext SHA-256: `d04e070ef10e92a0276f3a3d1633ebf0fc4d075bf3c9d206c5f1fc9a76315a4f`。平文とRSA秘密鍵はGitHubへコミットしない。

## 合格ゲートと結果
1. **現在のDraft PR / synthetic-ci**：1レース用の取得コードの接続と、1回しかGETしない振る舞いを合成テストで証明する。**実結果GETも実RSA Secretも使っていない**。
2. **保護mainへの限定適用**：必須CIとオーナー承認を確認後に**この限定PRだけ**をmainに適用する。PR291大量研究は別のDraftとして残す。ユーザーの明確な許可なしにmainへマージしない。
3. **本人が既存Actionsで一回の手動dispatch**：`KEIRIN PR71 GitHub-only forecast and PDCA` → `Run workflow` → branch `main` → `manual71_pilot=true`。他のproduction jobはskip。
4. **実行証拠の判定**：Run ID、読取専用job ID、元暗号SHA、原本照合状態、第三者取得元SHA、GET実行回数を記録。源泉側が403/429・表示欠落/結果の確定不明ならHOLD。
5. **次の本番5工程**：真正な公式結果・利用許可・公式締切時刻の確認、旧保存原本との照合、本人に承認されたAES Git保存正本、別runner復号SHA、本人向け実HTMLを再接続。同一レース/同一改訂/SHAの証拠が5工程すべて揃うまで **0/5、HOLD**。公開サードパーティの参考的中7-2-1は正式な自動結果の代用品にしない。

### 安全・運用上の注意
本PRは**準備とread-only予備動作**であり、公式認証結果の自動照合システムでも本番HTML自動公開でもない。所有者のオリジナルRSA秘密鍵がGitHub Secretにあるかどうかは未確認。default OFFは維持。mainにマージしない限りSecret付き実ジョブは動かない。取得先の提供元拒否を回避しない。サイトは非公開原本を露出させず、保護mainに未承認データを混ぜない。
