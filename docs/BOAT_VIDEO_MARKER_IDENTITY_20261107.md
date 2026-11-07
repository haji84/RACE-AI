# 6艇の画像内識別・継続追跡の検証（2026-11-07）

**6艇の継続識別は未完成。** 1〜6の自動番号分類、全フレームの私有保存、画像内の対応付けを実装した。番号の一度の出現、累積登録数、追跡器の成功フラグを、6艇の継続識別の合格へ読み替えない。本番の予想モデル・既存自動予想プロセスは切り替えていない。

## 実装した経路

- `boat_video_marker_reader.py`: 原画全体を固定128px帯で覆い、従来の領域幾何を使って全候補を列挙する。候補4個で打ち切らない。既存の通常CRNN readerの既定4候補経路は保持した。
- `boat_video_ppocr.py`: 明示的なローカルSHA固定モデルだけをCPUで読む。公式と同じbatch6/全6,625クラスの前処理・CTC復号を使い、平均文字scoreと1文字のCTC経路和を区別する。数字だけへの再正規化や文字列の部分切出しで艇番を作らない。
- `boat_video_marker_verifier.py`: 明示opt-inの開発用HOG/SVM。数字1〜6/reject0と周辺画像の二値分類を返す。原画12数字・5非数字・synthetic字体・岸の非対象領域を学習しており、評価との学習重複がある。重みは私有保存し、Gitへ入れない。
- `boat_video_marker_flow.py` / `boat_video_marker_identity.py`: 実画素の特徴点と画像内幾何を使う。3つの別frame・PTS・画素SHAで番号根拠を作り、同じframeの複数cropを複数票にしない。画像切替・サイズ・時刻の不連続や曖昧な対応ではUNKNOWNへ戻す。
- `boat_video_marker_pipeline.py`: 全体再検出と局所読みを統合し、現在の再検出位置で追跡中の番号位置を補正する。同じ数字の内包/相互中心包含の候補は、直接対応する全組のグループ内だけで1観測へまとめる。連鎖的な統合と後段の再統合による重複番号チェックの迂回を拒否する。
- `scripts/boat_video_marker_analyze.py`: ローカル動画の全原frameを実PTSで処理し、私有journalと処理receiptを保存する。途中失敗・frame数不一致・保持FDのctime/終端SHA不一致ではSUCCESSを出さない。

分類器のラベルは `DECLARED_DEVELOPMENT_GLYPH_CLASSIFIER`、モデルSHA、`sequence_likelihood=null`、非確率scopeで保存する。汎用OCRの「7」を「1」へ書き換えてCTC確率とする実装ではない。全経路で `identity_validated=false` / `model_eligible=false` を維持し、hull全体の位置、世界座標、艇の強さ、予想の的中確率を推定しない。

## 実映像の結果

