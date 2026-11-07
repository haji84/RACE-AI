## 2026-11-08 作業継続：字幕の自動補完と前向き比較器

日本語OCRは従来の全画面灰色処理が成功してもphaseがUNKNOWNの場合だけ、固定の白文字抽出（gray>200を反転）を追加する。初回viewの説明文・競合は残し、失敗viewの文字を確定根拠にせず、各RAW/座標/画素SHAを保持する。既存CLIの `--phase-only --phase-tesseract /usr/bin/tesseract --phase-tessdata /private/tessdata --development` から自動使用する。入力ごとの実長・表示frame数を検査し、元動画全体を処理したかを受領証で確認する。文字の可読性を現在開催や艇・強さの認証にしない。

`race_ai.boat_video_forward` の `fit_matched` / `register_study` / `forecast` / `score` は既存2系統を呼び、同じ普通特徴・学習race・開催/媒体の分離と、映像なし学習版の対照を固定する。利用者が供給する `record_reader` は既存の認証済み私有artifactから正確なdocumentを取り出す信頼境界であり、JSON内の自己申告verifiedで置換しない。凍結study・予想・結果・比較を別に保存し、比較は入力原本参照まで封印する。新scheduler/モデル系統や本番自動切替は追加しない。実映像の締切前contextと学習実測がない現状を、fixture成功で完成扱いしない。

映像907件・比較関連86件・字幕37件はそれぞれ成功し、独立審査後の修正も確認済み（範囲は重複）。原動画5528frameのCLI完走と、識別学習・実実況・物理測定に残る未達を[中間証拠](evidence/boat-video-phase-matched-forward-checkpoint-20261108.json)に記録する。以下は過去の検証を当時のまま保存した履歴。

# 6艇の画像内識別・継続追跡の検証（2026-11-07）

## 2026-11-08の追加実装：画面内容の抽出と日本語実況

`boat_video_activity.py` に、固定ローカルUperNet/YOLOXから水面・艇の画面候補を抽出する経路を追加した。水面の占有率だけでは岸の大きい画角を見逃すため、現在の艇検出とADEの艇領域、水面につながる画像境界を使う補完結果を別fieldへ保存する。`primary_water_content_candidate` と `border_connected_boat_content_candidate`、両者の `primary_aquatic_content_candidate` を区別する。湖のclass128の取り漏れも修正したが、検証した旧312点には湖classがなく、この修正による見逃し回復は0だった。

新177点の封印済みAI参照との照合は、aquatic候補が陽性80/85・陰性への誤検出0/92。Fukuokaは55/56・0/90で、事前に決めたFukuokaと全体のゲートを通過した。一方、Nesnadは7/11で場面別90%に届かず、水面単独も72/85で不合格。既知媒体内の別フレームによる開発評価であり、別媒体・humanGT・LIVE・艇の同一性・予想精度の合格とは区別する。

同じmedia SHAの展示文脈がある場合だけ `depicted_exhibition_content_candidate` を出す。文脈なしの新177点は全てfalse、`specific_phase=UNKNOWN`を維持した。画面内の小窓が画像の隅に接している場合の曖昧さも記録する。現在の展示開催・動作・スタート/周回の認証は行わない。

```bash
python scripts/boat_video_marker_analyze.py \
  --media /private/input/video.mp4 --output-dir /private/output/new-content-analysis \
  --phase-only --activity-model /private/models/upernet-convnext-tiny \
  --activity-boat-model /private/models/object_detection_yolox_2022nov.onnx \
  --exhibition-topic-context /private/input/source-topic.json --development
```

文脈JSONは所有者専用600の通常ファイルとし、次の4fieldのみ。`media_sha256` は実入力のSHA、`provenance_sha256` はその文脈の出典受領証のSHAに置く。`topic` は `EXHIBITION_TUTORIAL` / `EXHIBITION_BROADCAST` / `UNKNOWN`。この宣言の一致を開催認証へ昇格させない。

```json
{"schema_version":"RACE_AI_LOCAL_MEDIA_TOPIC_CONTEXT_V1","media_sha256":"<実入力SHA256>","topic":"EXHIBITION_TUTORIAL","provenance_sha256":"<文脈出典SHA256>"}
```

毎秒の観測だけを抽出し、全decoded frameと原PTSをjournalへ保存する。浮動小数の差で秒境界を飛ばさないよう、比較だけをmicrosecond精度の固定gridへ合わせた。区間は2つの異なる観測画像から確認し、未観測frameを補間しない。始終端の観測範囲・陰性・UNKNOWN・EOFの打切りを保存し、再表示による同一画像は区間内の確認回数を増やさない。内容の再表示区間は別に記録する。実原画360frameのBGR/PTS全一致と12回の実NN・固定V2幾何値の一致を保全した。さらに原動画4376frameを最終V4コードで全処理し、146回の実NN、同じmediaの展示文脈による54観測点・1候補区間を保存した。全4376frameのBGR/PTSが元decodeと一致し、146回全ての38判定field・class map hashも固定V4と一致。製品CLI全体は577.718秒で、実時間処理は未達、密な区間境界精度は未検証。

