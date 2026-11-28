# 3モデル未来比較の接続契約

## 現在の判定

**実レースの3者対戦はHOLD。** `prospective_contest.py` は、既存の比較器へ原本を渡すための受付契約である。DT-R1とCodex独立モデルは、既存の公式資料認証、別ランナーの読戻し、Git暗号保全を共用できる。正式対戦には、A/B各50%の真正な両分布、3者の締切前原本、同じ条件で照合できる公式結果が必要。合成原本は接続と境界の検証に使う。

旧v1は3者の予測時刻完全一致を引き続き要求する。任意のv2では、同じ時刻に固定した同じ入力を各モデルが処理し、実際の生成時刻が異なる場合を扱う。時計を書き換えて一致させない。過去の原本をv2未来原本へ昇格させない。

## 確認済みのモデル実体

mainの確認基準は `837189bc2e5a54af6a02555a658a44af0d9cab58`。同commitまでの既存変更を通常のmergeで保持し、既存のCodex loaderと公式入力projectorを再利用する。

| 役割 | 確認済みnative ID | 保存実体・現在の接続 |
| --- | --- | --- |
| 既存統合候補 | `official-and-research-ensemble-v1` | mainの `race_ai/keirin_official_condition_trial.py:build_combined`。既存captureの暗号原本へ `combined_forecast` として保存する。参加者としての正確なartifact manifestと、所有者の指定との一致確認は未了。 |
| Codex独立候補 | `keirin-conditional-order-trees-v1` | mainの `docs/evidence/keirin-learned-order-20261128/model.sealed.json`。既存owner鍵で復号する。専用の保護手動実行で締切前の生成・読戻し・保全を行う。事後の `keirin_official_learned_replay.py` は従来の検証として扱う。 |
| ChatGPT DT-R1 | `chatgpt-dt-r1` | `evidence/20261128-resume/frozen_model.json` の内部モデルSHAは `5e022092a35c0258954090c6f3d0f8fa14f03f22511b28d6aa9183f5a38c381c`。原本・校正・契約を含む暗号化studyの保全と実owner鍵での復号検証は別工程。 |

Codexの保存実体は次のハッシュで区別する。

- 暗号化ファイルSHA-256: `ba14eb787dca7d0a6b94af4e322f5a1b85ea9e5e90d4fae84d23ed7bdca87386`
- tree SHA-256: `17d8fddfbe4f6ba25871c9e869175e5ca2ca5e7475e96ab5f5b6a19e1bf0d7c6`
- 公開検証記録の `model` をcanonical JSON化したSHA-256: `634a75078328fc061d2ed92e4f0ab0fb1fc00e9a4331d4842887a923b758deb8`

ハッシュを読み取れたことは、ここで秘密鍵による実復号を行った証明ではない。native IDだけでも同一モデルの証明にはならない。

### A/B各50%の契約と実原本の受入

確認済みmainの既定値は `current_weight=0.5`。現行A/Bがそれぞれ25%、研究側の合計が50%となる。研究資料が不足した場合の系統別再配分と保留も同じ実装に含まれる。#405の学習候補は現行A/B合計25%で、8方式が揃う場合に各12.5%となるが、その候補を未来の正式参加者へ自動選定しない。

A/B各50%は専用の `official-ab-equal-weight-v1` で受け入れる。recipeの `current_arm_weights` は `{"A": 0.5, "B": 0.5}`、`research_weight` は0、`research_allocation` は `none`。旧研究版では研究配分を0より大きく保つ。外部固定の生データと実予想原本が揃うまでは契約検査のみが通る。

公式SPの `marks-ordinal-plus-observed-rider-strength-v1` と `line-tactical-six-phase-untrained-v1` は順位付き候補を保存する。Bは未校正の展開重みも保持する。両者について同一入力・同一出走者の完全な三連単の正規分布は未確認。候補順位を確率へ変換せず、完全な両分布を実原本から復元できた場合に半分ずつ合成し、同じ分布から二車単を求める。`display-two-component-equal-weight` は過去の比較で別のdisplay系の支持値を正規化した参考値。公式SPの両原本を使用した前向き成績と区別する。

v2契約は、実artifactの `integration_recipe` と、外部固定した `expected_integration_recipe` の一致を要求する。未指定は `PROSPECTIVE_V2_INTEGRATED_RECIPE_UNRESOLVED`、配分不一致は `PROSPECTIVE_V2_INTEGRATED_RECIPE_MISMATCH` で保留する。公式Aと公式Bを別々の対戦相手に置き換えたり、未確認のA/B50%モデルを新造したりしない。既存統合には `official-ab-equal-weight-v1` と旧研究統合のうち一つを指定する。残る二枠は上表のCodex独自とDT-R1で固定する。所有者指定の対戦では前者のIDを使う。

## v2で要求する証跡

