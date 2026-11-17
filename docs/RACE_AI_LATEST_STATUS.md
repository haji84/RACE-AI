## 2026-11-17 18:30 UTC: 保存修正を保護付きsourceへ統合、main接続と実運転は検証継続（GOAL未達）

GitHub認証付きAPIでPR #55の最終HEAD `15fc68755e60db3f4e578ef2b8415e4ed909c9eb` のCIを確認し、通常mergeした。実source `bb49215034b779ea1493b35dd91e5c3ebfc04032` のtree `8a97242da13235d3f55f127eb157f514a25d8eca` はCI済みtreeと完全一致。観測mainは `6f77923a5d77712b9471f59fe7f3649fb9e3ca1e`。主要791件/189.401秒、および3・12・38・165・46件とNode検証が成功し、6 checksは成功3/意図したskip3。source16ファイルは元のテストを含め明示転送し、4組の全tree一致を確認してsnapshotの親を保全した。APIで作り直したcommit metadataは元local SHAの復元とは呼ばない。

変更は選択blobの一括取得、全cipherの局所検証、限定transport診断、240件を超えるsource captureの全件事前検査と分割保存/復元/feed接続。AES認証・SHA・時刻・原本全bytes・旧pointer・CAS・途中失敗時HOLDは維持する。localのcapture最終771試験はGit fixture準備14エラーのFAILEDを保存し、fresh CI791成功と区別する。実workerでのbootstrap timeout解消、速度改善、全ラウンド実行、T15〜10充足、4競技全日網羅はまだ証明していない。次の通常owner admissionを既存の窓/guardで検証する。

**別の実失敗:** main6fの回復run44145562084/job134259611249は18:14:05 UTCに `BOAT_GAP_INPUT_BOUND` で停止した。GitHub実行一覧のJSONが512000Bの入力上限を超える経路で、元予想・復号・provider GETのstep前に失敗。現在同等の一覧を再構成した541139Bは失敗した一時fileそのもののbytes証拠ではない。必要4項目へ取得時に射影する修正を検証し、サイズ/件数上限・判断・停止境界を維持する。旧run44096454881にも同じ失敗があり、今回のsource修正が生んだ不具合ではない。

**Safari:** 実Mac44124279358のprivate原本/AES確認成功と、候補598の環境guard停止によるjob全体失敗/artifact0は両方保存する。main6fにある診断はまだ実Macで未実行。現行85試験に復元した元6試験を追加して両方の全ケースを保持する準備を行った。候補UIの公開はせず、公開asset f603、Draft #62の候補598を保持する。物理iPhone・本人login・current V5・全8参考の受入は未確認。

**引継ぎ保全:** PR70 `b7380fe6a377e6ccf2b96331f2126c52549bbe17`、PR292 `daae4c10167224b7730006d8ada5ade398aaa64b` は取得できず未復元。別環境の未push fileが自動移転したとは扱わない。映像6艇の独立GT/校正、適用可能全既存モデルの全レース網羅、独立した前向き改善の実証は未完了。実14 pairは1 race、qualified0/分母nullのまま。owner key・private原本は持ち出さず、新PR/課金/モデル系統/本番weights/投票は追加しない。実行環境のprocess不足を理由に他作業や原本をkill/resetしない。

詳細: [source merge evidence](evidence/boat-source55-normal-merge-proof-20261117.json)。

**このmain候補の追加検証:** test-first HEAD9bb6406d3fc06fa35d7961451f6ca9bd63ad5667の41 checksは、期待した失敗3・成功14・skip24で完了。新native module欠如（150試験/error1）と未縮約JSON（10/40試験、同じ21 subtest失敗）を実CIで確認した。次に4項目射影と固定Safari callerを追加し、実装HEADの全CIを必須とする。callerは既存owner dispatchの最後に置き、UIの失敗や通信待ちがP0/P1復旧を遅らせない。callerの204受付は実Mac合格ではなく、POST不確実時はrequest=null/attempted=true/ack=falseのHOLDとし再送しない。元6ケースとAPI6ケースの両方を保持したnative91試験を実行する。詳細: [実RED](evidence/boat-main52-actual-red-20261117.json)、[実装検証](evidence/boat-main52-runtime-integration-20261117.json)。

## 2026-11-17 17:38 UTC: 実Safari私有原本/AES成功を保全、環境guard診断をAPIで復元（GOAL未達）

観測main2641abcd/source f55351dc。実Mac44124279358/job134183698968は、Safari26.6で保存view generation422/results114/native P1 groups11を確認した。
1440/390px、元予想4比較・native P1詳細2・結果/予算2、別seedのブラウザAES2比較と4拒否、private session/driver後片付けが成功。
このprivate stepはsuccessだが、後続の候補598撮影stepがmain1442の環境guardで停止し、job全体failure/artifact0。
候補UIのSafari受入、物理iPhone、本人account login、current V5継続、全8参考の合格とは扱わない。

**診断のAPI復元:** 実行環境が32,049 zombie/PID1 tailの状態となり、Gitのfork/DNS threadと補助commandも失敗した。
環境resetや他作業の停止は行わず、保存済みcommitを保全。GitHub APIから同じ基底ファイルを取得し、
local cf9bdafdのruntime差分をblob9ad8a660として復元した。許可env6キーは維持し、未知キーは全てHOLD。
診断は件数と固定6 OSキーの真偽だけで、未知キー名/値/パス/資格情報は出力しない。実際の未知キーは未特定。
local作者85件・独立85件/76同値probeは通過済み。元の追加test原文は転送できていないため、
公開側は既存79件を保持し、同じ拒否・秘匿条件を検証する6件を追加した。local全tree一致とは主張せず、公開側の最終HEAD CIで確認する。

**source修正の保全:** 選択blob一括取得349480cd、全モデル保管640b7e92、複数capture bundle6f8de877、
歴史origin互換82c9b862はlocal commitとして保存済みで、今回のAPI転送は未完了。
captureのfinal local771件は14件のGit fixture準備エラーでNOT_GREEN。focused38・独立38+43+4とpre-final770の成功を区別する。
現sourceはf553のまま。次workerの実速度、全4競技全日/全モデル/T15〜10、公式締切/G8・前向き改善は未合格。
14比較pairは独立1レース、24原本AESは別の真正push監査であり、今回のMac/CIの合格数へ混ぜない。

[実runとAPI復元の範囲](evidence/boat-native-private-success-candidate-env-hold-20261117.json)。
公開f60308ef/本番weights/元work/KEIRIN default-OFF/原本を保持。新PR/モデル系統/課金/投票0。
元環境のb7380fe6/daae4c10はUNRESTORED。以下は過去時点の記録として保持する。

## 2026-11-17 16:12 UTC: スマホ幅のnative select準備を修正、実Safari解消は確認待ち（GOAL未達）

