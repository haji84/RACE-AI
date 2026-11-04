# 既存モデルの私有保存と原本比較

既存Draft PR71のローカル接続。全16系統の既存アルゴリズム・保存原本を扱うための処理であり、全4競技の実運転や精度改善が実証済みという意味ではない。新workflow・常駐loop・取得先・モデル系統・公開先は作らない。

## 実入力からの保存・読戻し

```python
from datetime import datetime, timezone
from race_ai.private_dispatch_operation import PrivateDispatchJournal, run_saved_inputs
from race_ai.dispatch_product_projection import project_dispatch

journal = PrivateDispatchJournal(owner_private_db_path)
operation = run_saved_inputs(
    journal, explicit_schedule, native_inputs,
    at=datetime.now(timezone.utc),
    allow_source=reviewed_policy.authorize,
)
saved = journal.read_operation(operation["operation_id"])
view = project_dispatch(saved, dataset_status="REAL_REPORTED")
```

`explicit_schedule`と`native_inputs`は[既存実行層の契約](ALL_EXISTING_MODEL_DISPATCH.md)に従う。各競技の既存native形式をそのまま渡す。4競技の正規化snapshotは`shared: {snapshot: ...}`へ渡せるが、BOAT履歴・展示原本・オート手入力・学習物をそこから推測で生成しない。

保存APIは既存`LocalPrivateJournal`の追加テーブルを使い、旧AUTORACEの表・APIを維持する。sport/race/stage/model/versionを分離し、SQLiteの同一トランザクション内で原本読取→不足モデルの実行→保存を行う。再起動・並行呼出しで元原本を上書きしない。日時が過ぎた未予想は補完しない。過去日時を現在時刻として渡して実予想を作らない。

元の整数キーを文字列へ変換すると、特に10頭以上の競馬で既存ハッシュが変わる。私有BLOBは既存codecの型保持方式を再利用し、元native objectとハッシュを保持する。JSONで一度丸めてハッシュを付け替える操作は行わない。

保存先は所有者専用の非Git領域で、親/ファイルのリンク・複数ハードリンク・権限・同一性を検査する。POSIX以外の私有ACLは未検証として拒否する。ローカルDBは外部freeze receiptではなく、その存在だけでは永続運用や無期限保管を証明しない。

実入力の新規保存には、既存の認可経路が`analysis`・`private_storage`・`private_derived`を認める必要がある。署名されたpolicyの検査を、実世界の権利許諾の自動認証とは呼ばない。元原本の初回移入は入力snapshot/学習物等の保存コミットメントと結び付け、推論を行わず保持する。十分なコミットメントを持たない旧C-lite/tactical/PDCA/Seller等は`UNVERIFIED_ORIGINAL_STORAGE_EVIDENCE`として拒否し、再生成で代用しない。既にこのjournalへ認可付きで保存した原本は再利用できる。

## 画面へ渡す

`project_dispatch()`は`operation.dispatch`または既存のdispatch reportを読み、`RACE_AI_PRIVATE_CYCLE_VIEW_V1`へ投影する。UIの「保存原本を読み込む」で派生JSONを選ぶ。書出しは[原本読込の私有保存条件](PRIVATE_CYCLE_VIEW.md)に従い、public assets/Gitへ置かない。

- 全16系統の生成/不足/対象外状態を残し、元の候補順位を再計算しない。
- オートの`A_PRE_TRIAL`/`B_POST_TRIAL`を保持し、朝版/展示後版へ改名しない。宣言された未予想段階も分母から消さない。
- Sellerの5点プランは保存5点として表示する。全順位/Top8が保存されていない場合、存在すると表示しない。
- native予想SHAがない場合は未取得のまま。別の出力本文SHAを、予想原本SHAと呼ばない。学習物SHAも別に保持する。
- 未取得の開催場/レース番号/参加者/生成時刻/保存時刻を補完しない。元の全native本文はreport/journalに保持し、画面派生には必要な順位と参照を渡す。
- すべて研究/合成閲覧。外部保存・公式結果・全開催網羅・精度改善の検証フラグを、取込値からtrueへ上げない。

## 保存済みBOAT原本の同条件比較

```python
from race_ai.private_saved_comparison import evaluate_saved_comparison

report = evaluate_saved_comparison(
    restored_state,
    schedule=declared_full_schedule,
    comparison=pinned_comparison,
    evaluated_at=evaluation_boundary,
    dataset_status="REAL_REPORTED",
)
```

`pinned_comparison`の必須キーは`comparison_id`・`sport`・`stage`・`starts_at`・`ends_at`・`baseline`・`learned`。baselineはmodel_id/model_version、learnedはmodel_id/model_version/training_sha256を指定する。対象期間は開始を含み終了を含まない。現在対応するのは、保存済みBOAT観測相性2系統とその学習版。4競技すべての学習版が存在するとは扱わない。

対象scheduleにはrace_id/sport/cutoff_at、任意のtrifecta_offeredを渡す。呼出側の台帳を独立に全開催確認したとは言わない。予想は同一race/stage/cutoff/as-of/roster/inputの原本同士を結び、別版や結果を見て選んだ予想へ差し替えない。学習版には正しい基準原本・別保存された学習物・学習対象除外の参照が必要。不足は`TRAINING_UNVERIFIED`等の理由を残す。

結果観測は保存artifact/memberへ結び付け、評価時点までに得られた履歴を使用する。重複/矛盾する着順、同着、返還、中止、結果拒否、払戻確認不足は通常的中と混同しない。取得時刻を公式確定時刻や公式改訂番号にはしない。

通常結果が評価できる対象については、元/学習版に共通の分母を使い、未予想・証拠不足も残す。出力するのは研究上の記述的件数・比較表であり、正式Hit@8/実購入回収率はnull。独立認証・改善実証・本番採用フラグはfalseのまま。予想/学習/採点runnerの再実行やproviderへのHTTPはない。

## 合成受入と外部条件

`tests.private_dispatch_ui_fixture`は全16系統の既存関数を使った合成出力と、4競技のSQLite保存→再起動→原本再利用→画面投影を作る。実入力や実購入ではない。[今回の試験・画面証拠](evidence/2026-11-04/continued-operation/EVIDENCE.md)を参照。

この環境の実原本読戻しは0件。api.github.com許可の実行環境への適用、Library原本の接続、4競技の本来の実入力・外部freeze/result・恒久私有保管、実機Safari、将来レースでの改善実証は未完了として[最新状況](RACE_AI_LATEST_STATUS.md)へ記録する。
