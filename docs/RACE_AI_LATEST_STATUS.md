# 2026-11-05 10:35 JST｜最新完了run第22巡回の原本独立検証・P1+50/通常採点+35、既存後続1件起動

対象：既存Draft PR #71、同一branch `feat/four-sport-forecast-audit-view-20261022`、既存workflow 405276784。前run `41940044369` は10:22:25 JST `completed/success`、実行HEAD `d481d0fe275dbd640d9b2d9858e6dff541206877`。全artifact一覧から最大保存巡回が **第22巡回** であることを確認（第23・24巡回は `BOUNDED_SESSION_END` により未処理）。GitHub jobログに `ROUND_SAVED_AND_READBACK_VERIFIED`・round22・予想353・通常採点42・179 GETを確認。

今回は次の3 ZIPをGitHubコネクタから**実バイト独立取得**、SHA256をローカル再計算してGitHub API digestと完全一致、全ZIP CRC正常：
- P1予想 `boat-national-cutoff-41940044369-cycle-22`、artifact `13380140156`、GitHub保存10:20:30 JST、SHA256 `891cbeec1cfeef511496fb6fb38a962666263242c8cb3efa32fa71908e601d17`。
- 別イベントの公式結果・PDCA `race-existing-cycle-41940044369-cycle-22`、artifact `13380020336`、保存10:20:36 JST、SHA256 `9ee4962aff1a54bc8e9112ec8b88619559054e38f2ba6195b72a3cb7573e7e73`。
- continuity `race-cycle-continuity-41940044369`、artifact `13379311948`、保存10:22:16 JST、SHA256 `0b2acd99c9941178911a46769f1a75bae5df5c7d2ea20086064aaa95578d6dae`。

結果ZIP内 `status.json` は `round_no=22`、`updated_at=2026-11-05T01:20:35.126502+00:00`。実 `forecasts.csv` は **353モデル別予想＝初回P0 288＋展示後P1 65（13レース×5基準モデル）**、`model_coverage.json` も353件。前回09:17保存記録の303/P1 15から **P1 +50件**。通常確定結果による採点は **42件（HIT16、MISS26）**、前回7から **+35件**。別に結果待ち309行、異常着順レビュー2行を保持し、外れにしない。独立の公式結果履歴は18観測。元P0の埋込ZIPはSHA256 `3a8bde638b93b61cbe21843bff5f3dbaf120c486b45f39efc3ea3a78f89034ab` で初回受領索引と連続原本の同一バイトを照合し、再生成なし。埋込P1のSHA256も今回の独立予想ZIPと一致。

`automatic_learning.state=INSUFFICIENT_VERIFIED_RACES`（異なる通常検証済み6レース、最小8、train0/validation0）で当日係数版は未確定、`LEARNED_SHADOW`保存0、`learned_shadow_comparison` 0。学習成功・過去holdout・前向き優位性を混同しない。結果取得パーサの未対応 `SOURCE_OR_PARSE_UNAVAILABLE` 2件は失敗理由として保持。公式 GET は179/240、`halted_reason=null`。第23/24巡回は時間制限により保存なし。日付・4xx/429・真正性・取得上限の停止規則を回避していない。

`coverage_audit` は対象144レース、締切済み10、未来134、展示後5モデル完備9レース、既締切 `20261105-10-02` に5モデル別不足。該当時刻に展示が公開済みだったかは検証されておらず、取得可能だった取りこぼしと断定しない。別の学習/正式採点母数から不足を消していない。他競技は `LIVE_INPUT_INTEGRATION_NOT_YET_VERIFIED`、外部研究は `NO_AUDITED_IMPORT_MANIFEST`、全16系統×4競技・全P1・無期限private保存・学習版の前向き優位性は未完成。

10:34 JSTに後続のin_progress/queued/pending/waiting各0、先行run成功、継続すべき未来レース・未確定結果ありを実API再取得で確認。既存trigger `docs/evidence/boat-nationwide-pilot-trigger.txt` のみ1回CAS更新し、commit `74572f2f304f9122cff987b05001b4455c29780c` により**新run `41949401478`** が10:34:11 JSTに `in_progress` 開始。これは新runの予想や結果成果を意味しない。起動後は重複後続push禁止。既存同一concurrency `boat-nationwide-cutoff-20261103`、cancel-in-progress=false、180秒/24巡/65分、1セッション240 GET・1巡45 GET・最大3レース・締切210秒、単一writerを維持。原本/過去予想・既存5モデル係数は不変。新タスク/別workflow/新PR/新モデル/Cloudflare/Vercel/追加課金/main統合/公開/実投票/無検証本番切替なし。

非公開Driveのフォルダ/root所有者一致、双方shared=false、owner権限のみはこの巡回で実確認。既存14ファイルに今回runの第22巡回ZIP3件は未登録。しかし、GitHub artifact参照をDrive uploadへ直接渡す試行は `BLOCKED_FILE_REFERENCE` / `file_uri must be a connector file reference object` により拒否された。**今回の第22巡回ZIP3件のDrive新規保存・Drive読戻しSHA照合は0件**。元GitHub ZIPは無改変で、上記独立ローカル再ハッシュ済み。公開repoへの個人Drive識別情報の記載なし。Drive未達を保全成功と偽らない。\n\n今回のローカル独立ZIP照合は成功したが、これを全ソースの独立監査や全日無欠落、学習版の有意な優位性に拡張していない。旧記録と他チャットの進行は以下に保持。

---

# 2026-11-05 09:17 JST｜前run第22巡回まで保存、展示後P1+15・通常採点7、後続1件起動

対象: 既存Draft PR #71 / branch `feat/four-sport-forecast-audit-view-20261022` / 既存workflow `405276784`。前run `41929106428` は2026-11-05 08:59:19 JSTにcompleted/success。GitHub Actions jobログで第22巡回の `ROUND_SAVED_AND_READBACK_VERIFIED` を確認。第23・24巡回は `BOUNDED_SESSION_END` により予想・結果保存をskipped。24巡全件予想したとは数えない。前run実行HEADは `63bc3ec3808b4c126e5fbf2de92d8e1525800a0a`。

当日11/05の第22巡回で、run内の保存・読戻し成功ログ上、基準予想 **303モデル別行（P0=288、展示後P1=15、P1は3レース×既存5モデル）**、通常採点 **7モデル別行**、セッション公式GET **112/240**。当日08:02第3巡回で基準288/P1=0/通常採点0だったため、今回確認できた差分は**P1+15、通常採点+7**。P1は第11・14・19巡回で各5行増。初回P0は `docs/evidence/2026-11-05/p0-first-receipt.json` の初回正本を再利用し再生成なし。通常採点7のHIT/MISS、100円払戻、係数学習版数、LEARNED_SHADOW比較、coverage_audit詳細は最新ZIP内部を独立展開できないため**未確認**。結果未確認を不的中にしない。GitHub Actionのrun内読戻し成功と、この実行環境での完全独立ZIP内部監査は分ける。

前run最新保存2 ZIP：展示後原本 `boat-national-cutoff-41929106428-cycle-22` artifact `13374696437`、サーバー保存2026-11-05 08:56:55 JST、GitHub API ZIP digest `sha256:5b4ec25c1e3e2beaff7bb2b3177a0211ab7b6680045a2f79e03592b2f0e98c85`。別イベント結果/PDCA `race-existing-cycle-41929106428-cycle-22` artifact `13374801406`、サーバー保存08:57:00 JST、digest `sha256:79963f23642fb4d3f576a72933b52424756033d5af3470dc92d69b476bfd0102`。continuity `13373829491`、digest `sha256:487e62dd4c0fda3f8f31e2ac7eeac29ef1041a17414367df31fd27f5c2a3e993`。3 ZIPはGitHubコネクタからダウンロードしFilesに保全したが、この環境のcontainer/Python実行が `redis.exceptions.ResponseError` となり実バイト再ハッシュ・ZIP CRC・status.json等の独立解析未了。API登録digestだけを独立再ハッシュ成功とは言わない。

09:15 JSTの既存Actions状態再取得では全repoの in_progress/queued/pending/waiting 各0、前run成功・通常の有界終了・当日の未来P1未保存レースが残っていたため、既存トリガーファイルを**1回だけCAS更新**。起動コミット `d481d0fe275dbd640d9b2d9858e6dff541206877` により新run `41940044369` が09:16:01 JSTにin_progress。旧runのrerun/キャンセルなし。後続追加push禁止。同一concurrency・cancel-in-progress=false、180秒/最大24巡/65分、240 GET/セッション・45/巡回・最大3レース・締切210秒以上・4xx/429/日付/原本不一致停止を維持。新runの予想・結果・学習成果は未確認であり、起動のみを予想成功と数えない。

最新の独立ZIP成績検証と原本の本人限定長期保存の継続は未完成。学習版の前向き統計的優位性・全16系統×全4競技・全P1・期限なし自動非公開保存は未証明。旧5モデルの係数・買い目と既存原本は不変。新task/PR/workflow/モデル系統/頻度/追加課金/Cloudflare/Vercel/main統合/公開/実投票/本番自動切替なし。他writerの既存記録は以下に保存。

---

# 2026-11-05 08:43 JST｜当日第17巡回までの保存済みartifactをGitHub API照合（成績増分未検証）

対象は既存Draft PR #71 / branch `feat/four-sport-forecast-audit-view-20261022` / workflow `405276784` / run `41929106428` のみ。点検時HEAD `ab57ae2f297066cf0eed77cdaf8ad5219943f3c2`、状態文書更新前blob `d9a6cfbcddedfe2ca08aaaeb8e1a2a9f49d6654c`。runは `in_progress`、job `126921153640` の第17巡回stepは `completed/success`、第18巡回は `in_progress`。同workflowのqueued APIは 0 件、全workflowのqueuedは 0 件。既存concurrencyは`boat-nationwide-cutoff-20261103`、`cancel-in-progress: false`、24巡の既存workflowをそのまま使用。新workflow/頻度/モデルは追加していない。

GitHub Actions artifact API（run全一覧 `35` 件）では、第17巡回の保存済みZIPが次の2件まで増加。**これはGitHub APIが報告するdigestで、独立実バイトSHA256再計算とは区別**する。

- `boat-national-cutoff-41929106428-cycle-17` artifact `13374346050`、GitHub保存 `2026-11-04T23:42:00Z`（JST 08:42:00）、API `sha256:2386dbdcb29bd5e42e1b56ad5d0d972c104c238e9f5dc14bdc0784b878b0ba38`
- `race-existing-cycle-41929106428-cycle-17` artifact `13374211446`、GitHub保存 `2026-11-04T23:42:06Z`（JST 08:42:06）、API `sha256:72f58fe5218f1ec25e615ee1806883471d755e28d829dcfc37802f06e5d4d430`

