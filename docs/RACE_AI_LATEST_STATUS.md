## 2026-11-17: 同一原本sidecar照合を修正し、実source同期を継続

既存PR108のdf3cc88はsource-free ownerと復旧CIがsuccess、独立55件と関連60件成功。
通常merge後のproduction実HEADはeff296f6d54ad4be297d93e32f1ee0d4592ad9e3でreviewed treeと完全一致。
同HEADの重複owner CIも発生しているため、mainの実起動を切り替える前に最終状態を確認する。
mainの既存PR100でlive pinを実eff296fへ同期する。旧提案の履歴は保全し、係数や別系統モデルを再投入しない。
main実run44017586294は停止したまま、新P1の復旧成功はまだ証明していない。
実復旧failureと、実別runnerによる438292原本AES合格・後段ALL_MODEL監査失敗を区別して保存した。

## 2026-11-17: 実別runnerで43829249080のAES/checkpointを認証

main実run44017586249のjob133819143803で、優先対象43829249080のcontinuity14208902044と
source-control14208782370を別runnerが実AES復号し、公開counterの全項目一致を確認した。
累積GET12770/日基点11524/worker0/巡回695を保全。公式GET0・新予想0・後継許可なし。
count artifact14298594525（ZIP SHAe920646551ba8a58457d9eefd2ccbb06b6d6a25c8882465f934fed0c31313723）を
この環境でも再取得し、metadataのSHA/サイズと照合した。
この独立AES合格は、新worker起動や本日のP1生成成功の証拠ではない。
同jobの後段ALL_MODEL再読戻しはINDEPENDENT_ALL_MODEL_REPLAY_NOT_AVAILABLEでfailure。
過去11/16全14モデル1680slotの完成は認定しない。復旧gateのsidecar差異は別修正として継続。
[実AESのcount証拠](evidence/boat-failed438292-independent-aes-20261117.json)。

## 2026-11-17 UTC: P0保管停止の修正を既存PR292へ統合、main接続を準備

正規認証で公開read/本人haji84/API push権限を分離確認し、既存branchへの実pushも成功。
branch protectionの読取APIは403で未確認。保護解除や--adminを使わず通常PR mergeを実施した。
元checkout b420631/branch workは保全。指定UI文書は履歴c15e683から全文復元した。
未push b7380fe6a377e6ccf2b96331f2126c52549bbe17 と daae4c10167224b7730006d8ada5ade398aaa64b は
ローカルobject不在、GitHub fetchはnot our ref。UNRESTOREDであり、今回の修正を復元済みとは呼ばない。

**実際に反映したsource**: PR292の候補d26b7ba47eae32152352c6204c6b2f373ce8dc45は
CI44016312344/44016312246/44016312251の3系統success。独立reviewもblockingなし。
通常merge後のproductionは82cedd7b6054ef73664a57e6e17709be56fb12c4、reviewed treeと完全一致。
新しいproducerはこの記録時点では未起動。mainのlive pinをこの実merge SHAへ同期する。
c123は過去原本の厳密なread-only originとして保全し、古いsourceへのdispatch許可にしない。

**停止と修正**: run43829249080の追加P0保管で失敗し24巡すべてskipped、後続2件もfailure。
ログには表示stateの180秒fetch timeout2回、all-model保管失敗、Vaultの60秒timeout2回。
bare Gitでwrite-treeが無関係なpromised blobを全取得する機構を再現。Vault現treeは約2.77GB。
Vaultだけmissing-ok tree作成にしてOID保全・選択原本の別reader SHA/AES/本文検証を維持。
表示/全モデルfetchはexact SHAのdepth1へ。全モデル現tree約420MBの検証は省略していない。
過去の実timeoutのGit subcommandは旧ログに無く、唯一の原因とまでは断定しない。
最新43978567937のworker1回GET/P0保存済みを、専用のbootstrap AES/公開control/先行原本replayで
認証後に3原本を保持・別reader検証する復旧を追加。累積13018/日基点13017/worker1/巡回707を保つ。
任意の取得数、未保存P1、403/429、source waitを許可しない。復旧自体の公式GET・新予想は0。

