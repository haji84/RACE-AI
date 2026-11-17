# 競輪 A/B｜全国全レース・全日付への拡張（2026-11-18 JST）

## 最新の本人指示

**「全レースを対象にやろ！」** 対象は全国のすべての実開催レース。G1/G2/G3/F1/F2、モーニング・デイ・ナイター・ミッドナイト、ガールズ、6車立てや途中欠車/中止も初期対象に残す。

A=実際に事前生成した既存方式の予想、B=初周→打鐘→最終H→最終B→4角→ゴールの6局面予想、C=B＋実追走履歴（任意）。**未完成の共通4モデル/PR71は必要としない。C未完成でもA/Bは走らせる。**

## 2026-11-18の正確な全国開催母数

全国の公開開催一覧は8場。KEIRIN HEXの通常開催ページ https://keirinhex.jp/races/20261118/ は50Rのみで、静岡11R、宇都宮9R、高知9Rを含まない。したがって「HEX通常一覧50レース=全国」と誤認しない。

| 開催 | コード | グレード | レース | 公開資料 |
| --- | --- | --- | ---: | --- |
| 小倉 | 81 | G1 | 12 | https://keirin.kdreams.jp/yenjoy/kaisai/2026/11/18/ |
| 西武園 | 26 | F1 | 10 | https://keirinhex.jp/races/20261118/ |
| 大垣 | 44 | F1 | 10 | https://keirinhex.jp/races/20261118/ |
| 小松島 | 73 | F2 | 11 | https://keirinhex.jp/races/20261118/ |
| 松山 | 75 | F2 | 7 | https://keirinhex.jp/races/20261118/ |
| 静岡 | 38 | F2 | 11 | https://keirin.kdreams.jp/shizuoka/racecard/38202611170200/ |
| 宇都宮 | 24 | F2 | 9 | https://keirin.dmm.com/utsunomiya/racecard/2026-11-18 |
| 高知 | 74 | F2 | 9 | https://keirin.kdreams.jp/kochi/racecard/74202611170200/ |
| **全国計** | | | **79** | https://keirin.kdreams.jp/kaisai/2026/11/18/ |

