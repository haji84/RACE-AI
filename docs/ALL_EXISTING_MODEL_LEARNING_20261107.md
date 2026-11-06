# 全既存モデルの研究用学習接続（2026-11-07 JST）

登録済み16系統・31競技枠に、元の式を使う係数推定・時系列検証・暗号化候補・同一入力の比較・PDCA契約を追加した。**実データで学習済みなのはボート観測系2系統、各8件（学習6・検証2）。残り29競技枠を実学習済みとは報告しない。** 新しい予想モデル、本番昇格、基準係数の変更はない。

## 1. 調査したAPIと既存構成

艇愛DB仕様・権利・公式配布仕様は[既存調査](TEIAI_HISTORY_INTEGRATION.md)、[個人研究判断と原文SHA](BOAT_PERSONAL_RESEARCH_LEARNING_20261107.md)を再利用。今回の艇愛DBデータAPI追加GETは0件。認証された保存済み原本と実GitHubメタデータを使用した。

API一覧（既存調査の再掲、末尾 `/` が必要）

|API|形式・指定|前段の実取得|
|---|---|---|
|`/api/meta/`|JSON、収録初日・最終日・レース数・更新時刻|資料調査のみ|
|`/api/highpayoff/YYYYMMDD/?limit=5`|JSON、limit 1〜50|資料調査のみ|
|`/api/today/?date=YYYYMMDD`|JSON、開催場・前月末まで12か月のコース成績|資料調査のみ。過去日付指定が当時値を保証するとは解釈しない|
|`/api/stadium/NN/course/`|JSON、場コード01〜24|資料調査のみ|
|`/api/race/YYYYMMDD/NN/R/`|JSON、source/race/day/entries/payouts|20261101/13/10 1件|
|`/api/racer/NNNN/`|JSON、source/racer/stats|4444 1件|
|`/api/racer/NNNN/results/`|UTF-8 BOM CSV、全出走|4444 1件、4,470行|
|`/api/rank/next/`|CSV、来期適用勝率|資料調査のみ|



