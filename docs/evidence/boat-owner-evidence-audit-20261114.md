# RACE-AI 本番復旧・全国P1・映像予想 引継ぎ
記録日：2026-11-14 JST。次の作業では必ず最新main/production/PR/CIを取り直す。

## 1. 本番へ反映した復旧
PR #275のproduction統合先は `203ca70a2ea04124b2cb0ceba9dc4bdad7cc8da9`。PR #276のmain統合は `34a64cc2c6e5132c8f4459ee4d05e0d41845f7a8`。mainのRELEASE_SHAとproductionの実HEAD一致を再取得して確認した。producer実テスト43471307499、mainの起動・復旧条件テスト43473569083/43473568674は成功。適用時にproductionの実行中・待機中ジョブがないことも確認した。

今回の復旧は同じ読込の再試行だけではない。同日に失敗したownerが保存したP1、RESULT、最終チェックポイントを認証し、取得済み原本の保管と独立読戻しを確認して、次の既存workerを起動できる接続。失敗した実行や原本を成功扱いに書き換えず、別の復旧証拠を作る。取得回数、日単位の起点、予想・保存時刻、SHA、単一writerを引き継ぐ。

未保存・破損した原本、取得拒否や待機状態、取得回数不明、キャンセル、コード版の不一致、他writer稼働中などはHOLD。どんな障害でも無条件で復旧できるという保証ではない。実レース時間帯に失敗したworkerから復旧し、その後の新しいP1生成まで成功した本番証拠はまだない。

## 2. 実原本監査が成功
PR #277で原本監査を追加し、PR #278で監査自身の前提誤りを修正した。最終main実行SHAは `bf630030b12678e0d1fa8979279bded9cf2b6993`。監査の対象は2026-11-13 owner run43348227701、元SHA `0796b52c2804177976e4c2e5ab9b65f32589720b`。過去時計を作らず、実際の監査時計2026-11-13T18:24:53.938456+00:00で認証した。

成功run: https://github.com/haji84/RACE-AI/actions/runs/43482296813
成功job: 132081795393。unit job132081593439も成功。
物理成果物: artifact14065946048、boat-owner-evidence-audit-43482296813、ZIP1210bytes。
GitHub記録とダウンロード実体のSHA256一致: `c51cb79404f30ac5d37aa5aae5e2c3a3b90408dc32af16d37858e52ca957a136`。
保存した集計原本: `docs/evidence/boat-owner-original-audit-20261113.json`。

保管済みの公式B資料そのもの、P0原本、物理保存証明を既存の読戻し器で検証した。公式資料SHA256は `98df6c09c74c334ae6f1e6ecb0c1b17b153c747f70dba288c9ba7543fe39b3ec`。新規の公式提供元GET、予想生成、原本変更はいずれも0。

### 確定した集計
- 公式開催資料の分母：13場156レース。従来の136は保存済みP0レース数で、全開催分母ではなかった。
- 基本P0原本：136レース。公式分母との差は20レース。
- 基本P1原本：9レース、3つのP1成果物。公式分母に対するP1未確認は147レース。
- 未確認147件の最終記録：21件はALREADY_CLOSED_BEFORE_SCHEDULE_CAPTURE、126件はNO_RETAINED_OBSERVATION。
- 21件は当該P1巡回で時刻判定を通過できなかった記録。全て同じ理由でP0も欠けたとは言えない。
- 126件は保存されたレース別試行記録がない。展示未公開、展示取得拒否、モデル故障と断定しない。
- 展示公開の事前証拠があるのはP1保存済みの9件。残る147件のP1適格性は不明であり、147件全てが適格予想の失敗だと決めつけない。
- 初期開催資料とP1原本の締切が異なるレースが1件。両方の原本時刻を保存し、差異を別計上。全国完成判定には使わない。

基本原本のモデル枠はP0が272、P1が45。これは今回の基本モデル読戻し範囲。従来の暗号保存画面の680/126は追加モデルも含む別範囲なので、不一致・予想消失と混同しない。全モデル完成は引き続き未確認。