**検証**: storage101、owner159、bootstrap/owner179、独立storage75/復旧46件success（範囲重複）。
6実ZIPのGitHub metadata/サイズ/SHA/run/head一致を確認。ローカルzip照合はAES監査の代わりではない。
実Vault先端のtree維持もローカル0.024秒/git516KiBで成功。remote書込0、実予想成功とは別。
mainの原本監査対象を実停止43829249080へ更新し、既存の真正release gateから最新bootstrapを復旧する。

**Safari**: 旧実Mac試験43830256729はimport前後の汎用SAFARI_OPERATION_FAILED。
固定readerにparser checkoutが無い状態でrace_ai.coreのModuleNotFoundErrorを再現、
既存PR64/72 parserを揃えるとimport成功。既存jobへ2つの固定checkoutを追加し、17境界試験成功。
readerも上記の検証済みstorage sourceへ同期。実Mac再試験・実機iPhoneはまだ未確認。

全4競技×適用可能全モデルの全日生成/保存/結果照合、6艇服色の継続識別・校正強さ・予想接続、
元モデル/学習版の未来改善は未合格。新PR/モデル系統/外部service/課金/権限変更/投票/本番weights切替0。
[証拠](evidence/boat-p0-storage-recovery-20261117.json)。以下は各時点の履歴として保全する。

<!-- BOAT main release and actual Safari attempt 2026-11-16T08:11Z -->
## 2026-11-16: 実source更新・自動後継起動、Mac試験の失敗修正

本人承認に基づく既存PR69の通常merge後、main実HEADは
`0c0c18db0b9f76fc75b63031ad528e2b2637b325`。reviewed f25c9ccdとtree完全一致。
同HEAD前の全13 CI checkが成功し、原本fullbody・全owner scopeの独立レビューも合格。
本番sourceは`c123b8538006b3189181195bbc91d8f28d216ba5`。
真正なmain push run43828431834/job133167655039が過去停止2件の原本を別runnerで検証し、
元予想/使用量を変えずに後継owner43829249080を08:11:22 UTCに起動した。
旧owner自然終了からこの新規実行までの間隔は約17分。無停止・全締切充足とは呼ばない。
新しい実予想の生成/保存件数、全モデル正式適格、別runner AESは継続確認中。

実Macの既存単一proof jobをrun43828472149で実行したが、Safari操作前に失敗した。
指定Python3.11のsetup前に境界テストがMac標準3.14.7で動き、
loopback拒否のstderr空assertionが失敗（14/15合格）。省略されたstderr全文の種類は未確定。
既存setup stepをテスト前へ移し、15既存試験と新しい順序試験の計16件がローカル成功。
ログ非露出のassertionは維持し、変更は実行順と回帰試験のみ。実Mac再試験へ進める。
実機iPhone、ブラウザAES/本人認証、8参考画面の完全視覚受入は未確認。

以下は過去の時点記録。映像3項目・全日充足・前向き改善・98%を実証済みとは扱わない。

<!-- BOAT approved source release 2026-11-16T07:55Z -->
## 2026-11-16: 原本保全の修正版をproductionへ統合

本人承認に基づき既存PR288を通常mergeし、実productionは
`c123b8538006b3189181195bbc91d8f28d216ba5`（07:55:20 UTC）。
reviewed `d798acd9` のtree `3888e6d7` と完全一致をGitHub/Gitで読戻した。
旧owner43818666068は07:54:09 UTCに24巡successで自然終了、累積GET12770。
稼働中のproducerは停止・差替えず、P1/RESULT/continuity/controlは保全した。

修正版は必須展示入力優先、真正native計算event、旧as_of生成時計の拒否、既知の不変原本locator、
同じtraining SHA42117035の暗号学習入力復元、透明playerの誤検出拒否を含む。
sourceのexact HEAD CI3系統と独立レビューが合格。関連Python群3/12/468/38/123/46件は重複を含む。
新しい実runでの生成・学習入力復元はこの記録時点では未実施。