Nesnad「[Kyotei - Sept 7 2021](https://commons.wikimedia.org/wiki/File:Kyotei_-_Sept_7_2021.webm)」、[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)の既存私有原本を使用。25.859秒・775原frame、SHA256 `1ac1f0c27f58d8d64ebb1cfc13c2c4e9133cf7bbcce04052f23c28bf2e37f194`。新しいCommons取得は行っていない。

### 4区間・計76原frameの開発評価

全自動候補・実モデル・現在位置の再検出で、1〜6を含む86件のcurrent-frame番号登録を出力した。全86件の物理印字はAI原画参照と一致し、対象86件で背景登録・誤番号・観察されたswapは0。ただし学習重複のあるAI DEVELOPMENT参照で、人間の正解や独立holdout・一般精度の評価ではない。

| 番号 | 固定17frame参照でのcurrent登録 | 評価全体の登録数 |
| --- | ---: | ---: |
| 1 | 10/17 | 21 |
| 2 | 5/17 | 10 |
| 3 | 11/17 | 11 |
| 4 | 12/17 | 12 |
| 5 | 11/17 | 19 |
| 6 | 10/17 | 13 |

**固定6区間の継続完成は0/6、最大同時登録は3。** 重複片の修正で4は同一IDの485〜496の12frame（実PTS差0.367秒）に伸長したが、途切れは残る。6種類の累積出現を現在の6艇追跡へ加算しない。最終コードの実モデル出力は、原画採点済み86イベントとbbox・BGR・PTSが完全一致し、全317の実PP入力/softmax SHAも照合した。

### 全775原frameの別検証

CLIで原本全775frameを処理し、全BGR SHA・実PTSが以前のcanonical decodeと一致。原本SHA・ctimeの検証でも原本不変を確認した。処理receipt `6eacf60c101704287a28477bcf2373f520e989cc62b8bcc93045e4cb991a6bd5`、journal `f943bab96ea47c39735c36f1ce4fb0322e34ecdcd66f9a7fcee672bb8cc12ed2`。

この実行の510登録は全件正解の意味ではない。frame37では建物の線を番号4として登録した反例がある。76frameの86件の一致を、全775frameや別の実レースへ外挿しない。SUCCESSは処理完遂・原本整合性の状態で、識別精度の合格ではない。全編実行は旧CLI版、終了時整合性guardの修正版は別の実6frameでも検証し、元192〜197のBGR・PTSを6/6照合した。

## 継続性・背景除外の追加検証

- **CSRT**: 実3観測で番号を確認した12開始点から、各17隣接future frameを追跡。全204回で枠を返したが、原画照合では正しい対象船体186、同艇搭乗者だけ1、混合曖昧15、別艇2。17future全てで正しい船体patchを追う試行は9/12で、1〜6各番号に短い成功例がある。約0.567秒の独立試行であり、同時6艇・全レース・現在の番号の再読成功ではない。成功フラグが真のまま別艇へ移る反例があり、自動採用していない。
- **DeepLabV3 MobileNet**: 公式全21クラス、固定10原画像で評価。既知PP正読10/12を5/12へ減らし、建物をboatカテゴリにする反例もあるため必須gateへ採用しない。
- **DIS dense flow**: 10連続pairのうちcamera fit採用5。建物上の誤番号2件はSTATIC_LIKEだったが、実数字12例はDYNAMIC3/UNKNOWN9。静止した艇を背景と断定できないため、背景除外の必須条件へ採用しない。画像内の動きであり、世界座標の補正や艇速の証拠ではない。
- **Grounding DINO tiny**: 公式Apache-2.0の固定モデル・数字を含まない固定prompt・既定閾値で10全画像を評価。既知PP正読10/12が6/12になり、f328の1/2/3などを落とす。岸の階段をBOATとする反例もあり、必須gateに採用しない。10画像のCPU network合計258.802秒で、実時間予算の合格でもない。

補助試験は各モデルの元条件・RAW・失敗・採点・SHAを別保存した。未採用案で現在の本番予想を変更していない。CSRTの新参照には予測枠を見ていない段階で一部集計値を伝えた経緯があり、完全出力未見の評価とは表示しない。

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

`--single-continuous-shot` は利用者による単一shotの申告であり、自動的なshot認証ではない。通常のintake/job/予想モデルへこの開発reportを昇格させない。既存の1ファイルのデコード資源保護は明示し、取得レース数・総GET数・巡回回数・総稼働時間の停止上限は追加していない。

現在の公式LIVEの403/P01002は未解消で、拒否済み映像の再要求・別経路取得を行っていない。6艇の継続識別を実運用へ進めるには、船体と背景の区別、遮蔽後の再同定、同時6艇の継続性、正規取得できる現在映像での別レース検証が必要。ターン・出足・行き足・伸びの強さと予想改善も未実証である。

集計・source版・検証SHAは [構造化evidence](evidence/boat-video-marker-identity-20261107.json)、現在の完了/未完/外部条件は [最新状態](RACE_AI_LATEST_STATUS.md) に記録する。原動画・切出し・重み・私有URLはGitへ追加しない。