実main69ba791b/source f55351dcは保持。既存PR56へe6876403の2file修正を結合した。
公開f603/同一b496 fixtureで、1440×1000の履歴欄は画面内、390×1000では下端1042pxで画面外となる前提不備を再現。
親selectとoptionの一意性・接続・有効性・表示を確認し、既存scroll/hit/native clickで親を準備した後、
同一の親が画面内/hit/focusを満たす場合だけnative optionクリックへ進む。選択済みも省略しない。
値の厳密読戻しと全4モデル/元予想比較、成功parser、private/AES/seed拒否、session削除・driver終了、workflowは維持する。
JSによる値設定・change送出・retry・受入条件の緩和は追加していない。失敗診断は型検証済みの真偽・件数だけ。

作者79件/14.197秒、独立79件/13.946秒、統合先79件/14.286秒がsuccess。独立レビューCLEAR。
公開fixtureの正確な新JSでも1440/390のpreflightと操作後readbackを確認した。
これは公開合成fixtureの前提不備への修正で、実44115451343のprivate側の原因確定・解消・候補UI実Safari合格とはまだ扱わない。
最終HEAD CI→通常main merge→同HEADの既存native Macを1回実行して確認する。
source pin/marker/owner起動は変えず、公開f60308ef/本番weights/原本/他作業を保全。新PR/job/権限/input/runner/cron/課金/投票0。
[候補と実証範囲](evidence/boat-completed-m2-current-pairs-aes-20261117.json)。以下は過去時点の記録として保持する。

## 2026-11-17 15:58 UTC: M2最終controlを含む24原本と14比較pairの実AES成功（GOAL未達）

実main69ba791be0dfb2a07a33cd6e5acab2befb236d43/source f55351dce855177a51330f72c37d6238ba2c9e3e。
既存PR57は最終ea20bc2fの全26 checks（success12/skipped14）とlocal結合210件の後に通常merge、tree完全一致。
GitHubのpair関連138件もsuccess。main push44115394347のHTTP確認はsuccess。

**当日比較pairの実独立監査:** run44115395767/job134151946786がsuccess。training原本1、比較pair archive1の
14初回保存model-cell組とRESULT journal10個を別runnerで認証した。元/学習版の組は独立1レースに対応し、
journal確定結果とのjoin14、欠落/保留/重複pair0。14レースや勝率改善と数えない。
294種類のRESULT revisionと重複観測2384は履歴の件数であり、独立レース数へ足さない。
原公式source/公式締切はUNKNOWN_HOLD、当日評価最小標本はUNREGISTERED_HOLD。G8資格0/分母null・promotion falseを維持。
全国件数artifact14342497406は2905bytes、ZIP SHA256を再取得照合した。owner keyはActions内だけで使用。

**完了M2の最終controlもAES一致:** owner44075021607/86b029aeは実10巡・24暗号原本を認証。
当該worker GET304、累積13807、当日基点13017、巡回累積730、prepared/source_waitはnull、stop=DAY_HANDOFF。
11〜24の明示no-opを実巡へ足さない。ALL_MODEL2〜10は原本なし/null/HOLDを維持し、
producerのcontexts0/generated0ログをAESゼロ件証拠へ変換しない。追加P1新規9行/再利用baseline5を区別し、旧未表示36行の修復とはしない。

**真正callbackは未観測:** 15:53:06 UTCまで、daily/matrixとも完了後workflow_runのREST記録0。
producer名/path/production branch/イベントとdefault main上のactive receiver/filterは一致し、原因は未確定。
今回の44115395767はpush監査で、完了callback成功とは数えない。現時刻を使う純粋gateは時間外HOLDで、実callbackではない。
既存05:30 JST scheduleを保持し、直接source再起動・clock/counter変更は行わない。

**新しい診断付き実Mac:** 既存workflow416758725をmain69で1回実行し、44115451343/job134152150622がfailure。
安全な診断はlatest_p1_private_transport/select_native_history・390px・native_option/HTTP400。
1440px側は通過した。公開f603/同一合成fixtureでも、390pxの選択欄が画面外でhit不可となる前提不備を再現。
実private側のdisabled/選択状態は未観測で、準備処理の修正と実Mac再検証はまだ未完了。候補UIのnative成功とは扱わない。
公開f60308ef/本番weightsは保持。

**実raw source-captureの保存来歴（RESULT取得経路）:** 正規jobログの11報告、全manifest/hash/commit祖先関係を再照合。
84→171組のraw/metadataは累積で、全旧組のhash/sizeを保持。最終cipher10,199,985bytes/SHA256は
正規Git Commit→Tree→Blobで再取得一致。元archive clock15:12:49.431006 UTCは再保存時も維持した。
この監査は鍵なしcipher照合で、ローカルMAC/AES/公式本文parse・RESULT journal結合は未実施。
B17欠落/P1 racelist・beforeinfo原文欠落は残る。folder240件超で停止する現行制限も判明し、
1bundleの安全上限を保った複数bundle保存を検討中。取得総数制限の解消やraw公式資格成功とはまだ扱わない。
[実AES・最終control・pair件数・限界](evidence/boat-completed-m2-current-pairs-aes-20261117.json)。

4競技の全日/全モデル/T15〜10、物理iPhone/全8参考画面、校正した6艇継続/強さ接続、前向き精度改善は未達。
元work/他作業/KEIRIN default-OFFを保全し、未push b7380fe6/daae4c10はUNRESTORED。新PR/モデル系統/課金/投票0。
以下は過去時点の記録として保持する。

## 2026-11-17 15:28 UTC: 実Safari失敗を保全し診断を改善、当日比較pairの独立監査へ（GOAL未達）

実main10a83499cdf3c200b15684f53044eebc1c320183/source f55351dce855177a51330f72c37d6238ba2c9e3e。
PR58は最終2309298fの24 checks後に通常mergeし、reviewed treeと一致。main push44105507295のHTTP確認はsuccess。
続く実Mac run44105597091/job134116978337は、候補UI撮影の前にSAFARI_WEBDRIVER_FAILEDでfailure。
element_click/HTTP400まで確認できたが、従来のreportは呼出し元を失い標準error種別も不足していた。
artifactは0で、候補UIの実Safari受入成功とは扱わない。以前の44068042347の実private AES成功も保全する。

**既存PR57の診断変更:** 固定の段階・操作・実幅・クリック経路・hit-test真偽とallowlist内の呼出し元を残す。
失敗応答から許された標準errorだけを抽出し、本文・DOM・selector・値・URL・私有予想は出力しない。
成功parser、native操作、retry回数、session削除・driver終了条件は保持。作者72件・独立72件、153 parser比較・
10操作trace・9 loopback拒否probeが合格。結合treeの72件も合格。実クリック失敗の原因修正完了とはしない。