mainは旧0c7d1b76。既存PR69で実production SHAへdispatch/reader/auditを同期する。
旧b491は既存原本のread-only検証とSafariの不変readerに保持し、古いsourceへのdispatch許可はしない。
原本全本文・全ownerのfresh AES再読戻しを合格条件へ追加して検証中。
Safariは同一公開資産と認証済み原本を実Mac Safariで確認する経路を準備済みで、本番実行はmain統合後。
全日1680slot、実機iPhone、映像3項目、前向き改善・98%の実証は未合格。

以下は過去の記録。最新実SHA・値はこの節と後続の実証記録を優先する。

<!-- BOAT completion continued 2026-11-16 -->
## 2026-11-16: 全件監査・Safari・映像・実学習の継続検証

この節は候補コードの検証時点の記録。main `0c7d1b76`、production `b491fb21` は継続中。
新しいPR・remote branch・workflow・job・cron・サービス・課金・モデル系統・投票は追加していない。

**実運転**：owner43803973248が24巡を成功終了（累積GET12236、WORKER_HANDOFF）。
定期run43812709551が原本回復ゲートを再検証し、後継43813602799を自動起動した。
結果更新と同じconcurrency groupで待っていた手動gate再試行は定期実行に置換・cancelされた。
候補コードでowner完了通知／正規release pushを結果更新の待ち行列から分けた。
既存のjob mutex、実履歴・原本・counter・source拒否の検査は維持する。
新しい後継の全ZIP独立AES監査と複数日の全件完走は未確認。

**07時頃UTCの追加確認**：後続43813602799は9巡目repeat_completeで停止。
暗号保管庫のmutable参照先を調べるGit ls-remoteの非zeroまで特定し、stderr未保存のため下位原因は未確定。
完了8／準備9、P1 14202239943とRESULT 14203116284の両原本を保全。
真正な定期run43812709551の既存gateを手動で再実行し、別runner133134392902が両原本をAES検証した後に
READY_VERIFIED_RECOVERED_OWNER_CONTINUATION、後継43818666068を起動した。
この再試行は手動介入であり、無人連続復旧の合格にはしない。
既知の不変commitを直接読戻す候補修正を進め、未知のGit/HTTP拒否を無条件に再試行しない。

**全レース×14モデル**：独立P0と生の公式Bからだけ台帳を作り、実generated・取得・物理保存時刻を
予想本文を変えないsidecarへ結合。未到来／締切前待ち／締切超過を分け、120×14=1680の名目分母を保持。
既存3モデルに真正生成時計と入力SHAが欠け、新しい日も最大11/14へ留まる経路を特定した。
さらにALL_MODEL再利用時に入力as_ofをgenerated_atへ投影する旧経路があり、監査の合格には使えない。
新しい推論呼出しの実開始・終了eventを保存する修正を候補へ実装。生成欄へ入力時刻を流用しない。
新原本でlegacy5/5適格、旧原本の3モデルHOLD、旧AES/cacheと予想inventory不変を116Python・7Nodeで確認し、
独立レビューも合格。main側は20試験合格。本番の新しい実レース適用は未確認。過去へ時計を後付けしない。

**Safari**：既存単一HTTP proof jobへstandard無料macOS runnerのnative Safari検証を実装し、
15件の境界試験と独立レビューが合格。同一公開JS/CSSとAES認証済み原本のTop8を操作比較する。
実Safari run、実機iPhone/iPad、8参考画面すべての視覚比較は、この記録時点では未実施。

**映像3項目**：公式の展示日・1Rを通常画面で選択。プレーヤーdocumentは200だが再生APIが403を返し、
「この動画の視聴は許可されていません。」と表示。実映像の取得0バイトで、拒否の個別条件は未特定。
公式が案内したYouTubeチャンネルの通常UIもERR_TUNNEL_CONNECTION_FAILED。迂回・再配信はしていない。
既存RGB rider候補を再学習せず既知の開発用oracle18例へ実推論し、9一致、6艇全正解0/3フレーム。
これは独立した人間正解や自動全画面追跡の精度ではない。6艇継続識別、物理的強さ、動画の未来改善は未達。
録画／3〜6艇／原本等143件の合成回帰は成功したが、実映像の受入へ加算しない。