前回08:02文書の第3巡回保存から保存済み第17巡回まで進行した事実は確認。しかし第17巡回ZIP内の `status.json` / `automatic_learning` / `learned_shadow_comparison` / `coverage_audit` / `forecasts.csv` / 公式結果履歴 / `model_coverage` / `external_research_summary` の独立読戻しは未完了。第16巡回の予想/結果ZIP 2件をGitHubコネクタでダウンロードしFilesで保全する所までは成立したが、ローカル実バイト再ハッシュ・CRC・内部CSV/JSON解析が実行環境の`redis.exceptions.ResponseError`で失敗した。従って**新しいP1件数・通常採点・的中・係数学習・同条件比較の増分は不明**であり、08:02時点の保存済みP0=288、P1=0、通常採点=0、学習版=0を現在値と断定しない。未確認を不的中に換算しない。参照する初回P0受領索引は存在し、上書きしていない。

現runの停止理由とGET消費の最新内部値を独立検証できていないため、後続の追加トリガー更新・再実行・キャンセルは行わない。4xx/429/真正性不一致や日付境界の停止条件、同時writer1、240 GET/session・45/巡回・最大3レース・締切210秒の制限を緩めない。次の確認では最新の全artifactから最大`-cycle-NN`を選び、実ZIP内statusと公式結果履歴を独立再ハッシュしてから初めて予想/採点/学習改善を更新する。全16系統・全4競技ライブ、全P1、期限なし非公開保全、学習版の前向き優位性は依然として実証未完。新task/PR/workflow/頻度/課金/main統合/公開/実投票/本番自動切替なし。

---

# 2026/11/05 08:02:07 JST｜11/05初回P0原本と第3巡回の3ZIPを所有者限定Driveに独立保全・SHA再照合

既存run `41929106428` の**GitHub上で初回保存済みのP0 ZIP**（artifact `13371295414`、SHA256 `3a8bde638b93b61cbe21843bff5f3dbaf120c486b45f39efc3ea3a78f89034ab`）、第3巡回の展示後予想試行ZIP（artifact `13371915442`、SHA256 `4ca3328dbc82e309d50d396d0059b22853b402f524c0571ce6ecd12ad2d28628`）、第3巡回の結果・PDCA ZIP（artifact `13369699300`、SHA256 `06edb78d1879da4e01488c584d8c384c330f7c82373d175288243ab1a1dc03c3`）を、**所有者本人一致・shared=false**をDrive APIで実確認した既存の非公開保管フォルダに3件とも無改変・新規保存した。各新規ファイルも権限owner 1人・shared=falseを個別検証。元ファイルとDrive再ダウンロード版をbyte-for-byte比較し、3件ともSHA256一致、ZIP CRC正常。公開GitHub文書に私有Drive ID/URL/認証情報を掲載していない。これは**3 ZIPのみの個別保全**であり、全巡回の無期限自動保全完成ではない。

第3巡回結果ZIPを独立再取得して内部status.json `round_no=3` / `updated_at=2026-11-04T22:59:52.533339+00:00`、forecasts.csv 288モデル別行、model_coverage 288件、official-result-observations.json は0件、研究manifestは未登録、`automatic_learning.state=INSUFFICIENT_VERIFIED_RACES`、`learned_shadow_comparison.saved_shadow_forecasts=0`、`coverage_audit.future_races=144` / `ended_races=0` / `complete_five_model_p1=0` を照合。**当日基準P0=288、通常結果採点=0、展示後P1五モデル=0、学習版=0、同条件比較=0**。第3巡回P1原本は`OBSERVED_ATTEMPT_NO_FORECAST / NO_COMPLETE_EXHIBITION_IN_ORDERED_CANDIDATES`で、展示未公表の時点に予想成功と偽らない。第3巡回保存時点のsession GETは14/240、halted_reasonなし、`completed_round=2`はアップロード時点の値で、GitHub Actionsでは第3巡回step成功後に第4巡回へ進行。第4巡回の未完成成果を合算しない。

11/04の基準570/通常採点489/研究版70/研究比較66は前日別runであり、11/05の新しい結果ではない。既存workflow405276784、concurrency single writer、cancel-in-progress=false、180秒/24巡/65分、240 GET/session・45/巡回・最大3レース・締切210秒以上、4xx/429/日付/真正性停止条件を維持。新タスク・新PR・新モデル系統・別workflow・課金・main統合・実投票・本番自動採用はしていない。

---

# 2026-11-05 07:57:14 JST｜当日P0初回原本の復旧完走・独立ZIP照合、展示後P1/結果は継続中

既存Draft PR #71、branch `feat/four-sport-forecast-audit-view-20261022`、workflow `405276784` のみを使用。11/05早朝の初回原本なし停止に対し、同日全runの既存原本確認→公式B入力から当日P0新規生成→GitHub別artifact保存→元ZIPとサーバー保存時刻のAPI読戻し→create-onlyの`docs/evidence/2026-11-05/p0-first-receipt.json`登録→既存workflow内の原本復元→有界repeat-startまで実証。HEADの初回索引登録コミットは`bfa7ba8b0ed46b2ae830294b376c74f24f1ebaef`（状態文書追記前）。初回索引は存在を確認した上で再発行・上書きしない。

新run `41929106428` はこの記録時点で **in_progress**。先行run `41928865017` はPython直接CLIの`ModuleNotFoundError: No module named 'race_ai'`で初回確認前にcompleted/failure。先行runの全artifactはソース検査用1件のみで、当日初回P0/展示後予想/結果原本なしと確認。CLI import修正・直接起動テストを既存ブランチへ追加し、先行runをrerunせず、同じconcurrencyを維持して新トリガー1回のみ（`63bc3ec3808b4c126e5fbf2de92d8e1525800a0a`）。新runの既存テスト、初回P0 preflight/capture/save/finalize/restore/repeat-startはActions stepでsuccess。新workflow/新PR/新モデル系統・スケジュール変更なし。

**11/05初回P0正本**：run `41929106428`、artifact `13371295414`、GitHubサーバー保存`2026-11-04T22:53:32Z`=07:53:32 JST、元ZIP SHA256 `3a8bde638b93b61cbe21843bff5f3dbaf120c486b45f39efc3ea3a78f89034ab`、元JSON SHA256 `791ddfdc72117f41954837c230040ef09a29c5f4fd423dd22e320ce0d32642bb`。公式B初回観測07:53:28 JST。144種類のレース×既存P0専用2系統＝**288モデル別予想**、144日程、skipped0。独立ダウンロードした818183バイトのZIP SHA256はAPI digestと一致しCRC正常。元ZIPは別保存の結果ZIP内にも同一バイトで残っている。元P0のsource GETは1回として同一セッションへ計上。初回原本・古いP0/P1の上書きなし。P0の2系統を展示後5モデル完成と混同しない。

**11/05第1巡回の保存済み原本のみ**：予想artifact `13371320638`（ZIP SHA256 `b31217f915752fa8185cf154ed20c562e96321bcac9e8ba046507799b0a2cdcf`）、結果/PDCA artifact `13369919747`（ZIP SHA256 `a64bc8d1886d265d537f203c79c1e8f18cb5691e49e641aa230d4d14047cbd82`）。結果ZIPは独立再ダウンロードしCRCと実バイトSHA256一致。内部status.json `round_no=1` / `updated_at=2026-11-04T22:53:55.116620+00:00`、基準予想288（P0のみ）、通常結果採点0/的中0、LEARNED_SHADOW保存0/同条件比較0。P1観測は`OBSERVED_ATTEMPT_NO_FORECAST`・`NO_COMPLETE_EXHIBITION_IN_ORDERED_CANDIDATES`、P1=0件。これは未公表展示を取得できたと主張するものではない。係数学習は当日独立照合済み通常確定結果が0レースのため`INSUFFICIENT_VERIFIED_RACES`、向上未証明。第1巡回結果ZIP保存時のsession requests_used=14/240（初回Bを含む）、結果観測0で、同ZIP内のcompleted_round=0はround完走前のスナップショット。Actionsの第1巡回stepは後にsuccessになり第2巡回へ進行。進行中runの未保存の第2巡回以降は合算しない。

11/04の570基準予想/489通常採点/学習版70/同条件比較66は**前日別runの記録**で、11/05の288件や0採点へ合算しない。全16系統・全4競技の実データ入力、当日全展示後5モデル、期限なし本人専用Drive保存、係数学習版の同条件未来優位性は未完成。現状Driveへの当日元ZIP新規保管は独立保存完了を確認できておらず、7日GitHub artifactを永久保管と呼ばない。既存停止条件、240 GET/session・45 GET/巡回・最大3レース・締切210秒・180秒/24巡/65分、同一concurrency・単一writerを維持。main/公開/実投票/課金/本番モデル切替なし。

---

# 2026-11-05 06:47 JST｜初回P0ブートストラップの下準備と原本再ハッシュ（本番予想未再開）

既存Draft PR #71、branch `feat/four-sport-forecast-audit-view-20261022` の最新HEAD `c2e15d5c4881c9e5c999c3fbbddf8f6d6f3c97ce` を確認。既存workflow `405276784` のファイル・同一concurrency・トリガーと取得上限は**変更していない**。最新のActions run一覧では11/05 JSTの対象workflow新規実行を検出しなかった。既存run `41842464812` はcompleted/success、最終保存可能巡回は11/04の第21巡回（`status.json`は`round_no=21`、`completed_round=20`であり全巡回完走と同義ではない）。

今回は既存最終artifact 3件を再ダウンロードしてZIP CRCと実バイトSHA256を再計算：予想`13336307604`=`119ee2a394acbaf1f15f1c92ca61b3ad96c80d53800cbf2c2468acf808f3762a`、結果/PDCA`13335717741`=`e6653f0fc545eead623eb0822c728d56d9a8ce1d364368a165822995d655a636`、継続`13335757993`=`64b8e3791d0ef8b94188733b290bc1f31a94e7bc0f695dedff638db3eb015242`。元API登録値に一致、ZIPのCRC異常なし。内部結果は**11/04時点**で基準570件（P0=288/P1=282）、通常採点489件（HIT139/MISS350、未通常81）、学習版70件、同条件比較66モデル別行/33レース、学習対象122レース（train92/validation30）、公式結果履歴505件。学習版の前向き優位性は未証明。

今回のコード差分は、同日の先行workflow runを列挙し初回P0の既存原本を優先して選ぶための`scripts/first_p0_bootstrap.py`追加、ユニットテスト`tests/test_first_p0_bootstrap.py`追加、および同runで新たに取得した初回BのGETを240回予算に計上する分岐を`scripts/github_existing_cycle.py`に追加したこと。ブートストラップは**既存workflowにまだ接続していない**ため、初回P0独立保存・索引登録・当日の予想再開を達成したとは扱わない。新規コードのテストはworkflow統合試験ではなく、既存の他CIでの検査のみ。B原本の11/05実バイト検証も未完了。

11/05 `docs/evidence/2026-11-05/p0-first-receipt.json` は未登録、本人専用Driveのフォルダを再列挙した範囲で当日初回P0該当なし（既存10件、shared=false、owner同一）。未接続の別保存先の不存在までは証明していない。初回原本の作成と外部時刻付与・読戻し・索引登録を安全に接続できるまで、既存トリガー追加・失敗run rerun・本番自動採用を行わない。同時writer1・4xx/429/真正性不一致・日付境界停止は引き続き必須。全16モデル/全4競技/全レースP1/無期限非公開保全は未達。新タスク・新PR・新workflow・新モデル系統・Cloudflare/Vercel・課金・main統合・公開・実投票なし。

