# RACE-AI 最新状況 — 2026-11-19 01:49 JST

**GOALは未達。** 原本・既存変更・重み・元の判定を保全して継続中。従来全文は[履歴](history/RACE_AI_STATUS_HISTORY_THROUGH_20261118_0928.md)へ同一Git blobのまま保全した。

## 接続・HEAD・未復元

- 今回のmain作業基点は `7584fc3d9d60aa2a548a43281041f66cf0ce9681`（既存PR22通常merge）。旧BOAT clock参照同期7003/PR25の証拠も保全し、既存PR19で新protected sourceへの正確な参照同期を進める。
- protected sourceは既存PR21の通常merge `fbc743be548bfd123e46cdbfe290515a59e5e0d3`、tree `1068d5a0d1225e0638a31528f8031a5b8e9fc584`。最終候補9f3/既存CI44348357932のtreeと一致。旧source995等の歴史role・原本・recovery契約を保つ。[sourceの実merge/CI](evidence/boat-source21-reviewed-merge-20261119.json)。
- main参照同期の実装は既存PR19へ通常FF push済み。実fbc依存で138/372件、UI固定更新との統合206件、独立review145件が全成功。新P0はsame＋M2/profile/BB/A74のみで、995/F1/C979/unknownと逆方向を拒否する。実auditor blobを再束縛し、6runtimeの差分逆変換は元bytesと完全一致。最終GitHub CI・通常merge・実launcher判定は別に確認する。[同期の検証](evidence/boat-main-exact-clothing-source-sync-20261119.json)。
- 選択実行環境は11/18 23:34 JSTに実コマンドが復旧し、管理statusもrunning/currentを確認。公開repoのgit readと最新HEAD一致、CLIのhaji84認証、既存PR62 branchへの通常FF pushが実成功。管理接続の保護された通常merge実績とは別にCLI書込も確認した。既存36 linked worktreesと元checkoutの変更を保全し、最新HEADを分離して作業。秘密鍵はActions内だけ。[環境・現行登録・ローカル検証](evidence/race-ai-local-runtime-resume-and-native-roster-20261119.json)。
- 元offline変更PR70 `b7380fe6a377e6ccf2b96331f2126c52549bbe17`、PR292 `daae4c10167224b7730006d8ada5ade398aaa64b` は08:40:39 UTCの正規APIが両方422 No commit foundで**未復元**。別環境のファイル移転を仮定しない。
- 復旧したfilesystemの唯一のGit object storeでも2commitは不在。古いcheckout・attachmentの実在は確認したが、元offline変更が移転したとは扱わない。
- 01:25 JSTの通常 `git fetch --no-write-fetch-head origin <SHA>` でも両commitは `upload-pack: not our ref`。公開read成功・認証成功・既存branchへの実FF push成功とは別に、元offline変更は未復元のまま。
- 新PR・モデル系統・課金・job/input/cron/runner/timeout/権限・marker名を増やしていない。UI公開・投票・本番重み切替0。OFF pilot/PR290/291/main308、legacy KEIRIN-AIを維持。

## P0保管の修正と実運転

元run43829249080のP0保管失敗・24巡skipを履歴として残す。Gitの不足blob取得が約2.77GBへ膨張する原因を再現し、選択blob取得と既存保管処理を修正した。修正後A74 run44218343091では24巡が実行され、別runnerの認証で24巡最終control・73 AES原本・ALL_MODEL 23 ZIP、saved AES viewと一致するP1 **513行/欠落0**を確認した。公式P0 scheduleは132レース。513行は固有レース数・完全P0/P1 union・適格分母ではない。[独立監査](evidence/boat-main-sync-closed-a74-actual-20261118.json)。

ALL_MODELのr4/19は欠落HOLDを維持。正規ログではr4はcontexts0/generated0の分岐、r19はartifact metadata/ZIP読取404。r4の入力網羅性、r19の対象/404根因は不明で、欠落を発行0や成功に置き換えない。[固定証拠](evidence/boat-a74-round04-round19-source-facts-20261118.json)。

