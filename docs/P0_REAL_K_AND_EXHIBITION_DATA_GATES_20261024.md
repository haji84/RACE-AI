# P0 実データ：既存PR64 K履歴→PR71近走計算／公式直前情報の受入監査

2026-10-24 JST。最上位[Issue #67](https://github.com/haji84/RACE-AI/issues/67)、既存Draft[PR #72](https://github.com/haji84/RACE-AI/pull/72)の実データ接続証拠。予想モデルの重み・旧予想・mainは変更しない。

## 結論（実データについて確認できた範囲）

- **過去K結果そのものを取得・解析できた**。公式日別K結果2026-10-23（1回の実GET）で14場、168レース、1,008出走者記録、ST数値1,002件、F6件。公式ファイルSHA `188ac9e6550eb37bd23a0413eddfcdd52e77fc7694a21b1a32542939afe50530`。[Actions #40056395755](https://github.com/haji84/RACE-AI/actions/runs/40056395755)
- **6日分K（10/18〜23）＋10/24 Bの単発7GET照合を実証**。[Actions #40057074332](https://github.com/haji84/RACE-AI/actions/runs/40057074332) completed/success。PR64の旧`parse_k`と、失敗したレースのみを厳格に隔離するラッパーを使用。K10/21は13場ブロック中1つがレース見出しなし、別の1レースが不完全と診断し、**正常な858行（143R）だけ認定**。欠けた1レースのST/着順を0や想像値で補っていない。[匿名診断 #40056999377](https://github.com/haji84/RACE-AI/actions/runs/40056999377)
- 6日間で構文解析できたK出走記録合計は **5,466行**（各日936 / 792 / 864 / 858 / 1,008 / 1,008）。出走者識別の重複を整理し、ビワコ2026-10-24・11Rの**6艇すべてに有効な過去5走が存在**。PR71既存の `boat_feature_adapter._historical_past` を**そのまま**適用して、6艇分の近走評価/スタート安定性 **12個の実数値候補**をメモリ内生成できた。
- 当日B側は2026-10-24公式ファイル SHA `1760b6e3fc024a517994fdd072d13c9676f5f42d009c1339681eb2d537bd11ae`、14場・168レース・1,008出走者をPR64既存パーサーで厳格に解析。6艇との登録番号照合に成功。**K由来の数値や元K/B本文はGitHubへ保存・再配布せず**、件数とarchive SHAのみ記録した。
- **実際の当日展示と気象も取得できた**：[三国2026-10-24 8R直前情報](https://www.boatrace.jp/owpc/pc/race/beforeinfo?hd=20261024&jcd=10&rno=8)。GitHub-hosted [Actions #40056884450](https://github.com/haji84/RACE-AI/actions/runs/40056884450) で現地締切予定12:11より前の **12:05:50 JST** に1GETし、PR64の`official_race_updates.parse_update`を**変更せず**使用。6艇展示タイムあり、スタート展示STは数値有効5艇／未数値1艇、風1m/s・波1cm・気温19℃。同サイトHTMLのSHA `dc9a09409d0e32fa01e14b91d0d6b1377abc5eae0ad4af797b1313c9280d7512`。元HTMLは公開リポジトリに保存していない。

## 技術的に足りないものを分けて扱う

1. **同一レースの全入力統合**：K+Bはビワコ11Rを選択し、展示と気象は別レースの三国8R。異なるレースのST・風波を混同して1レースの予測を実行してはいけない。現段階では4種のソースをそれぞれ**実際に読めた**ことまで。
2. **PR71既存FULLモデルの正確な入力**： `boat-comprehensive-v1` と `boat-scenario-mixture-v1` は6艇分の過去5走、展示タイム、展示ST、モーターと`wind_speed_mps / wave_height_cm / wind_relative_to_course / wet_surface_factor`を要求する。三国8Rでは展示STが数値5/6、さらに風の競走方向に対する角度・水面のwet factorについて入力変換の根拠がないので**全条件未成立**。欠測を0や平均にしない。
3. **公表時刻・利用条件**：公式K/BのHTTP Last-Modifiedは当時の初公開/訂正済最終値の証明ではない。展示HTMLも取得時刻はGitHub Actionsで確認できたが、それ以前の初公開時刻が正式認証されたわけではない。自動取得・分析・保存・学習・派生配布の用途別許諾も独立承認済とは言えない。PR64/71本番採用ゲートは維持、**model input admitted=0 / official prediction=0 / formal Hit@8未算出**。
4. **未来情報の遮断**：Kの全結果は当該日の事後確定成績。対象日2026-10-24より前のK日付のみを候補として使った。日付と実際の公表時刻・取得時刻の独立証明は別。結果を見た後の過去予想再生成や旧Top8書換えは禁止。

## 次に実証する最小E2E

- まず**一つの未来レース**で、実Bによる6艇登録/モーター、既存PR64のK履歴最低5走、展示タイムと展示ST6艇、レース時点の風波と必要な進入方向・水面条件を**同一race_id/as_ofで**照合する。
- 権限や出典が必要な箇所は`UNKNOWN/NOT_YET_PUBLISHED/RIGHTS_BLOCKED`のまま。PR71の元の重み・数式を変えずに実行し、必要な入力を満たせない場合は`NO_FORECAST`と完全な欠測リストを保存。
- 独立AIレビュー、公式確定締切、外部受領証拠付きTop8、結果・返還・払戻改訂照合を通して初めて正式な成績に計上する。研究用B-LITEは比較基準のみ。

コード：`scripts/p0_one_shot_real_k_readiness_20261024.py`、`scripts/p0_real_b_k_pr71_history_join_20261024.py`、`scripts/p0_one_shot_k21_shape_diagnostic.py`、`scripts/p0_real_mikuni_8r_preview_weather_20261024.py`。CIはすべてDraft PR #72配下、日別単発GET、常時巡回・課金・自動投票なし。
