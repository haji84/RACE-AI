# RACE-AI 最新状況 — 2026-11-19 10:39 JST

**GOALは未達。** 原本・既存変更・重み・元の判定を保全して継続中。従来全文は[履歴](history/RACE_AI_STATUS_HISTORY_THROUGH_20261118_0928.md)へ同一Git blobのまま保全した。

## 接続・HEAD・未復元

- 現在のmainは既存PR9の通常merge **`9a9588571b244e1e89aa7cbe35cb12d675c3bdcb`**、tree `ca598c921b989f517f51e459568658faa76575e5`。tested head ffdb890dと同一tree、22 checks（10成功/12skip/失敗0）、実CI385件/171.082秒＋raw7件/14.098秒が成功。閉prefix2読戻し・翌日修正・競輪typed denial診断・既存horse検証を反映した。実mainの原本読戻し44437961225/job135271458002は進行中。[通常mergeと実probe](evidence/boat-main9-reviewed-merge-and-real-keirin403-20261119.json)。
- 前段mainの既存PR13通常merge **`a6ec09072db385a7bba54deb5793cd5a68ad8b60`**、tree `9bb01f9963ee1a87e3372a586392b583514e87d1` は最終候補3ce1f1e5のtested treeと一致し、26 checks（12成功/14skip/失敗0）、実149/225/376＋7件ほかが成功。独立84＋role4件も成功しreview CLEAR。公開Pages `083739d080ac1fa88714bae0b5cca2bfe7712c8b`・公開資産f603は変更していない。
- protected sourceは既存PR15の通常merge **`1dbb47b68d487fc6def0bd4b10b1423f0a2145f6`**、tree `fac54c8e4fd3ceeb8177e408487ca80e9b1e76d4`。最終候補72012372のtested treeと一致。GitHub44422863984の913件/223件/既存3・13・38・46件とNode29件、別44422863924の復旧198件が全成功。main PR13はこの実Sと現在の呼出側proofを結合済み。[source/main復旧review](evidence/boat-r0-source-main-recovery-review-20261119.json)。
- 前段のmain作業基点 `7584fc3d9d60aa2a548a43281041f66cf0ce9681`（既存PR22通常merge）と旧BOAT clock参照同期7003/PR25の証拠を保全した。その後の既存PR19/13による参照同期・復旧は上記の実mainへ反映済み。
- 修正前sourceは既存PR21の通常merge `fbc743be548bfd123e46cdbfe290515a59e5e0d3`、tree `1068d5a0d1225e0638a31528f8031a5b8e9fc584`。最終候補9f3/既存CI44348357932のtreeと一致。今朝の実原本originとして保全し、995等の歴史role・原本・固定recovery契約も保つ。[sourceの実merge/CI](evidence/boat-source21-reviewed-merge-20261119.json)。
- 前段のmain実装は既存PR19の通常merge `bc40906cf2246ba12ad698bb71e6fec492ab7675`、tree `48fafe1fb44083e47f910db9b85c1ae429840e62`。最終候補d48のtested treeと一致し、28 checks（13成功/15skip/失敗0）。復旧138件/0.521秒、matrix372件/152.917秒＋7件/13.974秒、native検証コード140件/18.319秒が成功。新P0はsame＋M2/profile/BB/A74のみ、995/F1/C979/unknownと逆方向を拒否。旧role・fixed reader/recovery契約を保全し、現在のmainも継承する。[同期の検証](evidence/boat-main-exact-clothing-source-sync-20261119.json)。
- 選択実行環境は11/18 23:34 JSTに実コマンドが復旧し、管理statusもrunning/currentを確認。公開repoのgit readと最新HEAD一致、CLIのhaji84認証、既存PR62 branchへの通常FF pushが実成功。管理接続の保護された通常merge実績とは別にCLI書込も確認した。既存36 linked worktreesと元checkoutの変更を保全し、最新HEADを分離して作業。秘密鍵はActions内だけ。[環境・現行登録・ローカル検証](evidence/race-ai-local-runtime-resume-and-native-roster-20261119.json)。
- 元offline変更PR70 `b7380fe6a377e6ccf2b96331f2126c52549bbe17`、PR292 `daae4c10167224b7730006d8ada5ade398aaa64b` は08:40:39 UTCの正規APIが両方422 No commit foundで**未復元**。別環境のファイル移転を仮定しない。
- 復旧したfilesystemの唯一のGit object storeでも2commitは不在。古いcheckout・attachmentの実在は確認したが、元offline変更が移転したとは扱わない。
- 01:25 JSTの通常 `git fetch --no-write-fetch-head origin <SHA>` でも両commitは `upload-pack: not our ref`。公開read成功・認証成功・既存branchへの実FF push成功とは別に、元offline変更は未復元のまま。
- 新PR・モデル系統・課金・job/input/cron/runner/timeout/権限・marker名を増やしていない。UI公開・投票・本番重み切替0。OFF pilot/PR290/291/main308、legacy KEIRIN-AIを維持。