後続A74 run44252479726は12:15:41Zに自然完了。**24成功stepのうち実際のcontrol完了は14巡**、15〜24はWORKER_HANDOFFのno-op。追加生成は8巡で正数/6巡で0。producer報告の合計は10 contexts・100新規forecast・40 baseline再利用、対応8 readbackでverified=true。session requests494/lifetime15368、最終raw retention466/466もproducer報告であり、別runnerによる最終全原本認証や固有レース集計ではない。停止・hotswap・counter resetはしていない。[完了scope](evidence/boat-a74-continuation-final-20261118.json)。

13:06:27Z、main7003の既存launcher44310274907/job134822293251は **READY_VERIFIED_SAME_DAY_CONTINUATION**（dispatch_allowed=true/recovery_required=false/source GET0）を記録した。既存final_control・継続counter・fresh history・source wait条件を通り、13:06:28Zにsource995の実run44310358995が起動。[実継続ゲート](evidence/boat-http-receive-clock-source-main-sync-20261118.json)。

後続job134822591655は00:26:12 JSTに自然完了し、**69 step成功/失敗0・実control完了4巡**。5〜24はDAY_HANDOFFのno-op。正規の完了ログでは追加4巡ともcontexts0/generated_forecasts0、bootstrapは132 contexts/generated0。最終controlはready=true/session requests161/lifetime15529。saved viewの634 forecast/559 scoredは累積値であり、4巡分を加算しない。producerによる保存/読戻し報告と、別runnerでの全原本独立認証を区別する。新規P1が無いため受信clock修正の実原本結合も未実証。[自然完了の実ログ件数](evidence/boat-source995-natural-completion-20261119.json)。

現行sourceと旧A74のrepeated_cycleは同一bytesで、論理round・取得総数・session時間・round取得数の固定上限はNone。提供元wait・identity・JST日・物理worker handoffと累積counterを保持する。無上限のコードは全日網羅/T15〜10達成の実証ではない。[コード再確認](evidence/boat-source-no-total-cap-code-check-20261118.json)。