---

# 2026-11-05 05:14 JST｜P0初回ゲートの起動経路が欠落（新しい予想・採点なし）

既存Draft PR #71（監査時HEAD `793da023383155d9306b83c1d4be73655bf2befa`、branch `feat/four-sport-forecast-audit-view-20261022`）と同一workflow `405276784`のみ確認。GitHub Actionsの最新100 run（11/05 JST以降の記録を含む）で当日対象workflow新規runは0。Actions APIのin_progress/queued/pending/waiting各0件。直近対象runは前日 `41842464812`（completed/success）。その全45 artifactから最大保存巡回が第21巡回であることを再確認：予想 `13336307604`、結果/PDCA `13335717741`、継続 `13335757993`。API登録ZIP SHA256はそれぞれ `119ee2a394acbaf1f15f1c92ca61b3ad96c80d53800cbf2c2468acf808f3762a` / `e6653f0fc545eead623eb0822c728d56d9a8ce1d364368a165822995d655a636` / `64b8e3791d0ef8b94188733b290bc1f31a94e7bc0f695dedff638db3eb015242`。3ZIPの別再取得は開始したが、この巡回の実バイト独立再ハッシュはローカル検証環境エラーで完了せず、前回03:32までの独立照合結果と区別する。

11/05用 `docs/evidence/2026-11-05/p0-first-receipt.json` は404。本人専用Drive保存フォルダのAPIを再列挙して、ownerのみの権限・`shared=false`、既存10件、当日初回P0該当0件を確認。**独立索引がないことと全保管先で初回原本が存在しないことは同義ではない**。GitHubの同日対象workflow runは0だが、未接続先まで原本不存在の断定はしていない。

**新たに特定した構造的なブロック**：現行 `.github/workflows/boat-nationwide-ab-one-shot.yml` の実行経路は、最初に `python scripts/github_existing_cycle.py restore` を呼ぶ一方、当日の初回P0を生成→アップロード→API読戻し→初回索引登録するステップを持たない。`original(day)` は索引欠落時に `FIRST_RECEIPT_REGISTRY_MISSING_NO_BLIND_REGENERATION` を必ず送出する。従って**当日の初回原本を安全に確定する別途の既存P0ブートストラップ手順が成立するまでは、同じトリガーの追加pushだけでは予想を再開できない**。原因を公式B未公開/4xxと決めつけない。公式B当日実バイトの取得・解析・サーバー受領確認は今回未実施。

安全な残工程は、同日全runと外部保管の重複監査→公式B実入力の真正性検証→本当に初回原本不在の場合に限る既存モデルP0生成→締切前の別サーバー初回保存→ZIP/JSON SHA・時刻の独立読戻し→正本索引登録→同一既存workflowの復元→P1/公式結果/PDCA/係数学習研究比較。P0の自動初回作成経路は**未実装**、今回の新規実行0。基準予想570・通常採点489（HIT139/MISS350）・学習版70・同条件比較66は11/04の保存済み値で、11/05の新規実績や最新の独立再ハッシュではない。学習版の前向き優位性は未証明。停止条件・同時writer制限・権限範囲を緩めず、trigger更新、rerun、cancel、workflow/モデル/タスク追加、課金、main統合、公開、本番自動切替、実投票は実施せず。

---

# 2026-11-05 03:32 JST｜当日P0ゲートの独立再点検（前日値から実績増加なし）

既存Draft PR #71・workflow 405276784に限定。点検時PR HEAD `2d898448ec11358f4cc729cba649e2e4621123da`。GitHub Actions全workflowの新しい100 runと前日以降の作成時刻を照合し、11/05 00:00 JST以降に作成された8 runは既存のviewer/オートの**合成・オフラインCIのみ**で、対象workflowの当日runも当日初回P0 artifactも0。対象workflowの最新完了run `41842464812` は前日実行の `completed/success`、その第21巡回の予想/結果/継続artifact以降に新しい実レース原本が増えた証拠はない。GitHub Actions APIの `in_progress/queued/pending/waiting` は全workflow合計各0。

11/05の `docs/evidence/2026-11-05/p0-first-receipt.json` は引き続き404。本人専用Driveの既存フォルダを直接列挙し10件を確認したが、11/05用の初回P0に該当する新規保存物は0（既存10件を削除/改変せず）。この点検範囲では当日の独立初回原本を発見できなかった。ただし、他の未連携保管先まで不存在と証明したものではなく、索引欠落だけから再生成していない。

前日最終原本から、予想artifact `13336307604`（ZIP SHA256 `119ee2a394acbaf1f15f1c92ca61b3ad96c80d53800cbf2c2468acf808f3762a`）、結果/PDCA `13335717741`（`e6653f0fc545eead623eb0822c728d56d9a8ce1d364368a165822995d655a636`）、継続 `13335757993`（`64b8e3791d0ef8b94188733b290bc1f31a94e7bc0f695dedff638db3eb015242`）の3ZIPを**今回独立再ダウンロード**、実バイトSHA256=GitHub API digestかつZIP破損なしを確認。内部 `status.json` は2026-11-04 23:58:10 JST・第21巡回、基準570予想/通常採点489（HIT139/MISS350）、学習版70、同条件比較66行、公式結果履歴505。これらは**11/04の保存済み値**であり11/05の予想・採点ではない。学習版の前向き優越性なし。

現行 `scripts/github_existing_cycle.py` の初回索引必須ゲートは未変更で、当日P0初回原本の独立保全と索引が成立するまでは起動しても `FIRST_RECEIPT_REGISTRY_MISSING_NO_BLIND_REGENERATION` で停止する。実公式入力/初回原本/外部読戻し/索引登録の完全な一巡は**未完了**。安全な初回P0手順が成立するまで、後続トリガー・rerun・キャンセル・別workflowは追加しない。取得上限・日付停止・本番切替禁止を維持。予想/通常採点/研究比較の**増分0**につき外部通知不要。全16系統・全4競技全レース、期限なし自動保管、学習版優位性は未達。新タスク/PR/モデル系統/課金/main統合/投票なし。

---

# 2026-11-05 02:15 JST｜当日初回P0受領証拠未確認、予想起動を保留（前日原本再監査）

既存Draft PR #71、branch `feat/four-sport-forecast-audit-view-20261022`。監査開始HEAD `3c72b2dadc040bf43bf4a9efc1478907d7523827`、状態文書の変更前blob `dae902829321a49383d228e2e4841aa57ae4740c`。2026-11-05 02:11～02:15 JSTにGitHubの実状態と独立保存ZIPを再取得して確認した。

- 既存workflow `405276784` の最新対象run `41842464812` は2026-11-05 00:00 JST頃に `completed/success`。第21巡回の予想ZIP `13336307604`、結果/PDCA ZIP `13335717741`、継続ZIP `13335757993` は実バイトSHA256とGitHub登録digestがそれぞれ `119ee2a394acbaf1f15f1c92ca61b3ad96c80d53800cbf2c2468acf808f3762a` / `e6653f0fc545eead623eb0822c728d56d9a8ce1d364368a165822995d655a636` / `64b8e3791d0ef8b94188733b290bc1f31a94e7bc0f695dedff638db3eb015242` で一致、ZIP破損なし。結果内 `status.json` は `round_no=21`、更新時点2026-11-04 23:58:10 JST。前日基準570予想・通常採点489（HIT139/MISS350）、研究学習版70・同条件比較66行、公式結果履歴505。第21巡回の `completed_round=20` を第21巡回全工程の独立完走と取り違えない。
- 11月5日0時以降に作成されたActions runを確認した範囲では、この対象workflowの新runは0。GitHub Actionsの `status=in_progress/queued/pending/waiting` の各API結果も全workflow合計0であり、同一writerの後続待機なし。11月5日用 `docs/evidence/2026-11-05/p0-first-receipt.json` は存在を確認できない（GitHub contents API 404）。ただし、**索引不在だけで初回原本が存在しないと断定しない**。同日runや外部一次受領の照合が揃う前に既存P0原本を再生成しない。
- 現行 `scripts/github_existing_cycle.py` の `original(day)` は当日初回索引を必須としており、欠落時は `FIRST_RECEIPT_REGISTRY_MISSING_NO_BLIND_REGENERATION` で停止する。したがって11月5日の初回原本作成・独立保存・読戻し・索引照合が終わる前に既存トリガーだけpushしても、予想成功ではなく初期復元の失敗になる。**今回はトリガーを更新しない**。当日の展示後予想・当日の通常採点を実行したとは主張しない。
- 次の安全な完了条件は、11月5日分の同日全run・初回原本の独立索引を照合し、真に不在かつ実入力が入手できる場合に限り既存P0手順で作成→外部不変保存→元ZIP/SHA/サーバー時刻の読戻し→初回索引登録。その後、既存同一workflow・同一concurrency・writer単独でP1→別イベント公式結果→PDCA→研究係数学習と未来比較へ進む。日付境界、240 GET/セッション、45 GET/巡回、3レース/巡回、締切210秒、4xx/429/真正性停止条件は維持。
- 前日570/489/70/66から**増分なし**。5基準モデルの予想・係数は不変で、研究係数学習の前向き優位性未証明。新task/PR/workflow/モデル系統/頻度/追加課金/main統合/公開/実投票/本番自動切替なし。

---

# 2026-11-05 01:11 JST｜前日3原本ZIPを所有者限定Driveへ保全・独立再取得照合

既存run `41842464812` の2026-11-04最終監査に追加した保全証拠。非公開Google Drive `RACE-AI_予想原本保管` のフォルダ・rootのownerが同一、フォルダとアップロード後の各ファイルが `shared=false`、ファイル単独のpermissionはownerのみ、正しい親フォルダであることをAPIで確認した。既存7ファイルには上書きせず、次の元GitHub artifact ZIPを**無改変のまま3件新規保存**。各ファイルをDriveから独立ダウンロードし、実バイトSHA256=元GitHub API digestが3件とも一致した。

| 保存対象 | 元artifact ID | 無改変ZIP SHA256 | Drive読戻し |
| --- | ---: | --- | --- |
| 当日復元・原本索引continuity | 13335757993 | `64b8e3791d0ef8b94188733b290bc1f31a94e7bc0f695dedff638db3eb015242` | 一致 |
| 第21巡回の結果/PDCA | 13335717741 | `e6653f0fc545eead623eb0822c728d56d9a8ce1d364368a165822995d655a636` | 一致 |
| 第21巡回の展示後予想 | 13336307604 | `119ee2a394acbaf1f15f1c92ca61b3ad96c80d53800cbf2c2468acf808f3762a` | 一致 |

最初のDrive upload APIではfile_uri形式エラー、続くFiles経由のcontainer_pathではcontainer_session_expiredだったが、別にダウンロード済みの厳密なsource_file_refをFiles経由で指定することで3件とも成功。下記01:08時点の「当日Drive保存0件」はその時点の事実であり、**本追記時点では3件保存済み**。公開GitHubに私有DriveのID・URL・認証情報は載せない。3件の保存は今回対象の原本保全進捗であり、全日全巡回・全4競技の永久自動保存が完成したという主張ではない。

