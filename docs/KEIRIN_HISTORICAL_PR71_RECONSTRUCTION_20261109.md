# 競輪 PR71: 過去出走データからの特徴量復元監査（2026-11-09）

## 方針
新しい予想モデルを作らない。既存PR71の4モデルと `race_ai/keirin_allowed_delivery.py` の既存マッピングを正本とし、元ソースにある値だけを変換する。結果・払戻・事後オッズを入力に渡さず、存在しない数値を中立値・ゼロ・予想値で埋めない。元のモデル係数も変更しない。

## 実際に読み取った資料
- 松山 2026-11-08 2R: owner-private `matsuyama_2R_20261108_research_forecast.json`（ファイルSHA256 `8e3628b6d970cc128b140fc55957986a1126959f86e403ccd33520f081725ce7`）。7選手。競走得点、出走数、1着数、3連対数、B、逃/捲/差の件数がある。既存PR71の必要入力候補として `ability` と `consistency` が算出できるため **14/84必須枠**、その他 **70枠欠測**。任意枠49候補。環境 **0/9**。研究ファイル内の全210順は別の手計算モデルのもので、PR71の過去予想として移せない。
- 松山 2026-11-08 7R: owner-private `keirin_20261108_matsuyama7r_real_rider_sparse_research.json`（ファイルSHA256 `bd8cc4c7b3b05f3d2d0c54380b9df353b0448315a102991178fed5172792f85e`）。7選手。競走得点、出走数、B、逃/捲の件数がある。必須候補 `ability` だけで **7/84枠**、その他 **77枠欠測**。任意枠35候補。環境 **0/9**。

どちらも記録上は当日の締切前に研究出力が作られている。しかし **個々のソース値が締切前に公開・取得されていたこと、モデル推論/私有保管の取得権限、外部の独立締切前時刻証明は未確認**。正規化可能な候補と正式に許可されたモデル入力を混同しない。

## 復元した変換
- `ability`, `recent_points`: 競走得点 `x/(100+x)`（既存 score_open_v2）。能力の正しい勝率を意味しない。
- `consistency`（2Rのみ）: 当時の保存資料にある3連対数 / 出走数。
- `recent_win_form`（2Rのみ）: 1着数 / 出走数。
- `back_count_form`, `hsb_form`: B件数 / 出走数。
- `escape_style`, `makuri_style`, `sashi_style`（最後は2Rのみ）: 対応する決まり手回数 / 出走数。

**対象外で値を作っていない必須特徴量**: `recent_form`, `start_reliability`, `finishing_power`, `course_compatibility`, `stamina`, `tactical_adaptability`, `line_coordination`, `sprint_acceleration`, `attack_success`, `bank_fit`。7Rにはさらに `consistency` が欠ける。ラインの並び予想を連携成功率、B件数を瞬発力、直線長を個人のバンク適性に置き換えていない。

必須環境の未取得項目は `wind_mps`, `rain_mm_h`, `humidity_pct`, `air_temp_c`, `surface_wetness`, `bank_steepness`, `wind_exposure`, `track_roughness`, `line_complexity`。過去に実際に観測された天気を、当時予測可能だった値と同一視しない。過去の走路寸法など固定条件は利用可能でも、PR71向けの正規化変換の実証がなければ投入しない。

## 照合に利用した公開参考ページ
- 2R: https://www.chariloto.com/keirin/athletes/2026-11-08/75/2
- 7R: https://keirin.tokyo-sports.co.jp/list/race/20261107_33248

これらは現時点のページ表示と過去私有資料の整合を調べる参照であって、過去の公開時刻と機械利用権限を認定した証拠ではない。

## 追加した安全な処理と実行方法
- `race_ai/keirin_historical_sparse_feature_probe.py`: 2種類の保存済み研究ソースを検証し、測定値からPR71既存変換を使って必要入力候補だけを計算。原本の欠落、数値異常、重複、予想ラインの不整合を拒否。結果を読むこともPR71推論を実行することもない。
- `race_ai/keirin_historical_archive_inventory.py`: 以前の履歴分類に実測復元候補件数を接続。計算可能な値があっても正式採用数は0のまま。
- `scripts/keirin_historical_sparse_probe.py`: 本人の非公開絶対パスから1ファイルを読み、競走者名・元数値・位置情報を表示せず、型・不足項目・SHA・集計件数だけを出力。

```bash
python -m scripts.keirin_historical_sparse_probe --owner-archive "/private/race-ai/matsuyama_2R_20261108_research_forecast.json"
python -m scripts.keirin_historical_sparse_probe --owner-archive "/private/race-ai/keirin_20261108_matsuyama7r_real_rider_sparse_research.json"
```

## 続けるための実証ゲート
1. 当時の元出走表/成績の**公開時刻・取得時刻**が項目ごとに示された保管原本を取得する。現在のページ表示を無条件に過去原本と扱わない。
2. 欠ける必須モデル特徴量を、出典と事前に固定した変換規則で作れるか検証する。作れない場合はPR71の実計算を停止し、欠測レポートへ。
3. 同一レースのPR71必須7車×12特徴＋走路環境9項目＋347項目の状態チェック、予想/推論利用条件を検査して初めて `prepare_historical_pr71` に渡す。**過去の計算実行日時は実際の現在時刻として記録**し、事前予想原本にしない。
4. 事前に使用モデル版を固定し、学習用期間と未使用評価用期間を時間順で分ける。後から的中結果を見て候補や係数を追加しない。結果入手後に初めて `evaluate_historical_without_repredicting` に渡す。
5. 全候補順位・Top8/Top12・万車券捕捉率・仮想回収率をモデル別に算出。正式な前向き的中率/実購入損益は元予想と時刻の外部証明がなければ未評価。

現時点の実データでは **PR71 4モデルを正式再計算可能な過去レースは0**。合成CIが通っても、合法・真正・as-ofの実資料は自動生成されない。GitHubは研究コードと安全なSHA/件数のみ。私有選手データと予想原本は公開しない。