## 本人利用の範囲と朝の起動確認

ユーザーの「公開するわけやないよ」に従い、一般公開を前提にした許可待ちは取り下げる。本人用画面の開発・private loopback/合成受入を継続し、公開Pagesの資産は変更しない。

06:57〜07:02 JSTの正規metadataではlauncher359件、canonical owner356件とproduction限定34件を全ページ確認し、非completed0。新しい朝イベントは未観測で、新しい朝ゲートがHOLDしたという証拠はない。現在のref/owner doc/historyを既存pure decideで再評価するとREADY_EXISTING_OWNER_WORKFLOW_ONLYだが、Actionsの実起動判定とは区別する。既存manualはowner判定を通らずdaily collectorへ進むため、直接source起動の代替にしない。[全頁監査](evidence/boat-morning-schedule-delivery-audit-20261119.json)。

通常merge後、07:15 JSTの実launcher44409740547/job135174365706がREADY_EXISTING_OWNER_WORKFLOW_ONLY/dispatch_allowed=true/source GET0を記録し、既存gate経由でsource fbcのrun44409798061が起動した。直接source dispatch・旧runの再実行・counter resetはしていない。

## 今朝の追加P0保存失敗と原本保全

09:02 JSTの実launcher **44425780224/job135230120859** は別runnerで復旧を行い、正規完了ログにFAILED_OWNER_ORIGINALS_RECOVERED/recovered_runs1/source GET0/new_forecasts0/original_forecasts_changed=falseを記録。続いて **READY_VERIFIED_RECOVERED_OWNER_CONTINUATION** を通り、09:05:35にsource1dbbの実owner **44426169530/job135231474660** が既存ゲートから起動した。直接のsource起動・counter resetは0。[実ゲート/原本復旧](evidence/boat-main13-actual-r0-recovery-and-owner-start-20261119.json)。

新ownerはoriginal再利用28・追加P0実行30/暗号保存31/readback32/**期限後保管33**/view反映34の各stepがsuccess。以前失敗した33を実通過した。10:13の正規metadataでもjobは実行中で、巡回17のstepが進行中。**control完了数・生成件数・締切前件数はまだ新jobの完了ログ/AESから読めていない**。r2のALL_MODEL/P1/PRIVATE_PAIRSなどの暗号artifact実在を確認したが、存在・step成功だけで全件/全モデル適格や全日を主張しない。閉じたsnapshot2の独立読戻し候補b050のレビューで翌日の実時計による拒否を再現し、followup592c8c70でmainの履歴読取認証へ分離した。sourceの当日生成guardは翌日false/Noneを保ち、時計を戻さない。385＋raw7件、最終9 focused件、実S依存のroot77件が成功し、独立review CLEAR。現HEAD CI385＋7件も成功して通常merge済み。実Actions読戻し中。[候補と翌日修正の証拠](evidence/boat-current-s-closed-snapshot2-readonly-audit-20261119.json)。

この読取候補の発行済みモデル照合は、認証済みsaved viewから再構成したprojectionと原inventoryの整合確認であり、実runtimeのissued fileを独立に読んだ証明ではない。出力にscopeとruntime_issued_file_independently_read=falseを明示する。R1のALL_MODEL欠落は件数null/HOLDのまま、R3以降のstep/artifactは原metadataを保って理由付きで対象外とし、現在のview commit/観測時刻を閉prefixの時刻に置き換えない。