**実学習**：既存2系統を1回だけfit。真正な過去133レース（train100／内部holdout33）、
最新保存日2026-11-06のP0/P1混合156レースを隔離し、312 RAWを封印後に採点した。
正常確定127レースで相性32→34的中、ST重視33→36的中。残29レースは異常／未確定／時刻不一致の台帳を維持。
両系統のHolm補正p=0.75で、改善・前向き効果・98%は未実証。本番weights切替は0。
別途、404の旧学習artifactと同じtraining SHA42117035の暗号原本を復元し、新receiptで検証する候補を実装。
復旧失敗時は研究候補をHOLDとし、既存baseline予想は継続する。

完成／未完成／外部条件と実証値は [機械可読記録](evidence/boat-completion-validation-20261116.json) に保存。
下の過去記録は当時の状態として保全する。

<!-- BOAT real recovery 2026-11-16 -->
## 2026-11-16: 実原本の復旧と自動P1保存が成功

**実行して合格した部分**：PR164/174/199を本人承認後に通常保護merge。
productionはb491fb21ce58ba085dd8f54bb7326442b840d8f4。
既存の真正main push run43803669261/job133089404811で実orphan P1/checkpointをAES検証し、
原本3点をvaultへ保持・独立読戻しした。最初のgateはHOLD/recovery_required、
復旧後だけREADY_VERIFIED_RECOVERED_OWNER_CONTINUATIONとなり、既存workflowを自動起動した。
原本/完了数/使用量/公式結果を変更せず、復旧時の公式GET・新予想は0。
後継owner43803973248は2026-11-16T04:25:06Zにsource b491fb21/attempt1で実起動。
旧owner43782543906の完了6/準備7、累積11812・当日基点11524・worker70・巡回累積638は
元の記録として保全し、7巡完了や架空RESULTへ変換していない。

**後継の実保存**：朝P0を再利用し、追加P0暗号ZIP14197574600を04:34:26Zに保存。
展示後P1原本14197897453を04:38:08Z、追加モデルP1原本14198425877を04:38:29Zに保存。
両ZIPをこの環境から再取得し、GitHub metadataのSHA/サイズ/run/headと一致することを検証した。
最初の巡回は04:37:14Z〜04:41:02Zに成功終了。producer内の必須native AES/vault読戻しと
RESULT AESおよびreport読戻しが通り、第2巡も04:43:47Zに成功終了して第3巡以降へ自動で進んだ。原本は暗号化されたまま保持。
新P1の別runnerによる独立AES全件監査、当日全1680slotの達成はまだ証明していない。
新P1の件数・予想精度をZIPのサイズやjob成功だけから推定しない。
新巡回RESULTのnested P1と元P1 ZIPのbyte一致の独立検証は未実行。

**画面・結果の実再検証**：run43804655533/job133092532108が合格。
選択した保存済み2日分で公式GET212、結果sync276レース、変更42件、confirmed194・held12・pending70、
新しい結果観測35件。予想入力や原本は変更していない。Chromeで3つのスマホ/PC幅を操作し、
当日結果47件、P1表示21group、根拠3view、upcoming row訪問180、モデル切替時の原本照合6回を確認。
group/訪問/照合回数を固有モデル数・固有レース数へ換算しない。private contextはgeneration334。
P1通常モードで、指定P0原本の個別probeは未指定（expected_original_matched=false）。
原本hash/Top8等の通常表示照合と、この未指定probeを混同しない。
実機Safari、8参考画面すべての視覚比較、新P1の別runner AES全件監査は未確認。
詳細な実行/段階証拠はevidence/boat-orphan-p1-live-recovery-20261116.jsonと後続追記を参照。