### 第3巡の実データ対応
P1原本、RESULT内のP1バイト列、結果報告のSHA、run/head/day/round、最終チェックポイントの取得回数が一致した。状態はPENDING_PAIR_BOUND_TO_FINAL_CHECKPOINT。
completed_round=2、prepared_round=3、requests_used=88。lifetime_requests=9935、day_start_lifetime_requests=9847で差88。回数の初期化はしていない。

これは実原本を使った復旧に必要な対応関係の確認。読み取り専用の監査であり、11/13の失敗runを成功にしたわけでも、当日の第4巡や新しいP1を実行したわけでもない。監査出力のsuccessor_dispatch_allowedとlive_recovery_to_new_p1_provenはfalseのまま。

## 3. 映像の実態
今回読んだ11/13の3つのP1原本では、認証できた映像由来の予想は0件、映像関連拒否行も0件。範囲はSELECTED_OWNER_P1_ORIGINALS_ONLYであり、全履歴・全保存先の不存在は主張しない。

既存映像入力経路も調査した。旧認可branchのworkflow_dispatch履歴で確認したrun42147537641（2026-11-06）は、job127662552101が全体successでも、実出力はHOLD_OWNER_STATE_KEY_REQUIRED、ready=false、context_count=0、artifact_receipt_verified=falseで、暗号コンテキストuploadはskippedだった。これは当時の記録であり、今のowner鍵が未設定だという意味ではない。今回のAES原本監査では鍵を使った読戻しが成功している。

通常P1の展示数値取得と、展示動画の取得・解析・予想反映は別経路。動画の自動取得、全編の非公開保管、艇の識別・時刻・同条件比較の検証、締切前に独立保存された映像特徴を既存モデルへ渡す本番一巡は未完成。既存読込器や研究用特徴コードがあるだけで実映像を見た予想と呼ばない。

## 4. 全国P1の残る構造的障害
production203ca70のrepeated_cycle.pyはSOURCE_LIMIT240、ROUND_SOURCE_LIMIT45を維持。boat_nationwide_ab_pilot.make_pairの通常経路はracelistとbeforeinfoの2取得を各レースで行う。従って同経路で156レースを全て一度ずつ処理する前提なら最低312取得となり、240を超える。開催一覧・再確認・結果・任意の履歴取得は別なので、復旧だけでは全国完成にならない。

次は取得枠を再起動でリセットしたり増やしたりせず、既に認証・保管された番組と静的データの再利用、必須展示データの優先、締切直前の同一性確認を設計・実装する必要がある。展示や欠場、進入、締切の現在情報を古い情報で置換しない。今回この取得経路の最適化コードを本番へ出したとは主張しない。

## 5. 修正・テスト記録と次工程
最初の監査run43480965620は、新規集計器が初期番組とP1の締切一致を強制し、OWNER_AUDIT_FORECAST_CLOCK_INVALIDで失敗した。既存原本の改変や予想エンジン失敗ではない。原本ごとの厳格な締切・保存時計を維持して差異を別計上し、実際のcandidate_attempts項目を読むよう修正。17件の集計テストをローカル実行して全件成功し、GitHubの正確なPR HEADでも43482009344が成功。その後の実原本監査43482296813も成功した。

次の優先順は、(1) 最新owner実行で本物の復旧証拠と後続P1原本のつながりを検証、(2) 156等の公式全開催分母でP0/P1の不足を残したまま取得重複・任意処理の優先度を修正、(3) 実映像の非公開取得・解析・締切前保存・モデル反映を接続すること。新しいチャットでもこの証拠を読み、監査文書を増やすだけでなく未完成の実装から進む。

完了：失敗owner復旧の本番接続、復旧条件と回帰テスト、実公式資料に基づく分母と基本P1不足の確定、実第3巡の原本・取得回数対応確認。
未完了：実時間帯の障害復旧から次P1生成までの本番成功、全国全モデルP1完成、実展示映像を使った予想完成。

