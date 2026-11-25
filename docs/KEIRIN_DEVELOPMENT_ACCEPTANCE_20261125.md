# 選手詳細分析指示書との照合・引継ぎ（2026-11-25）

**引継ぎ済み。全体完成は未達。** [開発基準](KEIRIN_DETAILED_DEVELOPMENT_SPEC_20261125.md)を今後の要求として採用する。下表はコードの存在と実データ・本番受入を分けたものであり、既存の研究結果を再実施済みとするものではない。

## 確認した基準点

- main：`2d4a87c43795af5aaaa966603c9e5a634fb67759`（PR #329 統合後）。
- 継承する [Draft PR #327](https://github.com/haji84/RACE-AI/pull/327)：`c058c3cf5640661244c8cbef8c21c387c03eca02`。既存376変更ファイルを保全し、今回の差分だけを積み増す。PR名は「docs」だが実際はコード・研究・証拠を含む。
- [既存引継ぎ](KEIRIN_RIDER_TRAITS_CODEX_HANDOFF_20261122.md)、`AGENTS.md`、最新状況、予想／結果スクリプト、画面コード、公開ファイルとCIの実行内容を確認。
- [定期run 45606639155](https://github.com/haji84/RACE-AI/actions/runs/45606639155) はsuccessだが、実logは `HOLD_OWNER_SOURCE_PARTIAL_NO_COMPLETE_PR71_INPUT`。当日一覧は8場75レース、詳細・選手確認・新予想は0、独立読戻しjobはskip。918応答HTTP200を全入力完了と解釈しない。
- 公開SiteとGitHub移植画面は異なる配信経路。公開Siteの当日ファイルは75レース、保存済み公開記録と現HTTPのSHAが一致。[今回の読戻し](evidence/keirin-spec-handoff-20261125/public-site-check.json)。これは全国のカルテ／全モデル／全着順確率の完成証明ではない。

## 指示書27節との対応

状態の「一部」は、該当部品・研究があることを表す。全国接続や精度改善まで検証済みという意味ではない。

| 節 | 現在あるもの／今回の実装 | 未達の受入証拠・次の作業 |
|---|---|---|
| 1 目的・正本 | RACE-AI、既存A/B・保存・結果・画面を継承 | 全体完成・全国自動運用は未達 |
| 2 西武園11R | 2媒体の5-3-1一致を今回確認。会話参考を実際に独立採点 | 会話の締切前原本と映像の仕掛け順の独立確認 |
| 3 詳細カルテ | `keirin_rider_profile_history.py`、`keirin_rider_profile_identity.py`、`keirin_rider_context.py` | 全能力の観測機会・成否・分母、永続する全選手カルテ。決まり手を戦術試行数にしない |
| 4 過去条件別 | 登録番号×日付×役割／場／級班、複数年の研究記録 | 指定の全期間窓・全条件での分布と小標本補正の検証・公開接続 |
| 5 直近内容 | `keirin_rider_form_evidence.py`、`HistoryBook.features`の長短期差 | 相手・展開・消耗を考慮した30/20/10/5走・開催別の内容評価 |
| 6 映像・イベント | `keirin_video_corpus.py`、`keirin_video_review.py`、checkpoint研究 | 全車連続の時系列イベント。全国映像の確認完了ではない |
| 7 反応 | H/B仮説、番手自力の局面経路 | 条件別反応の実観測、計測可能な反応時間と選択確率 |
| 8 多段階捲り | 先頭・対抗・番手の既存分岐、事例保存 | 単騎を含む動的な連続仕掛け、外回り消耗、全試行分母での精度検証 |
| 9 単騎 | 既存のSOLO役割・基礎経路 | 戦術別自力・利用・切替・内外と相手条件を含む実履歴 |
| 10 番手・相性 | `keirin_rider_context.py`、連係／line-history／matchup研究 | 急加速・上捲り時の追走／千切れ／差し／自力を別々に予測・検証 |
| 11 コメント | 原文欄、自力方針の抽出、出典付き条件観測 | 発言時点管理と戦術選択の一致率、文脈による方針変更の接続 |
| 12 バンク | course/bank研究、役割×場の履歴 | 全場形状、位置別個人適性、左回り図・座標の実画面検査 |
| 13 気象 | 既存weather契約と研究試験 | 方位×風向×反時計回り×個人実績の接続。今回の風を未検証の耐性値へ変換しない |
| 14 評価分離 | 長期・直近・役割特徴の部品 | 指定の全分解評価、期間・標本・信頼度、当日評価との分離表示 |
| 15 六局面 | 既存`keirin_nationwide_auto_generator.py`と番手比較版 | 全車位置・条件付き多段階・イベントを含む動的分岐の全国接続 |
| 16 全着順確率 | 1〜3着の条件付き順位学習、2/3連単研究 | 1〜7/9着すべての行列・同時分布・券種周辺の整合、校正。候補支持率は代用不可 |
| 17 戦術確率 | 研究用分岐支持、H/B/checkpointの学習部品 | 本物の戦術機会と失敗を含む分母、信頼区間、条件付き／無条件表示 |
| 18 カルテUI | 移植画面の選手数字・コメント一覧、券種／絞込み等 | 選手名タップの詳細、全着順確率、条件別表示、実データ・スマホ受入 |
| 19 A/B/C | 旧版保存と比較CLI、C未生成を明示 | 新Bの全分析接続、旧A/Bを同時点で保存した公平な比較。研究版を自動昇格しない |
| 20 精度 | 多年時系列研究、forward-score／cohort／ledger | 三連単上位4・二車単上位2での未来比較、全着順Brier/Log Loss・校正と展開別指標 |
| 21 独立PDCA | **今回、既存forward-scoreへ独立展開採点を実装** | 凍結時点の展開入力と確認済み観測の定期供給、原因の検証。自動学習採用は未接続 |
| 22 カルテ更新 | 既存SQLite、日付付き履歴、映像review履歴 | 能力・全戦術・相性の差分と更新理由、時点復元、検証後の採用経路 |
| 23 真正性 | SHA/AES/Git履歴、既存別runner・result契約を維持 | カルテ・展開・全着順・券種の同一時点原本の本番完走。公式結果と配当は別受入 |
| 24 全国自動化 | discovery、GitHub定期処理、公開2媒体結果照合 | 全国対象／処理／未取得／保留の統一分母、全詳細カルテからPDCAまでの完走 |
| 25 開発順 | 現状確認後、既存採点へ最初の不足機能を実装 | 下記の次作業を順に実装・実データ比較する |
| 26 完成判定 | コード・研究・本番証拠を本表で分離 | 全国完成・前向き精度改善は未証明。CI合格を代用しない |
| 27 引継ぎ | 本書・要求整理・コード・テスト・実事例・出典SHAをGitHubへ保存 | 後続も実装／採点／採否／未達を更新する |

追加6能力（捲り抵抗、番手自力、並走持続、戦術切替、消耗後末脚、内外位置別）は[要求の第3節](KEIRIN_DETAILED_DEVELOPMENT_SPEC_20261125.md#追加必須能力)へ保存した。既存の番手自力・相対上がり等の部品を、6能力全体が測定済みである証拠にはしない。

## 西武園11Rの実照合

- [結果チェック](evidence/keirin-spec-handoff-20261125/seibuen11-result-check.json)：既存parserでKドリームスとnetkeirinの5-3-1、三連単100円840円が一致。**主催者公式結果の認証ではない。** 公式時刻・映像による展開は未認証。
- [会話由来の参考事例](evidence/keirin-spec-handoff-20261125/seibuen11-conversation-reference.json)：ユーザーが記録した初周、打鐘前、④→①→⑤の捲り、⑥と③の追走を出典別に保持。実測していない距離・速度・時刻は追加していない。
- [実行結果](evidence/keirin-spec-handoff-20261125/seibuen11-reference-evaluation.json)：着順参照一致、確認済み展開はE、ユーザー観察に基づく暫定B。**正式な締切前成績への加算0件。** 初周の全順序と全仕掛けの事前原本は無く、不足を後付けしない。
- 当日の公開済みファイルは以前の公開記録のSHAと一致。公開データには六局面原本はなく、5-3-1は第1候補ではなく上位4候補内。[読戻し証拠](evidence/keirin-spec-handoff-20261125/public-site-check.json)。会話の「本命5-3-1」の原本と同一だと仮定しない。
- 最初のKdreams検索URLの `pageType=showResult` は既存の厳格URL validator対象外だったため、公開されたクエリなしの正規詳細URLで照合した。URL制約は変更していない。取得本文は私用一時領域だけに保持し、GitHubへ保存していない。

再実行（既存ファイルを書換えず標準出力へ参考判定のみ）：

```bash
python - <<'PY'
import json
from pathlib import Path
from race_ai.keirin_flow_evaluation import evaluate_case
p = Path('docs/evidence/keirin-spec-handoff-20261125')
c = json.loads((p/'seibuen11-conversation-reference.json').read_text())
r = json.loads((p/'seibuen11-result-check.json').read_text())
print(evaluate_case(c['prediction_reference']['flow'], c['observed_facts'],
    starters=set(c['starters']), result_hit=c['prediction_reference']['reported_top1']==r['winning_triple'],
    observed_at=c['recorded_at']))
PY
```

## 今回追加した独立採点の契約

`race_ai/keirin_flow_evaluation.py` を `scripts/keirin_forward_score.py` に接続した。新しい予想エンジンや別PDCA正本は作っていない。旧引数での返り値は変えず、観測を指定した場合だけ `flow_evaluation` を追加する。予想配列、重み、原本、モデル採用、定期運用、公開Siteは変更しない。

```bash
python -m scripts.keirin_forward_score \
  --predictions /private/frozen-predictions.json --receipt /private/original-receipt.json \
  --roster /private/registered-roster.json --results /private/results.json \
  --flow-observations /private/flow-observations.json
```

観測envelopeのschemaは `KEIRIN_FLOW_OBSERVATIONS_V1`、`forecast_sha256` は凍結予想の実バイトSHA、`recorded_at` は観測集合を保存した実日時、`races` は登録済みrace_idとfactsの配列。観測集合へ未登録レースを足せない。

元予想に `flow: {published: {...}, trial: {...}}` が既に保存されている場合だけ比較する。各側には `phase_orders`（INITIAL/BELL/FINAL_HOME/FINAL_BACK/FOURTH_CORNERの完全な車番順）、`leaders`（BELL/FINAL_HOME/FINAL_BACKの主導権）、`initial_front`、`initiative`、`attack_order`（carとattemptを持つイベントの列）を必要な範囲で保存する。主導権を車列先頭から自動推定しない。複数シナリオの中から事後に的中経路を選ばない。

各factは `metric`, `phase`, `value`, `complete`, `source` を持つ。sourceは `kind`, `reference`, `recorded_at`, `sha256`。種別は OFFICIAL_RECORD / VIDEO_OBSERVATION / PUBLISHED_REPORT / USER_OBSERVATION / AI_ESTIMATE。最初の3種は作成者の出典確認を前提とし、**この採点部品自身はURLを取得せず出典の真正性を独立認証しない**。SHAがあることだけで実映像や公式記録の正しさを証明しない。ユーザー観察は暫定のみ、AI推定は実観測の採点に入れない。

- 着順は既存の登録・締切・SHA・結果チェックを通った対象だけ採点する。結果保留なら展開の比較件数は出すがA〜Eの分類へ加算しない。
- 全体一致A/Cはゴール以外の5局面・打鐘/ホーム/バック主導権・完全な仕掛け列を全て確認できた場合のみ。部分一致はE。独立確認された一つの明確な不一致でB/Dは判定可能。
- 観測の無い局面は一致率分母に足さない。複数出典の同じ観測を重複加算せず、相反する観測は保留。同じ選手の再加速はattemptで区別する。
- 出典・集合の時刻不整合、未出走車、車番重複、GOALを展開観測へ流用する入力、不正SHAを拒否する。
- 返り値は件数と分類・分母のみ。元の買い目・選手順序・本文を出力しない。

この接続は**任意の観測ファイルを渡して動く採点機能**までであり、凍結時のflow自動作成、レース後の観測自動収集、カルテ更新、本番自動PDCAは未接続。

## 精度についての引継ぎ

[既存20:08記録](evidence/keirin-95-continue-20261125/checkpoint-2008.md)は2媒体一致51件で三連単上位4＝16/51、上位8＝26/51、掲載点数＝19/51。これらは継承した特定時点の記録であり、今回再採点した全国成績ではない。今回の変更により着順精度が上がったとは主張しない。複数の試験案を同じ結果で選ぶことと、未使用の未来期間で効果を確認することを分ける。95%等の旧研究目標も完成の代用品にしない。

## 次に実行する作業

1. 既存 `keirin_rider_profile_history.py` と `keirin_form_history_admission.py` のID・時点契約を再利用し、レースに出る実選手のカルテを期間・標本・欠測付きで出力する。推定・実測・未観測を分ける。
2. 確認可能な戦術イベントを私有の既存review/履歴へ接続し、追加6能力を機会分母付きで導出する。決まり手回数だけで補わない。
3. 同じ取得時点の旧A/Bと比較Bについて、事前に選んだ代表flowを原本と一緒に新しい時刻・版で固定する。以前の原本にflowを追記しない。
4. 観測を別に保存して今回の採点に渡す。全着順同時分布、校正、カルテUIと公開経路を既存資産へ順に接続する。モデル採用は同条件の未使用未来レースで判断する。

先行資料にある私有333ファイル、複数年SQLite、映像、モデル重み一式は、この環境で全復元・再検証したとは主張しない。公開されたハッシュや集計だけから非公開の原本を作り直さない。Actions Secretを出力・移転したり、既存運用のモデルpinを変更したりしない。