契約は3者のnative ID、役割、モデルSHA、artifactの実バイトSHA、コードcommit、特徴量schema、提示policyを固定する。canonical JSONの期待SHAは、受け取った契約自身からその場で作る値ではなく、既存の信頼済み記録から渡す。

registryへ追加する2項目は `input_snapshot_sha256` と `input_frozen_at`。前者は共通資料manifestの実バイト、後者はその原本の独立確認済み固定時刻を指す。既存のinput・history・dataset・contextのハッシュも継続して照合する。共通資料には、実際に使用した出走表、履歴、バンク等の補助資料を含める。入力ハッシュだけを後付けで同じにすることは受付の代わりにならない。

モデルごとのreceiptは、契約SHA、registry SHA、共通資料SHA、予測原本全体のSHA、実生成・暗号化・独立読戻し時刻、暗号原本SHA、source/readback receiptへ結ぶ。以下を全て確認する。

`資料as-of <= 共通資料の固定 <= 実生成 <= 実seal <= 独立readback <= 締切15分前`

契約の固定も共通資料の固定以前でなければならない。モデルごとの特徴量schemaは異なってよい。各予想がどの特徴量を使ったかは、そのモデルの `feature_input_sha256` で別に保全する。

`prospective_verifier` は既存の信頼済みモデル復元・入力再構成・原本読戻しを呼ぶ実装でなければならない。比較器は正確な契約・registry・予測原本・receiptを渡し、外部verifierからそのpayload SHA、独立性、実モデル・入力・原本の確認を受け取る。`True`、自己申告のSHA、fixture用callbackは実運用の証拠にならない。

## 残る最小の実接続

| 工程 | 既存コードの再利用先 | まだ必要な接続 |
| --- | --- | --- |
| 共通資料の固定 | mainの `scripts/keirin_official_nationwide_continuation.py:_seal_and_archive`、既存暗号履歴 | 対象全予定、同じsource bundleと補助資料、契約pin、実時刻を3者へ供給する。資料不足は予定台帳へ残す。 |
| 統合の推論 | `build_combined` と保存済み `combined_forecast` | 確定recipeとartifact manifestを実原本へ結ぶ。部分研究資料での再配分を契約と一致させる。 |
| Codexの推論 | `keirin_learned_official_inputs.project`、`keirin_learned_order.load_frozen` / `predict` | 合成原本で既存owner復元証跡・共通資料のSHA・別候補の暗号化・T−15の独立時計を照合した。実レースの原本保全と公式採点を確認する。 |
| DT-R1の推論 | `OfficialAdmissionAdapter` と `run_shadow_cycle` | 実際の履歴・contextを既存support verifierへ結び、同じ共通snapshotを使う。rivalの予想をDT-R1の学習や入力に混ぜない。 |
| 原本の形式変換 | native `JointFinish`、既存 `validate_forecast` / `fixed_selection` | nativeの `order` を比較用 `cars` へ写し、三連単の全分布と同じ分布の二車単周辺分布を保存する。変換前後のSHA、native ID、実時刻を残す。 |
| 独立readback | 既存GitHub producer/readback、`records.replay_condition_pair` 等 | 締切前に3者のモデル・共通資料・原本を別runnerで再照合し、v2 receiptの全項目へ結ぶ。結果がまだない段階で、結果を必要とする `admit_saved_pair` を代用しない。 |
| 公式採点 | `OfficialAdmissionAdapter.result_verifier`、既存結果replay、`compare_models` | 原本の固定後に公式結果を追加。全予定と3者共通対象を別集計し、過去と未来のbootstrapを分ける。 |

mainの実source処理には、repository、main ref、workflow、job、実行event、owner鍵の既存チェックがある。研究ブランチから環境変数を作ってこのguardを迂回しない。既存の保護された経路へ接続する変更とレビューが必要であり、この契約だけでproducerや秘密鍵の利用が始まることはない。

## Codex独立モデルの締切前保全

既存の `keirin-result-live.yml` をmainから手動実行する。`codex-shadow` に `dossier_day` と `dt_r1_producer_run` を渡す。認証済みDT-R1バッチと同じ公式アーカイブのコミット、登録原本、各レースの正規化入力を再認証する。対象日・出走者・締切を確認し、Codexの凍結木と固有の特徴量で両市場を計算する。DT-R1の予想や学習済み重みは入力に含めない。登録全体を分母に保持し、対象となるDT-R1原本がないレースは保留として記録する。

Codexの暗号文は専用の成果物へ保存する。別runの `codex-readback` にCodex producerのrun IDを `dt_r1_producer_run` で渡す。GitHubが記録した元バッチ・Codex生成・独立読戻しの時計と、共通資料のSHAを照合する。`codex-retain` にCodex producerと独立読戻しのrun IDを渡す。締切15分前までに独立読戻しを終えた最初の原本を、既存の暗号化アーカイブでCodexの木のSHAごとに保全する。予想値や個人情報は暗号文に保持する。