## 2026-11-16: 中断ownerの独立読戻しと既存起動経路

以前の240/45取得枠は歴史記録。現在のproduction b491fb21は件数の固定上限を追加せず、
原本と使用量を保持する。PR164/174は本人承認後に通常保護merge済み。
別runnerの実監査43802953053/job133087189515は成功し、故障owner43782543906を読戻した。
canonical朝P0は120レース。native P1は3レース/15slot、全14モデルの当日分母は1680slot。
未完了controlは6/7、累積GET11812・当日基点11524・worker70・巡回累積638を保ったまま
HOLD_INTERRUPTED_ROUND_PARTIAL_AUDITを出し、dispatch/full coverageは許可していない。
さらに4つの実ALL_MODEL ZIPをSHA/AESで再読込し、正式な締切前27slotをsaved AES原本と照合。
違うrunの45/27slotを合算して全日充足とはしない。予想原本・結果・clockは変更していない。

PR174では既存push対象owner-pdca-main-trigger.txtが変わらず、release launcherは未実行。
既存PR199の旧proposal履歴を保全したdocs差分だけで、この既存対象fileを変更する。
新event/trigger/job/cron/権限は追加しない。真正なmain pushで実AES復旧を検証し、
後継workerの最初の使用量と新しい締切前P1保存を確認するまで再開成功にはしない。
実checkpoint AES復旧、新worker、映像・全日coverage・実機Safari・精度改善は未確認。

## 2026-11-16: 実orphan復旧と後継起動

既存main push43803669261が実AES/原本保持を完了し、source b491fb21への既存gateが
READY_VERIFIED_RECOVERED_OWNER_CONTINUATIONを返した。復旧で予想・RESULT・公式GETは生成せず、
旧6/7と11812/11524/70/638を維持。後継43803973248が04:25:06Zに自動起動した。
復旧直後04:25の時点では、原本・待機clock・counterを保全し、後続の実P1/結果は確認中だった。

後継43803973248は第1巡を04:41:02Zに正常終了し、第2巡へ自動進行。
P1原本14197897453（04:38:08Z）と追加モデルP1 14198425877（04:38:29Z）の
実ZIPを外から再取得し、SHA/サイズ/run/head/暗号化memberの一致を確認した。
producer内のAES/vaultとRESULT AES/report読戻しは必須stepを通過。
この新P1の別runnerによる全件AES監査は未実行で、件数や全日充足を推定しない。

新巡回RESULTのnested P1と元P1 ZIPのbyte一致を独立検証したとは主張しない。

実画面再受入43804655533は04:45:17ZにChromeの3幅で合格。当日結果47件、P1表示21group、
根拠3view、upcoming行訪問180、モデル切替の原本照合6回。group/訪問を固有数へ換算しない。
公式GET212で保存済み2日分の結果sync276レース、changed42・confirmed194・held12・pending70、
新観測35を記録。予想入力・原本を変更せず、private原本や鍵を公開していない。
実機Safari、8画面の完全視覚比較、新P1別runner AESと全1680slot・映像・精度改善は未達。

## 2026-11-18: 保管修正後の実運転と受信時計の修正

この節以前は記録当時の証拠として保持する。現在の要約は
[最新状況](../RACE_AI_LATEST_STATUS.md)を参照する。P0保管失敗43829249080は
履歴のまま残し、後続A74の24巡/73 AES原本/23 ALL_MODEL ZIP/P1 513行照合を
[独立監査](boat-main-sync-closed-a74-actual-20261118.json)で区別する。

直近A74 worker44252479726は自然完了したが、24成功stepの実control巡は14、
追加生成が正数なのは8巡である。[完了scope](boat-a74-continuation-final-20261118.json)。
保存PROGRAM原文のSHA/URLは存在し、要求された取得時計だけ結合しないため
厳密HOLDを維持する。[実時計結合](boat-current-pair-program-clock-binding-actual-20261118.json)。