予想・通常採点・学習版の成績に変更なし（基準570、通常489、LEARNED_SHADOW70、同条件比較66モデル別行）。後続runのqueued/pending/waitingを完全に列挙できていないため追加triggerなし。新PR/task/workflow/モデル/頻度/課金/main統合/実投票/自動本番切替なし。

---

# 2026-11-05 01:08 JST｜前日runの正常終了と継続原本を独立確認（採点・予想増分なし）

既存Draft PR #71 / workflow405276784 / run `41842464812`。2026-11-05 01:08 JSTに既存runのjob `126617327153` が `completed/success` であることをGitHub接続で確認。第21巡回の予想artifact `13336307604`（2026-11-04 23:58:02 JST、ZIP SHA256 `119ee2a394acbaf1f15f1c92ca61b3ad96c80d53800cbf2c2468acf808f3762a`）、結果/PDCA artifact `13335717741`（23:58:11 JST、SHA256 `e6653f0fc545eead623eb0822c728d56d9a8ce1d364368a165822995d655a636`）、最終継続artifact `13335757993`（2026-11-05 00:00:20 JST、SHA256 `64b8e3791d0ef8b94188733b290bc1f31a94e7bc0f695dedff638db3eb015242`）を無改変取得し、実バイトSHA256とGitHub API digestが3件一致。結果ZIPに埋込まれた予想ZIPも同一バイト。continuity.jsonの `complete=true`、rows=570、公式結果観測=505、LEARNED_SHADOW=70、同日走査run=23を確認。

**前回23:58保存値から正式予想・採点・学習比較の増分なし。** status.jsonはround_no=21、updated_at=2026-11-04T23:58:10 JST、基準予想570（P0=288/P1=282）、通常採点489（HIT139/MISS350）、結果未通常81、LEARNED_SHADOW70、通常同条件比較66モデル別行／33レース。係数学習122レース（train92/validation30）、元/学習版の同条件優越なし。モデル5系統の本番係数と元予想変更なし。coverageは144レース締切済、P1五モデル完全保存48レース、不足438モデル別行。これは当時の展示公開有無まで実証した取りこぼし数ではない。

公式GETは保存時199/240。状態上 `prepared_round=21`、`completed_round=20`、`halted_reason=null` であり、job全体のsuccessと第21巡回の継続レシート完成を同義としない。round22～24のActions stepはsuccess表示でも新規保存artifactは確認されず、新予想や採点の成功には換算しない。日付境界 `stop_at=2026-11-05 00:00 JST` を保ち、翌日への強制継続・GET上限の回避なし。

非公開Google Drive保存先はフォルダ `shared=false`、rootと同じownerであることをメタデータから確認したが、GitHubダウンロード参照をDrive upload APIに渡す処理はconnectorの入力形式不整合で失敗。**2026-11-04当日原本のDrive新規保存・読戻しSHAは0件で、恒久保全完成ではない。** 公開GitHubへ個人保存先のURL/ID/認証情報を記載していない。同workflowのactive/queued/pending/waitingを全runにわたり列挙するAPIが本接続にないので、後続不在を断定せず新規trigger更新・rerun・cancelはなし。既存workflow/task/schedule/モデル系統/PR/課金/main統合/公開/実投票/本番自動採用も変更なし。

未達は全16系統・全4競技の実ライブ全対象予想、全対象展示後保存、期限なし所有者限定保存、学習版の前向き統計的優位性。

---

# 2026-11-04 23:58 JST｜既存run第21巡回の保存原本監査（正式採点増加なし）

対象は既存Draft PR #71 / branch `feat/four-sport-forecast-audit-view-20261022` / workflow `405276784`、run `41842464812`。監査開始時のPR HEAD `e4c4cf5e100dfdb42121d13cb312320bf710a7d7`。第21巡回の予想artifact `13336307604`（23:58:02 JST、元ZIP SHA256 `119ee2a394acbaf1f15f1c92ca61b3ad96c80d53800cbf2c2468acf808f3762a`）と結果/PDCA artifact `13335717741`（23:58:11 JST、元ZIP SHA256 `e6653f0fc545eead623eb0822c728d56d9a8ce1d364368a165822995d655a636`）を無改変ダウンロードし、それぞれGitHub API digestとの一致を確認。結果ZIPに埋め込まれた予想ZIPとも実バイトSHA256が一致。内部status.json `round_no=21`、`updated_at=2026-11-04T14:58:10.175004+00:00`。`completed_round=20`のため、第21巡回の全step完走やworkflow終了とは区別する。確認時にjobは`in_progress`。

22:58 JSTの既存第1巡回→23:58 JST第21巡回で、基準予想 **570→570（増減0、P0=288/P1=282）**、通常採点 **489→489（増減0、HIT139/MISS350）**、学習版保存予想 **70→70**、同条件比較 **66→66行／33レース**、学習対象 **122→122レース（train92/validation30）**。学習版の未来精度改善は未証明、元5基準モデル/過去予想/本番係数への変更なし。

独立保存の公式結果観測履歴は **501→505（+4履歴行）**。第20巡回の原本との追記差分4件は `20261104-06-07`、`20261104-17-08`、`20261104-17-10`、`20261104-15-10`。いずれもデータの`confirmed=false`のため新しい通常採点へ加算せず、異常/返還/未確認をMISSに変換しない。内訳はRESULT_PENDING4、異常35、返還確認18、RESULT_REJECTED24。原本内forecasts.csv=570行、model_coverage=570件、external_research_summary=2研究件を照合し、正式採点に混ぜない。

`coverage_audit`は当日144レースが全締切済み、5モデルP1完全保存48レース、未保存438モデル別件（当時展示が公表済みかは未検証）。公式GET session値199/240、開始当初の180秒間隔・24巡/65分・日付境界停止は維持。`stop_at=2026-11-05T00:00:00+09:00`を確認。queued/pending/waitingの全runを列挙する権限付きAPIが本接続に無く、後続不在とは断定しない。run実行中のため新しいトリガーpush、rerun、cancelは行わない。上限/日付変更の回避もしない。

未達は4競技×全16モデルの全レース実運転、P1全件事前保存、期限なし本人専用保管、学習版の前向き統計的優位性。新タスク/頻度/別workflow/新PR/新モデル/Cloudflare/Vercel/課金/main統合/公開/投票/本番自動切替なし。

---

# 2026-11-04 23:02 JST — 全16モデルの私有保存・画面接続と原本比較を追加（実原本0件、製品全体は未完成）

オーナーの4項目（実JSON接続、4競技×全レース×適用全モデル、実機Safari、前向き改善比較）の継続指示に従い、既存PR71で不足していたローカル保存/画面/評価経路を実装した。環境設定の下書き保存と実行環境への適用を区別し、実入力を得ていない部分は完成と報告しない。

| 項目 | 実装・検証済み | 残る条件 |
| --- | --- | --- |
| 実JSON取得・接続 | 既存capture→restore→viewを維持。Library/shared/downloads/22参照を再探索、実バイト未接続。原本の保存先/IDは特定済み | **この環境の実読戻し0件**。api.github.com許可は下書きのみ、実行環境はenforced/revision1/custom hosts空。設定適用とLibrary原本接続が必要 |
| 全レース×適用全モデル | 既存SQLiteへ版/競技/段階別の追加保存表。全16native出力を保存・読戻し・画面へ渡す経路を追加。元SHA/順位/整数キーを保持、再起動/同時実行でも元原本を再生成しない | **4競技のライブ全対象運転は未達**。本来の実入力/学習物/利用条件/締切前外部保存/結果照合/恒久私有保管が未接続 |
| スマホ・PC/Safari | Chromiumの4幅で31操作グループ/48PNG。全16系統、試走前/後、5点プラン、未予想/未取得を操作確認 | **実機Safariは未接続・未受入**。ChromiumをSafari実機試験と呼ばない |
| 精度改善の前向き比較 | BOAT保存済み元/学習版の同条件比較APIを追加。全宣言台帳と未予想を保持、結果観測・学習物を結び、再学習/再予想しない | **改善実証は未達**。公式率はnull、独立検証/改善認定/自動本番採用はfalse。別writerの22:58監査も元/学習版11/33、10/33で同数 |
| 回帰と独立レビュー | **Python724件、Node175件、失敗/skip0**。認可scope迂回、異常着順、段階分母と5点の誤表示等を再現・修正・再レビュー | コード `eefc57a9e73e3270d4d50d48e1a08729868d88e5` を既存PR71へ通常pushしheadSha一致。viewer41844165883/AUTORACE41844165868はcompleted/success。後続の証拠文書commit自身のCIとは区別する |

[コードHEADのCI照合](evidence/2026-11-04/continued-operation/ci-verification.json) / [接続APIと限界](PRIVATE_OPERATION_AND_COMPARISON.md) / [テスト・失敗修正・48画面](evidence/2026-11-04/continued-operation/EVIDENCE.md)。派生画面のnative予想SHA欠測は未取得のまま、出力本文SHA/モデル学習物SHAとは区別する。オート試走段階をP0/P1へ改名せず、宣言された未予想段階を分母から消さない。Sellerは保存5点プランとして表示する。

同時writerの21cce5b→7bbafee/bb654bb/459e919/00232b7をfast-forwardで保全。JRA入力ゲート6試験も含め全Pythonを再実行済み。別writerの最新監査は既存run41842464812第1巡回570基準予想/通常489採点という記録で、今回この環境でZIPを再集計した値ではない。こちらから巡回起動/取消/再実行/provider GETは0。

外部操作：環境設定への通信許可適用（ツールは下書き保存のみ）、所有者Libraryの認可済み読取経路、実機Safariの操作可能な接続が必要。秘密値のチャット入力は不要。ユーザーの画像で確認できた「クラウドコンピューター」メニューからRACE-AI環境を開く案内を行い、画面上の適用操作を確認中。

新PR/Issue/開発タスク/workflow/schedule/モデル系統/Cloudflare/Vercel/追加課金/一般公開/実投票/main統合/本番モデル切替なし。mainは0e45c029e18d5f3f1e7a04aecedab3c4af261748のまま。全体完成と実測改善の宣言は行わない。

---

# 2026-11-04 22:58 JST｜新run第1巡回の予想・結果ZIP保存照合、通常採点+9（すべてMISS）

既存Draft PR #71 / workflow `405276784` / run `41842464812`。確認時のPR HEAD `459e9198d8714619acda49c6c412682fcf6479c3`、既存job `126617327153` は `in_progress`。新runの第1巡回では予想artifact `13328164756` (GitHub保存22:57:51 JST)、結果/PDCA artifact `13328349570` (22:58:10 JST) を確認。両ZIPを無改変取得して実バイトSHA256を計算し、API digestに一致（予想 `148df6fdaef0d118359407a8c6fa8a930c55f49c2e29d73bc4561b672f031369`、結果 `53a437948d38ef96afe800902f6a42a6ef403a55f8af52265c5593e41df00351`）。内部status.jsonは `round_no=1` / `updated_at=2026-11-04T13:58:08.974194+00:00`。continuity相当の `completed_round=0` なので**第1巡回全stepが完走したとは扱わず、保存済み成果だけ計上**。この時間以降の未完了巡回は加算しない。