この経路の保全と、公式結果につながる3者の正式対戦は別の受入工程。共通資料と2モデルの独立原本を確認し、完全分布をもつA/B各50%の実原本が揃った時点でv2の比較に進む。

## 公式入力と復元の実接続

`official_inputs.project` は、既存の `keirin_learned_official_inputs.project` が再解析する同じ公式原資料からDTの正規化行を作る。`verification_payload` の内容を既存 `records.admit_original` の実再検証結果と照合するcallbackが必須。新しい実処理時計と、元のsource証跡の時計を分ける。登録番号のある公式履歴だけを同じnamespaceで参照し、過去archiveの名前等による複合IDを公式IDへ推測変換しない。空履歴は欠測として残す。

`prepare` の106列へ既存のバンクcontext、上がり、能力変換を適用すると462列のモデルschemaになる。固定モデルが要求するvenue sidecarは `fixtures/venue_geometry.json`、SHA-256は `a7d832a2661c6f05167e7a412a55e51183c21e746447f91dac44e14eeb4dfe19`。バンクcontextには非ゼロ係数があるため、欠落したsidecarを空列で代用しない。利用時刻とgeometryの適用範囲も既存コードで検査する。このadapter自体は未来予想を生成・保存していない。

既存の `keirin-result-live.yml` / `observe-results` には、保護されたmainからのみ実行する手動 `dt-r1-restore` を追加する。元のDT study、Codex固定モデル、B候補の実owner復号を同じ既存鍵で検査する。provider取得・採点・再学習・原本生成・モデル採用は行わず、安全な集計receiptのみを残す。実行前の実装テストと実owner復号の合格は別判定である。

## 比較API

```python
report = compare_models(
    frozen_originals,
    admitted_official_results,
    complete_registry,
    expected_model_ids=confirmed_model_ids,
    prospective_contract=externally_pinned_contract,
    expected_prospective_contract_sha256=trusted_contract_sha256,
    prospective_receipts=receipts_by_race_and_model,
    prospective_verifier=existing_verifier_adapter,
)
```

元の予測オブジェクトや時計は変更しない。欠測の対戦相手を生成しない。v2の認証不足はHOLDとして全対象分母へ残す。混在する過去行にはv1の規則を使い、`prospective_contract.admitted_forecasts` へ加算しない。無効なv2契約を渡しても、過去行をv2で認証したことにはならない。

この関数自身は公式結果の発行元を再取得しないため、`source_attested` と `formal_comparison_verified` を自動的にtrueへ変更しない。実producer、独立verifier、公式結果の接続が成立するまでは、未来対戦の最終判定はHOLDのままである。

## 公開画面の表示名

`view.py` は `all_target.models` と `common_cohort.models` の集計を公開用に写す際、次のexact native IDを既存の表示IDへ対応付ける。原本、比較レポート、参加者manifestは書き換えない。

| native ID | 既存表示ID | 画面の名称 |
| --- | --- | --- |
| `official-ab-equal-weight-v1` | `existing-integrated` | 既存統合モデル |
| `official-and-research-ensemble-v1` | `existing-integrated` | 既存統合モデル（旧研究契約の表示） |
| `keirin-conditional-order-trees-v1` | `codex-new` | Codex 新モデル |
| `chatgpt-dt-r1` | `chatgpt-dt-r1` | ChatGPT DT-R1 |

旧表示IDを使う集計も引き続き表示できる。同一集計で1枚に複数のIDが割り当たる場合や、全対象と共通対象で同じ役割に異なる明示的なnative IDが使われる場合は `AMBIGUOUS_CONTEST_MODEL_ALIAS` で表示を止める。公式A/B個別や未知のIDを統合候補へ変換しない。欠測モデルは未受領、勝敗は未判定のまま。この表示名の対応付けは、artifact確認、統合recipeの選定、未来対決の認証を代行しない。

## 根拠

- [統合方式の実装](https://github.com/haji84/RACE-AI/blob/837189bc2e5a54af6a02555a658a44af0d9cab58/race_ai/keirin_official_condition_trial.py)
- [既存captureの保存接続と実行guard](https://github.com/haji84/RACE-AI/blob/837189bc2e5a54af6a02555a658a44af0d9cab58/scripts/keirin_official_nationwide_continuation.py)
- [Codex固定モデルの復元と事後比較](https://github.com/haji84/RACE-AI/blob/837189bc2e5a54af6a02555a658a44af0d9cab58/race_ai/keirin_official_learned_replay.py)
- [Codexのmodel manifestと暗号文検証記録](https://github.com/haji84/RACE-AI/blob/837189bc2e5a54af6a02555a658a44af0d9cab58/docs/evidence/keirin-learned-order-20261128/verification.json)
- [DT-R1保存済みモデル](https://github.com/haji84/RACE-AI/blob/01afb2d79a74fee214ac97b4934e4aff3c741e4a/research/chatgpt_dt_r1/evidence/20261128-resume/frozen_model.json)
