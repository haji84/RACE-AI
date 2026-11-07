# オートレース個人予想A/B：観測値だけで動く参照モデルと使い方

2026-11-03 / 既存Draft PR #71 / 公式AIの予想出力には依存しない。

## 目的と位置づけ

- 本人が通常の閲覧で確認した近走着順、ハンデ、試走タイムだけでA（試走前）、B（試走後）の3連単を作る**小さな研究用基準モデル**を追加。既存の多特徴量・多モデル研究資産を破壊・差し替えない。
- 公式AIの予想、オッズ、人気、払戻、確定着順は予想入力にしない。結果は予想作成が完了した後の**別入力**。
- 出場車3～8台、各車の実測された直近3～10走の着順（1～8）、実際のハンデ（10m刻み）、Bは全車の実際の試走タイム（3.00～4.50）を要求。欠測を架空の数字で補わない。
- モデル係数（近走1.20、ハンデ1mにつき-0.01、試走相対差0.90）は未学習の**仮定**。全有効3連単の相対重みを正規化し、上位8点＋研究用追加4点を選ぶ。相対重みを**校正済み的中確率**と呼ばない。
- 出典URL、本人の取得時刻、作成時刻、予想SHAを保持。A/Bごとに別ファイルで新規作成のみ。予想Aに試走値を混入させない。2分未満の締切余裕で予想作成しない。
- 個人が読んだ実結果を取り込んで1点/8点/12点を照合できるが、これは**本人記録の参考集計**であり、第三者サーバーの締切前証明や独立確認済み正式Hit@8ではない。
- **完全自動運用は未完成**：正規の試走公開イベント、実データ取得、クラウド永続保存、実公式結果検証、スマホ向けフォームは別工程。元サイトの継続自動取得や公開サービスは勝手に起動しない。

## 操作できる最小経路（Mac / Linuxなど所有者限定ファイル権限が使える環境）

以下は実運用のデータ例ではなく、**架空の2030年フィクスチャ**を動かす再現手順。

```bash
mkdir -p -m 700 "$HOME/.race-ai-personal"
python - <<'PY'
import json, os
from pathlib import Path
from tests.test_autorace_personal_baseline import sample
from race_ai.autorace_ab_pdca import PHASES
root=Path.home()/'.race-ai-personal'
for name, stage in [('A-observed.json',PHASES[0]),('B-observed.json',PHASES[1])]:
    path=root/name
    with path.open('x') as f:
        json.dump(sample(stage),f,ensure_ascii=False,indent=2)
    path.chmod(0o600)
PY
```

架空データの受付時刻は2030年なので、今このまま本番コマンドを実行しても時刻検証で拒否される（未来の観測・締切と認めない）。**それが正常**。実レースに置き換える際は公式発表値を本人が手入力し、日時は観測時刻と実締切をそのまま入力する。時刻や数値を都合よく補完しない。

実際に入力が揃ったときのコマンド：

```bash
python -m race_ai.autorace_personal_cli predict \
  --input "$HOME/.race-ai-personal/A-observed.json" \
  --output "$HOME/.race-ai-personal/A-frozen.json"

python -m race_ai.autorace_personal_cli predict \
  --input "$HOME/.race-ai-personal/B-observed.json" \
  --output "$HOME/.race-ai-personal/B-frozen.json"
```

確定結果を別の `result.json` に保存し、結果を観測してから：

```bash
python -m race_ai.autorace_personal_cli compare \
  --input "$HOME/.race-ai-personal/A-frozen.json" \
  --result "$HOME/.race-ai-personal/result.json" \
  --output "$HOME/.race-ai-personal/A-preview.json"
```

Bの結果照合も `--input` と `--output` をBのファイルに変えて実行する。保存済みのファイルが存在する場合は上書きせず失敗する。再実行で予想を事後改変しないための仕様。

### 本人が入力するJSONの仕様

`A-observed.json` / `B-observed.json` は以下の契約：

- 最上位：`schema="RACE_AI_AUTORACE_PERSONAL_OBSERVED_V1"`、`entry_kind="USER_OBSERVED_MANUAL"`、`race`、`drivers`
- `race`：`race_id`、`venue`、`race_no`、`event_date_jst`、`sales_cutoff_at`、`as_of_at`、`phase`、`source_url`、`source_captured_at`
- `drivers` は全車分：`car_no`、`handicap_m`、`recent_finishes`、`trial_seconds`、`trial_observed_at`
- A：`phase="A_PRE_TRIAL"`、全車の試走関連値は `null`。
- B：`phase="B_POST_TRIAL"`、各車の試走を記録した値と観測時刻が必須。
- `sales_cutoff_at` や `as_of_at` の時刻は `2026-11-03T10:20:00+09:00` のようにJSTオフセットまで記す。実際の日時は出典を確認して記入すること。

`result.json` の契約（結果入力は締切後のみ）：

```json
{
  "race_id": "autorace:2030-01-15:fictional-track:1",
  "winning_order": [1, 2, 3],
  "source_url": "https://example.test/fictional-result",
  "captured_at": "2030-01-15T10:10:00+09:00"
}
```

これは全て架空値であり公式の確定情報・実的中数ではない。実際の出典・レース・番号・日時に置き換えてから、正確な対照データと検証する。

## 試験

```bash
python -m unittest tests.test_autorace_personal_baseline tests.test_autorace_personal_cli -v
```

POSIX端末では非公開ファイルの新規保存と読戻し、AとBの分離、重複上書き拒否、試走欠測拒否、公式AI・オッズ・結果の入力拒否を合成テスト。Windowsの所有者限定ACLは現時点で検証していないため、ローカル私的ファイルへの本番書込みを拒否。

次の完成条件は、本人が取得した**未来の実レース**1件の前後データを、変造せずA→Bの順に保存し、公式結果を人が確認した後に別入力で突き合わせること。独立した外部時刻証明がなければ、正式な締切前実測Hit@8としては計上しない。