**当日比較pair:** M2 owner44075021607/86b029aeは15:14:53 UTCにsuccessで終了し、正規認証で完全jobログを取得できた。
producerの保存確認は第1巡の14 model-cell組、元予想14/学習版14、独立レースは1。14レースや精度改善とは数えない。
後続9巡のgenerate報告はcontexts0/generated0である。24実巡や全日coverageとは認定しない。
既存の独立AES監査にtraining原本・pair初回保存版・RESULT journal revisionの件数確認を追加する。
関連138件・独立100件と5追加probeが合格。真正Actionsでのpair読戻しはまだ未実行。
原公式資料/公式締切はUNKNOWN_HOLD、当日評価用の最小標本はUNREGISTERED_HOLDで、資格0/分母null・切替不可を維持する。
producerの申告を独立AES照合済みと混同しない。pair照合失敗でも既存core原本証拠を保持し、件数をnull/HOLDとして報告する。

PR57の旧head cca045bbc5db45cc1f799e6ce89fb0ddabdc44c9とmetadataを保全し、旧Blob実装treeは適用していない。
同HEADの必須CI、通常main merge、当日pairの実AES監査、改善した診断付き実Mac確認へ進む。
稼働終了後の公開control/真正callbackは別に確認する。sourceを直接再起動せず、時計やcounterを変更しない。
[実失敗・producer件数・検証範囲](evidence/boat-native-click-current-pairs-20261117.json)。

全4競技の全日/全適用モデル/T15〜10、物理iPhone/8参考画面、校正した6艇継続/強さ接続、前向き精度改善は未達。
未push b7380fe6/daae4c10はUNRESTORED。元work/KEIRIN default-OFF/公開f60308ef/本番weights/投票禁止を保持する。
新PR/新job/権限/input/runner/cron/課金設定は追加しない。以下は過去時点の記録として保持する。

## 2026-11-17 14:16 UTC: 修正原本の実鍵検証成功、二重起動HOLDを確認（GOAL未達）

実main43704b2fbe5cf4e1d471737c6f47e639a611a12f/source f55351dce855177a51330f72c37d6238ba2c9e3e。
既存PR59は最終f1457e89の27 checks後に通常mergeし、実treeとreviewed treeが完全一致。
正しい既存prefix/markerから実gate44100425945/job134098647385が動き、HOLD_ACTIVE_OWNER_WORKFLOW・dispatch false・公式GET0。
M2 owner44075021607は86b固定のまま継続し、追加workerを開始していない。次の版の実速度は未確認。

**期限切れ原本の実AES成功:** 正式監査44100426069/job134098651254がsuccess。
13559236491は元run42334526055/source8cfのZIP7,399,390bytesとmetadata740bytesのSHAが一致し、
16記録/88 native入力片を当時の保持時刻で認証・再演算できた。元clock/bytes/原本は変更0。
新model入力/現時点の入力許可/receipt/dispatchは作らず、owner keyはActions内だけで使った。
初回44093714741のfailure/HOLDと誤期待名900001の原因を保全し、正しい900003への1literal修正が実証された。
証拠artifact14335961767は1,120bytes、M2証拠14336036608は1,874bytes。両ZIPのサイズ/SHAを再取得照合した。

**M2は部分証明のまま:** 同runで完了1〜7巡、P0/P1/RESULT/ALL_MODEL計17暗号原本を認証。
追加モデルP1新規9行の保存AES view一致9/欠落0を維持。baseline再利用5行を新規へ足さず、旧36行の修復証明にしない。
ALL_MODEL2〜7欠落は生成数null/HOLD、公式B未認証・締切資格0/null、全日/最新live counter/精度改善は未合格。
[実gate・実AES・件数/hash・範囲の証拠](evidence/boat-actual-profile-gate-archive-aes-20261117.json)。

**UI候補の実Safari準備:** 既存DraftPR62の598候補を公開配信せず、同じ既存Mac jobの合成撮影へ接続する3file変更をレビュー。
64件＋独立64件、11拒否probe、実candidateの28 Chromium viewport/pageを確認。現在のf603実private/AES/P1を先に維持し、
session削除応答/driver終了・資格情報除去・新origin/session確認後に候補を撮影する。既存PR58で最終CIへ進める。
main pushはHTTPのみ。merge後、既存workflow416758725/ref main/browser=native-safariで実Macを1回確認する。
候補の実Safari/物理iPhone/全8参考/本人login/V5継続/実dataはまだ未確認。新job/runner/権限/input/cron/課金は追加しない。

4競技の全日/全適用モデル/T15〜10、校正した6艇継続/強さ接続、未来の精度改善は未達。
未push2commitはUNRESTORED、元work/KEIRIN default-OFF/公開f60308ef/本番weights/投票禁止を保持する。
以下は過去時点の記録として保持する。

## 2026-11-17 継続: 保存名の実照合失敗を1項目修正、次source f553へ正規引継ぎを準備

実main0d8126ed/source f55351dce855177a51330f72c37d6238ba2c9e3e。source既存PR63は最終acf84c7b/5 checks後に通常merge、tree完全一致。
registry再構築を検証1呼出し内で共有する変更で、model/weights/全検査は保持。local AES fixtureのPDCA30.4→15.2秒だが、
稼働中M2は86b029aeの固定checkoutで継続しており、本番速度・T15〜10改善は未実証。

**実原本監査44093714741は失敗を保存:** job134075234376のM2 phaseは1〜5巡を認証し、計13暗号原本、
追加モデルP1新規9行の保存AES view一致9/欠落0を再確認。ALL_MODEL2〜5は欠落・生成件数null、公式B未認証・資格0/nullでHOLD。
その後の期限切れ13559236491照合がARCHIVED_NATIVE_ORIGINAL_METADATA_REJECTEDとなり、job全体はfailure。
3証拠ZIPを再取得し、サイズ/SHAと2つの同一M2 documentを検証。原本復元成功や全件完了とは扱わない。

**実原因:** 正しい公式source-packetの保存名900003を、P0専用900001と取り違えていた。
実行当時8cfのscript blob4f906153…を正規GitHub readで取得し、17,260bytes/Git SHAとSHA256を検証。
ROUND900003とupload/readback名の流れを確認した。真正AES合成fixtureでも同じ拒否をRED再現し、
期待名1literalだけを修正。ZIP/metadata/cipher/entry/source/clock/hash/type/pinの全guardは維持する。
作者113件・独立13件と因果再現がsuccess。修正後の真正Actions実鍵結果はまだ未確認。

**既存PR59の最終候補:** 実source f553をfuture dispatch/controlへ結合し、M2をexact原本originとして保全。
現在のM2監査target44075021607/86、EFF既定/過去P0/Safari読取を保持。M2/EFF/新sourceの真正callbackと、
新source完了時も同じ厳密なpartial原本監査を接続する。稼働中owner・source不一致・旧checkout/proof・最終controlなしはHOLD。
既存markerへ追記し、正しいboat-owner-release: single-real-session-20261111 prefixで同じgateへ渡す。
combined d47de020は123 matrix/archive・92 gate、独立122/84/18 profile暗号拒否/2実M2-origin fixture/13 archiveがsuccess。
GitHub最終HEAD CI・通常main merge・実gate/修正済み原本AESは次工程で、前HEADの合格を流用しない。
[実失敗・件数・source/修正SHA・未達](evidence/boat-profile-release-and-archive-fix-20261117.json)。

