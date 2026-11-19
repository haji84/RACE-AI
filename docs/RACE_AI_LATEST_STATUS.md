# RACE-AI 最新状況 — 2026-11-19 14:19 JST

**GOALは未達。** 本人利用の開発・受入確認を継続し、一般公開の確認待ちは設けない。原本・既存変更・本番重みを保全する。前版は[同一blobの履歴](history/RACE_AI_STATUS_HISTORY_THROUGH_20261119_1332.md)と[相対リンクも有効なF4原文](https://github.com/haji84/RACE-AI/blob/f4a42cda749e6d52f90610b519df5cd7c896fac5/docs/RACE_AI_LATEST_STATUS.md)に保存した。

## 現在のHEAD・接続・保全

- 実mainは既存PR3の通常保護merge **f4a42cda749e6d52f90610b519df5cd7c896fac5**。tested head35ec4486と同一tree `db529bd97c3da502b1f70916f0c37565369a4bbe`、25 checks＝12成功/13skip/失敗0。実CIは457件/359.541秒＋旧A74 raw7件/23.582秒。[mergeと実CI](evidence/boat-main3-reviewed-merge-and-actual-ci-20261119.json)。
- 並行PR309のmain9520104cと102変更を保全し、旧main M4 ed336daa・M5 a277a692の原study証拠を継承した。再登録は0。
- 稼働BOAT sourceは **1dbb47b68d487fc6def0bd4b10b1423f0a2145f6** のまま。公開Pages `083739d080ac1fa88714bae0b5cca2bfe7712c8b`/資産f603、本番重み、Secrets/flagsは変更0。UI新規公開・投票・新モデル系統・課金・新job/step/input/cron/runner/timeout/権限は追加0。OFF pilot/PR290/291/main308、legacy KEIRIN-AIも当方では変更しない。
- 13:09:32 JSTの実確認は、無認証の公開API HTTP200、正規CLI haji84認証/push権限true、既存branchへの通常FF push成功。匿名/認証のHEADは一致。state keyはActions内だけ。[接続の別判定](evidence/race-ai-public-auth-write-offline-recheck-20261119.json)。
- 元offline変更PR70 `b7380fe6a377e6ccf2b96331f2126c52549bbe17`、PR292 `daae4c10167224b7730006d8ada5ade398aaa64b` は正規APIで再び両方422、local objectもなく**未復元**。ZIPや別環境ファイルの自動移転を仮定しない。

## P0保管・実運転・現在の学習候補読戻し

元run43829249080のP0保管失敗/24巡skipは履歴に残す。修正後A74は24巡・73AES原本・23 ALL_MODEL ZIP・保存P1 513行一致/欠落0を別runnerで確認したが、ALL_MODEL r4/19の欠落HOLDや全日適格は別問題だった。

実Sのfirst worker **44426169530/job135231474660** は自然完了success。実control24巡・今回requests420・lifetime15950。producerは19contexts/新171forecast/既存baseline再利用95を報告し12readback verified。これはproducer集計で、全原本union/全4競技/T15〜10の証明ではない。[実完了](evidence/boat-source1dbb-natural-completion-actual-20261119.json)。

旧追加P0の660原本は別runnerでAES/全inventoryを認証し不変のまま復旧済み。Sのr0は再発行0、132contexts/660slots保持。閉prefix2ではrawAES7・ALL_MODEL ZIP2・新P1 9行一致/欠落0、baseline5行は加算しない。R1 ALL_MODELは件数null/HOLD。issued mapは保存viewからの再構成で、実runtime issued fileの独立読取ではない。[独立認証範囲](evidence/boat-current-s-closed2-actual-counts-20261119.json)。

別のprivate venue学習候補はr18/23/24でVAULT_GIT_PUSH_TIMEOUTを報告した。fallback retained_candidates0を実未保存0にしない。M3実監査 **44460053379/job135344355259** はjob successだが、候補読戻しは**PRIVATE_ARCHIVE/HOLD**で、remoteへ未到達・保存/欠落/相違件数は全てnull。原予想保管とは分ける。[実report](evidence/boat-main3-bound-registration-and-cold-hold-actual-20261119.json)、[artifactの実照合](evidence/boat-main3-actual-counts-artifact-receipt-20261119.json)。

検証器が同raceのobservationをモデルpartitionごとに足し、正規producerのrace単位件数と一致しない欠陥を公開fixtureで再現した。既存PR121で、summary単位のcanonical raceと認証済snapshot完全一致/unique件数を検証する最小修正を準備中。元summary/cipher/score/crypto/source/G8を緩めず、保存済み判定は実再読戻し後に行う。

後継 **44446167880/job135298730289** は04:38:02 UTCでround2が長時間実行中、artifact7。実control/生成数/source_wait値は未読null。通常next_checkは最大180秒だがAUTHORIZATION_WAIT/SOURCE_REVIEW_WAIT/長いRetry-Afterには正規の長時間待機経路がある。実causeは未確定で、停止・再実行・counter reset・hotswapはしない。[readonly診断](evidence/boat-sourceS-successor-long-wait-readonly-20261119.json)。

## 前向き比較の実登録

M3実Actionsで **VERIFIED_ORIGINAL_SERVER_WITNESS** を確認した。元M4/run44449743664/artifact14495645723、nonce/spec/実candidate bindings/sourceSは不変。固定観測期間は **2026-11-19 12:15:30〜11-24 12:15:30 JST**。実適格matchedは二セルとも0、schedule分母はnull、評価はWINDOW_OPEN_HOLD。これは0開催/全件0の証明ではない。

100matched/5開催日/10会場日＋3指標の不確実性を満たす前の支持判定はNone。旧574 pairs/登録前予想を新分母へ流用しない。改善・98%・production昇格は未実証。原文代表照合は2/2一致を再確認したが、全records/公開時刻/実発売終了/G8は未証明。[登録と代表照合の実report](evidence/boat-main3-bound-registration-and-cold-hold-actual-20261119.json)。

## 画面・実Safari・実機

現本人用候補は **b55242230e93ec3975a5a49bf3dd5f46632ff794**、webtree `5cbbfe05a2971485b5c32a84a8ddf7b2539604cc`。mobile設定欄を69px短縮し320/390幅で完全表示券行を1行増やし、削除を含む44px target・320px間隔/最大金額表示・確認focus/scroll・短画面/更新保持を検証。CSSと既存geometryだけを変更し、元f723/f9e2を祖先に保つ。既存PR62証拠head8f916へ新Linux合成32PNGを同一byteで保管した。[合成証拠](https://github.com/haji84/RACE-AI/blob/8f916340f9287ae5d0379c15bf8791ff67313daf/docs/evidence/boat-ui-mobile-allocation-density-20261119/README.md)。

実Mac **44460086148/job135344475665** はSafari26.6で当日保存view/private loopback/AESを通過。feed revision477（予想件数ではない）・結果18・native P1 groups9・30cipher/239,433,121bytes・同一原本比較2を確認し、private session cleanupもtrue。plaintext endpoint0/外部browser要求0/実画面export0。[実private再生と失敗](evidence/boat-main3-actual-private-safari-and-synthetic-cleanup-hold-20261119.json)。

同jobの新candidate合成captureは**SAFARI_SESSION_CLEANUP_FAILED**で失敗、artifact0。終了処理が元UI例外を隠す可能性があり、主例外を同一のまま保全し8固定cleanup項目とwidth/pageを残す修正を既存PR121へ統合中。cleanup単独失敗は従来のHOLDを保つ。元164 testsを保持した172件とroot関連210件が成功したが、実Mac修正成功は未確認。RPC/retry/timeout/GUI設定・source/crypto/pins変更0。

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

新PRを作らず、既存PR121の元metadataと11月10日28race A研究SHA receiptを保全して利用する。元receiptはhuman heuristicでtrained modelではなく、元ZIP/予想原本は復元されていない。新しいmodel authorityや今の精度分母へ使わない。

[review済みlocal future patch](evidence/race-ai-reviewed-local-future-patches-20261119.json)は公式calendar partial parser・current分母None/0区別・空contextのAES receipt/不正path拒否。AUTO personal Bも完全8値・時計/SHA・未引退flag・締切前の既存B1入力へ接続するreview済みlocal修正を保管した。いずれも固定Sやstudyへ未適用で、実生成合格ではない。

次は保管検証器とSafari例外保全の最終CI、正規main統合、実Actionsによる再認証/読戻し/合成captureを確認する。実確認できない残件は完成扱いにしない。