22:15旧run最終原本→22:58新run第1巡回の差分：基準5モデル予想**570→570（+0）**、通常結果採点**480→489（+9）**、HIT139→139（+0）/MISS341→350（+9）。新たな通常採点は同日 `20261104-19-11` のP0 2系統＋P1 5系統=7件、および `20261104-19-12` のP0 2系統=2件。公式結果観測履歴に元source SHA、観測時刻、6艇ID照合を保持し、両レースの3連単結果1-2-4（100円1550円）/1-5-3（同1890円）をそれぞれ保存した。9予想すべてMISSで、同じレースのP0/P1とモデル別予想を異なるレース数に水増ししない。通常外はRESULT_PENDING4、異常35、返還確認18、RESULT_REJECTED24、合計570。result observation history 426→442、forecasts.csv 570行、model_coverage計570、external_research_summary 2件を確認。

係数学習入力は**120→122異なるレース（train90→92/validation30維持）**、学習版LEARNED_SHADOWは70予想のまま。同条件の研究比較は**64→66モデル別行、32→33レース**。観測相性は元/学習版11/33対11/33的中、ST重視相性は10/33対10/33。両系統とも今回までの仮払戻額は元/学習版同額で、**前向き精度改善は未証明**。元5基準モデルを変更せず、研究版の自動本番採用なし。

`coverage_audit` は対象144、締切済み144、未来0、展示後P1の5モデル揃い**47→48**、不足**433→438モデル別行**（締切済み分母が2レース増加したため増減を単純な取得可能取りこぼしとは呼ばない）。当時の展示公表有無は未確認。結果改訂は別revisionを保全、非通常結果をMISSに変換しない。新runはin_progressのため、既存後続トリガーを追加せず、並走writer・同run rerun・上限回避・新PR/新task/新workflow/頻度変更・Cloudflare/Vercel/課金/main統合/公開/実投票は行っていない。全16系統・全4競技ライブ全レース、期限なしowner-only保管、学習版の統計的優位性は未達。

---

# 2026-11-04 22:55 JST｜旧run第21巡回の実ZIP監査・結果照合継続の新runは起動中

既存PR #71 / workflow405276784 の旧run `41827144792` は **22:15:45 JST completed/success**。全artifact一覧から最新予想 `boat-national-cutoff-41827144792-cycle-21` (ID13328005191)、結果/PDCA `race-existing-cycle-41827144792-cycle-21` (ID13327145474)、継続 `race-cycle-continuity-41827144792` (ID13327140572)を選択。3件の元ZIPを独立ダウンロードし、実バイトSHA256=GitHub API digest一致（予想 `a3d74cb858738f61591802b33847cfc450528c958008334c30dcf565a08f5e1f`、結果 `589b6268e026a73e29ada5a9a8be3a36754d4fb0b24e417ebe4ddfca0b704782`、継続 `b20ee679fd16418f5f22819e8614136b282acd9cbc6598a34c85f3a0140ebff6`）。内部status.json `round_no=21` / `updated_at=2026-11-04T13:15:24.760110Z` と forecasts.csv 570行、model_coverage 570行、公式結果観測履歴426件、研究manifest2件を検査。continuityの `completed_round=20` のため第21巡回の全step完了と同義にはせず、workflow全体のsuccessと区別。

21:48保存値から**基準5モデル予想565→570（+5、P0=288維持/P1=277→282）**。新規5件は同一 `20261104-19-11`、締切22:20 JSTに対し22:03:23 JST保存。通常採点は**480件のまま（HIT139/MISS341）**、結果待ち13、異常35、返還レビュー18、RESULT_REJECTED24。別系統LEARNED_SHADOWは68→70（+2）、正式採点とは分離した同条件比較64モデル別行/32レースは増減なし。学習入力120種類のレース（学習90/未使用検証30）、予測精度優位性は未証明。学習5基準モデルの買い目・旧原本・本番係数は変更なし。最終保存時点の対象144レース、締切済み142、未来2、5基準モデルP1が揃った47レース、P1不足433モデル別件。残り2レースの締切22:20/22:45はこの監査時点では経過済みだが、当時展示の取得可能性や締切前の追加予想成功を推定しない。

旧runのセッションは公式GET240/240、source失敗7件が `SESSION_SOURCE_BUDGET_EXHAUSTED`。4xx/429や真正性不一致の証拠としては扱わない。新run起動前にPR HEAD/trigger SHA/同workflow全runの状態を再取得し、active/queued/pending/waitingなしと原本のSHA一致を確認。未照合通常結果13モデル別行のため既存triggerを**1回だけ**更新、commit `bb654bb44e605fecb74b44f4875ffdf9c9e1d4b5` → 同一workflowの新run `41842464812` が22:55 JST **in_progress**。新runの予想・採点artifactはこの記録では未確認、旧run成績へ合算しない。同一concurrency/既存上限/停止規則・新タスクなし。後続起動は追加しない。

未完成：全16系統×全4競技の直前凍結予想、P1全レース網羅、期限なし本人専用保存、学習版の前向き統計的優越。研究原本2件を正式成績へ昇格しない。Cloudflare/Vercel、課金、新PR/別workflow/main統合/本番自動採用/実投票なし。GitHub artifact保持7日は永久保存ではない。

---

# 2026-11-04 21:48:16 JST | run41827144792 round12 保存ZIPの独立照合（21:51 JST確認）

既存Draft PR #71、workflow405276784、run `41827144792` は確認時点で既存job `126564664035` がin_progress。PR HEAD `60fdb7140de2d4249749166798e0f531a7090684`、当該実行のコードSHA `9781164aa6eaa0ab9526df8f210d2517510b1079` を混同しない。実際のJSTで本チェックポイントを調べ、予想artifact `13323550835`・結果/PDCA artifact `13322934681` をGitHubから無改変ダウンロード。各実ZIPのSHA256は登録digest `049721dc98c33a5def8bd01fba602c35f7ca21af813aceba09a3481cbeeebc42` / `0c773a6a457b6ca45e764f45a78b61897f410fdec7e7195bf9bfaa8209ae990f` と一致。結果ZIP内の `current-p1-original.zip` は取得した予想ZIPと同一バイト。status.jsonの `round_no=12`、`updated_at=2026-11-04T12:48:16.793379+00:00`、forecasts.csv 565行、model_coverage 565件、公式結果観測履歴384件、外部研究manifest2件を読んだ。**ZIP保存・独立SHA照合は確認、同ZIP内continuityの `completed_round=11` のため第12巡回全stepの完走までは未確定。**

21:19の保存済み第2巡回565件・通常採点473件から、この21:48保存原本は**基準565件（増減0、P0=288/P1=277）、通常採点480件（+7）、HIT139（+0）/MISS341（+7）**。現存結果待ち8、異常35、返還確認18、結果拒否24は不的中に入れない。対象144レース、締切済み141、未来3、5モデルP1保存済み47レース、P1不足428モデル別件。展示の当時公開可否を未検証のまま「取得可能だった取りこぼし」とは断定しない。

LEARNED_SHADOWは68保存予想（前回から変化なし）、同条件通常採点は62→64モデル別行、異なる31→32レース。観測相性は基準/学習版とも11/32的中、ST重視相性は双方10/32的中、各系統の仮受取も同額。係数学習の採用元は120レース（学習90、未使用検証30）で、21:19記録の119レースから+1は検証側。特徴の未観測分は学習済みと扱わない。係数更新や過去holdoutを未来優位性の証明にしない。元5モデル・既存予想・正式採用は変更なし。

session内の公式GETは保存値146/240、`halted_reason=null`、通常180秒/最大24巡・公式GET上限を維持。runがin_progressのため新規起動なし。**同workflowのqueued/pending/waiting全runを列挙できるAPIが本接続に無いため、後続なしとは断定せず追加triggerは禁止。** 結果の改訂履歴・返還区分・元SHAは保全。全16モデル×4競技の実ライブ、全対象の展示後予想、無期限owner-only保存、学習版の統計的優位性は未完成。新タスク/新PR/別workflow/頻度変更/モデル系統/Cloudflare/Vercel/課金/main統合/投票なし。

---

# 2026-11-04 21:36 JST — 保存原本JSONから画面までの接続を実装・CI成功（実読戻し0件）

既存Draft PR71の同じブランチで、選択した保存原本artifactの取得 → SHA固定ローカル復元 → 画面用投影 → 操作画面読込を追加した。P0/展示後P1/保存済み学習版のTop8・全順位・native SHAを保持し、存在しないモデル版/生成時刻/入力SHAは未取得のまま。結果の取得観測時刻を公式確定時刻や改訂番号へ置き換えない。専用viewは研究/合成表示で、正式Hit@8/回収率へ加算しない。

| 完成条件 | 今回の状態 |
| --- | --- |
| 原本取得・ローカル復元・画面へのコード接続 | 実装済み。元ZIP/metadataを別の私有領域へ排他的に保存、元原本は変更しない。予想/学習/採点を再実行せず表示 |
| 操作画面と合成結合試験 | 合格。2レース14保存予想、P0/P1、2学習版、2結果観測。4幅29操作グループ、36PNG、外部provider GET0 |
| 回帰・独立レビュー | Python661件/Node169件、失敗・skip0。保存先差し替え・日付/取得時刻矛盾等を修正し再確認済み |
| 私有実JSONの接続 | **この環境では0件**。GitHub原本の保存先/IDとLibraryの旧保存記録は特定。api.github.com許可は環境下書きのみで、実行中環境に未適用。Library実バイト未接続 |
| 全レース×既存全モデル、4競技継続実運転 | **未達**。既存16系統オフライン実行層と不足検出は維持。別writerが21:19に記録したBOAT既存runの565基準予想/P1=277はその監査記録の値であり、この環境での今回再集計や全16/全4競技実績ではない |
| 実機Safari・恒久私有保管・精度改善 | **未受入/未達/未実証**。Chromiumを実機Safariと呼ばず、合成結果や学習版の表示を精度改善へ換算しない |
| 既存PR71への反映と新HEAD CI | コードcommit `4243f2997c9cd9bc289d837600ee51c0abd6d967` を通常pushしPR headShaと一致。viewer run41830307303 / AUTORACE run41830307315はともにcompleted/success。後続の証拠文書commit自身のCIとは区別する |

[取得/復元/読込手順](PRIVATE_CYCLE_VIEW.md) / [実装・失敗修正・36画面・テスト証拠](evidence/2026-11-04/private-cycle-view/EVIDENCE.md)。今回の追加は既存viewer CI job内の試験のみ。新PR/Issue/モデル系統/workflow/schedule/課金なし。