**UIは配信せず保全:** 既存DraftPR62に598c80c8を保存。mainの不完全な5file移植は採用せず、既存86b UI runtime上で
44 browser checkpoints/3 unit testsを再確認。全8参考はpartial、実native Safari/物理iPhone/本人login/実dataは未合格。
公開assetsはf60308efのまま。次は同じ既存Mac jobで、秘密を除いた別sessionによる候補UIの合成検証を準備する。

4競技の全日/全適用モデル/T15〜10、6艇継続/実距離時刻校正/強さ接続、前向き精度改善は未達。
元work b420631 clean、未push b7380fe6/daae4c10 UNRESTORED、KEIRIN default-OFF/1レースの別作業を保全。
新PR/新job/権限追加/課金設定/本番weights/投票/無断のUI配信変更0。以下は過去時点の記録として保持する。

## 2026-11-17 12:58 UTC: 実M2の9原本AES・追加モデルP1の9行表示一致、全件はHOLD

実main88c3fc5e06e8ce9438391c02bbaec09d2a00f052。既存PR65は最終6b2accce/27 checks完了後に通常mergeし、tree完全一致。
真正pushの既存監査44087732511/job134054474873がsuccess。公式GET/予想生成/原本改変0の別runnerで、
M2 owner44075021607/source86b029aeの完了巡1〜3を12:56:23 UTCで固定して照合した。
P0原本1・P1/RESULT各3・ALL_MODEL0/1の計9暗号原本を認証。ALL_MODELの2 ZIPはGitHub SHA/AES/既存モデル再演算が一致し、
追加モデルP1新規9行は保存AES viewの9行すべてと一致、見つからない行0。再利用native baseline5行を新規件数へ足さない。
これは旧eff snapshotの未表示36行の修復証明ではない。

**HOLD継続:** 第2・3巡のALL_MODEL原本は一覧にないため生成件数null・原因未確認で残す。当日公式B保存資料も未認証で、
公式締切適格0・分母null。監査job successを全モデル/全日/T15〜10合格と混同しない。
第1巡25分19秒、第2巡20分39秒、第3巡21分が実success。第4巡中で、実処理時間の内訳は完全jobログ待ち。
13:27 UTCの再取得では第4巡も21分27秒でsuccess、第5巡中。独立AES/表示照合は上の固定1〜3巡だけで、後の巡へ加算しない。
確認済み2証拠ZIP（14330127306/14329728104）のサイズ/SHAを再取得照合し、同一の件数documentであることを確認した。
[実M2の原本・表示・欠落・scope証拠](evidence/boat-m2-independent-aes-snapshot-20261117.json)。

最優先の旧43829249080も同じ別runnerで再AES認証し、公開counter一致・worker GET0/累積12770/巡回累積695を保全。
この過去checkpoint単体は新P1証明や後続dispatch許可ではない。新M2の9行実証は上の別証拠で示す。
[旧P0失敗checkpoint再認証](evidence/boat-failed-p0-reauthed-20261117.json)。

**次の修正候補:** registry再構築を検証1呼出し内で再利用する469e06cdを独立レビューし、既存PR63で通常CIへ進めた。
実AES合成fixtureのPDCA30.4→15.2秒、全検査回数・予想/判定一致。現行86b workerは差替えず、本番遅延解消とは認定しない。
期限切れ原本13559236491の保存暗号file7,400,747bytes/SHA一致は確認。Actions実鍵の原本再認証は未実行で、
元のmetadata/保存時刻を保持する件数/hash専用helperを準備中。古いinputを現在の生成許可へ変換しない。
helperのmain接続63f9d01cは112件・独立112件・8workflow block・6失敗/privacy検査を通過。排他作成/fsync/close済みの
自分の件数JSONだけをuploadし、既存file/symlink/書込失敗時はuploadしない。既存PR60の最終CI/真正実鍵検証は未実行。

実Mac Safari/WebCrypto・28合成画面は以前の実runで合格。local UIは改善継続だが全8参考一致/実機iPhoneは未合格。
local UI a4a200f5で金額10000000の末尾切れをRED→修正し、320/390/1440/1920pxと近隣PC幅を独立再確認。
最初の個別結果/配分行をスマホnav上へ収め、HOLD/unknown金額/原本/手入力・削除/購入拒否を保持。36合成PNGのhash/実寸を照合。
8参考は全てpartial、参考07の8tab対現行5tab、閉じたselectのellipsis、配分summaryのscroll等を未達として残す。
mainにはweb runtime一式がなく、3assetsだけの移植はself-containedではないことも確認。実UI source86b上のreview candidateへ分離し、
不足moduleをmainへ暗黙に追加しない。公開assetはf60308efのまま。[local画面の値・限界](evidence/boat-local-reference-layout-pass2-20261117.json)。
全4競技の全日/全適用モデル/T15〜10、6艇継続・実距離時刻校正・強さ接続、未来の精度改善は未達。
原本・元work b420631 clean・KEIRIN default-OFF/1レースを保全。未push b7380fe6/daae4c10はUNRESTORED。
新PR/本番weights/公開assets/追加課金設定/投票の変更0。以下は過去時点の記録として保持する。

## 2026-11-17 12:29 UTC: 正規M2引継ぎで2実巡成功、締切遅延は未解消（GOAL未達）

実main fd92b531b82f1365ce99e6917cc4812f8ce1ac42、source86b029ae5bddd5d4956497d8b32b2c92b8eec521。
既存PR171は通常merge・reviewed tree一致。正しい既存release prefixとmarker変更で真正gate44074681478が実行され、
job134009539055はsuccess。旧原本のAES/counter復旧後にREADY_VERIFIED_RECOVERED_OWNER_CONTINUATIONを確認し、
既存worker44075021607を11:33:04 UTCに一writerで開始した。gate自身の公式GET0/新規予想0を、当日全体の0と混同しない。