元r0の660件は以前のproducer報告であり、今回の復旧guardはexact artifact14475644448を実AES・inventory・vault・view/issuedmapで認証する。実復旧ログは件数を出していないため、独立ログ件数を660と補完せず、追加の原本監査で数を確定する。

実run44409798061/job135174569110は07:20 JSTに失敗。最初のP0の暗号保存・create-only first receipt・期限後vault保管はsuccess/独立Git読戻しtrue。次のproducerは132 contexts/追加660 forecastを生成したが、r0 upload直後のmetadata404でreadbackと追加P0恒久保管に失敗し、その後の巡回は全skip。実controlはcompleted_round0/requests_used1で、660件を実巡回成功や独立認証済み件数へ加算しない。[完了ログの件数](evidence/boat-current-p0-and-native-actual-failure-counts-20261119.json)。

08:08 JSTの正規認証では、r0 artifact14475644448/18,707,982 bytes/SHA256 e6c87d8ecacfc075b8b3e1ea1b9df51adec5cd2ad056a4b187df50601bea50d7 と最初のP0・continuity・source-controlが同run/head・期限内で存在した。metadata404の根因を反映遅延だけと断定しない。その後、再生成前にAES・全inventory・vault・保存view・発行済みmapを再認証する復旧候補をPR15/13へ反映し、前段の実復旧を確認した。[再取得したmetadata](evidence/boat-current-p0-retention-incident-metadata-20261119.json)。

既存PR15で、current-run upload receiptに一致するmetadata404だけの既存3回/60秒retryを追加P0の二つのconsumerへ結線した。さらに、上記exact失敗実行の原P0＋r0をAES・全inventoryで認証し、再復旧時もvaultから独立読戻し、既存V5へ追記して発行済みmapを検証する。元の固定検証器main blob c1621c/source blob be56afは変更0。歴史fbc proofはfbcとして認証し、新checkout・全履歴・全controlへ結合する。中間のcounter減少、原本/view/issuedmap欠落、未登録V5昇格はHOLD。mandatory restoreのpreflightで、任意bootstrapの失敗後に巡回へ進むことも防ぐ。

復旧author68e0b3a7をtransportへ合成した72012372は独立191件・実clock oracle・root focused50件を通り、上記の現HEAD CI後にsource1dbbへ通常mergeした。main PR13も149 gate件/0.395秒・現HEAD CI・通常mergeを完了し、前段の実復旧/worker再開へ進んだ。新jobの独立件数/締切/結果照合は未確認で、全日達成へ置き換えない。

## P0保管の修正と実運転

元run43829249080のP0保管失敗・24巡skipを履歴として残す。Gitの不足blob取得が約2.77GBへ膨張する原因を再現し、選択blob取得と既存保管処理を修正した。修正後A74 run44218343091では24巡が実行され、別runnerの認証で24巡最終control・73 AES原本・ALL_MODEL 23 ZIP、saved AES viewと一致するP1 **513行/欠落0**を確認した。公式P0 scheduleは132レース。513行は固有レース数・完全P0/P1 union・適格分母ではない。[独立監査](evidence/boat-main-sync-closed-a74-actual-20261118.json)。

ALL_MODELのr4/19は欠落HOLDを維持。正規ログではr4はcontexts0/generated0の分岐、r19はartifact metadata/ZIP読取404。r4の入力網羅性、r19の対象/404根因は不明で、欠落を発行0や成功に置き換えない。[固定証拠](evidence/boat-a74-round04-round19-source-facts-20261118.json)。

後続A74 run44252479726は12:15:41Zに自然完了。**24成功stepのうち実際のcontrol完了は14巡**、15〜24はWORKER_HANDOFFのno-op。追加生成は8巡で正数/6巡で0。producer報告の合計は10 contexts・100新規forecast・40 baseline再利用、対応8 readbackでverified=true。session requests494/lifetime15368、最終raw retention466/466もproducer報告であり、別runnerによる最終全原本認証や固有レース集計ではない。停止・hotswap・counter resetはしていない。[完了scope](evidence/boat-a74-continuation-final-20261118.json)。