[コードHEADのGitHub CI確認](evidence/2026-11-04/private-cycle-view/ci-verification.json)。この追記は成功確認後の証拠文書更新であり、コード変更なし。最新remoteを確認し、別writerの9781164/936144a/71054f5をfast-forwardで取り込んで保全。既存実run41827144792へこちらから追加trigger/cancel/rerunは行っていない。下記21:19は別writerによる監査更新として維持する。mainは0e45c029e18d5f3f1e7a04aecedab3c4af261748。一般公開、実投票、本番モデル切替なし。外部前提が満たされるまで製品全体の完成とは報告しない。

---

# 2026-11-04 21:19 JST｜新run第2巡回まで独立ZIP照合、予想+5・通常採点+56

既存Draft PR #71 / branch `feat/four-sport-forecast-audit-view-20261022`。GitHub最新PR HEAD確認時 `936144a2754c512f9338a03c34c2b14bb84652f7`、既存workflow 405276784のrun `41827144792` は in_progress。21:18:31 JSTまでに第2巡回の両ZIPが保存され、GitHub Actions job steps 01・02はsuccess、03は未完了。新runへは前runの原本を復元し、既存初回P0を再生成しない（既存P0保存stepはsuccess）。別workflow・別PR・新タスク/頻度・モデル系統追加なし。後続runのqueued/pending/waiting完全一覧をこの接続から取得できないため、新たなtrigger pushは禁止して見送った。

18:48:29 JSTの旧run `41801993716` 第21巡回の原本（560基準予想、417通常採点、LEARNED_SHADOW66、paired54）から、今回21:18:29 JSTの**新run第2巡回**は**565基準予想（+5、P0=288/P1=277）、473通常採点（+56）、HIT139/MISS334、LEARNED_SHADOW68（+2）、通常paired62モデル別行（+8、異なる31レース）**。新規5件は同一の `20261104-19-09` 展示後P1で、締切21:25 JSTに対し21:15:16 JST保存。5既存モデルすべての本来の買い目を保持し、当時はRESULT_PENDING。採点増分+56件は過去予想の結果確定が進んだものとして新規レースの的中に混ぜない。未確認の着順/返還/結果拒否は不的中に変換しない。通常外は結果待ち15、異常35、返還レビュー18、結果拒否24。

学習版は異なる119レースを対象とした学習90/未使用検証29、状態FITTED_SHADOW_ONLY。前向き同条件比較は2系統×31レースの62行。観測相性11/31対11/31、ST重視相性10/31対10/31で元モデル・学習版の的中は同数。双方とも同モデル内の仮払戻額は同額。改善版の前向き優位性は未実証。学習候補と元5モデル・旧予想は変更せず、自動本番採用なし。

保存確認: 新run第2巡回 予想artifact `13321225804` ZIP SHA256 `f3953a8be0bd7ccb0b804abc0d926e3489577b7774f2fe683869656ce64ac323`、結果/PDCA artifact `13320466282` ZIP SHA256 `04baba91da5a0aa0e1935b7b3f6dd7c45836d2beea1122444249d25097ac2f73`。両方を実ダウンロードしSHA256計算でGitHub登録digestと一致。結果ZIPでstatus.json `round_no=2` / `updated_at=2026-11-04T12:18:29.327606+00:00`、forecasts.csv 565行、model_coverage total565、公式結果観測履歴、改善候補、学習版、外部研究manifest2件を検査。新run第2巡回のCI workflow全体はまだ実行中であり、未完了第3巡回の成果を加算しない。現時点の対象台帳144レース、締切済み140、未来4、P1五モデル揃い46、missing model別428（当時の展示取得可能性まで確認できず単純な取得可能取りこぼし数とはしない）。

未達: 全16系統/全4競技のライブ全レース予想、全日網羅、期限なしowner-only保存、係数学習版の前向き統計的優位性。7日artifactを恒久DBと呼ばない。Cloudflare/Vercel・追加課金・main統合・一般公開・実投票・本番モデル自動切替なし。旧結果訂正や結果拒否は原本を保持する。

---

# 2026-11-04 21:12 JST — 既存boundedセッションを1件継続起動（新成果は未確認）

対象: 既存Draft PR #71 / workflow405276784 / branch `feat/four-sport-forecast-audit-view-20261022`。先行run `41801993716` は18:48:49 JSTにcompleted/success、第21巡回まで保存・読戻し完了後、公式GET計240/240で停止。旧runの再実行や上限引上げなし。予想ZIP `13311063371`、結果ZIP `13312385205`、continuity ZIP `13311801417`を各GitHubから無改変ダウンロードし、SHA256実バイトがAPI digestに一致（それぞれ `3ca3b063cbf9f409a21aaacc4870e3b493059f10c161aafb6b990f703565da90`, `3dcd04a42bd3cc1483313973f7a34dc58339f487e01522c30ea50283d869e35f`, `ea54e4d3ae0441423c52cc188a27002cde415f757ac02fcdeb18fc6ac61e3811`）。内部status.json `round_no=21`, `updated_at=2026-11-04T09:48:29.434953+00:00`, `560`基準予想、通常採点`417`、別系統LEARNED_SHADOW`66`予想・同条件比較`54`モデル別行を確認。学習入力101種類のレース（学習76/検証25）・`FITTED_SHADOW_ONLY`、精度改善の認定なし。本番採用なし。これは18:48時点の保存値であり、21時台の新予想/新採点と混同しない。

21:11 JSTの安全再確認ではworkflow405276784にactive/queued/pending/waitingの実行なし、先行runはsuccess、既存日程台帳では21時以降の未来締切と未照合結果が残っていた。既存triggerファイルのみ1回更新し、**新run `41827144792` がin_progress**。同一concurrency、cancel-in-progress=false、公式GET上限・4xx/429停止・日付/原本照合・締切210秒を維持。新runは原本復元step実行中であり、予想ZIP/結果ZIPはまだ未保存。この起動を追加予想・採点・学習済み改善の成功には換算しない。旧原本改変なし。新タスク/モデル/PR/workflow/schedule/課金/本番自動切替/公開/実投票なし。

未達: 全16モデル・全4競技の実予想、全対象直前凍結、期限なしowner-only原本保存、学習版の同条件未来優位性。GitHubの7日artifactを恒久保存と呼ばない。

---

# 2026-11-04 20:52 JST — 展示後P1対応を再確認、原本JSONの取得先を追跡

展示後版は実装済み。ボートのA/B、C-lite、観測相性2種の5系統は既存実runで締切前保存の実績がある。独立ZIP照合履歴のある18:36チェックポイントはP1=267モデル別予想/5系統全件保存43レース。最終P1総数は今回ZIP再取得できず未再集計。既存巡回は240/240で停止済み、現在も自動予想が出続けているとは言わない。新全16実行層はオフラインで対応し、全4競技/全レースのライブ供給・保存は未完成。Sellerは朝版専用で展示後版と偽らない。

今回のP1入力接続・締切・A/B/C-lite・凍結継続・オート試走後版の既存57テスト成功（50+7、失敗/skip0）。コード変更・provider GET・巡回再起動なし。別writerの92f3572/b9f7d70の結果監査メタデータはfast-forwardで取り込み保持。

JSONは、展示後BOATのnational.json（巡回別GitHub forecast artifact）と全体の原本参照を持つcontinuity.jsonまで保存先を特定。最終回だけでは全日分にならない。既知artifact13311386530を通常GitHub APIで実読取したがForbiddenで停止。api.github.com追加は環境下書きにあるが現環境へ未適用。Libraryの競輪元JSONとオート/PDCA22原本の記録パスも直接再探索したが、この環境には実バイトなし。今回は実JSONを取得できたと報告しない。

[探索箇所・原本参照・通信失敗の記録](evidence/2026-11-04/all-existing-models/PRIVATE_SOURCE_DISCOVERY.md)。次の外部前提は、保存済みapi.github.com許可を環境設定から適用して、既存認証でGitHub原本取得を再試行すること。Libraryの別環境ファイルが自動でこのクラウドに存在するとは扱わない。秘密値のチャット貼付・原本再生成・public転記・main統合なし。

---

# 2026-11-04 20:09 JST — 全レース×既存全モデルを必須として実行層・全件不足検出を追加

オーナーの追補「全レースを全モデルで予想すること」を必須条件にした。実入力のない未予想を一覧化しただけで達成扱いにしない。開始HEAD ef9e6013d89b110ee54c8ebafb137e950c2a26a7。既存Draft PR71の同じブランチのみ、新PR・新モデル系統・新workflow/task/scheduleなし。

| 項目 | 今回の結果 |
| --- | --- |
| 既存16系統の実行経路 | オフラインで既存関数へ全16系統を接続、実関数を合成入力で実行して試験。先頭1モデルだけを捨てず各出力を保持 |
| 全レース×モデル×段階/版の不足 | 実IDのscheduleから全slotを展開。対象外・入力不足・学習物不足・期限超過・選外・生成済み未受領・元原本再利用を分離 |
| 元原本の保持 | race/stage/model/version/native本文SHA/親入力を検査。保存済みを再発行しない。別モデル未保存をレース単位で省かない |
| 画面 | 取込0件でも16系統すべてを表示。競技別適用15/5/6/5、段階/版と未予想分母を保持。4幅28キャプチャ・25操作グループ成功 |
| テスト | Python618件、Node165件すべて成功、スキップ0。独立技術レビューの重大指摘を修正して再検証 |
| 私有原本の接続 | 過去Library保存記録と20オート原本の索引を特定。現環境に元バイトなし。既存PR72 SHA固定リーダーを再利用、12テスト成功。実読戻し0件 |
| 4競技実運転・全レース全モデル事前保存 | **未達**。新実行層の原本/入力/許諾/私有保存/外部freeze/resultへのライブ接続が必要。元Actions巡回は5ボート基準＋学習版のまま |
| 実機Safari・精度改善 | 未受入/未実証。Chromiumを実機Safariと呼ばず、既存係数・本番モデルを自動変更しない |
| exact-HEAD CI | この文書の時点ではローカル検証完了・push前。push後の既存CIを最終報告で確認する |

[実行層と呼出契約](ALL_EXISTING_MODEL_DISPATCH.md) / [私有保存先調査](evidence/2026-11-04/all-existing-models/PRIVATE_SOURCE_DISCOVERY.md) / [検証件数](evidence/2026-11-04/all-existing-models/validation-summary.json) / [合成dispatch証拠](evidence/2026-11-04/all-existing-models/dispatch-synthetic-proof.json)。モデルエンジンの数式や既存選別条件は変更していない。PDCAは既存純粋関数だけをNodeで呼び、Cloudflare/D1には接続しない。Seller既存の07:00以前・最大5件条件を分割/再実行で迂回せず、選外も未予想として残す。

本人Libraryにあったと記録されている競輪元JSONはkeirin_20261103_forecasts.json（58,754bytes、元whole-file SHAは調査記録参照）。現在のLibrary内容をこの接続から読む手段はなく、現在の存在確認とは区別する。GitHub暗号化履歴の実メタデータはsynthetic/gen1であり、実原本には使用していない。原本/秘密鍵/買い目/私有フルパスのpublic転記なし。実原本を本人がこの環境へ接続できれば元SHA照合で読めるが、whole-file一致を個別の締切前外部receiptに格上げしない。