**未完成**：全日120レース×14モデルの1680slot充足、無人での次workerへの継続、
実機Safari、映像3項目の全受入、前向きな予想改善と98%の実証。
既存の45slotと別ownerの27slotは重複範囲を解かず合算しない。
実機Safariは実機接続が必要。新しいvendor/課金/PR/job/cron/モデル系統/投票は追加していない。
ソースSHAの追加変更は実行中のproducerへ適用せず、旧PC monitorは停止状態を維持する。

以下は各時点の履歴であり、現在の状態は先頭の追記を参照する。

<!-- BOAT independent original readback 2026-11-16 -->
## 2026-11-16: 中断予想の別runner読戻し合格、後継起動は確認中

PR164の実sourceはb491fb21、PR174の実mainはce33c976。別runnerの実監査43802953053が成功。
中断owner43782543906のP1を含む原本を認証し、6/7・累積11812・当日基点11524・worker70・
巡回累積638を改変せず記録した。native P1は3レース/15slot。4個の実ALL_MODEL ZIPを
SHA/AESで再読込し、正式な締切前27slotがsaved AES原本と一致。全日1680slotの完成ではない。
[独立読戻しのcountsとSHA](evidence/boat-orphan-p1-independent-readback-20261116.json)。

PR174では既存の起動対象fileが変更されず、release launcherは走らなかった。
既存PR199の履歴を保全したdocs差分でowner-pdca-main-trigger.txtを更新し、既存経路を実行する。
新規workflow・job・cron・event・権限は追加しない。実checkpoint AES復旧、vaultへの3原本保持、
新workerと累積11812からの増分、新たな締切前P1保存はこれから確認する。
映像・全レース×全モデル・無人継続・実機Safari・精度改善・98%は未達のまま。

<!-- BOAT recovery update 2026-11-16: latest facts precede preserved history. -->
## 2026-11-16: 実画面の合格と自動予想復旧の状況

本人の「承認する」に基づき既存PR302/289/286/143/164を保護ルールに従って統合済み。
本更新前のmain実HEADは78b2847145e20293ea6c154df38918e726ebc133、
producer実HEADはb491fb21ce58ba085dd8f54bb7326442b840d8f4。

**実データで合格した部分**：結果バッチの実経過時間を加えた読取版b9a1451dfを
既存PR143で反映。実Actions run43790076944の結果取得とChromeブラウザ操作が成功した。
選択した保存済み2日分で公式GET179、結果sync276レース、変更22件、confirmed162・
held10・pending104を記録。ブラウザでは当日結果15件、native P1表示14group、根拠3view、
スマホ幅・PC幅を跨ぐupcoming row訪問180を原本と照合した。group/訪問数を
固有モデル数・固有レース数に数えない。実機Safariと8画面すべての視覚受入は未確認。

**現在の停止原因**：owner43782543906はP1第7巡14189866940を保存した後、
GitHub ARTIFACT_METADATA 404で停止。CONTINUITY14190011394とSOURCE_CONTROL14189372943の
ZIP/SHA照合では完了6・準備7・累積GET11812・当日基点11524・当該worker70・
完了巡回累積638。第7巡のRESULTは存在しない。公開counterの照合だけでは
実AES復旧の合格にしない。callbackは到着したが、旧helperのschedule限定と
RESULT必須条件で復旧が失敗していた。予想が現在稼働中とは報告しない。

**既存PR164/174の修正**：AES/public/canonical first receiptを検証して孤立P1と
最終checkpointを保持し、完了数・使用量を変えずに後継workerへ引き継ぐ。
保存直後のmetadata404だけに現在runのupload receiptを使った限定再読込を実装。
真正callback/release-pushの認証と、日内引継ぎで朝のP0原本を再利用する参照を修正。
修正候補は全live pin23箇所を実production SHAへ同期済み。ローカル120件が合格。
実AES runnerでの14189866940検証、新worker起動、累積11812からの増分と新たな締切前P1保存は
本記録時点では未確認。過去の予想・結果・待機clock・使用量を改変しない。