`boat_video_reazon.py` は、固定4assetの日本語ReazonSpeech/Sherpaを追加した。任意依存は `requirements-video-speech.txt`。既存CLIで `--commentary-model /private/models/reazonspeech-k2-v2-int8 --commentary-profile reazon-k2-v2-int8` を選べる。既定Tinyは維持し、Kotobaも `--commentary-profile kotoba-v2` で明示する。モデルはダウンロードしない。Reazonの既定は公式greedyで、`reazon-k2-v2-int8-context` は独立作成した一般36語を使う研究用設定。辞書による改善は未実証で、自動採用しない。

一般36語を使うReazon試作では音声約720秒・144窓のNN合計が101.602秒だった（製品CLI全処理時間ではない）。ただし、人の参照がある2つの順位対応は1/2のまま。対象艇番自体は2/2を読める。Whisperの複数設定、一般36語・219句、長い履歴、公式FP32原本の比較も未達を保全し、不明語を正解語へ置換しない。別Base-ASRとの一致はAI参照との比較として別集計する。低信号35窓にも非空の認識文が出たため、低信号保留を維持する。処理速度を認識精度と混同しない。

モデル読込は保持したdescriptorから行い、祖先パスの一時的な差替え・ファイル変更を検知/排除する。実況の否定・願望・追跡対象・言い直しは現在順位として採用せず、途中の不明語は保留する。実装の全テストと実認識の合否を分ける。`model_eligible=false` / `production_eligible=false` を維持し、既存自動予想・予想原本を変更しない。

[今回の機械可読な検証記録](evidence/boat-video-activity-native-commentary-corrections-20261108.json)と `docs/RACE_AI_LATEST_STATUS.md` に、実装済み・開発評価・未達を分けて記録する。

## 前回の展示区間・実実況の検証結果（修正前の記録）

自動区間の既存実装はなく、宣言phaseだけだったため、`boat_video_phase.py` に固定日本語画面OCRと時系列候補を追加して実行した。全147点を原画だけのAI参照と照合すると、展示55点のうち確定候補1点、生候補3点。誤検出0だが見逃し/保留が多く、周回展示18点は全保留。持続区間の検出は未合格。人間GTや実LIVEの認識率ではない。

既存原動画4376frameを全てCLIで保存し、146OCR観測を作成。参照147点はBGR/実PTS全一致。phaseだけなら印字モデルや単一shot宣言を使わずに解析できる:

```bash
python scripts/boat_video_marker_analyze.py \
  --media /private/input/video.mp4 --output-dir /private/output/new-phase-analysis \
  --phase-only --phase-tesseract /usr/bin/tesseract \
  --phase-tessdata /private/models/tessdata-fast-jpn --development
```

必要な `jpn.traineddata` はコードの固定revision/SHAに一致するローカルassetを用意する。自動downloadなし。1秒間隔はOCRだけのsampleで、全decoded frameを保存する。撮影内容を意味的に理解したphaseではなく、説明文・競合・読めない文字は保留する。音声へ自動的なphase正解を付けず、身体ID/本番予想へ昇格させない。

実実況は正常取得できた同一アーカイブ原本の24分を取得して全288窓を保存し、2R走行/ゴールと次3R展示の混在を確認した。別Base-ASRもTinyを見ずに転記したが、それだけでは人手正解にならない。オーナーが聞き取った5秒では、先頭1番/2番手6番に対し、現製品の順位対応は0/2、対象の明示艇番は1番だけ（1/2）だった。元ASRの「先頭→戦闘」等を正解へ書き換えない。1clipで全体精度を断定せず、この例の未合格を記録する。

空PCMとなる大きな絶対PTS、private TSV設定、fractional OCR box、説明の裸「番」誤受理を修正。低信号はVADの正解ではなく識別根拠の保留とし、高信号でのASR幻覚も残す。関連映像778件PASSはソフトウェア契約の検証で、上記の実認識不合格を取り消さない。[検証値・参照・証拠SHA](evidence/boat-video-phase-commentary-validation-20261108.json)。

