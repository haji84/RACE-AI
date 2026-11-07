# 6艇の画像内識別・継続追跡の検証（2026-11-07）

**6艇の継続識別は未完成。** 1〜6の自動番号分類、全フレームの私有保存、画像内の対応付けを実装した。番号の一度の出現、累積登録数、追跡器の成功フラグを、6艇の継続識別の合格へ読み替えない。本番の予想モデル・既存自動予想プロセスは切り替えていない。

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