既存の6つのALL_MODEL ZIPの独立AES読戻しで、正式な締切前45slot（9model×5race）を
saved viewと照合済み。別のnative25slotには適格性/生成時刻のview証拠不足があり、
合計70合格とはしない。当日120レース×14モデル=1680slotの全日充足は未証明。
映像3項目、無人の継続引継ぎ、予想改善の前向き実証、98%も未達。
新規課金・新service・モデル系統・Issue・PR・job・cron・投票は追加しない。

<!-- RACE_AI_BOAT_CLOCK_RECOVERY_20261116 -->
# 2026-11-16 JST｜再接続後の実確認：P1独立AES合格、結果取得の時計修正を反映中

- 本人承認後に既存PR302/289/286を通常merge。production84128e0、main65743d13をGitHubから再確認。
- 実監査43783302118で新owner43772481781の6 ZIPを別runnerがSHA/AES/元内容で照合。
  追加9モデルの45枠は公式締切前で画面原本とも一致。全日分母120×14＝1680は未完走。
  通常5モデルの25枠は別の原本監査で確認したが、旧表示schemaのmetadata欠測を補完して加算しない。
- 次owner43782543906は09:59:03 JSTにP1を保存した後、10:12 JSTに7巡目で失敗した。
  実エラーはVaultのARTIFACT_METADATA読取404。最終controlは完了6・準備7・使用70・累積11812・
  当日基点11524・巡回累積638。署名済みcontinuity/source-controlのZIP/SHAが一致し、改変していない。
  callback43784862364は真正なworkflow_runだが、復旧helperがschedule専用で拒否した。
  当該失敗にはP1だけが保存されRESULTが未保存の可能性があり、完了扱い・counter reset・盲目的な再実行をしない。
- 結果画面受入43783346260はINTRADAY_CAPTURE_CLOCK_INVALIDでbrowser前に失敗。
  9分の取得処理を開始時刻＋5分で検証していた実不具合を再現し、応答までの実経過時間を使うよう修正。
  未来時刻の許容5分、元の取得時刻・queue時点・取得拒否・保存処理は維持する。
  修正sourceはb9a1451df474e52d95bd40253676365c4fa0940d。既存b47との差分は時計と2回帰試験の2ファイルのみ。
  427秒の正常取得がRED→GREEN、301秒先の未来時刻は拒否。関連48件とsource独立レビュー合格。
  main caller44件も再接続後に合格。既存PR143で実SHAをpinし、同HEAD CI→main反映→実取得/browserを続ける。
  source commitは既存PR143の履歴に保持し、mainの実treeは呼出し・テスト・件数/SHA文書だけを変更する。
- クラウド切断から復旧し、修正commit・証拠を確認。予想workerの停止操作はしていないが、上記の実失敗により
  新しい予想workerは未稼働。G1復旧、無人handoff、全件coverage、画面、映像、前向き精度改善は未完了。

新PR/Issue/branch/workflow/job/権限/スケジュール/モデル系統/課金・投票・予想原本改変は0。
98%は未達・実現可能性未証明。[件数・SHA証拠](evidence/boat-approved-restart-live-20261116.json)。
以下は以前の記録として保全する。
<!-- /RACE_AI_BOAT_CLOCK_RECOVERY_20261116 -->

<!-- RACE_AI_BOAT_LIVE_RESTART_20261116 -->
# 2026-11-16 JST｜承認済み本番復旧：新P0/P1の自動保存を確認

- **本番適用済み:** PR #302をproduction `84128e0ec8bd9fe3da64ad49f74b8511b07e72be`、
  PR #289をmain `ea8965bd49955f5d1e204ca318cf9c542352f345` へ通常merge。いずれもレビュー済みtreeと一致。
  このチャットで本人承認を受領済み。
- **実障害原本の独立AES合格:** main run43772458812/artifact14185455502で、停止したowner43683174565の
  AESと公開counterが一致。累積11524・当日引継ぎ452・失敗worker取得0・巡回累積608を保全。