**最新の主経路は選手の服色による識別。** オーナーの明示指示に従い、白1・黒2・赤3・青4・黄5・緑6を読み取り、印字番号なしで同じ乗員の実画素を追うコードを追加した。既存の実映像61frame/2秒では、初期確認後の57frame連続で全6色の対応が一致し、誤番号0、motor25行への番号付与0。これは開発中に参照した低運動映像の結果であり、別場・交差・隠れ・現在のLIVEや船体全体の識別まで合格した意味ではない。本番予想モデル・既存自動予想プロセスは切り替えていない。

## 衣服色を主にする追加経路

### 周回展示の順番と実況を補助にする経路

`boat_video_broadcast_context.py` は、明示された個別周回展示の通過index/予定艇順、または時刻付きの「○号艇の周回展示」を補助候補へ変換する。予定順だけで現在の乗員を確定せず、複数乗員が映る場合は未結合。スタート展示の進入コース順と区別する。欠場・区間見逃し・放送切替を勝手な1〜6カウンタで補完しない。

レース実況の艇番と順位は別の値として解析し、服色ですでに得たIDへ「実況で告げられた順位」を対応させる。画像の左右から順位を推測せず、実況で服色ラベルを上書きしない。否定・疑問・人気順・数値断片・言い直しは保留。訂正や新しい発話の後、古い情報を期限切れによって復活させない。実況は公式結果でも締切前予想の入力でもない。

captureの新exportは最初の埋込音声を再圧縮せず残し、旧exportは不変。音声付きの元clipがない場合、既存の音声なし動画から実況は復元できない。別HLS音声groupの取得はこの修正に含まない。

`boat_video_commentary.py` は固定SHAの既存ローカルWhisper-tinyを使う任意経路で、自動downloadなし。5秒窓を全て処理し、音声窓の終端より前に認識結果を使わない。実audio frameのPTS/sample数を検証し、時刻飛びは補間せず拒否する。推定word timestampは使わず、frameの絶対source_ptsへ結合する。2秒の有効期間と放送遅延は未校正の宣言条件。

既存のTorch/Transformersとvideo依存が揃った私有Python環境で実行する（検証環境: Torch2.9.1+cpu、Transformers4.57.3、`requirements-video.txt`）。例:

```bash
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 python scripts/boat_video_marker_analyze.py \
  --media /private/input/video.mkv --output-dir /private/output/new-analysis \
  --rider-model /private/models/object_detection_yolox_2022nov.onnx \
  --commentary-model /private/models/whisper-tiny \
  --clothing-only --broadcast-phase RACE --development --single-continuous-shot
```

phaseが不明なら既定UNKNOWNのまま文字起こしを保存し、番号を作らない。既存の時刻付き宣言contextを使う場合は `--broadcast-context /private/context.json`。入力はprivate・SHA一致のJSON、出力はGit外の新規私有ディレクトリに `broadcast-context.json` / `commentary-receipt.json` / 全frame journalと受領証を保存する。mediaSHA不一致・音声時刻不整合・途中失敗はSUCCESSにしない。

実音声145.844535秒/30窓を27.906秒で処理。元動画は展示の日本語解説で、番号/順位実況の正解データではない。専門語の誤認識・旧試行の反復を保存し、ASR精度やLIVEの識別改善を合格にしない。別の6秒間引き動画で実人物検出＋実音声認識＋CLI保存も実行したが、連続6艇の受入とは別。関連映像748件PASS。[補助情報の証拠と未実証条件](evidence/boat-video-broadcast-context-20261107.json)。

`race_ai/boat_video_clothing_identity.py` は、既存PERSON提案と実LK追跡に服色の観測を合成する。3つの別原frameで確かめ、色が読めない間は現在の実画素対応が明確なときだけ以前の色IDを保持する。fresh観測と保持を分け、印字観測は常にfalse。重複色・明示的な競合・画面切替・追跡喪失を処理し、残り番号の穴埋めをしない。数字OCRや追加学習モデルは不要。

薄い緑はHSV彩度だけで白へ落とさず、GがR/Bより強いかも確認する。白黒は同じ原frameのneutral候補の明暗差を使い、照明条件の仮説を出力する。単独の中間灰色を黒と決めない。色面積率・検出scoreは校正確率ではない。

衣服領域には人物box内の固定位置priorを用い、**衣服の意味的segmentationではない**と各観測へ記録する。実原画の18anchorにもhelmetや機材境界の混入がある。黒服＋色hood、小柄・影・異なる照明の実運用精度は未確立で、`identity_validated=false` / `model_eligible=false` を保持する。色付き乗員partから船体位置・出足・ターン性能や予想改善を作らない。

既存コマンドに服色だけの経路を追加した。元動画・モデルはローカルの既存ファイル、出力先はGit外の新しい私有ディレクトリとする。

