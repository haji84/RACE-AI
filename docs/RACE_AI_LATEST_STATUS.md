# 2026-11-20 JST｜競輪の公式入力を修正中（GOAL未達）

本人用の開発を継続する。一般公開の確認待ちは設けず、UI新規公開・投票・本番重み切替は行っていない。以下を最新の実測として優先し、以前の記録は下段に保持する。

- 今回の検証元mainは **6306a6fd59f9a7b2df46eb8640d9ad5966c6a59e**。BOAT source **1dbb47b68d487fc6def0bd4b10b1423f0a2145f6**、元モデルと映像sourceのpin、Secrets/flagsは変更していない。
- 認証済み完了log **44553849928/job135664465763** では公式経路102応答が全てHTTP200、403/429・block・unknownは0、カレンダー73開催まで解析した。一覧の未来日欄にも今日と同じ確定リンクを要求していたため、レース・選手の検証は0のHOLDだった。job successを取得成功に読み替えない。
- 今日だけの厳密なリンク検証に修正した通常のlocal実取得では、当日の全候補 **6会場・57レースID** を検証し、最初の詳細画面まで全796応答HTTP200。表示用画像の追加項目で停止した。画像alt/srcの明示的な組を読取り形式に追加し、値をモデルや校正済み強さへ変換しない。
- 次のlocal取得は **4レース・28選手** を検証。確認済み1,527応答は全てHTTP200、終了時unknown1を保持し、9車立ての枠番号項目で停止した。公式表示JSにある枠番号/表示CSSだけを追加で読み分け、全許可keyは掲載JSの21項目と一致する。修正後に保存済み **5レース・37選手** をofflineで再検証した。これを5件の新規予想や全日全モデルの完成に数えない。
- 未完了の通信本文にも既存budgetを適用した。loopback実ブラウザで、旧処理はbudget1秒でも本文待ち2.995秒、新処理は約1秒でHOLDする。上記Actionsの長時間stepは依存導入であり、この待ち問題が実原因だったとは断定しない。
- 関連 **155検査** と元モデル優先の環境で **25検査** が成功。source/model admissionはfalse、新予想0。workflowの全byteは検証元mainと同じで、job/step/input/cron/runner/timeout/permission等の定義を増やしていない。[実失敗・修正・保全](evidence/keirin-current-day-dom-20261120/README.md)。**修正一式の実Actions取得は、この記録時点では未確認。**
- 既存PR103の元head **9b875cf9c1d48f8bd31e95fd407a24cf3dcdb330** と132変更pathのmode/type/blob/immutable URLを保全する。元のEV/model変更treeを本番へ適用せず、新PRを作らない。
- WINTICKET自身と映像collectorの403は別件として未解除。今回の公式入力経路を、そのサーバ側の解除と同一視しない。拒否後retry、UA/headers偽装、cookie持込、proxyは行っていない。
- 4競技全日×全適用モデル・締切15〜10分前の生成/保存/結果照合、物理iPhone13Pro、6艇の連続識別/校正/予想接続、前向き精度改善は未達。原本/登録済み観測期間/本番重みを保全する。
- 保管復旧336候補/1,008file/375,640,877bytes・欠落0相違0、実Mac Safari172検査、未push **b7380fe6a377e6ccf2b96331f2126c52549bbe17** / **daae4c10167224b7730006d8ada5ade398aaa64b** の **UNRESTORED** は前記証拠を継承する。別環境のファイル自動移転や物理iPhone合格は仮定しない。

以下は以前の確認記録であり、当時の「現在」表現を含む。

# 2026-11-20 00:04 JST｜競輪403の継続修正（GOAL未達）

本人用開発を継続中。一般公開の承認待ちは設けない。UI新規公開・投票・本番重み切替は実施していない。以下を最新の確認とし、下段の以前の状況は履歴として保持する。