13:06:27Z、main7003の既存launcher44310274907/job134822293251は **READY_VERIFIED_SAME_DAY_CONTINUATION**（dispatch_allowed=true/recovery_required=false/source GET0）を記録した。既存final_control・継続counter・fresh history・source wait条件を通り、13:06:28Zにsource995の実run44310358995が起動。[実継続ゲート](evidence/boat-http-receive-clock-source-main-sync-20261118.json)。

後続job134822591655は00:26:12 JSTに自然完了し、**69 step成功/失敗0・実control完了4巡**。5〜24はDAY_HANDOFFのno-op。正規の完了ログでは追加4巡ともcontexts0/generated_forecasts0、bootstrapは132 contexts/generated0。最終controlはready=true/session requests161/lifetime15529。saved viewの634 forecast/559 scoredは累積値であり、4巡分を加算しない。producerによる保存/読戻し報告と、別runnerでの全原本独立認証を区別する。新規P1が無いため受信clock修正の実原本結合も未実証。[自然完了の実ログ件数](evidence/boat-source995-natural-completion-20261119.json)。

現行sourceと旧A74のrepeated_cycleは同一bytesで、論理round・取得総数・session時間・round取得数の固定上限はNone。提供元wait・identity・JST日・物理worker handoffと累積counterを保持する。無上限のコードは全日網羅/T15〜10達成の実証ではない。[コード再確認](evidence/boat-source-no-total-cap-code-check-20261118.json)。

