# 4競技 過去レース大量検証と8点/12点同条件比較（2026-11-04）

## この変更で実装済み

* `race_ai/verified_bulk_backtest.py`: owner-supplied JSONL の予想、結果改訂、返還をオフラインで照合する既存の集計器。
* `race_ai/historical_pairwise.py`: 同じ`race_id`、同じモデル/版、同じ12券の上位8券と全12券を、同じ確定結果で比較する追加検証器。的中率の分母をそろえ、100円/点の購入額、返還、払戻、仮収支・回収率を別々に計算する。
* `append-results`: 既存のJSONL結果履歴へ、新しい観測を追記した**別ファイル**を出力。同一`race_id`と`revision`の内容矛盾や既存出力の上書きを拒否する。
* `tests/test_historical_pairwise.py`: 12点目での追加的中、通常/全額/部分返還、8点だけの予想から12点を捏造しないこと、未結果、重複予想、結果版競合を試験。
* 既存のPR #71のコードテスト用CIで実行する。main/本番/投票/定期外部取得は変更しない。

## 使用方法（Python標準ライブラリ）

事前にownerが利用条件を確認し、ローカルに`forecasts.jsonl`、`results.jsonl`を用意する。

```bash
python -m unittest tests.test_verified_bulk_backtest tests.test_historical_pairwise -v

# 既存の結果履歴を上書きせずに、より新しい結果版を追記する
python -m race_ai.historical_pairwise append-results \
  --base results_previous.jsonl \
  --incoming results_new_observations.jsonl \
  --out results_new_snapshot.jsonl

# その時点ですでに存在する12券を、上位8券と同じ20R等で比較
python -m race_ai.historical_pairwise compare \
  --forecasts forecasts.jsonl \
  --results results_new_snapshot.jsonl \
  --model-id 'オート::朝版A v2' \
  --cohort morning \
  --out local_compare_001
```

`local_compare_001/comparison.json`と`same_race_8_vs_12.csv`に各レースと集計を出す。出力先の上書き禁止。予想が8点しか保存されていないレースは、12点比較から明示的に除外する。

## 実データでの検証境界

2026-11-03のlegacy owner-supplied朝版252レースは、3競輪結果を追加すると248レースが集計上は照合済み、4レース結果未確認、全額返還4レース。成績は的中97/有効244レース、39.75%、仮購入206,400円、払戻+返還152,510円、73.89%。元の日別朝版参照結果に依存し、**全レースを独立に公式監査できたという証拠ではない**。新たに第三者ページで確認したのは奈良4R(3-1-4、990円)、奈良5R(1-2-7、14,750円)、奈良6R(2-4-1、2,520円)。残りは奈良7R、静岡6R/7R、武雄7Rで確定3連単・払戻を未取得。

同日のオート朝版 `朝版A v2` は20レースに12券が存在するため、同じ20レースでprefix8とprefix12の参考比較が可能。全額返還1レースを的中率から外した19件で、8点2的中(10.53%)、12点3的中(15.79%)。20件の購入総額/受取額は8点16,000/2,570円(回収率16.06%)、12点24,000/5,730円(23.88%)。追加4券の費用が増えるため、**収支は-13,430円から-18,270円に悪化**。結果ソースや保存時刻の真正性は全件独立証明されておらず、この比較は研究用参考値である。

これは「荒れそうなレースだけを事前の判定で12点にする可変戦略」のバックテストではない。可変12点運用を採用する前に、根拠となる荒れ判定を事前保存し、全同一対象レースで8点固定・12点固定・可変8/12の3方式を独立した仮想予算で比較する必要がある。

## 完成していない工程

1. 4競技の結果・取消・返還・同着を継続取得する権利と安定した実際のデータ取得先を確認する。
2. 人手確認済みデータのowner-private保存、SHA監査、GitHub Actionsからの継続再取得・復元を実証する。
3. オッズ・払戻・結果など締切後の情報が予想特徴量に混入しない時系列 train/validation/test を実レース数千件で実行する。
4. 公式結果を独立確認し、前向き締切前保存証拠付き予想に対し同日・同条件で成績比較する。

公開GitHubにはユーザー個人の生の予想原本、権限未確認の大量コピー、非公開保存先のURLやトークンを追加しない。自動投票、main統合、Cloudflare、Vercel、追加課金は本変更に含めない。