新workerは第1巡11:39:28→12:04:47（25分19秒）、第2巡12:04:47→12:25:26（20分39秒）がsuccess。
P1/RESULTの実GitHub暗号artifactを各2巡分確認し、第3巡が稼働中。ALL_MODELは0/1のarchiveを確認。
第2巡のALL_MODEL archiveは一覧にない。producerは当該生成/保存にcontinue-on-errorを持つため、欠落だけで
予想対象0や正常な処理なしと認定しない。全通常P1/RESULTを照合し、全モデル原本の欠落巡をUNKNOWN/HOLDで残す修正e3890bf9が完成。
eff/実86bの両依存packageで各100件、独立100件＋追加3検査success。実Bがあっても欠落巡の適格件数0と明示blockerを維持し、
callerのprefix短縮/偽除外/bool-int置換を拒否する。全通常原本・存在する全モデル原本の誤鍵/欠落/改ざん/expiryは引き続きfatal。
metadataだけで新規予想件数・表示一致・締切適格を認定しない。実M2の別runner AES/原本/既存モデル再演算監査を準備し、
公式B欠落時は資格0/null・full_day=falseを維持する。25分超の実遅延から、バッチ化だけでT15〜10達成とはしない。
稼働jobの完全ログは正規認証でもまだ404であり、実時間の内訳は未確認。ローカルで再現した重複検証を別に測定中。

**CIの実失敗を修正:** run44072746303のmirror205件中1件は、valid metadata_sha256内の偶然の4001を
個人名と誤検出した。完全reportを調べ、その文字列の出現は当該digestだけと確認。同じHEADのfailed-job-only再試行は成功したが、
初回失敗を消さない。元immutable d5ede5fbを保存し、runtime無変更・test2ファイルだけの01ed8abeへ固定する候補を検証。
既知field/path/typeの完全40/64hexのみを除外し、raw名・未知field・nested文字列・誤digestは拒否。親212件と独立adversarial検査success。
実GitHub run44085027353/job134045097361でも新revisionの212件＋32件がsuccess。同HEAD全27 checksが完了した。
この後の欠落監査修正e3890bf9を含む最終HEADは別途CI/保護mergeを経て実M2原本を読み取り、前HEADの合格を流用しない。
元PR65のtitle/body/headを私有localに保存し、旧head989ffff1を祖先に保持したままmainへretarget・review可能にした。
旧controller/Cloudflareの実装treeは適用していない。新しい欠落監査の独立レビューと同HEAD CI前にmergeしない。
実prospective artifact14328665148は6,381bytes/SHAを取得照合。対象は11月7日の旧凍結planでHOLD・改善証明falseであり、
11月17日の新しい前向き精度改善の証拠には数えない。

[真正gate・実ラウンド時間・artifact metadata・CI履歴](evidence/boat-m2-genuine-handoff-runtime-20261117.json)。
物理iPhone、8参考画面の最終一致、全4競技の全日供給、映像校正/6艇継続、前向き精度改善は未完了。
元work b420631 clean、未push2commitはUNRESTORED、KEIRIN default-OFF/1レースgateを保全。
公開asset f60308ef/本番weights/新PR/追加課金設定/投票の変更0。以下は過去時点の記録として保持する。

## 2026-11-17 継続: 実Safari内AES/28合成画面が成功、結果理由履歴の修正をsourceへ統合

実main519705524de274a6c73124746970615086ca237a、実source86b029ae5bddd5d4956497d8b32b2c92b8eec521。
sourceの既存PR201はexact d79a9a2c/CI44070104091 successと最終独立レビュー後に通常merge、tree完全一致。
同一source/time/status/dataのreason-only原本は両方を保存し、後続結果syncでも履歴を維持する。
着順/払戻/source/status/時刻/未知fieldの違い、偽履歴、未知の新reasonは拒否し、全拒否理由がHOLDに寄与する。
作者182Python/14Node、親153Python/14Node/15workflow、独立83Python+26追加検査success。
バッチ化で変わった独立reader契約へのfixture未対応もRED→6件GREENで修正し、本番readbackは緩めていない。
実viewの36行差分の修復とM2の新予想は、次の正規workerで再確認する。

**実Mac成功:** run44068042347/job133986892349、code51970552、Safari26.6/macOSでcompleted/success。
保存私有view generation412/results102/native P1 groups9で実1440/390px、元Top8比較4、詳細2、結果/予算2を確認。
別の元暗号seedをWebCrypto復号して同一原本比較2、鍵なし/誤鍵/別view/改ざんの4拒否を確認。
viewer鍵は私有fragmentのみ、request/storageには含めず、owner keyはbrowserへ渡さない。公式GET/許可外部通信/実data screenshot exportは0。
本人account loginとcurrent V5 live continuationはfalse。前のsession開始失敗は原因未特定で、起動設定は同じまま今回成功した。
資格情報を除いた別sessionでsynthetic7画面×320/390/1440/1920px、実innerWidth一致の28PNGを撮影・検証。
artifact14322350355/8,911,079bytes/SHA256を再取得照合した。[実Mac AES証拠](evidence/boat-native-safari-browser-aes-20261117.json)。

**ローカル画面改善:** commit5992f110でhome/list/detailの主要内容を先にし、全control/状態表示を保持。
320/390×844で最初の詳細ticket下端736/696pxは固定nav上端773pxより上。28合成画像と8参考画像を比較し、独立レビューもsuccess。
公開配信f60308efには反映していない。[ローカル画面の比較値と未達](evidence/boat-local-reference-layout-20261117.json)。
完全な8画面一致、長文/全データの密度、本人login、物理iPhoneは未合格。

**正規引継ぎの最終確認待ち:** 旧44019591352は実13巡で自然終了。公開controlは13/GET485/lifetime13503/daybase13017/WORKER_HANDOFF。
14〜24は処理なしで、24実巡とはしない。38原本のAES証拠はsnapshot1〜12だけで、公式締切資格0/nullと36未表示を保持する。
PR163のpin更新だけでは既存push filter/専用prefixを満たさず、次workerはまだ起動していない。
既存PR171で必須marker追記と正しいboat-owner-release prefixを揃え、実M2のみを既存gateへ渡す候補を検証中。
最終controlの真正AES/counter/single-ownerが通った場合だけ既存source workflowを許可する。直接/盲目的な再起動やcounter resetはしない。

4競技の日次全件/全適用モデル/T15〜10、6艇継続/実距離時刻校正/強さ接続、元モデル対学習版の前向き改善は未達。
241映像frameでの既定/opt-in packet byte一致は診断の非干渉証拠であり、識別精度向上の証拠ではない。
本番weights/新系統/新PR/追加課金設定/投票/無断の公開asset変更0。元work b420631 clean、未push2件UNRESTOREDを保全。
以下は過去時点の記録として保持する。

## 2026-11-17 10:39 UTC: 13実巡で自然引継ぎ、38原本の独立AES証明と表示差分を確認（GOAL未達）

実main b0a61b8b28bb98c1ad63babc7f8594cbd693d808、実production f43bde4c89cdc27728a112ad2a4b55769c7d3ec9。
既存PR107は5 checks完了後に通常mergeし、reviewed300efc02のtreeと完全一致。保存バッチ/疎なGit転送、動画3〜6艇coordinator、
旧eff原本read-only互換を含む。本番model/weights/系統/公開assetsは変更していない。次workerの速度と締切達成はまだ未確認。