```bash
python scripts/boat_video_marker_analyze.py \
  --media /private/input/video.mkv \
  --output-dir /private/output/new-analysis \
  --rider-model /private/models/object_detection_yolox_2022nov.onnx \
  --clothing-only --development --single-continuous-shot
```

`--rider-model`付きの既存複合経路も服色を主にする。匿名だけの従来出力が必要なら`--anonymous-riders`。1入力の解析資源ガードと取得総数・GET・巡回回数・総稼働時間の上限は別で、後者の停止上限は追加していない。既存CI内へ17件の服色回帰を追加し、関連映像696件PASS/0skip。原画の一時変更に対する私有snapshotと、終端保存失敗時の原子的state更新は独立レビューでRED再現後に修正した。[版・実測・証拠SHA](evidence/boat-video-clothing-identity-20261107.json)。

以下は番号印字を主にしていた以前の経路・失敗の保存記録。今回の服色観測とは混ぜない。

## 実装した経路

- `boat_video_marker_reader.py`: 原画全体を固定128px帯で覆い、従来の領域幾何を使って全候補を列挙する。候補4個で打ち切らない。既存の通常CRNN readerの既定4候補経路は保持した。
- `boat_video_ppocr.py`: 明示的なローカルSHA固定モデルだけをCPUで読む。公式と同じbatch6/全6,625クラスの前処理・CTC復号を使い、平均文字scoreと1文字のCTC経路和を区別する。数字だけへの再正規化や文字列の部分切出しで艇番を作らない。
- `boat_video_marker_verifier.py`: 明示opt-inの開発用HOG/SVM。数字1〜6/reject0と周辺画像の二値分類を返す。原画12数字・5非数字・synthetic字体・岸の非対象領域を学習しており、評価との学習重複がある。重みは私有保存し、Gitへ入れない。
- `boat_video_marker_flow.py` / `boat_video_marker_identity.py`: 実画素の特徴点と画像内幾何を使う。3つの別frame・PTS・画素SHAで番号根拠を作り、同じframeの複数cropを複数票にしない。画像切替・サイズ・時刻の不連続や曖昧な対応ではUNKNOWNへ戻す。
- `boat_video_marker_pipeline.py`: 全体再検出と局所読みを統合し、現在の再検出位置で追跡中の番号位置を補正する。同じ数字の内包/相互中心包含の候補は、直接対応する全組のグループ内だけで1観測へまとめる。連鎖的な統合と後段の再統合による重複番号チェックの迂回を拒否する。
- 同じ実画素contextを追うLK情報を `context_image_track` として対応付けへ渡す。前frameのSHA・scene・移動・一意なkeyと同じfresh番号が整合する場合だけ使い、別の位置/面積予測で根拠を切り直さない。これは `CONTEXT_IMAGE_TRACK` であり、船体や番号の真正性の証明ではない。正規flowの最終品質が任意hintの条件外なら理由を記録して従来geometryへ戻し、不正なschema・非有限値は拒否する。
- `scripts/boat_video_marker_analyze.py`: ローカル動画の全原frameを実PTSで処理し、私有journalと処理receiptを保存する。途中失敗・frame数不一致・保持FDのctime/終端SHA不一致ではSUCCESSを出さない。

分類器のラベルは `DECLARED_DEVELOPMENT_GLYPH_CLASSIFIER`、モデルSHA、`sequence_likelihood=null`、非確率scopeで保存する。汎用OCRの「7」を「1」へ書き換えてCTC確率とする実装ではない。全経路で `identity_validated=false` / `model_eligible=false` を維持し、hull全体の位置、世界座標、艇の強さ、予想の的中確率を推定しない。

## 実映像の結果

