# B-LITE / ENRICHED シャドー予想モデル v1（実装と検証ゲート）

2026-10-24 JST。対象: [Issue #67](https://github.com/haji84/RACE-AI/issues/67) / [Draft PR #72](https://github.com/haji84/RACE-AI/pull/72)。既存FULLは [Draft PR #71](https://github.com/haji84/RACE-AI/pull/71) のまま保持する。

## 新実装の位置づけ

`race_ai/boat_sparse_shadow_models.py` は新規**研究用**ロジック。既存 `comprehensive_four_sport_models.py` を変更せず、旧予想・旧SHA・公式結果・mainも変更しない。

| 系統 | 不変モデルID | 入力 | 実装時点での評価 |
|---|---|---|---|
| A: 旧FULL | 旧モデルの既存ID維持 | 6艇×11＋環境9＝75観測値 | 予想稼働・未来成績は未実証 |
| B: 軽量 | `boat-b-lite-v1-untrained` | 6艇それぞれに出典と時点を備えた全国勝率代理・当地勝率代理・モーター2連対率代理の3数値、計18観測 | 合成テストのみ、係数未学習・確率未校正 |
| C: 拡張 | `boat-enriched-v1-untrained` | Bの3数値＋6艇に等しく取得された追加選手特徴と、適合する気象/水面観測 | 合成テストのみ、係数未学習・確率未校正 |

追加できる特徴量の候補は `recent_form`, `start_reliability`, `finishing_power`, `consistency`, `start_timing`, `lane_course_fit`, `wind_response`, `wave_response`。気象・水面は `wind_mps` / `wave_cm` を、選手別の対応能力が本当に観測されているときだけ相互作用として反映する。観測値が無ければ気象の影響を創作しない。これらの変換式・仮重みの精度は未検証で、実モデルとして本番採用はしない。

**予想候補の数学的な正規化と、予測確率の校正は別**。`candidates.score`の合計が1であっても校正済確率ではない。Brier Score/Log Loss等の正式値に使用しない。

## 欠測・公平性・証拠

- 必須18個は値をでっち上げず、存在しなければ `NO_FORECAST` 相当の検証エラーとする。元B候補の `published_at=null`, `sample_n=null`, `source_rights_ref=null` のままでは**研究モデルの入力承認も通さない**。
- 任意項目の欠測は `MISSING`, `NOT_YET_PUBLISHED`, `NOT_APPLICABLE`, `RIGHTS_BLOCKED`, `SOURCE_UNAVAILABLE` で区分し、ゼロや曖昧な平均値で補完しない。選手ごとの任意項目は6艇全員に存在するものだけを拡張モデルの比較に使用。1艇だけ利用可能でも勝手に加点しない。未網羅項目は診断に残す。
- 追加特徴が1つも全員分そろわなければ、拡張モデルは `NO_FORECAST_NO_COMPLETE_ENRICHMENT`、B-LITEの旧予想は影響を受けない。各モデルが締切前に予想できなかった場合も全対象レース分母に残す。
- 入力は `published_at <= captured_at <= as_of < scheduled_cutoff_at` を要求。結果、オッズ、人気、配当を特徴に混入させない。`aggregate_stat`等は確かな集計母数が必要。単発気象観測や予報に偽の母数を強制しない。予報の対象日時を区別する。
- `OPERATOR_SUPPLIED_RESEARCH` は用途別利用権限確認の独立コールバックが無ければ拒否する。コールバック成功だけで規約適合、真正の外部時刻、公式締切、公開資格が証明できたという意味にはしない。
- `predict_shadow_pair` の全出力は `official_prediction=false`、`external_pre_cutoff_receipt=null`、`purchase_decision=NO_BET`、`formal_hit_at_8_eligible=false`。推論は純粋関数で外部通信や買い目保存、決済を行わない。研究用の同じsnapshotを両モデルで評価し、別SHAを残す。

## 未実施と次の受入条件

1. **既存Bファイル実データ**は10月22日分から3,024個の候補値を変換できたが、元の公表時刻、元統計の標本母数、利用権限の確証が足りない。今回この値を将来のレースへ流用せず、実データで新モデルを実行したとも主張しない。
2. 新モデル2系統は `tests/test_boat_sparse_shadow_models.py` による架空入力の契約テストが先行。実データの適法な取込みと特徴量証拠、別AIによる批判的レビュー、CIのexact head合格が正式な採用前に必要。
3. 未来の未使用レースを同日同条件で事前固定したA/B/Cシャドー比較。開催全対象はB-LITEの予想が無いレースも分母に含む。初回は1レースの公式締切と外部サーバー受信時刻を照合した予想凍結、公式着順・返還・払戻・改訂照合が先。実買い目・自動投票・課金なし。
4. 予測精度/回収率改善、全4競技への横展開、main統合、iPhone本番公開は別ゲート。98%は未達の挑戦目標。

**限定**：新モデルをDraftコードとして作成したことで、既存FULLの要件緩和、サービスへの有効化、実レースへの正式適用が承認されたと解釈しない。