停止/hotswap/再起動・counter resetはしていない。夜間の4巡成功を全日網羅・T15〜10の実証にしない。最初の追加生成13:21:23Zからprivate retention検証13:49:23Zまで時間がかかることを確認し、同じ復号objectへの二重検証だけを除く修正を既存PR21で取り込んだ。別snapshotごとの完全認証と保存全byte照合を保持。合成30セル/240lineageの境界中央値29.3%、全12候補保存の中央値18.26%短縮は実GitHub transportや締切達成の測定ではない。[source保存修正](https://github.com/haji84/RACE-AI/blob/fbc743be548bfd123e46cdbfe290515a59e5e0d3/docs/evidence/boat-retention-validation-throughput-20261119.json)。

## 本人用Safariの拒否診断修正

既存PR16で、実runのCURRENT_V5_REPLAY_INVALIDを固定phase・明示allowlist上流reason・bounded読込件数へ区分する診断修正を通常mergeした。author b5f907c4、統合9c69d1c9。RED→GREENを確認し、最終native148＋dispatch38＝186件が成功。独立186件/15.301秒と29境界probe/外部接続0も成功しreview CLEAR。元140テストと成功経路はAST同一、日付/clock/512files/256MiB/cipher/固定EFF/全workflow/UIは不変。例外文やURLを出さず、型/固定集合/件数を再検証する。旧runの内部原因は未確定だったが、反映後runでは次段落の拒否理由を実確認した。診断修正を実受入成功にはしない。[テスト先行と限定](evidence/boat-native-replay-diagnostic-test-first-20261119.json)。

PR16反映後の実Mac44409808616/job135174602639は148 unit成功・公開4資産一致後、current_day_authentication/HISTORY_DAY_UNAVAILABLEでHOLD。読込2 files/10,932 bytes、残budget268,424,524 bytesであり、今回の拒否を容量超過とはしない。当日の保存履歴不足を緩和・過去日付へ差替えず、P0原本とfeedを先に復旧する。更新候補f723の実capture・物理iPhone・直接feed配送は未合格。[実診断の件数](evidence/boat-current-p0-and-native-actual-failure-counts-20261119.json)。

main13のnative自動判定はCANDIDATE_UNCHANGEDで追加POSTなし。原本復旧・当日P1保存後、既存workflow416758725/browser=native-safariを正規認証で1回だけ実行し、**44428187504/job135238405624** が09:20に起動、09:28に **NATIVE_MACOS_SAFARI_SAVED_VIEW_VERIFIED** で成功した。Safari26.6/macOS、保存日11/19、feed revision455、認証済み結果3、native P1 group9、ブラウザAES成功。455は予想件数ではなくfeed改訂番号、9は固有レース数ではない。暗号文30 files/235,283,873 bytesを認証し、外向きbrowser request0・鍵をrequest/URL/storageへ出した件数0・実画面の画像出力0。実データはprivate loopback再生で、GitHub feed直接配送・本人login・物理iPhone・参考8画面すべての合格は未証明。[当日の実Mac受入](evidence/boat-native-current-day-mac-actual-20261119.json)。

候補f723の合成Safari画像28枚は、fixtureが1艇のみで出走者も無い旧入力だったため、4競技6/7/8/12出走の既存rich fixtureへ揃えた。author04777fceの3pathのみを既存PR5へ統合中。実f723 factoryの生成7266 bytesと完全一致し、旧guard・current V5・公開UIを保持。193 testsとLinux Chromiumの28枚/外向き0、独立193件/16.701秒が成功しreview CLEAR。新しいコードのMac実行・最終8画面比較は未実行で、実iPhoneの代用にしない。[fixtureとテスト先行](evidence/boat-native-rich-synthetic-test-first-20261119.json)、[独立review](evidence/boat-native-rich-synthetic-independent-review-20261119.json)。

一般公開・新しい配備先・公開許可待ちは前提にしない。正当な実装変更を既存prefix/markerを使う通常mergeへ進め、既存ゲートによるsource/native判定を別に確認する。直接source dispatchや予算resetは行わない。

## main反映後の実ゲートとSafari

02:11 JSTのmain bc launcher44355714905/job134983145756は、正規の実行全体log ZIPで **HOLD_OUTSIDE_OWNER_DAYTIME_WINDOW**、dispatch_allowed=false/recovery_required=false/source GET0を確認した。sourceを直接起動・旧workerを停止・counterをresetしていない。05:30以降も既存の全ゲートを通る必要があり、新source実運転/全日/T15〜10は未実証。

同じlauncherはnative受付1回のACK=trueを記録し、44355781785/job134983398274が実起動した。140 unit/52.232秒と公開f603の4資産一致を確認したが、02:15:41 JSTに **NATIVE_SAFARI_ACCEPTANCE_HOLD / CURRENT_V5_REPLAY_INVALID**。callsiteはread_current_v5_replay（main1614）で、内部のどの条件が拒否したかは未確定。時刻だけが原因と断定しない。更新候補のMac capture・物理iPhone・直接feed配送を合格にせず、繰返し起動/時計・guard緩和をしていない。[実merge/実ゲート/保留](evidence/boat-main19-actual-gate-and-native-hold-20261119.json)。

main bc反映後の固定原本監査44355714989/job134983143952も実完了success。02:20:51 JSTに旧A74の24control/73AES/23ZIP/P1 513一致・欠落0・不足round4/19 HOLDを再認証した。02:23:13にstrict4比較はRESULT4/PROGRAM0/未結合4でPROGRAM_CAPTURE_CLOCK_BINDING_UNVERIFIEDを維持。旧BB bootstrapの132 contexts/1,848適用slot、660 GENERATED_UNATTESTED/1,188 RULE_FILTEREDも独立認証したが、歴史原本の値で新source生成ではなくall_models_operational=false。固定M2は24AES/2ZIP・9行一致、不足round2〜10/HOLDを維持する。全scopeのsource GET0/予想変更0。[全safe status/count行](evidence/boat-mainbc-fixed-source-readback-20261119.json)。

## 原本時計の原因と将来分修正

締切診断の固定scopeはfirst-original **48レース/672モデルrecord**。42レース588件は一致、2レース28件は結果側予定締切が後、4レース56件は結果観測なし。前倒し/締切未記録0。正式ペア数・G8分母はnullで、元のPAIR_RESULT_JOIN/ALL_MODEL_INTAKE_RESULT_ACTUAL_CUTOFF_MISMATCHを維持。[件数](evidence/boat-current-pair-cutoff-inventory-actual-20261118.json)。

保存本文の独立認証44304417349/job134802152640（12:37:27Z）はjob successでも診断は**HOLD/PROGRAM_CAPTURE_CLOCK_BINDING_UNVERIFIED**。2レースに対する4比較でRESULT4一致・PROGRAM0一致・未結合4・inspector拒否0/時計相違0。固定26header/MACと候補AES/receiptの全検査を通り、必要なPROGRAMのSHA+URLに対応する原文は存在するが、予想入力が要求する取得時刻とは一致しない。4比較は4固有原本ではない。時計を緩めず別時刻の本文を採用しないため、PROGRAM予定表そのものの検証・公式改定の正当性・実発売終了・G8は依然未証明。[実原本の時計結合証拠](evidence/boat-current-pair-program-clock-binding-actual-20261118.json)。 main7003反映後も44310274869/job134822293517が実完了successし、13:16:36Zに同じstrict4比較HOLDと73AES/23ZIP/513一致・欠落4/19を再確認した。これは旧A74の再認証で、新source995の新規取得原本の証明ではない。[反映後再監査](evidence/boat-source995-post-merge-actual-20261118.json)。

旧sourceの静的追跡では、raw原本が受信直後の時計を保存し、予想入力へは2秒pacing後の別時計を返す不整合を確認。将来995はONの対象HTMLだけ同じ受信clockを共有し、OFFの振舞い・2秒待機・待機後の日付拒否・後で採る実生成時計を維持した。過去時計/本文/予想/結果は変更0。sourceのテスト先行REDは880件中想定2assert失敗/errors0、修正GREENは880件/219.105秒と既存3/12/38/165/46件が全成功。

main参照同期もテスト先行RED（recovery138件中5失敗、national368件中12失敗/errors0）を確認。最初の実装CIでは既存markerへのSHA追記漏れ1件を検出し、markerだけ追記して再実行。最終CI 44309440574の138件/0.368秒、44309440607の368件/184.690秒＋追加7件/30.051秒、既存mirror212件/101.412秒＋32件などが全成功。26 checksは12 success/14 skip/失敗0。独立静的reviewは6ファイル18置換規則/21箇所の順逆一致CLEAR。既存C979/F1等の歴史role・四つのP0親・失敗origin契約・EFF/native/旧P0を維持。[source/main同期の証拠](evidence/boat-http-receive-clock-source-main-sync-20261118.json)。

## 画面・4競技・映像・精度

今回、4競技の現行適用登録を実行して確認した。退役sellerを除く既存15系統・30 sport/modelセル（BOAT14/競輪5/AUTO6/競馬5）。既存の前向き生成・batch原本結合・生成時計・coverageの38テスト/308.633秒は全成功。ただし公開合成fixtureの契約検証であり、実日次台帳・全レース・T15〜10や精度改善の証明ではない。JRA/NARの適用区別も未確認のまま。

競輪のfe7 WINTICKET経路は公開日次index段階で提供元拒否/制限として停止し、403/429のどちらかをログから分離できない。前版の「fe7でHTTP403確認」という断定を訂正する。IP/地域/認証/clientの原因も未確定。00:37 JSTの通常Chromiumによる同じ日次index一回確認はHTTP200/SSR75レース、本人のiPhone 13 Pro Safariでも開催一覧が表示された。一方、01:02 JSTの既存Actions44342598507はDAY_INDEX_SOURCE_UNAVAILABLE、続く実cycleは1request・denial stop・new inputs0でHOLD。jobのsuccessを解消や完全入力の取得としない。追加の経路変更や403/429迂回はしていない。

既存PR9では、fe7が握りつぶした直近のtyped HTTPErrorだけをHTTP_403/HTTP_429/UNKNOWNの固定件数へ分けた。停止条件・接続先・UA・source fe7は不変。23 testsのRED→GREEN、関連96件と独立96件/5.456秒、実fe7 helperからのfixture403/429各1requestを確認。反映後の実main44437961180/job135271457441は10:35:16 JSTに **HTTP_403=1/HTTP_429=0/UNKNOWN=0**、public_page_requests1、new_pre_race_inputs0、denial stop=trueを記録した。今回の通常取得が403だったと初めて分離できたが、提供元の拒否原因・取得成功・403解消は未確認。[独立検証](evidence/keirin-typed-provider-denial-independent-review-20261119.json)、[実probe](evidence/boat-main9-reviewed-merge-and-real-keirin403-20261119.json)。

同じ候補は既存のreadonly締切前検証へhorseを1語追加し、4競技の正例・競馬の窓外・既存拒否条件の35件を確認した。既存の開始予定T15〜10/締切margin65秒の検証で、ユーザーの締切前優先処理・競馬実生成・JRA/NAR全5モデル適用の実証ではない。[検証範囲](evidence/horse-existing-prospective-gate-verification-20261119.json)。

旧日次discoveryの除外済みKdreams接続と旧mobile callerの承認外host接続は、transport前拒否に修正し既存PR22の通常mergeでmain `7584fc3d9d60aa2a548a43281041f66cf0ce9681` へ反映。旧HTML解析はpure offline helperに保全し、拒否時source attempts=0。ローカル138件/skip0・独立48件と既存CI21 checks（9成功/12skip/失敗0）を確認。これは競輪の403解消や当日予想生成の証拠ではない。[診断と修正](evidence/keirin-approved-source-local-diagnosis-20261118.json)、[main検証](evidence/keirin-source-guard-main-verification-20261119.json)。

既存PR62の候補コードは `f723f0e8b94a87a6d6a7b414b1bb30954541925e`、web tree `d905215e2f886b0bcc4f2e58323ceee465b03c38`。見た目の修正7e6743dcと旧候補7082を祖先に保つ。元ed904を祖先に保ち通常FF push済み。本文移動・320px買い目隠れ・短い横画面の確認button隠れ・60秒更新による展開/focus/12頭横scroll消失を修正した。全4競技タブの複数レースを含む合成fixtureで6/7/8/12出走を確認し、一覧カードは通常6艇257px mobile/181px PCへ収め、詳細情報と8買い目へ進める。既存30 checkpoint、追加4幅・短画面5条件・refresh/keyboard/WebCrypto等が成功し独立review CLEAR。固定8参考画像と元候補のnative PNG28枚の比較を保存。更新候補の実Safari・物理iPhone・login・GitHub暗号化feed直接配送は未確認。公開UI f603は変更0。[最終候補の追加証拠](https://github.com/haji84/RACE-AI/blob/7082e1214e6797806c00e1b60e088792c857672d/docs/evidence/boat-ui-populated-reference-followup-20261119.json)。

公開前の全資産比較で、旧7082に公開f603の選手名出典3種と最後のforecast日を保つ処理が欠ける退行を再現し、f723へ最小mergeした。候補既存EXECUTION_FAILEDの扱いも保持。product46/history12件は独立reviewでも全成功。元Python AESをNode WebCryptoで読む回帰、既存UI30・rich4幅・short5・refresh/roster/controls・合成WebCrypto等も成功。これは公開前に直した差分で、実予想/モデルを変更しない。

f723のnative Safari検証用SHA/treeとworkflow候補2tokenを一致させた。三つの見た目資産は7082と同byte。テスト先行RED1件→GREEN178件、独立178件も成功。旧7082の厳格loader検証を保全し、実f723も74資産/37,568,588byteを検証した。固定更新後の178件も全成功。checkerの関数・guard・時計・環境・公開f603/EFF/privateV5・job/権限は変更0。更新後の実native実行は上記CURRENT_V5_REPLAY_INVALIDで保留。[候補固定の証拠](evidence/boat-native-reviewed-candidate-pin-20261119.json)。

修正後の合成[8画面previewをGitHubへ保管](https://github.com/haji84/RACE-AI/blob/1e97e66031c3a48467029587bd29f2f6ab669df2/docs/evidence/boat-ui-f723-preview-20261119/README.md)した。Chromium/架空入力/portrait表示0・provider GET0で全8判定PARTIAL。元参考JPEG・実原本・鍵・owner URLを含めない。ユーザーは「公開するわけやないよ」と明示した。本人用UIの開発・受入確認が作業範囲で、一般公開やPagesへの配備を完成条件にしない。公開許可を開発・ローカル検証の開始条件にしない。以前の5ファイル配布案は参考として保全し、実行していない。公開範囲・暗号化・原本・モデル重みを保持して検証を続ける。

服色journal評価の実装はsource fbcへ反映した。実trackerのunknown_detectionsを無視すると6frame/36targetのうち不明検出のあるframeまで完全6艇成功に数える不具合を修正し、完全成功3frame・不明検出1・clean区間の継続6と区分した。rider部位を船体/物理位置へ転用せず、欠測frameも明示する。focused100・source223・独立112件などが成功しreview CLEAR。実6艇映像/独立GT/距離時刻校正/強さ評価の合格とはしない。[評価と再現](https://github.com/haji84/RACE-AI/blob/fbc743be548bfd123e46cdbfe290515a59e5e0d3/docs/evidence/boat-clothing-benchmark-resume-20261118.json)。

追加映像調査では既存CC BY-SA 4.0 clipのhashを再確認したが、新しい6艇連続映像は得られなかった。通常metadataの最初の1要求がHTTP403/126 bytesで停止し、その後の外部要求0・新video download0・tracker実行0・独立GT0。既知clip全体を今回再decodeしたという証拠や、世界中に適した映像が無いという主張はしない。[件数のみの調査記録](evidence/six-boat-licensed-media-count-only-audit-20261119.json)。

| 完成条件 | 実確認と残件 |
| --- | --- |
| スマホ/PC・Safari | 当日の実Mac Safari26.6/run44428187504で保存日11/19・feed revision455・結果3/native P1 9group・browser AES成功。private loopback再生で、GitHub feed直接配送の証明ではない。物理iPhone・本人login・全8画面の最終受入はfalse。候補f723の28PNGは合成で入力充実化を検証中。公開f603は維持。本人端末は13 Proだが接続された実機操作環境は無い。[当日の実受入](evidence/boat-native-current-day-mac-actual-20261119.json)。 |
| 全レース×全適用既存model | BOATは上記の部分証拠のみ。完全union/全日/T15〜10/日跨ぎは未証明。AUTOの個車入力、JRA/NARの適用区別、4競技全日の独立証明も未完。 |
| 競輪 | 最新の実44437961180（11/19 10:35 JST）はindex未取得、HTTP403が1request、429/UNKNOWN0、新入力0で停止。403自体は確定したが原因と解消は未確認。local通常index200/SSR75・本人Safari開催一覧表示とは別の接続環境。全347/437入力/全券/当日予想は未実証。[実ログ件数](evidence/boat-main9-reviewed-merge-and-real-keirin403-20261119.json)。 |
| 6艇の継続識別・校正・予想接続 | 同時6艇の独立GT・承認済み映像・実race結合が未確認。既知Commons映像は2〜3艇で、6艇精度や強さの校正を証明しない。 |
| 前向き精度改善 | 11/3事前方針のGit blob073379は旧A/B向けで、自動的に新nativeセルを登録しない。同じ100matched/5日/10会場日と改善・不確実性検定を継承する専用study候補を実装中。サーバreceiptへの登録と将来集計は未実行。過去574 PDCA pairs/holdoutを新分母へ流用しない。改善・98%は未実証、重み変更0。 |

競輪の承認は[WINTICKET/KEIRIN.JP限定](https://github.com/haji84/RACE-AI/blob/fe7e5581263b2b31fbd45536ac6a611c2779fa65/docs/KEIRIN_WINTICKET_KEIRINJP_OWNER_SOURCE_APPROVAL_20261109.md)でKdreamsは除外。本人は「利用はいいと書いていた」、追加の技術設定/許諾済み入力bundleは持っていない、iPhone 13 Pro、保管先GitHubと回答した。既存の本人使用・通常自動取得の指示を尊重し、設定名や許諾書を繰返し要求しない。完全347/437入力・全券・公式締切を創作せず、提供元403/429は尊重する。鍵/passwordは不要。既存公開RACE-AIでの3タブ切替確認も質問したが未回答で、Safari開催一覧表示をRACE-AI画面の実機受入に置き換えない。

コード検証・通常保護mergeの既存承認で可能な作業を継続し、実機・許諾データ・前向き観測の欠落を完成扱いしない。