- **自動実行を再開:** main起動43772458763からowner43772481781を一writerで開始。
  前回失敗した追加P0の恒久保存が今回は成功。08:20:46 JSTに通常P1、08:24:08に全モデル側P1の
  新しい暗号ZIPを確認し、GitHub SHA/サイズを再検証した。
  ownerは24巡を完了して成功。最終受領証のGET累積11742・当日基点11524・当該worker218、
  巡回累積632を確認。新P1の全件数・独立AES・公式締切照合は別runnerで確認する。
- **次workerは検証付き補助起動:** 完了後の真正なworkflow_runが未着のため、実GitHub原本の
  continuity/source-control ZIPを照合し、実時刻の既存gateが
  `READY_VERIFIED_SAME_DAY_CONTINUATION` と判定してから、owner43782543906を09:48 JSTに開始。
  同じproduction SHA・単一writer・カウンターを維持。無人の自動引継ぎ成功とは数えない。
- **結果更新は一部成功、画面は未合格:** 既存受入run43778358422は結果更新が成功し、
  選択済み2日分で9レースを変更、確定149・保留9・未確定118を報告（当日だけの数ではない）。
  表示context世代314は生成できたが、ブラウザは `SAVED_SITE_BROWSER_CHECK_FAILED`。
  旧readerの診断が不足しており、原因を断定しない。
- **既存PR #286で修正・再検証:** 旧12件固定を残すcollector呼出しを検証済みb47へ更新。
  通常のP1画面確認を承認済みproducerと同じ84128のreaderへ合わせ、過去P0専用0796は保全。
  ローカル74/37/31件と独立レビュー合格。既存の独立監査jobのmain push対象を、過去ownerから
  完了済みの新owner43772481781へ更新し、実鍵の新P1監査を実行する。
  次は同HEAD CI・main適用・実画面再試験。
  稼働中producer、job数、権限、スケジュール、モデル係数は変えない。

新規PR/Issue/workflow/モデル系統/課金・投票・原本改変は0。
G2〜G8、映像3〜6艇、前向き精度改善・98%は未合格。以下は以前の記録として保存する。
[件数・SHA・失敗を含む今回の証拠](evidence/boat-approved-restart-live-20261116.json)。
<!-- /RACE_AI_BOAT_LIVE_RESTART_20261116 -->

<!-- RACE_AI_BOAT_OWNER_APPROVED_RELEASE_20261116 -->
# 2026-11-16 JST｜本人承認済み：BOAT本番復旧リリース

本人がこのチャットで「承認する」と回答。既存PR #302のproduction統合、実HEADへ同期した
既存PR #289のmain統合、自動予想の再開・独立読戻しが承認された。
追加の確認待ちではない。無断の一般公開・モデル係数切替・新規課金・投票は含まない。

- **production統合済み:** PR #302、実HEAD `84128e0ec8bd9fe3da64ad49f74b8511b07e72be`。
  GitHubから読戻し、レビュー済み0db526870とtreeが完全一致することを確認。
- **mainの固定SHAを同期済み:** 6ファイル22箇所を上記実HEADへ変更。
  履歴原本の読取専用5d1dabffは保全。ローカルmain gate74件、独立AES reader37件成功。
  実HEAD同期後のCIも成功。既存のmain release push起動経路で最初のworkerを開始し、
  main統合・真正な別runner実行・新しい予想保存を続けて確認する。
- **未実証:** 実障害のAES復旧→新worker→新P1保存、全レース/モデルの連続完走、
  新結果→PDCA→画面の一巡、映像・精度改善。合成試験を実レース成功へ数えない。
- **保全:** 原本変更0、新PR/Issue/workflow/外部サービス/課金0。旧PC常駐monitorの再起動なし。