将来分の修正source995は880件等の実回帰成功後に通常mergeされ、main7003は
368+7件等の実回帰成功・独立review後にそのexact SHAへ同期した。原本・生成時計・
2秒待機・日付guard・counterは保全した。13:06:27Z、既存launcher44310274907/
job134822293251がREADY_VERIFIED_SAME_DAY_CONTINUATIONを記録し、既存経路で
source995の実worker44310358995が起動した。[修正と継続の証拠](boat-http-receive-clock-source-main-sync-20261118.json)。
新workerの実受信時計結合・新予想保存は未確認。起動成功を全原本再認証、
全レース/4競技/T15-10完遂・実機iPhone・6艇精度・前向き改善と呼ばない。

この追記は従来のowner監査証拠を最新の実証へ接続する。既存source-free unitの
対象文書であり、job/input/cron/権限/runner/timeout/marker/prefixを追加しない。
中立的なdocs mergeで追加owner起動、provider GET、UI公開や重み切替を要求しない。

### 2026-11-18 13:22 UTC: 反映後の再監査と第1巡への到達

main7003の既存監査44310274869/job134822293517が実完了success。固定旧A74の
73AES/23ZIP/513一致・4/19欠落と、13:16:36Zの厳密PROGRAM時計結合HOLDを再確認した。
source995後続44310358995は13:22:01Zに30step成功/失敗0、第1巡実行中へ進んだ。
追加P0の封印/読戻し保管/保存receipt長期保管等のstep成功はmetadata証拠であり、
件数・新規capture時計一致・第1巡保存完了はまだ不明。
[時刻付きの実証と限定](boat-source995-post-merge-actual-20261118.json)を保持する。
過去原本・予想・時計・counter・HOLD・本番重み・公開UIを変更しない。

### 2026-11-19 00:09 JST: 実行環境復旧と承認外sourceの停止

ローカルコマンド/GitHub認証/既存branchへの通常pushが実成功した。
[環境と4競技30セルの検証](race-ai-local-runtime-resume-and-native-roster-20261119.json)を保持する。
承認対象外Kdreamsと旧mobile hostはtransport前に拒否し、過去HTMLはoffline解析を維持。
[138件/skip0と独立reviewの診断](keirin-approved-source-local-diagnosis-20261118.json)を参照する。
WINTICKET403・真の全日生成・実iPhone・実6艇校正・前向き改善は依然未完了。
この中立的な修正/文書mergeはowner起動、UI公開や本番重み変更を要求しない。

[main統合テストの固定記録](keirin-source-guard-main-verification-20261119.json)は、既存PR22の同一runtimeに対する40件・起動138件・独立review48件の成功を保持する。source拒否を実取得成功へ置き換えていない。

### 2026-11-19 01:49 JST: 実source mergeとmain参照の同期

既存PR21の通常merge fbc743be548bfd123e46cdbfe290515a59e5e0d3 はtested tree1068d5a0d1225e0638a31528f8031a5b8e9fc584と一致。既存CI44348357932は882/223件等とNode29件が全成功し、実apt-mirrors.txt漏れの修正後は公式HTTPS62.8MBを25秒で取得した。
[main実SHA同期](boat-main-exact-clothing-source-sync-20261119.json)は138/372件、統合206件、独立145件が成功。旧role・固定recovery契約・3reader・M2 target・全日guard・原本を保持する。既存prefixとmarkerのみを使い、通常main merge後の実ゲート判定まで起動を成功扱いしない。
995の実完了は69stepだが4巡/追加生成0。競輪は[実44342598507](keirin-main758-actual-source-hold-44342598507-20261119.json)で拒否/制限停止、fe7のexact403単独は不明。[未公開候補の固定検証](boat-native-reviewed-candidate-pin-20261119.json)は実Safari/iPhone合格ではない。公開UI・本番重み・投票・元原本変更0。
