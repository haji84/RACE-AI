<!-- RACE_AI_OWNER_CODE_ONLY_UNISSUED_RELEASE_20261108 -->
# 2026-11-08｜オーナー指示によるCODE専用再開、公式取得の固定境界は継続

PR #71 の取得担当が凍結していた厳密な公式ソース認証・発行は**解除していない**。現在HEAD 9375d89142829340d871fc1145c04ffc3a72f680 の初回CI run42464729698 は画面 fixture の日付期待値不一致で全体FAIL、issuer job は権限発行・source取得・capsule保存を全てSKIPPED。旧 V2 issue attempt run42457957612 は依存インストール権限で失敗、旧target8d880c9について転送refの既存capsule階層から発行済み対象は確認されない。過去6個のcapsuleを保全、UNKNOWN/拒否履歴・旧epochの取得枠は変更しない。

ユーザーの最新指示に限り、現在のbranchに実provider・issuer・workflow・trigger・secret・モデル係数を変更しない**CODE専用の非強制fast-forward統合とCI実行**を認める。これはsource ownerの通常fixed issue/replayの解除ではない。新headで公式source GET/権限発行を開始してはならない。ユーザーの目的は実公式結果に基づく保存Top8→モデル別PDCA→暗号Git→独立読戻しだが、正規Actions受入を新HEADで確認するまで成功扱い禁止。

細部証拠: docs/evidence/2026-11-08/owner-code-only-source-hold-release-preflight.json 。元の `ACTIVE_FULL_FIRST_TO_FIXED_ATTEMPT_TWO_BOUNDARY` ブロックを下に保持し、*公式ソースに関するHOLD* として引き続き有効とする。
<!-- /RACE_AI_OWNER_CODE_ONLY_UNISSUED_RELEASE_20261108 -->

<!-- RACE_AI_NATIVE_COLLECTION_BOUNDARY_20261108 -->
# 2026-11-08 10:15 JST｜実データ取得の検証境界：同じPRのHEADを固定

全既存モデル接続担当rootが、残るAUTO通常3件の取得用HEADを全初回CIで検証している。現行19／30枠学習済み、AUTO通常5／8・競輪0／8、新候補の実未来PDCA0件。既存の同HEAD全初回成功・唯一issue子・実capsule独立読戻し・固定attempt2・取得間隔／上限の条件は変更しない。

BC・7ac・29eは並行する画面／動画更新で共有HEADが変わり、すべて新capsule・新取得を始める前に安全停止した。画面・動画・検証docsは全て保持している。全初回検証から発行・読戻し・実取得終了までが一つの実行境界になるため、**担当rootが下記状態を解除するまでPR71への追加pushを待機する**。並行開発・テストは別checkoutで進め、未反映の変更を保持して次の取得終了境界でまとめて取り込む。GitHub保護・権限・branch設定を変更する指示ではない。

- 状態：`ACTIVE_FULL_FIRST_TO_FIXED_ATTEMPT_TWO_BOUNDARY`
- 発行前のmerge履歴誤検出と、既存画面変更後の2系統CI fixture不整合を実再現・修復済み。検証済みコードとworkflowが同一な場合だけ使えるsource-free P2準備を統合し、次の取得自身の全初回CIと既存capsule条件は維持する。新CODEの全CI完了前には権限を発行しない。
- 00:07Zの6d6db7d9結果照合修正と00:13Zの574c53af監査docsも保持。旧39c向けcontroller13は共有HEAD変更を検出して子commit作成・権限発行・取得の前に停止した。新cap・新provider通信0のまま、最新変更を含む検証HEADへ再設定する。
- 取得request SHA：`bcbdaa8b350402d8753d23632709eee6a15b75d6402b1d4cb7108334ed4fa5e6`
- 前の実source：`d41f505cb00557dd1a6173a19b0945d7849e57fd`／run42413260799／固定2回目全体SUCCESS。以後の新capsule・新provider通信は0。
- 実行対象HEAD／run／firstViewerはPR71の全モデル接続ブロックと既存タスクの最新担当ブロックで更新する。この文書の自己SHAを推測して固定しない。
- 終了条件：担当が実source全体終了・暗号journalとRESULTの独立読戻しを確認し、この所有ブロックだけを解除する。CI成功だけ、時間経過、他HEADの成功で解除しない。

以下の各担当の記録・成果・原本SHAはそのまま保全する。
<!-- /RACE_AI_NATIVE_COLLECTION_BOUNDARY_20261108 -->

# 2026-11-08 08:32 JST｜作業継続中：展示字幕の回復と同条件の映像あり／なし比較を実装

- **実装・レビュー済み:** 白文字・黒縁の字幕の読取失敗を固定の全画面白文字抽出で補完。成功した灰色OCRがUNKNOWNの場合だけ使用し、説明文・競合・失敗view・元画素・両RAWを保持する。映像回帰907件（失敗0/skip0）、字幕37件、比較関連86件が成功（範囲重複あり）。比較器の独立審査3指摘も修正・再審査APPROVE。全リポジトリ・最新CIの成功はまだ主張せず、PR71 Checksでexact SHAを確認する。
- **実映像を実行:** 新しい開発3枚は字幕候補0/3→3/3。連続21枚は19候補・2低信頼保留、時系列確認16・UNKNOWN5。原動画は実測184.266秒/5528frameで、既存CLIが全件完走し原PTS・journal・受領証を保存。185観測点中START47/LAP51/UNKNOWN87、時系列確認64・UNKNOWN121。これは読取状態の件数で、区間精度ではない。全区間の独立した原画参照照合は継続中。初回181秒の入力宣言による拒否も保全し、ファイル名の180秒を真値にしない。
- **実行画素へ統一:** OpenCV画像と製品FFmpeg画像は同じ61frame/PTSでもBGRが異なった。製品journalのBGRと全一致する画像を抽出し直し、新しい識別推論の前に参照を再結合している。未観測frame・未知の衣服色は埋めない。
- **予想への接続コード:** `boat_video_forward.fit_matched → register_study → forecast → score`で、同じ元入力・開催分離・凍結された映像なし学習版／映像あり学習版を比較する。同じ映像の分割混入、原本改変、締切後入力を拒否し、比較へ予想・結果の正確な原本参照を保存する。既存2系統の保存済み実予想は完全再現したが、実映像context・前向き映像比較は今回も0件。改善を実証したとは表示しない。
- **識別の修正を継続:** 既存画像モデルの特徴から学習した検出器は開発写真の6人を検出できたが、1451候補が出て採用不可。教師の誤登録・未注釈領域を点検し、次版1083候補、位置も学習する版112候補まで改善したが6人中5人に留まる。厳しい棄却境界でも全6人を保持できず不合格。生RAW・失敗・全候補を保全し、新しい白/中立服と非選手の実素材で学習を続ける。これは予想モデル系統追加や本番切替ではない。
- **未合格を残す:** 実実況は人手参照2項目中1項目。追加の音声・語彙・完全な教師モデルも検証し、元認識文や艇番・順位を正解へ書換えない。船体実寸の公式資料と正規の地理院画像を取得したが、実船体端点・水面/姿勢・カメラ誤差が未確定で、速度・加速度・ターンの強さは認定しない。現在LIVE、6艇の交差/隠れを含む実運用識別、強さ、前向き改善、実機Safariは引き続き個別ゲート。
- **保全:** 自動予想/映像intakeは同じPID・起動時刻で稼働、原本checkpoint SHA `c40bead05533ace426188ea8a111b1e4a4a639283f576972ba276e14a3e8ff1a` を維持。新しい取得件数上限、PR/Issue/workflow/課金、main統合・公開・投票・本番モデル切替なし。他作業の最新差分を保全して既存PR71へ反映する。本記録は完成報告ではなく、実装と検証を継続する中間記録。

[機械可読な中間証拠](evidence/boat-video-phase-matched-forward-checkpoint-20261108.json)。原動画・音声・教師ラベル・重み・私有予想本文はGitへ入れない。

<!-- END_RACEAI_PHASE_MATCHED_FORWARD_CHECKPOINT_20261108 -->

# 2026-11-08 03:45 JST｜画面内容判定を実装・原動画を全件検証。実実況の順位は未達

- **実装・動作確認済み:** 固定ローカル水面/艇モデル、同じmedia SHAの展示文脈、未観測を補間しない候補区間、原PTSと全frameの私有journal、日本語Reazon/Sherpaの任意経路を既存CLIへ接続。服色の艇番を実況で上書きせず、本番モデルや既存予想を切り替えていない。
- **開発評価の合格範囲:** 新177点の原画だけによるAI参照に対し、aquatic候補80/85・誤検出0/92。Fukuoka55/56・0/90と全体の事前基準は通過。一方、Nesnad7/11は媒体別90%未達、水面単独72/85も不合格。既知媒体内の相関したframe検証であり、LIVE・展示開催の認証・艇の同一性・予想的中率の証明にはしない。
- **実原動画の確認:** 最終V4で4376frameを全処理し、元decodeとのBGR/PTS全一致。146回の実NNも固定V4の38field・class map hashと全一致。宣言された展示文脈による54観測点・1候補区間を保存、未観測frameは埋めていない。全処理577.718秒で、映像の実時間処理は未達、密な区間境界精度は未検証。
- **実実況は未合格:** 人が確認した5秒の2順位対応は1/2一致。対象艇番の文字は2/2読めるが、後半の対応を保留している。日本語Whisper、Reazonのgreedy/beam4、一般36語/219句、過去履歴、公式FP32比較でも2項目の合格に届かず、失敗RAWを保全した。辞書へ艇番・順位列・選手名・正解文を入れず、誤認語の置換もしない。新しい人手参照は未受領。別Base-ASRとの一致はAI参照として別記する。
- **ソフトウェア検証:** 保持descriptorでのモデル読込、所有権、祖先パス差替え、否定/願望の誤受理、秒境界の抽出ずれをRED/GREEN修正。変更元のローカル全4031テストは完走し、2つの既存fixtureテストで4失敗記録（エラー0・skip0）を検出。上流の固定pin fixture修正を取り込み、PDCAは両競技で必ず変わるラベル改変へ修正した。検証器を緩めず、統合後の原本/PDCA全21件（28.019秒）と映像全868件（83.008秒）が成功。全4031件を修正後に再実行したとは主張しない。逐次runは並列化のため中断し、そのlogも保全。最新CI/HEADは[既存PR #71 Checks](https://github.com/haji84/RACE-AI/pull/71/checks)を正とし、この記録で未取得のCI成功を主張しない。
- **未完成:** 現在の公式LIVE接続、開始/周回の実開催認証、別媒体・交差/隠れを含む6艇の実運用識別、船体/水面の校正とターン・出足・行き足・伸び、映像特徴による締切前予想の前向き改善、実機Safari。今回の候補検出をこれらの完成へ読み替えない。
- **外部の情報・許可が必要な部分:** 正規に自動取得・利用できるLIVE経路、権利を確認した学習/検証素材と追加の人手正解、実機受入。拒否済み配信への再試行・迂回、素材の無断学習/公開、main統合・一般公開・実投票・本番モデル切替は行っていない。
- **保全:** 自動予想PID423218と映像intake PID271439は同じ起動時刻で稼働。私有予想checkpoint SHA `c40bead05533ace426188ea8a111b1e4a4a639283f576972ba276e14a3e8ff1a` を維持。新しい取得件数上限・予想モデル系統・PR・Issue・workflow・課金サービスは追加していない。他Workerの全モデル/結果/UI更新を同一branchの最新取得HEADから保全して統合済み。

[機械可読な検証記録](evidence/boat-video-activity-native-commentary-corrections-20261108.json) / [実行方法と各制約](BOAT_VIDEO_MARKER_IDENTITY_20261107.md)。原映像・音声・人手転記・モデル重み・私有予想本文はGitへ入れない。

<!-- END_RACEAI_ACTIVITY_NATIVE_COMMENTARY_CORRECTIONS_20261108 -->

<!-- RACEAI_PHASE_AND_ANNOUNCER_VALIDATION_20261108 -->
# 2026-11-08 00:17 JST｜展示区間・実実況を検証。持続区間と順位認識は未合格

**展示区間の実測:** 従来は宣言phaseをコピーするだけで自動判定未実装だった。固定した日本語画面OCR＋別原画2枚の確認を追加し、元映像の独立したAI目視参照と全147点で照合。展示55点中、確定候補は1点（見逃し/保留54）、生文字候補3点。誤陽性0だが、非展示91点も全UNKNOWNで、非展示を意味的に分類できた証拠ではない。一般展示19点・周回展示18点は全保留。時間IoUのsample-cell近似は確定0.0183、生候補0.0549。持続的な展示区間の検出は未達。人間GT/独立holdout/実LIVEの正解率ではない。

**原動画を実行:** 4376原frameを全て既存CLIで保存し、146回のOCRを実行。参照147点のBGR・sourcePTSは全一致。新 `--phase-only` は印字/人物/音声モデルや宣言phaseを不要にし、複数shotの解析で単一shotの偽申告を求めない。OCRしないframeへ観測を捏造しない。最初の147件失敗はprivate tessdata内のtsv設定欠落が原因で保全し、TSV直接指定・微小OCR box・終端state保存を修正して147件全OCR成功へ戻した。OCR成功を区間認識の合格とは呼ばない。

**実実況の原本:** 既に成功した正規アーカイブ取得元から同一原本2700〜4140秒の24分を取得し、4区間/288窓を全保存。各区間18,000 Opus packetの元demuxPTSと保存後PTSが一致。低音量・展示案内から探索し、実走順位/ゴール呼称を含む候補区間を確保した。後半は次3R展示へ移るため、全部を同じレース/phaseへ結合しない。独立Base転記36窓もTiny出力を見ずに凍結したが、AI同士の一致を人手正解へ読み替えない。

**人手正解との照合:** オーナーが確認した5秒（source3785.021〜3790.021）の正解は「先頭1番・2番手6番」。認識器/解析のRAWは回答前に固定済みで、clipのPCM SHAも一致。現製品はこの2つの順位対応を0/2件、明示艇番の対象は1番のみ検出し6番を欠落（対象1/2）。「先頭→戦闘」、6番のカタカナ崩れ・2番手の境界消失がある。他の2番tokenは部分参照だけでは誤りと断定しない。1clip/2fieldの検証で、全体の正解率・98%目標・実順位真偽を認定しない。**この例では不合格**。

**追加修正と検証:** 大きな絶対sourcePTSでPCMが空になるcopyts/t境界、説明の「全国で1番」を艇番へする誤りをRED再現し修正。低信号は発話なしと断定せず保留し、全窓を保存する。実製品APIで別12分144窓を実行（ASR109回/低信号35保留/length7保留）、順位文法候補2件は正解2件という意味ではない。高信号の音楽等にもASR誤認があり、RMS条件をVADや精度保証にしない。関連映像778件PASS/0skip、79.396秒。契約テスト合格と、実区間/実実況の未合格を分ける。

**残る原因:** 画面見出しがない区間・背景の実艇活動を判定できず、文字候補の持続も弱い。短窓ASRの専門語/順位語/艇番が崩れ、音声と画面のrace境界・放送遅延・身体対応も未校正。人手正解を見て元RAWを書き換えたり、同音語の決め打ち修復や残番号埋めで合格へ変えない。

**保全:** 元予想SHA `c40bead05533ace426188ea8a111b1e4a4a639283f576972ba276e14a3e8ff1a` と保護checkout/稼働PID423218・271439の起動時刻を維持。停止/再起動、本番予想モデル切替、main統合、一般公開、投票、新PR/workflow/有料サービス・取得総数/GET/巡回数/総時間の停止上限追加なし。映像・音声・人手原文・モデル重みはprivateに保持し、公開Gitへ入れない。

[全実測・版・証拠SHA](evidence/boat-video-phase-commentary-validation-20261108.json)。以下の以前の実装・未検証の記録は当時の履歴として全て保全する。
<!-- END_RACEAI_PHASE_AND_ANNOUNCER_VALIDATION_20261108 -->

<!-- RACEAI_EXHIBITION_COMMENTARY_AUXILIARY_20261107 -->
# 2026-11-07 23:28 JST｜展示順と実況の補助照合を実装、音声保全・日本語認識・CLI統合を実行

**実装済み:** 服色＋現在画素追跡を主にし、周回展示の明示された通過順/艇番と、実況の「先頭○号艇・2番手○号艇」を別の補助情報として照合する。スタート展示の進入コースを1〜6の周回順へ置換せず、欠場時の予定順は明示入力する。区間や順番だけでUNKNOWN乗員を確定せず、服色ラベルの上書き・残番号埋め・色観測票の追加をしない。実際の自動通過区間検出の精度は未実証。

**音声欠落を修正:** 既存capture exportの `-an` が埋込音声を落としていた。今後の新しい書出しは最初の埋込音声をstream-copyし、音声なしも成功、非対応codecは黙って捨てず明確に失敗する。実FFmpegの映像/AACパケット・PTS/DTS一致と旧受領証の無変更再利用を確認。既存の動画原本や音声なしexportは再作成せず保全し、別HLS音声groupの新規取得や既知403再試行をしない。

**実音声で実行:** 固定SHAのローカルWhisper-tiny経路を追加。既存日本語解説145.844535秒を5秒窓30区間で処理し、2333513 PCM sample/約27.906秒（CPU2thread、音声部分）で完了。原本不変。実音声は展示説明であり、実レース順位の実況ではない。専門語誤認識があり、旧timestamped試行の反復も保全。番号・順位の実認識精度は未検証。音声結果を公式結果や締切前予想へ流用しない。

**実装の統合実行:** 同じ正式CLIで、元映像BGR一致6枚を含む私有の6秒間引き派生動画を、実人物検出＋実日本語音声認識＋frame時刻照合＋私有journal/receipt保存まで通しSUCCESS。これは連続6艇識別の受入ではなくtransport確認。派生動画のPTS再量子化は元時計と区別。UNKNOWN phaseから艇番を作らない。

**検証・失敗修正:** 関連映像748件PASS/0skip（75.820秒）。否定・疑問・人気順・複数字の断片を順位へ誤変換する不具合、訂正や新しい順位/通過の期限切れで古い発話が復活する不具合をRED再現して修正。独立レビューも既存16assertionsと追加2tests成功。発話の利用可能時刻は音声入力窓の終端以後とし、映像relative tではなく実source_ptsに照合する。実況遅延・実発話の意味/認識精度は未校正。

**保全・残る条件:** 自動予想PID423218/映像取込PID271439の起動時刻と元予想SHA `c40bead05533ace426188ea8a111b1e4a4a639283f576972ba276e14a3e8ff1a` 不変。稼働checkoutや本番予想モデルを切り替えず、停止/再起動・main統合・公開・投票・新PR/workflow/サービス/課金・取得総数/GET/巡回数/総時間の停止上限追加なし。現在LIVEの正規音声接続、実実況の艇番/順位精度、展示通過区間・服領域・艇体結合、映像の実時間性能・強さ/予想改善は別未達のまま。

[実行方法と限界](BOAT_VIDEO_MARKER_IDENTITY_20261107.md)／[コード版・全件数・証拠SHA](evidence/boat-video-broadcast-context-20261107.json)。以下の以前の実測・他作業の履歴は全て保全する。
<!-- END_RACEAI_EXHIBITION_COMMENTARY_AUXILIARY_20261107 -->

<!-- RACEAI_CLOTHING_PRIMARY_IDENTITY_20261107 -->
# 2026-11-07 22:59 JST｜服色を主にする識別を実装、実映像で6人の対応を57frame連続維持

**実装・実行済み:** オーナーの提案どおり、白1・黒2・赤3・青4・黄5・緑6を主根拠にする `boat_video_clothing_identity.py` を追加。印字番号を必須にしない。既存解析CLIの `--clothing-only` はOCRモデル不要で、人物検出→服色→実LK追跡→全frame私有保存まで動く。新予想モデル・外部サービス・workflowは追加していない。

**実映像の照合:** 既存の低運動61原frame/2秒を自動人物提案から処理。従来の物理R対応と照合した主対象366行は352一致・初期確認中14UNKNOWN・誤番号0。6人すべての色IDはframe274〜330の57frame連続で一致し、追加motor25行は全UNKNOWN。352は現在色観測289＋現在画素で過去色を保持63。全6色を同じ現在frameで新たに観測したのは13frameで、残りは保持を含む。緑の最長保持は22frame/0.732秒。元の境界意味UNKNOWN2行も保持し、352を衣服ROI純度の独立正解数へ読み替えない。

**初回失敗と修正:** 初回は薄緑がneutral白候補へ落ち、重複防止でIDが切れた（全6一致26/61、誤番号0）。G優位の低彩度領域を白の明暗処理へ入れない修正と回帰で、全6一致57/61へ改善。重複・競合・切替・喪失はUNKNOWN、残番号埋めなし。現在の実画素が明確な間だけ色IDを保持し、保持を新観測に数えない。

**検出も再実行:** 原frameとBGRが全61枚一致する私有・無劣化派生動画をCLIに入力し、キャッシュなしの固定モデル427forwardを実施。検出box・色ID・観測/保持状態が先の結果と61/61一致、全frame保存とSUCCESS受領証を確認。派生動画PTSは元と最大±1ms異なるため、元PTS保存の再生検証と区別する。処理179.674秒/入力2秒で、LIVEを実時間処理できた実証ではない。

**検証:** 関連映像696件PASS/0skip（84.946秒）。保存直前メモリ不足の原子的state更新と、caller原画の一時変更→復元からの誤番号を独立レビューでRED再現し、私有snapshot/事前割当でGREEN。旧印字/OCRの失敗と原本は残す。最新HEADの全PR CI成功はまだ主張しない。

**残る条件:** 人物box内の衣服位置priorであり、意味的な衣服segmentationは未完成。ヘルメット/機材境界、黒服＋色hood、別場・角度・交差・隠れ・長尺・現在LIVEの一般精度と実時間性能は追加検証が必要。`identity_validated=false` / `model_eligible=false`。艇体位置・ターン/出足/行き足/伸び・予想精度改善はこの2秒の結果から認定しない。

**保全:** 自動予想PID423218・映像取込PID271439は元起動時刻のまま。保護checkoutと元予想SHA `c40bead05533ace426188ea8a111b1e4a4a639283f576972ba276e14a3e8ff1a` 不変。取得総数・GET・巡回数・総時間の停止上限を追加せず、停止/再起動・main統合・一般公開・投票・本番予想モデル切替なし。既知403のprovider停止境界を回避する取得も行わない。

[変更・実行方法](BOAT_VIDEO_MARKER_IDENTITY_20261107.md)／[実測・版・証拠SHA](evidence/boat-video-clothing-identity-20261107.json)。以下は以前の印字方式・他作業の時点別履歴として全て保全する。
<!-- END_RACEAI_CLOTHING_PRIMARY_IDENTITY_20261107 -->

<!-- RACEAI_2139JST_901_PROBE_AND_FULL_READBACK_20261107 -->
# 2026-11-07 21:39 JST｜901の全体CIと第2回AUTO probe、全履歴読戻しを確認

既存Draft PR #71の検証HEAD `901fb57d2d0f1d0fa0b4051285dca399654a4738`／[run42371023982](https://github.com/haji84/RACE-AI/actions/runs/42371023982)はattempt 1／2とも全体SUCCESS。初回は全Python3,714件（360 skip・失敗0、1,427.474秒）、動画283＋185件、UI31件を通過した。attempt 2は認証済み同HEAD初回の重い2検査を再利用し、軽量検査・実取得・journal読戻し・画面検査を通過した。[全CI・第2回probeの件数](evidence/2026-11-07/901-full-ci-and-second-bounded-probe-counts.json)。

実第2回AUTO probeは8 GET・全200、document 1件＋背景通信7件で上限到達し、RESULT 0・`HOLD_UI_OR_SOURCE_UNAVAILABLE`／`REQUEST_LIMIT`。CSS 3件のcache再利用は実確認できた。POSTの`NORMAL_READ_IDENTITY`拒否2件はendpoint原本がjournalに残っておらず、拒否経路や原因を推測しない。元journal artifact13574582081のZIP・metadata・暗号文を既存commit `710b7437740ae38c05c68fb3a26cb00f4e54a374` へ保持し、元バイト一致と独立Git読戻しを確認した。[journal認証](evidence/2026-11-07/901-probe-journal-authenticated-counts.json)・[保持](evidence/2026-11-07/901-probe-journal-retention-counts.json)。旧browser実数UNKNOWN／予約24・旧固定epoch上限32は維持する。

日付延長履歴はb569／run42370578793の実Actions jobで全旧世代263か月を復元し、掲載7,964日＝PARSED7,846＋PARTIAL117＋公表待ち1日を確認。11月6日gridも7,963原本・2,643選手×24場＝63,432セルを復元した。提供元アクセス0で、b569の該当job成功と901の全workflow成功を分けて記録する。[実読戻し件数](evidence/2026-11-07/b569-full-history-grid-ci-readback-counts.json)。

実学習19/30、残AUTO6・KEIRIN5、新19候補／現行全30枠の実未来PDCA 0は変わらない。旧BOAT14の通常1レース・14組は別世代の証拠。次の同一1ケースrequestは未発行の準備・最大8・live plan不変であり、直前terminal12:39:30 UTC＋1秒＋1時間の最早13:39:31 UTC（22:39:31 JST）以降かつ新HEAD初回全体CI成功・新たな固定attempt 2認証などの条件を再確認してからだけ送信する。[次回準備](evidence/2026-11-07/third-auto-probe-preparation-counts.json)。新workflow・定期タスク・本番切替・実投票は追加していない。詳細は[現行の残枠報告](REMAINING_MODEL_COMPLETION_20261107.md)。下の記録は各確認時点の履歴として保持する。
<!-- END_RACEAI_2139JST_901_PROBE_AND_FULL_READBACK_20261107 -->
<!-- RACEAI_IDENTITY_UNMET_AND_QUOTA_CHECKPOINT_20261107 -->
# 2026-11-07 22:23 JST｜番号付き6艇は未完成。原因・検証・新原本を保全

**完成した部分:** current点対応を修正し、原画上の6人の可視partを同じ匿名R1〜R6で全61frame/2秒追跡。関連677テストPASS/0skip、統合後68.198秒。既存Draft PR #71へ反映した。数字は全None、船体boxなし、motor25行残存で、番号付き6艇の完成ではない。

**未達原因を実測:** RGB外観V1の自動391入力は、乗員part366中181一致・170棄却・2→3の誤り15、1/6は全61で棄却。全6番号一致0/61。motor25は全て0だが人物も落ちるためgateへ不採用。0を除いた診断でも1→2/3、6→5となり、閾値緩和/残番号埋めで直らない。人物存在と番号未読の分離、衣服/姿勢/色のデータ不足、文字単独の曖昧さ、艇体との一意な結合が残る。旧参照や失敗は書き換えない。

**船体・原本:** 固定SAM2 maskは清潔なhull coverage5/6・5/6・6/6。自動contact V2は手動正解promptなしで20pair/全60maskを保存したが意味未採点。正規公開CC写真の100原本・個別license・nativeRGB/BGRと重複0を確認、施設等も含み100教師ではない。原本resize0、同series相関・catalog未列挙gapを保持し、取得上限を100へ設定した訳ではない。新たな確実な1号艇rider1写真は未訓練V2候補に分離する。

**CIの区別:** 凍結commit d9c2のWorkflow42358009132は、別のseller廃止/legacy readback検証stepで失敗。関連映像677件のローカル合格を全PR/最新HEADのCI合格へ読み替えない。他作業のseller廃止を戻す修正は行わず、scopeを分けて記録する。

**継続を妨げた実行条件:** 複数の並列開発agentが実際に `You’ve hit your usage limit.` でerrored。追加課金/新accountは作らず、全コード・モデル・RAW・参照・失敗・未着手の引継ぎを保全した。現在の番号器やmaskを本番へ採用せず、未検証の確率・回収率を表示しない。

**保全:** 既存2プロセス(PID423218/271439)は元起動時刻のまま、保護checkout/原予想SHAc40bead…を維持。停止/再起動・main統合・一般公開・投票・本番予想モデル切替なし。既知403/同provider停止境界を回避せず、新しい予想モデル系統・外部サービス/課金・取得総数/GET/巡回数/総時間の停止上限は追加していない。現行公式映像の正規接続、実機Safari、4競技継続運転・前向き改善の実証は別未達のまま。

[実装と未達原因](BOAT_VIDEO_MARKER_IDENTITY_20261107.md)／[版・全件数・SHA](evidence/boat-video-identity-causes-20261107.json)。未採点のcontact60mask、許諾source100の人物/印字annotationと未読/機材の分離、番号/part自動結合から再開し、同じ調査や失敗試行を重複させない。

<!-- RACEAI_2031JST_INTEGRATED_CHECK_20261107 -->
# 2026-11-07 20:31 JST｜統合済みHEADのCI結果と安全停止の再照合

既存Draft PR #71のHEAD `151aa6e59074ba48e73c1036f5256e2396afd479` を再取得。統合後の既存[Viewer CI 42366037173](https://github.com/haji84/RACE-AI/actions/runs/42366037173)は2026-11-07T11:26:35Zに全体completed/success。[並行復旧CI 42364217725](https://github.com/haji84/RACE-AI/actions/runs/42364217725)のattempt2もcompleted/success。ただしCI成功・収集stepのsuccessを、新しいAUTO/KEIRIN通常結果・19枠未来PDCA成功とは認定しない。実結果ZIP保存stepはskipped。

通常source workflow405276784の最新成功runは[42352096559](https://github.com/haji84/RACE-AI/actions/runs/42352096559)。完了3巡・119/240 GET・`BOUNDED_SESSION_END`・`source_wait=null`。独立Git原本refの `state/boat-source-control/v1/latest.json` と当日run別記録をGitHubから取得し、workflow ID・repo ID・run ID・branch・HEAD・completed/success・control/continuity artifact ID/digest/sizeとGitHub APIメタデータの一致を確認した。keylessではHMAC/暗号原本の独立復号は未確認。最新完了source ZIPの実バイト再取得も未実施。今回確認した同workflowのactive/queued/pending/waitingは0。新sourceの起動判断に必要な所有者鍵の真正性検証をこの環境では完了できないため、トリガー追加をしない。

販売者削除は現行15系統/30枠のサイト反映と既存回帰成功が先行実証済み。実学習19/30（BOAT14、HORSE5）、未完了11（AUTO6、KEIRIN5）に変化なし。AUTO/KEIRINの旧collector journalによるbrowser予約24件の実通信数UNKNOWN・HOLDは維持。新しいcollector、失敗runのrerun、capsule独立発行、上限変更、原本改変、本番採用、実投票は行わない。固定28シナリオは実購入ではなく、前向きの精度改善も未認定。
<!-- END_RACEAI_2031JST_INTEGRATED_CHECK_20261107 -->

<!-- OWNER_REMOVED_SELLER_STATUS_20261107 -->
# 2026-11-07｜販売者モデルを現在の対象から削除、実サイト15系統の表示確認に成功

ユーザー指示により販売者モデルを実行・新規学習・通常画面・完成条件から外した。現在は15系統/競技別30枠。既存19枠の実学習とBOAT14枠の実未来PDCAの証拠は保持し、残る実学習はAUTO6・KEIRIN5の11枠。下にある旧31枠や販売者入力不足の記録は当時の履歴であり、販売者のwaku10取得を再開しない。

表示専用[42363442840](https://github.com/haji84/RACE-AI/actions/runs/42363442840)は全体success。132P0文脈・新規予想0を暗号化保存し独立読戻し・原本Git保持を通過。2026-11-07T10:27:40.754Zの実Chrome390/1440で、15系統・販売者非表示・当日結果98・native P1 group30・選手名・率/収支・日予算変更・1R1000・前日履歴を確認し、実JSONの最終gateも成功した。削除実装4a52c69cの[全体CI42363760967](https://github.com/haji84/RACE-AI/actions/runs/42363760967)も2026-11-07T10:53:32Zにsuccess。Python3,591件（360 skip）・隔離動画283/185件・Node88/99件・7画面4幅を通過した。並行更新c43871baの削除回帰も成功済み。

元予想・結果revision・元clock・日別成績・固定予算配分は保持した。この削除作業による通常source workerの取消/再起動/設定変更、公式source GETは0。未確認結果・AUTO/KEIRINの通信会計HOLD・将来の的中率改善は未解消のまま。[削除と検証](BOAT_SELLER_RETIREMENT_20261107.md)と[件数証拠](evidence/2026-11-07/seller-retirement-presentation-counts.json)を参照。
<!-- END_OWNER_REMOVED_SELLER_STATUS_20261107 -->

<!-- RACEAI_RIDER_CURRENT_POINT_CHECKPOINT_20261107 -->
# 2026-11-07 17:39 JST｜6人の匿名ID断絶を実画素対応で修正。艇番・船外機除外・船体結合は未完成

**実装・実測済み:** rider対応付けはIoU≥.5を維持し、current LKの実点≥4・既存品質比率.75・他R点0・現frame/PTS/BGR/sceneの一意な支持を追加した。既存点に触る未結合partは、新しい別人と断定せず全件UNBOUNDへ保持。番号/scoreで代表を選ばない。直接印字3根拠・競合・replay・cut/loss・未知の保持を維持し、独立41case GREEN。既存2プロセスと予想原本は変更しない。

**6匿名IDの検証と限界:** 同じ61原frame・2.0秒で実LKを実行し、原画採点で6人のprimary rider partがそれぞれ同じR1〜R6を全61で保持した。旧版の完走4→6、重複出力11→0、総R key23→7、primary入替の観測0。一方R7は船外機で25行残存し、余分な非人物なしの6出力は36/61。391行=乗員part366＋船外機25、元373検出=fresh362＋UNBOUND11を完全保存。数字は全None・hullなし。既存実NN427回の出力をreplayし新NN0、実LK13.921秒。未知の私有既存映像の短いAI DEVELOPMENT参照で、人間GT・全レース・番号付き6艇や強さ評価の完成ではない。

**番号の根拠不足:** 旧pixel/HOG14120行を再現して全HOG/label一致、新36字を足した21320行・小CNN1fit/30epochを検証した。oracle18は8一致・9棄却・異番号1、4は0/3、全6一致0/3で不採用。旧HOG比は新正読5・失った正読2という複合変更。匿名のnative単字だけを別AIへ再読するとCLEAR6/曖昧12で、CLEARの半分は既存場面参照1を7と読んだ。場面文脈依存も原因として区別し、旧参照やPP原文字を都合よく書き換えない。

**機材除外・学習データ:** DINO PERSONの固定22contextも本人支持13/18、隣接人2・候補なし3、motor4全て誤PERSONを残し不採用。別のRGB appearance学習へ、写真の確実な教師54・許諾動画の可視教師9・人が居ない機材66・背景37を原画/権利/重複/色channelで検査中。class1はまだ2写真例で、unknown/他rider混入3例を無理に教師へ戻さない。外部の正規CC公開元から、大きな直接印字1と白い上衣の新しい高解像度原本も取得・権利確認できた。これは別の静止写真であり、既知の公式LIVE403が解決した証拠ではない。進行中の固定学習snapshotへ未注釈資料を混ぜない。

**テスト・CI:** 統合後の関連映像677件PASS/0skip、68.198秒。旧CI42351039195は合成MP4の表示枚数前提で失敗し、ローカルでもencoded6/displayed5を再現。製品decoderを変えず、並行HEADのMP4明示6枚・muxer offset2・encoded/probed/decoded枚数確認を取り込み、CLI16件PASS。先の677件/76.335秒はMatroska版のclosed検証として保持し、統合後677件/68.198秒も確認した。最新exactHEAD全CIの合格とは別に扱う。旧775全編・606採点・追加65比較のsource/証拠は保持する。

**未完成・外部条件:** 船外機の除外、番号器と自動physical part/print結合、船体mask/座標、遮蔽後再同定、現在の正式映像での継続検証、強さ評価と予想改善は未完成。実機Safari/4競技長期実運転は別途実測が必要。既知拒否contentと同providerの停止境界を守り、UA/host/token等の回避・問い合わせ送信・新契約/課金はしない。main統合・一般公開・投票・本番予想モデル切替は無し。取得総数/GET/巡回数/総稼働時間の停止上限を本修正で追加しない。

[原因・修正・実測](BOAT_VIDEO_MARKER_IDENTITY_20261107.md)／[新旧版・集計・SHA](evidence/boat-video-identity-causes-20261107.json)。完成へ必要な番号・意味判定・結合の実装と検証を継続中。

<!-- RACEAI_RIDER_PART_LIFECYCLE_CHECKPOINT_20261107 -->
# 2026-11-07 16:50 JST｜未達原因を分離し、匿名乗員の実画素追跡を追加。6艇番の完成は未達

**実装済み:** 既存SHA固定YOLOXのPERSON headをboatと別型で読む `boat_video_rider_detector.py`、番号と分離した `boat_video_rider_tracking.py`、既存marker CLIの任意 `--rider-model` を追加。同じ原frame/PTSで匿名乗員とmarkerを別fieldへ保存する。番号producerは既定Noneで、近さ/包含/色/余った番号から結合しない。本番予想・既存intake既定は変更しない。実LK・current detection・flow-only・lost/曖昧性と最後の検出を分け、宣言された印字3根拠がある時の番号保持も新しい印字観測と区別する。

**失敗修正と検証:** 再played画素の矛盾後に古い番号が復活する不具合、同じ/ほぼ同じ印字へ別乗員が異番号を主張する不具合、重なるflow-onlyの二重出力をREDで再現・修正。独立レビューGREEN（番号/重複/相互交差7case）。新detector39・任意CLI16も独立PASS。関連映像 **670件PASS/0skip、71.743秒**。これは最新repository全体の全テスト合格や現場精度の証明ではない。775全編は旧CLI89e63、任意rider追加はCLI b3f802/track7d337とsource scopeを分けて保存する。

**実映像で確認した部分と未達:** 固定61原frameの実YOLOX427forwardで373候補、原画全件採点は実乗員part369・船外機4・同乗員の重複part11（369内）。6人全員を検出したのは53/61frame。実LK＋その実検出の完全replay（新NN0）は402track行、匿名4IDは全61で継続したが、残りは断絶/重複が残る。数字は全None・船体boxなし。402行の別原画採点は乗員part377・船外機25。6人の可視partは全61に存在するが、重複/船外機なしの6出力は30/61、6番partは7匿名ID・4番は11IDに断絶した。全61出力に一致するread-only traceでは、廃棄17keyにもcurrent LKの支持があり、形状差/重複候補との対応付けを追加調査している。flow成功を人物/艇番の意味的正解へ読み替えない。

**全編の意味採点を完了:** 既存全775frameの606登録は、正しい現在印字564・背景非数字36・艇体非数字5・UNKNOWN1。封印済606ラベルへ後から追加65を結合すると正しい印字63・艇体非数字2、ラベル変更0。最大同時正読3、固定17frameの6番号完走0/6は変わらない。AI DEVELOPMENT/学習重複であり一般精度ではない。

**番号器の未達:** 正しい乗員cropを与えてもRGB番号器は10/18（誤7/UNKNOWN1、4/6正答0、全6一致0/3）、旧HOGへ20字追加したlinearもRBFも印字oracle5/18で全体改善無し。失敗を保全し本番へ採用しない。既存許諾写真の未注釈分から直接印字・可視部位を追加確認中で、UNKNOWN原動画を訓練しない。背景除外、一意なphysical part/print binding、遮蔽後再同定、6番号同時継続と現在レース検証は未完成。強さ評価や予想改善はこの件数では実証していない。

**保全・外部条件:** 既存2稼働プロセス・保護checkout・予想原本を維持、停止/再起動・本番モデル切替・main統合・一般公開・投票なし。取得総数/GET/巡回数/総稼働時間の停止上限は本追加で設けない。既知403と同provider追加probe停止は維持し、拒否回避・問い合わせ送信・新サービス/課金なし。全会場403や一律の外部API契約必須とは断定しない。実機Safariと4競技の継続運転/改善実証は別の未達として保持。

[原因・実装・実測](BOAT_VIDEO_MARKER_IDENTITY_20261107.md)／[版を分けた証拠とSHA](evidence/boat-video-identity-causes-20261107.json)。6艇の自動識別完成へ実装と再検証を継続中。

<!-- RACEAI_SIX_BOAT_CAUSAL_CORRECTION_20261107 -->
# 2026-11-07 16:08 JST｜識別の欠測原因を再現して修正。固定102機会は59→67、6艇継続は開発中

**実装・実推論済み:** 同じ実LK context・同じfresh番号なのに位置/面積の再判定でIDを切っていた実5件を特定し、typed `CONTEXT_IMAGE_TRACK` を対応付けへ渡す修正を追加。min3・重複・異番号競合・blank・scene/時刻/サイズの拒否を維持した。有限な正規flowが任意hintの品質条件外なら理由付きで従来geometryへ戻し、不正schema/非有限値は拒否する。独立レビューで実flowの再計算後の品質値による中断を再現・修正してGREEN。

**確認した改善と限界:** 同じ76原frame・同じ重み・全自動入力で登録86→98。旧86の番号/bbox/BGR/PTSを保持し、追加12もAI原画参照と一致（部分glyph6、境界接触4、PP生文字不一致3は未修正のまま）。最終source `94d80c7e…/956658ac…` の全76 identity recordを、追加12件を採点した候補版の実出力へ結合。固定17frameは1〜6順 **11/10/13/12/11/10**、合計67/102、初回登録以降67/84。全102の分母・cold startを除外せず、**全17frame完走0/6・最大同時3**を維持。AI DEVELOPMENT/学習重複で、一般精度・人間GT・現在レースの実測とは扱わない。

**全編の処理・意味を区別:** 最終CLIが原本775frameを全処理、index・BGR・元PTSを775/775でcanonicalと照合。原本/全source/旧重みの前後SHA不変、receipt `ecf119e9…` / journal `92d998ba…`。606登録は正解数でなく、全606の原画採点中。frame37の建物を4とする反例は最新でも残る。同じ775入力の対応付けだけの再生は旧M=新M(hint無)が541、新M(hint有)が実606と全775一致（追加65/削除0・新NN/OCR/LK0）。追加65の意味的正誤は未確定。SUCCESSを識別成功としない。

**残る根因:** 岸の部材の偽4で真4も棄却すること、印字markと物理対象のlifecycleが別であること、入力領域がhull part/複数艇混在でrider全景と一致しないこと、少数source/可読性/学習表現の不足、候補全抽出の計算時間。既存YOLOXの別映像3frameでは各6艇のpartは候補に存在するが、20boxの内訳は全体envelope1/hull part11/混在8で、一意な6対象や番号識別の完成ではない。番号・可視body/rider・歴史根拠を分けて検証中。

**不採用も保存:** 写真20字追加は別映像oracle18で5一致/非ゼロ誤読2/棄却11、全6anchor0。広いcontextの既存YOLOXは真の印字16位置中5だけ保持。body HOGは転移艇8/10・背景7/12、wholebody RGB番号分類は転移1/8で本番へ組み込まない。色証拠無しで棄却すると実4も落ちる。性能では全候補抽出が約67%を占め、頻度を下げると登録27→16へ低下。2並列も壁約4%短縮に対しCPU約56%増で未採用。全RAW・学習/入力/失敗・別採点は私有保存。

**検証・保全:** 最終映像 **627件PASS/0skip、69.171秒**（関連6module122件）。旧Python3,106PASSは以前のcommitの記録で、最新HEAD全体の合格とはしない。既存CIのViewerは15分で全Python途中にcancelledだったため、同jobの検証時間を40分へ変更し、既存の映像stepへ7moduleを追加する。新job/workflow/scheduleやsource巡回は追加しない。稼働中の既存2プロセス・保護checkout `ef818e51…`・予想原本SHA `c40bead0…` は維持し、停止/再起動・本番モデル切替・main統合・一般公開・実投票は無し。原動画/重み/私有予想/URLはGitへ追加せず、取得総数/総GET/巡回数/総稼働時間の停止上限を本追加で設けない。

**外部条件:** 既知contentの403と同provider追加probe停止を保持。全会場403・全会場が外部API契約必須という証拠はなく、別providerの現在content/利用条件も未確定。拒否済contentの再要求/別host等の回避・問い合わせ送信・新課金は無し。UNKNOWN既存別映像は私有CV検証のみ、訓練/公開に使わない。実機Safari、4競技の長期実運転、強さ/世界位置と予想改善はこのテスト数で合格にしない。

[原因・修正・実測](BOAT_VIDEO_MARKER_IDENTITY_20261107.md)／[今回のsource版・集計・SHA](evidence/boat-video-identity-causes-20261107.json)。6艇継続の全体完成は未達のまま、実装・再検証を続ける。

---


<!-- RACEAI_AUTOMATION_20261107_1415_SOURCE_TEST_SCOPE_FIX -->
# 2026-11-07 14:15 JST｜新しいsource runは開始前テストで停止。既存9-step検証を追加2保全step対応へ修正し、正式source再起動はHOLD

**実GitHub観測:** Draft PR #71 / workflow405276784 / branch `feat/four-sport-forecast-audit-view-20261022`。source run `42341923234`（HEAD `8fda369102025bd0cc9ce30b2df541bb5bafeaf8`）は2026-11-07 14:15:42 JST `completed/failure`。失敗stepは `Test originals, pending results, tampering and unchanged models`、240テスト中1失敗。原因は `tests/test_cycle_workflow_references.py` の9個の必須巡回stepに、新設の結果原本retain/count-only receipt 2 stepを誤算入し、`AssertionError: 11 != 9`。このrunは初回P0復元・新しい公式GET・予想保存まで進んでいない。失敗runの再実行はしない。

**限定修正:** 既存compositeの必須9 stepの検証は減らさず、追加2保全stepを独立して名称・暗号鍵境界・active条件・元結果後の順序・保全結果receipt・optional継続条件で検証する。元モデル・係数・予想原本・コンポジット/ワークフローの実行仕様・GET上限・concurrency・起動頻度は不変。修正の実ActionsでのPASSは**この記録時点では未確認**。新しい正式sourceの起動は行わない。

**HOLD:** count-only original-vault `state/boat-source-control/v1/latest.json` はrun `42330631694`（失敗run）を参照したまま。直近成功run `42336097863` の第1巡のZIPハッシュ検証は既報の範囲だが、このlatestの所有者鍵HMAC/原本確認は今回未実施。成功の証拠に置き換えず、最新control/実run/署名整合が確認されるまで新sourceトリガー禁止。既存原本refやキー、旧run・結果revisionを変更しない。

**研究学習との区別:** 研究実fitは公開監査文書に記録されたBOAT14枠/31枠（同一8実レース6学習・2holdout）、残17枠（売主型1、非BOAT16）。新しいBOAT14枠の公式結果付き未来PDCA、非BOAT全16枠の通常8R/枠、LEARNED_SHADOWの未来優位性は未認定。独立の新原本・追加的中率・正式収支をこの停止runから計上しない。

新タスク・別workflow/PR・追加source run・再実行・本番モデル切替・投票・公開・外部クラウド・課金は行わない。

---

<!-- RACEAI_SIX_BOAT_MARKER_IDENTITY_20261107 -->
# 2026-11-07 JST｜1〜6の自動番号登録86件を原画照合。6艇の継続識別は未完成

**実装・検証済み:** 全画面の番号候補抽出、任意の全6,625クラスPP-OCR、3別frameの番号根拠、実画素の局所追跡、再検出による位置補正、重複片の整理、私有の全frame診断CLIを既存Draft PR71へ追加した。元の通常reader・本番予想の既定は変更しない。分類器の離散ラベルはCTC確率と分離し、モデルSHA・非確率scope・`sequence_likelihood=null`を記録。別フレームの原画素が3回必要で、同一frameの加工を票に加算しない。既存の予想・動画intakeプロセスは停止/再起動していない。

**実際の達成範囲:** 許諾済み既存日本動画の4区間・計76原frameを全自動で処理し、1〜6を含む86登録を出力。原画参照に一致する77件と、重複修正で増えた9件を照合し、対象86件の誤番号・背景登録は0。最終source `599dffc6…` の実出力は採点済みイベントとbbox/BGR/PTSが完全一致し、実PP317入力とsoftmaxの全SHAも一致した。4の同一ID連続登録は5→12frame（実PTS差0.367秒）。ただし同一動画の12数字等を学習したAI DEVELOPMENT参照で、独立精度ではない。固定17frameの登録coverageは1〜6順に **10/5/11/12/11/10**、**継続完成0/6・最大同時3**。累積6番号の出現を、現在の6艇継続識別の完成へ数えない。

**全編・失敗の確認:** 別の実CLIで元動画775frameを全処理し、全BGR SHA・実PTSをcanonicalと照合した。原本SHAは `1ac1f0c2…` のまま。SUCCESS receipt `6eacf60c…` は処理完遂・整合性で、510登録の正しさを示すものではない。frame37では建物の線を番号4として登録した反例がある。3実観測アンカーからのCSRT試験も204回すべて枠を返したが、原画採点は正しい船体186・搭乗者だけ1・混合曖昧15・別艇2。約0.567秒の17future追跡成功は9/12試行で全6番号に短い成功例があるものの、同時6艇・長時間・新番号再読ではない。背景除外のDeepLab/DIS/Grounding DINO固定試験は実番号の欠落・UNKNOWN・背景誤認が残り、必須gateや本番へ採用していない。

**修正・テスト:** 独立レビューの入力crop変化、割当後のメモリ確保失敗、矛盾OCRのblank化、異番号へのblank転送、再検出位置の未補正、部分片の連鎖統合とM側での再統合を再現して修正。CLIも保持FDのctime・終了時全SHAを検査し、同サイズ変更＋mtime復元ではSUCCESSを出さない。修正CLIの実モデル6原frameもBGR/元PTSが6/6一致。Python全体 **3,106件PASS/0skip**（988.076秒、code `39c97950…`）、最終変更を含む映像全体 **614件PASS/0skip**（76.537秒、CLI13件・pipeline33件を含む）。全体3,106は後続の変更を含む最新GitHub HEAD全体の検証と読み替えない。原本・重み・途中失敗・モデル出力・別採点を私有保存し、Gitへ追加しない。

**未完成:** 6艇の継続識別、船体と背景の確実な区別、遮蔽後の再同定、同時6艇と別レースでの実証、ターン/出足/行き足/伸びの実測・予想改善。本追加の出力は `identity_validated=false/model_eligible=false` のままで、未検証の予想確率や回収率へ変換していない。実機Safari・4競技長期運転の合否もこの追加テスト数から認定しない。

**外部条件・保全:** 最後に確認した当日三国の正規playerは11/7 09:48:10.456 JSTに403/P01002。現在映像の許可待ちは未解消で、拒否済みcontentの再要求・別経路取得・問い合わせ送信はしていない。現在レースの正規映像と取得/保存/分析の許可確認、独立した正解による検証が必要。保護checkoutは `ef818e51…`、起点予想DB SHAは `c40bead0…` のまま、既存2プロセスは継続。取得総数・総GET・総稼働時間の停止上限を本追加で設けていない。新PR/Issue/workflow/外部schedule/サービス/予想モデル系統/追加課金/環境再公開なし。main統合・一般公開・実投票・本番切替も行っていない。

[実装・実測・実行方法](BOAT_VIDEO_MARKER_IDENTITY_20261107.md)／[source版・集計・検証SHA](evidence/boat-video-marker-identity-20261107.json)。全体完成は未達として維持する。

---

<!-- RACEAI_AUTOMATION_20261107_1332_RECOVERY_SUCCESS_FROZEN_AUDIT_UNVERIFIED -->
# 2026-11-07 13:32 JST｜原本復元後の既存公式run成功。第1巡を実ZIP照合、28仮想シナリオは事前receipt未立証

**GitHub実API確認:** Draft PR #71、branch `feat/four-sport-forecast-audit-view-20261022`、workflow `405276784`。監査前の現HEAD `1bafe16e8ff34d38c58778b5a02e4c189c0ef12f`。source run `42336097863`（起動HEAD `013c59c3f41209993bfba1f4b2b93791deba3d6c`）は2026-11-07 13:30:41 JST `completed/success`。先行失敗 `42330631694` の `VAULT_REFERENCE_KIND_INVALID` 後、今回の現runは初回P0原本再利用step18とP0モデル実行step20〜24をsuccessで通過した。先行失敗runをrerunせず、P0初回原本を再生成しなかった。旧エラーが全入力・全runで解消した証明ではない。

**巡回と独立検証の境界:** 全artifact一覧にある現runの正式 `race-existing-cycle-42336097863`（接尾辞なし、**第1巡**）の実GitHub ZIP `13560407497` は、ローカル再SHA256 `2ea1f784579db5797127db32a42dd84ece69ade421ee353e4851c480e8ce85ed` がAPI digestと一致し、ZIP構造正常。中身は `private-original.enc`、鍵なしで `status.json/forecasts.csv/automatic_learning/coverage_audit/learned_shadow_comparison` の検証は不能。独立再取得したsource control ZIP `13559864971` はSHA `0bf5746512cd7c516c4439c6435e551aed64874147623216f222f020311b824a` 一致、JSONは `completed_round=1, requests_used=45, stop_reason=ROUND_SOURCE_BUDGET_EXHAUSTED`。GitHubでround02〜24のstepがsuccessでも、その番号の巡回artifactは存在しないため24巡完成とは認定しない。公式GET 240超過は本runの記録上なし。保存された新P1予想のモデル別件数、公式通常結果の追加採点、学習係数、未来比較、収支は復号していないため**不明**。

**前向き試算の限定的進展:** `boat-prospective-evaluation-42336097863-r1` の実ZIP `13560632416` を独立再取得、実SHA `6d649b2dcf57021686a9a778229c6156fe1214ae2898140a029a79fa7045c75c` がAPI digestと一致。内包JSONの `frozen_settlement` は登録28シナリオ全件 `SETTLED`、公開事前計画内の `plan_sha256=9f9176a2eb0638436fbc138d20174b4dedab4a0eab7ceea0220a474243baec05` と文字列一致。だが `independent_pre_cutoff_receipt_verified=false`、`prospective_allocation_verified=false`、`accuracy_improvement_proven=false`、`actual_purchases=false`。28ケースは**代替仮想条件**であり、合算購入・前向き改善・正式確定収支とは扱わない。表示ベース `result_states=final41/missing88/unsupported3` は同様に独立公式原本の再照合を今回完了しておらず、正式採点件数に加算しない。

**起動・vault安全HOLD:** 監査時に同workflowの実行中・待機中 `0` 件。ただし count-only `state/boat-source-control/v1/latest.json` は以前の**失敗run42330631694**を指したまま（本runへの更新未確認）。現runの source-control ZIP は正しいが、owner鍵のHMAC/暗号vault原本まで本監査で独立認証したことにはならない。このstale controlを正常・0件に置き換えず、次の公式sourceトリガーは予約しない。保存/表示専用jobも根本未修正の `ALL_MODEL_CLI_OPERATION_FAILED` を持つため無根拠にrerunしない。4xx/429/真正性停止の回避、旧ref fallback、初期化、別認証は無し。既存の安全制限・concurrency/頻度・他ジョブ・暗号原本・本番モデルには手を加えない。

**未完成の区分:** 原本復元stepと第1巡ZIP/カウンター実バイト検証のみ今回新たに確認。P1/結果/自動係数学習/LEARNED_SHADOWの未来前向き優位性、28条件の物理的事前証明、全4競技16系統、全原本期限なし保管・所有者本番日別表示は未認定。新タスク・新PR・別workflow・クラウド・追加課金・main統合・公開・実投票・本番自動採用なし。

---
<!-- RACEAI_AUTOMATION_20261107_1228_RECOVERY_FAILED_SOURCE_HOLD -->
# 2026-11-07 12:28 JST｜既存表示の暗号履歴が第13世代へ進展。ただしsource復元と表示P0処理は失敗、追加起動HOLD

**実GitHub監査:** 既存Draft PR #71 / `feat/four-sport-forecast-audit-view-20261022`。監査前のPR HEADは `911376d7c070b77ffb0f445c9f6545aec5012fa9`。対象workflow405276784の直近対象5 run（42332035282/42330631694/42329064283/42323582642/42322126540）はすべてcompleted/failure。直近表示run42332035282は2026-11-07 12:21:26 JST終了・failure、公式予想jobはskipped。表示の「当日P0既存系統実行」stepで `ALL_MODEL_PATH_REJECTED / ALL_MODEL_CLI_OPERATION_FAILED` が出た。ラッパーは実例外を隠すため、根本例外は未特定。このrunの新規予想・結果artifactは0件であり、P0実行成功や全5項目完成とは言わない。

**失敗直前までの保存進展:** 当該表示ログには独立の過去結果照合・暗号保存作業の記録がある。保存済みモデルの追加受領342行（P1、4 run参照）、結果観測追加29件、通常確定13レース・結果待ち2レース（いずれも表示回復処理内の集計）を記録。基準5モデルの公式採点への新規加算は不可。別保全工程は128原本のbounded追加と25新規モデル原本の保全をそれぞれ報告するが、`full_current_view_readback_verified=false` と残り59対象artifact・6後回しrunがあり全原本の完成ではない。公開Git上に存在する暗号履歴commit `e743c3522fd97407dab28d8bcc3609712f86dd07` は第13世代・2日付更新を示し、暗号化公開記録のcommit存在を別APIで確認。owner keyでの全履歴読戻し/モデル別正式精算成功とは認定しない。公式source GETは表示jobの回復処理0件。

**公式worker失敗と停止条件:** 直近source run42330631694は2026-11-07 11:52:45 JSTにcompleted/failure。`Reuse authenticated first original` で `VAULT_REFERENCE_KIND_INVALID`（`boat_private_original_vault.py` の署名済み索引参照kindチェック）により停止。原本欠落、原本の改変、認証拒否のいずれかと早合点せず、kind不整合の正確な対象原本と署名整合を調査するまで新sourceを起動しない。count-only latest controlはrun42330631694を示すが `run_conclusion=failure`、`completed_round=0`、`requests_used=0`。これは通常成功や予想0件の認定ではない。旧sourceの再実行/別認証迂回/新run/別保管refへのfallbackをしていない。

**最新確定原本の境界:** 最後に成功をAPIで確認した正式source run42318345435はcompleted/success、公開artifact全件に第9巡の予想ZIP・結果ZIP・継続ZIP・source controlがある。以前の監査記録では基準予想399行、通常採点126行と報告。今回APIのartifact登録digestは読み取ったが、暗号原本の新規復号・ZIP独立実バイトハッシュ・モデル別率/仮収支/28事前シナリオ精算の再算定は**未実施**。新回復の342行等を399件の正式基準予想へ合算しない。

**維持:** 当該監査では旧原本・係数・P0初回索引・結果revision・concurrency・取得GET上限・既存スケジュールを変更しない。待機runの有無は最新API第一ページで直近対象5件completedまで確認、全過去ページの完全列挙ではない。上記真正性停止のためトリガー変更・取消・rerunを見送り。別workflow/新PR/追加タスク・モデル・外部サービス・課金・main統合・公開・実投票・本番自動切替なし。全16系統/4競技、全レース、所有者用履歴、LEARNED_SHADOW未来優位性、5項目の完成は未達。

---

<!-- RACEAI_CONTINUOUS_VIDEO_IDENTITY_IMPLEMENTATION_20261107 -->
# 2026-11-07 JST｜連続映像の保存を実装・実動画1056フレーム一致。6艇の継続識別は未完成

**実装・検証済み:** 既存Draft PR71内に、正規の許可済みHLSを私有保存するCollector、再開可能なSQLite台帳、local-only MP4出力、既存intake接続、`--follow`自動巡回を実装した。総GET・区間数・巡回数・総稼働時間で打ち切らない。1応答の資源条件と120秒/256MiBの解析条件を区別し、解析対象外区間の保存後も後続取得を続ける。401/403・429/Retry-After待機を保持し、拒否回避・別variantへの切替・鍵取得はしない。既存の自動予想・動画intakeを停止/再起動していない。

**実動画での連続保存:** 新たに正規ページから取得したmassmatt「Vintage Boat Racing」（CC BY2.0、過去の外国モーターボート映像、35.2352秒/34,405,081B）をstreamcopyし、localhostで実時間の段階公開を行った。最終コードSHA `65d28859…` で25GET全200、12segmentを各1回保存。2窓900+156=1056フレームすべてのBGR SHAと1055個のPTS間隔・窓境界が元映像と一致し、再出力も同一SHA。時計注入・再encode・静止画反復なし。raw PTSには一定offsetがあるため絶対時刻同一とはしない。これは実媒体を使ったSYNTHETIC_TESTのHTTP transport検証であり、現在の日本公式LIVE・現在レース・艇番識別成功の証拠ではない。

**艇番の原因修正と未達:** 数字候補を艇画像の上側という理由だけで除外していた条件1個を修正し、上下移動のRED→GREENを確認。固定された写真の自動検出艇画像では、AI開発参照と一致するdistinct番号領域が0→2。選択済み同一撮影者データであり、独立精度・人間正解とはしない。既存日本競艇動画は全775フレームを照合し、実97sample/679検出forward/962CRNN forwardを実行したが、時間をまたぐ艇番は0→0、有効位置も0、動画での改善は未実証（597.302秒、budget不完了4件/省略view22件）。6艇継続識別・ターン/出足/行き足/伸びの実評価・予想精度改善は完成していない。重み・語彙・閾値・本番モデルを変更せず、映像特徴を現在の本番予想へ適用していない。

**失敗修正・全体検証:** 独立レビューで確認した応答待機の途中終了、同URIの新sequence、SQLite部分保存、export復旧、directory fsync、初回variant固定、不完全受信、sliding PDT、partial stage残存、CLI SQLite例外を再現して修正。最終関連4module60件PASS、並行変更を取り込んだコードcommit `038ca2a…` のPython全体2,635件PASS（847.837秒）。実媒体66保存物のSHA/size/0600を別途再照合。 後続workerの変更を保持した6ef96d0時点でも今回の映像コードSHA不変・関連60件PASSを再確認（後続の無関係な変更全体を2,635件検証済みとは扱わない）。初回の参照checkout不足による失敗と実装途中の失敗ログも保全し、成功へ置き換えていない。

**外部条件・保全:** 11/7 09:48:10.456 JST、当日morning開催・4R発売中/10:05締切の根拠を公式portalで確認した新規の三国LIVEも、正規プレーヤーの自動初期化API1回で実HTTP403/P01002「この動画の視聴は許可されていません」。可視Play前に停止し、manual Play0・映像応答0・保存0B/0frame・再要求/別会場切替0、AUTHORIZATION_WAITを記録した。過去の拒否映像は再要求していない。現在映像の403は未解消で、原因の特定・正規アクセス確認が必要。問い合わせは引き続き未送信。単なるsource宣言を許諾/レース認証へ昇格しない。実機Safari、4競技の継続実運転と前向き精度改善も今回のtransport成功で完了扱いにしない。起点DB SHA `c40bead0…` と保護checkoutは不変、既存監視/動画intakeは稼働継続。新PR・Issue・workflow・外部schedule・予想モデル系統・追加課金・環境再公開・main統合・一般公開・実投票・本番切替なし。

[操作方法と出典](BOAT_VIDEO_CONTINUOUS_CAPTURE_20261107.md)／[集計・コードSHA・検証証拠](evidence/boat-video-continuous-identity-20261107.json)。全体の完成判定は未達のまま維持する。

---

<!-- RACEAI_AUTOMATION_20261107_0928_COMPLETED_18_AND_SINGLE_SUCCESSOR -->
# 2026-11-07 09:28 JST｜実worker第18巡までの正常保存と取得枠停止、現worker第5巡の原本照合、後続1件予約

**GitHub実確認:** 既存Draft PR #71 / workflow405276784 / branch `feat/four-sport-forecast-audit-view-20261022`。監査直前HEAD `74883f3291bdb4a71afa34fd511d532faf31c074`。official run `42289399740` は09:06:07 JSTにcompleted/success、全artifact一覧から確認できる正式最終巡回は**第18巡**（結果ZIP保存09:05:32 JST、round readbackログ09:05:38 JST）。ログには `ROUND_SAVED_AND_READBACK_VERIFIED`、累計`forecast_count=284`、`scored_forecasts=14`（モデル別行、14レースとは限らない）、`session_requests=199` がある。P0元索引264行を再生成せず、当該runでは20行分の予想増加。第19〜24巡は `SESSION_SOURCE_BUDGET_EXHAUSTED` で非稼働。240回超過なし、ただし停止条件の内部余裕枠・次runの実GET数まで完成保証しない。

**独立の原本読戻し:** run42289399740の第18巡P1予想artifact `13551060941`、結果artifact `13549429995`、継続artifact `13549854306`、count-only source control `13549734540` をGitHubから再取得。実ZIP SHA256が各API digestに一致、ZIP破損0。source-control.jsonは `completed_round=18`, `requests_used=199`, `stop_reason=SESSION_SOURCE_BUDGET_EXHAUSTED`、2026-11-07当日・元run HEADとの対応一致。内部は`private-original.enc`なので本監査実行環境で復号してstatus.json、forecasts.csv、automatic_learning、learned_shadow_comparison、coverage_auditや公式結果改訂履歴を再計算できていない。**14行を「的中14」と扱わず、最新モデル別的中率・回収率・仮収支は新たに認定しない。**

**現runの最終保存物と進行中を区分:** official run `42299260917` は09:28 JST時点でin_progress。全artifactから第5巡P1 ZIP `13551766772` と結果 ZIP `13551956350` を確認し、両実ZIPのAPI digestとSHA256一致/ZIP破損0。第6巡はP1保存が先行、結果/読戻し未完了なので第6巡を成功実績に含めない。初回P0 receipt `docs/evidence/2026-11-07/p0-first-receipt.json` は132レース・264予想、元原本SHAは不変。未完了runをcompletedと偽らない。

**後続起動の重複防止:** 追加起動直前に同workflow全run・現job・既存トリガーの現blob・concurrency設定を再取得し、現run正常、waiting/queued/pending 0、同時official writer 1、当日未来レース有りを確認。既存 `docs/evidence/boat-nationwide-pilot-trigger.txt` をblob SHA条件付きで1回だけ更新（commit `74883f3291bdb4a71afa34fd511d532faf31c074`）。直後APIで同じofficial群に後続run `42318345435` がpending、`42299260917` がin_progressと確認。これ以上pushしない。旧workerのcancel/rerunなし。240/45 GET、24巡/65分/180秒、最大3レース、締切210秒以上、4xx/429/不一致/日付の停止境界は変更なし。

**別系統の失敗:** saved-view run `42308698200` は事前評価計画スキーマ不一致で失敗（08:08の既存監査参照）。後の `42310259077` はsource復旧段で`UNRESOLVED_PREVIOUS_RUN`を出して失敗。公式worker継続中に保守的整合性検査を緩和せず、saved-view成果を正常結果へ昇格しない。saved-viewとofficialのconcurrencyグループ分岐は依然未達。新しい前向きLEARNED_SHADOW改善、全16系統/全4競技完全稼働、全履歴の永久私有保存、本番モデル切替は未実証。新タスク/PR/workflow/サービス/課金/実投票/main統合なし。

---
<!-- RACEAI_VIDEO_NO_CONTACT_ALTERNATIVES_20261107 -->
# 2026-11-07 JST｜問い合わせ以外の経路：許諾付き写真6原本を取得・実推論、公式計測値は公開口確認／現在値は未取得

**実施済み:** PLAYへの問い合わせ送信は見送り、連絡先の入力・送信0件。新しい別作者の桐生写真6原本（2010年撮影、CC BY2.0、12,794,659B）を正規の公開ページから取得し、106保存物のSHA/size/0600を独立再照合。モデル出力を見ない別担当がAI開発用参照8数字領域・可視艇領域11件を封印した。直接読めるクラスは2/3/4/5/6、1は未確定。人間の正解・独立した評価用データ・現在レース・動画として扱わない。

**モデルの実処理と失敗修正:** 初回は写真の画素数が既存入力条件を超え、検出前に失敗。失敗履歴を保全し、原本や条件を変えず解析用コピーを合わせて再実行した。保存済みの実推論は検出7回・CRNN39回。NanoDetは新写真1枚で候補0、既存YOLOXは6枚で候補5・AI参照との固定IoU.5点一致3。数字の生候補1件は参照UNKNOWNで、確認できた自動艇番一致0。手動の位置指定で大きな4を読めたことを自動識別成功へ読み替えず、モデル・重み・閾値の実運転切替なし。

**公式数値の経路:** 展示タイム/STと条件付き過去コース履歴は既存2モデルへ接続済み。一周・まわり足・独立直線の専用取込は未実装。戸田公式の掲載開始告知・計測図・公開数値XML導線を確認したが、公式選択コードに基づく11/7戸田1Rの1要求は404、実測0行/PENDING。時系列や日付を替えて埋めず、単位・厳密距離・公表時刻は未確認。新数値を予想へ投入していない。

**未完成:** 別の現在映像経路も2会場の公式案内で調べたが、芦屋は非開催、下関の正規Play先は同じBOATCAST系を呼ぶ構成で子プレーヤー未要求。今回の新しい連続映像0バイト・0フレーム。403の原因/解消、6艇追跡、映像の強さ評価、前向き精度改善は未達。写真を反復して追跡成功を作ったり、未掲載数値を実測値として表示したりしていない。

**保全:** リポジトリの変更は文書だけ。実運転コード・取得数等の設定・配信元待機・workflow/trigger・予想原本を変更せず、監視PID423218・動画取込PID271439の停止/再起動なし。起点DBのSHA256 `c40bead05533ace426188ea8a111b1e4a4a639283f576972ba276e14a3e8ff1a` は不変。写真・注釈・重みはGitへ追加せず、問い合わせ・課金・新PR/予想モデル系統・本番切替・main統合・一般公開なし。

[別経路の検証結果と出典](BOAT_VIDEO_ALTERNATIVE_INPUTS_20261107.md)／[取得・推論・失敗・証拠ハッシュ](evidence/boat-video-alternative-inputs-20261107.json)。

---

<!-- RACEAI_AUTOMATION_20261107_0808_SAVED_VIEW_SCHEMA_FAILURE -->
# 2026-11-07 08:08 JST｜saved-view事前登録検査のスキーマ不一致。公式予想workerには影響を加えず監査

**新しい実差分と原因:** workflow405276784の別系統 saved-view run `42308698200` は2026-11-07 07:59:26 JSTに`completed/failure`。当該jobの「Verify public prospective policy is still before its first outcome」が `AssertionError` で停止。checkoutの固定HEAD `a77ef3e5c34feef06fb3840c7ac1845ac8b2ae7d` の `prospective-evaluation-plan.json` 内の `schema=RACE_AI_PRE_OUTCOME_BUDGET_PLAN_COUNTS_V1` に対し、既存workflowは `RACE_AI_PROSPECTIVE_EVALUATION_REGISTRATION_V1` を要求している。スキーマ不一致は原本実ファイルと実jobログから確認済み。結果改訂・4xx/429・公式取得上限が原因とは認定しない。今回のsaved-view研究政策受領artifactは0件であり、未来評価の独立事前登録成功とは扱わない。時計や事前登録条件を事後的に変えたり、過去時刻の証明を作成しない。

**公式workerと保存の分離:** 同workflow official run `42289399740` は今回GitHub再取得時 `in_progress`、`Wait without source requests for the authenticated exhibition window` が進行中。現runのartifact0件。公式後続 `42299260917` は既に`pending`（artifact0件）。追加トリガー/cancel/rerunは実施しない。同時公式writerは1。saved-view失敗runのofficial jobはskippedのため、公式P1/通常結果を失敗と断定しない。

**前回から変化のない正式実績:** 最後の保存済み公式完了巡回はrun42259181853第14巡（03:06:24 JST）。予想/結果元ZIPのAPI登録digestと以前の独立SHA検証履歴を照合、今回は元ZIPの新規バイト取得・再SHAではない。P0観測相性132予想、P0 ST重視相性132予想、P1既存5系統0、通常採点0、学習版未来比較0。今回の的中率・仮想収支・回収率は未算定。全16系統、全4競技、前向き学習優位性、期限なし非公開全履歴保存、有限GET実停止は未完成。

**保全:** 既存workflows/モデル/係数/予想原本/公式結果/初回P0/評価方針を変更せず、この監査記録だけを既存Draft PR #71へ追記。他チャット記録も保持。事前政策の有効性に矛盾があるため、「コード変更なしの検証成功」とは報告しない。private ID・URL・認証情報・生データ掲載なし。

---

<!-- RACEAI_OFFICIAL_LIVE_ROOT_CAUSE_FOLLOWUP_20261107 -->
# 2026-11-07 JST｜403追加原因調査：追跡情報は回収できず、STREAKS提供元への照会を準備

**原因の特定は未達:** P01002/id163「この動画の視聴は許可されていません。」の具体的な発生条件は、追加確認した公式資料でも不明。STREAKSは映像・端末・利用者の権利等を制御できると説明しているが、BOATCASTで有効な規則やコード対応表は示していない。地域/IP・参照元・配信期間・契約等のどれかと推測で断定しない。

**追加調査済み:** 別の元ネットワーク記録・ブラウザ出力・SDK受信記録・記録コードを照合。旧福岡展示の403本文も既知の5項目だけで、現在LIVEの追跡ID・要求/応答ヘッダー等は回収できず。福岡のcurrent LIVE観測の別保存物1,848バイトはフォントの200応答であり映像ではない。環境のHTTPポリシーはunrestricted/enforcedだが、保持診断はnot_found/records=[]。ログ欠落を無認証・正常・許可済みとは扱わない。id163をリクエスト追跡IDとは認定しない。

**次の正規確認先を特定:** [PLAY公式問い合わせ](https://www.play.jp/contact)を200・通常ブラウザで確認。「PLAY CLOUD(STREAKS)」の問い合わせ項目と、担当者から連絡する旨の案内がある。BOATCASTの返信不可フォームとは別。画面上の必須項目は区分・所属名・名前・メール・電話で、個人情報取扱への同意が必要。個別の技術回答や視聴許可は保証されない。[照会本文](BOATCAST_OFFICIAL_LIVE_ACCESS_20261107.md)を作成したが、送信の明示指示・送信者情報は未取得。**入力0・送信0、回答待ちではない。**

**保全と検証:** 最新PR71 HEAD b19bc2bを調べ、実運転の既存checkoutとは別の文書用領域で記録。変更は文書のみで、実運転コード・取得数等の設定・配信元待機・workflow/trigger・原本への変更なし。監視PID423218と動画取込PID271439は存在を確認し、停止/再起動/手動dispatch/rerun/cancelなし。起点予想DBはSHA256 `c40bead05533ace426188ea8a111b1e4a4a639283f576972ba276e14a3e8ff1a` で不変。新しい一次資料の3引用は全文/切出しSHAを独立照合。JSON・文書リンク・公開内容を検査し、フォームは入力や送信をせず確認した。公式LIVEの取得成功・映像3項目の完成・精度改善は未認定。

[追加の原因調査・窓口・証拠ハッシュ](evidence/official-live-root-cause-followup-20261107.json)。

---

<!-- RACEAI_AUTOMATION_20261107_0645_SINGLE_SUCCESSOR_RESERVED -->
# 2026-11-07 06:45 JST｜実workerの展示待機を監査し、同じ公式concurrency群へ後続1件のみ予約

**差分:** 対象Draft PR #71ブランチの監査時HEAD `ccdbe9fd4cec1531228849d6a6db24191e87b9e9`、既存workflow `405276784`の全run一覧と現在のjob steps、初回P0索引、最新完了原本artifact一覧を実APIから読取。現在run `42289399740`（起動HEAD `ad220c84eb4ff86b9f00dbab4d6246c4d08190b2`）は`in_progress`、既存初回P0の認証復元・再利用成功後、`Wait without source requests for the authenticated exhibition window`が進行中。取得session開始・展示後P1生成・通常公式確定・自動学習・未来LEARNED_SHADOW比較は本runでまだ検証できない。本runのGitHub artifact一覧は0件。終了・安全停止・GET値・原本の新規読戻し成功を主張しない。

**後続1件の予約:** 実行直前にリストを再取得。実行中の同workflow workerは`42289399740`だけで、queued/pending/waitingは0件、現在の待機stepに失敗なし、当日未来レースが残る。既存トリガー`docs/evidence/boat-nationwide-pilot-trigger.txt`を**一度だけ**原blob SHAによる更新で追記。変更commit `b11b4fa54622e85c6a9fadbd561313b3f725adba`。GitHub APIを再取得し、新run `42299260917`が**pending**、現run `42289399740`は**in_progress**を確認。後続は同じofficial concurrency group `boat-nationwide-cutoff-20261103`に入る、`cancel-in-progress=false`。追加予約・cancel・rerunは0。実行中writerは1つ。特に4xx/429・原本不一致・上限・日付停止を解除しない。

**原本と採点を分離:** 当日の最新完了の正式巡回は、先行run `42259181853` の保存済み**第14巡**（2026-11-07 03:06:24 JST）。今回GitHub artifact APIで結果ZIP `13527208833` の登録digest `5c32aff739d718d0cde99e2f38c4e005b4fb34524986b514c94877e6dc7f8208`、展示後P1 ZIP `13527811422` の登録digest `83b6a3f8e92f1ef603576dad282a7fc62cf3f6a2475bb4fb2da6b67cb9590f5c` を確認。両実バイトと内包statusは先行監査で独立照合済みだが、**今回の新規実ZIPダウンロードによる再照合は実施していない**。初回P0の`p0-first-receipt.json`は132レース/264予想・元ZIP SHA `98abf598c8685bef240f03e135e900dce78b89057c80959b93934d601d58dd3d`、当初索引は変更なし。新runの未完了成果・別jobの研究展示用出力は基準5モデル実績に混ぜない。第14巡に基づく公式通常確定0・P1基準5系統0・日内モデル別収支/的中率/回収率未算定を維持。

**安全制約と残作業:** 現branchのworkflowに`240GET/総・45GET/巡・最大24巡・65分/取得session・180秒間隔・最大3レース/巡・締切210秒前`の既存境界があり、解除なし。実workerは展示待ちであり制限内での正常停止の証拠はまだない。現workflowには saved-view と official で`concurrency.group`分岐が残る。今回のofficial後続はofficialと同じグループだが、**workflow全ジョブが一群の条件は未達**。実worker運転中のworkflow変更なし。原本7日保持を永久私有DBとは呼ばず、無承認の本番モデル切替・実投票・main/公開・新PR/別workflow/新タスク/頻度変更/Cloudflare・Vercel/追加課金なし。新しい確定成績がないため利用者通知に足る予測精度差分はない。

---

<!-- RACEAI_ALL_MODEL_ACTIVE_ENTRANTS_20261107 -->
# 2026-11-07 JST｜出場艇・全会場出走表・モデル取込を接続。実workerは原本復元後の展示待機

**サイト反映:** 所有者の既存閲覧リンクに288レース・2,414件の保存済み予想を統合。11月7日は11会場132レースに各7系統のP0を表示し、選手名は実際の登録番号と公式番組原本に照合した1,728出場枠へ反映。追加5系統660件はActions42280037707で実行・暗号化保存・独立読戻し済み。これは既存の正式P0/P1基準採点へ研究分を上積みする意味ではない。11月6日の結果表示は確定144・中止12、11月7日の未来132レースは結果待ち。

**実装と確認:** 出場3〜6艇と実艇番に対応し、明示欠場だけを展示必須対象から除外。展示未公開は欠場扱いにしない。全24会場の実保存ページ26件で出走表の形式・同一性を確認し、履歴・特徴量・実学習済みモデル・同一展示入力からのモデル別実行を接続した。旧原本辞書・締切・保存時計は不変。変更コード59a3c44のViewer42287788057/AUTORACE42287788123はsuccess、通常Python全体2,447件、追加283件、4画面幅のブラウザ確認も通過。

**実workerの進展:** 起動HEAD ad220c84eb4ff86b9f00dbab4d6246c4d08190b2のrun42289399740/job128138553596は、登録済み初回P0の再利用と原本restoreを成功させ、`Wait without source requests for the authenticated exhibition window`へ到達。最初の締切08:35 JSTに対するT-15の08:20まで待機し、まだ新runのP1生成・公式結果・最終停止を実証した段階ではない。初回Bの再取得はskip、反復source session開始前。既存GitHub監視も同一runをRUNNINGとして採用したが、継続workerの起動には作業環境の監視が稼働し続ける必要がある。

**保存・制限・残条件:** 新規のP0/P1/結果/継続原本は既存所有者キーで暗号化し、ホスト監視は暗号を復号せず、実GitHub receiptと同じ暗号文に結びつく件数専用controlを検査する。240/45 GET、24巡/65分/180秒と既存物理handoffを維持し、拒否・真正性異常・未完了取引を解除しない。販売者P0選択モデルの実評価点は未取得で、当該戦略の選択条件を維持。展示後の実未来保存、当該runの停止、的中率改善は今後の実データで確認する。

[検証記録と実行リンク](evidence/2026-11-07/boat-all-model-connection-validation.md)。直下は05:35 JST時点の独立監査記録で、当時in_progressだったrestoreは上記のとおり成功へ進んだ。

---

<!-- RACEAI_AUTOMATION_20261107_0535_RESTORE_SUCCESS_AND_OFFICIAL_STARTED -->
# 2026-11-07 05:35 JST｜Actions内原本復元成功を実証。新しい正式workerは実行中、通常採点は未増加

**今回確認した差分:** 既存workflow405276784のsaved-view run42287779744は2026-11-07 05:26:42 JSTにcompleted/success。GitHub Actions jobログの`scripts/github_existing_cycle.py restore`は05:26:39 JSTに`ORIGINAL_REUSED_NO_REGENERATION`、実際に元P0の132レース/264予想の復元を正常終了した。同runの研究モデル`bootstrap-current`はcontexts=132だが**generated_forecasts=0**であり、P1展示後5モデル・公式結果の成功ではない。これまでの当日保存済み原本77件は04:03に独立SHA/CRC照合済み、旧失敗時のHTTPコードはいまだ不明。

**新しい本来のworker:** 別作業がこの確認直前に既存triggerを更新し、HEAD `ad220c84eb4ff86b9f00dbab4d6246c4d08190b2` でworkflow run42289399740を開始（05:33:46 JST）。official_national jobがin_progress、saved-view jobはskipped。05:35 JST時点の実ステップは`Check all earlier same-day receipts before first P0`成功、`Reuse authenticated first original`は**in_progress**。まだ新runのrestore完走、予想/結果/PDCA ZIP、GET実数、240回上限安全停止の新証拠なし。今回の自動化からtrigger追加/cancel/rerun/新PR/タスク変更は**0件**。同時に待機中の予想runも検出なし。

**最新の正式完了巡回は不変:** 新日run42259181853の保存済み第14巡（JST 03:06:24）、132レース、初回P0既存2系統各132予想、P1基準5系統0、通常採点0、学習版未来比較0。研究用暗号化saved-view artifactを正式予想や公式採点に加算しない。したがって的中率・収支・回収率は未算定。

**検出した運転上の差異:** 現workflowのconcurrency.groupがcommit接頭辞によりsaved-view用とofficial_national用の**2群を条件分岐**している。official_national内は`boat-nationwide-cutoff-20261103` / cancel-in-progress=falseだが、workflow全体での「同じgroup」は現状満たしていない。worker運転中にworkflow更新・追加起動を行わず、次回の安全な改修ゲートとして残す。既存有限上限240/45 GET、24巡/65分/180秒、原本不一致・4xx/429停止を緩和しない。

---

<!-- RACEAI_AUTOMATION_20261107_0403_ALL_CURRENT_DAY_ORIGINAL_ARCHIVES_INDEPENDENT_AUDIT -->
# 2026-11-07 04:03 JST｜新日保存済み全38巡のP1・結果原本を独立再取得して元ZIP照合（実worker再開は保留）

**実行証拠:** 既存Draft PR #71の対象枝・今回の監査前HEAD `70280d99fc908853c505e6a546d28a9288a67a32`。対象workflow405276784は新日run42249906279がcompleted/success、第2 run42259181853および後続run42264560643がcompleted/failure。同workflowの最新実行リストでin_progress/queued/pending/waiting=0。既存実行をrerun/cancelせず、失敗を迂回する新トリガーも作成していない。

**当日全38保存済み巡回の独立実バイト監査:** 最初のrun42249906279の24巡、次のrun42259181853の完了第14巡まで計38巡について、GitHub ActionsのP1元ZIP **38件** と結果・PDCA元ZIP **38件** をすべてGitHubから別々に再ダウンロード。初回P0元ZIP **1件** も別取得。計77件の各実バイトSHA256はGitHub artifact APIの登録digestと**77/77一致**、ZIP CRC異常0。38件の結果ZIPすべてについて、内包`current-p1-original.zip`が各独立P1 ZIPと一致、`first-p0-original.zip`が固定初回P0 ZIP SHA256 `98abf598c8685bef240f03e135e900dce78b89057c80959b93934d601d58dd3d` と一致。各結果内`status.json`のrun_id/round_noとcanonical report_sha256も38/38一致。初回P0の`forecasts.json` SHA256は`109be9efcd7d6744120b53e00c82473b1544983cfb1060f3fe22442c799f36af`、同日初回receiptと一致。既存予想原本を再生成/書換えしていない。

**継続原本の独立監査:** 成功した先行runの最終continuity artifact13525525010 ZIP SHA256 `e72ad2adceaf8093ea1c18b63f5223ddfbea30d8e817611825f3decf2928a7af`、失敗run42259181853のcontinuity artifact13528026736 SHA256 `2712e88754d23e7d37a735d1385a711bc09d655b4c6c4e1840ff383c685fd295`、次の失敗run42264560643のbootstrap source-control artifact13527094985 SHA256 `7a467aead18c05ced18e2d0d5517e9bf5eef049e5d9e3c5a60bf3473fb55ed01` はすべてGitHub API digestと一致、CRC異常0。それぞれ内包state_sha256 / session_sha256 / source_control_sha256をcanonical再計算して一致。先行成功runの最終GET205、後続で第14巡まで成功したrunのGET134、有限設定240・最大24巡。最終の `completed_round=14/prepared_round=15` でその先の第15巡はCLIダウンロード失敗、上限安全停止の実証ではない。

**正式な成績・網羅性:** 最新の正常に凍結された2026-11-07第14巡は`status.updated_at=2026-11-06T18:06:24.807205+00:00`（JST 03:06:24）。11会場132レース、P0観測相性132・ST重視132、P1既存5系統すべて0、通常確定・モデル別採点0、LEARNED_SHADOW0、未来同条件比較0。各モデルの的中率・仮想損益・回収率は未算定。後の失敗runの未完了巡回を上積みしない。異常・未確認結果をMISSにしない。

**安全上の未完了を明確化:** 今回は独立した外部監査環境で、当日保存済みの全P0/P1/結果・継続原本の**バイト整合**を確認した。一方、GitHub Actions実workerの`gh api .../zip`が失敗した**当時のHTTPコード**は旧ログに残っておらず、403/429等だった可能性を排除できない。この実行ではworker内のrestoreを再実行しておらず、GitHub Actionsトークンの現行権限や実際の復旧動作は未実証。原本が存在することだけを理由に新runをトリガーせず、4xx/429/真正性停止の迂回をしない。最初に必要なのは修正後コードで失敗HTTP分類とActions実権限の安全な確認・同一原本の有界restoreで、成功時にはじめて新しい未来のP1に進む。

**変更範囲:** 今回の追加は監査文書のみ。既存の予想/結果ZIP、保管場所、同時writer、workflow/concurrency、最大24巡・65分・180秒・240 GET/総・45 GET/巡・3レース・締切210秒の制限、タスク/頻度・既存5モデル式/買い目・研究モデル/係数・新PR/新workflow・main・公開・課金・Cloudflare/Vercel・実投票・本番自動昇格に変更なし。全16系統/4競技の前向き優位性は未完成。

---

<!-- RACEAI_ALL_EXISTING_MODEL_LEARNING_20261107 -->
# 2026-11-07 03:55 JST｜全16系統31競技枠の研究用学習を接続。実学習2系統・未来PDCAは未完了

登録済みの全16系統・31競技枠へ、各モデル本来の係数・式による学習、時系列holdout、暗号化候補の復元、同一入力の研究予想、native買い目単位のPDCAを実装した。合成248レコードで全31枠の学習6/検証2を確認。既存の基準式と省略時出力SHAは保持し、新しいモデル系統・本番採用・購入・新しい定期タスク・外部クラウドは追加していない。

**実データ:** 会場別履歴を当時の原本に含む8レースで観測系2つだけを再学習（各6/2）。残り29枠は必要な実native入力不足であり、全モデル実学習済みとはしない。各観測系の8係数中6個が更新、展示2特徴量は支持数0で基準維持。旧8レース実学習と係数・指標の一致を確認。新しい入力は独立締切前の暗号化artifactと、別に認証した公式正常結果が揃った場合だけ追加できる。未学習競技の入力専用保存は予想・損失を作らない。

**実証:** 実装HEAD `34608b4863a816247231ce4ef3e32752682b07b9` の[Viewer Actions42273374848](https://github.com/haji84/RACE-AI/actions/runs/42273374848)と[AUTORACE Actions42273375048](https://github.com/haji84/RACE-AI/actions/runs/42273375048)はsuccess。ローカル全体2,208件失敗0（112skip）、追加10件とNode119件成功。実Actions artifact13531437402の所有者キー復号、元の実学習係数/holdout一致、既存Git ref保存元 `105e091816a25eaeb3798f0b6aaba6aa535ad2b2` から独立復元を確認。training SHA `138780934da999f7cc25ffb4de7e37f5c340c47bd5544e14398a2fe29cf2b4dd` を既存context/保持ポインターに固定し、実runtimeで全会場gridとともに復元した。詳細は[実装報告](ALL_EXISTING_MODEL_LEARNING_20261107.md)・[公開可能な件数証拠](evidence/2026-11-07/all-existing-model-learning-counts.json)。

**運転・残条件:** 直下の別監査で記録された既存workerの原本ZIP復元失敗を迂回・再生成しない。同時更新の安全なGitHub読取分類/限定再試行修正も取り込んだ。新workerの起動や再実行は今回0。学習済み候補での実未来P1、その独立締切前保存、確定結果との前向きPDCA、非BOATの実コホートと認証済み出典は未達。コード・合成試験・実2系統学習・未来レース・本番成功を混同しない。

---

<!-- RACEAI_AUTOMATION_20261107_0351_ARTIFACT_GH_FAILURE_REVIEW -->
# 2026-11-07 03:51 JST｜後続2 run のGitHub元ZIP取得失敗を検出、原本保全と安全な失敗分類を実装

**現在の運転状態:** 監査直前のPR #71ブランチHEAD `4144fe706dd6ce82faee411e5bc0fccd7ace7896`。対象workflow405276784の最新ボートrun 42264560643 は2026-11-07 03:13:01 JSTに `completed/failure`。その先行run 42259181853 も2026-11-07 03:09:25 JSTに `completed/failure`。最新40件のrepository runから同workflowの `in_progress/queued/pending/waiting` は0件、実workerなし。今回、失敗runのrerun/cancel・新トリガーは0。エラー原因が未確定で全原本のrestoreを完走できていないため、新runで迂回・再開しない。

**1件目の正確な失敗点:** run42259181853の第14巡までは完了予想/結果ZIPとも存在。第15巡 `scripts/github_existing_cycle.py supplement()`→`original()`→GitHub artifact13520355202/zipのCLIダウンロードが終了コード1となり失敗。tracebackで `subprocess.CalledProcessError` を確認。`gh` は stderr を捕捉しても記録しない旧実装のため、**HTTP 4xx/429/5xx/ネットワーク要因のいずれか現時点では分類不能**。原本改竄や公式GET上限到達が原因だと断定しない。後継run42264560643は独立再生の `restore()`→`cycle_recovery.recover()`におけるGitHub artifact13521606570/zipのCLI終了コード1で、予想ステップ開始前に失敗。前runのfailedを正常完走とせず、後継runも完走としない。

**今回の独立の元バイト確認:** GitHub公式artifact APIで13520355202（初回P0元ZIP SHA256 `98abf598c8685bef240f03e135e900dce78b89057c80959b93934d601d58dd3d`）、13521606570（既存P1元ZIP `5b4bf7797969523a0d671e55e8a208dc5bdb2e466ddd89c73bc1414c47daacd8`）を個別再取得。実バイトSHAは各登録digestと一致し、ZIP CRC異常なし。初回P0内 `forecasts.json` SHA=`109be9efcd7d6744120b53e00c82473b1544983cfb1060f3fe22442c799f36af` は2026-11-07初回索引と一致。**2件のartifactが現在読めることは実証したが、失敗run中のHTTP応答の正体・全履歴の完全な復元には代えない**。

**最新完了巡回のみの独立監査:** run42259181853の第14巡結果ZIP13527208833 SHA256 `5c32aff739d718d0cde99e2f38c4e005b4fb34524986b514c94877e6dc7f8208`、P1 ZIP13527811422 SHA256 `83b6a3f8e92f1ef603576dad282a7fc62cf3f6a2475bb4fb2da6b67cb9590f5c`、失敗後に保存された継続ZIP13528026736 SHA256 `2712e88754d23e7d37a735d1385a711bc09d655b4c6c4e1840ff383c685fd295` を独立再取得。3件ともAPI digest一致、CRC異常0。第14巡結果の内包P0/P1はそれぞれ独立ZIPと完全一致。`status.json` は `round_no=14`、`updated_at=2026-11-06T18:06:24.807205+00:00`（03:06:24 JST）、canonical report SHA再計算一致。継続 `repeat-session.json` のSHAも再計算一致し、`requests_used=134`、`source_limit=240`、`max_rounds=24`、`completed_round=14/prepared_round=15`、`halted_reason=null`。**安全上限240以内の正常な停止実証ではなく、14巡後の異常終了**。失敗した第15巡を結果済みに加算しない。

**2026-11-07基準モデルと学習:** ボート11会場132R、P0観測相性132保存/採点0/保留132、P0 ST重視相性132保存/採点0/保留132。P1既存5モデルすべて保存0、通常公式確定0、学習train0/validation0、LEARNED_SHADOW予想0/paired比較0。学習版の改善証明なし。的中率・仮想収支・回収率はモデル別に**未算定**とし、0%や回収率0%とは扱わない。`coverage_audit`は対象132/未来132/締切済0、全16系統の成功ではない。

**既存PR #71内の最小安全修正:** `scripts/github_existing_cycle.py`のGitHub artifact読取を修正。成功時の元bytesは無改変で返す。CLI stderrを公開せず、明示HTTP 4xx/429・原因分類不能は**即時停止**。明示HTTP 5xxまたはCLIのtransport timeoutだけ合計最大3回の有界再試行、なお失敗なら停止。公式データへの取得上限・真正性検証・結果改訂・既存モデルは変更なし。既存 `tests/test_first_p0_bootstrap.py` に4xx/429/不明時の再試行なし、5xx/timeoutの有界再試行と最終停止を検証する2試験を追加。保存されたsource bundleで関連unittest15件PASS。コードcommit `86b34fe01bcf9409263e6d9339a0f756792c72df`、試験commit `4144fe706dd6ce82faee411e5bc0fccd7ace7896`。exact-HEAD AUTORACE CI `42274260873` はsuccess、Viewer CI `42274261069` は03:50時点でpending。これらは修正後の実ボートworkerの復旧実証ではない。

**残条件と保全:** 直近の失敗2件から安全に復旧するには、同日全runの予想・結果・継続原本を改めて復元照合し、最初に失敗したGitHub ZIP取得のHTTP区分と現在の実権限を確認したうえで、新たな正常runの独立原本読戻しを完走する必要がある。02:46時点に本人専用Driveへ保全済みの当日4原本は今回変更せず、新規Drive保存0件。Driveの個人情報や私有URL/IDは公開記録に載せない。新PR/新workflow/毎時タスク変更/モデル追加/係数の無検証採用/Cloudflare・Vercel/追加課金/main/一般公開/実投票/他タスク変更なし。

---

<!-- RACEAI_AUTOMATION_20261107_0246_FINITE_DRIVE4 -->
# 2026-11-07 02:46 JST｜有限上限を読み込んだ実Workerで第7巡まで監査、初回P0＋最終3ZIPを非公開Driveへ4件保全・独立読戻し成功

**今回の重要な差分:** 従来 `BLOCKED_FILE_REFERENCE` により失敗していた本人専用Driveへの保全を、正規のLibrary/Google Drive create-only upload経路（元GitHub artifactの正確な `source_file_ref`）で初めて当日の4原本について完走した。指定保存先の所有者が現在の接続本人と一致、フォルダ `shared=false`・所有者単独権限を先に独立確認。対象フォルダ内に2026-11-07/run42249906279の同名ZIPが0件であることをLibrary一覧とDrive検索で確認し、新規4件を追加した。保存後に4件をDriveから独立再取得して実SHA256・CRCを確認し、4件ともGitHub元ZIP/API digestと完全一致、CRC異常0。さらに4件それぞれの保存先親フォルダ一致、個別 `shared=false`、ownerのみの権限とサイズを確認した。公開GitHubにはプライベートDriveのフォルダ/ファイルID・URL・個人情報・生ZIPを記載しない。

| 2026-11-07に新規保全した元ZIP | 元GitHub artifact | 実SHA256 = Drive読戻しSHA256 | サイズ |
|---|---:|---|---:|
| 新日初回P0（絶対非再生成） | 13520355202 | `98abf598c8685bef240f03e135e900dce78b89057c80959b93934d601d58dd3d` | 748,467B |
| 前完了run第24巡 P1 | 13524672657 | `7828e856a68e33c4f461879a6feefd52f616403eb43c55abffb2378136790f77` | 2,806B |
| 前完了run第24巡 公式結果・PDCA | 13524522979 | `98c60aa1f413668fe0352bb65cfd9556ec23018286e69c583e245b37d08387b5` | 771,569B |
| 前完了run第24巡 継続状態 | 13525525010 | `e72ad2adceaf8093ea1c18b63f5223ddfbea30d8e817611825f3decf2928a7af` | 1,461,114B |

**新しい有限上限の実Worker（重大な前進、ただし停止未実証）:** workflow405276784の前run42249906279は 2026-11-07 02:23 JSTにcompleted/success、最終第24巡の継続ZIPでGET205回・readback receipts24件。旧固定HEAD `8dd88b5...` の `source_limit/max_rounds/stop_at=None` であり、205<240という偶然を『240上限の実証』にはしない。現在run42259181853は固定HEAD `b0f94a2b4440fc4f7b71e3ae6f84b9f2bd8535ec` で **in_progress**。結果第7巡 artifact13526836309と独立P1 artifact13525787880を別取得し、結果ZIP SHA256=`4e1e912daa422aa3ba06e73daf546e74055fb8a4eaaced02eb771b5186fa69e3`、P1 ZIP SHA256=`6de4f63f8400362c7a488eefb1691fd1b9936575b740e2aae93306fcca0ecd35`。各実バイトはAPI digest一致、CRC異常0。結果内P1 ZIPは独立P1と一致、内包P0は初回原本SHAと一致。内包statusの `round_no=7`、`updated_at=2026-11-06T17:45:22.056664+00:00`（02:45:22 JST）、canonical report_sha256再計算一致。内包sessionの `completed_round=6/prepared_round=7`は第7巡readback**前**の値であり、第7巡継続receipt完了とは区別する。

**現在runの境界:** 第7巡保存session `requests_used=67`（forecast67）、`round_started_requests=54`ゆえこの巡の取得13回で、1巡45回以内。`source_limit=240/max_rounds=24/stop_at=2026-11-07 03:32:03 JST` が実セッションに存在し、旧runのNone既定から有限設定に移行したことを原本で初めて確認。`halted_reason=None`、現実行は進行中。**240GET以内・24巡/65分以内での実停止と終了後の継続ZIP独立読戻しは未達**。コードの既定値は240/45/24/3900秒・180秒のまま、4xx/429/日付/原本不一致を回避しない。

**後続1件の安全な先行予約:** 照合時点で現在run42259181853がin_progress、別worker queued/pending/waiting=0、未来132R、停止原因なし、既存workflowは同concurrency group/cancel-in-progress=falseと確認。既存trigger.txtに一行だけ追加するcommit `d777681e5f83dfb8e74f246b6b8c05d86ea20d82` で同workflowの後続run42264560643を1件作成し、API上 `pending` を確認。現在runはキャンセル・rerunしない、同時writerなし。後続が既に1件あるため追加pushは禁止。先行予約は現在runの正常停止を回避する許可ではなく、GitHub待機/起動遅延の空白は残る。

**モデル別成績と網羅性:** 2026-11-07の台帳はボート11会場132レース。保存P0は観測相性132とST重視相性132、合計264行。展示後P1の基準5モデルはいずれも保存0、通常確定・採点0、公式結果revision0、日内未確定132Rで、モデル別の的中率/収支/回収率は**未算定**（0%/0円と記載しない）。`coverage_audit`では未来132/締切済0/P1五系統完備0。`automatic_learning=INSUFFICIENT_VERIFIED_RACES`、TRAIN0/VALIDATION0、LEARNED_SHADOW予想0/同条件比較0。登録16系統の全予想成功ではない。external_research_summaryはNO_AUDITED_IMPORT_MANIFEST。P0初回索引 `docs/evidence/2026-11-07/p0-first-receipt.json`（JSON SHA、GitHub元ZIP SHA、保存時刻）と当日の4原本を突合し、旧予想再生成/上書きなし。

**保留条件:** 今回のDrive4件は真に保存・読戻しできたが、これを全日・全run・全競技の無期限私有保存完成とは呼ばない。現worker停止実証、最初の展示後5モデル×未来レースの締切前凍結、結果改訂別保存、モデル別の回収率PDCAと前向き学習優位性は未完成。新タスク/新PR/別workflow/頻度・既存5基準式/買い目/係数・main/一般公開/追加課金・Cloudflare/Vercel・実投票・本番自動切替は変更していない。今回GitHubで変更したのは既存triggerの予約1回と本監査文書のみ。

---

<!-- RACEAI_AUTOMATION_20261107_0155_CYCLE14_NO_NEW_SCORE -->
# 2026-11-07 01:55 JST｜新日第14巡原本再検証。予想/採点の実績差分なし

**独立照合した現在値:** PR #71の対象枝を再取得し、記録直前HEAD `43ae65a93c6a25666d3c3de495eab3498353321a`。対象workflow405276784の実run42249906279は固定旧HEAD `8dd88b5f6b75ec38e425fe9f685aab719872cdbb`でin_progress。リポジトリ直近100 runで別の予想worker queued/pending/waitingは0。追加run42253504820はsaved-view表示専用job completed/successで、official_national jobはskipped。別writerが動いたことを意味しない。実行中runはキャンセルしない。

**全artifact一覧から最新完了巡回を判定:** 2026-11-07 01:55 JST確認時、結果ZIPと予想ZIPがそろっている第14巡が最新。第15巡は予想ZIPのみ存在し結果ZIPが未保存のため、予想数・採点数へ未完了分を加算しない。第14巡結果 artifact `13523515299` は実ZIP SHA256=`02d5d87db860dce706df9fb545aa131270e8c3160711aade4bc1944224251daa`、予想artifact `13521734995` は実ZIP SHA256=`36ddc7f8cdebcef1eb03b4d80481b1bd3f1bc96044afd94b762ed1216e56a4f2`。両者GitHub API digest一致・ZIP CRC異常なし。結果ZIP内`current-p1-original.zip`と別取得P1原本はSHA一致、`first-p0-original.zip`のSHA=`98abf598c8685bef240f03e135e900dce78b89057c80959b93934d601d58dd3d`は初回P0元ZIP/初回receiptと一致。`status.json`の`round_no=14`、`updated_at=2026-11-06T16:52:44.372389+00:00`、`report_sha256`はcanonical再計算一致。sessionは第14巡readback前`completed_round=13/prepared_round=14`であり、継続第14巡完了と混同しない。

**モデル別成績（新日）:** 台帳ボート11会場132R、通常確定0R、全132Rが未来。P0観測相性132予想行・通常採点0/保留132、P0 ST重視相性132行・通常採点0/保留132。P1のA/B/C-lite/観測相性/ST重視相性は各0行で、まだ締切210秒前の展示後予想窓に入っていない。的中率・回収率・仮損益は両P0モデルとも**未算定**（0%や損益0円を成績とは扱わない）。第6巡以前から予想/採点/収支の実績差分は0。次の最初の締切は08:35 JSTで、national.json次回候補照会は08:20 JST。予想不足を分母から除外せず、未公表展示を取得可能だったと決めつけない。

**学習・結果・その他モデル:** 通常確定結果0R、公式結果revision0、`automatic_learning.state=INSUFFICIENT_VERIFIED_RACES`、TRAIN0/VALIDATION0。`trained_observed_models.json`の更新係数0、LEARNED_SHADOW保存0、同条件前向き比較0。model_coverageは登録16系統を列挙するが実予想接続は当日P0の2系統だけ。出走表台帳132Rを全16モデル予想成功へ読み替えない。external_researchは`NO_AUDITED_IMPORT_MANIFEST`。新しい予想と公式結果が揃っていないので精度改善の報告なし。

**起動/上限の監査:** 第14巡結果ZIP内`bounded_repeat_session.requests_used=111`、内訳forecast111、`source_limit=None/max_rounds=None/stop_at=None`、`halted_reason=None`。前回第6巡の55回から56回増加。まだ240超過ではないが、制限を守って停止した実証では**ない**。現在のPR枝`race_ai/repeated_cycle.py`ではSOURCE_LIMIT=240、ROUND_SOURCE_LIMIT=45、MAX_ROUNDS=24、MAX_SECONDS=65*60、POLL_SECONDS=180を実読取し、現在HEADの既存Viewer/AUTORACE CIはともにcompleted/success。しかしこの修正は旧固定SHAの進行中workerには反映されない。`.github/workflows/boat-nationwide-ab-one-shot.yml`は予想jobの既存concurrency=`boat-nationwide-cutoff-20261103`、`cancel-in-progress=false`を保持。4xx/429/真正性不一致による停止回避をせず、旧無上限workerに後続を追加予約しない。現在runに対しcancel/rerunなし。

**本人専用保存の確認:** この実行で接続Driveアカウントの本人owner一致、指定フォルダ`shared=false`・フォルダ種別を再確認。対象の新日run/P0ファイル名をフォルダ内に絞って検索し、同名候補なし。新日初回P0元ZIPをDriveへそのまま追加保存する試行は、GitHub artifactのコネクタ参照が`BLOCKED_FILE_REFERENCE`で拒否され、新規保存0件・独立読戻し未成立。GitHub artifactの7日保持を期限なしの非公開保全とは呼ばず、私有フォルダID・URL・認証値をこの公開文書に載せない。

**今回の操作:** 既存PR71の本監査追記のみ。元ZIPと過去予想・公式結果revision・基準モデル式/重み/買い目・係数・既存workflow/タスク/実行頻度/他タスク・本番モデル選択・課金/Cloudflare/Vercel・main統合・一般公開・実投票は一切変更しない。次の合格条件は、有限上限が固定されたHEADで新たに開始する正常workerによる実GET<=240、1巡GET<=45、上限到達時の安全停止、予想/結果/継続の独立原本読戻し、未来レースのP1と通常結果の前向き照合。

---

<!-- RACEAI_AUTOMATION_20261107_0131_CYCLE06_AND_DRIVE_CHECK -->
# 2026-11-07 01:31 JST｜第6巡独立読戻し・所有者専用Driveを再確認

既存workflow405276784/run42249906279の保存済み結果から第6巡を独立取得。結果artifact13521411929の実ZIP/API digest SHA256=`7802d86d12df12184956f04aeddcd3dd9678336cdf84393937592b3e43f93971`、予想artifact13521606570は`5b4bf7797969523a0d671e55e8a208dc5bdb2e466ddd89c73bc1414c47daacd8`、どちらもCRC異常0。結果内P1元ZIPと独立P1 ZIPは一致。初回P0元ZIPは `98abf598c8685bef240f03e135e900dce78b89057c80959b93934d601d58dd3d` で初回receiptと一致。status.round_no=6、updated_at=2026-11-06T16:28:47.070454+00:00（JST 01:28:47）、report_sha256はcanonical JSONから再計算して一致。内包sessionは第6巡readback前のcompleted_round=5/prepared_round=6で区別。

新日台帳132R、朝版P0の観測相性132件・ST重視相性132件、通常採点0・結果保留各132、展示後P1の5系統0、学習版0。結果公表前のため、各モデルの的中率・仮想損益・回収率は未算定（0%や0円の確定実績とはしない）。今回第5巡から的中・学習・P1件数の差分なし。継続session.requests_used=55、固定旧workerのsource_limit/max_rounds/stop_at=None。改修後枝の240/45/24/65分が、この進行中workerに適用されたという証拠ではない。

指定Driveフォルダをこの実行で再照合し、接続アカウントのowner権限が一致、共有状態`shared=false`、フォルダ自体の種別を確認。新日P0 ZIPの同名ファイルはDriveの対象フォルダ検索では0件。GitHubの元artifact参照をDriveへ無改変送信する試行は、コネクタが正規の `file_uri` として受け付けず失敗。追加保存0件、Driveからの独立読戻しは未成立。公開GitHubには私有Drive URL/ID、個人アカウント情報を書かない。別の転送方法でこの制限を回避していない。

既存PR71の有限上限のコード復元コミットを保持。復元4ファイルを含む既存AUTORACE CI（HEAD574e69c）は `completed/success`。追加監査文書commit422ca5b時点のAUTORACEは`completed/success`、Viewerは確認時`pending`。新しい実workerでのGET<=240を安全実証したと主張しない。実行中runはキャンセルせず、後継予約もせず、既存workflow/スケジュール/モデル/PR/本番切替等は変更なし。

---

<!-- RACEAI_AUTOMATION_20261107_0127_FIRST_P0_AND_FINITE_BOUNDS -->
# 2026-11-07 01:27 JST｜新日初回P0凍結・第5巡監査、数値制限の再復元

**対象:** 既存Draft PR #71、workflow405276784、同一PR枝。01:27 JSTに最新実行一覧/同run artifactを再取得。進行中run42249906279は固定旧SHA `8dd88b5f6b75ec38e425fe9f685aab719872cdbb`（11/7 01:10 JST頃起動）で `in_progress`。同workflowの別 queued/pending/waiting は取得した最新60 runで0。現在のworkerに後からのGitHub修正は適用されない。run cancel/rerun、追加trigger=0、既存workflow/タスクのスケジュール変更=0。

**新日原本の真正性:** `docs/evidence/2026-11-07/p0-first-receipt.json`（初回run42249906279、元P0 artifact13520355202、2026-11-07 01:11:14 JST保存）を確認。元ZIPを独立再取得し実SHA256=`98abf598c8685bef240f03e135e900dce78b89057c80959b93934d601d58dd3d`、GitHub API digest一致、ZIP CRC異常0。内包 `forecasts.json`のSHA256=`109be9efcd7d6744120b53e00c82473b1544983cfb1060f3fe22442c799f36af`、初回索引と一致。P0は132レース×既存2系統＝264モデル予想行で、初回原本を再生成していない。

**完了巡回のみの監査:** 全artifact一覧中の結果第5巡artifact13521675958（2026-11-07 01:25:41 JST保存）の実ZIP SHA256=`3bb174f9812866ed7380ab293fb731957fb5d12e416317f2f79dbe87c9425d10`、別保存P1 ZIP artifact13521725869実SHA256=`a12dd1e95d51aa7a80bf4c72e335818aa37f8d4f9fe6896a0750d17f2a355b77`。API digest完全一致、双方ZIP CRC異常0。結果ZIP内の `current-p1-original.zip` と独立P1 ZIPはバイトSHA一致、`first-p0-original.zip` は初回元ZIPとSHA一致。内包`status.json`の`round_no=5`、`updated_at=2026-11-06T16:25:39.088346+00:00`、canonical `report_sha256`一致。継続sessionはreadback前 `completed_round=4/prepared_round=5`、5巡readback完了とは混同しない。

**新日モデル別成績:** P0観測相性は保存132、通常採点0、保留132、的中率・収支・回収率は未算定（投資0円は「実績0%」の意味ではない）。P0 ST重視相性も保存132、採点0、保留132。P1のA/B/C-lite/観測相性/ST重視相性は各保存0、採点0で、締切前展示の予想条件未到来。13?会場と断定せず対象は実台帳132R。最新結果観測revision0、学習`INSUFFICIENT_VERIFIED_RACES`、TRAIN/VALIDATION0、LEARNED_SHADOW0、未来同条件比較0。全132Rは現時点で未来、過去11/6の収支を新日へ持ち込まない。

**重大な設定衝突の是正:** 監査時の最新枝 `race_ai/repeated_cycle.py`がMAX_ROUNDS/SOURCE_LIMIT/MAX_SECONDS/ROUND_SOURCE_LIMIT=`None`へ再変更されていた。これは本自動化で明示された24巡/240GET/65分/45GET上限と矛盾。既存PR71の同一branch上で、以前の安全検証済みコードと互換性試験を以下4コミットで復元した。`3897739`（実装）、`71c91c0`（反復境界回帰テスト）、`786a781`（65分の時間試験）、`574e69c`（ローカル取得停止回帰テスト）。現在枝ソースの既定値はMAX_ROUNDS=24、SOURCE_LIMIT=240、MAX_SECONDS=3900、ROUND_SOURCE_LIMIT=45、POLL_SECONDS=180。既存concurrencyグループとcancel-in-progress=falseは不変。現在進行中のrunの第5巡保存sessionは `requests_used=42`だが `source_limit/max_rounds/stop_at=None`、旧runゆえ安全実証には数えない。

**検証境界:** 修正後の実workerで合計GET<=240、1巡GET<=45、24巡/65分内停止と独立継続ZIP読戻しはなお0件。修正後HEADのViewer/AUTORACE CIは確認時 `pending/in_progress`、合格と誤報しない。未来132レースが残るが現在writerが進行中で上限ポリシー未適用のため、後継先回り予約は実施しない。既存の作業を中断せず、停止回避pushをしない。

**保全:** 初回GitHub artifactは7日保持（無期限所有者限定保全ではない）。指定Private Driveへの本実行での新規保存・所有者/非共有再照合は未実施のため、恒久保全と報告しない。基準5系統の重み/買い目・過去原本・既存workflow/PR/毎時頻度・他タスク・本番切替・実投票・公開・課金・外部サービス変更なし。次は修正後の別workerで上限実運転証明と再取得3ZIPの一致が合格条件。

---

<!-- RACEAI_OFFICIAL_LIVE_ACCESS_20261107 -->
# 2026-11-07 JST｜公式LIVEの403は未解消：通常再生SDKと正規の照会先を確認

**完了した調査:** 丸亀11/6の通常操作原本をSHA照合。公式ページ・SDK・会場設定は200、配信APIは18:18:34.313 JSTに403/P01002「この動画の視聴は許可されていません。」、映像0バイト。既修正のbr/mixローカル判定とは区別した。公開SDK2.5.8は過去の通常操作で保存した版とバイト一致。この正常HTTP403には通信例外/5xx等の再試行が適用されず、公開live.jsにも403からの認証更新処理は確認できなかった。「最初の403で止めたこと」だけを直せば復帰する証拠はない。

**未完成／外部確認が必要:** 視聴拒否の具体的な条件は未特定。地域、ログイン、参照元等を原因と断定しない。公式LIVE取得成功、6艇追跡、実測による強さ評価、動画特徴による前向き精度改善は未成立。配信元に確認する視聴条件・自動取得/分析の利用条件と照会本文を [正規取得経路の調査・照会案](BOATCAST_OFFICIAL_LIVE_ACCESS_20261107.md) に作成。BOATCASTの公開フォームは500文字以内の意見受付で「質問に返信不可」と明記されており、回答のある技術照会先とは扱わない。運営者BOATRACE振興会の公開組織概要まで確認したが、所在地だけでLIVE技術窓口は未特定。照会は**送付先未確定・未送信**で、回答待ちや許諾済みとは扱わない。

**最新HEADとの統合:** GitHubの既存PR71 HEAD701b771を調べ、他作業の監査追記を保全。数値上限240/45GET・24巡・65分を戻す差分は、このチャットの「上限を入れない」という指示に合わせて採用していない。4既定None、実カウンター・原本検査・配信元401/403/429等の待機と、有限値を明示指定する互換性を維持。下の監査文中の数値上限は当時の別作業記録であり、現在の既定ではない。関連99テストPASS。

**実運転・保全:** 監視PID423218・動画取込PID271439は存在を確認し、停止/再起動/手動dispatch/rerun/cancelなし。最新照合run42211744943は21:57:43 JSTにcompleted/successであり、現在実行中とは報告しない。起点予想DBのSHA256は `c40bead05533ace426188ea8a111b1e4a4a639283f576972ba276e14a3e8ff1a` で不変。今回、拒否済み映像への再要求、認証値の取得/転用、接続元変更、契約・課金・環境公開・本番モデル切替は行っていない。

[検証範囲・証拠ハッシュ](evidence/official-live-access-diagnosis-20261107.json)。今回の99テストと静的調査を、新しい公式LIVE再生や実機Safariの成功へ読み替えない。

---

<!-- RACEAI_AUTOMATION_20261106_2305_EXACT_HEAD_CI_PASS -->
# 2026-11-06 23:05 JST｜最新HEADの既存Viewer/AUTORACE CI両成功、実workerの上限遵守は未実証

**今回新しく確定した事実:** 既存Draft PR #71、同一branch HEAD `ca4e86d9e13ac80b8ba0e68976c54df040e5849b` の既存Viewer CI run `42227209786` とAUTORACE CI run `42227209831` は両方 `completed/success`。22:37段階のViewer pendingから進展。race_ai/repeated_cycle.py の現在HEADを再読取し、MAX_ROUNDS=24、POLL_SECONDS=180、SOURCE_LIMIT=240、MAX_SECONDS=3900、ROUND_SOURCE_LIMIT=45を確認。CI合格は**このHEADでの実workerが制限内で停止できた証拠ではない**。先行上限超過の旧runを正常な安全運転と呼ばない。

**既存workflow405276784の実運転:** GitHub直近100 runのうち同workflowのin_progress/queued/pending/waiting=0。最新の完了実run `42211744943` は21:57:43 JSTに `completed/success`、起動固定旧SHA `fb4f70b026424d9b50b792dc308a378664ee7c81`。最終保存第24巡 status.round_no=24 / updated_at=2026-11-06T12:57:25.358152+00:00。継続原本はGET675回（上限240より435超過）、source_limit=nullで運転しており、修正後HEADの実運転とは区別する。日付内の予定156Rは全締切済・未来0R、結果未確認17R・要確認8R・拒否4R。旧上限違反を後継起動で迂回することはしないため、今回trigger/push/cancel/rerun=0。新タスク・workflow・頻度変更なし。

**実ZIP/API再照合:** 最新完了runの全artifactから第24巡の独立元P1 ZIP `13504190716`、公式結果/PDCA ZIP `13503686892`、継続ZIP `13504510192` を再取得。各実SHA256は順に `f45933784ee8c7aab5fa1d748400ac39863983c50c8cc8da786968936c8d72ed`、`0a8034c9c1dc732a6f6613e158275b66d34c2446c0bc1b6194a338678804137c`、`c764592b727418d28681e7a6c85392865693b0def393d25f29d3b53add0eb8cb` でGitHub API digestと一致、ZIP CRC破損0。結果ZIP内のcurrent-p1-original.zipと独立予想ZIPはバイト一致、初回P0 SHA256= `6f900ac94d433aa11bf5b73a70ae68cd6ecf8849000fbb0726b3abd7769e82fc` で初回receiptと一致。status.report_sha256、repeat-session.session_sha256をcanonical JSONで再計算して一致。

**モデル別成績／学習:** 基準モデルはP0各156保存・127採点、P1各84保存・78採点、総採点644モデル×時点行。直前21:33のモデル別7行表から的中・回収率・仮想損益に差分なし。複数モデル合算を単一の仮想成績にしない。台帳全156Rに対しP1完備84R・不足72R×5=360モデル行、未公表展示を取得できたとは断定しない。LEARNED_SHADOW保存134行、同条件比較126行=異なる63R、学習TRAIN96/VALIDATION31。学習版優位性は未証明。本巡、参照する全親学習ZIPの独立再取得はしていないため、全比較の真正性再証明とはしない。

**非公開保全:** 指定Driveフォルダのownerが接続アカウント本人でshared=falseを再確認し、同run第24巡3ZIPの同名既存保存がないことを確認。元GitHub artifact 1件の新規Driveアップロードを試したが `BLOCKED_FILE_REFERENCE` でコネクタ送信不能。新規Drive保存0、他の原本に対する転送迂回なし。過去の保管成功分と今回の未保存分を混同せず、GitHub artifact7日を永久・所有者限定DBと呼ばない。私有ID・URL・認証情報・大量生原本は公開GitHubに記載しない。

**今回の実差分:** 最新HEADの既存Viewer/AUTORACE CIがともに成功したこと。予想/結果/PDCA/係数、モデル別実績と全原本は不変。次の実証は、制限値を保持したHEADで起動する**新しい正常worker**の実GET<=240・1巡<=45、24巡/65分内の安全停止、予想/結果/継続原本の独立読戻し。全4競技/16系統の継続接続、本番自動採用、期限なし非公開原本保存は未完了。

---

<!-- RACEAI_20261106_2237_CYCLE24_VERIFIED_LIMIT_AND_CI -->
# 2026-11-06 22:37 JST｜最終第24巡の独立照合、上限逸脱675GET、旧無制限CI試験3件を安全仕様へ修正

**固定対象:** 既存Draft PR #71 / 同一ブランチ、今回記録直前の最新HEAD `bd515aea09b720544c9365eaf387e75d4f3cb9f3`。workflow405276784の最新run42211744943は固定SHA `fb4f70b026424d9b50b792dc308a378664ee7c81`で2026-11-06 21:57:43 JSTまでにcompleted/success。取得した最新100 runではこのworkflowのin_progress/queued/pending/waitingは0。完走成功は公式GET上限遵守の証拠ではない。未来レース0、未確認結果17、特殊/要確認8、真正性拒否4であり、旧セッション上限違反の後継回避になり得るため追加trigger/cancel/rerunは行っていない。

**最終第24巡原本:** 全artifact一覧から名前の第24巡を選択。元P1 ZIP `13504190716` 実SHA256 `f45933784ee8c7aab5fa1d748400ac39863983c50c8cc8da786968936c8d72ed`、結果・PDCA ZIP `13503686892` 同 `0a8034c9c1dc732a6f6613e158275b66d34c2446c0bc1b6194a338678804137c`、継続ZIP `13504510192` 同 `c764592b727418d28681e7a6c85392865693b0def393d25f29d3b53add0eb8cb`。3件ともGitHub API digestとの一致、ZIP CRC異常0。結果ZIP内current-p1-original.zipは独立元P1とバイト一致。初回P0 ZIP SHA256 `6f900ac94d433aa11bf5b73a70ae68cd6ecf8849000fbb0726b3abd7769e82fc`は既存docs/evidence/2026-11-06/p0-first-receipt.jsonと一致。status.jsonのcanonical report_sha256、repeat-session.jsonのsession_sha256も独立再計算一致。status.round_no=24、updated_at=2026-11-06T12:57:25.358152+00:00。継続readback receipt24件、completed_round=24。

**実差分:** 21:33時点の第16巡から基準保存P0=312/P1=420、モデル別採点644行、LEARNED_SHADOW134行、同条件paired126行=63一意レース、通常確定127Rのすべてが増減0。モデル別P0/P1収支・率も同じなので前掲21:33の7行表を正本参照し、重複合算を新成績と報告しない。ボート13会場156Rは全締切済み、P1完備84R、残り72R×5=360モデル別予想不足。通常確定共通分母127Rに対しP1 Bは**保存済み予想のうち37的中/78採点=47.44%**、一方全正常確定対象では**37/127=29.13%（未予想49件）**。この2つを混同しない。欠測展示が公表済みだったかは未実証。公式結果履歴revision380件、未確認・拒否をMISSに加えない。

**学習版の安全評価:** 127一意通常確定Rから学習96/時間順検証31、FITTED_SHADOW_ONLY。LEARNED_SHADOW保存134/比較可能126行。学習元ZIP全件の今回再取得はしていないため全比較の再真正性完了は主張しない。学習候補の未来優位性未証明、本番基準5系統と原本は不変。

**重大問題:** 結果ZIP内session requests_used=675（forecast234/result441）、指定240GETを**435超過**。continuityも675、source_limit/max_rounds/stop_at=null、completed_round24。以前の第16巡452GETから223増えたが、予想・通常採点・モデル別収支に新規変化はない。この実行は固定旧SHAの無制限版であり、安全成功とは呼ばない。確認時の最新ブランチrace_ai/repeated_cycle.pyにはSOURCE_LIMIT=240、ROUND_SOURCE_LIMIT=45、MAX_ROUNDS=24、MAX_SECONDS=3900、POLL_SECONDS=180が存在する。ただし、この正しいHEADでの実worker 240以内停止は依然0実証。

**CIの実原因と修正:** 旧HEAD444f5588のViewer contract42219066802は1941テスト中の3失敗（test_local_forecast_automationの過去無制限期待2件、test_observed_weight_learningの無期限stop_at期待1件）でfailure。失敗ログを取得し、既存テスト2ファイルだけを修正。241GETからの再開はREVIEW_WAIT / SOURCE_BUDGET_EXHAUSTEDを要求し、移行元原本の不変を確認し、65分・24巡・240/45GETが次の毎時起動前に不当に早く止まらないことを要求。修正commit `99070bda6c020b47d195f94b24ebd3013acc8cc0` と `bd515aea09b720544c9365eaf387e75d4f3cb9f3`。後者のAUTORACE CI42226834201はsuccess、Viewer CI42226834231は確認時pending。未完了CIを成功と呼ばない。追加モデル、予想実装、workflow、schedule、実行制限値は変更していない。

**保全:** 本人専用Driveのフォルダ権限は接続アカウント本人とowner一致/shared=falseを独立確認。最新run原本名の検索結果0件。GitHub元ZIPのDrive新規転送はコネクタがファイル参照を拒否し、今回新規保存0件。ZIPはGitHub7日artifact依存、永久private保存とは認定しない。外部研究manifestは未検証のまま、他競技16系統/全4競技完了へ換算しない。

**次の合格条件:** 後続の**新しい固定HEAD**で実際に起動された既存workerが累計GET<=240・1巡<=45・24巡/65分内で安全に停止し、その予想/結果/継続3元ZIPを独立読戻しできること。過去不適合workerの同run rerun、上限回避push、無承認の本番切替は行わない。

---

<!-- RACEAI_AUTOMATION_20261106_CYCLE16_MODELWISE_QUOTA_RESTORED -->
# 2026-11-06 21:33 JST｜最新保存第16巡の独立監査、モデル別採点更新、有限安全制限を再復元

**実在stateと実行の区別:** 既存Draft PR #71、同一branchの確認時 HEAD `5ff339d6b601836029b0e56f4501698cc3e7cc59`。workflow405276784のrun42211744943（固定run SHA fb4f70b026424d9b50b792dc308a378664ee7c81）は監査時in_progress。直前run42201006851（固定SHA 0ff6439af131cef1b364be283786de3b9bf5f6be）はcompleted/success、第24巡。第16巡以前の実保存分のみ今回の結果として採用し、実行中の未保存第17巡以降を先取りしない。同workflowの取得済み実行一覧にqueued/pending/waitingは0。停止違反を抱えるrunを安全成功とみなさず、旧run rerun/現在run cancel/追加pushは0。

**独立ZIPの原本とSHA:** run42211744943の実artifact一覧から最新保存の第16巡を選択。結果ZIP artifact13502357839の実ZIP SHA256=0aded39a1e604d06bc749e03f98a6bdd46d77e7bc57072832e8a099144ce49cf、予想ZIP artifact13501134753の実SHA256=45a65ec871587657afd4688ce882a99aab571f55de95a0473e84562959e8590d。双方GitHub API digest一致、CRC異常0。結果ZIPに内包のcurrent-p1-original.zipは独立取得の予想ZIPとバイト同一。first-p0-original.zipの元SHA256=6f900ac94d433aa11bf5b73a70ae68cd6ecf8849000fbb0726b3abd7769e82fc、既存初回索引docs/evidence/2026-11-06/p0-first-receipt.jsonと一致。status.jsonのreport_sha256もcanonical JSON SHA256一致。status.round_no=16、updated_at=2026-11-06T12:33:15.325369+00:00。結果ZIP内のsession.completed_round=15/prepared_round=16はreadback前状態なので、第16巡のcontinuity readback完了は未認定。

**各モデルを独立採点した結果**（各モデル3連単8点×100円の仮想購入。通常確定・採点可能な予想だけが的中率の分母。実購入0）:

| 段階／基準モデル | 保存 | 採点 | 的中/不的中 | 的中率 | 仮投資額 | 払戻額 | 仮想収支 | 回収率 | 未採点 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P0 観測相性 | 156 | 127 | 30/97 | 23.62% | 101,600円 | 65,220円 | -36,380円 | 64.19% | 29 |
| P0 ST重視相性 | 156 | 127 | 28/99 | 22.05% | 101,600円 | 63,550円 | -38,050円 | 62.55% | 29 |
| P1 A 展示評価 | 84 | 78 | 20/58 | 25.64% | 62,400円 | 39,490円 | -22,910円 | 63.29% | 6 |
| P1 B コース・モーター | 84 | 78 | 37/41 | 47.44% | 62,400円 | 58,830円 | -3,570円 | 94.28% | 6 |
| P1 C-lite 当地ST | 84 | 78 | 32/46 | 41.03% | 62,400円 | 47,930円 | -14,470円 | 76.81% | 6 |
| P1 観測相性 | 84 | 78 | 21/57 | 26.92% | 62,400円 | 43,350円 | -19,050円 | 69.47% | 6 |
| P1 ST重視相性 | 84 | 78 | 24/54 | 30.77% | 62,400円 | 50,950円 | -11,450円 | 81.65% | 6 |

**前回完了第24巡からの実差分:** P0保存各156/P1保存各84は不変、通常採点626→644（+18モデル別行）、基準モデル単位の採点数はP0 123→127、P1 76→78。P1 Bは35/76・回収率94.90%・仮収支-3,100円から37/78・94.28%・-3,570円へ。Bは展示後5系統のうち最高だが、仮収支はなおマイナス。1日・採点済み条件付き比較を全レース・未来日の優位性へ拡張しない。

**学習版は別枠の同条件比較:** 一意の通常確定127レースを結果取得時刻順のTRAIN96/VALIDATION31に分割、FITTED_SHADOW_ONLY。LEARNED_SHADOWは保存134行、基準対研究版のpaired126行＝63レース×2系統。観測相性の基準15/63的中・払戻36,810円・収支-13,590円・回収率73.04%、学習版15/63・36,680円・-13,720円・72.78%。ST重視基準17/63・43,590円・-6,810円・86.49%、学習版17/63・38,380円・-12,020円・76.15%。各モデル/版の投入50,400円。学習元親ZIP全件は本巡独立再取得できていないので全ペアの新規真正性監査完了は主張しない。精度改善未証明、本番切替0。

**網羅・結果履歴:** 台帳13場156R、締切済156R/未来0R、正常確定127R、結果保留17R・要確認8R・拒否4R。P1五系統完備84R、未予想の締切済72R×5=360モデル別行は監査台帳に維持、取得可能だった展示が当時公表済みかは未確認。通常採点644行/未採点88行、公式結果revision371件を原本に保持。登録16モデルの全入力完備・他3競技との合算成績は認定しない。external_research_summaryはNO_AUDITED_IMPORT_MANIFEST。

**重大な上限違反と修正:** 当該進行runの第16巡セッション requests_used=452（forecast156/result296）、source_limit/max_rounds/stop_at=null。ユーザー指定の総240回上限を212回超過。前の完走run42201006851もrequests_used=747、240を507回超過。旧runの固定コードには安全上限がなく、現在の実行中プロセスへ新コミットを反映できない。既存PR #71のrace_ai/repeated_cycle.py既定をMAX_ROUNDS=24/POLL_SECONDS=180/SOURCE_LIMIT=240/MAX_SECONDS=3900/ROUND_SOURCE_LIMIT=45へ復元（commit564a042b5f55c02ba53682d7523bdf5344f8b0e5）。テストは旧無制限状態の再現を明示的にmock隔離し、実運用の有限既定、1巡45、旧無制限241件の同run再開拒否を新規検証（commit5ff339d6b601836029b0e56f4501698cc3e7cc59）。同HEAD AUTORACE CI42218617837はcompleted/success、Viewer CI42218617935は確認時pendingで**全CI合格未認定**。修正後の別の新実workerで240 GET以下の停止と継続元ZIP読戻しを実証するまで、安全運転認定しない。ユーザーのこの既存定期実行の数値上限指示を厳守し、並行作業の『無制限』記録をこのタスクに適用しない。

**保全と禁止境界:** 今回本人専用Driveへ新規追加保存0。過去に独立保全成功した3元ZIPは今回再読戻ししていない。GitHub artifactの保持7日を恒久保全と呼ばない。private URL/ID/認証情報/大量生データをGitHubへ記録しない。既存PR・workflow・concurrency（cancel-in-progress=false）・毎時スケジュールは不変。新タスク/新PR/新モデル/Cloudflare/Vercel/追加課金/main統合/公開/実投票/本番モデル自動採用・旧run停止回避pushなし。

**次の実証:** 修正HEADで新規に正常起動された既存workflowの1セッションを監査し、累計GET<=240かつ1巡<=45、24巡以内/65分以内の安全停止、独立予想・結果・継続3ZIPのreadbackを確認する。停止違反中の旧runが完走しても同条件の安全成功ではない。

---

<!-- RACEAI_VIDEO_FULL_FIELD_FOLLOWUP_20261106 -->
# 2026-11-06 20:29 JST｜映像3項目：全映像で実測したが完成条件は未達／取得上限なし

**判定:** コード変更・テスト・ブラウザ操作・実映像比較は実施した。ただし、6艇の継続追跡、実測に裏付けられた強さ評価、動画特徴を使う前向き精度改善は **未完成**。試験成功や数字候補数を、これらの完成・98%達成へ読み替えない。

**実装・修正済み:** 既存Draft PR71内で、分割画像の切れ端を同じ艇として重複処理する修正と、異なる時刻に同じ区間を通る艇の4特徴を既存2モデルへ渡す経路を実装した。さらに、保存済み特徴の検証がNumPyへ依存して予想Workerの標準環境で失敗する不備を修正（26fa514）。生成側の動画処理は既存の任意依存に残し、受取・検証・特徴ベクトル化はNumPy/OpenCVなしで通る。退化行列の拒否には標準ライブラリの正確な計算を使い、丸め誤差で特異行列を受理する不備も再現テストで修正した。既存V1/V2、4特徴、2モデル、未学習係数0、本番/予想適格性falseは維持する。

| 映像の完成条件 | 全映像での結果 |
|---|---|
| 識別・6艇の継続追跡 | 許諾済み原本775フレームの全BGR/PTSを照合し、97解析時点で同じ実検出・カメラを使って既存/元画素方式を比較。実検出679回＋CRNN1343回。番号の連続候補は0→2だが、追加の盲検AI参照でも固定IoU.5を満たさず正解認定なし。10枚・45参照枠の幾何一致は7（検出漏れと位置ずれを含む）。全6艇の番号が直接読める参照機会0で、6艇精度は未算出。 |
| ターン・出足・行き足・伸びの強さ | 元画素方式の実core出力582位置中、有効位置0。4特徴の計算・既存モデル接続は制御テストで確認したが、実映像の強さは認定できない。カメラ間隔を原本へ戻す対照では利用可能区間15→39だが、新たな30区間の独立精度確認がなく不採用。画像上の代理値を物理速度/強さと表示しない。 |
| 動画特徴による精度改善 | 適格な現在映像・締切前保存・後日の公式結果を結んだ比較0件。丸亀11/6の公開LIVE操作は403/P01002で視聴拒否。権限・経路を変えて回避していない。動画由来の的中率・回収率改善は未実証。 |

**追加調査で訂正・前進した点:** 旧参照に3号艇がなかったことは、元映像に数字3がないことを意味しなかった。元の許諾済み映像から、直接読める数字1～6を各2例、計12個の位置ラベルと、数字以外5例をAI目視で作成・封印した。人間の正解データや独立検証ではなく、同一映像内で時間的に相関する開発用参照である。明示的に不明な領域は除外し、服の色・消去法で番号を補っていない。

この17例だけで局在器を学習する固定案は実14枚で改善せず不採用。正しい数字位置を与えた診断では同じCRNNの原本切出し10/12、既存余白加工3/12だったが、元画素方式の全映像比較では上記の通り正解ID増加や有効位置を確認できなかった。局在器・正規化・原本全フレームでのカメラ補正の各試験は、重み・閾値・参照を結果に合わせて変更せず、旧失敗も保存した。候補版・新カメラ設定・新学習重みを実運転へ切り替えていない。

**検証:** 最終コードのPython全1938件PASS/0skip（340.746秒）。標準環境相当のNumPy/CVなしではデータ専用2件PASS、動画生成用16件は明示skip。上限・互換性105件、結果照合18件、Node契約35件もPASS。Chromiumの7画面操作、保存原本/PDCA、暗号化Pages、結果/予算の4ブラウザスイートを合成データで確認した。実機Safari・最初の8参考画像との新たな比較・実レース精度の証拠とは分ける。独立再レビューのP1/P2指摘は修正後解消した。過去の9242b99はViewer42198208757/AUTORACE42198208756がSUCCESSだが、このCIを新しいコードの検証結果へ流用しない。

**上限・自動運転・原本:** 取得/巡回/時間/1巡取得の4既定値はすべてNone。並行作業で再導入された240/45/24/65分は最新のユーザー指示に合わせて採用せず、有限ライブラリを明示指定する互換テストだけを残した。実カウンター、原本照合、401/403/429・Retry-After待機は維持。監視PID423218・動画取込PID271439の停止/再起動、手動dispatch/rerun/cancelは行っていない。通常の引継ぎで新run42201006851（固定0ff6439、4既定None）を採用。今回の保存時点のローカル監視はrun42201006851、最終観測2026-11-06T11:28:17.043783+00:00、api_wait=None。観測間隔だけから全レースの無停止カバーを保証しない。起点DBの再照合SHA256 `c40bead05533ace426188ea8a111b1e4a4a639283f576972ba276e14a3e8ff1a` は不変。

**外部の素材・検証が必要:** 視聴・利用できる現在レースの展示映像と正しいレース結合、代表的な角度/会場の船体・番号の独立した正解、強さの実測参照、以後の公式結果が不足している。権利未確認の戸田・福岡素材を学習へ転用していない。一般公開・main統合・実投票・本番モデル切替・新しい予想モデル系統・課金サービスは増やしていない。

集計・コードSHA・私有証拠SHAは [全映像追試記録](evidence/boat-video-field-validation-followup-20261106.json)。原動画・学習画像・学習重み・買い目・鍵はGitへ追加していない。

---

<!-- RACEAI_20261106_2013_CYCLE17_DIFF_ONLY -->
# 2026-11-06 20:13 JST｜保存第17巡を独立再照合（モデル成績の変化なし）

run42201006851は旧固定SHA 0ff6439af131cef1b364be283786de3b9bf5f6be でin_progress。新しく保存された第17巡結果ZIP artifact13498016396のGitHub API/実SHA256=37c3a8d574d3b73b825a47dcb4de9ac8142b4325261d4948aa669d4c93606d4a、P1元予想ZIP artifact13498161078の同SHA256=6d6a04fad5588f89fdf2ed4bd012fe2df12628b86b23a22ca7a7c65d819e3450。ZIP CRC両方正常、結果内包current-p1-original.zipは独立予想ZIPにバイト一致、first-p0-original.zip SHA256は6f900ac94d433aa11bf5b73a70ae68cd6ecf8849000fbb0726b3abd7769e82fcで不変、status.report_sha256もcanonical JSON再計算で一致。status.round_no=17、updated_at=2026-11-06T11:12:18.511792+00:00。

第16巡と比較したモデル別予想数・通常採点・的中・仮損益・仮回収率は**全7段階/モデル行で増減0**。第16巡モデル別成績表をそのまま参照。台帳は締切済152R・未来4R、P1五系統予想不足350モデル別行。学習版130予想/同条件比較118行も増減0。公式取得セッションは累計GET=527（第16巡の504から+23）、240上限を**287 GET超過**、source_limit=nullの旧実workerである。ブランチには有限制限の修正を反映済みだが、実行中workerでは未検証で安全認定できない。今回後続の予約・キャンセル・再実行・Drive追加保管・モデル自動昇格なし。

---

<!-- RACEAI_AUTO_20261106_2010_CYCLE16_SAFETY -->
# 2026-11-06 20:10 JST｜モデル別第16巡結果を独立ZIP監査、240 GET上限再復元

**RUN/HEAD:** 実worker `42201006851`（起動固定SHA `0ff6439af131cef1b364be283786de3b9bf5f6be`）は本監査時in_progress。新しい保存第16巡のstatus.round_no=16、updated_at=2026-11-06T11:09:22.367394+00:00。完走扱いせず、同workflowの後継待機runは確認範囲で0。既存runキャンセル、rerun、追加push、他タスク変更なし。

**元原本独立読戻し:** 第16巡予想ZIP 13498410424（GitHub API/実SHA256 `992eaf00394ec58f14547ab134f1ab398f13b4f5799d38d73b5130542567d403`）、結果ZIP 13498400418（同 `d51dc706c53c2f236453d181c082626543ed1b59112ca1b1047311cc0b2ec17c`）、双方CRC破損なし。結果ZIP内 `current-p1-original.zip`と独立予想ZIPはバイト一致。`first-p0-original.zip` SHA256=`6f900ac94d433aa11bf5b73a70ae68cd6ecf8849000fbb0726b3abd7769e82fc`で不変。status.report_sha256=canonical JSON再計算一致。第16巡結果ZIP内sessionは`completed_round=15/prepared_round=16`であり、第16巡の継続readbackは本結果ZIPだけでは未確認。

| 段階・モデル | 保存 | 通常採点 | 的中 | 的中率 | 仮投資 | 仮払戻 | 仮損益 | 仮回収率 | 未採点 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P0 観測相性 | 156 | 121 | 29 | 23.97% | 96,800円 | 64,720円 | -32,080円 | 66.86% | 35 |
| P0 ST重視相性 | 156 | 121 | 27 | 22.31% | 96,800円 | 63,050円 | -33,750円 | 65.13% | 35 |
| P1 A | 82 | 74 | 18 | 24.32% | 59,200円 | 33,690円 | -25,510円 | 56.91% | 8 |
| P1 B | 82 | 74 | 34 | 45.95% | 59,200円 | 52,400円 | -6,800円 | 88.51% | 8 |
| P1 C-lite | 82 | 74 | 30 | 40.54% | 59,200円 | 42,130円 | -17,070円 | 71.17% | 8 |
| P1 観測相性 | 82 | 74 | 20 | 27.03% | 59,200円 | 42,850円 | -16,350円 | 72.38% | 8 |
| P1 ST重視相性 | 82 | 74 | 23 | 31.08% | 59,200円 | 50,450円 | -8,750円 | 85.22% | 8 |

**前の19:32 JST第3巡との差分:** P1各モデル保存+2/採点+2、P0採点+3。モデル別損益増減はP0観測-2,400円、P0 ST-2,400円、P1 A+3,910円、P1 B-860円、P1 C-lite-860円、P1観測-1,600円、P1 ST-1,600円。通常確定・採点可能レースだけが率の分母。別モデルやP0/P1を混ぜた仮想収支をモデル成績として報告しない。

**学習/前向き比較:** 適格な一意121レースを取得順で学習91/検証30に分割。LEARNED_SHADOWは保存130行、同条件paired118行＝59R×2系統。観測相性は基準14/59的中、払戻36,310円、学習版14/59、36,180円。ST重視は基準16/59、払戻43,090円、学習版16/59、37,880円。各モデル各版の仮投入47,200円。学習版の改善は未実証、全親学習ZIPの今回再取得は未実施、本番切替なし。

**網羅/原本:** ボート13場156R、締切済152R・未来4R、P1五系統完備82R・締切済P1未予想350モデル別行（70R分）。基準保存722モデル・時点行、通常採点612、未採点110（RESULT_PENDING61/ABNORMAL_FINISH_REVIEW_REQUIRED41/RESULT_REJECTED8）。結果観測334 revisionを保全。出走/展示の当時公開可能性は未確認。model_coverage 16登録/全稼働未達、external_research_summary は NO_AUDITED_IMPORT_MANIFEST。

**重大安全逸脱:** 旧固定SHAの第16巡session.requests_used=504、指定の240回を264 GET超過。`source_limit/max_rounds/stop_at=null`で動作。現在ブランチHEADのデフォルトも`None`へ戻されていたので既存の安全実装とテストの2ファイルのみ検証済みcommit `8a63bed8d8cc49e54e99173f9324e5f9392fe564`の有限値へ復元（240 GET/1巡45 GET/最大24巡/65分/通常180秒）。4xx/429・真正性停止は回避しない。修正後の新workerでの上限順守は未実証。上限違反旧runを安全成功と認めない。

**保全/境界:** 過去の本人専用Drive3元ZIP保存成功を維持、今回Drive追加保存0。既存P0/P1/結果revision・基準5モデルの式/買い目・既存workflow/concurrency/頻度・他タスク・PR・課金・公開・main・投票・モデル自動採用は変更なし。artifact7日を永久保存扱いしない。

---

<!-- RACEAI_AUTOMATION_20261106_1935_CYCLE03_DRIVE_READBACK -->
# 2026-11-06 19:35 JST｜進行run保存第3巡を実ZIPで照合、元ZIP3件を本人専用Driveへ新規保存・独立読戻し

**監査対象区別:** 本チャットの前記録で完走run42191323045の第24巡を確定。その後のworker run42201006851（固定SHA 0ff6439af131cef1b364be283786de3b9bf5f6be）は本監査時in_progress。第3巡までの予想ZIP/結果ZIPは保存済みで、未完了の第4巡以降を実績に含めない。既存workflow405276784、同concurrency、cancel-in-progress=falseはそのまま。追加のtrig/cancel/rerunなし。

**新保存第3巡の元ZIP:** 2026-11-06 19:32:21 JSTのstatus.json round_no=3、run42201006851。予想artifact13494614802のバイト/API SHA256=397402d7789c7678be9e2d2776e5f7e41a9b05fa6022e3f558375319d8bb9a42、結果artifact13494944051のバイト/API SHA256=eab2ebc55eb4553adff9c4fcdfbd061bfe371d642a53913248895236e956020d。各ZIP CRC異常0。結果ZIP内包current-p1-original.zipは独立予想ZIPとバイト一致、first-p0-original.zip実SHA=6f900ac94d433aa11bf5b73a70ae68cd6ecf8849000fbb0726b3abd7769e82fcは既存初回索引と一致。status.report_sha256をcanonical JSONで再計算し一致。結果ZIPのsessionは読戻し直前completed_round=2/prepared_round=3なので第3巡の継続readback完了までは認定しない。

| 段階/基準モデル | 保存 | 通常採点 | 的中/不的中 | 的中率 | 仮投入(8点×100円) | 払戻 | 仮損益 | 回収率 | 未採点 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P0 観測相性 | 156 | 118 | 29/89 | 24.58% | 94,400円 | 64,720円 | -29,680円 | 68.56% | 38 |
| P0 ST重視相性 | 156 | 118 | 27/91 | 22.88% | 94,400円 | 63,050円 | -31,350円 | 66.79% | 38 |
| P1 A | 80 | 72 | 16/56 | 22.22% | 57,600円 | 28,180円 | -29,420円 | 48.92% | 8 |
| P1 B | 80 | 72 | 33/39 | 45.83% | 57,600円 | 51,660円 | -5,940円 | 89.69% | 8 |
| P1 C-lite | 80 | 72 | 29/43 | 40.28% | 57,600円 | 41,390円 | -16,210円 | 71.86% | 8 |
| P1 観測相性 | 80 | 72 | 20/52 | 27.78% | 57,600円 | 42,850円 | -14,750円 | 74.39% | 8 |
| P1 ST重視相性 | 80 | 72 | 23/49 | 31.94% | 57,600円 | 50,450円 | -7,150円 | 87.59% | 8 |

全表はモデル別×時点別の採点可能な条件付き結果。今日の156R全部の的中率でも、モデルを混ぜた実収支でもない。台帳対象156R、締切済148R/未来8R、P1五系統完備79R、締切済不足345モデル行を維持。基準保存712モデル段階行、通常採点596、未採点116、公式観測revision289。

**学習版を基準7行と分離:** 通常確定の一意118RのTRAIN89/VALIDATION29、研究係数のみ。LEARNED_SHADOW保存126、paired114モデル行=57レース×2系統。観測相性：基準14/57的中・払戻36,310円・損益-9,290円・回収率79.63%、学習14/57・36,180円・-9,420円・79.34%。ST重視相性：基準16/57・43,090円・-2,510円・94.50%、学習16/57・37,880円・-7,720円・83.07%。各版の仮投入45,600円。学習候補の優位は未成立。本番切替なし。学習元全ZIP再独立照合は本巡未実施。

**重要な非公開保全の実差分:** 所有者アカウントの一致とshared=falseを再照合した指定の本人専用Driveフォルダへ、完走run42191323045の第24巡に対応するP1元ZIP・結果元ZIP・継続元ZIPの計3ファイルを無改変で新規保存。Google Driveから3件を独立再取得してSHA256が各GitHub API元ZIP digest（5f9e4e20…、ad1b1aec…、0eabff20…）と完全一致、3件ZIP CRC異常0を実行環境で検証。公開GitHubにはフォルダID、私有URL、認証情報、生ソースを転記しない。これは3原本の別保全が成功した事実であり、すべての7日artifactの無期限保存完成ではない。

**安全とCIの未完了:** 前runの実取得740 GET、指定上限240を500超過。新run42201006851の第3巡保存内でも93 GET（forecast38/result55）、固定SHAは上限None。過去の違反を新コードで免責しない。既存PR71にMAX_ROUNDS=24/POLL_SECONDS=180/SOURCE_LIMIT=240/MAX_SECONDS=3900/ROUND_SOURCE_LIMIT=45を再復元し、停止移行の規約を維持。コミット0cda076f0、8a63bed8d。既存Viewer CI 42202627963は上限復元後の旧試験前提によりfailures3/errors1。旧仕様だけを検査する試験の隔離・期待を修正した同一PR追加コミット c771a631、2b5825c9、6078eb56。最新コードHEAD6078eb56のAUTORACE CI42203708383=success、Viewer CI42203708392は本監査時pending、合格未認定。進行中runは上限Noneの古い固定SHA、停止/キャンセル/再起動/後続トリガーは発行していない。有限上限の実worker証明は依然0。

**変更禁止事項:** 既存5基準の式・重み/買い目・全原本、同workflow/concurrency/毎時タスク、新タスク/PR/モデル系統、課金、Cloudflare/Vercel、main統合、一般公開、実投票、本番自動採用は不変。全4競技/16系統/全レース事前保存は未達。

---

<!-- RACEAI_AUTOMATION_20261106_1920_MODELWISE_RUN421913_FINAL -->
# 2026-11-06 19:20 JST｜最新完走run第24巡を独立検証、モデル別成績と上限修正を再確認

**固定したGitHub実在状態:** Draft PR #71 / 作業branchの確認時HEAD 8a63bed8d8cc49e54e99173f9324e5f9392fe564。対象workflow 405276784 は完走run 42191323045 が completed/success（固定run SHA 9bad5644bf7f0a21a15907073ba86ad10b27aede、完了19:10:40 JST）、後続run 42201006851 が in_progress（固定run SHA 0ff6439af131cef1b364be283786de3b9bf5f6be、開始19:13:31 JST）。確認時後続runの完了artifactは0件であり、最新完了巡の値を後続runの進行値としない。調査範囲の同workflowにqueued/pending/waitingは0。追加push/キャンセル/rerunは0。

**独立実ZIP・整合監査:** run42191323045の全50 artifactから第24巡を選択。予想ZIP 13494800033 の実/API SHA256=5f9e4e20eddfd6421f2c51be52ed528c1160641c4b5463caabd92d7675986a5e、結果ZIP 13494765244 の実/API SHA256=ad1b1aeccf824b1a1d2cd3f109f7bc352a4e59322c98d2305940aa5a6d73d745、継続ZIP 13494870021 の実/API SHA256=0eabff20f57927c0a93d79ece9d35c6b96169f52838a245f86a0d0bc2b3c0850。それぞれバイトSHA256一致・ZIP CRC異常なし。結果ZIPに内包するcurrent-p1-original.zipは予想ZIPとバイト同一。first-p0-original.zip SHA256=6f900ac94d433aa11bf5b73a70ae68cd6ecf8849000fbb0726b3abd7769e82fcは既存初回索引p0-first-receipt.jsonの値と一致。status.json round_no=24、updated_at=2026-11-06T10:10:17.653515+00:00。statusのreport_sha256と最終repeat-session.jsonのsession_sha256もcanonical JSONの再計算で一致。継続セッションcompleted_round=24、readback receipts24件。

**モデル別P0/P1基準成績（通常確定だけ、1モデル8点×100円仮購入、重複混合禁止）:**

| 段階・モデル | 保存 | 通常採点 | 的中/不的中 | 的中率 | 仮投入 | 仮払戻 | 仮損益 | 回収率 | 未採点 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P0 観測相性 | 156 | 116 | 29/87 | 25.00% | 92,800円 | 64,720円 | -28,080円 | 69.74% | 40 |
| P0 ST重視相性 | 156 | 116 | 27/89 | 23.28% | 92,800円 | 63,050円 | -29,750円 | 67.94% | 40 |
| P1 A 展示評価 | 79 | 71 | 16/55 | 22.54% | 56,800円 | 28,180円 | -28,620円 | 49.61% | 8 |
| P1 B コース・モーター | 79 | 71 | 33/38 | 46.48% | 56,800円 | 51,660円 | -5,140円 | 90.95% | 8 |
| P1 C-lite 当地ST | 79 | 71 | 29/42 | 40.85% | 56,800円 | 41,390円 | -15,410円 | 72.87% | 8 |
| P1 観測相性 | 79 | 71 | 20/51 | 28.17% | 56,800円 | 42,850円 | -13,950円 | 75.44% | 8 |
| P1 ST重視相性 | 79 | 71 | 23/48 | 32.39% | 56,800円 | 50,450円 | -6,350円 | 88.82% | 8 |

直前の完走runの前の第1巡表示（P1各75件/通常採点各68、P0各110件）に対し、今回P1各79件/採点71、P0採点116へ増加。P1 B回収率90.95%でも赤字。的中率は通常採点の条件付き分母であり、156全レースHit@8ではない。混合総投資/損益を主成績に使用しない。

**学習比較（完全に別枠）:** 一意116レースを学習87・後方検証29へ取得順で分割、研究学習結果artifact trained_observed_models.jsonはFITTED_SHADOW_ONLY。LEARNED_SHADOW保存124モデル別行、同条件比較112行=異なる56レース×2系統。観測相性は基準14/56、払戻36,310円、仮損益-8,490円、回収率81.05%。学習版14/56、払戻36,180円、仮損益-8,620円、80.76%。ST重視は基準16/56、払戻43,090円、仮損益-1,710円、96.18%。学習版16/56、払戻37,880円、仮損益-6,920円、84.55%。各ペア側は56×800=44,800円の仮投入。学習元ZIP全件の今回の独立再取得は未実施。係数変更は前向き精度改善の証明にならず、正式採用0。

**網羅と公式結果:** 13場156レース台帳。保存P0=312、P1=395で計707モデル・時点予想。通常採点587/未採点120（各モデル別の未採点は上表参照）。締切済146R/未来10R。P1五系統完備79R、締切済未予想340モデル別行=68レース×5系統。通常確定適格116R、結果pending18R/unknown4R/special8R。結果観測履歴286revision。出走表や展示が各時点で公表済みかは未立証。未確認・返還・結果異常をMISSとしない。個別モデルの欠損と全対象分母はcoverage_auditに保持。

**安全上限違反と実際の処置:** 完走run42191323045の継続原本はrequests_used=740（予想280/結果460）、SOURCE_LIMIT/max_rounds/stop_atすべてnull。指定240 GETを500回超過しており、安全な正常完走とは認定しない。続く現在のrun42201006851も上限なし固定HEAD 0ff6439で起動済み。並行作業で指定240/45/24/65分の上限が何度もNoneへ差し戻されていたため、今回も既存PR71のrace_ai/repeated_cycle.pyを上限240/45/24/3900/180秒に戻し、tests/test_repeated_cycle.pyの既定値pin回帰テストを復旧、旧無制限試験は明示的な隔離patchのみに限定。適用commit 0cda076f052f9fa29eb393594f98f963830d58aa、8a63bed8d8cc49e54e99173f9324e5f9392fe564。最終コミットHEADのAUTORACE CI 42202331556=success、Viewer 42202331452=pending（確認時）。これらは現在の実行中workerへ反映されない。有限上限で動く次回の実worker停止・独立読戻しは未実証。上限/4xx/429/改変停止を追加runで迂回しない。

**保全と未達:** 今回Drive新規アップロード0（所有者/非共有をこの実行では未再検証）。GitHub artifactは7日、無期限本人専用保管ではない。全16系統、全4競技、全レースP1、学習版の統計的優位、実worker有限GET停止は未達。新タスク/PR/別workflow/スケジュール/Cloudflare/Vercel/課金/main/公開/実投票/本番モデル切替なし。

---

<!-- RACEAI_VIDEO_SEQUENTIAL_STITCHING_20261106 -->
# 2026-11-06 18:41 JST｜映像3項目の実装・実映像比較：完成判定は未達、取得上限なし

**最新の明示指示:** 取得数・巡回数・稼働時間・1巡取得数に人工的な上限を入れない。現在の `MAX_ROUNDS / SOURCE_LIMIT / MAX_SECONDS / ROUND_SOURCE_LIMIT` はすべて `None`。並行作業の240/45/24/65分への変更は、この指示に合わせて統合時に採用していない。下に残る「240GET安全復元」「上限逸脱」は当時の監査記録であり、現在の設定ではない。計数・改変検出・原本照合と公開元の401/403/429・Retry-After待機は維持する。

**実装した部分（既存Draft PR71、コード517e290）:** 1艇ずつ通る展示を、同じ元映像・基準画像・実カメラ系列・通過ゲート/領域に結び付けて比較する経路を追加した。ターン半径、出足・行き足の変化、直線の画像運動の4特徴を計算し、既存2モデルの学習入力・接続処理へ渡せる。艇別の観測窓、直接番号根拠、内部の欠測、誤差、締切・取得時計を検査する。単位はpxとメディア秒で、物理的な速さ/強さへの換算や良否の向き、的中確率は未認定。空間ゲートの自動校正・自動フェーズ発見まで完成したとはしない。既存V1/V2と原本は維持する。

分割検出では、同じ艇の完全な候補と境界で切れた候補が重複し、番号処理を止める原因を実7呼出しの画素・原点・矩形で再現した。親候補と同じ内部端へ1入力画素以内に接し、切り取った親とのIoU>.5を満たす場合だけ重複を除く。レビューで見つかった内部の別艇候補を消す不備を修正した。既存の重なり保留、未読時の番号移譲防止、通常の非分割既定値は維持する。

| 完成条件 | 実測・現在の判定 |
|---|---|
| 識別・6艇の継続追跡 | October原本617フレーム/78回の実検出・カメラ処理、対象7枚の実OCRで番号候補1件を出力。独立した盲検AI目視参照で正番号1/35、別の7例は番号不明。全6艇を読める参照機会0のため6艇精度は未算出。完成条件は未達。 |
| 強さ評価 | 4特徴の計算と既存モデル接続は制御テストで確認。実映像の適格な連続位置・独立した強さ正解は不足。カメラ97サンプルの原因を調査し、元出力と完全一致する計測を保存。固定ORB案は独立した岸19点でも改善を確認できず不採用。実強度/物理速度は未認定。 |
| 動画特徴による精度改善 | 現在レースの許可された映像・適格な締切前コンテキスト・後日の公式結果を結んだ比較0件。最新の丸亀11/6 LIVEは18:18:34 JSTに403/P01002「視聴は許可されていません」で停止。未検証の強さ・確率・回収率や98%達成は表示しない。 |

**修正の実映像効果:** 同一49回の実検出を共有して旧処理/修正版へ別々に実OCRを通した。Octoberは艇の一致42/42を保ち、余分な検出19→9、全候補61→51。ただし正番号は1→1で改善なし。Augustは全候補47→45、番号出力0→0。752番は重複停止を解消して実OCRが正常完了したが、数字の位置候補が空で未読になった。いずれも再利用した開発映像とAI参照であり、未知映像の精度や人間の正解データではない。新しくメートル位置を評価した実験でもない。旧失敗、途中の拒否案、原本はすべて別途保存した。

**追加データ/外部接続が必要な部分:** 許諾済みCommons映像の既存参照は、既に見た全体を開発用として数えても読み取れる番号19例で3号艇0例、数字位置ラベル0件、人間検証なし。6艇用番号認識器の十分な教師データではない。未知の権利の戸田映像を学習素材へ転用していない。現在レースの公式映像403を別経路で回避していない。6艇の独立した番号/追跡正解、強さの実測正解、視聴可能な現在映像と以後の公式結果、実機Safariは引き続き未完了条件である。

**検証と保全:** 最終映像コードでPython全1906件PASS/0skip（319.169秒）、Node35件PASS、Chromium320/390/1440/1920pxで合成データ30操作確認・34PNG・ブラウザエラー0。並行した会場学習接続を統合後、影響範囲65件PASS、さらにPython全1918件PASS/0skip（436.229秒）を確認。これはSafari実機・8枚の参考画像との再比較・実レース精度の証拠ではない。2件の独立コードレビューと接続全体の最終レビューを修正後GREENで記録。既存CIの動画テスト一覧に新規テストを追加し、新しいworkflowは増やしていない。

既存自動予想run42191323045（固定9bad564、4上限None）は18:38:54 JST時点で監視中、`api_wait=null`。監視PID423218、動画取込PID271439は停止・再起動していない。起点DBのSHA256 `c40bead05533ace426188ea8a111b1e4a4a639283f576972ba276e14a3e8ff1a` は再照合で不変。新しいCV経路を現行取込プロセスや本番予想へ無断切替していない。main統合・アプリ公開・投票・追加課金は実施していない。

機微情報を除いた集計と私有証拠SHAは [実証記録](evidence/boat-video-sequential-stitching-20261106.json)。一般公開できない映像・参照画像・買い目・鍵はGitへ追加しない。

---

<!-- RACEAI_AUTOMATION_20261106_RUN42191323045_ROUND01_SAVED -->
# 2026-11-06 18:12 JST｜新run第1巡保存分のモデル別PDCA（worker全体は実行中）

**読戻し・区分:** GitHub workflow 405276784 のrun `42191323045`（固定run SHA `9bad5644bf7f0a21a15907073ba86ad10b27aede`）は現時点で **in_progress**。GitHub jobの第1巡stepはsuccess、第2巡はin_progress。第1巡P1原本artifact `13490821300` のZIP/API digest=`e7034a4b5830cc35957c09768a54066d5c9c619109bc9319114b40d4d35779a1`、結果・PDCA artifact `13491265201` のZIP/API digest=`0e46830dda7ffdcc2de382fb579a48f8acd7726570875d7ed99bac651b954604` はそれぞれ独立取得した実ZIP SHA256と一致し、ZIP CRC異常なし。結果ZIP内包P1元ZIPは独立取得したP1 ZIPとバイト一致、初回P0内包ZIP SHA `6f900ac94d433aa11bf5b73a70ae68cd6ecf8849000fbb0726b3abd7769e82fc` も不変。結果ZIP内 `status.json` は `round_no=1`、`updated_at=2026-11-06T09:10:57.802782+00:00`。同ZIPのsession `completed_round=0/prepared_round=1` は継続readback**前**の値であり、run全巡完走、最終continuity独立読戻し完了とは主張しない。

**採点済分のみ、モデル・版ごとの仮想収支（各モデル8点×100円）:**

| 段階・モデル | 保存 | 採点 | HIT | 的中率 | 仮投資 | 仮払戻 | 仮損益 | 回収率 | 未採点 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P0 観測相性 | 156 | 110 | 28 | 25.45% | 88,000円 | 62,740円 | -25,260円 | 71.30% | 46 |
| P0 ST重視相性 | 156 | 110 | 26 | 23.64% | 88,000円 | 61,070円 | -26,930円 | 69.40% | 46 |
| P1 A | 75 | 68 | 15 | 22.06% | 54,400円 | 27,050円 | -27,350円 | 49.72% | 7 |
| P1 B | 75 | 68 | 32 | 47.06% | 54,400円 | 50,530円 | -3,870円 | 92.89% | 7 |
| P1 C-lite | 75 | 68 | 27 | 39.71% | 54,400円 | 38,340円 | -16,060円 | 70.48% | 7 |
| P1 観測相性 | 75 | 68 | 19 | 27.94% | 54,400円 | 38,920円 | -15,480円 | 71.54% | 7 |
| P1 ST重視相性 | 75 | 68 | 21 | 30.88% | 54,400円 | 44,600円 | -9,800円 | 81.99% | 7 |

**前の最終保存第24巡からの実差分:** P1モデル別保存各+1、P0モデル別採点各+7・HIT観測+3/ST+2、P1モデル別採点各+1・HIT各+1。各モデルの純損益は前回からP0観測+6,280円/P0 ST+5,740円、P1各+390円改善したが、全モデルとも現在マイナス。P1 Bが採点済みでの暫定最良（92.89%）だが未学習モデル/未実証モデルを本番切替しない。その他モデルとP0/P1、研究LEARNED_SHADOWは合算評価せず別表示。

**網羅・学習:** 当日13会場156R、締切済140R・未来16R、P1五モデル完備74R、締切済P1不足330モデル別行を監査台帳に保持し、展示公開状態は未確認のまま取りこぼしを全て可能と断定しない。LEARNED_SHADOW 116研究予想・paired106行、前向き優位性未認定。結果異常/未確認/不整合は採点分母から分離し、全対象台帳から消さない。

**上限逸脱の区別:** このrunのセッション原本は `source_limit=null` / `max_rounds=null` / `stop_at=null` で第1巡保存時`requests_used=63`。**実workerは修正前の固定HEAD**で動作し、現HEADの240GET安全復元は実行中runに反映されない。既存PR71ブランチ上の `race_ai/repeated_cycle.py` のデフォルトは240/1巡45/24巡/65分/180秒へ修正済みだが、修正HEADによる実worker安全停止は依然未証明。停止回避の後続push/同run rerun/cancelはしていない。別PR・別workflow・他タスク・課金/サービス・本番切替・公開・投票は触れない。

---

<!-- RACEAI_AUTOMATION_20261106_MODEL_BY_MODEL_1809 -->
# 2026-11-06 18:09 JST｜モデル別の仮想収支・的中率と次worker安全上限の復元

**今回の実差分:** 基準モデル全体の合算値だけで収益性を説明すると各モデルの強弱が見えないため、これ以降の正式報告は `stage + model_id` ごとに、採点済件数/的中数・率/投資/払戻/純損益/回収率/未採点件数を分離する。LEARNED_SHADOWも研究用別枠とし、P0/P1、異なるモデルの予想を同じ「1件の的中率」に混合しない。

**独立監査に使った保存済み原本:** 同workflowの最新**完了済み**run `42177614402` 第24巡。予想artifact 13487355443 (`sha256:f5d6c1151e4530f72eb295ca54c326132fdd590e3ae2e5e300655ab487f108be`)、結果artifact 13487495212 (`sha256:1d9478fb89464c7a70ca96d9ecf58dcec9a96753fa604d704d9bdc8e2df606f6`)、継続artifact 13487220725 (`sha256:c8e0f0a48f96eaca9e726477df9a7c14f8aca183b67be8d5dd6c0574edd2a45a`)を実ZIP読戻しし、実SHA256=API digest・CRC正常。結果ZIP内 `status.json` の `round_no=24`・`updated_at=2026-11-06T08:01:21.786868+00:00`、`scoreboard` と `per_forecast` を照合。保存済みの通常採点だけが分母。直近in_progress runの未完了巡回を加算しない。

| 予想版・基準モデル | 保存 | 採点 | 的中 | 的中率 | 投入(各8点×100円) | 払戻 | 仮想純損益 | 回収率 | 未採点 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P0 観測相性 `boat-observed-pairwise-factor-v1` | 156 | 103 | 25 | 24.27% | 82,400円 | 50,860円 | -31,540円 | 61.72% | 53 |
| P0 ST重視相性 `boat-observed-pairwise-start-v1` | 156 | 103 | 24 | 23.30% | 82,400円 | 49,730円 | -32,670円 | 60.35% | 53 |
| P1 A `boat-display-rating-PL-reference-v1-UNVALIDATED` | 74 | 67 | 14 | 20.90% | 53,600円 | 25,860円 | -27,740円 | 48.25% | 7 |
| P1 B `boat-course-motor-shadow-v0.1-UNTRAINED` | 74 | 67 | 31 | 46.27% | 53,600円 | 49,340円 | -4,260円 | 92.05% | 7 |
| P1 C-lite `boat-local-start-course-shadow-v0.1-UNTRAINED` | 74 | 67 | 26 | 38.81% | 53,600円 | 37,150円 | -16,450円 | 69.31% | 7 |
| P1 観測相性 `boat-observed-pairwise-factor-v1` | 74 | 67 | 18 | 26.87% | 53,600円 | 37,730円 | -15,870円 | 70.39% | 7 |
| P1 ST重視相性 `boat-observed-pairwise-start-v1` | 74 | 67 | 20 | 29.85% | 53,600円 | 43,410円 | -10,190円 | 80.99% | 7 |

**判定と網羅性:** P1 Bの採点済67件における回収率92.05%が最良だが、全基準モデルの仮想純損益はマイナス。P0モデルは各53件、P1モデルは各7件が未採点。未確認・異常・結果拒否を不的中にしない。締切済・未保存を分母から除いて全国網羅済みとは主張しない。全体合算は監査用照合値でしかなく、モデル選抜の根拠に使用しない。学習版paired104行/52Rは基準7モデル採点541行と別管理し、改善優位なし・本番モデル不変。

**安全コードと実稼働の区別:** 既存Draft PR #71の同ブランチ `race_ai/repeated_cycle.py` と `tests/test_repeated_cycle.py` だけを、既存の安全検証済み版blobへCAS更新。修正commit `080c8f2fc72f7f1f5670de21b5e1829b50a3d29f` と `5c76f2ee9c39e18a2f9d9f128f5fb192e7f4caca`。デフォルト `SOURCE_LIMIT=240`/`ROUND_SOURCE_LIMIT=45`/`MAX_ROUNDS=24`/`MAX_SECONDS=3900`/`POLL_SECONDS=180` の回帰テストを復元。更新HEADのAUTORACE CIは成功、Viewer CIは確認時点でpending。**修正後workerのGET以内安全停止・原本読戻しは未実証**。

新しく起動した同workflow run `42191323045` は2026-11-06 17:56:49 JSTから `in_progress`、実行固定HEAD `9bad5644bf7f0a21a15907073ba86ad10b27aede` は安全修正前（当該ソースの上限がNone）。18:09 JST時点でこのrunの完成済み巡回artifactは0件。安全コードをブランチに復元しても進行中runには適用されない。停止回避の追加push/後続起動・cancel/rerunはしない。GET違反・4xx/429・真正性不一致の原因を迂回せず監査する。

**運用境界:** 同じPR・workflow・concurrencyを維持、実行頻度、新タスク/PR/workflow、新モデル系統、Cloudflare/Vercel、追加課金、main統合、一般公開、実投票、本番自動切替は変更なし。GitHub7日artifactを恒久非公開DBとは呼ばない。

---

<!-- RACEAI_MODEL_SPECIFIC_REPORT_CORRECTION_20261106 -->
# 2026-11-06 18:01 JST｜モデルごとに的中率・仮想収支・回収率を分離する正式報告ルール

オーナー指摘：モデルを混ぜた収支・的中率・回収率では実力を判断できない。以後、RACE-AIの結果報告は必ず競技×開催日×モデルID×段階(P0/P1)×基準/学習版別に提示し、モデル混合の合計損益・合計回収率・合計的中率を見出しや結論の主指標に使わない。
各モデルごと、保存予想数、採点可能件数、的中件数、的中率、8点×100円の仮投入・仮払戻・仮損益・回収率、未採点/異常/返還/未予想件数と不的中原因を表示する。各モデルの条件付き成績と全通常確定レースを共通分母にしたHit@8は別指標。結果未確認を負けにせず、複数モデル・版の成績を足して単一運用利益と呼ばない。実投票収支は未確認として分離。

**参照固定時点:** 2026-11-06 17:01:21 JSTの旧run42177614402・第24巡。結果ZIP artifact13487495212の実バイトSHA256=1d9478fb89464c7a70ca96d9ecf58dcec9a96753fa604d704d9bdc8e2df606f6、P1原本ZIP artifact13487355443のSHA256=f5d6c1151e4530f72eb295ca54c326132fdd590e3ae2e5e300655ab487f108be、継続原本ZIP artifact13487220725のSHA256=c8e0f0a48f96eaca9e726477df9a7c14f8aca183b67be8d5dd6c0574edd2a45a。すべてGitHub登録digestと実SHA一致・ZIP CRC異常0。後続run42191323045は確認時in_progressでartifact0件、旧第24巡の数字を新runの実績と混同しない。

| 段階 | モデル | 保存 | 採点 | 的中/外れ | 仮投入 | 仮払戻 | 仮損益 | 的中率 | 回収率 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| P0 | 観測相性 | 156 | 103 | 25/78 | 82,400円 | 50,860円 | -31,540円 | 24.27% | 61.72% |
| P0 | ST重視相性 | 156 | 103 | 24/79 | 82,400円 | 49,730円 | -32,670円 | 23.30% | 60.35% |
| P1 | A 展示評価 | 74 | 67 | 14/53 | 53,600円 | 25,860円 | -27,740円 | 20.90% | 48.25% |
| P1 | B コース・モーター | 74 | 67 | 31/36 | 53,600円 | 49,340円 | -4,260円 | 46.27% | 92.05% |
| P1 | C-lite 当地ST | 74 | 67 | 26/41 | 53,600円 | 37,150円 | -16,450円 | 38.81% | 69.31% |
| P1 | 観測相性 | 74 | 67 | 18/49 | 53,600円 | 37,730円 | -15,870円 | 26.87% | 70.39% |
| P1 | ST重視相性 | 74 | 67 | 20/47 | 53,600円 | 43,410円 | -10,190円 | 29.85% | 80.99% |

11/6の台帳対象156R、基準P0=312・P1=370モデル別行。通常採点541モデル別行。上表の分母は採点済みのレース数であり、全対象156Rの的中率ではない。未採点はP0各53、P1各7モデル行。未予想を含む同一共通分母Hit@8はcoverage_auditの通常確定分母と照合して別に表示する。

**LEARNED_SHADOWは独立表示（同条件52レース×各2系統）:** 観測相性基準12/52的中、払戻31,190円、仮損益-10,410円、回収率74.98%。学習版11/52、払戻29,930円、仮損益-11,670円、回収率71.95%。ST重視基準13/52、払戻36,050円、仮損益-5,550円、回収率86.66%。学習版14/52、払戻32,760円、仮損益-8,840円、回収率78.75%。各モデル×版の仮投入41,600円。学習版114保存行中104行比較可能。学習成功と前向き優位性は別、本番採用なし。

**原因別PDCA（P1）:** Bの不的中36件＝3着候補14/1着候補外10/1・2着組合せ12。Aの53件＝19/20/14、C-liteの41件＝16/9/16、観測相性49件＝18/17/14、ST重視47件＝17/15/15（同じ順）。各モデルの改善候補は未来レースで事前検証し、過去8点の買い目を変更しない。

今回の変更対象は監査記録と今後の報告形式だけ。既存モデル・過去予想・結果revision・既存workflow・実行頻度・新タスク・新PR・main・公開・追加課金・実投票・自動本番切替は変更しない。

---

<!-- RACEAI_AUTOMATION_20261106_CYCLE24_VERIFIED_1751 -->
# 2026-11-06 17:51 JST｜第24巡の独立ZIP監査と上限違反確定（後続起動せず）

**固定の事実:** 既存Draft PR #71のブランチ HEAD `35295f9f13f3e8f81766100cbce110481268f024` を確認。対象workflow `405276784` のrun [42177614402](https://github.com/haji84/RACE-AI/actions/runs/42177614402) は旧固定SHA `f6987b3466b4b58f1420c20018e9be886e7a1c06` で2026-11-06 17:01:40 JSTまでに `completed/success`。GitHub repository最新30 runでは対象の後継in_progress/queued/pending/waitingは確認されなかった。ただし全履歴の完全な待機網羅ではないため、追加pushやrerunは**0件**。16:44の第16巡観測を今回の最終状態へ延長しない。

**独立の元ZIP監査:** 対象runのGitHub全50 artifactから第24巡を抽出。P1元予想artifact `13487355443`（実ZIP/API SHA256 `f5d6c1151e4530f72eb295ca54c326132fdd590e3ae2e5e300655ab487f108be`）、結果artifact `13487495212`（同 `1d9478fb89464c7a70ca96d9ecf58dcec9a96753fa604d704d9bdc8e2df606f6`）、継続artifact `13487220725`（同 `c8e0f0a48f96eaca9e726477df9a7c14f8aca183b67be8d5dd6c0574edd2a45a`）をコネクタから再取得し、実バイトSHA256とGitHubのAPI digest一致、3 ZIPのCRC異常0。結果ZIP内の`current-p1-original.zip`は独立取得P1 ZIPとバイト一致、初回`first-p0-original.zip`の実SHAは初回索引 `docs/evidence/2026-11-06/p0-first-receipt.json`と同じ `6f900ac94d433aa11bf5b73a70ae68cd6ecf8849000fbb0726b3abd7769e82fc`。旧P0/P1再生成なし。内包`status.json`は`round_no=24`、`updated_at=2026-11-06T08:01:21.786868+00:00`。最終continuityの`repeat-session.json`は`completed_round=24`、readback receipt 24件。第24巡以降の未完了値は加算しない。

**保存された実績（最終巡、11/6ボート13会場156R）:** 基準P0=312件・P1=370件、計682モデル×時点行。結果通常採点541行=HIT158/MISS383。未採点141行=RESULT_PENDING92、異常着順要確認41、RESULT_REJECTED8。採点済み541行の仮想8点×各100円は投入432,800円、受取294,080円、仮収支**-138,720円**、仮回収率**67.95%**。前回第16巡比P1 +5、通常採点+16、HIT±0、MISS+16、仮収支-12,800円。個別レース156件の正式的中率ではなく、複数基準モデルとP0/P1を重複する研究値。実投票0。公式結果観測履歴245revisionを保持し、未確認を外れにしない。

**学習と網羅:** 研究用観測相性2系統だけを一意103レースから学習78・時系列未使用検証25に分割、`FITTED_SHADOW_ONLY`。LEARNED_SHADOW 114モデル別予想、結果済み同条件paired 104モデル別行（**52種類のレース**）。観測相性: 元12/52的中・学習11/52、仮受取31,190円対29,930円。ST重視相性: 元13/52・学習14/52、仮受取36,050円対32,760円。学習版優位は証明されず本番切替なし。今回、114件が参照する親学習元ZIP全件の独立再取得は未実施。台帳は保存時点で締切済133R/未来23R、P1五系統完備73R、締切済P1未保存300モデル別行。未公表展示の取得可能性は不明。全16系統/全4競技完了には換算しない。

**安全違反:** 最終継続原本`requests_used=732`（予想290/結果442）、指定上限240を**492 GET超過**。`source_limit=null`、`max_rounds=null`、`stop_at=null`で動作。旧runのsuccessは上限遵守ではない。ブランチ最新`race_ai/repeated_cycle.py`では`SOURCE_LIMIT=240`、`ROUND_SOURCE_LIMIT=45`、`MAX_ROUNDS=24`、`MAX_SECONDS=3900`、`POLL_SECONDS=180`を実読取。ただし**修正HEADでの実workerが240 GET以内で安全停止・読戻しできたという実証は0件**。旧runの停止条件を後続起動で回避しない。既存concurrencyは同グループ、`cancel-in-progress: false`を再確認。

**保全と制限:** 本人専用Driveは接続ユーザーと所有者一致・shared=falseを確認。対象run原本の未保存名を検索したが0件。GitHub取得ZIPのDriveアップロードは`BLOCKED_FILE_REFERENCE`で成立しなかったので、今回Drive新規保存0件。これはGitHub7日artifactの無期限owner-only保全ではない。私有フォルダ情報、生の大容量原本、認証情報は公開GitHubに記録しない。他タスク/実行頻度、新workflow、新PR、Cloudflare/Vercel、課金、main統合、一般公開、実投票、モデル自動昇格は一切変更しない。

**次の合格条件:** 修正済みコードで起動された**別の正常な実worker**で累計GET240以内・巡回45以内を実証し、停止時に予想/結果/継続元ZIPを独立再読込すること。上限違反した旧runを安全成功としない。

---

<!-- RACEAI_AUTOMATION_20261106_CYCLE16_VERIFIED_1644 -->
# 2026-11-06 16:44 JST｜既存run第16巡の原本を独立読戻し、旧実行のGET上限超過を再確認

**確認元と現在性:** Draft PR #71のbranchを確認、検証時HEAD `e0f1697debe9fc7529ebe777b17080c7251be0e7`。既存workflow `405276784`のrun [42177614402](https://github.com/haji84/RACE-AI/actions/runs/42177614402) は旧固定コード `f6987b3466b4b58f1420c20018e9be886e7a1c06` で**in_progress**。同workflowの取得済み直近300 runで別のqueued/pending/waitingを認めず、後続トリガーは発行しない。runのjobでは第16巡のstepがcompleted/success、第17巡がin_progress。以下は第16巡の保存済み時点の数字で、実行中の未保存第17巡を加算しない。

**独立保存物:** 予想ZIP artifact `13486475784`の実バイトSHA256 `08b59f28de37403bb636f3153014ee614deda6ea364fefe4bffa077e1198a425`、結果・PDCA ZIP artifact `13485861917`の実バイトSHA256 `3cea9580775d108a2ce137736805d95d98405b4632845dbfd5bf0b8530e30d8c` は各GitHub API digestと一致し、外側ZIPのCRC異常は0。結果ZIP内包P1 ZIPは独立取得P1 ZIPとバイト一致。P0 ZIP artifact `13428142302`のSHA256 `6f900ac94d433aa11bf5b73a70ae68cd6ecf8849000fbb0726b3abd7769e82fc` ともバイト一致。結果内部statusは `round_no=16`、`updated_at=2026-11-06T07:42:15.424733+00:00`。同ZIP内sessionの `completed_round=15/prepared_round=16` はアップロード時の値であり、完了巡回artifactと混同しない。

**実成績と前回第12巡との差分:** 13場156R、基準P0=312、P1=365、計677モデル・時点行（第12巡から増減0）。通常確定採点525（HIT158/MISS367、増減0）、未採点152。モデル・時点ごと8点×100円の仮定で投入420,000円、受取294,080円、仮収支 **-125,920円**、仮回収率 **70.02%**。実購入なし。締切済130R・未来26R、P1五系統が揃う72R、締切済P1不足290モデル別行。未公表展示の公開可能性は未証明。結果取得失敗16件は外れに換算しない。公式結果履歴revision235件は原本内に存在。

**自動学習と同条件比較:** 係数学習は通常確定100一意レースを時系列でTRAIN75/VALIDATION25に分離した研究版のみ。LEARNED_SHADOW112モデル別行、独立した基準とのpaired100行=異なる50R、前向き優位性未立証、本番自動採用なし。今回学習元ZIP全件の独立再取得は行っておらず、全比較の新規真正性監査完了を主張しない。

**安全違反と処置:** 旧run第16巡の内包session実数は `requests_used=493`（forecast193/result300）、`source_limit=null`、`max_rounds=null`、`stop_at=null`。指定240 GETを **253 GET超過**。第12巡378から+115 GET、予想件数や採点は変わらず。run successやstep successは上限遵守ではない。現在HEADの `race_ai/repeated_cycle.py` はSOURCE_LIMIT=240、ROUND_SOURCE_LIMIT=45、MAX_ROUNDS=24、MAX_SECONDS=3900、POLL_SECONDS=180を独立読取で確認し、当該安全版commit `db7063d4a8536ee877bebb52cac64aec3c642b63` の既存Viewer/AUTORACE両CIはsuccess。ただし修正後の新worker実証はまだ0件。旧runのcancel/rerun、停止の迂回を目的とした新トリガー、運用上限の解除はしない。並行作業が指定上限をNoneに戻していた履歴を残し、今後も新HEADと固定run SHAを区別して検証する。

**変更境界:** 今回は監査記録のみ。元P0/P1、基準5モデル、学習係数、実行頻度、workflow/concurrency、他タスク、新PR/main/公開/課金/実投票を変更しない。Drive新規保全なし。artifact7日を恒久私有保管と呼ばない。

---

<!-- RACEAI_AUTOMATION_20261106_1634_BOUNDED_RESTORE_CYCLE12 -->
# 2026-11-06 16:34 JST｜240 GETの指定上限を再復元、最新保存第12巡を独立検証

**今回の上限修正:** 既存Draft PR #71の同一ブランチでコード・回帰テストを1コミット `db7063d4a8536ee877bebb52cac64aec3c642b63` にまとめて反映した。新しいsession既定値は `SOURCE_LIMIT=240`、`ROUND_SOURCE_LIMIT=45`、`MAX_ROUNDS=24`、`MAX_SECONDS=3900`、`POLL_SECONDS=180`。従来の上限なし履歴を検証する13試験は明示的にその設定を注入する隔離試験とし、現在の既定値を固定する回帰テストを追加した。コードをGitHubから独立読戻しして値と追加テストの存在を確認。これは**コード反映の事実**であって、修正後の実worker成功を意味しない。確認済みAUTORACE CI `42181593013` はcompleted/success。Viewer CI `42181593404` は16:34時点でpending、合格未認定。

**実稼働runと本件の安全違反:** Workflow `405276784` の現在run `42177614402` は修正前の固定SHA `f6987b3466b4b58f1420c20018e9be886e7a1c06` で実行中。ユーザー指定240回上限に対し、保存済み第12巡に内包されたsessionの実値は `requests_used=378`（**138 GET超過**）、`source_limit=null`。修正後のコードはこのin_progress workerには適用されない。同runの前に完了したrun `42172002810` 第24巡の継続原本は `requests_used=703`（463超過）、completed_round=24、readback receipt24件。停止回避目的の再起動・新trigger・rerun・cancelは実施していない。競合する並行作業によって既定値が繰り返しNoneへ戻されているため、**現在のコード修正だけで次回安全運転が保たれるとは言えない**。同時writerは追加していない。

**最新保存済み第12巡だけの独立照合:** active run `42177614402` の結果ZIP artifact `13484574899` 実SHA256 `ea986a2b43bd60088fbfc730669cd2c49a7d01b712d4a7c6625d463337793a89`、P1 ZIP `13485795498` 実SHA256 `94f34bb26e7ef827ec4029e22dc49fffde77a7969898689163675ba60d0bdddf` はともにGitHub API digestと一致、ZIP CRC正常。結果ZIP内部のP1元ZIPと独立P1 ZIPがバイト一致。初回P0原本はartifact `13428142302` を独立取得して実SHA256 `6f900ac94d433aa11bf5b73a70ae68cd6ecf8849000fbb0726b3abd7769e82fc` とCRC正常、結果ZIP内包P0とも一致。statusの`round_no=12`、`updated_at=2026-11-06T07:31:23.296342+00:00`を確認。session内部は第12巡readback**前**の`completed_round=11/prepared_round=12`なので、現在runや第12巡の継続読戻し完了と誤認しない。

**第12巡に固定した成績（11/6ボート156R）:** 基準P0=312/P1=365、計677モデル・時点行。通常採点525行＝HIT158/MISS367、未採点152。モデル・時点ごとの仮想8点各100円では投資420,000円、仮想払戻294,080円、仮想収支**-125,920円**、仮想回収率**70.02%**。同じレースをモデル別/版別に重複採点する研究値で、全国156Rの一意レース的中率でも実購入実績でもない。coverageは締切済129R、未来27R、P1五系統完備71R、締切済P1欠測290モデル別行。欠測展示が事前公表済みだったと断定しない。結果取得不可17件も外れにしない。

**係数学習と比較:** 通常確定一意100Rを学習75/検証25に時系列分割し、既存観測相性2系統の研究版のみ更新。LEARNED_SHADOW保存112モデル別行、paired100行（異なる50R）。観測相性モデルは学習版11/50的中・元版12/50、払戻29,930円対31,190円。ST重視相性は学習版14/50・元版13/50、払戻32,760円対36,050円。学習版が明確に優秀という結論にはならず、本番切替なし。今回、112件すべての親学習ZIPを再取得して検証したわけではない。

**未完成・保全:** 修正後runの240GET以内停止、全レースP1・全16/4競技、原本の無期限私有保全、学習版の将来優位性は未実証。今回はDriveへ原本追加保存せず。既存PR/Workflow/毎時タスクの枠組みやconcurrencyを変えず、main・公開・追加課金・投票も変更していない。

---

<!-- RACEAI_FINAL_VERIFIED_SCOPE_AND_REMAINING_GATES_20261106 -->
# 2026-11-06 15:26 JST｜上限なし修正のコードCI成功、後継Worker実行中・映像3条件は未完成

**完成を確認した範囲:** 既存Draft PR #71で、認証復帰・一要求内の原本検証再利用・数値上限なしの修正を保存した。並行の会場履歴/公式K/成績/予算画面の変更も保全した。修正を含むコードHEAD [45a2749](https://github.com/haji84/RACE-AI/commit/45a2749e36806035cd275c4b54bb2437931a2528)の既存Viewer [42172920937](https://github.com/haji84/RACE-AI/actions/runs/42172920937)・AUTORACE [42172920961](https://github.com/haji84/RACE-AI/actions/runs/42172920961)はcompleted/success。観測した後続HEAD1298618との差は別競技のaudit JSON2件のみで、ソース・テスト・Workflowは同じだった。この追記自体は記録だけで、そのChecksを過去のコードCIと混同しない。続くf1e7320で同じ数値上限が再導入されたため、検証済みの346335be（None既定・計数/取得元待機/整合性保持）とd20be01dの試験を復元した。再導入側の差分は数値既定とその既定を要求する試験であり、新たな実カウンタ保護は失っていない。両方の監査記録は保持した。

**自動運転の最新事実:** 旧run42164651846は05:47:39 UTCに通常終了していた。前のin_progress表示を現在へ延長した説明を訂正する。並行の数値上限再導入は後継条件と矛盾しており、今回の修正後、同じWorkflowの後継 [42172002810](https://github.com/haji84/RACE-AI/actions/runs/42172002810)が06:03:02 UTCに自動起動した。06:23 UTCの正規メタデータで実行中を再確認。約15分の引継ぎ間隔があり、全時間・全レースを無欠落で連続実行したという認定はしない。人工的な取得/巡回/時間上限はNone、401/403・429/Retry-After・真正性停止、計数・旧申告・受領証は保持している。実行中runを手動停止・cancel・rerunしていない。監視は同じ私有保存先/ポートのPID423218、映像intake271439は保持、初回DBのSHAは不変。

**実データ画面:** 並行追加された読取用scriptを同じloopbackサーバーへ反映し、Chromium390/1440で663保存予想（P0=312/P1=351）、156台帳/取得結果73の分母、各モデルのTop8/SHA・原本不変を確認した。26 GETのみ、外部/生成/投票/source取得は0。日予算1000受理・50拒否など表示操作は合格。一方、実P1の試算はモデル版・保存時刻の証拠不足で全予定が除外され、成立していない。後のP1=372件の全groupでも予定0だった。未確定額を含む全体収支の分岐は実データでは非該当、合成試験の合格だけを根拠にする。根拠のない版・時計・金額を補って機能完成に見せていない。

**未完成・外部入力条件:** 実映像の最終識別は旧AI参照10例で0、有効位置0、動画特徴を使う前向き比較0件。現方式の識別性能不足、解析に使える現行展示映像・独立正解・水面/時計/強さ参照の未接続が残る。6艇継続追跡、ターン・出足・行き足・伸びの強さ、動画による改善は完成していない。実機Safariも未受入。取得・解析を認められた映像供給経路と独立参照の接続が必要で、既知403等の迂回や不明な素材の学習使用はしていない。全4競技/全モデルの無欠落運転、98%達成、私有原本の無期限保管もこの結果から認定しない。

実装・合成/実データ試験・失敗と修正・証拠のSHAは[続行証拠](evidence/2026-11-06/real-video-validation/continuation.json)に保存。main統合・一般公開・実投票・本番モデル切替、新PR/Workflow/サービス/課金は実施していない。

---

<!-- RACEAI_AUTOMATION_20261106_1524_CYCLE09_QUOTA -->
# 2026-11-06 15:24 JST｜第9巡の独立原本・採点を確認、240 GET制限を既存PRへ復元

**固定HEADと稼働区別:** 既存Draft PR #71、同一ブランチの安全修正commit `f1e732061fd61556b301c97e994430c101e75ad0` で`race_ai/repeated_cycle.py`の既定値をSOURCE_LIMIT=240、ROUND_SOURCE_LIMIT=45、MAX_ROUNDS=24、MAX_SECONDS=3900、POLL_SECONDS=180に復元し、既存制限テストを同一commitで整合。旧セッションや停止証拠を後書きで改変しない。修正後の実worker検証とexact-HEAD CI結果はこの時点で未確定。現在のrun [42172002810](https://github.com/haji84/RACE-AI/actions/runs/42172002810) は**修正前の固定HEAD `e4fed1d74b2e43170ceb314a518bdba4104f21ff` でin_progress**、今回の修正はこのプロセスへ適用されていない。queued/pending/waitingの後続は確認範囲で0件。旧run rerun、追加trigger、cancelなし。

**最新独立読戻し（保存済み第9巡のみ）:** 第9巡の結果ZIP artifact `13482461562`、SHA256 `ca2e0ff3b431310e44630085297a256ed94205cc59af08b06ddb7dc8f3ef445d` とP1 ZIP `13482301968`、SHA256 `041947fc7c3a2835684461698ea5b2ed42c8904adcaa929229e788476a23388b` をGitHubから別取得。双方API digest＝実ZIP SHA256、CRC破損0。結果ZIP内P1原本はP1 artifact実ZIPと同一。初回P0内包ZIPのSHA `6f900ac94d433aa11bf5b73a70ae68cd6ecf8849000fbb0726b3abd7769e82fc` は既報と不変。結果ZIPのstatus.round_no=9、updated_at=2026-11-06T06:24:13.849479+00:00。sessionは読戻し前のcompleted_round=8/prepared_round=9であり、第9巡readback完了やrun完走を先取りしない。

**第9巡までの保存済み成果（11月6日ボート156R）:** P0=312、P1=305、合計617モデル・時点行。通常確定の採点417行＝HIT145/MISS272、未採点200。7モデル・時点それぞれ8点各100円の仮定で、採点済みに限る仮投入333,600円／仮受取274,680円／仮収支-58,920円／回収率82.34％。同レース複数モデル・時点の合計であり、156R全体や実投票の成績ではない。通常結果81R、締切済110R・未来46R、P1五モデル不足260モデル別行をcoverage_auditへ残す。未公開展示を取得可能だったと推定しない。研究LEARNED_SHADOWは基準から別計上88モデル別予想・同条件paired72行、前向き改善は未認定。

**重大な実行逸脱:** 第9巡保存時点の旧run session.requests_used=**258**（forecast114/result144）、指定240回を**18回超過**。旧固定HEADのsource_limit=nullにより停止していない。これを正常な上限遵守と報告しない。後続runの先行予約は停止条件の回避になるため行わず、既存の実行中writerをキャンセルしない。今後の別runで240以内の停止と、最後の保存原本独立readbackを実証するまで安全運転未達。

**保全:** 本人専用Driveフォルダの権限を当該接続アカウントとのowner一致・shared=falseで再確認した。ただしGithub ZIP→Drive uploadはconnector file_uri型エラーで成立せず、今回新規Drive原本0。GitHub artifactは7日保持のまま。新PR、別workflow、毎時タスク変更、モデル系統追加、Cloudflare/Vercel、main統合、一般公開、追加課金、実投票、本番自動切替なし。

---

<!-- RACEAI_AUTHORIZED_NO_NUMERIC_CAPS_RESTORED_AGAIN_20261106 -->
# 2026-11-06 14:55 JST｜並行更新の数値上限再導入を修正、旧計数と取得元の待機は保全

**適用する指示:** このチャットのオーナー後続指示「取得上限なし」「その上限や停止もなし」「開発中も自動運転を止めない」を適用する。同じPRの並行commit40325f9/7e11d9aで240 GET・1巡45 GET・24巡・65分と旧None方針の拒否が再導入され、既存監視の引継ぎ条件とも矛盾していた。人工的な4種の既定値だけを`None`へ戻した。HTTP401/403、429/Retry-After、時刻・真正性・原本不整合の停止は解除しない。以前の427取得を240以内と偽る変更ではなく、過去の取得数・累計・原本は減らしていない。

**実装と検証:** 新たに加わった巡回開始時の取得計数は保持し、明示的な有限制限を設定したライブラリ試験も残した。旧数値方針の移行では元SHA・旧停止理由/上限・それまでの移行履歴、準備中ラウンド・受領証・取得元待機を保持する。再計算した累計が既存の申告値より小さくなる場合は、書込前に拒否し元ファイルを残す。重複と構文破損が混入していたテストを修復した。関連93件PASS/skip0（11.412秒）、別担当の5件もPASS/skip0（0.218秒）、独立レビュー合格。310取得・27巡・78分相当と再起動後の保持は**合成試験**であり、新たな実取得や全開催網羅の実証ではない。並行の公式K解析修正も保持し、別途25件PASS/skip0を確認した。

**運転と未完成条件:** 予想run42164651846は従前の上限なしコードを使用した。前回のin_progress観測を現在へ延長せず、旧runの完了・後継起動は改めて実メタデータで確認する。今回の修正によるrun停止・再起動・rerun/cancelはしていない。監視と映像intake、私有checkpoint、予想原本も書き換えていない。この修正は、次の通常引継ぎで再び数値停止しないためのコード修正である。同じPRに矛盾する方針の並行更新が続いた事実を残す。今回の修正コミットのCIはpush後に別途確認する。既に合格したb10758b等のCIをこの未push差分の合格と読み替えない。

映像の最終番号識別0/10、有効位置0、動画特徴による将来比較0件は変わらず、3項目は未完成。通常データの締切14分53秒前保存、実JSONのTop8/SHA表示一致と区別する。main統合・一般公開・実投票・本番モデル切替・新PR/Workflow/課金なし。詳細なSHAは[続行証拠](evidence/2026-11-06/real-video-validation/continuation.json)へ記録した。

---

<!-- RACEAI_FINAL_24R_QUOTA_REGRESSION_AUDIT_20261106 -->
# 2026-11-06 14:50 JST｜旧worker全24巡の原本保存を独立確認、GET630回の上限違反を確定

**最終結果の観測対象:** workflow405276784/run [42164651846](https://github.com/haji84/RACE-AI/actions/runs/42164651846) は旧HEAD 70514b3でcompleted/success。しかし安全上限遵守には**失敗**しており、successを安全運転認定しない。全50 artifactを確認して最後の第24巡の予想ZIP `13479874664`（SHA256 `a1f6e725ae9ab3e73e0761f1e11beef9f0e872ce05d6805e9a8abf4d43597143`）、結果ZIP `13479879941`（`db05cb5d9e5ab21d208b0c61f8d02950970709ce7a0772a4383c0b18c9e102fe`）、continuity ZIP `13481370042`（`7e149febf610c8ad500dc052899bce15395e1970f0c9277f8411640bf1892edc`）をすべて独立再取得。実ZIP SHA256はGitHub API digestと一致、CRC異常0。内包P1は別取得予想ZIPと一致、初回P0 ZIP SHA `6f900ac94d433aa11bf5b73a70ae68cd6ecf8849000fbb0726b3abd7769e82fc`は不変。最終continuity内 `repeat-session.json` は`completed_round=24`、readback receipt24個を記録。status.jsonは`round_no=24/updated_at=2026-11-06T05:47:21.305897+00:00`、同結果ZIP内部のsessionはreadback前の`completed_round=23/prepared_round=24`なので区別。

**旧実行の停止規則違反:** 最終continuityの`requests_used=630`（forecast273/result357）で許容240回を**390回超過**、`source_limit=null/max_rounds=null/stop_at=null`でquota停止は働いていない。先ほどの安全修正commit [40325f9](https://github.com/haji84/RACE-AI/commit/40325f978575f5cdaa2be00c4e5ba8466be0b0d3)は旧実runの固定HEADに含まれない。次回の新規実workerでの上限実証は未完了。追加トリガー・同run rerun・cancelなし。

**最終第24巡の業績:** 13場156R、基準予想587モデル・時点行（P0 312/P1 275）、通常結果採点364行（的中132・不的中232）、未採点223。1点100円×8点/モデル・時点の仮想購入では投資291,200円・受取260,660円・仮収支-30,540円・回収率89.51％。実投票ではなく、同じレースを複数モデル/版で採点。台帳で締切済98R、未来58R、P1五モデル完全51R、締切済P1不足235モデル別行。展示のその時点の公開可否は未独立確認。全レース的中率とは呼ばない。

**既存係数学習と未来比較:** FITTED_SHADOW_ONLY、異なる通常確定72Rを学習54/検証18へ分離、学習研究版76モデル別予想、同条件比較58行=異なる29R。観測相性は学習版8/29的中、元版9/29。ST重視は学習版10/29、元版10/29で仮払戻は学習版27,130円対元版31,580円。精度改善・優位性は不成立。本番モデルは不変。全学習元artifactの今回の独立読戻しはしていない。

**修正後テスト/CIの現在地:** 安全修正は既存PR71の同一ブランチ内。古い既存Viewer CI [42169864461](https://github.com/haji84/RACE-AI/actions/runs/42169864461)は失敗（テスト移植時の文字列途切れ1件と旧無制限仕様を期待するlocal test2件）。途切れたfixtureを修復し、上限遵守の旧仕様テストも維持すべき停止へ変更した。既存取得ソースに安全コードを当てて83件をローカル再検証してPASS。修正後の正確な最新HEADのCIはまだ未確認であり、修正完了と認定しない。既存AUTORACE contract [42169864380](https://github.com/haji84/RACE-AI/actions/runs/42169864380) は前安全修正HEADでsuccessだったが、旧失敗Viewerの代替合格ではない。

**保全・禁止操作:** 今回Drive所有者/非共有は未再確認で新規保存なし。元ZIPは7日artifactのままで恒久DBではない。全16/4競技の直前予想・長期非公開保存・研究版の前向き優位性未達。新タスク/新PR/別workflow/実行頻度変更/無検証の本番切替/実投票/公開/Cloudflare/Vercel/追加課金なし。

---

<!-- RACEAI_LIMIT_RESTORED_IN_EXISTING_PR_20261106_1443 -->
# 2026-11-06 14:43 JST｜旧Workerの公式GET上限超過を独立検出し、既存PR71の次回コードへ上限制御を復元

**確認したHEADと実run:** 既存Draft PR #71・同じbranchへ安全制御commit [40325f9](https://github.com/haji84/RACE-AI/commit/40325f978575f5cdaa2be00c4e5ba8466be0b0d3)をfast-forward適用。workflow405276784の実行中run [42164651846](https://github.com/haji84/RACE-AI/actions/runs/42164651846)は**旧HEAD 70514b3で開始したまま**であり、今回のコード修正は実行中プロセスには適用されない。同workflowのqueued/pending/waitingは監査時0件。追加trigger・run cancel・rerun・別workflow・schedule変更なし。

**独立保存検証（完了済みartifact第22巡、実run全体はまだin_progress）:** 予想ZIP artifact 13480781705の実SHA256=`11c2437cbb9e8c8f7a3d5c4e7737aaaa1ad5ce97169f9a2e885ad4a2b99f1f55`、結果/PDCA ZIP artifact 13480502682の実SHA256=`4cd09d3bbdf9fb94321452746967a176e31268d85f9a2c90b3a19ac99017c244`。GitHub API登録digestと実バイトが両方一致、両ZIP CRC正常、結果ZIP内P1のZIPハッシュも予想ZIPと一致。内部status.jsonは`round_no=22`、`updated_at=2026-11-06T05:42:20.995662+00:00`。同一status内repeat sessionの`completed_round=21/prepared_round=22`は読戻し直前の状態であり、第22巡の継続読戻し完了やrun successとは主張しない。初回P0 ZIPの元SHA=`6f900ac94d433aa11bf5b73a70ae68cd6ecf8849000fbb0726b3abd7769e82fc`で不変。

**この保存時点の実集計:** 対象156R。基準モデル・時点予想582行（P0 312/P1 270）、通常採点364行（HIT132/MISS232）、未採点218行。基準7モデル・時点を各8点100円で全採点分のみ仮想購入した計算で投資291,200円・払戻260,660円・仮収支-30,540円・仮回収率89.51%。実購入なし。締切済97R・未来59R、5系統P1完全50R、締切済P1不足235モデル別行。展示が当時公表されたか不明な未保存を取得可能な取りこぼしと断定しない。公式結果観測revision156件。

**自動学習の実数:** 既存観測相性2系統のみFITTED_SHADOW_ONLY、異なる通常確定72Rを学習54R/検証18Rに分離。研究LEARNED_SHADOWは基準に合算せず74予想、未来結果の同条件ペア58モデル行＝異なる29R。観測相性は学習版8/29対元版9/29、仮払戻26,020円対27,280円。ST重視相性は学習版10/29対元版10/29、仮払戻27,130円対31,580円。学習版優位性は未実証、基準5モデルの式・重み・買い目と本番選択に変更なし。学習元全件の再独立取得は今回実施せず。

**重大な安全上限違反と改修範囲:** 旧実run第22巡の`requests_used=582`（forecast253/result329）で指定240回を**342超過**。旧実行コードの`SOURCE_LIMIT=None/MAX_ROUNDS=None/MAX_SECONDS=None`と一致。これを安全正常運転と認定しない。既存PR71の同じブランチへ`race_ai/repeated_cycle.py`および既存2テストファイルだけを修正、公式GET総240回・1巡45回・最大24巡・65分、停止したセッションの上限移行による再開を防ぐ制御を復元。以前取得した実行ソースへの同じ製品コード差分で関連80テストPASS、さらに現HEADとのテスト差分整合を修正し同じPRへ適用。正確な修正HEADのCIではAUTORACE既存contract [42169864380](https://github.com/haji84/RACE-AI/actions/runs/42169864380)がcompleted/success、Viewer既存contract [42169864461](https://github.com/haji84/RACE-AI/actions/runs/42169864461)は監査時in_progress。**修正後の新しい実Workerによる240回以内停止・原本読戻しの実証は未達**。旧runはキャンセルしない。安全停止の迂回となる後続を予約しない。

**未達と保全:** 全16系統/4競技の実ライブ全レース、完全P1網羅、永久本人専用保存、学習版の前向き統計的優位性は未完成。今回Driveへの新規原本保存と所有者/非共有の再検証はなし。7日間artifactを永久保管と呼ばず、私有URL/ID・認証情報・元生データは公開記録に含めない。新タスク/PR/workflow/モデル系統/課金/Cloudflare/Vercel/main統合/一般公開/実投票/無検証の本番自動切替なし。

---

<!-- RACEAI_FINAL_REQUEST_VIEW_CI_20261106 -->
# 2026-11-06 14:26 JST｜表示修正の既存CI成功、実映像3条件は未完成

**確認できた完成範囲:** 既存Draft PR #71の表示修正commit [63ecc92](https://github.com/haji84/RACE-AI/commit/63ecc928ed89e87901e4ccaa5184b30518f9c895)に対し、既存Viewer [42167380144](https://github.com/haji84/RACE-AI/actions/runs/42167380144)とAUTORACE [42167380137](https://github.com/haji84/RACE-AI/actions/runs/42167380137)はcompleted/success。GitHub側の全Python1853件は140件の明示skipを含み、別の分離映像試験251件はskip0で合格した。これらを重複のない合計や映像精度の証明へ変換しない。実データのChromium390/1440で18表示のTop8・SHA一致、自動予想の認証復帰、1レース×既存5モデルの締切14分53秒前保存は前報の独立証拠どおり。今回の追記は記録だけで、検証済みのソース・テスト・Workflowを変更しない。この記録コミット自身のChecksは別に確認する。

**未完成の範囲:** 識別は旧AI目視参照で最終出力0/10、有効位置0/582要求セル、動画特徴を使った締切前予想と将来公式結果の比較0件。現方式の読取・追跡も受入を満たしておらず、独立した正解・水面/時計/強さ参照と、解析可能な現行展示映像も不足している。6艇識別、ターン・出足・行き足・伸びの強さ、動画による改善を完成扱いにしない。実機Safariも未検証。

**追加素材の探索:** Commonsへの追加1要求は05:20:46 UTCにHTTP403で停止し、以降のCommons要求・新動画取得・推論は0。先行429の待機根拠を確認せず要求した判断誤りも私有受領証に記録した。既存cacheで確認した10検索・65ファイルは限定範囲で、他の利用可能な映像が存在しないとは断定しない。現行環境のネットワーク設定は観測上unrestricted/enforcedで、今回設定を変更・公開していない。403の原因を環境allowlist不足と決め付けていない。

予想Worker42164651846と映像intakeを保持し、初回DBのSHAは不変。新PR・新Workflow・新予想系統・追加課金、main統合・一般公開・実投票・本番モデル切替なし。詳細は[続行証拠](evidence/2026-11-06/real-video-validation/continuation.json)と各時点の記録に残す。

---

<!-- RACEAI_FORECAST_INDEPENDENT_SAVE_20261106_1406 -->
# 2026-11-06 14:15 JST｜締切14分53秒前の自動保存とスマホ・PCの原本表示を確認

**自動生成・独立保存の新しい実証:** 認証復帰後の既存workflow405276784/run [42164651846](https://github.com/haji84/RACE-AI/actions/runs/42164651846)の第3巡で、1レース×適用可能な既存5モデルの展示後P1予想を自動保存した。P1 artifact `13479011897`のGitHubサーバー作成時刻04:59:07 UTCをレース締切と照合し、全5件が**893秒＝14分53秒前**だったことを別担当が確認した。同じ対象の学習シャドー2件は研究用として別計上する。指定した締切15〜10分前の保存を、この1レースで確認できた。全国全レースの保存達成や実際の投票を意味しない。この5件の公式結果はまだ未確定である。

**原本を保持した照合:** 別の結果artifact `13478907182`は04:59:16 UTC作成。両ZIPのAPI digestと実バイトSHA、全ZIP CRC、結果ZIPに埋め込まれたP1原本との同一性を検査した。初回P0 ZIPの既存SHAと312件すべての予想SHA・Top8も不変で、再生成・上書きしていない。独立確認の匿名化した受領証SHAと原本ZIPのSHAは[続行証拠](evidence/2026-11-06/real-video-validation/continuation.json)へ記録した。買い目本文・生JSON・鍵・私有原映像は公開していない。

**最新artifact時点の件数と学習:** その結果artifactは通常予想527件（採点済307・未採点220）と学習シャドー52件、計579件を含む。これは検証したGitHub artifactの時点の集計で、後のローカル画面600件とは観測時点・証拠を区別する。通常特徴を使う既存モデルの未来paired比較は44モデル別行・22種類のレースで、元モデル15的中・学習版15的中。現時点で的中の増加はなく、改善を実証したとは扱わない。上記の新しい5件の結果未確定と、この累計比較を混同しない。いずれも動画特徴による比較ではない。

**表示遅延の修正:** ローカルstatusが同じ原本検証と艇文脈の付与を繰り返していたため、1要求につき新鮮な原本を一度検証・付与するよう修正した。要求をまたいだcacheは使わず、次の要求で原本/文脈の更新・改竄を確認する。日付跨ぎと競技/空データの扱いも検査し、関連62件がPASS/skip0（40.581秒）。ただし自動運転中に入力文脈が82→89件へ進んだため、同一入力の修正後profileは実行せず、速度倍率を主張しない。独立レビューは合格し、別担当が追加4件PASS/skip0（0.155秒）を確認した。05:08:14 UTCにローカル監視だけを正常終了し、同じ保存先・loopbackポート8765・既存GitHub認証で修正を読み直した。監視PIDは400731→406374。元のcheckpointを私有に排他的保存し、401復帰flagを再適用せず、待機・復帰履歴・intentをリセットしていない。遠隔の自動予想run42164651846は実行中のまま、映像intake271439・初回DBも保持した。05:08:53 UTCのローカルstatus 1要求はHTTP200・6.750秒で応答し、`RUNNING / continuous=true`、同じrun42164651846、取得/巡回/終了時刻の人工上限なしを確認した。実行中runの計数は`ACTIVE_RUN_UNVERIFIED`・nullのままで、過去の計数を現runへ流用していない。その時点の画面用保存件数は600件だが、これはローカル観測のみで、前述の独立確認したartifact579件とは時点・証拠を区別する。単発の応答時間を修正前後の速度倍率や応答保証に読み替えない。修正後の実ブラウザ確認は次段落の範囲で合格した。最終コードの既存PRへのpush後CIは、この記録時点では未開始である。

**スマホ・PCの実操作確認:** 05:09:21〜05:10:11 UTCに、実際の私有保存データをChromiumの幅390/1440で読み取り専用操作し、両方でP0=156R/312件、P1表示=156R/288件、合計600件を確認した。各幅でP0の2版・P1の7版、計18表示の順序付きTop8と全SHAがAPI原本と一致し、再GETでもstage応答バイトは不変。合計24 GETのみで、POST・外部/競技ソース/予想生成要求0、ページ例外0、横はみ出し0。18枚の画面証拠は私有に保存し、390のP1詳細と1440のホームは目視でも確認した。statusはHTTP200で2.3922秒/2.8486秒だったが、同一入力の速度比較や応答保証ではない。実機Safari、元の8参考画像との今回の全面比較、映像/予想精度の検証はこのブラウザ試験に含まない。未検証項目は保守的な状態表示を保持し、偽の確率を表示していない。

**残る実映像の完成条件:** 最終番号識別0/10、6艇×97標本の要求582セル中有効位置0、動画特徴による締切前予想と将来公式結果の比較0件は変わらない。6艇の継続追跡、校正したターン・出足・行き足・伸びの強さ評価、動画特徴による改善はいずれも未完成。通常特徴の自動予想保存と動画評価の合格を区別し、98%の的中、未検証の強さ・確率・回収率を表示しない。既存予想原本・自動運転を保持し、main統合・一般公開・投票・本番モデル切替・新PR/サービス/課金は行っていない。

---

<!-- RACEAI_VIDEO_AUTH_RECONNECTED_20261106 -->
# 2026-11-06 13:54 JST｜GitHub認証待ちを修復、既存自動Worker再開・1848件試験と8075675のCI合格

**復帰処理を実装・適用:** 既存Draft PR #71の同じbranchへ[8075675](https://github.com/haji84/RACE-AI/commit/8075675482a80599795a4e5150c734777056a18b)をpushした。信頼されたローカルCLIから、元checkpointの実バイトSHAを指定した場合だけ、同じ既存GitHub認証・repository・workflow・branchと認証済み最終checkpointを正規APIで確認する。排他lockと前後のファイル/時計を検査し、対象をGitHub APIの401待機に限定した。元401・元ファイルSHA・確認したsource-control SHAを監査記録へ残して復帰する。403・429・競技サイトの待機・真正性/原本不整合、未完の取引・計数・履歴は保持する。HTTP画面からの権限自己申告や別認証経路は追加していない。

**今回の実適用:** 04:45:56 UTCの正規認証/同一workflow/最終原本確認は成功し、その時点で同workflowの実行中・待機中は0、元checkpointは不変だった。元ファイルを私有に排他的保存した後、04:46:32 UTCに401待機で止まっていたローカル監視だけを正常終了し、同じ保存先・loopbackポート8765・既存認証で再起動した。監視PIDは157669→400731、映像intake PID271439は停止/再起動せず、初回DBのSHAも不変。04:46:41 UTCに専用復帰処理が監査受領証1件を保存し、`api_wait`を解除した。復帰直後のcheckpointは、元の全状態へ待機解除と受領証だけを加えた再構成SHAと一致する。その後の通常巡回による状態更新とは区別する。

**後継Workerを確認:** 起動直後のローカル表示は最終原本の取得中で`NOT_STARTED`だったが、その後、既存監視が通常の原本検査と引継ぎを実行した。同じworkflow405276784の後継run [42164651846](https://github.com/haji84/RACE-AI/actions/runs/42164651846)が04:48:20 UTCに作成され、GitHub上で`in_progress`を確認した。固定HEADは`70514b3076614ea94b10e6595a9df9f5e858b320`で、復帰修正8075675を祖先に含む。手動dispatch・trigger・rerun・cancelはしていない。これは自動Workerの再開確認であり、新予想の保存・全レース網羅・締切前保存完了の認定ではない。最終完了runのGET427、累積3547、完了巡287は過去runの認証済みcounterとして区別する。以下の「再起動なし」「認証復帰は未適用」は、それぞれの過去時点の記録である。

**追加検証:** 復帰の単体/境界40件PASS（2.077秒）、監視・HTTPサーバー・既存巡回・ローカル自動予想の統合125件PASS/skip0（9.218秒）、CLI19件PASS（5.436秒、追加3件を含む）。独立レビューは合格し、保存失敗時にメモリ内の401まで解除される欠陥を修正した。並行統合した保存Pages/venueのPython15件もPASS（3.454秒）、実WebCryptoのブラウザ試験は7ページ・reload/link・4保存版・過去日・誤鍵/改竄/鍵なし拒否を確認した。これらはソフトウェアの確認で、実機Safariや実予想精度の実証ではない。

**全件試験とCI:** 復帰修正8075675を対象にローカル全Python **1848件PASS/skip0（442.671秒）**、実プロセスexit 0を確認した。既存Viewer CI run [42164381973](https://github.com/haji84/RACE-AI/actions/runs/42164381973)も、同じ8075675でcompleted/successを04:52:15 UTCに確認した。11job成功・2jobは明示skipで、実動画暗号取込と別runnerでの本番原本復元がskipされたことを成功に読み替えない。全件試験の開始後に統合した公式K特殊結果の欠損時刻処理は別途20件PASS/skip0（1.651秒）を確認した。1848件の結果は8075675のコード範囲、追加20件はその後の対象差分に限定し、最新merge HEAD全体の全件再試験済みとは主張しない。最新mergeのCIは別途確認中。ローカルstatus応答の遅延も調査中で、現在の稼働確認はGitHub側の実runを根拠にしている。

**別の公式映像経路も確認:** 公式場一覧から通常リンクで辿った戸田の公式YouTubeと平和島の展示リプレイを確認した。戸田は通常ブラウザの`ERR_TUNNEL_CONNECTION_FAILED`で停止し、HTTP401/403を観測したとは扱わない。平和島の公開ページはHTTP200だったが、既に停止対象のプレーヤー提供元へ至る境界で止め、提供元/再生APIには要求していない。新たな再生可能clip・フレームの取得は0で、全場の映像が利用不能とは推定しない。拒否済み資源の再試行、別session/経路・資格情報による迂回はしていない。

**映像3条件:** 最終番号識別0/10、有効位置0/582要求セル、動画特徴を使う締切前予想と将来公式結果の比較0件は変わらない。6艇追跡・強さ評価・前向き精度改善の完成とは扱わず、未検証の確率・強さ・98%の的中を表示しない。既存予想・映像・正解参照を保全し、main統合・一般公開・投票・本番モデル切替・新PR/サービス/課金は実施していない。

---

<!-- RACEAI_VIDEO_AUTOMATION_AUTH_WAIT_20261106 -->
# 2026-11-06 13:38 JST｜自動監視のGitHub認証待ちを確認、実映像の3条件は未達

**現在の運転状態:** 04:19 UTC（13:19 JST）のローカル表示は`SOURCE_WAIT`。`continuous=true`は継続運転の設定であり、現在の予想Worker稼働の証拠ではない。私有checkpointには02:39:32 UTCのGitHub HTTP 401、`AUTHORIZATION_WAIT / SOURCE_AUTHORIZATION_REQUIRED`が保存され、再試行時刻はない。記録上のrun `42148186039`は02:57:26 UTCにcompleted/successで終了していた。04:21 UTC時点の同じworkflowに実行中・待機中の後継は確認できていない。自動運転が今も稼働しているという以前の時点の記録を、現在へ延長しない。

**正規認証の確認と復帰の区分:** 04:38 UTCに、現在設定済みの同じGitHub CLI認証経路で正規の`gh auth status --hostname github.com`がexit 0・ログイン済みを報告した。これは過去の401の原因特定、保存待機の解除、後継run開始を意味しない。現状コードには認証修復後の専用復帰経路がなく、再起動だけでも待機が残る。復帰処理は準備中で、checkpoint・lock・既存原本を直接書き換えず、別の資格情報・経路による迂回もしていない。この確認時点でプロセス再起動、待機解除、追加trigger/rerun/cancelは未実施。

**保存値と証拠の限界:** 同じローカル観測は156R、保存509モデル・時点件（P0=312、P1=197）、結果観測70件/30R。GitHub最終artifactの512件とは観測対象・時点が異なるため、同一の最新値として混在させない。ローカル件数だけで締切前の独立保存時刻を認定しない。初回DBのSHAは保持し、旧予想を再生成・上書きしていない。

**追加の回帰確認:** 最新の並行26ファイルの統合後、ローカル自動予想・venue履歴・公式結果・状態統合に関する113件がPASS/skip 0（37.361秒）。前報の全1806件PASS/skip 0（389.439秒）は、その26ファイル統合前のコードに対する結果である。件数を合算せず、古い全件試験を最新HEAD全体の合格と扱わない。後続指示の取得・巡回・時間の人工上限なしという契約を維持し、401/403・429/Retry-After・真正性・原本不整合の待機は維持する。

**実映像の未完成条件:** 以前のAI目視参照に対する最終番号識別は0/10、有効位置は6艇×97標本の要求582セル中0で、独立した物理位置の精度率ではない。6艇継続追跡の合格、実測校正・強さ評価、動画特徴を使った締切前予想と将来公式結果の比較（0件）はいずれも未成立。ローカル/CIのソフトウェア試験を識別・強さ・予想精度の実証へ読み替えず、98%の的中や改善を表示しない。詳細な実験結果と過去時点の運転記録は以下に原形を保持する。

---

<!-- RACEAI_VIDEO_FINAL_MEASURED_GAPS_20261106 -->
# 2026-11-06 13:04 JST｜全97標本の映像識別は不合格、原本読戻し・継続運転の回帰を統合

**結論:** 実映像の6艇識別、ターン・出足・行き足・伸びの強さ評価、動画特徴による前向き精度改善は、まだ完成していない。読取・校正・実験モデル入力・暗号保存・復元のコードを実装したことと、実際の受入を分ける。未検証の強さ・確率・回収率を作って表示せず、本番モデルを切り替えていない。

**全動画の実経路:** 既存の許諾済みCommons実動画を、現在のCRNN＋分割YOLOX＋識別継続処理で1回だけ実行した。775フレームを全部復号し、97標本で本物の検出・カメラ・読取・識別を実行、観測所要708.03秒。先の28フレームだけの疎な検出とは異なる。原映像・全画素SHA/PTS・実ファクトリ返値・モデル/ソースSHAの前後一致を確認し、原出力凍結後に別担当が再採点した。以前使った資料の再利用developmentで、新しい未知映像の合格とは扱わない。参照は少数のAI目視で、人の認証済み正解ではない。

| 確認対象 | 実測と区分 |
| --- | --- |
| 番号識別 | 参照9フレーム中6が標本一致、3は未抽出。可読10例に最終正解出力0、出力自体0なのでprecisionはnull |
| 6艇追跡 | 最終番号領域0。6艇すべて可読な参照の分母0、正解率はnull |
| 位置 | 要求した6艇×97標本の582セル中、有効0。物理位置の独立した精度評価ではない |
| 生の読取 | 109呼出し全部COMPLETE、期限超過/例外/省略0。局在した数字34views＝同一crop内24component＋正規化重複10。艇全体だけの診断1viewを除外 |
| 実際の番号候補 | 読取器の採用仮説20件/16標本。正解と認定した20件ではない。曖昧2、利用可能な数字なし87 |
| カメラ | 採用12、背景不足76、fit拒否8、初期化1。論理識別区間は全97で0、hard cut/gap0 |
| 生の艇領域 | 参照18に一致9、誤検出3、取りこぼし9。部分注釈の未対応1を採点から除外 |
| 強さ・精度改善 | 独立した水面/時計/接地点/強さの実参照0、動画特徴を使う締切前予想0、未来公式結果との比較0 |

**原因の区分:** 採用された数字仮説20件は全部、カメラ背景不足の場面だった。同じ論理区間で数字が連続して現れる最大数は2で、幾何対応を含む追跡成功数ではない。重なりflagは43標本。従来の区間リセットだけを今回の0件の原因とは言えず、読取の断続、艇領域の重なり、背景不足を別に記録した。3観測・曖昧さ・重なり・時刻・原本検査を弱めて番号を埋めていない。

**採用しなかった変更:** 公式Apache-2.0のPP-OCRv3英語DB検出器を、同じ12個の予測艇crop、同じCRNN/全37文字で既存方式と比較。新方式は7文字領域/数字位置1対10、生の1〜6候補0。旧方式は数字位置8対10・正しいraw10views＝6箇所だが、時系列識別の成功ではなく、1cropのsoft期限超過もあった。新方式は不採用。さらに、実検出キャッシュと同じ画像でカメラだけを再計算した。既定ROIは97件全部で元のstatus/H/品質と一致し、全面ROIは採用12→15・fit拒否8→5。しかし背景不足76件はフレーム集合ごと同じで、主な不足を解消しなかった。新ROIも採用せず、追加探索を停止した。後者はDNN/読取の再実行0で、独立した岸側参照や識別・強さの新評価ではない。

**原本接続の修正:** 並行作業の原本を保持するcontribution統合、受領履歴、保存済み予想を再推論せず読む画面を取り込んだ。こちらの修正は、両暗号の認証・production監査・現行状態の独立読戻し後だけ原本包含を確認する。同等以上の原本を含む場合はcheckpointを二重発行しない。実入力では一部原本が現行状態に含まれず、4edd3d4の検査は正しく`STATE_REGRESSION_FILES`で拒否した。以前の「同じデータを受領済み」という推定を訂正する。関数の拒否は保持し、その包含比較だけの専用型をCLIが`HOLD_TRANSFER_REBASE_REQUIRED`・`transfer_imported=false`（未取り込み）・encrypted=falseとして記録する。破損・鍵違い・未来/不正データ・contribution不整合・未知エラーはfatalのまま。HOLDは取り込み成功ではなく、現行/未取込の原本・cipher・refsを変更しない。

**連続運転の指示:** このチャットの後続指示「取得上限なし」「その上限や停止もなし」「開発中も自動運転を止めない」を優先する。並行commit8ddde85で戻された240 GET、45 GET/巡、24巡、65分の人工上限だけを、既に認可された無上限へ戻した。他の原本・履歴・表示修正は保持した。旧45 GET停止の移行も、計数/ハッシュ/受領証/待機を保存する。403・429/Retry-After・真正性/原本不整合は既存の保護を維持する。実行中Workerや私有実セッションを書き換えず、保護PIDの停止/再起動、公式workflowの追加trigger/rerun/cancelはしていない。稼働済みrunは固定HEADを使い、コード反映は通常の引継ぎで行う。

**検証:** 上限回帰57件PASS/skip0。型限定HOLDの単独回帰30件PASS/skip0、独立レビュー合格。並行contribution/受領履歴との統合レビューも合格。並行原本contribution・受領履歴・保存ビュー・上限回帰を統合したローカルPython全1806件PASS/skip0（389.439秒）。保存原本のブラウザ試験も、起動時自動読込・過去日保持・4保存版Top8一致・再予想要求なしを確認した。既存CIのexact run/HEADと最終受領記録は下の[続行証拠](evidence/2026-11-06/real-video-validation/continuation.json)およびGitHub既存チェックへ記録する。一般Pythonと映像専用・ブラウザの重複件数を合算しない。

**未完成・外部条件:** 現方式の識別性能の改良と十分な独立ラベル、正規の現行展示映像、実測校正・強さの参照、締切前に独立保存した比較予想と後日の公式結果が必要。確認した福岡当日LIVEの403/P01002と既知の拒否映像は再試行/迂回しない。これを全場の映像が不可とは拡張しない。現行展示の映像原本から予想モデルへの実接続、実機Safari、実動画による前向き改善は未実証。新PR・新workflow・新予想family・追加課金・main統合・一般公開・投票・本番モデル切替なし。生映像・GT・鍵・私有の買い目本文をGitへ追加せず、私有原本を公開配布していない。

---

<!-- RACEAI_AUTOMATION_20261106_1305_PARENT_AUDIT_CI_FIX -->
# 2026-11-06 13:05 JST｜学習元19 artifactを独立照合、既存GET上限のCI回帰不一致を修正

**実行状態・HEAD:** 既存Draft PR #71 / workflow 405276784、今回の監査直前HEAD `3a2f6e8fbe142665bc4ca53ef7f911316df45f77`。GitHub Actions repository直近100 runに同workflowの in_progress/queued/pending/waiting はなく、最新race worker `42148186039` は2026-11-06 11:57:26 JST に completed/success。ただし実行SHA `8494b85923e10d57f9c6f23a28f3aa38bfc33797` は**240 GET修正前**。旧runの実数427/240で上限187件超過し、successを安全運転の実証に換算しない。現HEADによる新しい405276784実runはまだなし。旧超過のrerun/新trigger追加なし。

**初回原本と最新完了巡:** 同run第24巡のP1 ZIP artifact `13472992546`（SHA256 `1020bca258f9493a4b79b379ea6cb0bd6ad40da59c559bd56de2547db00e99b2`）、結果ZIP `13473452006`（`f76fefdc554d005ef0d4a3a6ca8ed1a8898a718f525e8285f79843563184dda4`）、継続ZIP `13473566824`（`fb85292c00ba9563a2a3e8b4877a3caf2c8916e89c50160c72f38cf06de2efc5`）を再取得して各実バイトSHA/API digest一致・ZIP CRC正常を検証。結果ZIP `status.round_no=24`、更新11:57:11 JST、継続`completed_round=24`。第24巡のP1が結果ZIPの埋込み原本と同一。初回P0 ZIP artifact `13428142302`（SHA `6f900ac94d433aa11bf5b73a70ae68cd6ecf8849000fbb0726b3abd7769e82fc`）は同日初回索引と埋込みP0に一致、312件を再生成・上書きせず。

**新規の独立学習元監査（前報からの進展）:** 11/6の最終結果`learned_shadow_comparison.per_forecast`に存在する46研究予想（2既存観測相性系統）の参照先を重複排除し、**19件すべての元GitHub結果artifact ZIPを個別再ダウンロード**した。19件すべてAPI digest＝実ZIP SHA256、CRC異常なし。各ZIP内`trained_observed_models.json.training_sha256`が内部statusの学習版SHAに一致し、参照する46行も全件一致。46行すべてで「学習元artifactのGitHubサーバー作成時刻 < 当該基準予想の入力as_of < シャドー保存時刻 < レース締切」、基準8点との対応、学習/検証race_idの非重複を確認。内訳は結果確定の同条件比較28モデル別行（14種類のレース）と結果待ち18行。これは**参照・時系列・原本整合の独立監査合格**であり、係数推定全計算の再現、入力の第三者証明、実際の性能向上の認定ではない。

**固定時点の成果（新たな予想増分ではない）:** 最終ZIPは対象156R、P0=312・P1=200（基準512モデル別件）、通常採点207モデル/時点行（HIT95/MISS112）、仮想購入8点各100円の条件付き損益+35,850円／回収率121.65%。31種類の通常確定レースをTRAIN24/未使用検証7とし、学習研究用46予想、通常paired28行。観測相性14比較は元/学習版とも6的中、ST重視14比較は元/学習版とも7的中、ST重視の学習版払戻は元より4,450円少ない。全国156R全体の的中率・回収率や実購入の成績に拡張しない。coverage_auditは締切済42R・未来114R、P1未保存7R×5系統=35行で、展示が当時公開済みかは未証明。

**GET上限テストの修復・CI:** 旧HEADのViewer run `42158798013` は、旧仕様 `source_limit is None` を要求する単一回帰テストが240の新契約と矛盾して失敗。他は合格。既存PR branch上でその期待値だけを240へ変更したtest-only commit `3a2f6e8fbe142665bc4ca53ef7f911316df45f77`。修正後の同HEAD Viewer `42159523879` は2026-11-06 13:02:30 JSTにcompleted/success、全job successまたは明示skip。既存workflow設定・モデル・原本は変更なし。これで**CI上の回帰整合は成立**したが、405276784での実際の240 GET以内停止・24巡/65分遵守は引き続き**未実証**。

**保存境界・禁止事項:** 非公開保管先は本人所有・非共有をメタデータ確認したが、今回のGitHub元ZIPからDriveへの保存はconnector egress拒否で不成立、新規Drive保存0。無期限保管・全学習元の私有保全は未完成。取得上限を回避する追加起動、旧run rerun、既存workflow/schedule/タスク・PR追加、main統合、一般公開、課金、実投票、旧予想改変、研究版の本番自動採用はなし。全16系統・全4競技・無欠落の未来直前予想・学習版の優越性は未達。

---

<!-- RACEAI_AUTOMATION_20261106_1248_SAFETY_AND_CYCLE24 -->
# 2026-11-06 12:48 JST｜第24巡原本の独立照合、上限超過の修正を既存PRへ適用

**第24巡実原本:** 既存workflow405276784、run [42148186039](https://github.com/haji84/RACE-AI/actions/runs/42148186039) はcompleted/success（GitHub最終更新11:57:26 JST）。全50 artifact一覧から第24巡P1原本ZIP `13472992546` / `1020bca258f9493a4b79b379ea6cb0bd6ad40da59c559bd56de2547db00e99b2`、結果ZIP `13473452006` / `f76fefdc554d005ef0d4a3a6ca8ed1a8898a718f525e8285f79843563184dda4`、continuity ZIP `13473566824` / `fb85292c00ba9563a2a3e8b4877a3caf2c8916e89c50160c72f38cf06de2efc5` を別取得。3件ともGitHub API digestと実バイトSHA256一致、ZIP CRC異常なし。内部`status.round_no=24`、`updated_at=11:57:11 JST`、継続`completed_round=24`、原本P0内包SHA `6f900ac94d433aa11bf5b73a70ae68cd6ecf8849000fbb0726b3abd7769e82fc` を再確認。今回は学習元artifact全件の独立再取得と新たな公式プロバイダ照合までは未実施。

**11/6の確認済み保存値:** 対象156R、P0=312、展示後P1=200（前回120から+80、40R×5）、基準計512（+80、CSVのrace/phase/model一意512）。公式通常結果の保存済み採点207モデル・時点行（前回105から+102）、HIT95（+44）/MISS112（+58）。7モデル/時点の各8点100円仮購入で投入165,600円、受取201,450円、差引+35,850円、回収率121.65%。正式成績は採点済207モデル・時点行の条件付きであり、全国156Rの的中率でも実投票でもない。42締切済R・114未来R、通常確定31R、P1五系統完備35R、未保存P1=35モデル別行をcoverage_auditに残す。欠測が公開済展示の取りこぼしかは未検証。

**係数研究:** 通常確定一意31R（学習24/未使用検証7）で2つの既存観測相性系統に`FITTED_SHADOW_ONLY`。LEARNED_SHADOW保存46モデル別行（前回14から+32）。同条件で公式結果が保存されたpaired=28行（14種類のレース）。観測相性は基準/学習版とも6/14的中、ST重視相性は両者7/14的中だが、ST重視の学習版仮受取22,170円、基準26,620円で-4,450円。学習成功と未来の精度改善を混同しない。親学習artifact全件独立再照合が未完了のため、本番採用・優位性認定なし。

**安全不一致の修正:** この旧runの`repeat-session.json.requests_used=427`（指定240を187超過）、旧コード`SOURCE_LIMIT=None`。既存PR #71の同じbranchへコードと2既存テストのみcommit [8ddde850](https://github.com/haji84/RACE-AI/commit/8ddde8509ae7c308927d0a984b4fa9ff30efb453) をfast-forward/expected-head lease成功で適用。`SOURCE_LIMIT=240`、`ROUND_SOURCE_LIMIT=45`、`MAX_ROUNDS=24`、`MAX_SECONDS=65*60`、旧runの停止解除・上限水増し禁止を明示した。元source bundleからpatch適用した同系統のローカル単体50テストPASS。commit 8ddde850自身のViewer CI run42158394123は並行pushでcancelled、**exact-HEAD CI合格も既存workflowでの新上限実運用遵守もまだ未実証**。後続HEAD 8535ef81のViewer CIが進行中で、sourceファイルの新blob SHA `48287a965ab8c6e12ec2b1afed44c049ab47313a` は保持確認。

**継続判定:** 12:48時点で確認可能なrepository最新Actions一覧内には405276784のrun42148186039より新しい実行がない。最終runが超過427 GETで安全正常とは認められないため、旧run rerun・上限回避目的の後続トリガーは追加しない。既存毎時スケジュール、concurrency、他workflow/タスク、モデル、原本、main、公開、課金、投票は不変更。Driveの新規保存・owner/share再確認は今回未実施。GitHub artifact 7日保持のままで期限なし私有保存は未完成。

---

<!-- RACEAI_AUTOMATION_20261106_1134_CYCLE24 -->
# 2026-11-06 11:34 JST｜既存run第24巡の完走と正式採点増分、公式GET417回の超過確認

**独立確認:** PR #71（Draft）の監査時HEAD `a0c2479f4ffec04e05ec62a145c5f7a658815a4d`、既存workflow `405276784` の完了run `42142323217` の1ジョブはcompleted/success。全artifact50件から最終第24巡を選び、結果・PDCA元ZIP `13471056161`（実SHA256 `9645cbe76d1ba655c0f70755220e2dec5f7558e1f247565fc89cfd50b2acb28d`）、P1元ZIP `13469979920`（`7ad8436a60de8a3c563a10552c25d39ce0bfd6891fb73c91d92e7ae4bd286ff3`）、最終継続ZIP `13471395500`（`075c97b9dce072a562c5c897348dd01c4cb7182dbbd5cb5b4d837562e8e1bd92`）を別取得。3件ともGitHub API digestと実ZIP SHA256一致、CRC異常なし。結果ZIP内P1は別取得元ZIPと完全一致、内包P0の実ZIP SHA `6f900ac94d433aa11bf5b73a70ae68cd6ecf8849000fbb0726b3abd7769e82fc` も既存初回P0と一致。継続JSONは`completed_round=24/prepared_round=null`、24巡すべてにreadback receiptがある。

**確定した増分:** 11/6対象13場156R。基準予想はP0=312件不変、P1=120件（10:51既報105件から+15）で計432件。CSV432行にrace_id/phase/modelの重複0。通常確定は一意15R（+4）、モデル別正式採点105件（+28）、的中51（+14）・不的中54（+14）。全7モデル/時点を1モデル8点×100円で仮想購入した場合のみ投入84,000円・受取62,910円・収支-21,090円・回収率74.89%。同じ15Rを7系統で採点した数字で、全国156Rの実成績や実投票ではない。締切済24R、結果待ち7R、異常2R。5系統P1が欠けた締切済3R×5=15モデル別件はcoverage_auditから除外せず、展示公開済みの推測はしない。結果観測revisionは46件。

**学習研究:** `automatic_learning.state=FITTED_SHADOW_ONLY`、一意の通常確定15R、TRAIN12/VALIDATION3で既存観測相性2系統の係数候補を作成。LEARNED_SHADOW保存14モデル別件（既報8件から+6）だが、正式な未来ペア結果比較はまだ0件。過去holdoutと未来優位性を混同しない。基準5系統・元買い目は変更なし、モデルの本番自動切替なし。今回全14シャドーそれぞれの元学習artifactを独立再取得できたと主張しない。

**最重要の未達:** 実ZIPの`repeat-session.json.requests_used=417`、内訳forecast333/result84。指定1セッション240 GETを**177回超過**。現行`race_ai/repeated_cycle.py`は`SOURCE_LIMIT=None`、`MAX_ROUNDS=None`、`MAX_SECONDS=None`のまま。正常終了は安全上限遵守の証拠ではない。保存済みの過去原本は書き換えない。ローカル限定の安全上限候補（240 GET/24巡/65分、1巡45回）と対応回帰テストは既存workflow掲載の175テストPASSだが、**GitHub PRへは未適用・CI未検証**。再実行・後続trigger・上限回避・稼働中workerキャンセルは実施せず、現時点のqueued/pending/waitingの全件一覧は取得できていないため後続ゼロと断定しない。修正の採用には最新HEADとの競合照合、元原本の保全、既存CIが必要。Drive追加保存の今回増分は実施なし。新workflow・新PR・別モデル系統・追加課金・公開・main統合・投票・本番自動採用は行っていない。

---

<!-- RACEAI_VIDEO_COMPLETION_CONTINUATION_20261106 -->
# 2026-11-06 10:54 JST｜映像識別・校正・モデル接続を続行、実映像の受入は不合格

**完成区分:** 任意の分割検出、生CTC読取、カメラ補正と識別継続の分離、独立ランドマーク/時計による物理文脈、既存2モデルへの入力・学習・再演、暗号化した独立保存と既存自動取込の発行journalを実装した。**実レースの6艇識別、ターン・出足・行き足・伸びの強さ評価、動画特徴による精度改善は未完成。** コード試験の成功を実測精度の改善として扱わない。既存Draft PR #71、既存workflow、既存モデルfamilyを継続し、元のTesseract既定経路・予想原本・本番モデルを保全している。

**実測:** 新たに別日の戸田の過去資料2本を取得し、出力を見る前にAI目視参照・フレーム/PTS/画素SHA・評価条件を凍結した。第三者アーカイブは権利未確認のため私有評価のみ、学習/配布には未使用。参照は人による検証済み正解ではない。各ケースは4区間の28フレームだけで識別を実行し、12フレームを採点、16をwarmupとした。残りはNOT_EVALUATEDであり、全動画の検出やカメラmaskと等価とは主張しない。

| 映像・固定方式 | 可読番号への正解出力 | 物理的な艇領域の一致 | 誤検出領域 |
| --- | ---: | ---: | ---: |
| 2022-10-15・YOLOX/Tesseract全画面 | 0/15 | 20/44 | 2 |
| 同・YOLOX/Tesseract分割 | 0/15 | 37/44 | 12 |
| 同・YOLOX/生CRNN分割 | 0/15 | 37/44 | 12 |
| 同・NanoDet/Tesseract全画面 | 0/15 | 11/44 | 0 |
| 2022-08-19・CRNN/従来リセット対照 | 0/12 | 31/51 | 3 |
| 同・CRNN/新しい一致観測による継続 | 0/12 | 31/51 | 3 |
| 同・私有の画像特徴試作/同じ継続 | 0/12 | 31/51 | 3 |

同じ参照を方式ごとに繰り返しており、方式間の分母を足して標本数を増やさない。8月資料は9網羅/3部分注釈で、未対応10領域を標準scorerが採点対象から除外。既知の非競走艇3観測は全方式で生の船領域として検出され、重複除外後に読取を行ったのは2例。CRNNの局在数字候補は0だが、画像特徴の試作は1例に誤った競走番号候補を出した。最終継続IDの誤付与は全方式0だが、全体の出力も0であり安全性改善の証明にはならない。全方式の有効位置は全6艇とも0。全6艇の番号を読める参照フレームは0なので、全6艇の正解率はnull。出力が0の方式の番号precisionもnullで、誤番号0を高精度としない。水面/時計/接地点/強さの実正解、映像を使った締切前予想、後日の公式結果との比較はすべて0、改善実証なし。

**修正内容:** 付番できない・曖昧な艇へ古いIDを移す不具合を修正。背景特徴不足でカメラ区間が毎回変わっても、実験経路では各フレームの新しい数字一致がある場合だけ識別の論理区間を継続できる。計測の実カメラ区間と欠測は保持する。メートル文脈では生画素座標と補正後座標を区別し、全使用フレームの独立検算と旋回半径の誤差伝播を検査する。公式4特徴ID/既存2モデルfamilyは維持し、方向係数や未校正確率を作らない。

**独立保存:** 私有の元映像/報告/証拠/校正文脈を再検証してAES-256-GCMで暗号化し、既存Viewer workflowのdispatch専用jobへ渡す経路を実装。GitHub artifactは暗号文だけを保持する。既存intakeの信頼するPython呼出元から、元入力を変えず発行できる。STARTEDを呼出前に追記し、結果不明や中断を盲目的に再送しない。dispatch受付と独立artifact受領を区別し、既存cycleは実APIのHEAD/時刻/ZIPdigestを確認する。未接続の鍵・送信関数・platform readinessはHOLD、CLI/JSONから権限を作らない。実文脈の公開/受領、本番採用、稼働中プロセスの更新を済んだとは主張しない。11:00 JSTに実データ/鍵を含まない無効入力を1回だけdispatchし、[run42147537641](https://github.com/haji84/RACE-AI/actions/runs/42147537641)が同じHEAD27c1981で起動・成功。受信jobだけ実行、他jobはskip、artifact0。実際は鍵の検査が先に`HOLD_OWNER_STATE_KEY_REQUIRED`を返したため、プラットフォーム上の起動可否と鍵未接続を確認しただけで、実runnerの復号/文脈受領や無効本文の検査成功は認定しない。鍵の生成/設定/上書きや送信の再試行は行っていない。その後の並行更新2318cacでは、既存Actions鍵から公開受信鍵だけを出すPDCA用jobが追加され、run42148288953のartifact13470563954を読取専用で照合し`OWNER_RECIPIENT_READY`を確認した。従って11:00時点のHOLDを現在のGitHub鍵不在とは断定しない。新しい公開受信鍵の準備は動画の受領成功ではなく、この動画senderとの互換・ローカル側の認可済み暗号接続は未実証。root鍵の取出し/複製や別暗号方式の重複開発はしていない。

**却下した試作:** 旧来の許諾済み画像だけで学習した私有の画像特徴識別はdevelopmentで誤検出があり、新しい8月映像でも継続ID0。Git/本番へ採用していない。さらに同じ固定YOLOXのPERSONクラスで服色を読む前段を調べたが、全画面7候補はすべて岸の人物、分割18候補のうち16は岸/背景、選手領域は2だけだった。6艇が写る既存写真でもPERSON検出0で、色判定の前に中止した。色という情報自体を否定する結果ではなく、この局所検出器では不足している。

**検証・統合:** OpenCV/暗号ライブラリを含むローカルPython全1727件PASS、skip0、266.454秒（映像実装HEAD27c1981）。並行更新2318cacのrecipient/handoff差分は別に16件PASS、skip0、8.505秒。スコープ別レビュー・契約横断レビュー・公開転記レビューは合格。並行作業のPDCA保存/復元、大容量checkpoint修正、署名済みHTTPS apt設定、公開受信鍵、SHAのみの研究証跡と既存worker後継markerを保持した。

**11:12 JSTのCI完了:** PR run HEAD `2318cac2a411d7050e0abf0a5c849778b1f99193`で[Viewer42148288953](https://github.com/haji84/RACE-AI/actions/runs/42148288953)と[AUTORACE42148288971](https://github.com/haji84/RACE-AI/actions/runs/42148288971)がSUCCESS。一般Python1735件/skip140、映像専用251件/skip0、UI契約48件、動画UI12件、ブラウザ39チェック成功。重複を含むためテスト数を合算しない。CI checkoutはPR merge `e536bc389f17af6c55147fd2c822394c78d29c23`で、本件ソースの実SHAはbranchと一致。ブラウザは320/390/1440/1920pxで7ページと自動反映等を操作し、errors0/source GET0、合成PNG60枚を保存。元ZIPを独立取得してAPI digest/実SHA一致・CRC異常0、390詳細/1440ホームを目視確認した。今回の元8枚の再対照と実機Safariは未実施。27c1981の旧Viewer CIは映像試験成功後のブラウザ中に並行pushでcancelされており、成功件数へ混ぜない。詳細は[続行証拠](evidence/2026-11-06/real-video-validation/continuation.json)と[実行ガイド](BOAT_VIDEO_MEASUREMENTS.md)。この追記は記録のみで、記録後HEADのCI結果はGitHubの既存チェックと私有受領記録で確認する。

**継続運転・外部条件:** 10:54 JSTのローカル状態はRUNNING/continuous=true、425モデル別予想（P0=312/P1=113）、156R。これはAPI表示の観測で、全予想の独立保存時計や画面到達時刻の再認証ではない。既存run42142323217を継続し、こちらから予想workflowをtrigger/rerun/cancelしていない。保護PID157669/271439の開始時刻と元DB SHA `c40bead05533ace426188ea8a111b1e4a4a639283f576972ba276e14a3e8ff1a` は不変。新コードのための再起動なし。

福岡の当日LIVEを通常の公式導線で10:23 JSTに確認したが403/P01002「視聴は許可されていません」で停止。唐津と既に拒否された過去映像も再試行/迂回していない。認可済みの現行映像、十分な独立識別ラベル、実測の水面/時計/接地点、強さの正解、締切前に独立保存した比較予想と未来の公式結果が必要。実機Safariも未実施。追加課金・新PR・新workflow・main統合・一般公開・投票・本番モデル切替は行っていない。

---

<!-- RACEAI_AUTOMATION_20261106_1051_CYCLE17 -->
# 2026-11-06 10:51 JST｜ボート第17巡の実原本照合・学習候補の未来初保存・10原本を非公開保全

**確認対象:** 既存Draft PR #71、workflow `405276784`。確認時GitHub HEAD `80654331d1c56385243d11ef4f8ffcc2efb3ba30`、現run [42142323217](https://github.com/haji84/RACE-AI/actions/runs/42142323217) は`in_progress`、同workflowのqueued/pending/waiting=0。前run [42134238827](https://github.com/haji84/RACE-AI/actions/runs/42134238827) は`completed/success`。その最終継続ZIP `13468605667` はAPI digestと実ZIP SHA `18b831f6ad60e52f08e3fdf58868df5a382b013230d6a6513447221bdaf1daad` 一致・CRC正常、completed_round=24、受領24件。現runの第17巡結果ZIP `13469659050`（実SHA `0e62f49e73cd481e83972d728f9a87fbbb14f191afef64ce0bcb219302a0b547`）と対応P1 ZIP `13469738969`（`8a6ad6bf04136ab8c9349c32270e8ccdf4202de12ff58b155fc8241b9aa4f92c`）を独立取得し、両GitHub登録SHA/ZIP CRCと結果ZIP内P1元ZIPの実バイト一致を確認。status.round_no=17、updated_at=2026-11-06T01:51:29.872739Z（10:51:29 JST）。継続はcompleted_round=16/prepared_round=17で、**第17巡は保存・独立取得成功、継続読戻しの最終承認は未完了**。

**11/6の実増分（09:28既報との比較）:** 13場156レースの朝版P0 `312`モデル別件は初回ZIP `13428142302` の実SHAと内部JSON SHAが正本receiptと一致し無変更。展示後P1は25→**105モデル別予想（21レース×5、+80件）**、基準計337→**417件**。CSV417行、race_id/phase/model_idの重複0。公式通常結果は一意11レース、7モデル/時点×11＝**77モデル別採点**（HIT**37**・MISS**40**、既報21採点/13HIT/8MISSから+56行/+24HIT/+32MISS）。8点各100円×全7モデル/時点の研究仮想合算は投入**61,600円**、受取**47,590円**、損益**-14,010円**、回収率**77.26%**。これは11レースを7系統採点した値で、全国156レースの成績でも実投票でもない。締切済19R、未来137R。通常確定11R、結果待ち6R、異常2Rを区別。締切済の展示後5モデル不足は2レース×5＝**10モデル別件**、公式展示が当時公開済みかは未証明。原本を改作して穴埋めしない。

**係数学習と未来シャドーの実差分:** 既存観測相性2系統の `automatic_learning.state=FITTED_SHADOW_ONLY` に初めて到達。通常確定一意11レース、TRAIN9/VALIDATION2を確認。学習済み係数モデルは**2系統**（基準5モデルの係数・式・既存買い目は不変）。研究用 `LEARNED_SHADOW` は**8モデル別件・4未来レース**に保存され、同条件で結果確定のペア比較は**0件**。保存済み最初の2件（同一1レース）は親の独立学習artifact `13469747293` をGitHubから別途取得し、API digest/実ZIP SHA `1f8f6b2f9223ff04be56d3923d1ad846a646e43acb4062f24f6a2547b567d301`・CRC正常、内部training_sha `49edc143925ff2087b60fb7adb48c59e69da3a97e3038b5cec5b43adeef48985` と一致。学習元artifact作成01:38:55Z＜入力as_of01:41:51Z＜締切10:55JST、対象レースは学習/検証IDに含まれないことを検証。他の6シャドーについて全親元を再認証できたとは扱わず、未来での的中率改善・統計的優越・本番自動採用は未達。学習validationはわずか2レースで採用判断できない。

**今回の私有保全:** 指定Google Driveフォルダを直接メタデータ確認し、単独owner権限・shared=false・共有ドライブ外と照合。未保存の元GitHub ZIP **10件**（現run第10巡結果、第11/12巡P1・結果、第17巡P1・結果、前run第24巡P1・結果・最終continuity）を、改変なし新規保存。10件すべてDriveから独立再取得してGitHub原本と実バイトSHA256完全一致、CRC異常0。公開GitHubへ私的Drive URL/ID・認証・予想本文を転記しない。これら10件を全run/全学習元の永久保全と誤認しない。

**停止条件の重大未整合:** 前run第24巡の実GET `300`回、現run第17巡で`290`回。指定の1セッション公式GET240回を前runで60回、現runで50回**実超過**。実コード `race_ai/repeated_cycle.py` の `SOURCE_LIMIT=None/MAX_ROUNDS=None/MAX_SECONDS=None` とworkflow `timeout-minutes:360` は240GET/24巡/65分契約に不適合。現runは固定SHAで稼働中なので、本監査ではキャンセルも安全上限を迂回する追加triggerも行わず、設定修正成功と主張しない。まず独立したコード修正・契約テスト・既存原本保全を通した後にのみ安全な後続を判断する。旧モデル買い目・本番係数・他タスク・新workflow/PR/モデル系統・課金・公開・実投票は変更なし。

---

<!-- RACEAI_HISTORY_PDCA_20261106_0940 -->
# 2026-11-06 09:40 JST｜履歴PDCAの実結果1R照合と、暗号化状態のGitHub受入経路

**この作業の範囲:** 選手情報の並行実装を取り込み、公式90日分と期別成績を1653プロフィールへ統合済み。締切改訂・集計漏れ・保存完了時計の修正を維持し、11/6朝のV2原本156ペア/624予想を再生成していない。既存workerの第21巡artifactだけを再利用し、09:01 JST時点の締切済3Rのうち通常確定1Rを照合した。観測相性は元版/履歴版とも的中、ST重視は元版的中/履歴版不的中。結果の再実行で版数や採点数は増えない。追加の公式GETは0件。[件数のみの証拠](evidence/2026-11-06/history-pdca-initial-real-result-counts.json)。これ以後のworker増分を照合したとは主張しない。

**09:51 JST追補:** 大きい暗号文のBase64検査で発生したスタック上限を再現し、並行Codexと同じ修正へ統一した。修正後の[GitHub別runner](https://github.com/haji84/RACE-AI/actions/runs/42139398162/job/127636721950)で、期別選手1643人/9858コース行と2005年1月の限定checkpointの実復元が成功。GitHub側の鍵は利用可能になった。PDCA専用156ペア/90日履歴journalはローカルの同じ鍵への接続待ちであり、全状態の同期や精度改善は未認定。公開fixture/production形式の架空8MiB・鍵違い・改変拒否など統合後31テストも通過した。

**新しい受入経路:** `boat_pdca_github.py`で、所有者鍵を検査してから同じGitHub内の専用state refへ暗号文を世代別に追記。固定commit/SHA/scopeを既存CIの別runnerで私的復元し、元bytes・保存完了receipt・最新採点の再実行を確認する。公開artifactは件数と受入状態だけ。main/稼働worker・既存予想・モデル重み・権限・実投票を変更しない。送信先URLの変更と現在ファイルhead欠落は、新規回帰テストで拒否を確認した。

**確認と残件:** ローカルPython1567件/失敗0（任意CV依存56件skip）、Node202件/失敗0、第三者レビューのImportant2件を再現して修正済み。既存Draft [PR #71](https://github.com/haji84/RACE-AI/pull/71)へ非force反映し、GitHub CIで再確認中。ローカルは所有者鍵がなく、Secrets管理APIも403で拒否されたため、別認証・権限変更・鍵置換は行っていない。現入力は`WAITING_ENCRYPTED_INPUT`。**実データ暗号化公開→別runner復元は未完了**であり、正式な締切前receipt接続と精度改善も未証明。[所有者設定後の具体的な実行手順](BOAT_PDCA_PRODUCTION_HANDOFF.md)。別workerの全run保管・全競技の自動運用完成をこの確認へ加算しない。

---

<!-- RACEAI_AUTOMATION_20261106_0928_CYCLE06 -->
# 2026-11-06 09:28 JST｜唐津2R確定結果の増分採点、第6巡原本SHA/CRC独立照合

**対象と実行:** 既存Draft PR #71、branch `feat/four-sport-forecast-audit-view-20261022`。確認時PR HEAD `90e98805d2e8deea99f46dacb082edb98917bc5c`。同一workflow `405276784` の最新run [42134238827](https://github.com/haji84/RACE-AI/actions/runs/42134238827) はin_progress、同workflowのqueued/pending/waitingは確認した最新一覧で0件。前run [42124871318](https://github.com/haji84/RACE-AI/actions/runs/42124871318)はcompleted/success、第24巡最終継続元ZIP `13464303868` を独立SHA/CRCで再検証し、completed_round=24を確認。新規trigger、rerun、cancel、writer増設なし。

**最新の実保存成果:** 現run第6巡の結果・PDCA元ZIP artifact `13466556835`、GitHub API digestおよび独立取得した実ZIP SHA256 `7aef778701771e81272fad8874eda421d3d55f3b26605563fbc7dda2a3460b93` が一致、ZIP CRC正常。対になるP1元ZIP `13466152173` の実SHA256 `2ca215b5e951a62d4c4ac3379bf738ff2fa6bf7578c0497fd5e5415ad26ee181` もAPI digest一致、CRC正常。結果ZIP内 `current-p1-original.zip` と別取得のP1元ZIPはバイト一致。現run内部 `status.json.round_no=6` / `updated_at=2026-11-06T00:27:15.930596+00:00`（09:27:15 JST）、`completed_round=5/prepared_round=6` なので**第6巡の保存・独立照合は成立、第6巡の継続receipt完了はまだ未認定**。当日初回P0元ZIP `13428142302` は実SHA `6f900ac94d433aa11bf5b73a70ae68cd6ecf8849000fbb0726b3abd7769e82fc`、中の `forecasts.json` SHA `e9ef52b153f8648aedec59fb3233d2405528e862858b211b754801d409ce0860` とも `docs/evidence/2026-11-06/p0-first-receipt.json` に一致。第6巡結果ZIPの `first-p0-original.zip` にバイト一致、P0/P1の再生成・上書きなし。

**第24巡の既報値との差分:** 11/6のボート13場156R、朝版P0=312モデル別件は不変。新たに唐津3R（`20261106-23-03`、09:27 JST締切）へ展示後5系統P1を09:13:02 JSTに元ZIP `13464214744` として独立保存した事実を第6巡から照合。P1は20→**25モデル別件（5R×5）**、全基準予想332→**337件**。公式唐津2Rは09:19:05 JST（締切09:01後）の別結果観測で通常確定、**1-2-6／3連単100円2,050円**。公式結果observationsの別revisionを維持。通常採点は14→**21モデル別件**（HIT11→**13**、MISS3→**8**）、3つの通常確定レース×7モデル系統。未確認をMISSへ変換しない。各8点×100円の7系統すべてを仮想購入した場合、累計投入16,800円、累計払戻19,510円、**仮想損益+2,710円・仮回収率116.13%**。前回14モデル別行に対し今回は+7行、+2HIT/+5MISS、仮想投入+5,600円・受取+4,100円・損益-1,500円。条件付きモデル別採点は全国156Rの的中率ではなく、実投票も0件。

**PDCA:** 唐津2RはP1 Bコース・モーターおよびC-liteのみ的中。P0観測相性2系統とP1観測相性2系統は3着不一致、P1展示Aは1着不一致で不的中。3着候補選択の前向き改善を研究対象として保持し、既存8点・重み・過去予想を変更しない。最新 `automatic_learning` は通常確定一意3R、最少8R未達による `INSUFFICIENT_VERIFIED_RACES`、学習済係数・当日 `LEARNED_SHADOW`・学習版前向き比較の新増分0。 `coverage_audit` は第6巡09:27時点で全156R、締切済5R、未来151R、P1完備5R、未採点の締切済結果は通常判定確定を確認するまでMISSにしない。`model_coverage.json` で登録16系統と基準7モデル/時点を区分、`external_research_summary.json` は `NO_AUDITED_IMPORT_MANIFEST`。他競技の正式採点には今回加算しない。

**重大な安全条件:** 現run第6巡のGET `requests_used=74` は当該runの240件上限内。ただし `source_limit=null/max_rounds=null/stop_at=null` の無制限設定は継続し、直前run実績269回は240件超過29回。workflow `timeout-minutes=360`、物理handoff330分も指定24巡/65分と衝突。上限/4xx/429/真正性等の停止条件の回避を認めず、追加triggerは行わない。現在のworkerをキャンセルせず、無検証の制限変更をpushしない。今回Drive新規保存・全学習元再認証は未実施で、過去全runの永久保全や学習候補の有意な精度改善は未認定。新task、実行頻度変更、新workflow/PR/モデル、Cloudflare/Vercel/課金、main統合、公開、実投票、本番自動切替なし。

---

<!-- RACEAI_AUTOMATION_20261106_0911_CYCLE24 -->
# 2026-11-06 09:11 JST｜第24巡完走、三国1Rの通常結果を正式照合、原本7 ZIPを非公開追補、安全上限超過を検出

**最新実状態:** Draft PR #71の確認時HEAD `24ad152952338a96881aedc3b09d47ce1b80c8ae`。既存workflow `405276784` のrun [42124871318](https://github.com/haji84/RACE-AI/actions/runs/42124871318) は `completed/success`。その直後に既存run [42134238827](https://github.com/haji84/RACE-AI/actions/runs/42134238827) が別の既存triggerで起動し `in_progress`、対象workflowのqueued/pending/waiting=0。こちらからの追加trigger・rerun・cancel・workflow変更なし。

**最終完了原本:** 旧run第24巡の結果/PDCA artifact `13464717720`（ZIP実SHA256 `f8c0a2b113caf6926a125926b76a45d29e0becdb32bed3b8ce1f1b6a50cc1597`）、対応P1 artifact `13464717704`（`c7ff0d266fd6d95d6c9725be328bfd944967354fb5db9efc4aafdfbc441dd7d8`）、最終継続 `13464303868`（`df36a67f08a8208639d8223bc98a680362b4565cdb70b421f70a522ad11db0f2`）。3件ともAPI digestと独立取得ZIP実SHA256一致、CRC異常なし。結果ZIP内 `current-p1-original.zip` はP1原本バイトに一致。初回P0原本 `13428142302` の実ZIP・内包 `forecasts.json` のSHAは `docs/evidence/2026-11-06/p0-first-receipt.json` と一致し、結果ZIP内 `first-p0-original.zip` と実バイト一致。継続 `repeat-session.json` は `completed_round=24/prepared_round=null` と24件の `verified_at` receiptを保持。最終 `status.json.round_no=24/updated_at=2026-11-06 09:04:15 JST`。後続runにおける新しい巡回の成功までは推定しない。

**予想・結果の実差分:** 11/6公式台帳156R、初回P0は312モデル別予想で不変。P1は15→**20件**（唐津1R・2R、三国1R・2Rの4R×5系統）、うち三国2Rの新P1 artifact `13463429322` は09:01:13 JST保存、09:13 JST締切より11分47秒前。基準合計327→**332件**。唐津1Rに続き三国1Rも通常確定 `1-3-4/100円360円`、結果の後イベント元SHAを区別して保存。通常採点は7→**14モデル別件**、HIT5→**11**、MISS2→**3**。2つの通常確定レースに対する7系統×2で、レース数14ではない。8点×100円の研究上の全モデル仮投入11,200円/払戻15,410円/仮収支+4,210円/仮回収率137.59%。条件付きのモデル別行的中率11/14=78.57%は全156Rの的中率ではない。締切済3R/未来153R、結果未確認の唐津2Rを外れにしない。P1五系統完備の締切済3Rだが全156Rの網羅完了ではない。

**学習・PDCA:** `automatic_learning.state=INSUFFICIENT_VERIFIED_RACES`、一意の通常確定レース2（最小8）で学習適格母数未達。`trained_observed_models.json` は学習済係数モデルなし、当日 `LEARNED_SHADOW=0`・同条件比較0。展示Aは2Rとも外れ、2Rとも3着候補不一致。改善は研究候補のみで元Top8/5モデル式/係数、本番モデルは不変。外部研究正式manifestはなし。他3競技の同時点原本・公式結果は正式照合未実施。

**今回の非公開保全:** Google Driveの指定フォルダについてfolder ID一致、唯一owner、`shared=false`を改めて確認。第22〜24巡の予想元ZIP3件+結果元ZIP3件+第24巡完走の継続元ZIP1件、計**7件を新規保存**。7件すべてDriveから独立再取得して実SHA256/API digest一致、CRC異常0。第22巡結果ZIPを最初に誤ってP1名で新規保存したため、元バイトを変えずメタデータのみ正しい結果ZIP名へ修正し、改名後のDrive metadataと原本実SHAを確認。未保存元ZIP以外を上書きせず、私有Drive URL/ID・認証・生予想/結果をGitHubへ書かない。既報44件に追加された7件で11/6対象の保全は計51件だが、全run・全学習元・全公式改訂履歴の恒久保全は未証明。GitHub artifact保持7日は不変。

**重大な未整合:** 第24巡 `requests_used=269`。明示上限240 GETを **29回超過** した実測であり、単なる設定不一致ではない。現行 `source_limit=null/max_rounds=null/stop_at=null`・workflow timeout360分は240 GET/24巡/65分に不適合。現行runをキャンセルせず、上限/4xx/429/真正性エラーの回避目的で後続pushを追加しない。後続runも旧コードを使う可能性があるため、安全条件を満たした自動運用とは認定しない。既存上限の実装・回帰検証は今回未完了。新タスク、新PR、別workflow、新モデル系統、追加課金、公開、main統合、実投票、本番自動採用は行っていない。

---

# 2026-11-06 08:58 JST｜第21巡SHA照合・三国1R結果待ち・11/6原本44 ZIP非公開読戻し

既存run [42124871318](https://github.com/haji84/RACE-AI/actions/runs/42124871318) はin_progress 1件、同workflowのqueued/pending/waitingなし。第21巡の結果原本artifact `13464416656`、実ZIP SHA256 `b60f011a029bc0ebf2e721d004947ecab0cf0902e9eb793958ca3ae84f8c6081`、対応P1試行ZIP `13464476510` SHA256 `58c3a6a7d263478d2da07462c79bd55124f5ce94fbcfa3701d5811a6d74c677a`。GitHub登録digest・独立取得実バイトSHA一致、CRC異常なし。内部`round_no=21/updated_at=2026-11-06 08:55:17 JST`、`completed_round=20/prepared_round=21`。第21巡は保存と独立照合まで、読戻し完走は未認定。

P0初回312行、P1締切前15行（唐津1R・三国1R・唐津2Rの既存5系統）、合計327モデル別行で変動なし。唐津1Rの通常結果は2-1-4／2,650円で保存済み7モデル別採点5的中・2不的中。第21巡で三国1Rの後イベント結果を1版追加取得したが、状態は`PENDING/OFFICIAL_RESULT_PAYOUT_ONLY`。未確認の通常確定結果へ昇格せず、スコアも不的中へ変更しない。全対象156R中締切済2R・未来154R。学習は`INSUFFICIENT_VERIFIED_RACES`のまま、LEARNED_SHADOW正式比較の新増分なし。

非公開Driveに第21巡のP1元ZIPと結果元ZIPを追加保全、元の42件と合わせ**11/6原本計44件**。対象run第1～21巡のP1試行原本21件＋結果・PDCA原本21件＝42件、初回P0 1件、前run継続ZIP 1件。保存先owner一致/`shared=false`確認済み。44件すべてDriveから別取得し、GitHub原本実バイトSHAと44/44一致、CRC異常0、計21,059,662バイト。保全できたのは指定の44原本であって他run全件/全公式改訂/全学習素材の永久保全ではない。公開GitHubへDrive ID/URL・個人情報・買い目本文は転記しない。

**安全差分：** 第21巡公式GETは229回。ユーザー指示の1セッション240回上限まで11回しか残らない一方、稼働コード`source_limit=null/max_rounds=null/stop_at=null`、workflow timeout360分は指示の240GET/24巡/65分と不整合。現runをキャンセル/介入せず、上限回避目的の後続push・同run rerunも禁止維持。現行コードの無制限継続を安全成立とはしない。新workflow、新PR、モデル変更、頻度変更、追加課金、main統合、公開、投票、本番自動切替なし。

---

# 2026-11-06 08:53 JST｜11/6初の実結果照合・P1第三レース・現run第1～20巡40原本ZIPを非公開保全

**GitHub独立証拠：** 既存run [42124871318](https://github.com/haji84/RACE-AI/actions/runs/42124871318) はこの監査時点`in_progress`、同workflow 405276784のqueued/pending/waitingなし。実行元HEAD `cf74fcc56ce1855e8f118ce39a6eed71b1e95e0a`。最新実保存第20巡の結果/PDCA原本artifact `13464760617`、実ZIP SHA256 `4af82017337bcb29f274fa1cf3635b40d48f5467a2756d5a238ed1cb90a30d6b`、対応P1試行ZIP `13464835477` SHA256 `39ca5c2f1a7a5cb5d59023a00906c2e9983228a377c9984a14684d7c0ad783da`。GitHub API digestと独立取得したZIP実バイトSHA一致、CRC異常なし。内部`status.round_no=20/updated_at=2026-11-06 08:52:08 JST`、継続は`completed_round=19/prepared_round=20`なので第20巡の読戻し完走までは未認定。

**凍結予想の増分：** 13場156Rの初回P0は312モデル別行のまま。展示後P1は唐津1R・三国1Rに加え**唐津2R（`20261106-23-02`）へ既存5系統5件追加**し、P1が**15行＝3R×5系統**、当日の基準計327モデル別行。唐津2Rの締切09:01 JSTに対し初回P1保存08:49:13 JST（元artifact `13462499574`、実SHA `24417543a72db1713e4cbbc596d6fb6d82874b4bb6c14fde87cd53db362e7a4f`）で、210秒の事前余裕を満たした。旧P0・P1は無変更。

**本日の最初の正式結果・PDCA（重複レースではない）：** 11/6唐津1Rの公式結果を、先行PENDING `OFFICIAL_RESULT_PAYOUT_ONLY` と後続の独立`AVAILABLE`の2版として保持。後続結果には6艇の登録番号・通常着順、3連単**2-1-4／100円払戻2,650円**を含み、結果時刻08:49:17 JSTは08:35締切後。旧結果観測のrevisionを消さず、基準原本に結果を後付けしない。通常採点は**1レースに対するP0二系統＋P1五系統の7モデル別行、HIT 5・MISS 2**。各8点×100円の仮想購入では7行合計投入5,600円・払戻13,250円・仮収支+7,650円、見かけのモデル別行的中率5/7＝71.43%、回収率236.61%。ただし**実際には1レースであり、7件の独立レースや全日成績の証拠ではない。** P0二系統とも的中、P1はコースモーターB・観測相性・ST重視相性の3系統的中、展示Aと当地ST C-liteは3着候補不一致で不的中。次のPDCA研究は既存8点の3着候補順位の前向き評価に限定し、本番係数や過去買い目は書き換えない。

**学習の境界：** 一意の通常結果は現状1レース、既存の`automatic_learning=INSUFFICIENT_VERIFIED_RACES`、当日LEARNED_SHADOW/前向き比較の正式増分0。1Rの結果を7学習サンプルに膨らませない。返還・訂正・結果待ちを不的中へ転換しない。成績の統計的優越・全16モデル/全4競技・全レース網羅性は未達。

**Driveの原本保全を実完走：** 本人専用フォルダはGoogle Drive metadataで唯一のowner、`shared=false`と実確認。今回のGitHub run **第1～20巡のP1試行原本20 ZIP＋結果・PDCA原本20 ZIP＝40 ZIP**、および11/6初回P0 ZIP1件、前runの継続ZIP1件、合計**42件を既存非公開Driveへ新規保存**。当初`container_path`はsession-expired、GitHub→Drive直結はblockedだったが、GitHub downloadで返った原本の`file_id`をそのままLibraryの`source_file_ref`へ渡す経路で成功。42件を**Driveから別途再取得**し、42/42がGitHubからの原本ZIP実SHA256・GitHub API digestと一致し、CRC異常0、総原本バイト20,104,726。ZIPの上書き・加工・再圧縮は一切なし。所有者限定の保管を確認できたのはこのフォルダと42ファイルであり、過去全run・全学習ソースの永続的保存完了ではない。公開GitHubに個人Drive URL/ID・認証・生結果/買い目は転載しない。

**未解決の実行条件：** 第20巡で公式GET `requests_used=213`。現行`source_limit=null/max_rounds=null/stop_at=null`、workflow `timeout-minutes=360` はユーザーの240GET/24巡/65分と未整合のまま。別チャットの上限解除指示履歴があり、稼働中runを停止したり上限を回避したりする後続push/同run rerun、無検証の設定改変は実施しない。今回新workflow、新PR、新モデル、頻度変更、追加課金、main統合、公開、実投票、本番自動切替はなし。

---

# 2026-11-06 08:46 JST｜展示後5系統P1が2レース10件、新規ZIP17件を非公開Driveで独立読戻し

**本巡の実増分：** 既存workflow 405276784 のrun [42124871318](https://github.com/haji84/RACE-AI/actions/runs/42124871318)、実行コードSHA `cf74fcc56ce1855e8f118ce39a6eed71b1e95e0a`。同workflowの直近100実行では実行中1件・queued/pending/waiting 0件。runは継続中であり同runのrerun・追加trigger・キャンセルなし。最新の保存済み結果原本は第17巡、`status.json.round_no=17`、`updated_at=2026-11-06 08:44:16 JST`、前巡の読戻し `completed_round=16/prepared_round=17`。第17巡は実ZIPハッシュとCRC検証まで完了し、読戻し完了を後付け認定しない。

**新規の締切前5系統P1（P0とは別）：** 11月6日13場156レースの既存P0=312モデル別行（156R×2）は不変。P1は2レース×既存5系統＝**10モデル別予想**を新規保存した。唐津1R（`20261106-23-01`、締切08:35）は08:23:14 JSTにGitHub ZIP保存、元ZIP artifact `13462342640`、実ZIP SHA256 `ef077647f207e56a217269ac8a0652482b86e36dc495868aaa977292a4d72432`。三国1R（`20261106-10-01`、締切08:47）は08:32:12 JSTに保存、元artifact `13462852230`、SHA256 `43a2ee1734a89dfb156f196fd87f86746408a10e08d78f3fbe0db3edcc02a0d4`。双方とも公式6艇の展示・登録番号・締切の構造を保持し、締切より210秒以上前にGitHub側artifactが作成され、実ZIPバイトSHA256がAPI digestに一致、CRC異常なし。既存P1の展示A・コースモーターB・当地ST C-lite・観測相性・ST重視相性で各5件。初回P0の実ZIP `13428142302` を独立取得、初回receiptのZIP SHA `6f900ac94d433aa11bf5b73a70ae68cd6ecf8849000fbb0726b3abd7769e82fc`、内部JSON SHA `e9ef52b153f8648aedec59fb3233d2405528e862858b211b754801d409ce0860` と一致。旧P0・P1原本再生成なし。

**結果と学習を混同しない：** 第17巡結果ZIP `13462684523` は実SHA256 `218d5413f43de02d23c7a3e1e5f64717ddbe5d60c3ff24e65c97bc73b27eb6a0`、ZIP CRC正常、内部 `forecasts.csv` 322モデル別行＝P0 312＋P1 10。公式結果観測は唐津1R 1件だが `PENDING/OFFICIAL_RESULT_PAYOUT_ONLY` であり確定着順・払戻の正式照合に昇格しない。通常採点0、学習候補 `INSUFFICIENT_VERIFIED_RACES`、LEARNED_SHADOWの当日採点/未来比較0。08:44時点で締切済1R、未来155R。結果未確認をMISS扱いせず、的中率・回収率・仮想収支は未算出。

**非公開原本保全の突破：** 既存Driveフォルダは独立メタデータでowner権限のみ・`shared=false`・個人My Drive直下の非共有フォルダと照合。GitHub connectorの`file_uri`をそのままDriveへ送る方法は`BLOCKED_FILE_REFERENCE`で失敗、Libraryの`container_path`方式も`container_session_expired`で失敗。ただし**原本取得時の正確な`file_id`を使ったLibraryの`source_file_ref`方式では、2026-11-06の未保存ZIP17件を新規作成できた**。内訳：初回P0×1、以前runの継続ZIP×1、現run第10～17巡のP1 ZIP×8と第11～17巡の結果ZIP×7。17件をDriveから別経路で再取得し、GitHub API digest・元実ZIPとSHA256全件17/17一致、CRC異常0。Drive内の元ZIPは編集・再圧縮・上書きなし。公開GitHubへDriveのID/URL、買い目原文、生ソース、認証情報は掲載しない。**現run第1～9巡と第10巡結果、他runの原本全量については、今回の17件だけでは保全完了ではない。**

**運転上の未解決：** 現run第17巡で公式GET `requests_used=186`。旧指示のセッション240件・1巡45件／3レース・24巡／65分と、現行実コード`source_limit=null/max_rounds=null/stop_at=null`、workflow `timeout-minutes=360` は依然不一致。停止回避を認めたり無制限継続を安全稼働と認定したりしない。別チャットの上限解除指示履歴もあるため、実行中workerや別の同時開発を破壊する無検証の設定巻戻しはしない。同runへの割込み・後続pushなし。GitHub artifact 7日保持を永久保存と呼ばない。5系統全156R・他3競技・全16系統・未来の統計優位性は未完成。

---

# 2026-11-06 JST｜実映像2資料で識別を実測、現行方式は不合格（強さ・予測改善の認定なし）

既存Draft PR71で継続。開始HEAD35871afから、他作業の監査・既存worker引継ぎだけの更新を960bdeaまでfast-forwardし保全した。新PR・外部タスク・workflow・予想モデル系統・有料サービスは追加していない。

**実映像を取得・復号：** Commonsの[江戸川・2021年9月7日](https://commons.wikimedia.org/wiki/File:Kyotei_-_Sept_7_2021.webm)（Nesnad、CC BY-SA4.0、25.859秒/775フレーム、SHA `1ac1f0c27f58d8d64ebb1cfc13c2c4e9133cf7bbcce04052f23c28bf2e37f194`）と、[福岡公式の展示解説](https://www.boatrace-fukuoka.com/modules/fukuokainfo/?page=index_lib&bnr=1)（2021年9月22日公開、145.903秒、SHA `7821356af29809c5da4a40eb06586896a8723d9068aba8e0b8a9e005dc535b70`）を通常の公開導線で取得した。福岡はALL RIGHTS RESERVEDで再利用/学習許諾を認定せず、私有解析だけとする。生映像・注釈・取得プレイリストはGit/UIへコピーしない。両資料とも正確なレース番号・締切・6艇の登録番号は未確定で、JOB_V1や当日予想へ偽装しない。

**実測は不合格：** 既存NanoDet/YOLOXの最初の追跡はOCR中断で失敗。別の全復号・生検出では97標本で艇候補総数32/104、同時最大4/5、0.90以上の数字読取0、YOLOXの3秒期限切れ4件。初回NanoDetの抑制された例外原因は確定できず、同じ原因とは断定しない。修正後は両方式とも775フレーム/97標本を最後まで返したが、数字候補と有効位置は全6艇とも0。実行完了と識別成功は別で、実行優先度の違いも含むため、完走率の因果的改善をこの対比だけでは認定しない。

**分母付き照合：** モデル結果を見る前に別担当が9フレーム・30艇の領域・19可読番号を注釈した。これは独立したAI目視参照で、人の正解認証ではない。固定4fpsで対応した6フレームの可読番号10例では両方式とも正解出力0/10、出力がないため適合率はnull。未抽出の3フレームは別記し、不的中や成功に変換しない。同じ映像内の分割は未知映像への一般化と呼ばない。艇の領域だけの照合（概略枠IoU0.5以上）は18艇中NanoDet0/18、YOLOX6/18。別資料の福岡は3注釈フレーム中1フレームが抽出に対応し、領域は両方式0/6。低解像度で番号は読めないため番号精度の分母は0。これらは少数のAI注釈との一致で、全場・全レースの性能ではない。

**実装・修正：** `boat_video_benchmark.py` は、BGR24画素SHA/PTSへ結び付いた参照と、番号に依存しない一対一の位置対応から、取りこぼし・誤番号・誤検出・ID切替・分母を別集計する。PNGファイルSHAを画素SHAと混同せず、実映像/合成、実エンジン/注入、AI注釈/人の認証を分ける。OCRは低信頼度PSM11が別方式を妨げる不具合を修正、0.90/共通3秒期限は維持。型付きOCR失敗は当該艇の欠測とし、移動した失敗艇の古いIDが隣艇へ移る再現も修正した。未想定エラーと起動失敗は隠さない。

**不採用の試作：** 開発用だけで数字領域抽出/傾き補正を試した。2値の領域マスクは5を読めた一方、実際の2を4と高信頼度で誤読したため不採用。元のグレースケール画素を保つ別試作は誤採用を抑えたが、採用できる読取0。閾値低下、色からの艇番割当、欠測を6艇まで埋める処理は採用していない。公開OpenCV Zoo CRNNのINT8/FP32も、同じ固定54入力で私有試験した。両版とも1/2/5の正しい生文字列を5ビューで返したが、全37クラスのCTC経路を合算する生尤度は最大0.7597/0.6188で、0.90を満たす採用は0。Tesseractの信頼度と同一尺度ではなく、量子化だけが原因とも認定しない。追加したOCR資産は私有の研究用途だけで、製品コード・新しい予想モデル系統・本番切替へ導入していない。

**別担当による固定の生文字候補試験：** 開発用入力から固定したFP32版を、ラベルを開く前に1回だけ別担当が実行・凍結し、その後に採点した。同じ動画内の未使用5フレームでは9可読参照中2箇所、別の琵琶湖の写真では6参照中4箇所に正しい生候補が出た。動画の1箇所は既存4fps追跡が抽出しない660番フレームで、抽出対応だけなら1/7。候補ビューは動画で正4/誤0/位置未対応1、写真で正7/誤0/未対応0だが、正規化違いの重複を含む。これは数字領域の生出力で、採用ID・時系列追跡は0のまま。誤り0を100%の精度や一般化成功とは扱わない。1艇の処理は3秒のsoft予算を超えて3.831秒となり、後続3ビューを省略。新方式は製品に組み込んでいない。CTCの0.90は診断値だけで生候補の採否に用いておらず、校正済み正解確率ではない。

**強さ・予測改善は未成立：** 有効位置が0のため、各方式・資料の4区間×6艇は全欠測。独立した水面/画角校正・時計・区間/強さの正解もなく、画像上速度を強さへ変換できない。動画特徴を使った実学習・締切前実予想・未来結果比較は0件。既存cycleへの動画文脈/独立受領証の運用接続も別の未完成条件であり、次の結果を待つだけで完成するとは扱わない。福岡11/05 1Rの通常展示再生も403/P01002で拒否され停止した。過去資料で取得時刻を遡らせたり、元の予想・結果を書換えない。

**検証：** 基点960bdeaでPython全1,488件成功。並行する履歴/PDCA実装をcf74fccまで保全して統合した版fd2c5f1では、SHAに偶然含まれる登録番号の数字列を漏えいと判定するテストが1件失敗した。出力項目/保存済みSHAを照合するテストへ修正し、全1,559件がskipなしで成功（282.782秒）。独立再審査は構造的な漏えい5変種を拒否できることも確認した。その後のc1165b9からの並行更新は資料と別の試験fixtureのみで、製品ソースは不変・当該fixture1件成功。番号/艇領域ベンチマーク25件、OCR回帰12件成功。新OCR回帰を既存CIの隔離CV試験にも追加済み。実装HEAD `a6615ee8784f721e66c52837db031a4c0caa8a7d` の[Viewer CI](https://github.com/haji84/RACE-AI/actions/runs/42129603918)と[AUTORACE CI](https://github.com/haji84/RACE-AI/actions/runs/42129604000)も成功。CIの通常Pythonは1,559件中1,503成功/任意CV56件skipで、隔離CV116件はskipなし・新OCR12件も成功した。Node88件、統合UI48件、ブラウザ39確認/動画UI12件が成功。AUTORACEはUbuntu31成功、Windows21成功/ファイル権限10件skip。私的データ取得のHOLDや別runner復元skipは実データ取得成功とは扱わない。この追記は資料だけで、実装・試験・workflowツリーは上記HEADと同一。CIの成功を実映像性能の達成証拠へ変換しない。

福岡の別リソースである当日LIVEは08:16 JSTに通常画面で「ライブ配信時間外」を確認。これは403とは別の可用性状態で、将来の視聴許可も実レース映像の取得も未認定。稼働中run42124871318（固定cf74fcc）と自動予想RUNNING/continuousを確認し、予想本体・動画intakeは停止・再起動していない。修正ソースを既存intakeへhot reloadしたとは扱わない。既存288原本DBのSHA `c40bead05533ace426188ea8a111b1e4a4a639283f576972ba276e14a3e8ff1a` を確認。[実測・ソース・試験の証拠](evidence/2026-11-06/real-video-validation/verification.json)を保存。以下は過去記録として保全する。

---

# 2026-11-06｜選手DB統合・PDCA集計修正・私的状態引継ぎ（実データGitHub復元は鍵待ち）

既存の公式期別1,643名と90日履歴1,609名を登録番号で結合し、当日583名全員を含む1,653プロフィールを私的に出力。両資料に情報がない当日4名も欠測として保持。予定84,816機会は出走確認84,104/欠場142/未確認570へ区分。期別の年齢・級別を現在値へ変換せず、交換周期や因果的戦法は未確認のまま。

原本698行を変えずに11/5を再採点し、通常133R/641モデル別採点（204HIT/437MISS）、例外/結果待ち57行へ整合。両比較版の締切改訂、元締切遅刻の拒否、UTC/JST日本開催日の照合を修正。履歴平均/母数は艇愛側と同じ既存関数へ一本化した。

V1の624研究原本は隔離して保全。V2は156R×2モデル×2版=624研究予想を07:20:07 JSTまでに物理保存。着順468/936艇・ST897/936艇を入力し、最初の締切08:35 JSTより前。正式外部時刻証明と未来改善は未実証。公開はSHA一覧のみ。

実データの私的journalは156ペア/674ファイル版を保持。別プロセスの暗号化復元・原本保持・訂正結果・重複防止・次予想を架空データで検証し、既存CIへ別runner検証を追加。実データのGitHub暗号化復元はGitHub jobが`HOLD_OWNER_STATE_KEY_MISSING`（源流GET0件）を返したため保留し、全実運用完了とはしない。[実装・実データ・検証境界](BOAT_PDCA_COMPLETION_20261106.md)。稼働worker・既存原本・main・係数・投票・配備先を変更しない。

---

# 2026-11-06｜公式90日履歴と同時刻の履歴比較を準備（V1準備時点の記録）

BOATERSの明示的な取得制限と運営許可未取得を確認し、既存の公式B/K経路で2026-08-07〜11-04の90日・180原本を私的に保存。通常13,090R、例外/未確認1,046R、選手1,609名の出走事実84,246件を取り込んだ。原本・DB・買い目は公開しない。締切改訂の評価ビューで11/5の通常採点を637→641モデル別行へ整合し、旧予想は不変。

11/6全156R×既存2モデル×元版/直近履歴版の624研究予想を同時刻・8点で別保存した。直近着順489/936艇・ST932/936艇で利用。未来結果、正式外部receiptへの接続、モーター交換周期、全4競技・常時自動運用・期限なし私有保全は未達。本番モデルや稼働中workerを変更しない。公開は[SHAのみの事前監査](../audit/freezes/2026-11-06/official-history-research-pairs-sha-only.json)。[取得経路・使用方法・受入境界](BOAT_HISTORY_PDCA_20261106.md)。

---

# 2026-11-06 07:27 JST｜前run24巡完走・現run第16巡の実原本照合（新予想・結果・学習増分0）

対象：既存Draft PR #71、branch `feat/four-sport-forecast-audit-view-20261022`、workflow `405276784`。監査直前PR HEAD `960bdeac629e4811c4bf6ac71a4b3d8dfa8ef215`。GitHub Actions対象run一覧（最新100件から当該workflow抽出）で実行中は [run 42114125652](https://github.com/haji84/RACE-AI/actions/runs/42114125652) 1件のみ、queued/pending/waiting=0。前run [42102544987](https://github.com/haji84/RACE-AI/actions/runs/42102544987) はcompleted/success。実行中runのキャンセル・既存runのrerun・後続pushは実施せず、同時writerはAPI上1件。

**保存済み独立照合：** 最新実保存第16巡の結果・PDCA artifact `13458124691` の実ZIP SHA256 `9f4fa35faa20fab8042e8ae952ca43536af16da0ad14e54452d12e95320daec8`、対応P1試行ZIP artifact `13459151142` のSHA256 `64c4b62145d2f7b725837e1e1e50ffc55b930d1bd90568b521cfd8d74dc5a1ea` は、GitHub API digestと実バイトが一致しCRC異常なし。結果ZIP内 `current-p1-original.zip` は別取得P1 ZIPの実バイトSHA一致。内部 `first-p0-original.zip` も当日初回P0原本 artifact `13428142302` の**別取得実ZIP**とバイト一致。初回P0元ZIP SHA `6f900ac94d433aa11bf5b73a70ae68cd6ecf8849000fbb0726b3abd7769e82fc`、`forecasts.json` SHA `e9ef52b153f8648aedec59fb3233d2405528e862858b211b754801d409ce0860` は既存 `docs/evidence/2026-11-06/p0-first-receipt.json` と一致。初回原本の再生成・上書きはなし。結果内 `status.json.round_no=16/updated_at=2026-11-06 07:25:32 JST`、`bounded_repeat_session.completed_round=15/prepared_round=16`。**第16巡は別保存と独立ハッシュの成立まで、第15巡まで読戻しreceipt成立、現runの全24巡完走は未認定。**

**前runの最終読戻し：** 最終継続artifact `13454938639` 実SHA256 `2e01672cd9e49f83c9005eedb87907e964cd27c08a3ff6ab3abc2084fb485940`、最終第24巡結果ZIP `13454639202` SHA256 `f341595ffce41fd9696534c58e8a3ea70f862998f79fa9b080f11516f8de7f57`、対応P1試行ZIP `13454988553` SHA256 `f3c19f72f6e907bfdd3710035abac1d1c5fc4507c409415beeec25f4ce225039`。3件の実ZIP SHAがAPI digestと一致、CRC正常。継続 `repeat-session.json` に `completed_round=24/prepared_round=null`、24件の `verified_at` receiptあり。前run24巡読戻しを認定。

**本日の事前予想・成績：** 公式日程台帳13会場156R、P0既存2系統312モデル別件（`forecasts.csv`実312行、`model_coverage.total_saved_forecasts=312`一致）、展示後P1=0、公式確定結果観測=0、通常結果採点=0、学習版=0、未来ペア比較=0。 `coverage_audit` は未来156R・締切済0、 `automatic_learning.state=INSUFFICIENT_VERIFIED_RACES`、 `external_research_summary.state=NO_AUDITED_IMPORT_MANIFEST`。最終候補理由 `NO_COMPLETE_EXHIBITION_IN_ORDERED_CANDIDATES`、次確認予定08:20 JST。的中率・回収率・収支の新値は計算不能。過去日の値の持越し・結果後予想・未確認結果を不的中扱いすることはしない。

**未整合と非公開保全:** 現保存セッション公式GET実数156だが `source_limit=null/max_rounds=null/stop_at=null`、既存workflow timeout360分と定期指示240GET/24巡/65分は矛盾したまま。GitHub Actions `concurrency.group=boat-nationwide-cutoff-20261103/cancel-in-progress=false`。他の直接指示（上限撤廃）も既存記録に存在するため、稼働中runを止めたり、停止条件回避の新runを押したり、無検証でコード/設定を巻き戻さない。本人専用Driveの指定フォルダはowner権限1件・shared=falseと今回直接照合したが、既存runの継続原本ZIP1件追加はLibraryの `container_session_expired` で失敗。connector-to-connector経路も `BLOCKED_FILE_REFERENCE`。**今回のDrive新規保全0件。** 公開GitHubへの私有URL・個人ID・予想本文・生ソース等は転載しない。

次の実用判定：08:20以降に公式展示が実際に揃った適格未来レースを締切順に選び、既存5系統P1を締切210秒以上前に独立保存、結果は後イベントで別原本・改訂履歴照合。検証済み通常結果のみから観測相性2系統の係数候補を作り、独立学習元照合後に未来同条件で比較する。新タスク・実行頻度・新workflow/PR/モデル/課金・外部サービス・main統合・公開・投票・本番自動切替なし。

---

# 2026-11-06 06:25 JST｜当日第20巡の実ZIP検証と前worker24巡の引継ぎ監査（新P1・採点増分なし）

対象は既存Draft PR #71、同一workflow 405276784、GitHub上の確認HEAD `ea8b71dad0bf9dced24d3cf4ffce23eae015fb88`。確認時のrun [42102544987](https://github.com/haji84/RACE-AI/actions/runs/42102544987) は `in_progress` 1件、対象workflow直近100件にqueued/pending/waitingなし。前run [42090917336](https://github.com/haji84/RACE-AI/actions/runs/42090917336) は `completed/success`（05:19:12 JST）。前run最終継続artifact `13450426983` を実ZIPバイトで独立取得し、GitHub API digestとSHA256 `db7f17ed2b1814333210f4d88fd21c3d7f5d1eb5bbc4ff27bd2171e436fdbc11` が一致、ZIP CRC正常。内部 `repeat-session.json` は `completed_round=24/prepared_round=null`、第24巡の別保存読戻しreceiptを保持。前run24巡完走を認定。

**現run第20巡の別保存原本の独立照合:** P1試行ZIP artifact `13454831900` の実SHA256 `55e3473622df25a663533b3b33d655d0897e2625c0001601414220e6efc77862`、結果・PDCA ZIP artifact `13454831911` の実SHA256 `5ebb4640c8a5fa03b1c35a84e2322b15cc83facf6c0cae67709b37680a9cdbea` はそれぞれGitHub登録digestと一致、ZIP CRC異常なし。結果ZIP内 `current-p1-original.zip` は独立取得P1 ZIPと実バイトSHA一致。`first-p0-original.zip` は当日初回P0 artifact `13428142302` とSHA256 `6f900ac94d433aa11bf5b73a70ae68cd6ecf8849000fbb0726b3abd7769e82fc` で一致、初回receipt索引の登録digestとも一致し再生成・上書きはなし。

**巡回の境界:** 結果ZIP内 `status.json.round_no=20/updated_at=2026-11-06 06:22:55 JST`、`bounded_repeat_session.completed_round=19/prepared_round=20`。第19巡までの独立読戻しreceiptがあり、第20巡は元ZIP保存・独立ハッシュ照合のみ確認。run全体の完走とはしない。現run `requests_used=202`、`halted_reason=null/source_wait=null`。公式6艇の展示後入力は未成立（`national.json.reason=NO_COMPLETE_EXHIBITION_IN_ORDERED_CANDIDATES`）、次の候補確認は08:20 JST。

**当日成績:** 13会場156レース、朝版P0=312モデル別予想（2系統×156R）、P1=0、公式結果観測=0、通常採点=0、学習版=0、未来比較=0、`forecasts.csv`実312行/重複なし。 `coverage_audit`: 未来156/締切済0。学習は `INSUFFICIENT_VERIFIED_RACES`、`external_research_summary=NO_AUDITED_IMPORT_MANIFEST`。従って新しい的中率、回収率、仮想収支は算出しない。過去の日の成績を今日に混ぜない。

**安全・保全未達:** 実GETは202<240だが、保存セッション `source_limit=null/max_rounds=null/stop_at=null`、現workflow `timeout-minutes=360` は当定期指示の240GET・24巡・65分と不一致。別に記録されたオーナーの上限撤廃指示とも競合。実行中runをキャンセルせず、無制限実行の後続起動・同run rerun・設定の無検証変更・並列writer増加はしない。Google Driveの対象非公開保管フォルダは今回も所有者一致/`shared=false`を直接確認したが、元ZIP6件の新規保存はLibrary側 `container_session_expired` で6/6失敗。別経路の単独再試行も同じ失敗、GitHub→Drive直結は参照型不一致。**今回のDrive新規保存0件であり、恒久保全完了ではない。** 元ZIPの編集・再圧縮、公開Gitへの私有URL/ID・生予想・認証値の転記はなし。

次の作業は既存workflowの安全上限の運用契約一致と、08:20以降の展示公表を実際に確認した5基準モデルP1の締切前独立保存、結果が出た後の別イベント採点・係数学習・LEARNED_SHADOW前向き同条件対照。既存タスク・実行頻度・workflow・新PR・新モデル・外部サービス・追加課金・main統合・一般公開・実投票・基準モデル本番係数は無変更。

---

# 2026-11-06 05:18 JST｜最新保存第23巡を独立ZIP照合、前worker第24巡も復元確認（事前予想増分0）

対象：既存Draft PR #71 / `feat/four-sport-forecast-audit-view-20261022`、確認時HEAD `aae143f374135c14b681b244f5900be8612d560f`、既存workflow `405276784`。直近30run確認では [run 42090917336](https://github.com/haji84/RACE-AI/actions/runs/42090917336) が `in_progress` 1件、同workflowのqueued/pending/waitingは0。現runの第23巡保存済みだが、第24巡は実行中でありrun全体の成功とは判定しない。追加trigger・キャンセル・rerunなし。

**前回04:37監査の未検証分を解消した実差分：** 現run第23巡の結果・PDCA元artifact `13448378689` の実ZIP SHA256=`39e23fb2304415e453c0e2e13f9d8e341a30f5a53f40802ea641b5873a7ac49d`、第23巡P1試行元artifact `13448563524` は `d5b375bbd71385157f713ee3e66493c77bc747885c098d1478df7bd1811d0e52`。双方GitHub API digestと実バイトSHA256一致、CRC異常0。結果ZIP内 `current-p1-original.zip` も別取得P1元ZIPとバイト一致。結果ZIP内 `first-p0-original.zip` は11/6初回原本artifact `13428142302` のZIPとバイト一致、SHA256 `6f900ac94d433aa11bf5b73a70ae68cd6ecf8849000fbb0726b3abd7769e82fc`、内部 `forecasts.json` SHA256 `e9ef52b153f8648aedec59fb3233d2405528e862858b211b754801d409ce0860` も初回receiptの登録値と一致。原本再生成なし。

**巡回完了境界：** 第23巡の `status.json.round_no=23`、`updated_at=2026-11-06 05:16:04 JST`、`bounded_repeat_session.completed_round=22/prepared_round=23`。第22巡まで22組の別保存読戻しreceiptを内部確認し、最終 `verified_at=2026-11-06 05:13:04 JST`。第23巡は実ZIP保存を独立照合したが読戻し完了の認定はまだ行わない。前run [42079188438](https://github.com/haji84/RACE-AI/actions/runs/42079188438) は `completed/success`。第24巡結果ZIP artifact `13444198615`、対応予想ZIP `13444198605`、継続ZIP `13444018826` を別取得し、3件ともGitHub API digestと実バイトSHA256一致・CRC正常。継続 `repeat-session.json` の `completed_round=24/prepared_round=null` と24組のreceiptを確認。前workerの最終読戻しまで認定。

**11/6正式な実績：** 対象13会場156R、P0初回312モデル別予想（2系統×156R）を `forecasts.csv` 実312行・ユニーク312と `model_coverage` で一致。P1=0、公式確定結果観測=0、通常採点=0、LEARNED_SHADOW=0、未来ペア比較=0、学習 `INSUFFICIENT_VERIFIED_RACES`。 `national.json` は `NO_COMPLETE_EXHIBITION_IN_ORDERED_CANDIDATES`、次の確認予定08:20 JST、最初の対象締切08:35 JST。 `coverage_audit` は156Rすべて未来、終了済み0。したがって未予想を不的中へ計上しないし、的中率/回収率/収支も未算出。 `external_research_summary=NO_AUDITED_IMPORT_MANIFEST`。他競技の新予想/成績の独立認証なし。

**安全条件の未整合：** 現runの結果保存時点 `requests_used=219`、`halted_reason=null/source_wait=null` だが現行 `source_limit=null/max_rounds=null/stop_at=null`、workflow timeout360分はこの定期指示の公式GET240/24巡65分制限と一致しない。実使用219<240は安全上限が強制された証拠にはならない。これらの相反条件の未解消中、後続pushで停止条件を回避せず、writerを増やさず、現runもキャンセルしていない。未公表展示の取得可能性を断定しない。恒久非公開保全/全16系統/全4競技/未来優位性は未完成。本番モデル・買い目・原本・既存毎時スケジュール・新PR/新workflow・公開・課金・実投票は無変更。

---

# 2026-11-06 04:37 JST｜前worker完走と次worker第10巡の保存物一覧を監査（内部独立検証は保留）

既存Draft PR #71 / `feat/four-sport-forecast-audit-view-20261022`、監査時HEAD `9a6085be9b88c3ae5f3a6d5c96210247871bdefb`、workflow `405276784`。前run [42079188438](https://github.com/haji84/RACE-AI/actions/runs/42079188438) は **04:06:49 JST completed/success**。Actions jobで第24巡とcontinuity構築が `completed/success`。後続run [42090917336](https://github.com/haji84/RACE-AI/actions/runs/42090917336) は **04:07:53 JST起動/in_progress**。直近100 run中、同workflowの稼働はこの1件、queued/pending/waitingは0。キャンセル・rerun・追加pushなし、同時writerはAPI上1件。

後続runのActions jobでは **第10巡までsuccess**、実行中stepは `Deadline-ordered five-model round 11`。保存済みの第10巡の予想artifact `13446497882`（GitHub API digest `sha256:df708ad32ffc63bce01120afe1b431e1bdfafbf51efc16e92b2c2a361bcf54c8`、API時刻19:36:50 UTC）と結果・PDCA artifact `13447616575`（API digest `sha256:97f19fca7e0e3b118040b5b53ad9e491fcaaf3e2857010f718910b2eb54e6a06`、API時刻19:36:53 UTC）を一覧で対にして確認。第10巡のAPI保存メタデータを第10巡の内部読戻し完了と混同しない。

**確認の限界:** 第9巡の予想・結果、前runのcontinuity、当日初回P0原本はGitHub connectorからZIPを取得したが、この実行環境のローカルファイル解析がエラーで、実ZIPバイトSHA、CRC、内部 `status.json.round_no/updated_at`、`forecasts.csv`、`automatic_learning`、`learned_shadow_comparison`、`coverage_audit`、学習元の独立読戻しを今回完遂できていない。API digest登録は独立SHA一致の証明ではない。直近独立監査で確認済みの11/6初回P0=312モデル別件（156R×2）を維持し、**最新P1・結果採点・学習版・的中率/回収率/収支の増分は未確認**。0件との断定も、過去日の成績の流用も行わない。P0初回原本・過去予想を再生成しない。

先行監査記録の稼働コード `source_limit=null/max_rounds=null`・workflow timeout360分と、当定期指示の240GET/24巡/65分が未整合。今回の内部カウンター検査不能につき上限遵守を新規認定しない。明示的な4xx/429/日付/真正性停止を回避する後続起動も行わない。他チャットの更新を残し、新タスク・頻度・workflow・PR・モデル系統・課金・Cloudflare/Vercel・main統合・公開・実投票・本番自動採用の変更なし。

---

# 2026-11-06 JST｜展示映像の6艇候補・自動取込・既存2モデルの実験接続を追加（実映像の受入は未完成）

既存Draft PR #71の同じブランチで実装。別作業のTeiai履歴、全選手期別データ、worker引継ぎの更新をfast-forwardで保全し、確認済み基点は `3123f54ebea1b90eff453c322fd3009cd5a52097`。新PR・外部タスク・workflow・予想モデル系統・有料サービスを追加していない。

**実装済み（ソフトウェア）：** 既存のハッシュ固定OpenCV検出器とローカル数字OCRを使い、白・黒を含む6艇を色に依存せず候補追跡する。数字の反復観測・カメラ移動・匿名追跡IDを関連付け、曖昧さ、競合、遮蔽、画面切替では欠測に戻す。未付番の艇も背景補正から除外する。実フレームSHAを保存し、映像ごとに識別器を作り直す。これは実艇の識別精度の認定ではない。

ローカル自動取込は原本を変更せず、私有キュー、実復号、計測報告、モデル接続結果まで別版で保存する。累積件数・バイト数による取得停止なし。T−15〜T−10を優先し、新着と締切を1件ごとに再確認する。解析済みで証拠待ちだった報告も、証拠がそろえば過去映像の処理より前にモデルへ渡す。単一writer・原子的上書き防止・中断証跡・同一入力の再推論防止を実装した。公式映像の取得機能とローカル入力処理は区別する。

**既存モデルへの接続済み：** ターン・出足・行き足・伸びの4特徴を、既存の `boat-observed-pairwise-factor-v1` / `boat-observed-pairwise-start-v1` の版 `0.3.0-VIDEO-EXPERIMENTAL` へ渡す任意の学習・推論経路を追加。公式8特徴と旧版の出力を保全する。現在レースの映像は展示後P1だけに用いる。係数は初期0、支持のある学習データから方向も学び、誤差区間が重なる艇同士は優劣に変換しない。画角・基準面・比較区間・時計・艇番・レース・原本の整合性と、呼出元による独立受領証の認証を要求する。入力作成→独立保存→予想観測時点→実推論を別の時刻で保持し、締切を越えた出力は採用しない。

保存された研究版2モデルは、既存5基準モデルと合わせて私有ビューへ読戻せる。閲覧時に再学習・再予想しない。報告自体は **UNVALIDATED/model_eligible=false**、研究版は **production_eligible=false** を維持する。画像上のpx/sを実速度・強さ・的中確率と表示しない。信頼する入力提供元と認証関数が未接続なら、CLIは待機・欠測理由を保存し、実予想を作ったことにしない。

**修正・独立再審査：** 数字の曖昧さ/競合による別艇への誤継続、匿名IDの型不一致、小さい有効検出、書込直後SIGKILLの二重リンク、誤差区間の重なりによる差分の増幅、比較区間の不一致、未来の学習受領証、未支持特徴の係数変更、文脈時刻の書換え、P0への展示混入、証拠待ち報告の締切前接続遅延を再現・修正。最後の締切回帰3件は別担当も実モデルの経路で再実行して成功した。

**検証：** 固定CV venvのPython全 **1,451件成功・skipなし**、対象Node94件成功。合成動画を実復号し、実際の候補関連付け処理へ制御した検出/数字観測を渡して6艇を追跡、6艇の直線計測、文脈の合成データ拒否、映像係数0、原本不変を確認。実NanoDet/Tesseractを使うCLI起動も確認したが、この合成動画では計測0件であり、実艇の識別成功とは呼ばない。合成保存ビューの390/1440幅の実ブラウザ操作12項目で、既存2IDの研究版と5基準版、元のTop8/SHA、6艇候補・欠測・未検証表示を確認。JS例外・変更系HTTP要求・画面外への横はみ出し0。合成の映像補足はブラウザ専用fixtureへ明示的に添付したもので、実映像の自動接続証明ではない。

全画面の320/390/1440/1920幅の操作は、コード・タイマー・待機上限を変えない再実行で **30項目成功**。初回の320幅「過去レース」クリックの30秒タイムアウトは失敗証拠を保全し、同じ操作の計測付き再現では成功した。初回の根本原因は未確定であり、根拠のない修正やタイムアウト拡大はしていない。

**GitHub CI確定：** 実装と別作業監査の統合SHA `981768b4a2f46076877202f7676c9639644e5624` のexact checkoutをログで確認。[Viewer42085233304](https://github.com/haji84/RACE-AI/actions/runs/42085233304) と既存AUTORACE42085233355がcompleted/success。通常Pythonは1,451件中任意CV44件skip、隔離CVは104件をskipなしで成功し、44件全ての再実行成功を照合した。全fixture付きブラウザ39項目、映像UI Node12件も成功。全選手取得ジョブは鍵未接続の明示HOLDでupstream GET0、暗号化復元はskipのため、取得成功として加算しない。このCI追記は文書と証拠のみで、実装・テスト30ファイルのSHAは不変。

**現在の稼働：** ローカル映像取込PID271439を `--follow --connect-models` で起動。実際の状態は `WAITING_FOR_AUTHORIZED_SOURCE`、公式取得false、実映像・予想出力0。これは新しい外部サービス・workflowではない。既存アプリPID157669（起動09:48:10 UTC）を停止・再起動せず、既存workflow405276784のrun42079188438（固定HEAD `3123f54ebea1b90eff453c322fd3009cd5a52097`）と自動予想RUNNING/continuous=trueを確認。既存288原本DBのSHAは `c40bead05533ace426188ea8a111b1e4a4a639283f576972ba276e14a3e8ff1a` のまま。予想workflow/triggerや本番係数をこの実装のために変更していない。

**未完成・外部条件：** 実展示映像の解析成功 **0件**、映像を使った実予想・実学習・改善実証 **0件**。通常の公式導線で試した住之江・多摩川・徳山の対象展示は、正常なプレーヤー初期化後も403/「この動画の視聴は許可されていません。」。津公式リンクのYouTubeはトンネル接続失敗、別の2場の通常入口も接続拒否/タイムアウトだった。拒否を別認証・URL推測・別プロキシで回避していない。全場が利用不可とは判断しない。利用可能な認可済み映像、6艇と走行区間の独立正解、未使用の実映像での識別/計測精度、実用上の強さの評価、締切前実予想の独立保存と未来公式結果の比較が必要。**今回の3項目を実運用まで完成したとは認定しない。** 実機Safariと98%の達成も未確認。本番モデル切替、main統合、一般公開、実投票は行っていない。

実行・検証の詳細は [展示映像の手順](BOAT_VIDEO_MEASUREMENTS.md) と [ソース・試験・受入の証拠](evidence/2026-11-06/boat-video-model-connection/verification.json) に記録する。以下は過去時点の監査記録として保全する。

---

# 2026-11-06 03:29 JST｜継続worker完走→新workerの第10巡を独立監査（当日予想追加なし）

**対象:** 既存Draft PR #71 / workflow `405276784` / ブランチ `feat/four-sport-forecast-audit-view-20261022`。確認時HEADは `3123f54ebea1b90eff453c322fd3009cd5a52097`。

**前runの確定完走:** [run 42066504421](https://github.com/haji84/RACE-AI/actions/runs/42066504421) は 2026-11-06 02:49:19 JST に `completed/success`。最終第24巡結果ZIP artifact `13439721825` は GitHub API digest/実ZIP SHA256 `afae2c1a4fedbe0b6b5fa3eb15a3f531ef9f121bef4a127173dac7ba3f8181fd` と一致、ZIP CRC正常。最終continuity ZIP `13439716866` も SHA256 `e209a3fe95364d70e90847511893aa87ff22e6e6bb363b246f9532b10834ecd0` と実バイト一致、CRC正常。`repeat-session.json` は `completed_round=24/prepared_round=null`、第24巡の別保存読戻しレシート日時2026-11-06 **02:49:10 JST**、当run公式GET実数206。直近の第13巡だけで完走扱いしたのではない。

**現在runの途中保存:** [run 42079188438](https://github.com/haji84/RACE-AI/actions/runs/42079188438) は 2026-11-06 02:54:41 JST起動、03:29 JST時点 `in_progress`。対象workflowの直近100 runから同時 `in_progress` はこの1件、`queued/pending/waiting` は0。第10巡 `status.json.round_no=10/updated_at=2026-11-06 03:24:31 JST` の結果ZIP artifact `13442406865` と対応P1 ZIP artifact `13442093519` をGitHubから別々に取得、実バイトSHA256はそれぞれ `7ffd8ad8a5a4ad6f66f828f0cab38fb81574b7180921ac43d0a1abe2a38e2f9c` / `768d9d201e309c38a4d291397ead7097dd0ef0094e50cf19ff4ed00921e46d84` でAPI digest一致・ZIP CRC正常。結果ZIP内 `current-p1-original.zip` と別取得P1 ZIPはバイト一致。 `first-p0-original.zip` と初回P0 artifact `13428142302` もバイト一致。初回索引 `docs/evidence/2026-11-06/p0-first-receipt.json` の元ZIP SHA/JSON SHAとも一致。過去原本の再生成なし。

**独立読戻し境界:** 第10巡結果ZIPは保存成功、内部sessionの `completed_round=9/prepared_round=10` と第1〜9巡の `verified_at` レシートまで確認。**第10巡の読戻し完了とrun全体成功はまだ認定しない**。当runの取得実数94、`halted_reason=null/source_wait=null`、公式結果原本 `official-result-observations.json=[]`。

**予想・結果・PDCA:** 当日13会場・156R。P0初回312モデル別予想（観測相性・ST重視相性の各156件）、P1=0、通常結果採点=0、LEARNED_SHADOW=0、未来同条件比較=0。 `forecasts.csv` と `model_coverage` はP0の312件で一致。 `national.json` は `NO_COMPLETE_EXHIBITION_IN_ORDERED_CANDIDATES`、予想条件の新規成立なし。次候補確認時刻は**08:20 JST**。 `automatic_learning.state=INSUFFICIENT_VERIFIED_RACES`、本日分の新規学習係数・精度改善を認定しない。未来156レースを未予想P1の不的中には数えず、開催前の回収率も作らない。16系統/4競技の全数運転、永久私有保全、学習版の前向き優位性は未証明。

**制約衝突は継続:** 取得実績206/94は各runとも240未満だが、実コード `source_limit=null/max_rounds=null/stop_at=null` とworkflow `timeout-minutes:360` は今回定期指示の240GET・24巡/65分と不一致。別のオーナー直接指示にある上限撤廃を、この監査で無断巻き戻していない。 `concurrency.group=boat-nationwide-cutoff-20261103/cancel-in-progress=false` は確認。停止条件回避の追加push、同run rerun、実行中runキャンセル、モデル本番切替、実投票なし。後続runも未予約。次の要点は朝の正式展示新規観測で初めてP1を凍結できるかの判定、および取得上限の実契約統一。

---

# 2026-11-06 02:16 JST｜11/06 第24巡完了workerから次worker第13巡への原本引継ぎ監査（新P1・採点は0）

既存Draft PR #71の監査。前run [42055132384](https://github.com/haji84/RACE-AI/actions/runs/42055132384) は 2026-11-06 01:37:54 JSTに completed/success、最終第24巡の結果artifact `13434787464` はAPI digest `892d448bcb0a95a06bc4dc122c3d6dec341ca55fef659a0a1895adf0144c7375` と実ZIP SHA256・CRC一致。最終continuity artifact `13434836595` もAPI digest `645c44e9acea9bc98a2d4cbaf856f49833ee3b33aeda1eabd5623983749edf0e` と実ZIP SHA256・CRC一致、内部 `repeat-session.json.completed_round=24/prepared_round=null`。当run公式GET実数221、ただし source_limit=null/max_rounds=null/stop_at=null を確認し、安全上限がコードで強制されたとは認定しない。

既存workflow405276784の後続 [42066504421](https://github.com/haji84/RACE-AI/actions/runs/42066504421) は確認時 in_progress、実行HEAD `0b400636041f435754d8d6c0c2c48ef7faaf6ab4`。対象workflowの確認済み他runにqueued/pending/waitingや並行in_progressなし。第13巡の結果artifact `13435569104`（API digestおよび実SHA256 `7f2cfd6dbf6695f360a09b838365d3aa9539020bbd01bacdf8e56f1087237202`）、別取得P1 artifact `13435813562`（`b842088ce95f41f5a8a210eea0cbebcfa232c77a06539f4e79f05f0cad64d8da`）は双方ZIP CRC異常なし、結果ZIP内 `current-p1-original.zip` とP1実ZIPがバイト完全一致。結果ZIP内 `first-p0-original.zip` も先行初回P0 artifact `13428142302` の元実ZIPとバイト完全一致。新しい初回P0を生成・上書きしていない。

第13巡 `status.json.round_no=13/updated_at=2026-11-06 02:16:05 JST`、継続 `completed_round=12/prepared_round=13` なので**第13巡は保存確認のみ、独立読戻し完了は第12巡まで**。11/06公式日程13場156レース、P0=312モデル別件（156R×2）、P1=0、公式通常結果採点=0、学習版予想=0、同条件成績比較=0、結果観測版=0。展示前であり的中率/回収率/損益は未算出。最新P1監査の次回候補確認は08:20 JST、候補の一部に `VENUE_PROGRAM_STATS_UNSUPPORTED_CONTEXT_ONLY` があり、出走表取得とP1の実生成は混同しない。

**安全上限の未整合：** 現行第13巡の公式GET実数111、保存契約の `source_limit=null/max_rounds=null/stop_at=null` は今回指定された240 GET・24巡/65分の制限と不一致。過去のownerによる上限撤廃記録と現在の定期指示が競合するため、実行中runの取消・上限の無断切替・停止条件回避・新トリガー・rerunは一切実施していない。実差分は前run最終24巡の認証と次run第13巡までの引継ぎ・保全検証のみ。新モデル/PR/workflow/課金/main統合/公開/実投票/本番自動切替なし。今後の展示後実予想・独立保存・結果照合・学習版前向き優位性の成立は未確認。

---

# 2026-11-06 01:29 JST｜展示映像の実験計測・私有保存・画面接続を実装、実映像の自動評価は未完成

既存Draft PR #71の同じブランチで実装した。途中の最新HEAD `24cc6f097452134d5bfe287c3ae1cd9204e5f39f` にあった別作業の監査追記をfast-forwardで取り込み、履歴を保全。新PR・外部タスク・workflow・モデル系統・有料サービスは追加していない。

**実装済み：** ローカル動画をFFmpegで実復号し、表示PTS、背景ホモグラフィによるカメラ補正、色の候補追跡、ターン・出足・行き足・伸びの画像上の計測を保存する。色は実艇の独立識別ではない。画面切替、遮蔽、同色複数候補、色の重なり、誤差以下の移動、スタート基準不足は欠測。報告はGit外の私有ディレクトリへ0600の改変検知付き別版として保存し、レース・締切・6艇すべての登録番号が一致する場合だけ既存viewへ補足する。原本のTop8・SHA・時刻・結果は変更しない。翌日取得のリプレイは締切後として表示する。

CLI `scripts/boat_video_analyze.py` と実行手順 [展示映像の実験計測](BOAT_VIDEO_MEASUREMENTS.md) を追加。既存画面のレース詳細→直前情報に任意の報告パネルを接続した。稼働中サーバーのasset許可表を変更・reloadせず、既に配信される `ui-model.js` 内へ一度だけ組み込んだ。報告がなければ既存表示を維持し、不正な任意JSONは照合不能として表示する。

**検証済み範囲：** 固定NumPy/OpenCVの隔離venvでPython全 **1,241件成功・skipなし**。Node契約135件＋表示/モデル22件成功。既存全画面の320/390/1440/1920幅の操作30項目成功。合成動画→実デコーダー→報告の私有保存/読戻し→稼働中アプリへのJSON読込を別途390/1440幅で操作し、4区間、証拠フレーム、合成ラベルを確認、JS例外・画面外への横はみ出し・変更系HTTP要求0。低解像度の負例は3項目を欠測に保ち、移動量を解像できる別の合成正例は4項目を計測した。正例はスタート線と区間を既知の生成軌跡から指定しており、実場の自動区間識別成功ではない。実映像の解析成功は **0件**。画像上速度の傾向の誤差は信号より大きい例もあり、強さや改善の認定には使わない。

独立審査で、遠近カメラ移動の誤追跡、緩い曲線の直線誤認、誤差以下の揺れ、複数色の重なり、途中の解像度変更、非ゼロ開始PTSの6件を再現・修正し、元の再現素材で再審査PASS。さらにPython/UI間の時刻形式と物理検証状態の不一致2件を修正・再審査PASS。既存ブラウザ試験の固定50ms待ちによる不安定さは、対象の状態応答が画面へ反映されたことを待つ試験へ修正した。

**未完成・外部条件：** 公式映像が存在しないとは判断していない。通常の公式BOATCAST導線で住之江11/5 12R展示を選択し、ブラウザ初期化不良を解消した後、正しい埋込SDK要求が **403/「この動画の視聴は許可されていません。」** となった。初期のプレーヤー単体403とこの通常操作の証拠は区別する。別の正規公開経路である津公式YouTubeチャンネルは `ERR_TUNNEL_CONNECTION_FAILED`、HTTP応答なし。拒否を別認証・URL推測等で回避していない。利用可能な実映像の供給、白/黒を含む6艇の識別、実場の基準線・走行区間と画角/時刻の独立照合、映像の常時自動収集から既存workerへの接続、強さの評価と前向き精度改善、実機Safariは未完成。全報告は **UNVALIDATED/model_eligible=false**。新しい動画特徴を予想・学習・正式成績へ投入していない。

**自動予想は継続：** 開発・テスト・pushのためにアプリPID157669や監視を停止・再起動せず、既存workflow405276784のrun42055132384（固定実行HEAD `f15448d0a00887cff9153a3398b18a3b0761a04e`）だけがin_progress、auto enabled/continuous=true、RUNNING、停止/エラーnullを再確認した。ローカル既存288原本DBのSHAは `c40bead05533ace426188ea8a111b1e4a4a639283f576972ba276e14a3e8ff1a` のまま。予想workflow/triggerを変更せず、後続を別予約していない。ユーザーの現在の上限撤廃と開発中継続の指示を、過去の監査文書にある旧制限で巻き戻していない。main統合・一般公開・実投票・本番切替なし。

[ソースSHA・検証・受入差分の証拠](evidence/2026-11-06/boat-video-measurements/verification.json)。**GitHubコードCI確定（01:35 JST）：** 実装SHA `326cb90e66b17239b7539c845a8ba577902f0fd6` のexact checkoutをjob logで確認。[Viewer run42065221293](https://github.com/haji84/RACE-AI/actions/runs/42065221293) と既存AUTORACE run42065221265はともにcompleted/success。通常Python discoveryは1,241件中任意CV14件skip、別の固定CV venvで映像関連70件をskipなしで成功、追加映像UI Node10件も成功した。ローカルの全1,241件skipなし実行とは区別する。この追記は文書と証拠だけで、実装ソースSHAは不変。以下は過去時点の監査記録として保持する。

---

# 2026-11-06 01:11 JST｜本日P0原本312件を照合、既存第15巡の保存結果を独立確認

**11月6日分の差分（前日の698件に加算しない）:** 公式日程13場156レースを対象に、観測相性・ST重視相性の既存P0 2モデル×156R=**312モデル別事前予想**が初回原本として保存済み。初回GitHub artifact `13428142302` のAPI登録SHA256と実ZIPバイトSHA256が `6f900ac94d433aa11bf5b73a70ae68cd6ecf8849000fbb0726b3abd7769e82fc` で一致、ZIP CRC正常。内包 `forecasts.json` のSHA256 `e9ef52b153f8648aedec59fb3233d2405528e862858b211b754801d409ce0860` は既存 `docs/evidence/2026-11-06/p0-first-receipt.json` に記録された初回索引と一致。元のサーバー登録時刻は **2026-11-06 00:27:45 JST**。第15巡の結果原本内 `first-p0-original.zip` は初回原本ZIPと**実バイト完全一致**し、後付け再生成ではないことを照合。P0 312件は2026-11-05の採点済み637件とは別の日の事前保存件数。

**既存run:** [42055132384](https://github.com/haji84/RACE-AI/actions/runs/42055132384) は確認時 `in_progress`。同workflow `405276784` の直近Actions一覧で `queued/pending/waiting` 後続runなし、他の同時writerなし。実行HEAD `f15448d0a00887cff9153a3398b18a3b0761a04e`。第15巡の結果artifact `13432322427` はGitHub API digest `74f7f5635aa55ce560ef5ace8e62db816b4dcde337a93c5fd8782829851a852a` と実ZIP SHA256一致、CRC正常。内包 `status.json.round_no=15`、`updated_at=2026-11-06 01:10:25 JST`、`bounded_repeat_session.completed_round=14/prepared_round=15`。**独立読戻し完了の証跡は第14巡まで**であり、最新第15巡の保存成功とrun全体の完走を混同しない。

**結果・学習・網羅:** 11/06対象156Rは確認時点で全て未来。基準P0=312件、展示後P1=0、通常結果採点0、学習版予想0、同条件の未来結果比較0。よって的中率・回収率・収支は未算出。第14巡公式予想ZIPは `NO_COMPLETE_EXHIBITION_IN_ORDERED_CANDIDATES`、`next_check_at=2026-11-06T08:20:00+09:00`。展示が未公表か取得不能かは各レースの実観測で要確認。P1がないことを外れ扱いしない。全16系統・他3競技の実接続・期限なし非公開保全・学習版の未来優位性は未実証。

**停止条件の明示的な衝突:** 現runの保存セッションは第15巡時点`requests_used=142`（累積954）、`source_wait=null/halted_reason=null`で、GET実績自体は240未満。しかし適用コードは`source_limit=null`、`max_rounds=null`で、workflow `timeout-minutes: 360`は今回指示された240 GET・24巡/65分の契約と一致しない。過去のownerによる撤廃記録とも競合するため、この監査は稼働中runを取消・上限回避・rerunせず、別後続を予約しない。誤設定のまま安全上限が実効的に守られたとは認定しない。モデル係数、過去買い目、原本、スケジュール、他タスク、新PR/workflow/課金/本番切替は変更なし。

---

# 2026-11-06 00:31 JST｜次worker42055132384への引継ぎ完了・11月6日朝版312予想の保存/読戻しを確認

オーナーの「次のWorkerへ引き継いで」に従い、前workerの正常終了・activeなし・最終原本/待機/カウンターを確認し、既存Draft PR71へ引継ぎ修正 `f15448d0a00887cff9153a3398b18a3b0761a04e` を適用した。[同じworkflow405276784の後続run42055132384](https://github.com/haji84/RACE-AI/actions/runs/42055132384)はin_progress。**第1巡がsuccess、第2巡へ進行**をActionsで確認した。別workflow・モデル系統・外部タスク・サービスは追加していない。

**実保存・独立読戻し：** 11月6日00:27:45 JSTに156レース×既存観測相性2モデルの **朝版312予想** を保存。P0 artifact13428142302の実ZIP SHA/API digestは `6f900ac94d433aa11bf5b73a70ae68cd6ecf8849000fbb0726b3abd7769e82fc`。結果/状態artifact13428811891の実ZIP SHA/API digestは `c21c4daaf077ee0dcc05ae8ea67a2523ef23cfccecf0060989fe33c6d577df29`。双方を再取得し、既存readerで日付・モデル・締切前時刻・原本形式を確認した。朝版2モデルの実保存であり、4競技/全モデル完備や展示後/T−15〜T−10保存の実証へ広げない。

前workerの累計 **812GET/47巡** をbaseとして継承し、第1巡結果snapshotは当run16GET・累計828GET、source_wait/halted_reason null、取得/巡回/時間上限null。結果ZIPはcommit前のprepared_round1/completed0を保存しており、それを最終状態とは呼ばない。第1巡の読戻し完了と次巡開始はActions側のsuccessで別確認した。既存アプリPID157669を維持し、auto enabled/continuous=true、state=RUNNING、active_run_id=42055132384、停止理由nullを確認した。[引継ぎ証拠](evidence/2026-11-06/worker-handoff-repair/successor-first-round-readback.json)。

旧原本を削除・上書きせず、監視processを終了・再起動せず、新workerへ渡した。新しいcompact最終artifactは当workerの正常終了時に発行されるため、その実レシートと次々workerによる受理はまだ未検証。ローカル実原本での旧32MiB契約互換は直下の修復記録を参照。main統合・一般公開・実投票・本番モデル切替なし。

---

# 2026-11-06 00:21 JST｜次worker引継ぎのサイズ不具合を修正、原本を保全して適用

オーナーの「次のWorkerへ引き継いで」に基づき調査した。前worker42047977632は2026-11-06 00:00:28 JSTにsuccessで終了したが、最終continuity artifact13427340610が **36,517,292 bytes** と旧32MiB読取境界を超え、既存supervisorが `SUPERVISOR_STATE_OR_CHECKPOINT_UNAVAILABLE` で待機していた。原因は過去のsource-control ZIPを次のZIPへ重複して含める構成だった。

**原本照合：** GitHub digest `50cb65bf1a99356b9fe3a5175fe0e4cecf789fae704d58895131afd0fc733777`、全137memberのCRC、session/state seal、既存125原本ZIPを照合。4巡完了・当run196GET・累計812GET/47巡、prepared_round/source_wait/停止理由null。698基準予想と392結果観測を保全し、原本の削除・再生成・カウンターの初期化はしていない。

**修正：** 既存の大きいcontinuityだけ128MiBまで受理し、digest/CRC/repository/run/sealと512MiB展開上限を維持。予想・結果ZIPの32MiB境界は変更していない。今後の引継ぎは同じworkflow・同じartifact名で、exact-byteのsession/continuity JSONを別ディレクトリへまとめ、過去ZIPを再梱包しない。元フォルダーの原本ZIPは保持する。実原本によるローカル確認では状態JSONのSHAを変えず **2,912,589 bytes** のcompact ZIPとなり、稼働中supervisorの旧32MiB読取契約で検証できた。これはローカル再梱包の試験であり、新しいGitHubレシートの実証とは区別する。

**検証：** Python全1,171件合格、最終の梱包関連47件・既存大サイズ互換99件合格、独立レビュー指摘残なし。[証拠](evidence/2026-11-06/worker-handoff-repair/)を保存。アプリ/監視PID157669を止めず、既存PR71の同じworkflowの後続へ適用する。新workerの実起動・新しいcompact最終artifactは適用後に別途確認する。新PR/workflow/外部タスク/モデル/課金/main統合/一般公開/実投票/本番切替なし。

---

# 2026-11-06 00:21 JST｜11月5日の全ボートPDCAを原本から再計算（新しい事前予想は0件）

対象は11/5全日。直近完了run [42047977632](https://github.com/haji84/RACE-AI/actions/runs/42047977632)、結果artifact `13425289339`、GitHub登録ZIP SHA256 `df47ed7d1c4c1c96a17015c72c4cb6fda052212b3098890f7fa589da66bb105f`を実ZIPバイトSHA・CRCで照合。継続artifact `13427340610`（SHA256 `50cb65bf1a99356b9fe3a5175fe0e4cecf789fae704d58895131afd0fc733777`）はcompleted_round=4、4巡分の受領記録を保持。実行はcompleted/success、ただし11/6の新P0・当日予想完走は未検証。過去P0/P1や係数は変更なし。

11/5の正規開催台帳144R、既存基準予想698モデル別行（P0=288、P1=410=82R×5）。最後のstatusは11/5 23:57:56 JST。通常結果のモデル別採点637行（HIT202/MISS435、前回既報546から+91モデル別採点、HIT195から+7、MISS351から+84）。除外/保留は異常32、返還14、結果待ち9、RESULT_REJECTED6モデル別行。独立した通常確定レースは131Rで、全日144Rの残り13Rは全件通常確定ではない。これは637レースや202レースの的中ではない。

固定8点×100円のモデル別参考実績（モデル間の仮購入額を合算して「実収支」としない）：
- P0 観測相性：37/131、仮投入104,800円、払戻98,240円、仮損益-6,560円、回収率93.74%。P0 ST重視相性：35/131、払戻79,130円、仮損益-25,670円、回収率75.51%。
- P1 予想済みモデル別の通常採点75R：A展示23/75（払戻36,580円、仮損益-23,420円、回収率60.97%）、Bコースモーター25/75（33,990円、-26,010円、56.65%）、C-lite33/75（63,070円、+3,070円、105.12%）、観測相性25/75（45,020円、-14,980円、75.03%）、ST重視24/75（46,050円、-13,950円、76.75%）。各モデル仮投入60,000円。これは予想済みだけの条件付き成績。
- **厳格な全対象監査との相違を保留**：共通の `all_race_top8_target` は131通常確定を分母にするが、P1についてRESULT_REJECTED扱いの常滑10R/11Rを除外し、73件のみ採用。C-liteは32/131=24.43%、Bは24/131=18.32%、Aは23/131=17.56%。同じ08-10/08-11でP0はRESULT_REJECTED、P1は通常MISS/HITという結果版判定の不一致を検出。別の保存結果revision・元SHA・捕捉時刻を再確認するまで全対象の正式勝敗・投資計算へ無理に統合しない。旧結果は削除しない。
- PDCA診断：P1 C-liteの42不的中は3着候補不一致21、1着候補外10、1・2着候補不一致11。Bの50不的中は23/14/13。C-liteの万舟は通常7機会中1捕捉、6未捕捉。高配当を選んで事後再予想しない。
- LEARNED_SHADOWは基準698とは別集計：132件保存、通常120モデル別ペア行＝60R×観測2系統。元33的中/仮受取74,790円、学習版35的中/85,050円（+2的中、+10,260円）。少数標本・多バージョン・学習元artifact全件の独立再確認未完了なので、統計的優位性も元モデルへの自動昇格も認定しない。最新学習対象133R、TRAIN100/VALIDATION33、結果情報リーク禁止維持。
- 他の3競技の11/5全対象の事前凍結原本と公式結果を今回同一条件で認証できていない。的中0扱いや捏造集計をしない。私有ZIPや買い目全文は公開GitHubへ転載しない。

次の独立工程：①常滑10/11Rのresult revision食い違いの解消、②他保留レースの公式結果・返還/異常再監査、③翌日新P0の初回レシートと既存5モデルの締切前予想、④C-liteの3着候補絞りと学習版を未使用未来レースで前向き比較。新タスク、新モデル、新PR、別workflow、公開、課金、main統合、実投票、予想改変なし。

---

<!-- LATEST_RECONCILIATION_20261106_0018 -->
# 2026-11-06 00:18 JST｜11/05最終4巡の独立照合、正式採点91件増と網羅・学習研究の差分（安全条件不一致のため新規起動なし）

**実行証明：** 既存workflow `405276784` の最新run [42047977632](https://github.com/haji84/RACE-AI/actions/runs/42047977632) は2026-11-06 **00:00:28 JST** に `completed/success`。実行コード `0fbb642b744319320f317f9bf0b34beed25fce4d`。同workflowの直近一覧で実行中/queued/pending/waiting **0件**。これは11/05を対象とする継続runで、11/06新レース予想成功とは異なる。

**最新完了巡回：** 第4巡の結果・PDCA ZIP artifact `13425289339`（保存2026-11-05 23:57:58 JST、実SHA256=`df47ed7d1c4c1c96a17015c72c4cb6fda052212b3098890f7fa589da66bb105f`）、第4巡のP1 ZIP `13426765625`（実SHA256=`bc64bf2ea39e2e01218f537f84525bbb0579e3eadf4c42291de1ee662cbe4a7c`）、最終continuity ZIP `13427340610`（実SHA256=`50cb65bf1a99356b9fe3a5175fe0e4cecf789fae704d58895131afd0fc733777`）をGitHub artifact API digestとダウンロード実バイトでそれぞれ突合し、ZIP CRC正常。結果ZIP内 `current-p1-original.zip` が別取得したP1 ZIPの実バイトと一致。最終 `repeat-session.json` で第1～4巡の別保存/独立読戻しreceiptあり、`completed_round=4`、`prepared_round=null`、第4巡読戻し2026-11-05 **23:58:05 JST** を確認。結果ZIP自身の `status.json.round_no=4` / `updated_at=2026-11-05T14:57:56.446847Z` は読戻し完了時点より前の保存記録として区別。

**11/05結果差分：** 基準予想 **698**（P0=288/P1=410、増分0）、通常結果採点 **546→637（+91）**、的中 **195→202（+7）**、不的中 **351→435（+84）**。保留は **61モデル別件**で不的中に加算しない。12場・対象144レース、締切済144、通常確定131、結果待ち4、結果拒否3、異常6（レース単位の状態）。P1の5基準モデル完備 **82/144レース**、欠測 **62レース×5=310モデル別件**を `coverage_audit` に残す。未公開展示の当時の入手可能性は証拠がなく、取りこぼしを消さない。 `forecasts.csv` 698行、モデル台帳合計698と一致。公式結果観測版数 **392**。

**11/05仮想成績・PDCA：** P1は各モデルの**通常採点75レースのみ**を8点×100円として評価。C-lite相当の当地・ST・コース重視モデルは33/75的中、投入60,000円・受取63,070円・仮想損益**+3,070円**・回収率**105.12%**。ただし全対象の通常確定131レース分母では**32/131=24.43%**（厳格な適格保存証明条件により条件付き33件とは異なる）。P1全5モデルの不的中245モデル別件の内訳は3着候補不一致88、1着候補外87、1・2着ペア不一致70。既存8点の配分変更はせず、未来レースで事前固定検証する研究課題とした。

**学習・未来比較：** 学習ユニーク133レース（学習100・過去holdout33）、観測相性2系統の研究係数版のみ。 `trained_observed_models.json` を保存、欠測特徴の係数は基準保持。 `LEARNED_SHADOW` 保存132モデル別件、通常結果による同条件比較 **110→120** モデル別行（60レース、学習版35的中・仮想払戻85,050円、基準33的中・74,790円）。本差は新規対照10行で変化しておらず、未来優位性の証明ではない。学習元artifact全件の独立再取得照合および統計的優位性は未完了。基準式・過去予想・正式買い目は未変更、本番自動昇格なし。

**継続起動判定：** 最終continuityは当run `requests_used=196`（予想43・結果153）で単独実績として240以下。ただし保存契約 `source_limit=null/max_rounds=null/stop_at=null` とworkflow `timeout-minutes=360` は、この定期指示の**240 GET、24巡/65分**という明示条件と一致しない。旧オーナー指示による撤廃記録とも衝突するため、今回の監査だけで勝手に上限を書き換えず、条件未整合のまま**新トリガー・rerunは実施しない**。11/06の新規公式開催、締切前展示取得、初回P0、別保存の成立は未検証。新run・新task/workflow/PR/モデル/課金/Cloudflare/Vercel/main統合/公開/実投票/本番切替なし。7日GitHub artifactは恒久私有保管ではない。他3競技、全16系統、全日無欠落、期限なし私有保全、学習版優位性は引き続き未達。

---

# 2026-11-05 23:47 JST｜オーナー指示で開発中の継続運転を再開、既存workerを停止しない

オーナーの直接指示「自動運転は開発中も止めないで」を受領し、先の取消についての意図確認待ちは解消した。既存Draft PR71の最新HEAD・別作業の監査追記を確認し、原本と文書を保全して取り込んだ。GitHubの前run41979370711の最終continuity artifact13395880555を認証し、prepared_round/source_wait/停止理由がnull、完了21巡、同run334取得・累計616取得/43巡を確認した。active/queued/pending/waitingなしを再確認し、既存triggerへ1件だけ追記した。

**実再開：** [同じworkflow405276784のrun42047977632](https://github.com/haji84/RACE-AI/actions/runs/42047977632)はin_progress。起動commitは `0fbb642b744319320f317f9bf0b34beed25fce4d`。新規workflow・外部タスク・モデル系統・有料サービスは追加せず、同じconcurrency/単一writerを維持する。アプリPID157669と監視processは終了・reloadしていない。コード22ファイルの検証済みSHAは不変、既存supervisor回帰25件合格。再開は新予想保存や24時間無欠落の証明ではなく、対象の締切前実生成・保存は次の適格入力から別に検証する。

**今後の開発方針：** 開発commit・テスト・source-only pushを理由に現行runや監視processを止めない。現workerは固定SHAのコードで完了し、検証後の差分を同じworkflowの次workerへ引き継ぐ。日付・物理workerの切替で原本、初回レシート、カウンター、取得元の待機を保全する。過去の監査文書に残る240/45取得・24巡/65分制限を、現在のオーナー指示に反して再適用しない。[運用方針](LOCAL_FORECAST_GENERATION.md)へ記録した。HTTP待機・真正性・締切・原本保存は継続し、未取得を成功や的中率98%へ変換しない。main統合・公開・実投票・本番モデル切替なし。

---

<!-- RESULT_SOURCE_RECHECK_20261105_2341 -->
# 2026-11-05 23:41 JST｜旧SOURCE_OR_PARSE_UNAVAILABLE 3競走の公式Web結果を再確認（正式採点への反映なし）

**今回の実差分は参照結果の独立確認であり、公式採点・予想追加・モデル改善の実証ではない。** 最新完了run `41979370711` / 第21巡の結果ZIP（artifact `13395351632`、実SHA256=`acaf98ae69cf9c1bdbdeccee306e3da0d0d04a31a3737fa229b253f15860a0b8`）は本確認で実バイトSHA256とZIP CRCを再照合し正常。予想ZIP `13395371515`、継続ZIP `13395880555`も登録digestと実バイトSHA256、ZIP CRC一致。結果ZIP内の `current-p1-original.zip` は別取得の予想ZIPに完全一致。内部 `status.json.round_no=21` / `updated_at=2026-11-05T07:02:18.662992+00:00`。保存済み基準698、通常採点546（的中195・不的中351）、未採点152、学習版132、前向き比較110行は**変更なし**。別イベントの原本結果を書き換えていない。

**今回直接読取したBOAT RACE公式の結果表示（11/05対象、公式公開日時はページ上から不明）：**
- `20261105-22-10` 福岡10R：通常1〜6着表示、3連単 **4-6-1 / 100円27,050円**。表示URL：https://www.boatrace.jp/owpc/pc/race/raceresult?rno=10&jcd=22&hd=20261105 。凍結P0 2系統（元 `13371295414`、保存 `2026-11-04T22:53:32Z`、締切 `2026-11-05T15:12:00+09:00`）の8点には4-6-1が含まれず、**正式読戻し/結果原本の別イベント保存まで未実施の参考照合**として保持。P1予想は同レースで保存0。結果側は先行原本で `SourceError: explicit official payout required` だった。
- `20261105-08-09` 常滑9R：**3-1-5 / 4,780円**、6号艇「エ」の異常着順表示。表示URL：https://www.boatrace.jp/owpc/pc/race/raceresult?rno=9&jcd=08&hd=20261105 。先行 `unsupported finish disposition` を単純な通常確定に変更しない。
- `20261105-03-12` 江戸川12R：**4-5-6 / 16,340円**、1号艇「転」の異常着順表示。表示URL：https://www.boatrace.jp/owpc/pc/race/raceresult?rno=12&jcd=03&hd=20261105 。先行 `unsupported payout-only result table set` を通常確定へ無理に昇格しない。

**採点保留の根拠：** 今回は公式Webページのテキスト独立確認だけで、公式HTMLの実レスポンス生バイトSHA・取得サーバー時刻を添えた結果原本の独立保存・新しい結果revision・runnerにおける整合性検証がない。したがって既存の `RESULT_PENDING` を自動で `MISS` にせず、`train/validation` への投入も行わない。とくに「エ」「転」は通常確定対象の例外として区別。学習済み候補の優位性は未証明。

**実行・安全境界：** この時点で対象workflow `405276784` の最近200件内で最新run `41979370711` は `completed/cancelled`、実行中/queued/pending/waitingなし。第21巡の独立読戻しは正常、第22巡の待機処理が `The operation was canceled.`。取消者・意図は取得できない。ワークフローの `cancel-in-progress=false` 維持を確認したが、`timeout-minutes=360` と先行 `source_limit=null/max_rounds=null/requests_used=334` は今回指定の240 GET・24巡/65分に不一致。キャンセル原因と矛盾した安全上限の解決なしに既存runをrerun/追加triggerしない。現時点のPR確認HEAD `0983db08e0bade9ee9eefa87e263333035828dfe` は他チャットによる変更を含むため、その履歴を消さない。新PR/別workflow/新モデル/本番切替/main統合/外部課金/公開/実投票なし。

---

# 2026-11-05 21:47 JST｜取消runの全21巡・予想/結果42原本ZIPを非公開Driveへ保全、全件独立読戻し成功

**今回新たに完了した実差分：** 既存run 41979370711 の第01～20巡の予想原本ZIP20件と公式結果・PDCA原本ZIP20件、計**40件**をGitHub artifactから無改変で再取得し、本人所有かつ共有なしの既存Driveフォルダへ**重複のない新規ファイルとして40件追加**。今夜追加のZIPは計**21,041,980 bytes**。先に保存済みの第21巡の予想・結果2件と最終継続ZIP1件を合わせ、このrunの**全21巡×2種=42件＋継続1件、計43 ZIP**が当該非公開フォルダで確認できた。ソースバンドルはこの42件に含めず、過去の別run全件・全学習元・全公式改訂履歴の長期保全完了とは呼ばない。

**原本真正性：** 新規40件すべてをGitHubから独立ダウンロードし、実ZIPバイトSHA256をGitHub API artifact digestと**40/40一致**、ZIP CRC異常0。Driveへ原本を再圧縮・編集・上書きせず保存し、**Driveから40件を別途ダウンロード**して元GitHub実バイトSHA256と全件一致、ZIP CRC異常0（40/40）。Driveフォルダメタデータ上、接続中ユーザーが唯一のownerで `shared=false` を保存前に確認。Private DriveのファイルURL/ID・アカウント・秘密値・生予想本文はGitHubへ転記していない。既存Drive保管3件は変更せず今回の40件に加算しない。

**予想実行は未再開：** 既存workflow405276784の最新run41979370711は `completed/cancelled`（16:05:36 JST）、最新第21巡の独立保存・読戻しは16:02:26 JSTに完了、22巡は取消、23・24巡は未実行。GitHub最新30件の実行一覧で同workflowの `in_progress/queued/pending/waiting` なし。取消者・意図の証拠なし。現行workflow `timeout-minutes: 360`、保存実行契約 `source_limit=null/max_rounds=null` および `requests_used=334` は本定期指示の240 GET・24巡/65分と不整合。停止回避のpush/rerun/設定無断変更は行わない。現在の新規実予想・公式採点・係数学習・前向き比較は**0件**、保存済み基準698予想・通常546採点・学習版132・比較110モデル別行は増分なし。統計的優位性・本番採用も未成立。

**残る外部条件：** 取消原因と相反する実行上限の解決、未来レースでの厳格な前向き比較、他3競技/16登録系統の実接続、他run分と独立学習元の期限なし非公開保全。今回保存を追加したのは既存Driveのみ。新タスク/新PR/別workflow/スケジュール/課金/Cloudflare/Vercel/main統合/公開/投票/本番自動切替なし。既存GitHub artifactの7日保持は変更なし。

---

# 2026-11-05 19:03 JST｜非公開Google Driveへ第21巡原本3件を新規保全、独立読戻しSHA一致

**今回の新規成果：** 以前のGitHub ZIP→Google Drive connector直結uploadは型不一致だったが、既存GitHub artifactを実バイト取得し、ChatGPT LibraryのGoogle Driveマウントを通じて**同一ZIPを再圧縮・内容変更なしで3件新規保存**できた。既存のファイルを上書きしていない。これまで報告していた「Drive追加0件」から**今回+3件**に改善した。

**保存先の安全確認：** 対象の非公開原本フォルダが、指定されたDriveフォルダと同じfolder IDであることを二つの接続経路で検証。接続中ユーザー＝唯一のowner権限、`shared=false`、別ユーザーへの共有権限なしを保存前に照合。公開リポジトリへ私有Drive ID・私有URL・アカウント情報は転記しない。

**GitHub API digest→ダウンロード実バイト→Drive保存→Driveから再取得した実バイトの独立一致（3/3）**：
- 第21巡P1予想原本（GitHub artifact `13395371515`）：54,811 bytes、SHA256 `17e44570cfb6dc8b9e50511c8a5018d4caffbb47033b743f67536b519a4c90de`、再読戻し一致、ZIP CRC異常なし。
- 第21巡結果・PDCA原本（artifact `13395351632`）：1,047,023 bytes、SHA256 `acaf98ae69cf9c1bdbdeccee306e3da0d0d04a31a3737fa229b253f15860a0b8`、再読戻し一致、ZIP CRC異常なし。
- 当run継続原本（artifact `13395880555`）：16,688,587 bytes、SHA256 `12cc88117f6bf486ec6fab14d6c3dd78634632b634eb20d9653755b24195cbca`、再読戻し一致、ZIP CRC異常なし。

**厳格な限界：** これは**3件の原本ZIPの非公開保存実証**で、過去全runの原本や全学習元・結果改訂履歴の永久保全完了ではない。Drive側の誤消去・所有権変更・保存容量・長期ポリシーまで保証していない。今日の既存workflow405276784に新runはなく、最新予想run `41979370711` は引き続きcompleted/cancelled、今回の新予想・採点は0件。最近30件のActions一覧で同workflowの実行中/待機中を確認せず。キャンセル原因と本指示の240GET/24巡/65分に対する現行`source_limit=null/max_rounds=null/timeout-minutes=360`の食い違いは未解決なので、**追加push・再起動・設定変更はしていない**。基準モデル・買い目・学習済み候補・過去P0/P1原本は無変更。2026-11-05第21巡の基準698件、通常採点546件、学習版132件、前向き110モデル別行は前回の保存値で、新規増分として加算しない。

---

# 2026-11-05 18:52 JST｜取消後の既存第21巡3原本を再独立照合、5モデルの損益要因を解析（新予想0）

既存Draft PR71 / workflow405276784の最新run **41979370711はcompleted/cancelled**。GitHub Actionsの直近一覧では同workflowにin_progress/queued/pending/waitingを確認できず。runの取消主体・意図は未解明のため、追加trigger、同run rerun、キャンセル解除はしない。最新第21巡の保存時刻は**16:02:18 JST**。以下は保存済み値の再検証と新しい内訳解析であり、18時台の新規レース予想・結果反映ではない。

**実バイト原本照合：** 予想ZIP artifact 13395371515 SHA256 `17e44570cfb6dc8b9e50511c8a5018d4caffbb47033b743f67536b519a4c90de`、結果・PDCA ZIP 13395351632 SHA256 `acaf98ae69cf9c1bdbdeccee306e3da0d0d04a31a3737fa229b253f15860a0b8`、継続ZIP 13395880555 SHA256 `12cc88117f6bf486ec6fab14d6c3dd78634632b634eb20d9653755b24195cbca`。3つとも本巡に改めてGitHubからダウンロードして実バイトSHA256・ZIP CRC一致を再確認。原本の書換・再生成なし。結果ZIP内の `status.json`、`forecasts.csv`、`model_coverage.json`、`coverage_audit`、`automatic_learning`、`learned_shadow_comparison` と公式結果履歴を読取。前回既報の基準698件、P1=410件、通常546採点（HIT195/MISS351）、学習版132件、比較110行に増分はない。

**通常採点済み同一70レースのP1モデル別8点×100円仮想収支（厳格な全対象分母とは別）：** local-start-course 33的中/70・受取63,070円・損益+7,070円、course-motor 25/70・33,990円・損益-22,010円、display-rating 23/70・36,580円・損益-19,420円、observed-pairwise-factor 25/70・45,020円・損益-10,980円、observed-pairwise-start 24/70・46,050円・損益-9,950円。各モデルの投入は56,000円。最良のlocal-start-courseでも37件不的中で、内訳は3着候補不一致19件、1着候補外8件、1・2着組み合わせ不一致10件。次のPDCA検証対象は**既存8点内の3着組合せの選び方**であり、新モデル追加や後付けの8点書換はしない。なお全対象厳格判定は17:18記録の98レース分母/適格P1=68を使用すること。70件条件付き率を全対象的中率と呼ばない。

**学習版対照：** 異なる55レース・2系統110行を保存済み結果から再集計。学習版35的中/仮受取85,050円、元版33的中/74,790円（学習版+2・+10,260円）。Top8の集合変更54行、学習版のみ的中3行、元版のみ的中1行。統計的優位性は未確定、正式採用なし、検証・学習の分割と過去結果の書換禁止を維持。公式結果のsource/parse未確定3レースは、未確認として除外したまま。

**保全の実際：** 本人Drive保管フォルダは接続中アカウントがowner、`shared=false`と権限メタデータから確認。しかし、新ZIPのDrive追加は**0件**。GitHubコネクタのZIPファイル参照をDrive uploadへ渡す際、Driveツールの入力型はstringなのに処理側がconnector file reference objectを要求して拒否することを複数形式で再現。元ZIPを変換・再圧縮して代用せず、新規保存成功とは主張しない。7日artifactの恒久保全は未達。

**再起動見送り理由：** 現行workflowは同concurrency・`cancel-in-progress: false`だが`timeout-minutes: 360`、既存保存セッションは`source_limit=null/max_rounds=null/stop_at=null`。本タスク指定の240 GET・24巡/65分と衝突。取消原因・安全上限の整合が未確定のため、追加pushを行っていない。既存5基準モデルの重み・式・買い目、新PR、新workflow/スケジュール、外部クラウド、課金、main、公開、実投票、本番自動採用は変更なし。

---

<!-- BOAT_SUPPLEMENTAL_CONTEXT_20261105 -->
# 2026-11-05 18:39 JST｜公式コメント・展示観測・進入条件別成績の収集を既存PR71へ追加（映像評価・98%は未達）

オーナーの追加指示に基づき、既存の取得・保存・表示経路へ補足観測を実装した。新規PR・Issue・外部開発タスク・workflow・モデル系統・有料契約を作成せず、固定モデルの係数・順位計算・過去原本を変更していない。今回の追加値は**補足観測**であり、学習済み特徴や精度改善を認定するものではない。

**実装済み：** 展示未公開でも公式直前情報から体重・調整重量・チルト・プロペラ表示・部品交換・気温/水温/風速/波高/風向表示を取得。展示タイム・STのF/L原文・展示での表示位置を別記録とし、本番実進入と混同しない。ピットレポートは選手/取材者の帰属と原文を保持し、明示的な提供なし・構造未対応・取得待ちを区別する。全項目に元URL・SHA・実取得時刻・公式の締切を付け、公開時刻不明を取得時刻で代用しない。

**自動取得の接続済みコード：** 既存巡回で直前情報・コメントを収集し、前日の公式B番組/K結果を同じGET計数・HTTP待機制御で取得する。検証済みの日次キャッシュは追加GETなしで再利用し、既存artifactからの復旧と次巡へ引き継ぐ。未公開404はRetry-After付きの未取得状態を保持し、401/403/429を別URLで回避しない。補足データの不備やworker引継ぎは、完成した予想・確認済み原本の継続保存を妨げない。特別開催の追加タブに既存の予想用統計パーサーが未対応でも、同じ原本の正式な出走者・締切だけを別途確認し、補足観測を取得する。**この場合のP1予想は未対応のまま**とし、統計値や予想を作ったことにしない。

**進入履歴の実集計：** 実取得した2026-11-04のB/K原本を日付・場・レース・登録番号・実際の締切で照合し、通常129レース/774選手出走、除外15レース（非通常着順9、異常/未記録スタート6）を確認。内へ入った観測42、外枠艇に内側へ入られた観測44。自分が内へ入った時、外へずれた時、外枠艇が内側にいた時、内へ入った艇がいる時の実コース別に出走数/1着/2着内/3着内を集計し、率は件数から算出する。0標本の率はnull。前付けの意図・抵抗・因果的な強弱の証明ではない。現在の接続は1日分で、長期の強さや今回の進入を推定できる蓄積量ではない。

**実接続・画面の証拠：** 公式11GET（全200、予想生成0）を私有原本として保存し、3レースの補足観測を既存アプリの直前情報へ接続。公式コメント3件、あるレースの展示6艇分のタイム/STを確認した。後者は締切後の取得であり、締切前予想に後付けしていない。スマホ390px/PC1440px×3レースをブラウザ操作し、出典SHA・コメント・展示値を照合、横方向のはみ出し0、POST0、外部リクエスト0、画面エラー0。保存予想830件の全フィールドと結果履歴が元の私有投影と一致し、native288件DBのSHAも `c40bead05533ace426188ea8a111b1e4a4a639283f576972ba276e14a3e8ff1a` のまま。実HTML/LZH・コメント本文・予想・画面画像はGitへ入れず、件数/SHAの[証拠](evidence/2026-11-05/boat-supplemental-observations/)だけを保存した。

**検証：** 最終Python全件 **1,154件合格（241.330秒）**、JavaScript全件 **190件合格（fail/skip 0）**、実パーサー出力との型連携を含むブラウザ回帰11件合格。独立レビューで指摘された不正な成績率の受入、後続観測でコメント/履歴が消える問題、任意コメントのworker引継ぎで完成予想を失う問題、任意キャッシュの不備で原本継続保存を妨げる問題を修正し、回帰テストを追加した。手動JSONに不正な補足データが含まれても既存画面を壊さず、不可能な率や時刻矛盾を表示しない検査も追加した。独立レビューは修正後に指摘残なし。

**未完成・未実証：** 展示映像からのターン・出足・行き足・伸びの自動計測/評価、数値の計測校正、十分な長期進入履歴、追加観測を使った学習/前向き精度改善、全レース×全モデル×4競技の実運転、実機Safari、98%の全レース三連単8点的中はいずれも未達。選手コメントの感想を走行性能の実測値へ変換しない。

**私有アプリへの適用確認：** 既存8765アプリを同じGitHub監視モードで再起動し、原本の自動表示のまま390/1440px×3レースを再操作。実パーサー出力を受理し、生成ボタン非表示、原本Top8不変、締切前/後表示、POST0/外部要求0/画面エラー0を再確認した。予想ワークフローは起動していない。

**運転・外部確認待ち：** 最新の実予想run41979370711は16:05:36 JSTにcancelledのまま。停止操作の意図に関する回答は未着であり、今回もtrigger追加・rerun・取消解除を実施していない。追加した自動取得コードの再開後の実連続稼働は未検証。環境設定の再公開、main統合、アプリ一般公開、実投票、本番モデル切替は行っていない。GitHub artifactの7日保存を長期私有DBと見なさない。

---

# 2026-11-05 17:18 JST｜全レース・三連単8点・98％目標を固定し、履歴入力と全対象評価を実装（98％未達、実運転適用待ち）

オーナーが目標を「全レース・三連単8点で98％」と明示した。これはHit@8_allの目標値で、各レースの的中確率98％という表示・将来保証・実投票の承認ではない。既存PR71の最新HEADfb57ec3と外部更新を取り込み、既存モデル系統と係数・順位式を保って実装した。新PR/Issue/外部開発タスク/workflow/モデル系統/課金/配備なし。

**実装したこと：** 既存の独立認証済み結果ZIPから、予想時点以前に確認できた登録番号別の直近着順・実STを既存観測2系統へ任意入力として接続。対象レースの結果、予想時点後の取得、結果改訂の重複、F/Lをゼロ値扱いする入力を防止する。親artifactの実SHA・受領証・実読戻し時刻と観測membershipを保持し、後続原本を復元する際も親ZIP由来の独立proofと照合。単なる自己hashを出典認証とはしない。確認済みの実進入コースは0件なので、コース別2項目はNO_VERIFIED_COURSEのまま。枠番/DOM順から推測しない。データは取得済みの疎な履歴で、選手の全戦歴とは呼ばない。

既存coverage_auditへ全レース8点の目標評価を追加した。通常確定した共通レース分母をモデル/時点/基準・学習版ごとに用い、未予想・時間超過・原本不整合はNO_PRE_CUTOFF_FORECASTとして別計数しつつ全対象的中への寄与は0。予想済みだけの条件付き率は別に残す。5モデルの買い目和集合を8点と数えず、結果を見て当たった版を選ばない。結果待ち/不明/返還/異常/未来は件数と範囲を明示。Wilson区間は記述統計で、相関するレースの独立性や未来98％の証明にはしない。

**実原本での確認：** 第21巡結果artifact13395351632をSHA/CRC/既存readerで読戻し、公式サイトGET0・予想再生成0で旧保存値を評価。16:02:18時点の144対象は締切済110/未来34、通常確定評価98、結果待ち6/不明2/特別4。P1は各基準モデル68件が適格、30レース分が未予想等として分母に残り、全対象率は23〜32/98＝**約23.5〜32.7％**。最高P0も33/98＝約33.7％。これは1日分の途中評価であり、98％は未達。旧記録のP1採点70件と率33〜47％は予想済みだけの条件付き集計で、新指標はschedule/cutoff/通常結果を同条件で厳格照合した値。過去の買い目や通常採点結果を上書きしていない。

現時点の未来保存予定23レース/138出走枠に対する履歴入力dry-runでは、23枠で直近着順/STの2項目を構成できた。各1過去レースのみの疎な履歴で、精度改善の実証ではない。原本830件、既存モデル係数、過去Top8、実投票台帳は変更しない。履歴は次の予想入力と将来結果からの学習にのみ使い、過去の予想を作り直して成果とは数えない。

**検証：** 最終凍結Python **1074件成功**。履歴なしの旧bundleは変更前literal digestと一致、既存archive/learning/coverage読取も回帰成功。独立審査で、未来の結果改訂が分母を縮める問題、float/bool券、履歴証拠を除去して旧形式へ戻す完全再hash偽装を発見・再現・修正し、再審査PASS。UI/ブラウザ/実機Safariをこのbackend変更で再試験したとは扱わない。検証済み確率・回収率表示や本番学習版への切替は追加していない。

**実行状態は停止中：** GitHub run41979370711は16:05:36 JSTにcancelled、第1〜21巡のstepはsuccess、第22巡の待機で取消。取消主体・意図は未確認で、既存supervisorはREVIEW_WAITを保持。本人による停止だったかをこのチャットで確認中。停止意図の確認なしに新規trigger/rerun/キャンセル解除を行っていない。今回のコードは既存PRへのレビュー可能な改良で、新履歴を使った締切前実保存や98％改善は未実証。4競技全運転・全日無欠落・恒久私有保管・実機Safariも未完成のまま。

[全レース8点の保存実測](evidence/2026-11-05/all-race-eight-learning/saved-all-race-assessment.json) / [実履歴入力dry-run](evidence/2026-11-05/all-race-eight-learning/history-input-dry-run.json) / [1074テストとソースSHA](evidence/2026-11-05/all-race-eight-learning/verification.json)。以下は各時点の履歴として保全する。

---

# 2026-11-05 17:13 JST｜取消runの全21巡予想・結果ZIPと継続原本を独立照合（起動保留）

対象: Draft PR #71 / branch `feat/four-sport-forecast-audit-view-20261022` / workflow 405276784 / 最新確認HEAD `f8089a33fd5e768deff156e1aaa3c265b1fb4171`。Actions全run直近30件を再取得し、このworkflowのin_progress/queued/pending/waitingは確認範囲で0件。最新run `41979370711`はcompleted/cancelled（16:05:36 JST）であり、正常終了runとして扱わない。Job logの第22巡待機stepに `The operation was canceled` を確認。誰が取り消したか、なぜ取り消されたかはActions記録からは不明。

**新しく独立完遂した整合性監査（17:13 JST）：** 取消runの第1〜21巡の予想ZIP **21件**を個別に再ダウンロードし、GitHub側のcontinuity `receipts` 登録SHA256と実バイトSHA256、ZIP CRCをすべて照合。結果・PDCA ZIP **21件**も別々に再取得し、同じreceiptのSHA、ZIP CRC、内部status.round_no=1..21と、各ZIP内 `current-p1-original.zip` が該当巡の予想ZIP実バイトと完全一致することを検証。前runから持ち越された継続ZIP `13395880555`（SHA256 `12cc88117f6bf486ec6fab14d6c3dd78634632b634eb20d9653755b24195cbca`）の内包旧予想原本ZIP **104件**も個別に展開し、同梱receiptの実SHA/CRC一致。旧104件＋当run21件の予想原本計**125件**の照合に不一致0件。結果ZIPの予想・採点件数は途中で減少なし。

**第21巡の成功確定範囲を修正：** 第21巡の結果ZIP内 `status.json` は保存時点の `completed_round=20/prepared_round=21` だったが、取消後に保存された継続ZIPの `repeat-session.json` は `completed_round=21/prepared_round=null` と21個の `verified_at` 付き対証跡を保持する。したがって**第21巡の独立読戻しまで完了**、第22巡は待機中キャンセル、第23・24巡はskipped。run全体はキャンセルのまま。最後の保存済み結果は `round_no=21/updated_at=2026-11-05T07:02:18.662992+00:00`（16:02:18 JST）、基準698予想（P0=288/P1=410）、通常546採点（HIT195/MISS351）、研究学習版132件、前向き同条件110モデル別行。これらは**前回既報の保存値の再検証であり新規増分ではない**。

**継続判断：** 上記は予想原本125件と当runの結果原本21件の整合性検証であり、過去の全結果・全学習元artifactの再ダウンロード、Drive保全、取消主体の特定、作業HEADと当run HEADの完全互換性までは未確認。現HEADのコードは `requests_used=334/source_limit=null/max_rounds=null/stop_at=null` の実行契約で、今回の明示された**公式GET240・24巡/65分・1巡45/最大3レース**という条件と矛盾する。別チャットからの上限撤廃変更を、この監査のために無断巻戻しせず、取消run rerun・新トリガー・他workflow・新PR・新モデル・本番切替は**一切実施しない**。上限を回避する再起動は認めない。再開には矛盾する実行契約の解決、取消原因の確認、原本と学習元の残照合が必要。

予想・採点の既存数字を新成績として加算しない。artifact7日保持は恒久私有保管ではなく、全競技全モデル、全日P1無欠落、学習版の前向き統計的優位性は引き続き未実証。新タスク/頻度/PR/workflow/課金/main統合/一般公開/実投票/本番自動切替なし。

---

# 2026-11-05 16:46 JST｜run取消を検出、第21巡の保存ZIPを独立検証（継続起動保留）

対象：既存Draft PR #71、workflow 405276784、branch `feat/four-sport-forecast-audit-view-20261022`。今回監査でPR HEAD `03df29ce161aa926da2ae53a82d30e8dfccd56cd`、状態文書元blob `678e0a25dfb375b0d67b3a02c12bbe43391ef444`。全Actions直近30runから当該workflowのin_progress/queued/pending/waitingは0件。最新run `41979370711`（実行HEAD `5ef86817daea89544d03f462f58110e1222a9518`）は**2026-11-05 16:05:36 JSTにcompleted/cancelled**。Jobログで第1〜21巡のstepはsuccess、第22巡の「Wait for next deadline scan or worker handoff」は16:03:21 JSTに `The operation was canceled`、23〜24巡skipped。取消操作の主体・原因は未確認。今回run再実行・追加トリガー・キャンセルなし。

**今回取得した最新保存第21巡の実バイト照合：** P1予想 `boat-national-cutoff-41979370711-cycle-21`（artifact 13395371515、保存16:02:11 JST、SHA256 `17e44570cfb6dc8b9e50511c8a5018d4caffbb47033b743f67536b519a4c90de`）／結果PDCA `race-existing-cycle-41979370711-cycle-21`（artifact 13395351632、16:02:20 JST、SHA256 `acaf98ae69cf9c1bdbdeccee306e3da0d0d04a31a3737fa229b253f15860a0b8`）／取消後の継続ZIP `race-cycle-continuity-41979370711`（artifact 13395880555、16:03:23 JST、SHA256 `12cc88117f6bf486ec6fab14d6c3dd78634632b634eb20d9653755b24195cbca`）。3件ともGitHub API digestと実SHA一致・ZIP CRC正常。結果ZIP内`current-p1-original.zip`は別取得P1実バイトに一致。継続ZIPの内包元ZIP104件の各SHAは内包receiptと全件一致、CRC異常なし。ただし追加当runの21個のP1元ZIPは継続ZIP内に直接同梱されず、**全原本復元・中断再開の完全整合性は未認定**。

**前回15:42第11巡→今回16:02第21巡の実保存差分**（重複レースでなくモデル別件数）：基準5系統668→**698（+30）**、P0=288不変、P1=380→**410（+30、82レース×5）**。通常採点504→**546（+42）**、HIT186→**195（+9）**、MISS318→**351（+33）**。保留は結果待ち123・異常18・返還7・RESULT_REJECTED4で、MISSと混同しない。`forecasts.csv`698行、race_id/phase/model重複0、`model_coverage.total_saved_forecasts=698`一致。公式結果観測247版。 `status.json.round_no=21/updated_at=2026-11-05T07:02:18.662992+00:00`、ただし`bounded_repeat_session.completed_round=20/prepared_round=21`なので第21巡の保存成功と継続完走を区別する。

研究学習版120→**132**（+12）、確定結果の前向き同条件比較98→**110モデル別行**（+12、55レース×2）。同じ110行で基準33的中・仮払戻74,790円、候補35的中・85,050円（候補+2的中、+10,260円）。一意の通常結果100レースをtrain75/validation25とした`FITTED_SHADOW_ONLY`候補。全学習元artifactを今回独立再取得しておらず、統計的優位性は未証明、本番採用なし、基準5モデル・過去買い目は不変。網羅監査は144対象・締切済110・未来34・P1五系統完備77レース、締切済未保存33レース×5＝**165モデル別行**。未公表展示が予想時点に取得可能だったかは未検証で、分母から除かない。

**停止と設定衝突：** 実原本では`requests_used=334/source_limit=null/max_rounds=null/stop_at=null`、本定期指示の240GET・24巡・65分と不一致。別途の承認変更をこの監査で勝手に巻き戻さず、cancelled runのrerunや停止条件回避の後続pushも禁止して保持。4xx/429・原本不一致が原因とは断定できない。Driveの新規保存、owner/shared再認証、全学習元の独立読戻しは今回未実施。GitHub7日artifactと1日ソースZIPは恒久の非公開保存ではない。他3競技・全16系統・全日P1無欠落・期限なし保全・学習版の前向き優位性は未完成。新タスク/頻度/workflow/PR/モデル/外部サービス/課金/main統合/一般公開/実投票/本番自動切替なし。

---

# 2026-11-05 15:44 JST｜実第11巡回の独立ZIP再照合と前向き比較の更新（実行中runの途中保存）

対象は既存Draft PR #71 / 既存workflow405276784 / run `41979370711`。監査時PR HEADは `4f7d813a92e5403fe385b7cfdff626616f0f30e3`、実行run HEADは `5ef86817daea89544d03f462f58110e1222a9518`。Actions全run一覧で同workflowのin_progressはこの1件のみ、queued/pending/waitingは確認範囲で0件。先行のrun41967896991はcompleted/success、失敗run41979177157は再実行しない。追加push・新run予約・実行中キャンセルなし。

11巡目にGitHubへ保存された予想ZIP `boat-national-cutoff-41979370711-cycle-11`（artifact 13393853194、15:42:11 JST、ZIP SHA256 `c64212aaaf61a9cf0c744d5d9200426ce138fbbad4bb5279aa883a134facd4dd`）と結果・PDCA ZIP `race-existing-cycle-41979370711-cycle-11`（artifact 13394860218、15:42:19 JST、ZIP SHA256 `2a41795fd97b967e1b8445c0061273778382f2c6d9e9ee0b8c995eb7dddb4d03`）をコネクタから**実バイトダウンロード**し、各GitHub API digestとSHA256完全一致、ZIP CRC正常を確認。結果ZIP内 `current-p1-original.zip` の実バイトも別取得P1 ZIPと完全一致。これは保存済み第11巡のartifactであって、run全体はin_progress、`session.completed_round=10/prepared_round=11`。第11巡の継続receipt完了は未認定。

**第1巡（15:21:51 JST）保存原本からの実差分：** 基準5モデル643→668件（+25、P0=288不変、P1=355→380、**新規5レース×5モデル**）。`forecasts.csv`は668行、`model_coverage.total_saved_forecasts=668`と一致。通常結果採点489→504件（+15、HIT182→186、MISS307→318）。未確認はMISSにせず、今回の別保存ZIPに結果待ち135、異常18、返還7、RESULT_REJECTED4を維持。公式結果観測205→227版。基準予想・P1はそれぞれ異なる競走数/モデル別件数と区別する。11巡目の`status.json.round_no=11/updated_at=2026-11-05T06:42:17.706091+00:00`、予想原本の初回保存時刻・締切を保持した。

研究学習版は110→120モデル別予想（+10）、通常結果での同条件ペア96→98行（異なる49レース、+1レース）。98行で元31的中・仮払戻73,250円、研究候補33的中・78,590円。差は候補+2的中・+5,340円で第1巡との差は拡大していない。研究用の学習可能93レース、train70/validation23、`FITTED_SHADOW_ONLY`、本番自動切替なし。学習元artifact全件独立再取得と統計的優位性の証明は今回行っていない。過去8点・基準5モデル係数は不変扱いであり、係数学習成功を精度改善の証明としない。

`coverage_audit`: 対象144レース、締切済105、未来39、展示後5モデル完備73、締切済未保存32レース×5系統＝160モデル別行を残す。展示の当時の取得可能性は未検証。16系統・4競技の実入力と前向き全対象、長期の本人限定外部保全は未完了。Driveへの新規保全・独立読戻しは今回行っていない。7日GitHub artifactを恒久私有DBとしない。

**取得・継続契約の指示不一致を保全：** 本定期指示は公式GET240/1巡45、24巡/65分での制限維持を指定。一方、現に稼働中の別途オーナー承認のコード/当該結果ZIPでは `source_limit=null/max_rounds=null/stop_at=null`、本run `requests_used=197`、前run含む`lifetime_requests=479`、`halted_reason/source_wait=null`。本監査は矛盾を無断上書き・回避せず、実行中writerに追加の後続を積まない。API 4xx/429・真正性/日付保護の詳細な実挙動は今回の独立再現対象外。main・課金・公開・実投票・新workflow/PR/モデル/タスク/スケジュール変更なし。

---

# 2026-11-05 15:24 JST｜連続予想版を既存PR71へ適用・実20予想を自動保存、1レースは締切13分22秒前

オーナーの「その上限や停止もなし」「常に新しいレース」「できれば締切15〜10分前」に基づき、既存Draft PR #71へ連続版a1b980aと起動修正**5ef86817daea89544d03f462f58110e1222a9518**をpushした。[同じ既存workflow405276784のrun41979370711](https://github.com/haji84/RACE-AI/actions/runs/41979370711)は稼働中。**第1巡がcompleted/success、第2巡へ進行**をActions APIで確認。writerはこのrun1件、追加queued/pending/waitingなし。新PR・Issue・外部開発タスク・workflow・モデル系統・サービス契約は作成していない。

**実保存を確認したこと：** 15:21:38 JSTに4レース×既存基準5モデル＝**20予想**をボタン操作なしで新規保存した。従来の3レース打切りを超えている。15:35締切の1レースは**13分22秒前**に独立GitHub artifactへ保存し、実取得→生成→保存の時系列を確認。残り3レースは目標後の遅延fallback（締切前4分22秒/5分22秒/7分22秒）として区別し、T−15〜T−10達成へ水増ししない。15:21:38のP1 ZIP13393745796の実SHA/API digestは6e642d2996a20b79febb0b479439c6e7476da9d59b8b0a5a83681b4cea93747f。本人の実機表示受領時刻は未証明。

別保存の結果ZIP13392858916（15:21:53 JST、SHA48558655011292f84a6a996a8f28d006d33200beaf47a4b78a6c7f338224d737）から、実runの **source_limit=null / max_rounds=null / stop_at=null**を直接確認。取得は実44回（予想26/結果18）、先行282回を保持してチェックポイント累計326回、source_wait/halted_reasonはnull。物理workerの11:47:13 UTC handoff時刻は継承境界であり論理運転の終了時刻ではない。結果ZIPはrepeat-complete前のprepared_round=1を含み、GitHubの第1巡success/次巡開始で独立ZIP読戻し完了を別に確認した。現run全体の完了・24時間無欠落・実際の次batch自動引継ぎ完了はまだ主張しない。

**アプリ表示まで確認：** 同じクラウド内の既存loopbackサーバーをGitHubモードへ切替え、監視processを実起動。continuous=true/state=RUNNING、取得/巡回/時間上限nullで同runを監視し、静的なコード対応だけで終えていない。15:24時点の私有表示は**144レース・753予想（基準643/研究学習版110、P0 288/P1 465）・結果観測205版**。旧725件すべてのSHA/Top8/全順位/初回保存時刻/原本参照が不変で、新規28件＝基準20＋研究学習版8。未取得の対象総数は不明として表示し、全モデル網羅や精度改善を認定しない。

390/1440幅の実ブラウザでP0/P1の保存件数・選択原本SHAをAPIと照合し、自動表示、生成ボタン非表示、POST0・画面エラー0を確認。実スクリーンショットは本人私有領域のみ。旧nativeの288件DB SHA c40bead05533ace426188ea8a111b1e4a4a639283f576972ba276e14a3e8ff1a・元取得3回を保全し、native入力providerを起動せず二重生成していない。

初回run41979177157は、本番日付の環境変数を合成未来日テストへ渡す配置ミスで事前試験1件が失敗した。公式GET/新規予想0のまま終了。原因を再現し、実日付pinをunit test後・原本preflight前へ移動、関連160件成功を確認して5ef8681で修正した。修正版のViewer CI41979378870、AUTORACE CI41979378874はいずれもsuccess。全Python1036/Node179/合成39操作群の検証を迂回して本処理へ進めていない。

| 区分 | 現状 |
| --- | --- |
| 完了 | 論理上限撤廃、T15/T10優先・全適格候補巡回、待機/カウンター/原本の継承、監視process起動、初回20実予想と別結果保存、753件の実画面読戻し |
| 継続検証 | 24巡/65分超の実運転、実際の次batch/翌日引継ぎ、全日P1無欠落、前向き精度改善の優位性、私有保管の継続性 |
| 未完成・外部条件 | 他3競技の適格な当日入力、全16系統×全レース実運転、実機Safari。クラウド停止中の稼働は保証せず、取得元のRetry-After/認証/真正性の要確認は守る |

main統合・環境再公開・アプリ一般公開・実投票・本番モデル切替・追加課金なし。[実20予想と保存余裕](evidence/2026-11-05/continuous-deadline-forecast/applied-first-p1.json) / [実run上限値・累計](evidence/2026-11-05/continuous-deadline-forecast/applied-runtime-policy.json) / [監視と単一writer](evidence/2026-11-05/continuous-deadline-forecast/applied-supervision.json) / [725件の原本不変](evidence/2026-11-05/continuous-deadline-forecast/applied-original-preservation.json) / [実画面照合](evidence/2026-11-05/continuous-deadline-forecast/applied-browser-readback.json)。以下は各時点の履歴として保全する。

---

# 2026-11-05 15:14 JST｜連続予想版の最終検証・実原本725件の画面接続（反映直前）

固定GET・論理24巡/65分/日付停止の撤廃、T−15〜T−10優先、既存workerの自動引継ぎと私有表示を実装。凍結ソースでPython **1036件成功**、Node **179件成功**。合成ブラウザは320/390/1440/1920幅・**39操作群/60PNG**、エラー0、元サイトGET0、生成POSTなし。最終状態ラベル変更後も自動表示4群を再検証した。複数agentの独立レビューで見つかった空のP0追加ID・初回取得のhandoff境界・checkpoint欠落・403回復期限・学習版別名入力の再利用判定を修正し、回帰を確認した。

実保存run41967896991の126 ZIP/API digestを厳格読戻し。**144レース、725保存予想（基準623、研究学習版102）、P0 288/P1 437、結果観測192版**を私有projectionへ接続した。623基準行のSHA・Top8・全順位・原本参照、全192観測、170 member参照を保全。肥大した監査文書を表示入力へ重ねていた問題は、原本を消さず検証済み付帯文書の重複を除いて修正。JSONサイズ保護は据え置きで入力40,910,737→16,171,960bytes。読み戻しから推論・公式サイトGETは0。学習版を含む725と、基準623を混同しない。

先行runはsuccess、第22巡まで完了、prepared_round=null、チェックポイントの取得数282・source_wait=nullを独立認証。mainは0e45c029e18d5f3f1e7a04aecedab3c4af261748のまま。旧ローカル288原本DBのSHA c40bead05533ace426188ea8a111b1e4a4a639283f576972ba276e14a3e8ff1a・元取得3回・中断要確認を保全し、native生成を再開しない。適用後はGitHub生成元のみをsupervisorが監視する。

ここまでは最終検証と旧保存原本の接続。新HEADのrun起動・新しい予想保存・T15〜T10実測・実画面照合は、これから別記する。[検証とソースSHA](evidence/2026-11-05/continuous-deadline-forecast/verification.json) / [実原本読戻し](evidence/2026-11-05/continuous-deadline-forecast/real-saved-projection.json) / [先行checkpoint](evidence/2026-11-05/continuous-deadline-forecast/predecessor.json)。

---

# 2026-11-05 実装更新｜取得固定回数・論理24巡/65分/日付停止を撤廃、連続引継ぎと私有表示を接続

この項は今回の作業treeのコード変更を説明する。稼働先へ適用したHEAD、実行run、独立ZIP、実際の保存件数・ブラウザ照合は、適用後の証拠として別に記録する。コードが連続運転に対応したことを、24時間実運転や全日無欠落の証明とはしない。下の時点付き実測と過去原本を保持する。

| 対象 | 今回の変更と保全する条件 |
| --- | --- |
| 取得回数 | 固定45GET/処理・累積240GET停止を撤廃。上限はNone/null、取得数・累計は記録し、負数/bool/回数減少を拒否 |
| 論理巡回 | 24巡・65分で終了せず、対象日を固定したtransactionを完了してJST日別に引き継ぐ。旧日の原本と累計を消さない |
| 取得順・保存目標 | T−15～T−10のWINDOWを優先し、そのphase内で締切順。3予想/5試行の打切りを撤廃し、適格な全対象を確認。T−10後は210秒より前の遅延fallbackとして区別 |
| 取得元の待機 | 429/Retry-After、一時障害、未公開展示、認証・利用条件、真正性の要確認を記録。即時再試行や別endpoint迂回を行わず、期限なし要確認を時刻や日付で解除しない |
| 原本・再起動 | V1の正常上限終了は旧バイト/SHAを保全して移行。中断/不整合/認証等は要確認を維持。lock初期化記録によりcheckpoint欠落を初回として再作成しない |
| GitHub物理worker | 同じworkflow・concurrency・既存認証actorを使用。物理上限360分、330分handoff、24batch区切りを独立保存後に次workerへ引き継ぐ。論理巡回の終了上限ではない |
| アプリへの接続 | GitHubモードは認証したartifactのSHAを検証した私有projectionを読取り表示。画面側provider/native生成は起動せず、GitHub生成とローカル生成を重ねない |

物理workerを切り替える`WORKER_HANDOFF`と、日付を変える`DAY_HANDOFF`を区別した。引継ぎ前に追加GETを停止し、既に生成できた原本は保存・検証して残す。次runの起動だけを予想成功と数えず、確認済みHEADを親に持つcommitのforceなし追記・先行run/queued照合・単一writerを使う。`GITHUB_TOKEN`の自己pushが再帰起動すると仮定せず、新PAT・別workflow・新しい外部サービスを作らない。

表示は元データ取得・生成・保存時刻と待機理由、次回確認、次の締切を扱い、証拠不足はUNKNOWN、未保存はNOT_SAVED、目標後の保存はLATEとする。GitHubへの保存と、本人の画面へ見えた時刻の独立受領証明は区別する。過去の固定ZIPが新しいコードや最新件数へ自動更新されたとは扱わない。

関連回帰と独立レビューでは、WINDOW順の実GET、404のserver Retry-After、元行/source/rawの結び付き、日付を跨ぐ待機・累計、正常終了移行と要確認保全、欠落checkpointを検証した。全体試験の最終件数と実適用は適用工程で記録する。[起動・連続運転・表示の契約](LOCAL_FORECAST_GENERATION.md)。

未完成は、他3競技の適格な当日入力、全16系統×全レースの実運転、全日P1無欠落、恒久私有保管、実機Safari、学習版の前向き優位性。BOATの事実から別競技の特徴を作らず、未校正確率/未検証回収率を実績表示せず、本番モデルを切り替えない。main統合・一般公開・実投票・追加課金は行わない。

---

# 2026-11-05 14:25 JST｜第15巡回の元ZIP独立照合・学習候補比較の累積更新（実行中runの完了ではない）

既存Draft PR #71 / workflow 405276784 / run `41967896991` を読み取り監査。点検時のPR HEAD `b2b7e9e47c16a805c5710a7193df67507bf5b0d8`、同workflowはこのrunのみ`in_progress`で、追加の`queued/pending/waiting`なし。GitHub Actions上の「Deadline-ordered five-model round 15」はcompleted/success、round 16は実行中。**今回の確定範囲は第15巡回の保存済みartifactのみ**。第16巡回以降やrun全体の終了を完了扱いにしない。

第15巡回の別保存原本2 ZIPを独立ダウンロード、実バイトSHA256をGitHub API digestに照合、ZIP CRC正常：
- 展示後原本：`boat-national-cutoff-41967896991-cycle-15` / artifact `13391021693` / SHA256 `49cd0683973cd9d92e54d3766ed6a19a1058ab2572f9d361822d071f2a8fc9cb` / GitHub保存2026-11-05 14:24:37 JST。
- 結果・PDCA原本：`race-existing-cycle-41967896991-cycle-15` / artifact `13390359154` / SHA256 `ca8cfa8308743a7eecd5648e4d323d5924d955aa141ede1ea07ff73238f22b99` / GitHub保存14:24:46 JST。
- 結果ZIP内の`current-p1-original.zip`実バイトは別取得P1 ZIPと完全一致。初回P0埋込みZIPのSHA256 `3a8bde638b93b61cbe21843bff5f3dbaf120c486b45f39efc3ea3a78f89034ab`は既存初回原本と一致。P0再生成なし。今回の元サイト別経路GET・全学習元artifactの独立再取得は未実施。

**保存値の実差分（13:48 JSTの第3巡回→14:24 JSTの第15巡回）：** `status.json.round_no=15`・`updated_at=2026-11-05T05:24:44.562589+00:00`。基準予想 **543→598件（+55）**、P0 288件不変、展示後P1 **255→310件（+55、計62レース×5系統）**。`forecasts.csv`598行と`model_coverage`598件が一致し、race_id/phase/model重複0。通常採点 **314→412件（+98）**、HIT **126→156（+30）**、MISS **188→256（+68）**。未採点・返還・異常レビューをMISSにしない。対象144レース、締切済84、未来60、締切済P1完備58レース、P1不足26レース＝130モデル別行を`coverage_audit`に保持。展示当時の提供可否は未確認。

既存観測相性2系統の学習候補`LEARNED_SHADOW`は **70→92モデル別予想（+22）**、公式通常結果に基づく前向き同条件比較は **46→74モデル別行（+28、37レース×2モデル）**。基準 **23的中・仮払戻59,630円**、学習候補 **25的中・64,970円**（差+2的中・+5,340円、過去の差と変わらない）。研究用候補の学習状態は`FITTED_SHADOW_ONLY`、一意の確認済み通常結果76レース（train57/validation19）、少数・欠測の特徴係数は基準据置。学習候補の統計的優位性は未証明、基準5モデルと過去8点は不変、本番自動切替なし。別保存の公式結果観測履歴173版、未対応払戻表`SOURCE_OR_PARSE_UNAVAILABLE`1レースを保全。

**既存の取得上限に指示衝突あり：** この定期指示は240 GET/セッション・45 GET/巡の固定停止を要求する一方、別チャットのオーナー承認を受けた既存HEAD・実行runは固定GET回数を撤廃済み。第15巡回ZIPは`requests_used=201`・`source_limit=null`・`halted_reason=null`、180秒/最大24巡/65分・3新規レース/巡・締切210秒・HTTP4xx/429・日付/真正性停止は変更していない。矛盾した上限policyをこの監査で無断で再変更せず、実行中runをキャンセルせず、**追加トリガーpush・rerunもしない**。固定上限維持の現指示に対し、現行runの上限は異なることを明記し、後続による停止条件の回避は行わない。

本人専用Driveのroot/対象フォルダは今回APIでowner本人一致、shared=false、ownerのみpermissionを確認。既存14ファイルに第15巡回ZIPは未保全。最新結果ZIPの追加アップロードは`BLOCKED_FILE_REFERENCE`で拒否され、**新規保存0件・Drive読戻し0件**。GitHub artifact7日保持を永久保全と呼ばない。他競技の正式入力、全16系統/全対象P1、恒久的な非公開保全、研究学習版の優位性は未完成。新タスク・頻度変更・別workflow・新PR・モデル系統・追加課金・main統合・一般公開・実投票・本番切替なし。

---

# 2026-11-05 13:48 JST｜第3巡回の独立ZIP照合、既存run継続、追加起動なし

既存Draft PR #71 / workflow405276784のみを監査。監査開始時のPR HEAD `2dfc56a4bbdbb1b02763327b7686931cf62da214`、先行run `41964059991` は13:38:33 JSTにsuccess、第16巡回を最終保存。後続run `41967896991` は旧runの完了後13:38:36 JSTから実処理を開始し、この監査では13:48:37 JST更新の**第3巡回まで**予想・別イベント結果の独立artifactが保存されたことを確認。後続run自体は監査時in_progressで、runの終了や第4巡以降を完了としない。

旧第16巡回の結果ZIP `13388234377`、同予想ZIP `13388582279`、continuity ZIP `13388199631`、新第3巡回の結果ZIP `13389576218`・予想ZIP `13389402102` を独立取得。すべてGitHub API digestと実バイトSHA256一致・ZIP CRC正常。結果内のP1元ZIPも独立取得したP1 ZIPと実SHA一致。新`status.json.round_no=3`、`updated_at=2026-11-05T04:48:37.966535+00:00`と`forecasts.csv`543件、`model_coverage.json`の543件を照合した。今回の独立公式サイト再GETおよび全学習元artifact再監査はしていない。

**実保存の差分（旧run第16巡回→新run第3巡回）：** 既存基準予想533→543モデル別行（+10件、P0=288不変、P1=245→255、2レース×5基準モデル）。通常採点314件は不変（HIT126、MISS188）、未確認を外れにしない。LEARNED_SHADOW 66→70研究モデル別行（+4件）。同条件の通常比較46モデル別行＝異なる23レースは不変で、元16的中/学習候補18的中、仮払戻元51,160円/候補56,500円（差+5,340円）。現時点の小さな比較で学習版の統計的優位性や本番切替は認定しない。学習入力62種類の通常レース（train47/validation15）、基準モデルと買い目は不変。

最新`coverage_audit`は対象144レース、締切済73、未来71、締切済み5モデルP1完備47レース、未予想130モデル別行を保持。取得可能な展示の取りこぼしと断定せず、未対応の払戻表2件は`SOURCE_OR_PARSE_UNAVAILABLE`として保持。他競技の正式原本入力、全16モデルの予想、全対象P1、永久owner-only保存、学習版の前向き優位性は未完成。

**取得上限に関する指示競合を保全：** 13:26 JSTに別途オーナー承認で累積240回/1巡45回の固定GET停止を撤廃したコードが既存PRに反映されている。新run第3巡回statusは`requests_used=45, source_limit=null`であり、本定期検証の旧指示に残る240/45上限維持とは一致しない。この監査では取得policyを変更・巻戻しせず、実行中writerをキャンセルせず、追加trigger、rerunもしない。HTTP4xx/429・日付変更・真正性不一致など別の安全停止は残っている。

当該巡回のDrive owner/sharedの現物再照合は行わず、新規Drive保全・読戻し実績を主張しない。GitHub artifact7日保持を期限なしDBと扱わない。新タスク/頻度/PR/workflow/モデル系統/Cloudflare/Vercel/課金/main統合/公開/実投票/無検証本番切替なし。他チャットの記録と過去の数値・原本は下に保全。

---

# 2026-11-05 13:42 JST保存分 — 取得回数上限撤廃版を実運転へ適用・保存原本で確認

オーナーの「てきようして」により既存Draft PR #71へpushし、適用コミット **717725c26c3be7ffd1ee02c045b3311a169aef3c** を反映した。同じ既存workflow405276784・concurrency/cancel-in-progress=falseで後続を1件だけ待機させ、先行run41964059991の正常終了後に[新run41967896991](https://github.com/haji84/RACE-AI/actions/runs/41967896991)が13:38:36 JSTに開始。旧runは240GETの通常停止で第16巡まで完了し、HTTP4xx/429等の停止を迂回していないことを最終継続原本から独立確認した。

**実運転第1巡の保存データで、`bounded_repeat_session.source_limit: null` とP1の `source_request_cap: null` を直接確認。固定GET回数上限の撤廃は、コード反映だけでなく実行・私有保存まで適用済み。** 第1巡回stepは13:42:49 JSTにsuccess。保存時点の実取得22回（予想18/結果4）、停止理由null。180秒間隔・最大24巡/65分・JST境界・3新規レース単位・210秒余裕・HTTP4xx/429停止と原本検証は維持する。今回のsession終了予定は14:47:21 JST、他の停止条件で早期終了する。

第1巡の予想ZIP13388817224/結果ZIP13388433291を独立取得し、API digest/実SHA/CRC・結果sealを照合した。元P0埋込みZIP SHA `3a8bde638b93b61cbe21843bff5f3dbaf120c486b45f39efc3ea3a78f89034ab` と、**先行533基準予想すべてのSHA/Top8/生成・保存時刻が不変**。累積P0 288/P1 245、通常採点314、学習版66/比較46は復元済み原本を含む値であり、この初回巡回の新規基準予想/P1/通常採点/学習版増分は0。展示未公表を予想成功とせず、結果観測履歴のみ125→126（+1版）。本番昇格・実投票・精度改善認定はfalse。

結果読取3件は未対応の払戻表形式によりSOURCE_OR_PARSE_UNAVAILABLEとして保持し、未確定/レビューを外れや成功へ変換しない。会場日程の棄却1件と未公開展示2件も理由付き保留。第1巡保存時点にHTTP4xx/429の停止はない。取込やsource検証の未完成を、取得回数上限撤廃の成功に便乗して隠さない。

適用HEAD717725cのViewer CI41967903546・AUTORACE CI41967903393はcompleted/success、関連6job成功（CodeRabbit skipped）。push前にもPython122件/Node179件を再検証し、変更済み全Python888件・ブラウザ37操作グループのソースSHAと一致を確認。リモート主要10ファイルも実バイト一致。mainは0e45c029e18d5f3f1e7a04aecedab3c4af261748、初回P0索引blobも不変。環境再公開・アプリ一般公開・新PR/workflow/model/task/サービス/課金/main統合/実投票/本番切替はなし。

ローカル閲覧APIも新設定`source_limit:null`を返すことを確認。保存288原本のDB SHAと取得3回は不変、中断後のSTOPPEDを保持してGitHubとの二重取得を起こしていない。GitHub最新原本のアプリ自動同期や全4競技/全適用モデル/全レース運転、恒久私有保管、実機Safari、精度改善実証は別の未完成条件。

[実運転の上限値](evidence/2026-11-05/no-get-count-limit/applied-runtime-policy.json) / [初回原本の独立照合](evidence/2026-11-05/no-get-count-limit/applied-first-round-summary.json) / [先行処理の正常引継ぎ](evidence/2026-11-05/no-get-count-limit/applied-predecessor-handoff.json) / [取得・解析の保留事項](evidence/2026-11-05/no-get-count-limit/applied-source-limitations.json)。これより下の未push/待機の記載は、それぞれの時点の履歴として保全する。

---

# 2026-11-05 13:26 JST — オーナー承認により取得回数上限撤廃版を既存PRへ適用

オーナーの「てきようして」により、既存PR #71へのpushと次の既存自動運転への適用が明示承認された。以前の「未push・反映待ち」は以下に履歴として保全。適用対象は検証済みa92a742のコード。全Python888件/Node179件/ブラウザ37操作グループに加え、push直前にも取得policy・保存原本・workflow契約を再検証し、私有情報を含まない差分を独立審査した。

旧run41964059991は旧HEADで実行中のため中断しない。同じ既存workflow405276784・concurrency/cancel-in-progress=falseを使い、後続を1件だけ待機させる。先行原本を復元してから新しい上限値nullで実行する。新旧の実運転/待機/保存証拠は確認後に追記する。コード反映と、実行中旧runの上限解除を混同しない。

固定GET上限だけを撤廃し、3分間隔/24巡/65分/JST境界/3新規レース/210秒余裕/HTTP4xx・429停止と原本保全を維持する。main統合、環境再公開、一般公開、実投票、本番モデル切替、新PR/workflow/model/task/サービス/課金は行わない。

---

# 2026-11-05 — 自動予想経路の取得回数上限を撤廃（実行中GitHub版への反映は未実施）

オーナーの「取得上限なしにして」に対応し、ローカル実装と本人用アプリから**累積240回・1収集45回という固定GET回数停止を撤廃**した。上限metadataはPython None/JSON null、画面は「取得回数上限なし」と実際の取得数を表示する。取得数を巨大値へ置換したり、カウンター/原本/旧停止記録を削除して解除したりしていない。

**全Python888件・Node179件・合成ブラウザ37操作グループ/58PNGが成功、独立レビュー118件成功**。240回超からの継続/再起動、258回の反復guard計数、1収集50回・pilot60回の模擬GET、365→366回の自動画面更新を確認。旧metadata240と既存原本を読め、回数減少/bool/負数等と旧停止の自動解除は拒否する。既存DB SHAとsource回数3/STOPPEDは不変。実公式取得・追加実予想・モデル係数変更は0。

3分間隔・24巡/65分・JST日付境界・3新規レース単位・締切210秒前・単一writer・HTTP4xx/429停止・出典検証・サイズ/timeout条件は維持。別の過去one-shot診断の6GET等は今回の自動予想経路の変更範囲外。回数上限撤廃を全競技/全モデル/全レース実運転や24時間常駐完成とは扱わない。

公開HEAD `897a31c21b703f2474683fb13143f814686f92dd` の並行監査/トリガー記録をローカルmerge `539d04b`で保全。workflow契約の競合は双方のbootstrap順序/guardを統合し、関連16件が成功。**今回の変更は未push・未公開**。既存run41964059991は旧HEAD fea5b2a4で起動しており、実行中の240回制限を途中解除したものではない。既存処理の中断・再起動・追加run・環境再公開は行っていない。実運転への適用は既存PR向けコードの反映が残る。

本人用の新しい配布物 `RACE_AI_20261105_no_get_limit_app.zip` を別名で作成。12,765,026バイト/319ファイル、SHA256 `a5adc98ca72f02c4501900593c13fb9a8313f82e72d1895eb3f351306c7a29cb`。CRC/全格納SHA、276現行ソース・20seed、cache/symlink0を検証。isolated `--check` は保存288件、追加GET/推論0。旧配布物と全原本は無改変。予想JSONは以前の08:23保存分GITHUB293件と別来歴LOCAL288件の固定snapshotであり、最新の463件等へ自動同期しない。

[変更・試験・適用範囲](evidence/2026-11-05/no-get-count-limit/EVIDENCE.md) / [最終検証](evidence/2026-11-05/no-get-count-limit/verification-summary.json) / [配布物SHA](evidence/2026-11-05/no-get-count-limit/package-delivery-summary.json)。全144レースの展示後保存、他3競技/全適用モデル、GitHub最新原本のアプリ自動同期、恒久私有保管、実機Safari、精度改善実証は未完成。新PR/Issue/task/workflow/model/サービス/課金/main統合/一般公開/実投票/本番昇格はなし。

---

# 2026-11-05 12:50 JST｜既存run第17巡回の原本再監査と後続1件の安全起動

対象：既存Draft PR #71 / branch `feat/four-sport-forecast-audit-view-20261022` / workflow `405276784` のみ。監査開始時のPR HEAD `e28910757fb5c159765abd8ea9f84523f8f59cfb`。前run `41949401478` は11:24:53 JSTに `completed/success`、実行HEAD `74572f2f304f9122cff987b05001b4455c29780c`。全37 artifactから無接尾辞を第1巡回、`-cycle-17` を第17巡回として最大完成巡回を選定。第18〜24巡回は240 GET上限による安全停止であり、実施済み扱いにしない。

前runの第17巡回・別保存の **P1元予想** `13382273973` / **公式結果・PDCA** `13382722611` / 最終**継続原本** `13383015886` の3 ZIPを今回新たに独立ダウンロードして実バイトSHA256を再計算。GitHub API登録digest `9cbc7ac048bad16465cde4a52e5553e3b76848a98a8bea84242f05d7047c9f57` / `759a7c3bea91eafa4c9c75171be43d28c340c67cd84a1c3c187df28baaac5893` / `92e43ef2db8a127ae52d9ba19a1b6e0e094680bb3d0b38267bbb4ed4d9f4c10e` に完全一致し3 ZIPともCRC異常なし。内部`status.json.round_no=17` / `updated_at=2026-11-05T02:24:33Z`、`forecasts.csv`443行と`model_coverage.json`の基準443件が一致、公式結果観測履歴も保存。結果ZIP内の旧原本を改変していない。continuity ZIPの元ZIPや学習元全件について、今回の独立ZIP再取得による第三者完全監査完了までは主張しない。

**再確認した前run最終保存値（新規増加なし）**：基準5モデル443モデル別予想（P0=288、展示後P1=155、P1対象31レース）。通常結果採点140モデル別行（HIT68/MISS72）、RESULT_PENDING294、異常着順レビュー9、合計443。LEARNED_SHADOW30モデル別予想、前向き同条件比較10モデル別行/異なる5レース、基準版・学習版とも4的中/仮払戻12,780円で改善証明なし。学習状態`FITTED_SHADOW_ONLY`、独立検証済み通常20レース（train15/validation5）、元5モデル係数・買い目不変。全日144レース、前run集計時締切済み28、P1完備27、不足`20261105-10-02`の5モデル別行を維持。展示当時の提供可否は未立証。実ZIP内の`bounded_repeat_session.requests_used=240/source_limit=240`、GitHub Actions jobログの第17巡回読戻し完了および第18〜24巡回 `SESSION_SOURCE_BUDGET_EXHAUSTED` を別途確認。4xx/429や真正性不一致を上限停止と混同しない。

12:49 JST、既存日程原本の時刻比較では未来締切88レースが残り、直近Actions一覧に対象workflowのin_progress/queued/pending/waitingはなく、前runは正常完了。既存trigger `docs/evidence/boat-nationwide-pilot-trigger.txt` を、元blob SHA確認後**1回だけ追記CAS更新**。更新コミット `fea5b2a404dd5eb5a602d741263a95000c1e3b6f` により**後続run `41964059991` が12:50:17 JSTにin_progress**。同workflow・同一concurrency `boat-nationwide-cutoff-20261103`・cancel-in-progress=falseを維持、後続をもう1件積まない。後続はまだ予想/結果artifact0件のため、P1増分・通常採点・学習比較増分を**未確認**とする。前runの240 GETを上書き/超過させたり失敗runをrerunしたりしていない。新セッションも240 GET上限と4xx/429/日付/原本不整合停止を必須とする。

本人専用Driveのrootと対象フォルダは今回も所有者本人一致、shared=false、ownerのみのpermissionを実確認。既存14ファイルを保全したまま、最新3ZIPの追加アップロードを試行したが `BLOCKED_FILE_REFERENCE` により拒否。**今回の新規Drive保存0件、Drive独立読戻し0件**。公開GitHubへの私有DriveのURL/ID・秘密情報・生原本転載なし。7日artifactを期限なしDBと呼ばない。全16系統×4競技実予想、展示後全対象、永久本人専用保全、係数学習版の統計的な前向き優位性は依然未完成。新タスク/頻度/PR/workflow/モデル系統/Cloudflare/Vercel/追加課金/main統合/一般公開/実投票/無検証本番切替なし。

---

# 2026-11-05 11:27 JST｜既存run第17巡回まで独立照合・P1+90/通常採点+98・上限停止


対象：既存Draft PR #71 / workflow 405276784 / run `41949401478`（実行HEAD `74572f2f304f9122cff987b05001b4455c29780c`）。同runは11:24:53 JSTに `completed/success`、ログの `ROUND_SAVED_AND_READBACK_VERIFIED` は**第17巡回まで**。第18〜24巡回は `SESSION_SOURCE_BUDGET_EXHAUSTED` で実行せず。第17巡回結果ZIP内の `bounded_repeat_session.completed_round=16` は保存時点の途中状態で、最終continuityの `completed_round=17` とActions完了ログを別途照合済み。

独立再取得した第17巡回P1元ZIP：artifact `13382273973` / API digest・実ZIP SHA256 `9cbc7ac048bad16465cde4a52e5553e3b76848a98a8bea84242f05d7047c9f57`。別イベント結果/PDCA ZIP：artifact `13382722611` / `759a7c3bea91eafa4c9c75171be43d28c340c67cd84a1c3c187df28baaac5893`。最終continuity：artifact `13383015886` / `92e43ef2db8a127ae52d9ba19a1b6e0e094680bb3d0b38267bbb4ed4d9f4c10e`。3ZIPとも実バイトSHA256一致・ZIP CRC正常。第17巡回の `status.json.round_no=17`、`updated_at=2026-11-05T02:24:33Z`。元P0埋込みZIP SHA256は `3a8bde638b93b61cbe21843bff5f3dbaf120c486b45f39efc3ea3a78f89034ab` で既存初回P0と一致。P0再生成なし。予想ZIPの実バイトSHAも結果ZIP内埋込みP1と一致。

**11/05確定済み保存値**：基準予想443モデル別行＝初回P0 288＋展示後P1 **155（31レース×既存5モデル）**。前回10:35記録の353/P1=65から **P1+90行（18レース分）**。通常結果採点 **140行（HIT68/MISS72）**、前回42から **+98行**。未確認 `RESULT_PENDING` 294行、異常着順レビュー9行を外れにしない。保存 `forecasts.csv`・`model_coverage.json`・`status.json` の基準443行一致。7系統×20通常採点行は**20種類のレース**であって140レースではない。公式結果観測履歴59版（59種類のレースとは限らない）。保存済み8点と結果3連単・100円払戻の再計算は140通常行で内部記録と整合。公式サイトへの新規独立再照会まではしていない。

**自動学習と未来比較**：独立確認済みの異なる通常結果20レースを時系列でtrain15・未使用validation5に分割、`automatic_learning.state=FITTED_SHADOW_ONLY`。既存観測相性2系統のみの研究係数版、基準5モデルの式・買い目は不変。LEARNED_SHADOW 30モデル別行（15レース）、同条件通常採点10モデル別行（異なる5レース）。**基準/学習版とも4的中、100円払戻合計とも12,780円**。学習版優位性なし。比較30行が参照する異なる学習元11 artifact ZIPを独立再取得し、各GitHub digest/ZIP CRC/`trained_observed_models.json.training_sha256`を照合。学習元サーバー保存時刻 < 予想元入力as_of < P1予想保存時刻 < 公式締切、同レースが学習/検証IDに含まれないこと、基準側8点同一性を30行で再検算し矛盾0。学習版の後付け採用、本番自動切替なし。少数例の同点は統計的な同等性証明ではない。

`coverage_audit` は日程144レース、締切済み28、未来116、展示後5モデル完備27レース、締切済み `20261105-10-02` にP1不足5モデル行を保持。該当時点の展示公開可能性は未検証。外部研究は `NO_AUDITED_IMPORT_MANIFEST`、他3競技は `LIVE_INPUT_INTEGRATION_NOT_YET_VERIFIED`。

**停止と保全**：最終continuityは `requests_used=240/source_limit=240`、`halted_reason=SESSION_SOURCE_BUDGET_EXHAUSTED`。上限を回避するトリガーpush・rerun・キャンセルなし。本人専用Driveのroot/フォルダの所有者一致・双方shared=false・ownerのみを実再確認し、既存14ファイルを保持。ただし最新第17巡回ZIPのDrive新規保全は `BLOCKED_FILE_REFERENCE` により未達（Drive保存成功とは数えない）。GitHub artifact7日保持を無期限保全と呼ばない。全16系統・全4競技・全P1・学習版の前向き優位性・期限なし非公開保存も未完成。新task/PR/workflow/頻度/モデル/課金/main統合/公開/実投票なし。

---

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

# 2026-11-05 12:56 JST — 自動予想463件・展示後35レース、既存巡回は継続中

状況照会に対し、公開PR HEAD `897a31c21b703f2474683fb13143f814686f92dd` と既存workflow405276784を読み取り確認した。新しい起動・取得provider実行・予想再計算・push・環境公開は行っていない。ローカル実装はb54a80cのまま未pushであり、以下は既存GitHub運転の累積保存値。

既存run[41964059991](https://github.com/haji84/RACE-AI/actions/runs/41964059991)（実行HEAD fea5b2a404dd5eb5a602d741263a95000c1e3b6f）の第2巡回、12:56:12 JST保存分を独立読戻し。結果artifact13387321038の実ZIP SHA256 `a366011b6627f8242af75c6a6258c83af175e29c58bff4fca8f86c7fd732d854` がAPI digestと一致しCRC正常。朝版P0 **288件＝144レース×2モデル**、展示後P1 **175件＝35レース×5モデル**、基準計**463件**。先行する同日runの原本を復元した累計で、今回の2巡だけで463件を新規生成した意味ではない。

通常結果照合250モデル別行/50レース、未確定204行・異常着順レビュー9行を外れに変換しない。研究学習版38件は基準463件と別枠。同条件比較30モデル別行/15レース、精度改善未証明・本番昇格false。学習は独立通常50レース（train38/validation12）。未校正の確率や回収率を実績表示しない。

既存GitHub自動巡回は観測時に実行中、180秒間隔、当該session67/240GET、停止予定13:57:52 JST（上限・異常で早期停止）。第2巡回ZIP内のcompleted_round=1はアップロード前snapshotであり、第2巡回完走確認と混同しない。前run41949401478は240GETで第17巡まで保存し正常終了。ローカル自動workerは重複回避のSTOPPEDを維持し、保存原本を再生成していない。

**未完成**：全144レースの展示後保存、他3競技/全適用モデルの実入力と自動運転、GitHub最新予想のアプリへの自動同期、全原本の恒久私有保管、実機Safari、精度改善実証。前回配布ZIPは08:23保存分の固定snapshotであり、今回の463件へ自動更新されない。今回の照会でUI同期機能を実装済み・新コード公開済みと扱わない。[保存原本の安全な検証要約](evidence/2026-11-05/automatic-forecast-generation/midday-round02-status.json)。

---

# 2026-11-05 JST — ボタン不要の自動予想を実装、既存自動運転のP0 288件・展示後5件を照合

オーナーの「自動生成できるようにして欲しい」に対応し、既存ローカルアプリの**起動→入力確認→既存モデル実行→私有保存→画面の自動読戻し**を接続した。生成ボタンは不要。ブラウザはGETで保存原本を読み、画面更新で取得/再予想しない。新しいcron・workflow・外部サービス・モデル系統は作っていない。

別途、稼働中の既存GitHub自動運転[run41929106428](https://github.com/haji84/RACE-AI/actions/runs/41929106428)を独立点検し、**11/05 08:23 JST保存時点で144レース、朝版P0 288件＋展示後P1 5件＝293件**を確認した。第11巡回までActions成功。P1は1レース×既存5モデルで、GitHub保存08:23:52 JST、締切08:35、全5件が締切668秒前。ZIPの実バイトSHA/API digest/CRC・各原本SHA・Top8・保存時刻を照合した。結果/採点/学習版/同条件比較は0で、確率・回収率・精度改善を実績表示しない。 **293件すべてを厳格な読戻しJSONへ投影し、390/1440幅で展示後5モデルを各幅選択、計10選択/80点のTop8・SHAを画面照合済み**。JSON読込は表示操作であり、新しい予想の生成操作ではない。

| 条件 | 完成したこと | 現在の制限 |
| --- | --- | --- |
| ボタン不要の生成 | ローカルHTTP起動時に単一worker開始。初回P0、以後は既存締切順P1、保存済み原本を再利用 | 実入力providerはBOATのみ。他3競技/不足モデルの特徴を補完しない |
| 自動表示 | 起動時の保存原本読込と180秒ごとのGET更新。金額入力/候補確定/選択SHA/タブ、手動JSONを保全 | 静的HTMLだけでは推論しない。GitHubの後続原本を自動同期する機能は未実装 |
| 実運転と重複回避 | 既存GitHub runで展示後5件の新規生成と独立保存を確認 | ローカル巡回は既存writer確認後に停止。2つを同時運転しない |
| 原本保全 | ローカル288件とGitHub293件を別来歴のJSON/原本で保持。ローカル全288原本不変 | 同じnativeキー/Top8でも全P0 SHA/時刻は異なり、後のGitHub受領を早いローカル原本へ流用しない |
| 検証 | **Python877件・Node179件成功**、合成4幅37操作/58PNG、独立最終レビュー40件成功 | 新コードは未push。既存runの成功を未pushコードのCI成功とは呼ばない |

既存の**180秒、最大24巡/65分、240GET/JST日、JST日付境界停止**を維持。同日再起動で開始時刻・回数・P0完了をリセットせず、自動で次セッションを作らない。P1は最大3新規レース/巡、保存余裕210秒、各GET前にも終了時刻を確認。4xx/真正性不一致の停止を強行しない。全日・全144レースP1の保証ではなく、現状2GET/レースの経路では240GET以内の全P1取得も未達。

ローカル実観測は4巡完了、P0再利用288/P1新規0/取得3。23:18:21 UTCの停止と第5巡開始が競合し、1秒joinでdaemonを置き去りにする不備を発見した。未完了記録を残し、取得/推論0で再起動時の`INTERRUPTED_ROUND_REQUIRES_REVIEW`停止を確認した。修正後はSTOPPINGで次の処理を止め、進行中checkpointを待つ。有限240秒を超えれば失敗を明示し、成功終了やlock解放と扱わない。1秒超の処理/timeout/繰返し終了の回帰試験が成功。同梱の停止記録を削除して再実行しない。

並行の公開HEAD `ab57ae2f297066cf0eed77cdaf8ad5219943f3c2`をローカルmerge `9c5af90`で保全し、最新状況の双方の追記を残した。新しい初回索引・B取得計上順に対する旧試験の不整合と、実時計で朝windowへ入るNode試験を修正した。本番モデル・元予想は変更していない。今回の変更は**ローカル保存・未push**。mainは`0e45c029e18d5f3f1e7a04aecedab3c4af261748`のまま。

**未完成**は、競輪/オート/競馬の当日実入力、全競技×全適用モデル×全レースP0/P1、全日の単一writer運転、全原本の恒久私有保管、公式結果の十分な前向き照合/学習比較、精度改善の実証。**外部の接続・受入が必要**なのはLibrary等の未接続原本と実機Safari。現環境では実機Safariを操作できず、Chromium試験を代用の合格とはしない。

[起動・自動運転の範囲](LOCAL_FORECAST_GENERATION.md) / [実装・失敗修正・実測証拠](evidence/2026-11-05/automatic-forecast-generation/EVIDENCE.md) / [独立保存と締切照合](evidence/2026-11-05/automatic-forecast-generation/remote-original-summary.json) / [最終試験](evidence/2026-11-05/automatic-forecast-generation/verification-summary.json)。本人用配布物にはLinux/WSL2起動コード・固定PR64/72参照・停止状態を保つ私有seed・別来歴のLOCAL/GITHUB JSON・GitHub原本3ZIPを同梱する。クラウドの127.0.0.1は手元PCのURLではない。 配布ZIPは12,762,191バイト/319ファイル、CRC/全格納SHA一致、cache/symlink0。別保存先のisolated `--check`は保存288件、追加GET/推論0。[配布物SHAと照合](evidence/2026-11-05/automatic-forecast-generation/package-delivery-summary.json)。

新PR/Issue/開発タスク/別workflow/schedule/モデル系統/Cloudflare/Vercel/追加課金/環境再公開/一般公開/main統合/実投票/本番モデル切替は行っていない。

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

# 2026-11-05 JST — アプリから当日BOAT144レース・288予想を新規生成（全4競技/全モデルは未完成）

オーナーの「予想を出せるようになって！」に対し、保存原本の閲覧だけだった画面へ**当日実入力→既存nativeモデル→私有保存→画面表示**を接続した。実際にボタンを押し、11/05公式出走表の144レースについて既存観測相性2モデルの**新規288予想**を生成。ローカルcommit完了は11/05 07:05 JST、全288件が実締切前。再操作は**新規0/再利用288**で、元Top8/SHA/保存時刻を変えていない。

| 対象 | 新しい予想を出す状態 | 実測・残る条件 |
| --- | --- | --- |
| BOAT朝版P0 | **実生成・保存・表示済み** | 公式Bの144予定/144適格レース、2モデル288件。原本27,981バイト/SHA `123c27dc5965ef09c60156a35c3d73d9ba40ab7b871578cd20c83ea4520d92c4`。取得1回、再起動後も入力と回数を再利用 |
| BOAT展示後P1 | 実入力取得から既存5モデルまで接続・試験済み | 今回の当日実生成成功は0。公式展示が揃うことが条件。1操作で新規最大3レース、45GET/操作・240GET/JST日を保持。現状2GET/レースのため全144P1の完全取得は未達 |
| BOAT他モデル | 不足理由を全slotに表示 | 競技上の適用2,160枠中、生成288/未予想1,872（実入力不足1,728・学習物不足144）。動いたモデルだけで全モデル完走とはしない。Sellerの時刻/5件条件は不変 |
| 競輪・オート・競馬 | **当日入力providerは未接続** | 既存実行/保存層は4競技で試験済みだが、取得ページだけから特徴を捏造しない。画面は生成不可を明示 |

生成サーバーは127.0.0.1だけで起動し、画面は競技/時点だけを送る。時刻・出典・個人分析/私有保存の限定スコープ・保存先はサーバーが決める。ブラウザの時刻/URL/許諾/path注入、別Origin/Host/nonce、私有ファイル配信を拒否。静的viewerはAPI通信なしで従来のJSON取込を維持する。

保存では推論後の実時計と210秒余裕を再検査。commit後に遅延/逆行した記録や時刻不明の原本は再試行でも採用せず、既存原本は削除/再生成しない。ローカル時刻は独立外部freezeではなく、今回の288件をGitHub当日初回受領索引の登録成功や本番モデル採用とは呼ばない。

**全Python829件・Node179件、失敗/skip0**。合成35操作グループ/56PNG、実サーバーエラー/日付不整合の追加回帰も合格。実APIでは1440幅で288予想すべて、390幅で6予想を選択し、計294選択/2,352点を原本と照合。ページ/コンソールエラー・外部ブラウザ通信・横はみ出し0。元入力、実予想、実画面はGit外に保管。

起動用パッケージには固定PR64/72コード、元B、私有DB/時刻記録、288実予想のJSONを同梱。別の私有保存先へ移入し、isolated import/起動確認/新規0・再利用288/取得0・原本不変を検証した。**LinuxまたはWindows WSL2が必要**。クラウドの127.0.0.1を手元PCのURLとして案内せず、通常のWindows PythonではJSON閲覧と生成サーバーを区別する。既存保存先へseedを上書きしない。

[起動と生成範囲](LOCAL_FORECAST_GENERATION.md) / [実生成・失敗修正・検証証拠](evidence/2026-11-05/new-forecast-generation/EVIDENCE.md) / [実測要約](evidence/2026-11-05/new-forecast-generation/actual-generation-summary.json) / [配布物SHA](evidence/2026-11-05/new-forecast-generation/package-delivery-summary.json)。

残る条件は、全4競技×全適用モデルの実入力/継続実運転、全レースP1、独立外部保存/公式結果接続、実機Safari、精度改善の実証。未検証の確率/回収率を表示せず、既存モデルの係数・本番モデルは変えていない。既存当日workflowの初回受領ゲートも別に保全し、勝手に解除しない。

公開済みPR HEAD`60caf4a02eb35f82fbe5ca4377a5f304cd2c00cf`を確認して取り込み、先行する初回P0 bootstrapの並行作業を保全。確認時in_progress/queued0、追加run起動なし。今回のコードはローカル保存で**未push**。新PR/Issue/開発タスク/workflow/schedule/モデル系統/Cloudflare/Vercel/課金/環境再公開/一般公開/main統合/実投票/本番モデル切替は行っていない。

---

# 2026-11-05 JST — 実原本接続・最終画面照合を完了（4競技全運転・実機Safari・精度改善は未達）

環境設定の公開/適用後にGitHub APIから実バイトを取得できた。以前の「実読戻し0件/許可未適用」は当時の記録として下に保全する。今回の最終読戻しは**11月4日分**で、既存run41842464812第21巡回の結果23:58:11 JST保存、継続原本は翌5日00:00:20 JST保存。以後の当日予想や全競技完走を意味しない。

| オーナーの完成条件 | 今回確認できたこと | 未完成・外部接続が必要な条件 |
| --- | --- | --- |
| 実JSON接続 | **BOAT144レース・基準570予想・学習版70予想・結果観測505履歴を画面へ接続**。SHA・Top8・全文履歴を照合。基準P0=288/P1=282、学習版P1=70。展示後P1計352件を選択可能 | Libraryの競輪76/オート20+PDCA等の元予想は未接続。GitHubで見つかった他3競技154件はページ観測であり予想0件 |
| 全レース×適用全モデルの実運転 | 既存16系統の実行/私有保存/不足表示を維持。今回の640件は保存済みBOAT5基準モデルと学習版で、元原本を再生成せず使用 | **4競技全モデルの継続実運転は未達**。適格なnative特徴・学習物・利用条件・締切前保存・結果接続が不足。全144レースで5モデルP1が揃ったのは48、未保存438モデル別件。締切後の遡及生成はしない |
| スマホ・PC/Safari | 4幅の合成33操作グループ/54PNG。実データは390/1440の各幅で全640予想・全505観測を検証、実画面28PNG/2traceは私有保管 | **実機Safariは未接続・未受入**。ChromiumをSafari実機受入と呼ばない。保護された配布/実機操作の接続が必要 |
| 精度改善の前向き比較 | 原本選択・56コホート・28学習物SHA・144台帳を維持し、最終505観測で再検証。正常同条件33レースずつで元/学習版は11/11と10/10。独立検査で869ファイル/256ZIP不変 | **改善実証は未達**。両系統は同じレースを共有。正式率null、独立認証/改善認定/本番採用false。別途の35レース券別会計と混ぜない |
| 回帰・失敗修正・原本保全 | **Python780件・Node179件、失敗/skip0**。空P0、原本締切差、観測順依存、原文4000文字切断、学習4参照欠落、長URLはみ出しを再現/修正/独立再レビュー | 新コードは今回の「追加公開しない」という指示に従い**ローカル保存、未push**。公開済みHEADのCI成功を未pushコードのCI成功とは扱わない |

最終ビューの元原本は**256ZIP**（BOAT251/継続2/他競技3）。別途、既存artifact13332009079の公式原文2ページを含む1ZIPもSHA一致で保全し、取得原本は計**257ZIP**。後者はstrict parserが`start evidence incomplete`で拒否するため、505観測や公式成績へ混ぜない。照合不可33観測・5レースの締切差を補正せず保持。最新の照合不可結果を古い結果へ黙って戻さない。

並行writerの[全144レース券別会計](BOAT_20261104_FINAL_RECONCILIATION.md)の追記をfast-forwardで保全した。同文書のXLSX/監査ZIP/audit_summary本体は、この環境の接続済みファイル、GitHub metadata396件、既存234ZIPのメンバー名から見つからず、今回その会計全件を独立再現したとは報告しない。別の35レース会計診断と今回の正常33対比較は対象判定が異なる。両方とも統計的な改善認定ではない。

本人用の**アプリ+2分割実JSON（約1.18MB ZIP）**と**257原本の保全セット（約132.5MB ZIP）**を非Git領域に作成し、CRCと全格納ファイルSHAを再検証した。アプリ同梱の実ファイル298件読込と4競技件数、合成ボタンも127.0.0.1のローカル起動で確認。私有予想・原文・実画面をGit/public assetsへ配置しない。一時クラウドと7日artifactは恒久保存ではなく、本人端末への保存または認可済み恒久保管の接続が残る。

[実装・失敗修正・受入証拠](evidence/2026-11-04/real-original-readback/EVIDENCE.md) / [読戻し要約](evidence/2026-11-04/real-original-readback/real-readback-summary.json) / [私有画面の安全な要約](evidence/2026-11-04/real-original-readback/real-browser-summary.json) / [比較要約](evidence/2026-11-04/real-original-readback/real-comparison-summary.json) / [取得ページの表示契約](SAVED_CARD_READBACK.md)。元8参考画面との対応表は既存UI証拠に保持。

公開済みPRはDraft/Open、baseは`codex/actions-four-sport-e2e`。最終取得したHEAD `3c72b2d`までfast-forwardし、並行writerの7fe5777/e4c4cf5/ab3c2d0に加え9374db6（競馬履歴変換）/9b2f21c/3c72b2d（巡回・Drive保全記録）を保全した。競馬変換は[既存4モデルへの入力経路](HORSE_HISTORY_CONVERSION_20261105.md)で、実予想生成・校正は未完了。別writerはDriveへ3原本保存/独立SHA一致を記録しているが、この環境にはDrive connectorがなく、こちらでのDrive再取得や全原本の恒久保存成功は主張しない。

公開済みab3c2d0のviewer41853165866/既存synthetic41853165906はsuccess（CodeRabbitはskipped）。後続9b2f21c時点のAPI観測ではin_progress0、queued4で、4件とも既存のviewer/AUTORACE CI。追加の予想巡回を起動せず、既存CIを取消/再実行しない。[観測記録](evidence/2026-11-04/real-original-readback/remote-ci-observed.json)。未pushコードのCI成功を意味しない。

この工程からの新PR/Issue/開発タスク/workflow/schedule/モデル系統/Cloudflare/Vercel/追加課金/環境再公開/GitHub push/一般公開/実投票/main統合/本番モデル切替は0。mainは`0e45c029e18d5f3f1e7a04aecedab3c4af261748`。4条件すべてを満たす製品全体の完成宣言は行わない。

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


---
<!-- RACEAI_AUTOMATION_20261107_1726_READONLY_AUDIT -->
## 2026-11-07 17:26 JST｜RACE-AI既存source第2巡と19枠研究fitの安全監査

**監査対象**：Draft PR #71、branch `feat/four-sport-forecast-audit-view-20261022`、監査時 HEAD `329014cb3cef495ebc1df5558fa012f5e150b646`。既存 source workflow 405276784 の run `42352096559`（起動HEAD `784b446c62790d4cb3c7efe2e4f88dc778daa079`）は `in_progress`。実jobは第1巡 `success`、第2巡 `in_progress`、第3巡以降 `pending` のstep状態。別runの待機/queued/pending/waitingは一覧内で0件。現在runをcancel/rerunせず、追加source triggerも行わない。

**原本の独立読取**：現在runの第2巡に対応する暗号化artifact `boat-national-cutoff-42352096559-cycle-02`／id `13567480576` を独立ダウンロード。実ZIPバイトのSHA256 `e084dc3a72f0e5eca34579bf52f52963a3d2cf52cc9deda4d7a98b100e9a2544` がGitHub API登録digestに一致、ZIP破損なし、暗号化member `private-original.enc` の存在確認。**鍵のない検査のため内部status/forecasts.csv/公式結果・係数・HMACは読戻し未実施**。第2巡のファイルが存在することと、実行step完了・予想採点成功は区別する。

**前回正常終了workerのsource control**：run `42342290428` は `completed/success`、HEAD `df05282fc85265b99c43141c74dff678a53518ac`。original-vaultの公開運用カウンター `state/boat-source-control/v1/latest.json` 参照先の同日レコードについて、repo id `1416489937`、branch、workflow `405276784`、run id/HEAD/statusとcontrol/continuity実artifact id・size・API digestの一致を確認。既存メタデータの第4巡・146/240GET・`BOUNDED_SESSION_END`・source_wait=nullは過去runの値で、現在実行中runのGETや停止理由に転用しない。MAC/HMACの検証と所有者鍵による暗号原本復号はこの監査では行っていない。

**モデルと結果の区分**：公開の残枠記録は実研究fit **19/31枠（BOAT14/HORSE5）**、元入力152 records（112+40）、同競技8実レース／枠を6 train/2 holdoutで学習。HORSE通常8結果・特殊2結果。残12枠はAUTO6、KEIRIN5、seller1。19候補の未来レースでの独立保存・実PDCA・本番採用は未実証。元のBOAT14ペアは通常1レースの比較であり、成績の優位性証明ではない。実Actions `42352845874` と `42353120278` は `failure`、後者のviewer jobは動画fixture `tests.test_boat_video_marker_cli.MarkerCliTests.setUpClass` でAssertionError。全体CI成功や19候補の本番読戻しを主張しない。

**収集HOLD**：既存result collector run `42349536138` は全workflow successでもAUTO/KEIRINの6ケース `HOLD_BROWSER_SOURCE_UNVERIFIED`。当該暗号journal id `13565712487` のbrowser予約24件は実通信回数UNKNOWN（全予約上限32）として保持。再起動・別credential/URL・回数reset・未確認結果の外れ認定は行わない。売主型のwaku10一次値もINPUT_MISSINGのまま。

**保全**：原本/係数/買い目/学習SHA/旧スナップショット/trigger/workflow/スケジュールは無変更。このstatus追記は実source GETを発火するworkflowのpaths filter対象外。新source・表示jobの明示起動、新モデル、新PR、本番切替、main統合、一般公開、実投票、外部サービス・課金は実施しない。最新実行中runと終了runの成果を混合せず、28シナリオの正式収支・モデル別的中率は未独立確認。


<!-- RACE_AI_FIXED_SIXTEEN_PREPARATION_20261107 -->
### 既存モデル・次の実取得準備（2026-11-07 22:43 JST）

実学習19/30（BOAT14/HORSE5）、残AUTO6/KEIRIN5、新19/30未来PDCA0。直近実取得は901/42371023982 attempt2の8 GET全200・RESULT0・上限HOLD。新V4は元MAX32内の16通信・同一AUTO1レース、旧8契約とUNKNOWN24/旧epoch32を維持し、全prior・実時計・日付越え・固定attempt2を検証。request c89917e0/plan fe3b07abは準備のみ、capsule未発行。通常UIの1R identity完了待ちと最終通信drainを修正、外部通信0の実JS＋合成Result再現15応答保存／返却後不変、独立レビューCLEAR。新HEAD全体CIを確認後だけ実取得する。新workflow/schedule/model/課金/本番昇格/投票なし。

詳細：[指定12項目・新16準備](REMAINING_MODEL_COMPLETION_20261107.md)。
<!-- /RACE_AI_FIXED_SIXTEEN_PREPARATION_20261107 -->
<!-- RACEAI_SOURCE_DAY_HANDOFF_20261107T1335Z -->
# 2026-11-07 22:35 JST｜最新sourceはDAY_HANDOFFで安全終了、予想巡回0

既存workflow405276784の最新完了run [42376316340](https://github.com/haji84/RACE-AI/actions/runs/42376316340)、実worker HEAD `6a1a1f1a12248dc35f22a512783c279544c70086` は completed/success。GitHub公開artifactの実ZIPを独立ダウンロードし、GitHub API digestとのSHA256一致とZIP展開健全性を確認した。control artifact `13575967848` = `sha256:73fdcd87e18423539a1cbb129e6e8104f99ffa0763d446986035cf54013d8238`、continuity `13576047576` = `sha256:7f0ad9796688ad11e2b2ac062af6673867b08389870e6f990c56eaa8866b95b8`、forecast r0 `13576406441` = `sha256:75b35a7eca913514405deddb53a69c1ac2aa03588d101d3c7493eab5c03c2438`。ZIP内暗号文の所有者鍵による復号・真正性MACは今回未検証。

control内部の確認値は `stop_reason=DAY_HANDOFF`、`completed_round=0`、`requests_used=0`、`source_wait=null`、累計 `lifetime_completed_rounds=524` / `lifetime_requests=9059`。r0アーカイブは暗号化成果の保存であり「巡回1完了」「新P1実予想完成」とは扱わない。最新source実行中/queued/pending/waiting は確認時0。旧 `state/boat-private-originals/state/boat-source-control/v1/latest.json` はrun42352096559を指したままで、新runの所有者MAC付きmirrorと原本読戻しが未確認。安全な新規source起動条件を満たすと推定せず、追加triggerは行わない。

今回の照合前のPR HEADは `713732af0b2446d44c02182a579c5abc20ca0b76`。コードHEADとworker実行HEADは別。現行対象15系統/30枠、研究実学習19/30・残AUTO6+KEIRIN5=11に新認定なし。AUTO/KEIRIN結果collectorの旧UNKNOWN24/固定epoch上限32、既知probe別計上、4xx/429/真正性HOLDは維持。公式結果の新独立照合、LEARNED_SHADOW未来優位性、収支改善は追加認定しない。実原本・履歴・係数・スケジュール/上限・本番モデル・投票は変更せず、他担当の既存CI/復旧を再起動しない。
<!-- END_RACEAI_SOURCE_DAY_HANDOFF_20261107T1335Z -->
