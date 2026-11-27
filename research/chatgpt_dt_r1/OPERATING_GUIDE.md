# DT-R1 完了版の使い方と受入条件

RACE-AI内の独立した研究参加モデル。相手の重み・出力を学習へ流用しない。正式採用、未来成績、身体エネルギーの実測をコード完成と混同しない。

## 今回完了した接続

| 工程 | 実装 |
| --- | --- |
| 学習 | 過去日履歴、上がり91列、5機能147列、最大12項目の学習期間内探索。7月に候補選択、8月校正、9月監査、10〜11月再検証。 |
| 出典・選手結合 | 新規特徴量v3で選手ID・登録番号・脚質・時計を拘束。旧v2原本は独立再構成と再認証後だけ互換検証。 |
| 上がり・映像 | 最終1周19列は欠損固定・係数0。上がりは半周。計測の区間数・不確実性を保存し再検証。target raceと同じJST日の履歴を除外。 |
| 買い目・信頼度 | 保存済みの固定点数校正を利用可能。オッズ方式の上限2/4/9/12点、1点終了、90/80/60%基準、証拠不足HOLDを維持。 |
| 比較 | 3参加者の外部固定pin、共通の履歴・出典・context・時刻を照合。欠測は分母に残し、予測後の資料を拒否。 |
| 保存・復元 | モデル、7校正artifact、契約、選択記録、原本を既存owner codecで暗号化。外部manifest SHAと全内容を確認して新しい私有ディレクトリへ復元。 |
| 表示 | 公開は検査済みパラメータ・集計・暗号文。デスクトップ/モバイルの実ブラウザで区分・信頼度切替と表示を検査するCI。 |

## 1. 研究全体を保存する

完了したstudyを指定する。元の研究ファイルを変更せず、既存の出力先は拒否する。

```bash
python -m research.chatgpt_dt_r1.bundle export \
  --study-dir "$DT_R1_STUDY_DIR" \
  --output-dir "$DT_R1_BUNDLE_DIR" \
  --owner-public-key docs/evidence/2026-11-18/keirin_owner_existing_rsa_public_spki3072.pem
```

出力は `frozen_model.json`、`public_report.json`、`dashboard.html`、`manifest.json` と暗号化shard。個別原本・校正race ID・完全監査は暗号文の中に保持する。未知ファイルが公開ディレクトリへ追加された場合も検証を失敗させる。

返されたmanifest SHAを信頼済みコミットと別の記録へ固定する。後から受け取ったmanifest自身をハッシュしただけでは期待値の認証にならない。

```bash
python -m research.chatgpt_dt_r1.bundle verify \
  --bundle-dir "$DT_R1_BUNDLE_DIR" \
  --manifest-sha256 "$DT_R1_EXPECTED_MANIFEST_SHA"
```

これは暗号文・公開物の完全性確認。所有者鍵での復号や元資料の真正性を証明したとは表示しない。

## 2. 既存鍵で復元する

所有者の既存秘密鍵を既存の保護された経路から供給する。鍵や復元先をGit配下へ置かない。欠落、期待SHA相違、別モデル混在、既存の復元先は停止条件。

```bash
python -m research.chatgpt_dt_r1.bundle restore \
  --bundle-dir "$DT_R1_BUNDLE_DIR" \
  --manifest-sha256 "$DT_R1_EXPECTED_MANIFEST_SHA" \
  --owner-private-key "$DT_R1_EXISTING_OWNER_PRIVATE_KEY_FILE" \
  --output-dir "$DT_R1_NEW_PRIVATE_RESTORE_DIR"
```

通常ファイルだけを復元する。パス外展開・symlink・PAX/GNU拡張を拒否し、展開量を制限する。全バイトとモデル/校正/契約の結び付きを検証してから出力する。元の保存状態をリセットしない。

## 3. 同じ点数条件の校正を使う

forecastで保存した1レースの原本に、対応する点数のcalibratorを渡す。

```bash
python -m research.chatgpt_dt_r1.cli select \
  --forecast "$DT_R1_PRIVATE_FORECAST_FILE" \
  --fixed-k 4 --market trifecta \
  --calibrator "$DT_R1_NEW_PRIVATE_RESTORE_DIR/trifecta_4.calibration.json" \
  --output "$DT_R1_PRIVATE_SELECTION_FILE"
```

二車単は `--market exacta --fixed-k 1` または `2` と対応する校正を使う。別モデル・別点数・別policyへ校正を使い回さない。過去校正の未来移転は `COHORT_TRANSFER_UNVALIDATED` のHOLD。固定点数では `--odds`、`--policy-config`、新しい `--at` を指定せず、原本の時計を保持する。

## 4. 3者を同じ資料で比較する

pin形式は既存ledgerと同じ `{model_id: {model_sha256, policy_sha256, feature_schema_sha256?}}`。実際の3モデルから値を受領し、ファイルのbytes SHAを外部固定する。統合モデルの内訳を名前から推定せず、相手のSHAを架空値で埋めない。

```bash
python -m research.chatgpt_dt_r1.cli compare \
  --forecasts "$DT_R1_INTEGRATED_ORIGINALS_FILE" \
  --forecasts "$DT_R1_CODEX_ORIGINALS_FILE" \
  --forecasts "$DT_R1_CHATGPT_ORIGINALS_FILE" \
  --outcomes "$DT_R1_ADMITTED_OUTCOMES_FILE" \
  --registry "$DT_R1_COMPLETE_REGISTRY_FILE" \
  --model-id existing-integrated --model-id codex-new --model-id chatgpt-dt-r1 \
  --pins "$DT_R1_PARTICIPANT_PINS_FILE" \
  --pins-sha256 "$DT_R1_EXPECTED_PINS_BYTES_SHA" \
  --require-shared-evidence \
  --output "$DT_R1_NEW_PRIVATE_COMPARISON_FILE"
```

`shared_evidence_sha256` は既存registryのrace/day/cohort/cutoff、input、history/dataset/context snapshot、context時刻を束ねる。モデルごとの特徴量schemaは違ってよい。元資料の認証と実際の入力照合は既存source/readback verifierが担当し、自己申告SHAだけでは真正性を認定しない。

欠落・資料相違・予測より後のcontextは全対象ではHOLDとして残し、共通対象から除外する。旧形式集計は `NOT_REQUESTED` と表示し、厳格比較済みとは呼ばない。

## GitHubと画面検査

研究CIの1回限りの学習は既存の固定branch・commit message条件で動く。公開集計とowner暗号化bundleだけをartifactへ渡す。7日保存artifactは受渡し用で、恒久保存は検証済みbundleと外部manifest pinをGitに残す。生DB・元ページ・平文原本・鍵をuploadしない。

画面検査は既存runnerのChromeを使用。幅1440pxと390px、収録済みの全車立て/級班/会場、7点数条件、候補表、JavaScriptエラー、外部通信、ページの横はみ出しを確認し、集計画面だけを撮影する。

## 別に必要な実証

- 認証済み実映像・6局面ラベルによる学習。今回のアーカイブ試験で追加映像計測は0件。
- 共通締切前入力を使う3者の凍結原本、独立読戻し、公式結果による未来対戦。
- 同時点オッズ・検証済み払戻を含む可変点数の実測収益。
- 実owner秘密鍵による保護された復号読戻し、既存全国実行経路での継続受入。
- 保護レビューと所有者の正式採用判断。本番のモデルpinを自動更新しない。

未取得の観測や未来の結果を推測で埋めない。合成試験の成功を実映像の性能や未来の的中率に数えない。