Nesnad「[Kyotei - Sept 7 2021](https://commons.wikimedia.org/wiki/File:Kyotei_-_Sept_7_2021.webm)」、[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)の既存私有原本を使用。25.859秒・775原frame、SHA256 `1ac1f0c27f58d8d64ebb1cfc13c2c4e9133cf7bbcce04052f23c28bf2e37f194`。新しいCommons取得は行っていない。

### 4区間・計76原frameの開発評価

同じ全自動候補・実モデル・原画で対応付けを修正し、current-frame番号登録は86→98件になった。旧86件の番号・bbox・BGR・PTSを全て保持し、追加12件も別のAI原画採点に一致した。追加12件には明確な部分glyph6件と字端接触4件があり、PP生文字の不一致3件は書き換えていない。これらは学習重複のあるAI DEVELOPMENT参照で、人間の正解や独立holdout・一般精度ではない。

| 番号 | 固定17frame参照でのcurrent登録 | 評価全体の登録数 |
| --- | ---: | ---: |
| 1 | 11/17 | 26 |
| 2 | 10/17 | 15 |
| 3 | 13/17 | 13 |
| 4 | 12/17 | 12 |
| 5 | 11/17 | 19 |
| 6 | 10/17 | 13 |

**固定6区間の継続完成は0/6、最大同時登録は3。** 固定102機会の登録は59→67。初回登録frame以降は67/84だが、これは全102の分母を置き換えない。初回の3観測待ちと、断絶後の再暖機を分ける。4は同一IDの485〜496の12frame（実PTS差0.367秒）で、開始時の背景重複・遅延も残る。6種類の累積出現を現在の6艇追跡へ加算しない。最終 `94d80c7e…/956658ac…` の実再推論は、追加12件を採点した候補版の実出力と全76 identity recordが完全一致。全317の実PP入力/softmax、32,587分類、全flow・番号入力も一致し、差は任意hintの診断欄だけだった。

### 未登録の実原因と修正範囲

修正前の102機会には未登録43件があった。current番号が対応付けまで到達済みの31件は、対応付けの再起動10件と3観測未達21件。残りは重複2件、局所glyph棄却3件、既知lineage消失2件、密な参照がなく上流を区別できない5件だった。3観測未達21件には正常な初回待ち7件も含まれ、全てを不具合や復元可能件数とは数えない。

実際に同じS key・TRACKED・同じfresh番号でIDを切った5件は、2の207/211/215、1の241、3の316。距離3件・面積比2件で、既に3観測以上を持つ3件も捨てていた。typedな画素対応を渡してこの二重判定を修正した。min3・重複・異番号競合・blank・cut/時刻/サイズの拒否は維持する。

別の原因は、480/482の岸の橙黒部材を4と分類し、真の4も重複として棄却したこと。重複guardは正常なので緩めない。小さいglyph周辺の分類と、艇/搭乗者の意味的な検出・番号の結合が別の未達である。

### 全775原frameの別検証

最新コードでもCLIで全775原frameを再処理し、全BGR SHA・元PTS・indexが以前のcanonical decodeと一致。原本SHA・ctime、source/重みの実行前後pinも不変だった。最新receipt `ecf119e92b7ea89ff768a7b0fe5fa1a9039ea10d7d1cd4adcae90b306d2d734e`、journal `92d998ba52e0f44e8a95e94f4278c18dfc938d8a93d9e568625ef137492a6f22`。

最新全編は606登録、最大同時3。全606件をcurrent原画で採点・封印し、現在の正しい艇番印字564件、背景非数字36件、艇体上の非数字5件、判読不能UNKNOWN1件だった。全606行のrow/event hashと完全被覆を照合した。正しい印字の最大同時数も3で、学習重複のあるAI DEVELOPMENT参照である。frame37の建物の線を4とする反例は最新でも同じ位置に残る。76frameの98件の一致を全編へ外挿しない。SUCCESSは処理完遂・原本整合性の状態で、識別精度の合格ではない。以前の旧版全編510登録と、そのreceipt/journalは別の版として保存した。

最新775の同じ番号入力を使った対応付けだけの再生では、旧Mと新Mのhint無しが全775件で一致し541登録、hint有りは実出力と全775件で一致し606登録（追加65、削除0）だった。これは追加NN/OCR/LKを実行しないcounterfactualであり、実推論を増やした証拠ではない。全606採点を先に封印した後で追加65件へ一意に結合すると、正しい印字63件と艇体上の非数字誤登録2件だった。旧541件は正しい印字501・背景非数字36・艇体非数字3・UNKNOWN1。正読の増加と誤登録の増加を両方保持し、ラベル変更は0。

## 継続性・背景除外の追加検証

- **CSRT**: 実3観測で番号を確認した12開始点から、各17隣接future frameを追跡。全204回で枠を返したが、原画照合では正しい対象船体186、同艇搭乗者だけ1、混合曖昧15、別艇2。17future全てで正しい船体patchを追う試行は9/12で、1〜6各番号に短い成功例がある。約0.567秒の独立試行であり、同時6艇・全レース・現在の番号の再読成功ではない。成功フラグが真のまま別艇へ移る反例があり、自動採用していない。
- **DeepLabV3 MobileNet**: 公式全21クラス、固定10原画像で評価。既知PP正読10/12を5/12へ減らし、建物をboatカテゴリにする反例もあるため必須gateへ採用しない。
- **DIS dense flow**: 10連続pairのうちcamera fit採用5。建物上の誤番号2件はSTATIC_LIKEだったが、実数字12例はDYNAMIC3/UNKNOWN9。静止した艇を背景と断定できないため、背景除外の必須条件へ採用しない。画像内の動きであり、世界座標の補正や艇速の証拠ではない。
- **Grounding DINO tiny**: 公式Apache-2.0の固定モデル・数字を含まない固定prompt・既定閾値で10全画像を評価。既知PP正読10/12が6/12になり、f328の1/2/3などを落とす。岸の階段をBOATとする反例もあり、必須gateに採用しない。10画像のCPU network合計258.802秒で、実時間予算の合格でもない。

補助試験は各モデルの元条件・RAW・失敗・採点・SHAを別保存した。未採用案で現在の本番予想を変更していない。CSRTの新参照には予測枠を見ていない段階で一部集計値を伝えた経緯があり、完全出力未見の評価とは表示しない。

追加した20字（許諾写真8枚）を同じHOG/SVMへ一度学習しても、別映像のoracle18字は旧0/18→新5/18、非ゼロ誤読2・棄却11で、全6が揃うanchorは0。広い番号周辺を既存YOLOXへ渡す固定21入力試験も、真の印字16位置中5だけ保持したため必須gateにしない。26行で学習したbody HOGも転移時の艇8/10・背景7/12、wholebody RGB番号分類も転移1/8で不採用。再fitや閾値変更で結果を隠さない。

既存YOLOXの別映像3frame・最終20boxを全て原画確認すると、全6艇の物理partは各frameに含まれていた。ただし全体envelope1・hull part11・複数混在8。riderを含む正解枠とのIoU不足を、艇の一部すら検出していないことと同一視しない。番号・現在の可視対象・歴史的な番号根拠を分離し、艇に結びついたrider partも別型で調べている。これを全6の自動番号識別成功とは数えない。

### 乗員の検出と番号読取を分けた修正

`boat_video_rider_detector.py` を追加し、既存SHA固定YOLOXのCOCO class0 PERSONを、boat/hullとは別の `RIDER_PART_TYPED` 候補として返す。モデル・前処理・固定score条件・native7viewは既存と同じ。person候補は乗員の所属や番号の証明ではなく、重みの追加配布・download・本番既定切替は行わない。元のboat detectorは変更しない。

固定3原frameのcached後処理では各6人、全18件が別々の実乗員の頭部/胴体に対応した。可視rider全景の参照IoU≥.5は16/18で、2件は腕の範囲が欠ける部分検出。親艇への最大重なり候補9/18は複数艇が混ざり、person boxの包含や最近傍だけで艇番を結合できない。

製品detectorの別実行は、固定61原frame・元BGR/PTSで427回forwardし、373候補を保存した。候補数6のframeは40、5は8、7は11、8は2で、全61で6人を一意に検出したとは言わない。全3anchorのbox/score配列は先のcached18件と完全一致。全373件の原画採点は、実乗員part369（境界に別乗員が混ざる可能性UNKNOWN2を含む）・船外機の非人物4・同乗員重複part11（369の内数）。実乗員6人が揃うのは53/61frameで、原画上は6人とも全61で可視だった。これを全6継続の合格にはしない。番号未読を余った番号で埋めない。

`boat_video_rider_tracking.py` は、typed detectorと実LKの対応を使い、未読でも匿名Rを出す。現在の画素支持・最後の再検出・fresh/flow-only・lost/曖昧性を区別し、番号は別の明示physical-pair producerだけが3つの別frame/PTS/BGRから作れる。包含/近さ/色/appearanceだけを印字観測として受け入れない。宣言pairも真正性証明ではなく、既定producer=Noneで番号は全UNKNOWN。矛盾するreplayed画素で古い番号が復活する問題、別Rが同じ印字へ異番号を主張する問題、重なるflow-onlyを二重出力する問題をREDで再現・修正し、独立レビュー7case GREEN。

固定61の実LK＋先の実検出373件の完全replay（新NN0）では402track行、匿名4IDは全61で継続。数字は全None・船体boxなし。402行の別原画採点は乗員part377・船外機25、既存373検出を一意joinしflow-only29も全件目視した。6人の可視part自体は全61で存在する一方、重複/船外機なしの6出力は30/61。6番のpartは7匿名ID、4番は11IDへ断絶し、これを6艇の連続IDには数えない。余分なflow-only棄却5も原画確認し同乗員の重複partとして別保存した。観察範囲で同Rの別primaryへのswapは0だが、AI DEVELOPMENT/短い2秒で現場精度ではない。flow-successを実乗員や艇番の証明にはしない。

対応付けを追加修正した版 `98befe…` では、元のIoU≥.5を保持し、同じcurrent Fの実点≥4・既存品質比率.75・他R点0・現BGR/PTS/index/sceneの一意な支持を使う。既存画像点に触る未結合proposalは、新人物と決めずUNBOUNDとして全件保存する。current pixel ownerは人物や番号の認証ではない。

同じ61原画で実LKを再実行すると、6人のprimary rider partをR1〜R6の同一匿名keyで全61・2.0秒追跡できた。全391出力を原画照合し、乗員part366・船外機25、primary swap観測0。旧版の真6人の完走4→6、同乗員重複出力11→0、R key総数23→7。motor25は減っておらず、余分な非人物なしの6出力は36/61に限られる。全373の実検出はfresh362＋UNBOUND11に完全分割して保存し、355対応根拠は幾何336＋current LK点19。モデルNNは既存427回の出力をreplayし、新NN0、実LK13.921秒。これは2秒の私有既存映像の画像内part追跡で、数字全None・hullなし・人間GT/現場/全レースの6艇識別完成ではない。

番号分類には別の不足がある。写真の直接印字と結び付いた乗員12例で学習したRIDER RGB分類器も、正しい乗員cropを与えたoracle18例で一致10・誤り7・UNKNOWN1、全6一致0/3、4/6の正答は0だった。背景29例も24例を数字へ誤分類し、単独gateや番号器へ採用しない。Todoの4/6は衣服自体の低彩度、6は黄緑側のhue、1は直立の白上衣と黒下衣など、訓練写真との画素・姿勢差を確認した。日照原因や個別部位の判断寄与は未確定。正しい領域を与えるだけでは番号問題が解決しないという容量検証であり、OCRや自動6艇識別の合格ではない。

16原frameの性能計測では全候補抽出がprofile内pipeline時間の約67%。refresh8はrefresh1より速いが登録27→16へ低下した。2band並列は全8,509候補と順序が一致した一方、壁時間約4%短縮に対しCPU約56%・最大RSS約65%増で、採用根拠は弱い。profile/同時負荷の影響もあり実時間性能の保証ではない。候補削除や古い番号の保持で高速化したことにはしない。

marker修正時の映像回帰は **627件PASS/0skip、69.171秒**、関連6moduleは122件PASS。独立レビューで発見したflow再計算後の品質値による例外中断も再現して修正・再レビューGREEN。旧全体Python3,106件PASSは以前のcommitの記録で、後続の全HEADが合格したとは扱わない。

初回rider/任意CLIの映像回帰は **670件PASS/0skip、71.743秒**、current point版の最初のCI fixture検証は **677件PASS/0skip、76.335秒**（ローカルMatroska版）。detector39・CLI16の独立制御テストもPASS。これは関連映像moduleの検証で、最新repository全HEADの全3,000件超や現場精度の合格を意味しない。775全編の実行は旧CLI `89e63…`、rider追加はCLI `b3f802…` とsource scopeを分けて保存する。

追加データは既存許諾写真の新36字（4は6例・6は7例、1は0で補完しない）と可視rider46観測、別型の人の居ない機材66＋IGNORE9を原画で確認・封印した。既存20写真字と合わせ56字で、作者・series相関を維持する。旧14,120行の画像を再生成してHOG541/label全一致を確認し、新36×200を追加した21,320行で小CNNを1回・30epoch学習。保存前後の全train logits一致まで確認したが、別の同一oracle18評価は8一致・9棄却・異番号1、4の正答0/3、全6正読anchor0/3で不採用。旧追加20字HOGの5一致に対し新5件を読み、以前の正読2件を失った。データ追加と表現/学習方式が同時に変わるため、算法単独の改善率とはしない。重みは私有のまま本番へ適用しない。機材negativeは「人が居ない」の注釈であり、印字数字が無いという教師へ流用しない。

18個のnative glyphだけを匿名化し、場面・艇番範囲・モデル出力を伏せて別AIへ再読させると、CLEAR6・AMBIGUOUS12。CLEARは既存場面参照1を7と読む3例と5を5と読む3例、2/3/4/6各3例は曖昧だった。これは新しい人間GTではなく、既存参照も書き換えない。小さい単字の文脈依存を、分類器の不具合や根拠不足と分けるための監査であり、7を1へOCR訂正する処理は追加しない。

既存DINOをPERSON queryへ変えた固定22contextの別容量評価も、真18の本人支持13・隣接人2・候補なし3、motor4全て誤PERSONを残し、必須gateへ採用しない。元条件・全900×22のraw・全20box・意味採点を保存し、数字や色query・閾値調整は行わない。

CI `42351039195` は合成MP4 fixtureの「6枚で一意」の前提で失敗した。ローカルFFmpeg7でもencoded6枚/decoded5枚というedit-list関連の反例を再現。製品decoderを変えず、並行HEADに入ったMP4の明示6枚・muxer `output_ts_offset=2`・encoded/probed/decoded枚数確認を取り込んだ。統合したCLI16件もPASS（4.827秒）、統合後の映像全677件もPASS/0skip（68.198秒）。先のローカルMatroska検証は別scopeの証拠として保持し、現在のfixtureへ再実行済みとしない。最新exactHEADのCI合格とは別に記録する。

## 実行方法と範囲

```bash
python -m pip install -r requirements-video-ocr.txt
python scripts/boat_video_marker_analyze.py \
  --media /private/clip.webm \
  --output-dir /private/new-marker-report \
  --recognizer-model /private/ch_PP-OCRv4_rec_infer.onnx \
  --context-model /private/context-svm.xml \
  --glyph-model /private/licensed-development-hog-svm.xml \
  --development --single-continuous-shot
```

SHA固定の私有モデルが必要。今回の資産は同じクラウドworkspaceの `owner-files/six-boat-completion-20261107` に保全している。cloneだけで重みを取得する処理はなく、新しい外部サービス・アカウント・課金を要求しない。出力先は新規の私有directoryで、既存ファイルや原本を上書きしない。

任意に `--rider-model /private/object_detection_yolox_2022nov.onnx` を加えると、同じ原frame・PTSで匿名PERSON partを処理し、`pipeline_result.rider_part_tracking` とreceiptへ別保存する。marker番号はriderへ結合しない。local SHA固定モデルのみを使い、途中rider失敗も既存journalの部分保存とFAILEDにし、SUCCESSを出さない。既定のmarker経路・intake・予想エンジンは保持する。

`--single-continuous-shot` は利用者による単一shotの申告であり、自動的なshot認証ではない。通常のintake/job/予想モデルへこの開発reportを昇格させない。既存の1ファイルのデコード資源保護は明示し、取得レース数・総GET数・巡回回数・総稼働時間の停止上限は追加していない。

既知の公式LIVE contentの403/P01002と、同providerの追加probe停止は維持し、拒否済み映像の再要求・別経路取得を行っていない。全会場403・全会場が外部API契約必須という証拠はない。別providerの現在content/利用条件は未確定。6艇の実運用には、可視対象と番号の一意な結合、背景除外、遮蔽後の再同定、同時6艇の継続性、正規の現在映像での別レース検証が必要。ターン・出足・行き足・伸びの強さと予想改善も未実証である。

最新の原因・修正・source版・検証SHAは [継続evidence](evidence/boat-video-identity-causes-20261107.json)、旧86件段階は [以前のevidence](evidence/boat-video-marker-identity-20261107.json)、完了/未完/外部条件は [最新状態](RACE_AI_LATEST_STATUS.md) に記録する。原動画・切出し・重み・私有URLはGitへ追加しない。

## 最終チェックポイント：番号付き6艇は未完成

RGB外観CNN V1を固定166base/8,300variant・30epochで1fitし、別担当が手動RIDER18と自動373/追跡391入力をRAW先封印で評価した。自動391の真の乗員part366では181一致・170棄却・2→3の誤り15。境界UNKNOWN2を除く正式364例は179一致。1/6は全61で棄却、全6番号一致0/61。motor25は全て0だが、真の人物も多数落とすので必須gateへ採用しない。番号の外観候補であり印字観測ではない。

封印済logitだけを追加推論なしで調べても、1の正解class順位は6〜7位、6は3〜5位だった。0を無視すると1は2/3、6は5となり、motor25にも偽番号を付ける。棄却条件を緩めるだけでは解決しない。人物存在と番号未読を分離し、姿勢・衣服・低彩度の新しい許諾データで表現を改善する必要がある。

SAM2の自動BOAT箱20から全60maskを保持した試験は、清潔な単一hullの原画coverageが3時点で5/6・5/6・6/6。既定quality最大＋mask NMSの固定selectorでも同じで、6艇instanceの完成とはしない。検出PERSONのbottomcentreを正例、他PERSONのbottomcentreを負例とする自動contact V2は、手動point/正解bbox/番号なしで20pair・60maskを完走・保存したが、意味採点は未実施。

別公開元Flickrの個別CC BY-SA2.0を確認した原本100枚は、原本・license・native RGB/BGRの全件SHAと重複0をrootでも確認した。100は既知公開link集合を処理した結果で取得上限ではなく、公開catalogの未列挙gapも残す。施設/航空機等を含むため100rider教師や独立100人とは数えない。大きい印字1と白い上衣のrider1写真は別V2候補としてnative注釈済みで、固定V1学習には混ぜていない。公式LIVEの403を解決した証拠ではない。

継続中の複数開発agentが実際に利用上限エラーとなった。追加課金や新accountは作成せず、確認済みコード・全原本・失敗・未着手を保全した。既存予想/映像intakeのPIDと起動時刻・保護checkout・予想原本SHAは維持。6匿名part追跡の成立を、番号付き6艇や強さ/予想改善の完成へ読み替えない。
