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


## ローカル実動画デコード経路の追加確認（合成映像）

公式映像・所有者の実撮影素材は使わず、FFmpegで3秒間・320×240・12fpsの単純な色付き矩形を含む合成MP4を生成した。既存`scripts/boat_video_analyze.py`の**実FFmpeg/実OpenCV経路**で解析し、`save_evaluation`による非公開0600レポートを`read_evaluations`で再読込した。

- 合成MP4 SHA256：`cb40c7b950c014d4d63ed0536aed5c785e1929a99afc9689bdf83e1db745705f`
- 生成レポート SHA256：`4f998ef16c78737c5e2e4be36e42f98c18ef416f6820f1d073dee468e80fa03b`
- 実ファイル読込・映像デコード・封印レポート：成功
- 六艇候補の表示：6、実際に数値測定できたphase：0
- `dataset_status=SYNTHETIC_ONLY`、`validation_status=UNVALIDATED`、`model_eligible=False`

**このテストは展示映像の艇番識別・実測性能・予想生成を証明しない。** 初回、作業ディレクトリのsetgid許可ビットが0600/0700制約を満たさず拒否された。所有者専用の正しい0700へ修正すると成功した。本番保護のため、この権限検査は弱めていない。合成メディアも非公開の試験領域から本番・Public Gitへコピーしていない。

## 実原本の件数証拠（本番へ影響なし）

11月13日の保存済みowner原本を読んで作った、公開可能な**件数だけの抜粋**を`tests/fixtures/boat_20261113_authenticated_count_summary.json`に追加した。元のGitHub Actions検証ジョブ番号は`43482296813`、そのZIP内のJSON原本SHA256は`64922c4d6b5355e30b8d2316558d2b4e9beb73ee7e93c805291298b4b99bee53`。これは元の監査時点での証拠への参照であって、今回のCIがAESを再復号したことは意味しない。

確認事項：公式掲載156、P0 136（2モデル272レコード）、P1 9（5モデル45レコード）、P1未確認147。内訳は締切後に取得された記録が21、試行記録なし126。1レースは公式締切とP1原本締切が不一致。展示映像を使った予想の原本は確認対象0。欠落147すべてがP1生成可能だったという証拠もない。これらの個別原因を「展示がなかった」と補完しない。

## 実映像の権利と非公開AI解析の入口

映像を使う前に`race_ai/boat_video_rights_admission.py`の研究専用入口を追加した。入力はレースID、締切、実動画SHA、取得時刻、権利者の明示した私的コピー・自動フレーム解析・研究予想への利用範囲、独立の許諾原本確認である。文面を自称するだけではHOLDし、条件が揃っても`READY_PRIVATE_RESEARCH_INPUT_ONLY`という**入力準備**しか認めない。映像DL／展示映像AI完成／本番公開／予想的中は認定しない。

2026-11-14時点の確認済み一次情報：
- BOATCAST公式サイトポリシー：https://boatcast.jp/static/sitepolicy/index.html （著作権者の許諾や法定例外を超える無断利用・大量アクセスの制約）。
- ボートレース下関FAQ：https://www.boatrace-shimonoseki.jp/sp/index.php?page=other-faq （公式以外でのレース映像使用を認めない旨）。
- ボートレース福岡FAQ：https://boatrace-fukuoka.com/modules/other/?page=index_faq （動画コンテンツ材料としての使用を案内。ただし自動DL・AI研究やモデル学習への包括許諾とは読めない）。
- ボートレースまるがめFAQ：https://www1.marugameboat.jp/faq.htm （リプレイ映像等は非営利目的に限って一定の利用を案内し、他会場の許諾範囲とは区別）。
- ボートレース多摩川：https://www.boatrace-tamagawa.com/sp/entry/?page=other-racevideo （オンラインでのレース映像公開について届出・回答が必要）。

いずれのFAQも全国24場の自動取得・機械解析・AI学習・再配信をまとめて許可する根拠ではない。素材の権利・利用条件を確認できないものは、ユーザーが望む研究モードでも無条件で取り込まない。独立許諾確認コールバックの試験用モックを使った成功は**実際の利用許諾を得た証拠ではない**。

本番への昇格条件は従来どおり、実映像＋許諾→実艇番照合→追跡精度・動作測定→締切前の保存済みP1原本→別runner SHA検証→将来結果PDCAまで、すべて本物の再現証拠が必要。