**旧worker自然終了:** owner44019591352（eff296f）は10:28:18 UTCにsuccess。実P1/RESULT各13archive、ALL_MODEL0〜13を確認。
14〜24のstepは0〜1秒の処理なし終了であり、24実巡完走とはしない。公開final controlはcompleted13、requests485、
lifetime13503、day base13017、stop=WORKER_HANDOFF。最終controlのAES一致と次worker許可は真正gateで再確認する。
[物理引継ぎ証拠](evidence/boat-owner-physical-handoff-20261117.json)。既存PR163で次の正規dispatchを実f43へ固定する候補を確認中。
旧effの実完了/原本は保持し、旧checkout/旧proofを現在の起動権限にしない。実snapshot/Safariのread-only pinはeffを維持する。

**独立AESが実success:** 既存run44063726374/job133971901973、main b0a61b8bで38暗号原本を別runner復号。
固定snapshotは巡回1〜12（10:19:34 UTC取得）、ALL_MODEL13 ZIPのSHA/AES/既存モデル再演算を照合。
P1新規原本252行、保存view一致216/見つからない36（巡回10〜12）。基準P1再利用140行は新規件数に足さない。
公式B当日保存indexなしのため公式締切資格0・分母null、全日/最新稼働counter/後続許可false。
実artifact14319890592の2038bytesとSHA256も再取得照合済み。[実AES集計](evidence/boat-active-owner-aes-snapshot-20261117.json)。
これは暗号原本一致の部分証明であり、全日/全14モデルの締切適格・画面全件反映の合格ではない。

**表示差分の実原因:** 完了した実jobログはENCRYPTED_VIEW_REJECTEDを記録。直近は同一source bytes/同一data/同一finishで
reasonだけが異なるSAVED_MODEL_VIEW_CONFLICTING_RESULT_OBSERVATION。両方の原本/拒否理由を保持する追加的union修正をローカルで検証中。
着順/払戻/source/status/未知fieldの相違や誤鍵は引き続き拒否し、表示側から結果を捏造しない。まだ実view修復済みとはしない。

**Macは引き続きHOLD:** run44063729583/job133972032065は40テスト成功後、Safari新sessionの境界でSAFARI_WEBDRIVER_FAILED。
app/暗号seedの開始前であり、原因は未特定。秘密を含まないoperation/HTTP status/W3C enumのみの診断を追加する候補を検証中。
Safari browser AES、synthetic28画像、本人login/実機iPhone/8画面の最終受入は未合格。旧実操作successとは分離する。
UIの参照画像に基づく余白/順序の改善は別のローカルpreviewで検証し、無断の公開はしない。

4競技の全日供給、締切T15〜10の実充足、6艇継続/校正/強さ接続、元モデル対学習版の未来改善は引き続き未達。
未push2commitはUNRESTORED、元work b420631 cleanと並行KEIRINの変更を保全。新PR/追加課金/投票/本番weights切替0。
以下は過去時点の記録として保存する。

## 2026-11-17 10:15 UTC 継続: 12巡success、原本監査とMacの実失敗を修正中（GOAL未達）

確認済みmain2408a833920b539e7f29fb9fde02ca290e4f5df0（既存PR192/160を通常merge、各reviewed tree一致）。
同時進行KEIRIN PR308のdefault-OFF/1レースgateとPR291は保全。production eff296fと単一owner44019591352は継続中。
GitHub実job133825616165で01〜12巡success、13巡中（09:49:21 UTC開始）。24巡、全日、全締切T15〜10、
全4競技×適用可能全モデルの達成とはしない。後半は1巡30分超であり、遅延は未解消。

**実監査の失敗と修正:** 既存run44060568619/job133961084410は旧43829249080のcheckpointを別runnerで再AES認証したが、
現ownerの全モデル照合はHOLD。固定vault115c6aa3f0e07c0de3f668ffa4e75b68c01edf88の当日11/17公式B indexは404、
親directoryは200（08/13/14/15/16のみ）。同条件の暗号fixtureで拒否を再現した。
修正候補は固定したactive snapshot限定で原本ZIP/AES・元モデル再演算・保存view一致を調べ、公式締切資格と分離する。
公式資格件数0、分母null、full_day=false、後続許可false。既定の完了run検証は引き続き拒否し、誤鍵/改ざん/別原本/一般例外はfatal。
98作者テスト、独立78件+追加2拒否検査、統合118件がsuccess。修正版の実AES結果はまだ未確認。
[当日資料欠落の実証](evidence/boat-active-cutoff-prerequisite-20261117.json)。

**実Macの失敗と修正:** 既存run44061190244/job133963304442はbrowser開始前、39件中1つのsynthetic artifact fixtureでHOLD。
macOSの/var→/private/var symlinkを再現し、信頼済み一時fixtureだけcanonical pathに修正した。
productionのsymlink拒否は維持し、その拒否回帰を追加。40 focused/91関連テストsuccess。
ブラウザWebCryptoによる同一seed復号、誤鍵/鍵なし/別view/改ざん拒否、資格情報を除いたsynthetic7画面×4幅撮影は実Mac再試験待ち。
旧44028066179の1440/390操作成功とは区別し、本人login、物理iPhone、8参考画面の最終受入は未合格。
公開配信f60308efのassetsは変更していない。

**保存遅延と動画coordinator:** 不変研究ファイルをサイズ制限付きでまとめて追記し、別Git DBで全選択byteを再照合する候補を既存PR107でCI中。
全件を処理し、総レース/GETの上限追加、原本削除、CAS緩和なし。実Git sparse取得で無関係な古いblobを取得しないことを確認。
動画matched coordinatorの六艇固定を既存3〜6艇validatorへ接続し、欠場艇を買い目へ含めない。モデル/重み/系統は変更しない。
統合199件、独立の実workflow recovery662件等success。将来releaseでのexact eff checkpoint読戻しも追加し、旧checkout/旧proofの起動権限は拒否する。
稼働中workerは差替えず、実運転の速度改善と次workerは未確認。

**実映像と残る外部証拠:** 許諾済みCommons映像を復元し、775frames/25.859秒・SHA256
1ac1f0c27f58d8d64ebb1cfc13c2c4e9133cf7bbcce04052f23c28bf2e37f194を確認。事前固定した4区間241framesでsix-unique仮説frameは0。
これは独立正解ラベル付き精度率ではない。後からの目視では、空水面、2〜3艇、遮蔽/画面外を含み、全241枚を六艇観測機会の分母にしない。
歴史的な権利未確認61frame派生物とは別source。正しい6艇継続識別、距離/時刻校正、強さの予想接続、未来精度改善は未証明。
AUTOの元parserは試走の総数のみで、各車の数値・source時刻・同race/rosterの結合が不足しB_POST_TRIALを維持。
非BOATの日次全レース供給、既存モデル全適用、前向き比較の不足をsynthetic試験で埋めない。