取得240/240停止済みrunの再起動0、追加provider GET0、原本上書き0、receipt新造0、main統合0、一般公開0、実投票0、本番モデル切替0。既存実runの560基準行/417通常採点という別writerの記録を保存し、今回の全16/全4競技の実行件数や精度改善と混同しない。GitHub API通信許可は引き続き未適用、Issue14/68追記と最終private artifactの再取得は未完了。

---

# 2026-11-04 19:31 JST — PR71反映とGitHub CI成功を確認

検証対象HEAD `d419d8bb5d7d30fd71ce2bda449a085c8124f0c6` を既存Draft PR71へ通常pushし、PRページのheadShaとremoteを照合。Forecast audit viewer contract [run41814145631](https://github.com/haji84/RACE-AI/actions/runs/41814145631) と AUTORACE offline contract [run41814145656](https://github.com/haji84/RACE-AI/actions/runs/41814145656) はともにcompleted/success。両runページの対象commit表示d419d8bを照合した。viewer既存job内で新しい操作試験を実行し、合成証拠artifact（17.8MB、GitHub登録digest a55e5d3a8d3abd6370de2171c0c4b3b34739b357b243e8018a12f1d2aed90ee9）を確認。これはartifactの独立ZIP再ハッシュではない。artifact名のb8ab9a...はPRのGitHub merge SHAであり、明示checkoutしたhead d419d8bと取り違えない。

競合writer e587f5aの巡回監査を保持したmerge後も、web/race_ai/tests/.githubはローカル全件成功時6dbb896と完全一致。以下の19:22の「未push」は当時の状態で、現在は反映済み。今回の追記は証拠文書のみの後続commitになるため、このrunを後続文書commit自身のCIと偽らない。新HEADの確認は最終報告に記す。

実原本接続0件、実機Safari、全4競技の実運転・恒久私有保管・前向き精度改善は依然未達。Issue14/68コメントはAPI接続制限で未送信。mainは0e45c029e18d5f3f1e7a04aecedab3c4af261748のまま。一般公開・投票・本番モデル切替なし。

---

# 2026-11-04 19:22 JST — 既存PR71へ操作UIを統合（ローカル検証済み／製品最終GOAL未達）

正式指示書全文・Issue14/67/68・PR62/71を読み、添付8枚を実際に目視比較した。開始HEAD c15e683d520ba248526800c8a35c161735a2d565、main 0e45c029e18d5f3f1e7a04aecedab3c4af261748。既存PR71の同じブランチで作業し、新PR・Issue・workflow・巡回タスク・モデル系統は作っていない。

| 合格条件 | 今回の結果 |
| --- | --- |
| スマホ/PCの8対応画面と7ページ操作 | ローカルChromiumで合格。320/390/1440/1920、28PNG、25操作グループ、外部ソースGET0 |
| 原本読込・段階/モデル・結果改訂を分離 | 合成と既存エンジン保存出力で合格。元SHA保持、返還/欠測/取込申告を区別。私有実原本の読戻しは未接続 |
| 回帰・レビュー | Python563件、Node161件すべて成功、スキップ0。独立技術レビューの重大指摘は修正・再検証済み |
| GitHub exact-HEAD CI | この記録時点では新コード未push。以後の実行は別記。初期CI41809839240はSuccess/c15e683をWebページで確認 |
| 実開催全対象・継続運転・4競技供給・永久私有保管 | 未達。UI成功とは別条件 |
| 前向き精度向上・98%・実機iPhone Safari | 未達/未受入。実測改善・校正済み確率・実購入回収率を捏造しない |

変更：web/index.html/style.css/app.js/ui-model.js（PR62を再利用）、web/product-data.js（読取専用adapter）、race_ai/audit_projection.py（既存保存ランキング/SHAと全結果改訂を保持）、関連テスト。既存forecast-audit画面と予想/学習エンジンは維持。既存viewer CIの同じjob内だけに試験を追加。参照PR64/72の無関係な実装や外部配備設定は移植していない。

[実装・画面・失敗修正・検証証拠](evidence/2026-11-04/product-ui/UI_EVIDENCE.md) / [起動・読込手順](PRODUCT_UI_LOCAL_USAGE.md) / [実装計画と再利用差分](superpowers/plans/2026-11-04-product-ui-integration.md)。28画面とテストログを合成ラベル付きで保存。読込値のreceiptピン検査は独立署名認証ではなく、そう表示しない。モデル/版/段階を混ぜた正式率を出さず、未予想を段階分母から除かない。候補確定・手動購入・取込購入は別台帳。予想/購入明細はブラウザへ自動保存/外部送信しない。

既存巡回run41801993716はWebでcompleted/success（1h3m4s）を確認。以下に残す18:38時点のin_progressは当時の記録であり現在の状態ではない。このセッションの最終artifact再取得はAPI制限で未実施。push直前に別writerのe587f5aff8bf6e951b08a313896293438ef3de11を検出して保全・統合した。下記19:18の別作業記録は最終第21巡回・560基準予想・417通常採点・240/240上限停止を報告している（このセッションのZIP独立再ハッシュではない）。学習版最終成績は未再計算。旧checkpointの64学習shadow/52モデル比較行（26レース）、元/学習版とも17的中・仮受取32,100円という記録を最新値や改善達成へ読み替えない。今回live取得・巡回再起動・上限変更は0。

外部条件：現環境のGitHub APIはForbidden。Issue14/68への追記と最新artifact読取は未実施。api.github.comの通信先追加を環境設定下書きに保存しただけで未適用。私有の実予想/結果ファイルは未マウント（今回の実原本import0件）。必要なのは権限のある投影/owner読取経路と実機受入であり、チャットへの秘密鍵貼付ではない。main統合、一般公開、Cloudflare/Vercel、課金、実投票、本番モデル切替はいずれも行っていない。

---

# RACE-AI 現在地・実行結果の確認先

## 2026-11-04 19:18 JST｜最終第21巡回まで実行ログ・artifact登録を照合

対象：既存Draft PR #71 / workflow 405276784 / run `41801993716`。2026-11-04 19:18 JSTにPR HEAD `c15e683d520ba248526800c8a35c161735a2d565`、同workflowの直近実行、GitHub Actions jobログと全artifact一覧を再確認。対象run自体の実行HEADは `8dc4e482e02c332fa54fc38129946cc90871f355`。当該runは18:48:49 JSTに `completed/success`。最後に実際に保存・読戻しまで完了したのは**第21巡回**（18:48:38 JST）。第22〜24巡回は `SESSION_SOURCE_BUDGET_EXHAUSTED` で実予想・照合なし。セッション取得240/240。正常終了を全24巡の実施と読み替えない。

**最新のrunログ確定値：** 基準5モデル予想 **560モデル別行**（前回18:38文書の555から+5、異なる対象レースは144）、通常結果採点 **417モデル別行**（410から+7）。第18巡回で1レース×5モデルを追加、第19〜21巡回で新規予想なし。第21巡回の予想操作は `OBSERVED_ATTEMPT_NO_FORECAST / NO_COMPLETE_EXHIBITION_IN_ORDERED_CANDIDATES` で、空の試行を予想成功に算入していない。通常採点増加は新規予想の的中とは別事象。最新学習版の予想数・前向き比較成績は、この監査では最終ZIP内部を独立展開できず**未再計算**。以前の64研究予想・52比較行を最新値として再宣言しない。自動本番採用なし。

最終の予想artifact `13311063371`（ZIP SHA256/GitHub digest `3ca3b063cbf9f409a21aaacc4870e3b493059f10c161aafb6b990f703565da90`）と結果・PDCA artifact `13312385205`（同 `3dcd04a42bd3cc1483313973f7a34dc58339f487e01522c30ea50283d869e35f`）をAPI一覧と実行ログのアップロードdigestで照合。run内の `repeat-complete` は `ROUND_SAVED_AND_READBACK_VERIFIED`（第21巡回・560予想・417通常採点・240取得）を記録。コネクタからZIP取得はしたが今回の実行環境でローカルZIP展開/実バイト再ハッシュがエラーとなり、**今回の別環境独立再ハッシュ成功とは言わない**。run内読戻しとGitHub API登録digest照合を確認した範囲に限定する。

同workflowの最新30 run一覧に当該runより新しい実行・in_progress/queuedは見当たらなかったが、**終了理由が公式GET上限到達**のため、取得上限を回避する即時再トリガーは行っていない。既存周期・concurrency・データ取得上限・原本停止規則を維持。新PR、新モデル、新workflow、追加課金、公開、main統合、実投票、モデル自動採用なし。期限なしowner-only原本保全・全16系統/全4競技実接続・学習版未来優位性は引き続き未達。

## 2026-11-04 18:38 JST｜反復run第17巡回の予想・結果ZIPを独立照合（実行は継続中）

対象：既存Draft PR #71 / `feat/four-sport-forecast-audit-view-20261022`。確認時HEAD `399d712d1405ecf70bb0f002eb40382b7a8d0cdd`。既存workflow 405276784 / run `41801993716` のジョブは確認時 `in_progress`。第17巡回の予想artifact `13311386530` (ZIP SHA256 `9838c0ee57a2eb9024d2e1e664d1f60b909ca3bfc5b503137b0343dc8202e183`) と公式結果・PDCA artifact `13311232967` (ZIP SHA256 `08d36821ab53e824aa6600739e3f5914f111a8a648a80afcdaa60737d450e80c`) を個別ダウンロードし、実ZIPバイトをSHA256計算してGitHub API digestと一致。結果ZIP内部の `status.json` / `forecasts.csv` は双方555行、`round_no=17`、集計時刻18:36:35 JST。保存済み第17巡回の証拠であり、次の未完了巡回は加算しない。状態ZIP内のsession `completed_round=16` は第17巡回の読戻し前に記録された値で、別途第17巡回の両artifactがGitHubに保存済みなのを確認した。

17:49 JST文書チェックポイント（525基準予想・378通常採点・学習版52・前向き同条件44行）からの差分：**基準予想555（+30、6レース×5モデル）、通常採点410（+32）、LEARNED_SHADOW64（+12）、同条件採点52モデル別行（+8）**。基準内訳はP0 288 / P1 267。通常採点HIT121/MISS289で410。非通常は結果待ち72、異常着順33、返還確認16、結果拒否24。通常410＋非通常145＝555。通常採点の+32件は今回追加予想+30件が直ちに的中した意味ではない。144レースが対象台帳であり555はモデル別予想数。

学習版の通常同条件比較は異なる26レース・2系統52行。基準/学習版とも各17的中、仮払戻合計各32,100円で今回も改善差なし。自動係数学習は異なる100レース（学習75・未使用検証25）で`FITTED_SHADOW_ONLY`。本番モデルの係数・過去予想は変更せず、精度改善/優越性を証明した扱いにしない。締切済み121レース、展示後5モデルが揃った43レース、未保存のモデル別P1は348行（当時の展示取得可能性は別途要検証）。実run取得予算は220/240、停止理由なし。公式取得失敗記録1件は予想成功・外れに換算していない。

後続の`queued/pending/waiting`全件の一覧取得はこの接続で検証できていないため、**新トリガー追加なし**。先行runをキャンセル・rerunせず、既存の同一writer継続に任せる。新タスク・schedule・workflow・PR・モデル・課金・main統合・実投票なし。全16モデル/4競技、全レース直前網羅、期限なしのowner-only保存、学習版の未来優位性は未完成。GitHub文書に私有保管先情報や生原本を転記していない。


## 2026-11-04 17:49 JST｜既存第1巡回の独立ZIP照合済み、次巡回は進行中

既存workflow 405276784、run `41801993716` の第1巡回が、予想原本の別artifact保存→公式結果・PDCAの別artifact保存→読戻しを通過し、第2巡回へ進んだ。GitHubサーバー保存時刻は予想17:48:24 JST、結果17:48:44 JST。結果ZIP `13307849010` SHA256 `579d3e277bbded624304a78f07fc27ed0b32ac0f60b15e1ceafcc82db29fafd3`、予想ZIP `13308117574` SHA256 `11751c7e150d4f57a6d80bae1a188c02814e92e8fe8da753a65c536c90c9a289` を再ダウンロードし実バイトSHAとAPI digest一致。内部status.json・forecasts.csvも一致。

前回16:37 JST第17巡回から今回17:48:42 JST第1巡回への差分は、基準5モデル予想 **515→525（+10モデル別予想、2レース）**、通常結果採点 **331→378（+47モデル別採点）**、LEARNED_SHADOW **48→52（+4研究予想）**、独立結果との学習版同条件比較 **34→44モデル別行（+10行、異なるレース数とは別）**。P0は288件維持。新規P1は公式出走・展示実入力のレースID `20261104-01-07` 締切17:55、`20261104-15-07` 締切18:02にそれぞれ既存5モデル。新規10件は17:48に締切前GitHub保存済みで、当時RESULT_PENDINGなのでこの新規2レースを的中/不的中に入れない。

第1巡回終了時点の内訳はHIT112、MISS266、結果待ち74、異常33、返還レビュー16、RESULT_REJECTED24、合計525件。通常採点378件。公式GET使用は予想21・結果24=45/240。第2巡回以降の未完了成果は加算していない。学習版の精度向上・本番採用は未証明。既存5モデル係数、旧P0/P1、学習版原本は不変。現在run継続中で新しいトリガーは追加しない。公開GitHubへの機密原本/個人保管先の転記なし。

## 2026-11-04 17:46 JST｜既存巡回を1件再開（新runの予想・採点は未確認）

既存workflow 405276784 の先行run 41787887120は17巡成功後、16:37:45 JSTに正常終了。上限240/240 GETに到達した。結果artifact `13304611018` と継続artifact `13304890338` は本実行で無改変ZIPを再取得し、SHA256 `684a7b71282aca8383c5cfe2056bf9b4bf04330ea963548f42b3052b54afc06c` / `5285179034da073ae4ca2eeaec890858586d9b2eaf6b6456e287e5d76912bc32` が記録と一致。最新保存値は基準515予想・通常採点331件・LEARNED_SHADOW48予想・同条件17レース（2系統とも元/学習版のHit@8同数）。これは16:37保存値であり新runの成果ではない。

PR #71のHEAD `d079bd99b1ed5b26a1aeade60b216bebc9f30218` と過去runを読み、同workflowのactive/queued/pending/waitingが無いことを確認して既存トリガーだけを1回更新。commit `8dc4e482e02c332fa54fc38129946cc90871f355` によりrun `41801993716` がqueuedになった。後続の追加トリガーは禁止。新runの初回原本復元、展示後締切前予想、結果照合、PDCA、独立ZIP読戻しは**まだ確認できていない**。元予想/係数は不変、新モデル・PR・workflow・schedule・実投票・main統合なし。共通原本の時刻矛盾や4xx/429では停止。

## 2026-11-04 17:20 JST確認 | 学習版と元モデルの同条件・前向き比較

読戻し・再計算時刻: 2026-11-04 17:20:41 JST。対象データの集計時刻は **16:37:27 JST**。確認時刻とレース結果の取得時刻を混同しない。新しい公式結果の取得や予想の再生成は今回していない。

対象: 既存Draft PR #71 / feat/four-sport-forecast-audit-view-20261022 / workflow405276784。
実run: https://github.com/haji84/RACE-AI/actions/runs/41787887120
実行コード: 813ed493a431351e3d86cee684481ff6d988c8e7。第17巡回の保存済みstatusと最終continuityを読み直した。

## 結論

**同じ17レースで比較した範囲では、学習版によるHit@8・仮回収率の改善は観測されなかった。** 自動学習の実行成功と精度改善は別。優越性も同等性も統計的に証明したとは扱わず、元モデルを自動で置き換えない。

| 系統 | 同条件レース数 | 元モデル的中 | 学習版的中 | 元的中率 | 学習版的中率 | 元仮回収率 | 学習版仮回収率 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 観測相性 | 17 | 7 | 7 | 41.18% | 41.18% | 101.47% | 101.47% |
| ST重視相性 | 17 | 6 | 6 | 35.29% | 35.29% | 89.26% | 89.26% |

1点100円・固定8点の仮想購入。各系統・各版の仮購入額13,600円。観測相性は元/学習版とも受取13,800円・仮収支+200円。ST重視相性は両版とも受取12,140円・仮収支-1,460円。実購入ではない。

17レースは両系統で同じ集合。2モデル分の34比較行を34種類のレースと数えない。また、各系統は14個の学習パラメータ版を順次使用した運用集計であり、単一の固定学習版の検証17件ではない。版別の成績は元statusのtraining_sha256別scoreboardに保持される。

両系統とも、上位8点の組合せ集合が変わったのは17レース中4レース、残り13レースは同じ。候補の順序変更は観測相性10件・ST重視相性13件。学習版だけ的中した件数も、元モデルだけ的中した件数も両系統とも0。係数や順位が変わっていても、現在の固定8点の成績改善にはつながっていない。

## 比較対象と除外を保持

- 保存済み学習版は48モデル別予想、異なる24レース。基準モデル515予想には合算しない。
- 通常結果で同条件比較できたのは34モデル別行、異なる17レース。
- 未採点14行は、結果未照合10行（5レース）、返還レビュー2行（1レース）、異常着順2行（1レース）。これらを外れに変換したり、保存台帳から削除したりしない。
- 学習版の最初の実証対象だった平和島8Rは元/学習版とも不的中、福岡8R・常滑9Rは両方とも的中。これらは上の17レースに含まれ、別加算しない。

## 今回の再検証範囲

1. 最新の結果ZIPと継続ZIPをGitHubから取得し、API登録digestと実バイトSHA256を照合。ZIP破損なし、内部status/state/sessionのハッシュも一致。
2. 基準515行・学習版48行の一意なrace_id/stage/model_idを確認。比較48行の元モデルSHA、学習版SHA、保存時刻、学習元参照、上位8点を両ファイルで照合した。
3. 認証済みcontinuityの学習証拠索引から、学習版の保存時刻 < 新入力as_of <= 予想保存時刻 < 締切を確認。同一レース・同一時点・同じ基準版との対応を検査した。
4. 通常34比較行は、別保存された公式結果履歴のsource SHAと取得時刻を特定し、6選手ID、正常着順、締切、確定3連単と100円払戻を再照合。保存済み8点との一致から的中・受取を独立再計算し、元集計に一致した。
5. 比較用レースを的中結果で選別していない。通常結果の条件を満たさない14行は理由付きで残した。

境界: 今回は認証済み2ZIPからの前向き成績の再計算。個々の学習元ZIP全件の再取得、全パラメータ版の学習計算再実行、全原本の新規第三者認証までは行っていない。学習元の検証履歴は認証済みcontinuityのtraining_proofsに残る。この限定を隠して全モデル学習品質の独立審査完了とは呼ばない。

## 学習の現在地

保存された最新学習版の入力は異なる83レース、学習63・未使用検証20。採用入力の構成はP0=55/P1=28。学習側の特徴支持は全国勝率63、モーター2連率63、展示タイム22、展示ST21。直近/コース別の着順・ST履歴4特徴は支持0であり、学習済みとしない。

過去の未使用検証20レースは上の未来比較とは別枠。観測相性は元/学習版とも4的中、ST重視相性は元4的中に対し学習版3的中。過去holdoutも一律改善ではない。検証結果を見て過去の学習版予想や元モデルを上書きしない。

## 実行状態と未達

基準予想515件、通常採点331件。内訳HIT105/MISS226、結果未照合111、異常33、返還レビュー16、結果拒否24。515=331+111+33+16+24。これは144種類のレースに対する複数モデル/時点の集計。

最終session.jsonでcompleted_round=17、requests_used=240/source_limit=240、halted_reason=SESSION_SOURCE_BUDGET_EXHAUSTEDを確認。runは16:37:45 JSTにcompleted/success。上限で止まった後の18〜24巡回を実処理成功に数えない。今回、新トリガー・後続run・タスクを追加しておらず、現在も無停止で動いているとは主張しない。上限を回避する再起動は行わない。

16:37の台帳では締切済み106レース、未来38レース、締切済みで5モデルP1が全て揃った36レース。不足308モデル別P1行を保持。展示がその時点に取得可能だったか未確認のものを、取得可能なのに取りこぼしたと断定しない。全日無欠落は未達。

## 次の判断基準・継続制約

今後も締切前に保存済みの同一レース・同一入力の元モデル/学習版を比較し、学習版だけの的中、元だけの的中、仮収支差、版別成績、未照合理由を確認する。少数例の同点を永久に同じと断定せず、逆に自動学習成功だけで性能向上と扱わない。本番自動切替なし。

既存5基準モデル、既存2系統のLEARNED_SHADOW、旧原本、研究オート2件の証拠区分を維持。既存タスクのID/頻度、同workflow/concurrency、取得上限、締切210秒以上、失敗時停止の制約は変更していない。新モデル系統/新PR/新workflow/課金/main統合/投票なし。全16系統/全4競技、翌日P0無人準備、期限なし本人専用保管は未完成。7日artifactを恒久保管としない。

## 出典・再現キー

- 結果artifact13304611018: ZIP SHA256 684a7b71282aca8383c5cfe2056bf9b4bf04330ea963548f42b3052b54afc06c。
- 継続artifact13304890338: ZIP SHA256 5285179034da073ae4ca2eeaec890858586d9b2eaf6b6456e287e5d76912bc32。
- 元status report SHA256: 57f3f7d7f5a5dec14d670421a6a50fe629cf08f081008a6e22c9241b4f2062ff。
- 今回ローカル再計算サマリーSHA256: 9ca4a68d72cb38060271ad93883c163efc210417cff953b89873dfb8f023c3d6。

直前16:42の状態文書全文は [変更前の監査記録](evidence/2026-11-04/status-before-paired-comparison-1720.md) に元blob4729606f7d217fffa092c7251e11af87816e92f1のまま保存。過去の証拠や他チャットの記録を削除していない。