BOAT RACE公式K/B配布、mbrace選手期別配布を照合基準にしている。取得上限・条件を緩和せず、新しい取得タスクも追加しない。出典：BOAT RACEオフィシャル、[艇愛ボートレースDB](https://boatrace-db.jp/)。

要求された既存BOAT履歴・特徴量・展開・入力・4競技dispatchを調査し、現在のcatalogとdispatchから16系統/31枠を列挙する。古い2系統の用途MACを全モデルに拡張せず、別ドメインの所有者判断を、原本・取得元集合・全入力SHA・レジストリSHAへ明示的に結び付ける。

## 2. 実際に利用した項目

以前から暗号化保存済みの選手登録番号・艇番・レースID・開催場・締切・取得元SHA・取得時刻・公式確定順序と払戻を再利用。会場別履歴を含む凍結済みP0入力を選択し、全国勝率、モーター2連率、直近着順/ST、コース別着順/STを既存observed学習器へ渡した。会場別集計の期間・母数・取得元は原本で維持する。

## 3. 未取得・未学習の項目

8件はすべてP0（展示入力なし）。展示ST/展示タイムは支持数0で基準係数を保持。A/B/C-liteの当時の完全な元入力、戦術履歴、独自rating、他競技の本人識別付き入力・認証済み結果を後から創作しない。

全期間gridは2005-01〜2026-11、263か月、1,167,150レース/7,002,900艇、2,643登録×24場=63,432プロフィールという前段の実測を再利用。17未掲載日・156会場日などの欠落と2005年より前を保持し、『全選手の生涯全期間完成』とはしない。現時点で旧公式BOAT系の取得元スコープのみが実認証されており、非BOATの本CLIによる実学習は未接続。非BOATのライブラリ契約と暗号化入力保持は合成データで確認した範囲。

## 4. 正確性・時間・同条件の扱い

前段で艇愛4,470艇行中4,424一致・不一致0・公式欠損46、別実1レースの6艇と10払戻の一致を確認。今回これを再取得・全量再照合したとはしない。全期間100%の正確性や精度向上を主張しない。

入力取得・保存・結果取得・公表・候補作成・予想生成・実締切を区別する。公表時刻不明はNoneのまま。結果の利用可能時刻順に6/2分割し、同時刻を跨がせずholdoutで係数を変えない。若手の母数を捏造せず、支持4件未満は元の係数に固定。勝者の決まり手を特定敗者の被害や前付けの意図に読み替えない。

各比較は同じ競技枠の同じ元入力・名簿・締切で基準と学習候補を再計算する。sellerの見送りと3/5点、各モデルの元の買い目数を保持し、全モデル同一予算・同一実コホートという主張はしない。本人IDを持たないseller/AUTOは別の出典/時刻/元入力SHAに結合したregistered_rosterを要求し、枠/車番を本人IDの代わりにしない。

## 5. 対応モデルと特徴量・係数

元の非線形混合・条件付き確率・負係数・clampを保つ。共通PLを別モデルの別名として使わない。係数数は既存式に従いモデルごとに異なる。実観測2系統は8係数のうち各6係数が更新された。

| 既存系統 | 対応競技（順序対応） | 係数数 | 実測段階 |
| --- | --- | --- | --- |
| `boat-display-rating-PL-reference-v1-UNVALIDATED` | boat | 2 | 合成入力で確認、実入力不足 |
| `boat-course-motor-shadow-v0.1-UNTRAINED` | boat | 9 | 合成入力で確認、実入力不足 |
| `boat-local-start-course-shadow-v0.1-UNTRAINED` | boat | 12 | 合成入力で確認、実入力不足 |
| `boat-course-entry-method-scenarios-v0.1-UNTRAINED` | boat | 8 | 合成入力で確認、実入力不足 |
| `boat-comprehensive-v1` | boat | 8 | 合成入力で確認、実入力不足 |
| `boat-scenario-mixture-v1` | boat | 26 | 合成入力で確認、実入力不足 |
| `boat-observed-pairwise-factor-v1` | boat | 8 | 実8件・6/2 |
| `boat-observed-pairwise-start-v1` | boat | 8 | 実8件・6/2 |
| `multisport-factor-interaction-v1` | boat,keirin,autorace,horse | 11,14,11,12 | 合成入力で確認、実入力不足 |
| `multisport-scenario-ensemble-v1` | boat,keirin,autorace,horse | 17,20,17,18 | 合成入力で確認、実入力不足 |
| `multisport-conditional-duel-v1` | boat,keirin,autorace,horse | 17,20,18,19 | 合成入力で確認、実入力不足 |
| `multisport-race-trajectory-v1` | boat,keirin,autorace,horse | 20,23,21,22 | 合成入力で確認、実入力不足 |
| `multisport-chronological-ranker-v1` | boat,keirin,autorace,horse | 64,63,60,91 | 合成入力で確認、実入力不足 |
| `autorace-personal-observed-baseline-v1` | autorace | 3 | 合成入力で確認、実入力不足 |
| `boat-pdca-lane-shadow-v1` | boat | 1 | 合成入力で確認、実入力不足 |
| `seller-shadow-v1-20261104` | boat | 5 | 合成入力で確認、実入力不足 |

## 6. 新規・変更ファイル

- `race_ai/existing_{boat,common,special}_parameter_adapters.py` と対象nativeモデル：省略時は既存出力SHAを維持する任意係数入口。
- `race_ai/all_existing_model_{registry,learning,research}.py`：31枠の契約・原本/名簿/用途/時系列・元式による最適化・状態検証。
- `race_ai/all_existing_model_{inputs,intake,runtime}.py`、`scripts/all_existing_model_learning.py`：取得済み元入力の私的保持、独立artifactと認証済み公式結果の結合、既存CLI。
- `race_ai/all_existing_model_{pairs,receipt,pdca}.py`：同一入力比較、暗号化の前向き証拠、モデル別採点。未学習入力専用schemaは予想を持たず、的中/損失の分母に入らない。
- `boat_venue_learning_{context,handoff}.py`、`boat_venue_research_retention.py`、`observed_weight_learning.py`、`cycle_recovery.py`：既存暗号化経路のschema切替と旧原本互換。
- `scripts/{boat_nationwide_ab_pilot,github_existing_cycle}.py`、既存composite action/既存viewer workflow：通常原本の独立保存を終えてから任意の研究経路を実行。生入力はGit外0700/0600、暗号化内容の復元確認後のみ削除。遅延・部分保存は隔離。
- Node既存PDCA係数入口（旧workersソースのオフライン計算のみ、Cloudflareへの接続・デプロイなし）、専用合成テスト、所有者用途記録、設計/実装計画。本変更の正確な一覧はPR差分に記録。

## 7. テスト

合成データの31枠すべてに8件を与え、6/2分割・係数支持・元式の再計算を確認。これは実31枠学習ではない。native省略時の既存SHA、極端係数、欠測支持、名簿誤照合、時刻/期限/ZIP/出典/候補の改変、見送り、source-only・mixed archive、キャッシュメタデータとGitHub実保存時刻の不一致、暗号化復元、中断/二重処理を検証。

最終全体テスト・独立レビュー・Actionsの実測値はこの文書末尾へ追記する。未実行の検査を成功扱いしない。

## 8. GitHub Actions

既存`.github/workflows/forecast-audit-ui.yml`の実原本復元jobで全モデル用CLIを実行し、同じ3ファイル形式の暗号化artifactへ保存する。既存round内の任意の私的予想/受入/PDCA/継続処理へ接続。新workflow・定期タスク・権限・サービス・課金なし。実行URLと固定HEADは末尾の検証記録に記載する。

## 9. HEAD・実候補の識別

本体HEADはPR71の検証記録を参照。最初の現行レジストリ実候補training SHAは `f31d234e24372d5198b50cf2c398c05934a59ac587fc3ea4c87f3d0c2a1c35ad`。既存state ref保存元 `722fafa5c3d4247bcb733cb819e3fc7cddedcbec` から別フォルダへ所有者キーで復元し、元候補との完全一致を確認した。以前の2系統実学習と係数・holdout指標は完全一致。候補作成時刻の差でSHAが変わることを同一artifactの証拠へ付け替えない。

## 10. 実データで確認済みの範囲

認証済みG7原本から14異なるレースを読み、そのうち会場別入力を当時保存した8件だけで2系統を学習。62取得元を正確なURL/rights集合で所有者の個人研究判断へ結合。実キーでローカル暗号化→既存Git状態追記→別フォルダ復元まで確認。新しい提供元許諾を得たという記録や追加の許諾質問は行っていない。本番への採用なし。

## 11. 未完成条件

29枠の必要な実native入力コホート、非BOAT公式結果の認証済み出典スコープ、学習済み全候補を用いた実未来レースの締切前保存・確定結果照合・前向きPDCA・精度優位性は未完了。コード・合成試験・2系統実学習・未来検証・本番成功を区別する。8件のP0を展示後P1や全期間学習に言い換えない。

## 12. 次の最小工程

実Actions artifactと既存全会場gridの所有者キー復元・独立メタデータ検査を終え、既存contextポインターを実artifactに更新した。次の既存巡回で実A/B/C-lite/observed元入力を締切前に暗号化保持し、別に取得した公式正常結果と結合する。各枠で最低8件（train6/holdout2）を満たしてから、対象入力集合へ明示的に結び付けた研究判断のもとで再学習する。既存研究判断の再使用によって新しい出典/入力を黙って許可しない。未来1件の保存と結果一巡を実測するまで、本番切替や予想精度向上を主張しない。

## 検証記録（実測）

- ローカル全体：`python -m unittest discover -s tests -q`、2,208件・439.597秒、OK (skipped=112)。
- 全体実行後に追加した4競技rankerの実学習artifactによる後日入力契約を含む追加対象10件は成功（6.738秒）。runtime/CLI最新18件も成功（40.541秒）。
- Node：`node --test tests/*.test.mjs`、119件成功、失敗0。既存YAML3ファイルの解析・Python構文・`git diff --check`成功。
- 独立レビュー：当初のseller見送りPDCA・本人名簿・ranker支持/評価/用途不一致、日内の無関係結果混入・保存時刻メタデータの自己申告を修正。現時点でCritical/Important指摘の残り0。
- 実装HEAD `34608b4863a816247231ce4ef3e32752682b07b9`： [Viewer Actions 42273374848](https://github.com/haji84/RACE-AI/actions/runs/42273374848) と [AUTORACE Actions 42273375048](https://github.com/haji84/RACE-AI/actions/runs/42273375048) は実APIで `completed/success` を確認。所有者キーでの実学習jobと実候補の独立復元も成功。
- 別件の既存未来収集worker run42264560643は旧HEADで原本復元中のGitHub ZIP取得が失敗して終了。現在の全モデル実装を使った未来予想成功とは扱わず、同じ失敗を迂回して原本を再生成しない。

### 実Actions候補の受入と予想経路の固定

実装HEAD `34608b4863a816247231ce4ef3e32752682b07b9` の実jobが作成したartifact `13531437402`（run `42273374848`）を独立にダウンロードし、実GitHub APIメタデータを再取得して、repo/run/head・実ZIP SHA・保存時刻・期限・所有者暗号化を検査した。training SHA `138780934da999f7cc25ffb4de7e37f5c340c47bd5544e14398a2fe29cf2b4dd`、実2学習/29不足、元の係数・支持数・holdout指標の完全一致を確認。既存state ref保存元 `105e091816a25eaeb3798f0b6aaba6aa535ad2b2` へ追記し、別フォルダから復元して候補全体一致を再確認した。

既存の`boat-venue-learning-context-input.json`と`boat-venue-learning-input.json`を、この実artifactと認証済み暗号文へ更新した。さらに通常のruntime preloaderで実候補と全会場gridを再復元し、2026-11-06 18:51:56 UTCに両者のSHA一致と31枠/実2学習を確認した。GitHub artifactのZIPは実コネクタ取得バイト、メタデータはGitHub APIの別GETを使用した。runtime readerの検証を省略していない。これは実未来P1の生成・保存・採点ではない。

[公開可能な件数・SHA・保存証拠](evidence/2026-11-07/all-existing-model-learning-counts.json)に詳細を保持。暗号化候補の3ファイル以外の生入力や係数は公開していない。期限は2026-11-13 18:44:50 UTCであり、期限後のreceiptを自動延長しない。

初回CIの全Python検証は2,209件・失敗0（170skip）、382.272秒。後段の隔離video検証283件も成功した。ローカルの112skipとCIの170skipを同じ件数と書かず、重複する検査件数を足して独立件数としない。参照先固定後の最終CIはPRの最新チェックを参照する。既存Node検証stepにも新規のnative PDCA係数テストを追加した。
