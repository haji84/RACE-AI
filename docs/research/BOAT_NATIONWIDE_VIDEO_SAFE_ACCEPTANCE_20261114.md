# BOAT 全国P1・展示映像研究ゲート（本番影響なし）

基準日：2026-11-14（JST）。このブランチは本番ではない。production/mainのref、既存スケジュール、GitHub Actionsの公式GET、鍵、モデル、採点器、原本には変更を加えない。PRはレビュー用のDraftで維持する。

## 実測の分母と今回の作業

2026-11-13の既存監査では、公式開催は13場156レース。P0原本が136レース、P1原本が9レースで、公式分母でP1未確認は147レース。これは「147レースが全部生成できたはず」との意味ではない。展示公開・時刻・中止・取得可否・適格モデル構成の独立照合が必要。

今回の新規純粋関数：`race_ai/boat_national_video_research_gate.py`

- ソースGET、動画取得、Git保存、シークレット読み取り、モデル変更なし。日付・race ID・締切・外部保存時刻・同一race/model原本の重複矛盾を点検し、全開催を分母としてP0件数、P1の何らかの原本、モデル群の揃ったP1、未確認理由、会場別の件数を区別する。
- 依頼側が「ソース認証済み」を宣言するだけでは証拠にならないので、この関数だけでは`nationwide_p1_complete_proven`をtrueにしない。すべて存在する場合でも、独立検証へ進む候補と判定する。
- 既存の`boat_video_connection.connect_report`が生成する`CONNECTED_EXPERIMENTAL`を、実際の既存2研究モデルの予測関数で合成実行し、モデルID・SHA・予想時刻・保存receipt属性と非本番フラグの整合を検査。現実の展示動画や著作権・使用許諾、実艇番ラベル、独立runnerの現物読戻しをこのテストから証明しない。
- 事後保存、型の不一致、締切変更、原本重複矛盾、モデル不足、動画receipt改ざん、本番昇格フラグを拒否する。

## 実行ゲート

source-freeローカル回帰：`python -m unittest tests.test_boat_video_connection tests.test_boat_video_evaluation tests.test_boat_video_model_context tests.test_boat_national_video_research_gate -q`。初回は新モジュール未実装でRED、実装後67件成功。GitHub Actionsの既存PR専用`main_entry_contract`に同じ研究テストを追加し、source-ownerの実GET jobはpull_requestで無効のまま維持。

**本番リリースゲートは未達。** 上記は実P1生成、全国156件達成、展示動画入力、独立SHA読戻しを実証しない。

## 次の本命の実装

1. 公式プログラム由来のrace IDと締切原本、P0/P1暗号原本を同じ実行の別readerで復旧し、モデル別の欠損をrace単位で実測。合成シミュレーションでなく本番プログラムのどの区間が未達かを調べる。
2. 地域/会場ごとのP1表示ページ公開時刻と締切を確認し、正当な候補を漏らさず次の取得タイミングを実装。公式サイトの403/429とRetry-Afterは厳守。
3. 実日中に新しいP1の生成→AES保存→別runner一致を実証し、モデル別・全race ID分母を計算。事後予想の補完は禁止。
4. 展示映像の利用許諾を検証し、権利処理が明確な実素材を非公開で受領する。既存のローカルFFmpeg/OpenCV評価、番号識別、比較根拠、凍結済み学習器、動画receipt、実予想結果を同じ締切前の時間軸に結合し、実レースの独立検証を合格するまで`LEARNED_VIDEO_EXPERIMENTAL`として隔離。
5. 本番候補が揃った時点で、作成元のSHA・ソースアクセス・権限・原本不変性・全CIを本人が承認した上で初めてリリースを検討する。

本PRは作業の基準を作る研究PRであり、実データの自動取得や本番導入を無断で行うものではない。