新PR、新モデル系統、追加課金、公開配信変更、投票、本番weights切替は0。元checkout b420631/workはcleanを維持。
未push b7380fe6a377e6ccf2b96331f2126c52549bbe17 / daae4c10167224b7730006d8ada5ade398aaa64bはUNRESTOREDのまま。
以下は各時点の履歴として保全し、この追記をGOAL完成報告とは扱わない。

## 2026-11-17 最終継続記録: P0復旧後4巡成功、Mac Safari1440/390pxの私有表示操作が成功

**確認対象code**: main36088f5d0d2513f88c3a71ae0a1f3e1d1d5a9649、production eff296f6d54ad4be297d93e32f1ee0d4592ad9e3。
元checkout b420631/branch workはcleanのまま保全。公開GitHub readとhaji84の正規認証を別に確認し、
既存branch実push/通常PR mergeも成功。旧protection API403とは別にactive rules API200でPR+unit必須を確認。
保護設定変更・force/--admin・新PR・追加課金・投票・本番weights切替・公開配信asset変更は0。
未push b7380fe6a377e6ccf2b96331f2126c52549bbe17 / daae4c10167224b7730006d8ada5ade398aaa64b は
GitHub/ローカルobjectから取得できずUNRESTORED。元環境のローカル変更を移転/復元済みとはしない。

**P0最優先**: 旧43829249080はP0保管failure/24巡skipの履歴を保持し、別runnerで原本AES/公開counter一致を認証済み。
Gitの全履歴fetch・promised blob tree作成を修正し、保存済みbootstrapの同一原本sidecar照合も修正した。
真正gate44019424267がGET0/新予想0で3原本を復旧し、後継44019591352を起動。
後継の旧停止箇所step33と巡回01〜04がsuccess（04終了05:59:18 UTC）。巡回05実行中。
新P0/P1/RESULTの暗号ZIPを取得しrun/head/サイズ/SHA照合。新原本の別runner全本文AES/全モデル分母監査は未確認。
24巡完走、全レース締切15〜10分前充足、全4競技×適用可能全モデルの全日自動生成/結果照合は未合格。
BOAT論理巡回・総GETの固定上限Noneは保持し、403/429や未検証sourceの拒否を緩めていない。

**実Mac Safari**: run44028066179/job133853102653、Safari26.6/macOSで06:03:13 UTCにsuccess。
実innerWidth1440/390の両方、保存Top8比較4回、P1詳細2画面、結果/予算2画面を通過。
認証view generation409、当日結果49、native P1 groups9を使用。これらの数を全14モデル/全日達成の分母にはしない。
鍵のURL/リクエスト/storage露出false、外部通信許可0、公式GET0、予想/結果変更false。
公開f60308efの同一配信資産とPythonで認証済み原本を、私有loopback経路で確認した。
ブラウザ内AES/本人ログイン・物理iPhone・8参考画面の全視覚受入はfalse/未確認。
失敗したMac試験/候補機構も履歴に保全。26ローカル境界試験/独立26件と実Mac成功を区別する。
[実Mac count証拠](evidence/boat-native-safari-20261117.json)。

**残るgate**: 過去の固定native13559236491はAPI404で未復元、旧長期RESULT保管/前向きplanはHOLD。
新巡回の必須P1/RESULT Vault経路の成功とは区別する。服色/追跡/校正/接続/学習の既存120件はsuccessだが、
実映像で6艇を継続識別し、校正した強さを締切前予想へ接続した証拠、元モデルに対する未来改善は未実証。
次は進行中ownerの自然終了と既存workflow_runの別runner原本/全モデル監査、実機iPhone/ブラウザAES/8画面、
実映像校正/予想接続、前向き比較を実データで検証する。未確認を合格扱いしない。
[保管・復旧・未達の統合証拠](evidence/boat-p0-storage-recovery-20261117.json)。以下は各時点の履歴として保全。

## 2026-11-17: Safari実390pxの一覧残留を確認、クリック対象の保護を追加

実main 1242ccc97a483d50a3f77cbe9d655952f4ed773d（既存PR182、23 checks完了・tree一致）。
実Mac44026515882/job133848050105は実innerWidth390、page-racesのまま、JS error0でHOLD。
停止はapp_checks:598の展望tab取得。直前のレース詳細clickが画面遷移として成立していない。
requested幅/ループindexは旧ログに無いため、desktop予算を含めた通過範囲は断定しない。
既存PR64を履歴保全して再利用し、可視対象を中央へスクロールし、実際のhit-testが対象/子要素であるまで待ってから
ネイティブWebDriver clickする。固定ナビとの重なりは候補機構であり、実原因の唯一断定や合格認定にはしない。
選択肢optionの既存native protocolは維持。JS click/state代入は使わず、予算/ページ送りも同じ可視クリックを使う。
重なった対象へclickしない回帰を含む26件と独立26件success。実Macは統合後の次試験で確認する。
固定parser761247bの原本/全既存履歴は保持し、main/sourceの実行コードにmutable PR64 branch参照が無いことも確認した。

production source eff296f6d54ad4be297d93e32f1ee0d4592ad9e3の単一owner44019591352は巡回01/02/03 success、04中。
旧P0保管失敗から新予想/保存の実進行を確認したが、24巡・全日全件・別runner新原本AES・4競技全モデルの正式充足は未確認。
公開配信asset・予想原本・本番weightsは変更しない。未push2件UNRESTORED、iPhone/8画面/実映像/校正/未来改善も未完成。

## 2026-11-17: 実ownerは3巡success、Safariの詳細タブ停止を継続診断

実main fb938e5b8690b8d525056e875d1178e94e988c02（既存PR194、23 checks完了・tree一致）、
source eff296f6d54ad4be297d93e32f1ee0d4592ad9e3。
単一owner44019591352はP0保管step33と巡回01/02/03がsuccess。巡回03終了05:40:01 UTC、巡回04中。
24巡完走・全4競技全レース/全モデル・全締切T15〜10充足・別runnerの新原本AESはまだ未確認。

実Mac44024956057/job133842950712はapp_checks:559の詳細タブclickでHOLD。
どちらのviewportかは旧ログに無いため、予算変更をどこまで通過したかも未確定。W3C入力修正の実証にはしない。
既存PR182で、要素の1回照会を同じ可視条件の45秒待機へ変更する。失敗時は画面ID/幅、公開JSのmodule/行、
エラー件数のみを許可リストと整数上限で出す。任意DOM文字列、URL、例外本文、鍵、予想は出さない。
遅延要素の回帰RED→Safari23件success、独立23件success。実Macでの原因/解消はまだ未証明。
予想worker・公開配信asset・model/weights・原本はこの診断変更で動かさない。