停止/hotswap/再起動・counter resetはしていない。夜間の4巡成功を全日網羅・T15〜10の実証にしない。最初の追加生成13:21:23Zからprivate retention検証13:49:23Zまで時間がかかることを確認し、同じ復号objectへの二重検証だけを除く修正を既存PR21で取り込んだ。別snapshotごとの完全認証と保存全byte照合を保持。合成30セル/240lineageの境界中央値29.3%、全12候補保存の中央値18.26%短縮は実GitHub transportや締切達成の測定ではない。[source保存修正](https://github.com/haji84/RACE-AI/blob/fbc743be548bfd123e46cdbfe290515a59e5e0d3/docs/evidence/boat-retention-validation-throughput-20261119.json)。

## 原本時計の原因と将来分修正

締切診断の固定scopeはfirst-original **48レース/672モデルrecord**。42レース588件は一致、2レース28件は結果側予定締切が後、4レース56件は結果観測なし。前倒し/締切未記録0。正式ペア数・G8分母はnullで、元のPAIR_RESULT_JOIN/ALL_MODEL_INTAKE_RESULT_ACTUAL_CUTOFF_MISMATCHを維持。[件数](evidence/boat-current-pair-cutoff-inventory-actual-20261118.json)。

保存本文の独立認証44304417349/job134802152640（12:37:27Z）はjob successでも診断は**HOLD/PROGRAM_CAPTURE_CLOCK_BINDING_UNVERIFIED**。2レースに対する4比較でRESULT4一致・PROGRAM0一致・未結合4・inspector拒否0/時計相違0。固定26header/MACと候補AES/receiptの全検査を通り、必要なPROGRAMのSHA+URLに対応する原文は存在するが、予想入力が要求する取得時刻とは一致しない。4比較は4固有原本ではない。時計を緩めず別時刻の本文を採用しないため、PROGRAM予定表そのものの検証・公式改定の正当性・実発売終了・G8は依然未証明。[実原本の時計結合証拠](evidence/boat-current-pair-program-clock-binding-actual-20261118.json)。 main7003反映後も44310274869/job134822293517が実完了successし、13:16:36Zに同じstrict4比較HOLDと73AES/23ZIP/513一致・欠落4/19を再確認した。これは旧A74の再認証で、新source995の新規取得原本の証明ではない。[反映後再監査](evidence/boat-source995-post-merge-actual-20261118.json)。

旧sourceの静的追跡では、raw原本が受信直後の時計を保存し、予想入力へは2秒pacing後の別時計を返す不整合を確認。将来995はONの対象HTMLだけ同じ受信clockを共有し、OFFの振舞い・2秒待機・待機後の日付拒否・後で採る実生成時計を維持した。過去時計/本文/予想/結果は変更0。sourceのテスト先行REDは880件中想定2assert失敗/errors0、修正GREENは880件/219.105秒と既存3/12/38/165/46件が全成功。

main参照同期もテスト先行RED（recovery138件中5失敗、national368件中12失敗/errors0）を確認。最初の実装CIでは既存markerへのSHA追記漏れ1件を検出し、markerだけ追記して再実行。最終CI 44309440574の138件/0.368秒、44309440607の368件/184.690秒＋追加7件/30.051秒、既存mirror212件/101.412秒＋32件などが全成功。26 checksは12 success/14 skip/失敗0。独立静的reviewは6ファイル18置換規則/21箇所の順逆一致CLEAR。既存C979/F1等の歴史role・四つのP0親・失敗origin契約・EFF/native/旧P0を維持。[source/main同期の証拠](evidence/boat-http-receive-clock-source-main-sync-20261118.json)。

## 画面・4競技・映像・精度

今回、4競技の現行適用登録を実行して確認した。退役sellerを除く既存15系統・30 sport/modelセル（BOAT14/競輪5/AUTO6/競馬5）。既存の前向き生成・batch原本結合・生成時計・coverageの38テスト/308.633秒は全成功。ただし公開合成fixtureの契約検証であり、実日次台帳・全レース・T15〜10や精度改善の証明ではない。JRA/NARの適用区別も未確認のまま。

競輪のfe7 WINTICKET経路は公開日次index段階で提供元拒否/制限として停止し、403/429のどちらかをログから分離できない。前版の「fe7でHTTP403確認」という断定を訂正する。IP/地域/認証/clientの原因も未確定。00:37 JSTの通常Chromiumによる同じ日次index一回確認はHTTP200/SSR75レース、本人のiPhone 13 Pro Safariでも開催一覧が表示された。一方、01:02 JSTの既存Actions44342598507はDAY_INDEX_SOURCE_UNAVAILABLE、続く実cycleは1request・denial stop・new inputs0でHOLD。jobのsuccessを解消や完全入力の取得としない。追加の経路変更や403/429迂回はしていない。

旧日次discoveryの除外済みKdreams接続と旧mobile callerの承認外host接続は、transport前拒否に修正し既存PR22の通常mergeでmain `7584fc3d9d60aa2a548a43281041f66cf0ce9681` へ反映。旧HTML解析はpure offline helperに保全し、拒否時source attempts=0。ローカル138件/skip0・独立48件と既存CI21 checks（9成功/12skip/失敗0）を確認。これは競輪の403解消や当日予想生成の証拠ではない。[診断と修正](evidence/keirin-approved-source-local-diagnosis-20261118.json)、[main検証](evidence/keirin-source-guard-main-verification-20261119.json)。

既存PR62の最終候補は `7082e1214e6797806c00e1b60e088792c857672d`、実装 `7e6743dc08cc940af0c9fcdf4787ba82ea679407`、web tree `82118c8bbe853eff07f461d1c3a6da43ec138bd7`。元ed904を祖先に保ち通常FF push済み。本文移動・320px買い目隠れ・短い横画面の確認button隠れ・60秒更新による展開/focus/12頭横scroll消失を修正した。全4競技タブの実件数を持つ合成fixtureで6/7/8/12出走を確認し、一覧カードは通常6艇257px mobile/181px PCへ収め、詳細情報と8買い目へ進める。既存30 checkpoint、追加4幅・短画面5条件・refresh/keyboard/WebCrypto等が成功し独立review CLEAR。固定8参考画像と元候補のnative PNG28枚の比較を保存。更新候補の実Safari・物理iPhone・login・GitHub暗号化feed直接配送は未確認。公開UI f603は変更0。[最終候補の追加証拠](https://github.com/haji84/RACE-AI/blob/7082e1214e6797806c00e1b60e088792c857672d/docs/evidence/boat-ui-populated-reference-followup-20261119.json)。

未公開候補のnative Safari検証用SHA/tree/三資産hashとworkflowの候補2tokenを一致させた。テスト先行RED1件→GREEN178件、独立178件も成功。実7082の厳格loaderは74資産/37,563,754byte・元合成4recordを検証した。checkerの関数・guard・時計・環境・公開f603/EFF/privateV5・job/権限は変更0。当日private gateと実Safari本体の成功は別に確認する。[候補固定の証拠](evidence/boat-native-reviewed-candidate-pin-20261119.json)。

服色journal評価の実装はsource fbcへ反映した。実trackerのunknown_detectionsを無視すると6frame/36targetのうち不明検出のあるframeまで完全6艇成功に数える不具合を修正し、完全成功3frame・不明検出1・clean区間の継続6と区分した。rider部位を船体/物理位置へ転用せず、欠測frameも明示する。focused100・source223・独立112件などが成功しreview CLEAR。実6艇映像/独立GT/距離時刻校正/強さ評価の合格とはしない。[評価と再現](https://github.com/haji84/RACE-AI/blob/fbc743be548bfd123e46cdbfe290515a59e5e0d3/docs/evidence/boat-clothing-benchmark-resume-20261118.json)。

| 完成条件 | 実確認と残件 |
| --- | --- |
| スマホ/PC・Safari | 実Mac Safari26.6/run44258108084で11/18世代433・結果79/native原本9group・2model比較・browser AES成功。固定暗号文loopback再生で、GitHub feed直接配送の証明ではない。物理iPhone・本人login・全8画面の最終受入はfalse。元候補ed904の28PNGは合成。未公開最新候補7082/公開f603を維持。本人端末は13 Proだが接続された実機操作環境は無い。[実受入](evidence/boat-native-v5-actual-acceptance-20261118.json)。 |
| 全レース×全適用既存model | BOATは上記の部分証拠のみ。完全union/全日/T15〜10/日跨ぎは未証明。AUTOの個車入力、JRA/NARの適用区別、4競技全日の独立証明も未完。 |
| 競輪 | 最新日次capture44283995717/job134731792136は10:42に日次index HTTP403で停止。最新PR71 44273370761/job134695450969も9:10に不完全入力HOLD。最新canary44310295802は13:06に旧11/3 manifest/GET0で当日入力なし、fallback134822438215は13:07に実HTTP403とNO_VERIFIED_DAILY_CATALOG_OR_REPLAYで停止。[直近canary](evidence/keirin-canary-actual-20261118-1307.json)。discovery44222760913の79リンク/8会場はidentity-only。job成功を予想生成とせず未認証件数はnull。[直前30件の範囲](evidence/keirin-latest-scheduled-goal-blockers-20261118.json)。 |
| 6艇の継続識別・校正・予想接続 | 同時6艇の独立GT・承認済み映像・実race結合が未確認。既知Commons映像は2〜3艇で、6艇精度や強さの校正を証明しない。 |
| 前向き精度改善 | 11/3事前方針073379は100matched/5日/10会場日を要する。今回nativeセルとの適用は未判定。過去574 PDCA pairs/holdoutを適格分母へ流用しない。改善・98%は未実証、重み変更0。 |

競輪の承認は[WINTICKET/KEIRIN.JP限定](https://github.com/haji84/RACE-AI/blob/fe7e5581263b2b31fbd45536ac6a611c2779fa65/docs/KEIRIN_WINTICKET_KEIRINJP_OWNER_SOURCE_APPROVAL_20261109.md)でKdreamsは除外。本人は「利用はいいと書いていた」、追加の技術設定/許諾済み入力bundleは持っていない、iPhone 13 Pro、保管先GitHubと回答した。既存の本人使用・通常自動取得の指示を尊重し、設定名や許諾書を繰返し要求しない。完全347/437入力・全券・公式締切を創作せず、提供元403/429は尊重する。鍵/passwordは不要で、実機のSafari開催一覧表示をRACE-AI画面の実機受入に置き換えない。

コード検証・通常保護mergeの既存承認で可能な作業を継続し、実機・許諾データ・前向き観測の欠落を完成扱いしない。