- 確認済みmainは **3c78b756960148f6bafd00a3dd243288430629ed**。既存PR101の通常保護mergeで、WINTICKETの拒否に依存しない公式KEIRIN.JPの通常画面経路を接続した。BOAT source **1dbb47b68d487fc6def0bd4b10b1423f0a2145f6** と既存モデルpinは変更していない。
- 実Actions **44547916659/job135643414848** は公式経路37応答が全てHTTP200、403/429は0。jobはsuccessでも、こちらの通信チェックで停止し開催一覧/レース/選手の解析は0だった。未取得を成功扱いにしない。
- 同じ停止を変更していないguardで再現した。公式画面の掲載scriptが送る `/sp/ana` の空body・同一origin XHR GETが最初の停止点。後続6通信は停止後のblockだった。この厳密な通常通信だけを許可する修正と、解析から既存owner-cycleまでの回帰検査を進めている。[診断と修正範囲](evidence/keirin-official-analytics-20261119/README.md)。**修正後の実取得は、この記録時点では未確認。**
- WINTICKET映像側の実run44491357722と44528962738は通常Chromiumでも `DAILY_INDEX_HTTP_403`。今回の公式入力経路の確認と、WINTICKET自身の403解除は分ける。UA偽装・cookie持込・proxy・拒否後retryは行わない。
- 既存PR102の元head **c52ff0216435b97a0209c43bbe5d0de589445736**、120変更pathのmode/type/blob/immutable URLを保全し、新PRは作らない。workflow/job/step/input/cron/runner/timeout/permissionの定義追加は0。
- 原暗号文の保管復旧は **336候補・1,008file・375,640,877bytes・欠落0・相違0** を別object databaseで全byte確認済み。state head **6c0a01ce55b1948b17610f694a15629df5ccdacf**。追加Actionsの候補AES再検査は初回限定guardでHOLDであり、全byte一致とは別に扱う。鍵のlocal取得は0。[既存PR62の保管証拠](https://github.com/haji84/RACE-AI/blob/6970228c7df74f4e93122facf9d3baff4733413f/docs/evidence/race-ai-final-handoff-20261119/ciphertext-recovery.json)。
- 実Mac Safari26.6の44470498836/job135378501491は172検査・private loopback/AES・合成28PNGを通過した。物理iPhone13ProのRACE-AI受入は未確認。本人SafariでWINTICKET一覧が開いたことを実機アプリ受入に置き換えない。[最新の他scope証拠](https://github.com/haji84/RACE-AI/blob/6970228c7df74f4e93122facf9d3baff4733413f/docs/RACE_AI_LATEST_STATUS.md)。
- 元offline未pushの **b7380fe6a377e6ccf2b96331f2126c52549bbe17** / **daae4c10167224b7730006d8ada5ade398aaa64b** は正規readでもlocal objectでも取得できず **UNRESTORED**。別環境ファイルの自動移転は仮定しない。
- 4競技全日全モデル・締切15〜10分前の生成/保存/照合、6艇の連続識別/校正/予想接続、前向き比較の精度改善は未達。登録済み観測期間/原本/重み/分母を変更しない。

以下は以前の確認記録。上記と矛盾する「現在」表現は当時の時点を示す。

# RACE-AI 最新状況 — 2026-11-19 15:03 JST

**GOALは未達。** 本人利用の開発・受入確認を継続し、一般公開の確認待ちは設けない。原本・既存変更・本番重みを保全する。前版は[同一blobの履歴](history/RACE_AI_STATUS_HISTORY_THROUGH_20261119_1332.md)と[相対リンクも有効なF4原文](https://github.com/haji84/RACE-AI/blob/f4a42cda749e6d52f90610b519df5cd7c896fac5/docs/RACE_AI_LATEST_STATUS.md)に保存した。

## 現在のHEAD・接続・保全

- 現mainは既存PR121の通常保護merge **147d0558dc8c8718af673310b324b63babc90d59**。tested head eeb3c5a4と同一tree `b0627bcfdf671fe49beb14b0610b04f2140aa52d`、26 checks＝12成功/14skip/失敗0。実CIは472件/343.745秒＋旧A74 raw7件/20.255秒。summary型の独立BLOCKERを閉じ、PRのSafari172件も成功した。[mergeと実CI](evidence/boat-main121-merge-and-actual-ci-20261119.json)。
- 並行PR311のmain8d67210c/12変更とPR309のmain9520104c/102変更をmode/type/blob一致で保全した。当方のworkflow変更は0。旧main M3 f4a42cda・M4 ed336daa・M5 a277a692の原study証拠を継承し、再登録は0。
- 稼働BOAT sourceは **1dbb47b68d487fc6def0bd4b10b1423f0a2145f6** のまま。既存Pagesは自動の暗号化data2file更新だけで `379531bb7e6d52157f5f5aa89751727cffcff2cf`へ進んだ。UI資産f603、本番重み、Secrets/flagsは変更0。UI新規公開・投票・新モデル系統・課金・新job/step/input/cron/runner/timeout/権限は追加0。OFF pilot/PR290/291/main308、legacy KEIRIN-AIも当方では変更しない。
- 13:09:32 JSTの実確認は、無認証の公開API HTTP200、正規CLI haji84認証/push権限true、既存branchへの通常FF push成功。匿名/認証のHEADは一致。state keyはActions内だけ。[接続の別判定](evidence/race-ai-public-auth-write-offline-recheck-20261119.json)。
- 元offline変更PR70 `b7380fe6a377e6ccf2b96331f2126c52549bbe17`、PR292 `daae4c10167224b7730006d8ada5ade398aaa64b` は正規APIで再び両方422、local objectもなく**未復元**。ZIPや別環境ファイルの自動移転を仮定しない。

## P0保管・実運転・現在の学習候補読戻し

元run43829249080のP0保管失敗/24巡skipは履歴に残す。修正後A74は24巡・73AES原本・23 ALL_MODEL ZIP・保存P1 513行一致/欠落0を別runnerで確認したが、ALL_MODEL r4/19の欠落HOLDや全日適格は別問題だった。

実Sのfirst worker **44426169530/job135231474660** は自然完了success。実control24巡・今回requests420・lifetime15950。producerは19contexts/新171forecast/既存baseline再利用95を報告し12readback verified。これはproducer集計で、全原本union/全4競技/T15〜10の証明ではない。[実完了](evidence/boat-source1dbb-natural-completion-actual-20261119.json)。

旧追加P0の660原本は別runnerでAES/全inventoryを認証し不変のまま復旧済み。Sのr0は再発行0、132contexts/660slots保持。閉prefix2ではrawAES7・ALL_MODEL ZIP2・新P1 9行一致/欠落0、baseline5行は加算しない。R1 ALL_MODELは件数null/HOLD。issued mapは保存viewからの再構成で、実runtime issued fileの独立読取ではない。[独立認証範囲](evidence/boat-current-s-closed2-actual-counts-20261119.json)。

別のprivate venue学習候補はr18/23/24でVAULT_GIT_PUSH_TIMEOUTを報告した。fallback retained_candidates0を実未保存0にしない。M3実監査 **44460053379/job135344355259** はjob successだが、候補読戻しは**PRIVATE_ARCHIVE/HOLD**で、remoteへ未到達・保存/欠落/相違件数は全てnull。原予想保管とは分ける。[実report](evidence/boat-main3-bound-registration-and-cold-hold-actual-20261119.json)、[artifactの実照合](evidence/boat-main3-actual-counts-artifact-receipt-20261119.json)。

検証器の同race observationのpartition重複集計とsummary primitive型比較を修正し、**M121実ActionsでPRIVATE_ARCHIVEを通過**した。次のremote読戻しでは**336候補中176一致・160欠落・相違0、認証して一致した原bytes194,960,367**。remoteは `1af9a3ad7dda6ef2068397e6f98fa00d1de45fa9`、statusはHOLD_PRIVATE_RESEARCH_RETENTION、reasonはREMOTE_CANDIDATES_MISSING_OR_CONFLICTING。160は一部file不足も含む候補数で、欠落file数/round別内訳は未確認。旧HOLDを保存済みと読み替えず、原ciphertextとActionsの認証済inventoryを照合してcreate-only復旧可能性を調べる。local owner-key取得/復号/復旧pushは0。[実report](evidence/boat-main121-actual-cold-retention-and-study-20261119.json)、[artifact照合](evidence/boat-main121-counts-artifact-receipt-20261119.json)。

後継 **44446167880/job135298730289** は04:38:02 UTCでround2が長時間実行中、artifact7。実control/生成数/source_wait値は未読null。通常next_checkは最大180秒だがAUTHORIZATION_WAIT/SOURCE_REVIEW_WAIT/長いRetry-Afterには正規の長時間待機経路がある。実causeは未確定で、停止・再実行・counter reset・hotswapはしない。[readonly診断](evidence/boat-sourceS-successor-long-wait-readonly-20261119.json)。

## 前向き比較の実登録

M121実Actionsでも **VERIFIED_ORIGINAL_SERVER_WITNESS** を確認した。元M4/run44449743664/artifact14495645723、nonce/spec/実candidate bindings/sourceSは不変。固定観測期間は **2026-11-19 12:15:30〜11-24 12:15:30 JST**。実適格matchedは二セルとも0、schedule分母はnull、評価はWINDOW_OPEN_HOLD。これは0開催/全件0の証明ではない。

100matched/5開催日/10会場日＋3指標の不確実性を満たす前の支持判定はNone。旧574 pairs/登録前予想を新分母へ流用しない。改善・98%・production昇格は未実証。原文代表照合は2/2一致を再確認したが、全records/公開時刻/実発売終了/G8は未証明。[登録と代表照合の実report](evidence/boat-main3-bound-registration-and-cold-hold-actual-20261119.json)。

## 画面・実Safari・実機

現本人用候補は **b55242230e93ec3975a5a49bf3dd5f46632ff794**、webtree `5cbbfe05a2971485b5c32a84a8ddf7b2539604cc`。mobile設定欄を69px短縮し320/390幅で完全表示券行を1行増やし、削除を含む44px target・320px間隔/最大金額表示・確認focus/scroll・短画面/更新保持を検証。CSSと既存geometryだけを変更し、元f723/f9e2を祖先に保つ。既存PR62証拠head8f916へ新Linux合成32PNGを同一byteで保管した。[合成証拠](https://github.com/haji84/RACE-AI/blob/8f916340f9287ae5d0379c15bf8791ff67313daf/docs/evidence/boat-ui-mobile-allocation-density-20261119/README.md)。

実Mac **44460086148/job135344475665** はSafari26.6で当日保存view/private loopback/AESを通過。feed revision477（予想件数ではない）・結果18・native P1 groups9・30cipher/239,433,121bytes・同一原本比較2を確認し、private session cleanupもtrue。plaintext endpoint0/外部browser要求0/実画面export0。[実private再生と失敗](evidence/boat-main3-actual-private-safari-and-synthetic-cleanup-hold-20261119.json)。

M3の合成capture終了失敗で元UI例外が隠れる問題は、主例外同一性と8固定cleanup項目を保持する修正をM121へ統合した。ただしM121実Mac **44467823700/job135369769829** は追加source-free fixtureの6subcase失敗でstep6停止し、private Safari/合成captureは全てSKIP・artifact0。実Mac修正成功は未確認。

実symlinkの一時rootで同6失敗を再現し、テスト出力先2箇所だけresolve()して意図したresize/open/capture境界へ入るよう修正した。通常172件と同alias下172件が成功、root関連210件/20.105秒も成功。原172methods/本番symlink guard/runtime/RPC/timeout/source/pinsは不変。元Macの実際のalias文字列は未記録なので断定しない。[再現と修正](evidence/boat-native-M121-temp-alias-test-fixture-fix-20261119.json)、[root最終検証](evidence/boat-native-M121-fixture-root-final-review-20261119.json)。

物理iPhone13Pro・本人login・直接GitHub feed配送・全8参考画面の最終受入は未確認。本人SafariでWINTICKET開催一覧が表示されたことをRACE-AI画面合格に置き換えない。接続された実機操作環境は無い。

## 4競技・競輪・映像の残件

| 完成条件 | 実確認と不足 |
| --- | --- |
| 全レース×適用可能な既存全モデル | sourceSのactive登録は既存15系統/30 sport-modelセル。4競技全日union・締切15〜10分前生成/保存/結果照合、AUTO実8試走値、JRA/NARの全5model適用は未実証。未提供sportを0件とするcurrent分母と空入力receiptのlocal修正はreview済みだがSへ未適用。 |
| 競輪403 | fe7実probe44437961180はHTTP403=1/429=0/UNKNOWN=0、新入力0。本人Safari/別client通常200とは別。公式SP calendarは73期間/42会場見出し/当日候補8、個race/締切/rosterはnull。既掲載JSの正規POST1回は500、本文未保存で原因不明。403解消・全347/437・当日全予想は未証明。 |
| 6艇識別・校正・予想接続 | 775frameを既存S/modelで実推論。6人物が同時に見える7frame/0.2秒のAI参照42を先に固定し、manualROIをモデルへ渡さず評価。幾何15/42・服色current正解2・6色同時0/7、ID遷移分母0。世界距離/速度/強さ/予想適格はfalse。 |
| 前向き精度改善 | 原サーバ証拠の実登録は成功。window open、適格matched0、所定期間/件数/不確実性未達。改善の証明はこれから。 |

競輪の新mainから除外済みKdreamsへ進めたsecondary入口は、既存4host/https/no-userinfo/443をRequest/open前に検証する修正で閉じた。381関連＋独立381＋禁止81/承認24 casesが成功。旧offline parser/NoRedirect/source flagsを保全し、実provider要求0。これを403解消とは扱わない。[独立review](evidence/keirin-approved-transport-guard-independent-review-20261119.json)、[SP正規navigationの実停止](evidence/keirin-calendar-normal-navigation-actual-stop-20261119.json)。並行PR309の17歴史結果/11月18日79cohortも当日の全国live intakeや新しい前向き改善へ加算しない。

映像ではgeneric PERSON候補が観客にも置かれ、元metadataもparent boat/identity/model eligibleをfalseにしていた。追加の同7frame観測は既定の戻り値を完全保持し26→25→16→15の対応を確認。global cap到達後の未訪問tailに9対象があるが、NMS拒否/uncapなら成功とは推定しない。source/閾値/cap/weights/GTは不変。短い選定後AI参照はhuman GT/全race連続ID/前向き精度ではない。[counts・hash・許諾](evidence/boat-six-rider-diagnostic-final-counts-hashes-license-20261119.json)。raw frame/journal/参照座標は非公開。

## 既存変更と次の検証

新PRを作らず、既存PR121の元metadataと11月10日28race A研究SHA receiptを保全して統合済み。次は既存PR106の元15filesをimmutable5b0f7ef/全Git ancestryで保持し、元32race SHA receipt1fileだけを現treeへ同一blobで採用する。raw JSON/予想/結果原本とUIはmainへ追加せず、元metadata/全mode/type/blob/URLを保存してfixture修正を載せる。元receiptはhuman heuristicでtrained modelではなく、元ZIP/予想原本は復元されていない。新しいmodel authorityや今の精度分母へ使わない。

[review済みlocal future patch](evidence/race-ai-reviewed-local-future-patches-20261119.json)は公式calendar partial parser・current分母None/0区別・空contextのAES receipt/不正path拒否。AUTO personal Bも完全8値・時計/SHA・未引退flag・締切前の既存B1入力へ接続するreview済みlocal修正を保管した。いずれも固定Sやstudyへ未適用で、実生成合格ではない。

次はfixture修正の最終CIと通常main統合、実Mac再確認、認証済cipher inventoryに基づく欠落160候補の安全な復旧可否を確認する。実確認できない残件は完成扱いにしない。