旧指定未push2コミットはUNRESTORED。元checkout b420631のclean状態、公開read/認証writeの区別を保全。
Mac Safari全判定・物理iPhone・ブラウザ内AES/本人認証・8参考画面の視覚受入、実映像6艇/校正/予想接続、
元モデル/学習版の未来改善は未合格。過去原本の固定pin404と旧前向きplan HOLDも保全している。

## 2026-11-17: Mac再試験も日予算でHOLD、ネイティブkey eventsを検証

実Mac run44023534099/job133838349546（main acd7c76）はapp_checks:564のbudgetで再びHOLD。
CMD+AをElement Send Keysのtextへ埋める修正は実Safari合格ではなかった。失敗を保全し、
既存PR194でW3C /actionsのkeyDown/keyUpへ変更する。Commandを離してから数字とTabを送る。
アプリの値/stateをJavaScriptで書き換えず、最終値・元買い目・結果・横幅・秘密境界の条件は維持する。
さらに失敗時だけ、要求予算5000/10000・実欄の0〜10,000,000整数またはnull・focus/validの真偽を診断する。
任意のDOM文字列、出典、URL、owner key、driver例外本文は報告しない。21件と独立21件success。
このローカル成功を実Safari合格に置き換えない。main統合後に同じ既存Mac jobで再検証する。

source eff296fのowner44019591352は巡回01/02 success、巡回03中。
各巡回には新P1/RESULTの必須Vault保管と次巡許可前の原本確認を含むが、別runnerの全本文AES/全モデル監査とは区別する。
公開配信asset・予想原本・model/weights・source pinは今回のSafari修正で変更していない。
物理iPhoneの接続toolはこの環境では未検出。4競技全件・実機iPhone・実映像/校正/予想接続・未来改善は未完成。

## 2026-11-17: 2巡目も実成功、Safari予算入力修正を通常統合

実main acd7c767a454a78dd19499344935ccffd567e67d。既存PR203の23 checksが完了し、
10 success/13 skipped、独立Safari20件success後の通常mergeでreviewed treeとの完全一致を確認。
実Mac再試験44023534099を同HEADで開始した。まだ合格扱いにはしない。
source eff296fは変更せず、単一owner44019591352は巡回02も05:21:47 UTCにsuccess、巡回03へ進んだ。
原本からの実P0保管復旧と2巡連続の生成・保存進行を確認。24巡/全締切/全モデルの正式充足は未確認。
初期checkout b420631/branch workはcleanのまま保全。競輪PR291の並行更新は触っていない。
原本と未push2件UNRESTOREDの扱い、過去固定pin404、前向きHOLDは下記のとおり保全する。

## 2026-11-17: 実Safariの停止を日予算のネイティブ入力まで特定

診断のみの既存PR208は23 checks完了（10 success、13 skipped）後に通常merge、
実main cb3261d0ec66173313e12b74a02e45ac9404e399はreviewed treeと完全一致。
実Mac再試験44022519670/job133835055575はapp_checks:560のdriver.budgetでHOLD。
最初のviewportで原本読込・P1詳細・元Top8 hashでのモデル比較・研究からの復帰・結果件数は通過したが、
予算変更・2つ目のviewport・最終privacy判定までの合格はまだ証明していない。
Element Clear後の空値changeをアプリが拒否して元予算を戻す経路をローカルで再現し、同じAPP_UI_CHECK_FAILEDを確認。
既存PR203で、ClearをMacの通常CMD+A→修飾キー解放→置換入力→Tabへ変更する。
最終値wait・買い目hash・結果/横幅/秘密境界の全判定を維持。公開appや稼働source eff296fは変更しない。
新回帰を含むSafari20件success、実Macの再検証は統合後。CI合格だけでSafari合格とはしない。

服色/追跡/校正/接続/学習の既存ローカル120件もsuccessだが、実映像6艇・校正強さ・締切前予想接続の証拠にはしない。
旧公式結果長期保管manifestが参照するnative13559236491は実API404。今回の新P1/RESULTとは別の過去固定pin。
期限/認証を緩めず、過去原本の回収可否は未確認のまま残す。旧前向きplanのHOLDも保持する。
未push2コミットUNRESTORED、全競技全件/物理iPhone/未来改善は未完成。

## 2026-11-17: 真正な後継でP0保管と巡回01が成功、Safariの実画面はHOLD

main実HEAD df1ee16ca9d2d5813880a9d4b8f6d62ed765fb76（既存PR100通常merge）、
production実HEAD eff296f6d54ad4be297d93e32f1ee0d4592ad9e3。両方reviewed treeとの一致を確認した。
真正push run44019424267/job133825071851が、旧bootstrapの3原本を復旧して別reader照合し、
GET0・新予想0・使用量不変でFAILED_OWNER_ORIGINALS_RECOVERED→後継許可になった。
後継44019591352は04:47:27 UTC起動、P0表示復元/追加P0暗号化/保存がsuccess、
旧障害箇所のstep33「Retain exact additional P0 execution and physical save receipt beyond expiry」もsuccess。
巡回01は04:54:59〜05:05:53 UTCにsuccess、現在巡回02中。24巡完走はまだ未確認。
新native P1 artifact14300807230、ALL_MODEL P0 artifact14300856240/P1 artifact14301166184、
RESULT artifact14300863214をローカルで再取得し、実GitHub metadataのrun/head/ZIP SHA/サイズを照合した。
このZIP照合は別runnerの新原本AES・全モデル分母監査の代わりではない。後段の独立監査は未確認。

同巡回の公式結果長期保管count14300389237はHOLD_OFFICIAL_RESULT_RETENTION、
理由ALL_MODEL_OFFICIAL_RESULT_FREEZE_NATIVE_ARTIFACT_CLOCK（RUNNER_PREFLIGHT）。
結果暗号artifactの存在とは別に、全件長期保管の完成を認定しない。実失敗を保全して原因調査を継続する。
前向き比較count14300399647はHOLD/FROZEN_INPUT_REVIEW_REQUIRED、accuracy_improvement_proven=false、
independent_pre_cutoff_receipt_verified=false。元モデルに対する未来改善・本番昇格は未実証のまま。

実Mac Safari run44020668953（macos-15-intel）は固定parser導入と原本読取を通過したが、
画面操作でAPP_UI_CHECK_FAILED。実desktop Safari合格・物理iPhone合格とは呼ばない。
既存PR208を履歴保全して再利用し、非公開データを出さず公開checker関数/行だけを報告する診断を追加。
診断の回帰18件と独立review18件success。公開asset・原本・稼働中source・本番weightsは変更しない。

指定未push2コミットは引き続きUNRESTORED。4競技全件、T15〜10優先充足、8参考画面/実機iPhone、
服色6艇の継続識別・校正した強さ・予想接続、前向き改善は未完成。
[実保管と後継の証拠](evidence/boat-p0-storage-recovery-20261117.json)。以下は各時点の履歴を保全。

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