実際の全79個の `YYYYMMDD+場コード+R番号` IDを **[不変GitHubコミット4f601b9](https://github.com/haji84/RACE-AI/commit/4f601b9b8ba3a5edb35e55c298eec72248c7a15d)**（2026-11-18 **07:24:42 JST**）で登録。正本は `docs/evidence/2026-11-18/keirin_all79_nationwide_AB_registered_v1.json`。79Rとも最初から母数に含め、欠測・C未生成・結果未確定だから削除しない。

## ここまでの実レース実績（厳密に区別）

- **全国対象の登録：79/79**。これは「予想79件」ではない。
- **実際に締切前に生成してAES-256-GCM暗号保存したA+B：既存の西武園1R `202611182601` の1レース**。GitHubコミット [5b4abe91](https://github.com/haji84/RACE-AI/commit/5b4abe91cacfc13a876648e51b8f90fb9b086dc6) の時刻は06:55:57 JST。A/B各8点、元動画局面は未認証。研究内容は `docs/KEIRIN_ACTIVE_GENERATED_AB_OPTIONAL_C_20261118.md` に記載。
- **残り78Rについて本チャットで新規A/Bを作成した証拠：0件**。未生成を「不的中」とせず`NO_FORECAST / HOLD`。
- **独立runner暗号文SHA照合：上記1レースの暗号文について成功**。別runner RSA復号・公式締切の独立認証・正式結果でのA/B照合は未合格。
- **正式な79R一巡完走：0/79**。GitHubのsynthetic-ci SUCCESSは本番予想生成数に数えない。
- **Cの正式実追走ラベル：0件**、CのみHOLD。

## 今回追加した実装

1. `race_ai/keirin_nationwide_active_AB.py`：**79件を完全保持**。通常50件だけで成功とは扱わない。会場コード/出走日/レース番号・重複・欠場場を照合。本人の既存予想と6局面の両方が揃わないレースは予想未生成/HOLD。6車（宇都宮1R）・ガールズを除外しない。独立した出走表・締切・暗号文読戻し・公式結果の証拠が欠ければ正式成績に入れない。
2. `race_ai/keirin_nationwide_AB_executor.py`：真の出走前レースデータと締切時刻を独立に認証できるときだけA/Bを作る。生成関数は既存 `race_ai/keirin_active_available_pipeline.py` に接続できる形。作ったA/Bは別々の非公開AES保存関数へ渡し、次の別runner暗号文SHAが確認できたものだけ独立読戻し済と表現。公開報告に選手データ・買い目/復号鍵を出さない。**ソースが1件もなければ79RをHOLDで終了し、自動で架空の予想を作らない。**
3. `race_ai/keirin_dynamic_nationwide_registry.py`：**11月18日の79を将来日に固定してしまわない**。毎日の開催場/当日のレース数を独立確認したときだけその日固有のコホートを生成。1社の部分一覧だけで「全国を全件登録」としない。翌日以降の会場数・レース数が変わっても自然に対応。
4. `tests/test_keirin_nationwide_active_AB.py`／`tests/test_keirin_nationwide_AB_executor.py`／`tests/test_keirin_dynamic_nationwide_registry.py` を既存Actions研究CIに登録。実在79Rの登録ID一覧と、**架空ソースでの安全な処理経路**のみを検証。合成データのケースを「本番実績」と数えない。

## これから必要な本番接続（NO-GOを正直に残す）

- **実動データ取得**：全国8場の「真の出走表・当日更新・ライン・コメント・勝ち上がり・最新締切」を取得し、元ページの可用時刻/SHAとセットで個別に認証。現在のWINTICKET1GET拒否の旧原因を、別サービスを規約回避して叩くことで隠さない。HEX通常50件のみはNG。静岡・宇都宮・高知も必ず探索。
- **79個の予想開始**：既存Aと真の6局面Bを各締切65秒以上前に別々に作り、一度だけ秘密鍵保護AESを保存。締切変更・配信欠落・早発走・欠車なども原本と状態で区別し、遡及予想は一切禁止。
- **独立GitHub実証**：保存された全モデルの暗号文SHA・本番RSA復号（許可された別runner）・作成時刻を連動し、79件の成功/欠落を監査。
- **結果**：主催者の最終発表・払戻・返還/同着・訂正を別証拠で認証し、同じレースのA対BをHit@1/Hit@全候補/各点100円の仮想回収率とHOLD率で採点。Cのデータが出来るまではA/Bを止めない。
- **正式な全国無人本番はまだ完成していない**。今回のコード追加はDraft PR #291のみ、保護mainへ未統合。A/B予想生成・秘密鍵付与・結果取得を無断で本番スケジュールへ昇格しない。

**最優先の次のゲート**：2026-11-18の残り78レースについて、レースごとに公開済みの真正な出走前情報を入れ、少なくとも追加1レースで締切前A/B暗号原本の作成から別runner読戻しまで実証する。その後、毎日の全レースへ適用率100%を目指す。未生成は水増ししない。


## 11/18 07:44 JST 追加：毎日変動する開催母数と全国結果スコアボードの検証

- `race_ai/keirin_dynamic_nationwide_registry.py` は **2026-11-19以降の日付も動的に受付**。79という固定数を将来も使い回さず、独立した公開開催場一覧を優先して入場。未確認会場を全国全件と発表しない。翌日コホートが7Rしかないという架空ケースも合成で検証。
- `race_ai/keirin_nationwide_AB_executor.py` は実79件と将来の可変件数の両方に対応。出走前情報・締切・本物のA/B生成・所有者AES create-only保存・独立暗号文SHAがそれぞれ欠けたレースはHOLD。**当日79件に予想を自動生成したという意味ではない。**
- `race_ai/keirin_nationwide_AB_results.py` は会場別に固定母数、予想済み、正式に照合できたレース、HOLD、Hit@1/全買い目、100円均等仮想回収率を集計。第三者検証がない自己申告の的中レポートはHOLD。A/Bは同じ実レースのみで比較、CはCがある同一分母に限定。
- 合成テスト3群 `tests/test_keirin_nationwide_active_AB.py`、`tests/test_keirin_nationwide_AB_executor.py`、`tests/test_keirin_dynamic_nationwide_registry.py` と結果採点 `tests/test_keirin_nationwide_AB_results.py` を既存研究CIへ追加。**[GitHub Actions Run 44192752948](https://github.com/haji84/RACE-AI/actions/runs/44192752948)で研究サブセット202件PASS**。PRの本番main限定ジョブはSKIPPED。合成テストにおける実際の予想/払戻・架空提供元コールバックを本番79件に加算しない。
- PR #291タイトルを「nationwide all-race A generated vs B six-phase, optional line C」に更新、旧4モデル前提と新方針の違いをPR説明先頭にも明記。

**対象登録の完了 ≠ 79件予想の自動生成完了 ≠ 79件結果照合完了**。2026-11-18の未完78Rは、個別に真の出走表・ライン・締切を取得してBを作りAESで不変保存しない限り完成にならない。現時点で自動無人本番達成は未確認。