[承認後リリース証拠](evidence/boat-owner-approved-release-20261116.json) /
[既存PR #289の最新Checks](https://github.com/haji84/RACE-AI/pull/289/checks)。
以下は承認前の検証記録であり、そこでの「承認が必要」は過去の状態。
<!-- /RACE_AI_BOAT_OWNER_APPROVED_RELEASE_20261116 -->

# RACE-AI 最新状況（2026-11-16 JST）

BOAT最終引継ぎのG1を優先し、実障害の原本調査からコード修正まで進めた。
**本番の新予想再開・映像完成・98%達成は、まだ宣言できない。**

## 完了した作業

- 既存PR #302のHEAD `0db526870a509cd6e68c44e693ed3e73d3b0e50f` に、
  当日使用量を引継ぐzero-round復旧、巡回途中に残った旧240件制限の撤去、
  VaultのGit fetch判定と秘密を出さないタイムアウトを実装した。
- 同HEADでGitHub CI3系統成功。owner324/46/3/12件、復旧140件、Vault75件成功。
  範囲に重複あり。本番producerはPR上でskipped。
- 既存PR #289へmainの最新96e0045ffを取り込み、05:30 JST早期起動を保全。
  mainのzero-round受理不足を修正し、本番固定SHA22箇所を候補へ同期した。
- 過去原本の再検証は実runのSHAと受領証・予想のsource SHAを厳密照合する。
  失敗runのAES checkpoint専用読取も既存監査jobに接続。main gate74件、
  独立したmatrix/exact/failed-AES37件のローカル試験成功。実鍵の監査はまだ未実行。
- PR289コードHEAD `80b3b81f7ddb8e79a7d6f751d621043022ae7fbe` でもGitHub全12チェック成功。
  [復旧gate69件](https://github.com/haji84/RACE-AI/actions/runs/43770742038)、
  [独立原本読取37件](https://github.com/haji84/RACE-AI/actions/runs/43770742073)、
  [既存mirror205/30件・結果31件・起動44件](https://github.com/haji84/RACE-AI/actions/runs/43770742201)が成功。
  範囲は重複する。本番のAES・取得・dispatch jobはPR上でskipped。
- 実障害と前workerの5 ZIPのGitHub SHA・サイズを再検証し、使用量11524/11072/0、
  巡回累積608を保全。歴史時刻での再現は現在のdispatch許可にはしない。

## 未完条件

| Gate | 現在の状態 | 残る実証 |
| --- | --- | --- |
| G1 | コード・PR302 CI合格、本番HOLD | 真正な別runner AES復旧→次worker→新P1物理保存 |
| G2 | 既存PR302の検証処理あり | 真正な締切短縮/延長と実保存の独立照合 |
| G3 | 早朝起動のコード・ローカル試験合格 | 日付handoff・初レース欠落なし・継続実運転 |
| G4/G5 | 過去原本の一部監査あり | 新しい全国適格race×model分母と全P0/P1の独立AES照合 |
| G6 | 既存原本の表示実証あり | 新公式結果→PDCA→Pages→実画面の全件一巡 |
| G7 | 研究継続、実データ合格待ち | 3〜6艇の継続識別・動作の強さ・締切前映像P1 |
| G8 | 未合格 | 複数開催日の連続運用、未予想率、未来A/B精度改善 |

過去の締切不一致9モデル枠はHOLDを維持。98%は未達・実現可能性未証明。
この作業で公式provider GET0、新規予想0だが、当日全体の実績が0という意味ではない。
未取得の最新全件数は不明として扱う。

## 本人承認が必要な工程

productionは `5d1dabff0ab9bb83132cd7fbdd43f49fb4eef6c4`、mainは
`96e0045ffb3a8368c4f63cb955564bb4e6259c0e` のまま。
従来の無断main統合・本番切替禁止、および正式引継ぎ§6に従い、まだ更新していない。
PR302統合後の**実production HEAD**を取得し、PR289の固定SHAを再結合・同HEADでCI確認後に
mainへ統合する必要がある。現在のPR289の候補SHAをそのままmainへ入れてはならない。

新規PR/Issue/workflow/課金・一般公開・投票・予想原本改変なし。
旧ローカル常駐monitorは再起動しない。

[詳細・リリース順序](RACE_AI_BOAT_RECOVERY_20261116.md) /
[件数・原本/テストSHA証拠](evidence/boat-main-zero-round-release-preparation-20261116.json)
