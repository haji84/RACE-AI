# 展示映像の実験計測

既存PR #71で、ローカル映像の自動取込、復号、艇の検出と数字OCRによる6艇の候補追跡、カメラ補正、4区間の計測、私有保存と既存モデルへの実験接続を実装する。**実映像で強さを評価する機能の完成を意味しない。** 正規の映像供給、6艇識別の実測、独立した正解・将来結果との照合は別の受入条件である。

## 実行

通常の予想運転とは別のプロセスで実行する。既存アプリ・workerを止めない。

```bash
python -m venv /absolute/private/video-tools
/absolute/private/video-tools/bin/python -m pip install -r requirements-video.txt
```

FFmpeg / FFprobeも必要。インターネット上の動画URLやプレイリストをデコーダーへ渡す機能はない。利用できる映像をローカルの通常ファイルとして用意し、その実バイトSHA256をマニフェストへ記録する。

```bash
/absolute/private/video-tools/bin/python scripts/boat_video_analyze.py \
  --video /absolute/private/exhibition.mp4 \
  --job /absolute/private/video-job.json \
  --private-root /absolute/private/reports
```

保存先はGit外の既存0700ディレクトリ。報告は `video-evaluations/<report_sha256>.json` に0600で追記し、既存版は上書きしない。stdoutは報告SHA、保存先、計測件数だけを返す。入力エラー時に本文や秘密値を表示しない。

マニフェストの契約は `RACE_AI_BOAT_VIDEO_JOB_V1`。必要な項目:

- `race_id`: `YYYYMMDD-JJ-RR`、`cutoff_at`: タイムゾーン付きの同じJST開催日の締切。
- `roster`: 1〜6号艇それぞれの `lane` と4桁の `registration_number`。原本と一致する実登録番号を使用する。
- `source`: `kind`、`media_sha256`、実際の `captured_at`、`identity_status`。ローカル映像は `OWNER_LOCAL` / `OWNER_DECLARED`、合成テストは `SYNTHETIC_TEST` / `SYNTHETIC`。
- 任意の `options`: サンプリング頻度・画面内水面領域・解析資源の設定。資源境界を超えたファイルはエラーにし、途中までの解析を完了として保存しない。自動予想の対象レース数には影響しない。
- 任意の `phase_windows`: 号艇番号を文字列キーにし、`turn` / `exit` / `runup` / `straight` の `[開始秒, 終了秒]` を指定。指定区間は呼出元の申告であり、自動的に実走行区間と認証しない。
- 任意の `start_gate`: 補正後の画像座標による線分 `a` / `b` と垂直な通過方向 `normal`。行き足は実際に観測された通過前の区間が必要。未設定をゼロや未検証STで補完しない。

翌日以降に取得したリプレイも解析できる。取得日を開催日に偽装しない。解析開始・完了は実時計から記録し、取得・開始・完了のすべてが締切前でなければ `pre_cutoff_available=false`。このフィールドも外部の独立時刻認証ではない。

## 保存済み予想と一緒に閲覧

```bash
/absolute/private/video-tools/bin/python scripts/boat_video_analyze.py \
  --video /absolute/private/exhibition.mp4 \
  --job /absolute/private/video-job.json \
  --private-root /absolute/private/reports \
  --view-in /absolute/private/original-view.json \
  --view-out /absolute/private/NEW-view-with-video.json
```

入出力フラグは対で指定し、出力には未作成のファイル名を使う。元の予想・結果・SHA・時刻は変更しない。レース、締切、6艇すべての登録番号が一致する報告だけを補足する。合成報告は実予想へ接続しない。出力JSONを既存画面の原本読込から開くと、レース詳細→直前情報→「映像の実験計測」で各区間、欠測理由、時刻、SHA、標本フレーム番号を確認できる。通常の公式プレーヤーからの常時取得は未接続である。

## 6艇の数字による候補追跡

既存のハッシュ固定OpenCV YOLOX/NanoDetとローカルTesseractを再利用する。大きいモデルバイナリは新たにGitへ追加せず、既存の正しい資産を明示的に指定する。実行にTesseractとEnglish traineddataも必要。ライセンス・出典は `docs/licenses/opencv-zoo/` に保全する。

```bash
/absolute/private/video-tools/bin/python scripts/boat_video_analyze.py \
  --video /absolute/private/exhibition.mp4 \
  --job /absolute/private/video-job.json \
  --private-root /absolute/private/reports \
  --hull-model /absolute/private/object_detection_nanodet_2022nov.onnx \
  --detector-kind nanodet
```

`--tesseract` / `--tessdata` でローカル実行ファイル・データ場所を指定できる。指定場所は報告へ保存せず、モデル/エンジンのSHAと版を保存する。映像ごとに新しい識別器を作る。白・黒も含めて色に依存せず艇の領域を検出し、同じ艇の位置・数字の観測が3回以上一致した場合に `NUMBER_TEMPORAL_CANDIDATE` とする。数字の曖昧さ、競合、重なり、画面切替・欠落では候補の継続を中断する。読めない艇を6艇になるまで強制割当しない。元の色候補経路は引き続き選べ、旧版の出力は保持する。

候補がまだ付番されていない領域もカメラ補正から除外する。小さい検出領域は背景から除外するが、計測対象として無理に使わない。デコードしたフレームのSHAを数字の証拠へ関連付け、別の匿名追跡IDになった時点で計測区間を分ける。これらは実艇の独立識別や実運用精度の認定ではない。

## ローカル自動取込とモデル接続

認可済みのファイルとJOB_V1を `race_ai.boat_video_intake.enqueue(private_root, media_path, job)` へ渡すと、原本を変更せず私有領域へ改変検知付きで取り込む。

```bash
/absolute/private/video-tools/bin/python scripts/boat_video_intake.py \
  --private-root /absolute/private/reports --follow --connect-models \
  --hull-model /absolute/private/object_detection_nanodet_2022nov.onnx \
  --detector-kind nanodet
```

これは既存クラウド内のローカル入力処理で、公式サイトの取得権限を作るものではない。デフォルトは1巡のみ、明示した `--follow` が新着のキューを繰り返し処理する。総レース数・累積ファイル数・累積バイト数による取得停止は設けない。ファイルごとの復号・資源検査は維持し、空き容量不足は実際の保存エラーとして記録する。

T−15〜T−10を優先し、1件ごとに新着と現在の締切を見直す。解析済みで証拠待ちだった報告も、締切前なら各処理の選択前に再確認し、新しい証拠が届けば過去映像の解析より先にモデルへ渡す。同じ入力では再推論しない。保存と状態更新は単一writer・上書きなしの原子操作で行う。中断した試行を成功や過去の時刻へ戻さず、再起動時にも二重解析しない。既存の予想workerとアプリを停止する必要はない。

`--connect-models` は、保存した報告から `prepare_video_context` を実際に呼び出す。別途確認された艇番・同じ比較区間・カメラ/校正/時計・誤差の証拠がなければ、24セルを理由付き欠測にする。合成データや締切後の処理を実予想へ採用しない。私有の `video-connections/` に接続結果を別保存し、同じ入力のポーリング・再起動では重複を作らない。

予想を実際に生成するには、信頼するPython呼出元が `identity_evidence_provider`、`model_inputs_provider`、`receipt_verifier` を渡す。モデル入力は固定した `snapshot` / `baseline_suite` / `training_context` / `video_context` / `video_receipt`。JSONに「検証済み」と記すだけでは認証しない。CLIは勝手にこの証拠や検証関数を作らず、未接続理由を記録する。文脈が欠測、未学習、受領証不足なら買い目を捏造しない。

接続対象は既存の `boat-observed-pairwise-factor-v1` と `boat-observed-pairwise-start-v1` の実験版 `0.3.0-VIDEO-EXPERIMENTAL`。新しいモデル系統ではない。既存の公式8特徴、既存予想原本、旧版の式・出力は変更しない。4つの映像特徴を別の版付き入力として同じ対比較/6・PL式と学習処理へ渡す。ターン半径の大小を手作業で強さへ変換しない。映像係数は初期0で、実際に支持される学習データから符号も学習する。誤差区間が重なる艇同士には優劣の差分を与えない。学習不足では0のまま保持し、本番へ自動昇格しない。

現在レースの展示映像は展示後P1の入力に限る。過去の入力・結果は1レース1結果で分け、同時刻の結果を学習/検証へ分割しない。入力文脈の作成、独立保存、予想用の観測時点、実際の推論開始・完了を別々に記録する。保存済み文脈の時刻を予想時刻へ書換えず、受領証の秒精度も考慮し、実推論が締切を越えた場合は予想出力へ採用しない。

ローカルの接続結果は、独立保存された正式な前向き予想の証明ではない。新しい研究版の原本は既存の私有ビューでも基準5モデルと分けて閲覧し、未検証の入力・学習・保存依存を表示する。閲覧のための再予想・再学習は行わない。

## 実映像の参照付き検証

`race_ai.boat_video_benchmark` は追跡・計測・予想とは別の、読取専用の照合である。`benchmark_identity(tracking, reference)` は数字付き候補領域、`benchmark_hulls(tracking, reference)` は数字を読む前の生の艇候補領域だけを評価する。後者を艇番の識別精度と呼ばない。

参照は `RACE_AI_BOAT_VIDEO_REFERENCE_V1` とし、元映像SHA、寸法、表示フレーム番号、相対PTS、復号したBGR24画素バイトのSHA、領域、可読な艇番または不明、網羅/部分注釈、分割条件を記録する。PNG/JPEGファイルのSHAは画素SHAと別である。読めない番号を色や期待艇数から補わない。画素/時刻が異なる参照は拒否する。抽出されなかったフレームと、観測したが候補が空だったフレームを分け、前者を自動的な不的中や成功へ変換しない。

位置の一対一対応を番号より先に決め、誤番号、取りこぼし、誤検出、ID切替、分母を分離する。推論エラーを持つフレームも、可視の注釈があれば欠測として分母に残す。分母0の率はnull。全6艇を可読に注釈できたフレームがないとき、全6艇成功率は算出しない。AI目視、申告された人の注釈、合成データを別記し、JSONに人と書くだけで認証しない。同一映像内のフレーム分割は未知映像の検証ではない。

正確なレース番号・締切・登録番号が不明な過去資料は、`extract_tracks` の出力を直接照合する。`analyze_video` を使うためにJOB_V1のレース情報を作らない。保存済み原本や本番モデルを変更しない。

```python
from race_ai.boat_video_benchmark import benchmark_identity, benchmark_hulls

# tracking: 実行済みTRACKS_V1、reference: モデル出力を見る前に作った参照。
identity_report = benchmark_identity(tracking, reference)
hull_report = benchmark_hulls(tracking, reference)
```

2026-11-06の実試験では、Commonsの実レース動画と福岡公式の過去展示解説を私有保存して復号した。元の数字読取は現物を取りこぼし、修正後に処理が完走しても数字候補と有効位置は0だった。少数のAI目視参照への番号一致は両方式0/10で、不合格である。独立した校正/時計/強さの正解はなく、未来予想の改善も認定しない。数字抽出の試作には高信頼度の誤読もあり、その方式を採用していない。実測値・資料の権利・分母と範囲は `RACE_AI_LATEST_STATUS.md` に記録する。

OCRの3秒期限や出力処理に既知の失敗が起きた場合は、当該艇を欠測にし、`LOCAL_OCR_TIMEOUT` / `LOCAL_OCR_PROCESS_FAILED` / `LOCAL_OCR_OUTPUT_REJECTED` を残す。失敗した艇の古いIDを隣艇へ転用しない。起動失敗や未想定の不正入力まで成功扱いするものではない。0.90の採用基準と期限は維持する。

## 計測の意味と未完成条件

ターンは標本の方向変化・経路長・相当半径、出足と行き足は標本間速度の傾向、伸びは画像上の平均移動速度と横ずれを記録する。単位はpxと動画PTSの秒。実速度m/s、瞬間加速度、選手能力、艇間の優劣ではない。別カメラ・別遠近条件のpx/sを順位付けに用いない。

背景のホモグラフィ推定と品質条件でカメラの動きを扱う。遮蔽、複数候補、色の重なり、画面切替、時刻欠落、位置誤差以下の動きは欠測にする。色候補の `COLOR_CANDIDATE` と数字/時系列の `NUMBER_TEMPORAL_CANDIDATE` は、どちらも艇の独立識別を認定しない。波や背景が実場で十分な補正基準になることも未検証。

全報告は `UNVALIDATED` / `model_eligible=false`。ハッシュは改変検知用で、映像の権利・艇番・取得時刻の真正性を認証しない。画面の任意JSON取込も形式と関連付けの照合であり、報告本文のSHA再計算や独立認証ではない。

2026-11-06 JSTの初期確認では、通常の公式導線で住之江・多摩川・徳山の対象展示の再生要求が403/「この動画の視聴は許可されていません。」となり、公式にリンクされた津YouTube経路はトンネル接続に失敗した。その後の福岡の対象レース展示も403で停止した。別認証・URL推測・別プロキシ等で拒否を回避していない。別に取得できた福岡の過去解説動画やCommons資料とは分ける。この結果を全場の映像が利用不可という意味には拡張しない。**現行レースの公式映像の常時取得、実映像6艇の十分な識別精度、実用上の強さの評価、映像を使った締切前実予想、精度改善の実証は未完成。** 実映像での試験を行ったことと、試験に合格したことも区別する。

## 検証

既存CIのViewer audit contract内で、別venvの固定NumPy/OpenCVを使い、合成動画を本当に復号するテストを実行する。システムPythonだけの試験でOpenCV試験がskipされた場合は、映像復号の成功とは扱わない。

```bash
python -m unittest tests.test_boat_video_measurements tests.test_boat_video_evaluation tests.test_boat_video_cli -v
/absolute/private/video-tools/bin/python -m unittest tests.test_boat_video_tracking -v
/absolute/private/video-tools/bin/python -m unittest tests.test_boat_video_identity tests.test_boat_video_identity_tracking tests.test_boat_video_intake tests.test_boat_video_connection -v
/absolute/private/video-tools/bin/python -m unittest tests.test_boat_video_ocr_reliability -v
python -m unittest tests.test_boat_video_benchmark -v
python -m unittest tests.test_boat_video_model_context tests.test_boat_video_learning tests.test_video_existing_hooks tests.test_video_shadow_projection -v
node --test tests/boat_video_ui.test.mjs
```

合成画像の正常な追跡は実レースの受入成功や予想精度の改善を意味しない。


## 2026-11-06 続行：分割検出と生CTC候補を明示的に選ぶ

既存の既定経路はTesseractと0.90の読取ゲートを維持する。`--tiled-hulls` は同じ固定済み検出モデルを832pxの重なりを持つ区画と全画面へ適用し、元画面へ戻した領域を統合する任意指定。重みや艇番の閾値は変更しない。候補増加は誤検出・処理時間も増やし得るため、正解参照との別検証が必要。

`--crnn-model` は固定済みOpenCV Zoo FP32 CRNNを使う実験経路を選ぶ。学習済みの全37クラス（英数字36文字+blank）を保ち、実グレースケール画素から自動抽出した数字領域を読む。全艇を埋める割当、色からの艇番置換、正解ラベルの入力は行わない。艇全体を読む診断結果は位置のある数字証拠として採用しない。

```bash
/absolute/private/video-tools/bin/python scripts/boat_video_analyze.py \
  --video /absolute/private/exhibition.mp4 \
  --job /absolute/private/video-job.json \
  --private-root /absolute/private/reports \
  --hull-model /absolute/private/object_detection_yolox_2022nov.onnx \
  --detector-kind yolox \
  --tiled-hulls \
  --crnn-model /absolute/private/text_recognition_CRNN_EN_2021sep.onnx
```

CRNNの正しいFP32資産SHAは`a84b1f6e11a65c2d733cb0cc1f014aae3f99051e3f11447dc282faa678eee544`。自動ダウンロードはせず、明示したローカル資産だけを検証する。`--crnn-model` は`--tesseract`/`--tessdata`と併用しない。既存の`boat_video_intake.py`にも同じ任意指定を追加したが、稼働済みプロセスを自動再起動・hot reloadしたとは扱わない。

生CTCの`sequence_likelihood`は未校正の文字列尤度で、的中確率・識別精度・Tesseract信頼度ではない。出力は`minimum_sequence_likelihood`と明示的な未校正scopeを使う。同じ位置の数字が実際に3フレーム以上観測され、既存の時間・位置・競合チェックを通った場合も候補に留める。曖昧な読取や重なった候補などで中断した艇の過去番号を、近くの未読艇へ移さない。復帰には新しい3観測が必要。共通3秒はsoft予算で、途中のnative推論が超過する場合は後続を省略して不完全と記録する。硬い3秒上限や処理成功を偽らない。

レース番号・登録番号・締切が不明の過去資料を調べるときは、`make_crnn_identity_extractor(...)`または既存`extract_tracks(...)`で追跡候補だけを保存する。架空のJOB_V1や当日の予想を作成しない。取得権利不明の公開映像は私有評価に限定し、学習・再配布の許諾を認定しない。

## 独立した座標・時計の参照から物理座標を計算する

`race_ai.boat_video_calibration`の`calibrate_tracks(tracking, manifest)`は、`RACE_AI_BOAT_VIDEO_CALIBRATION_V1`を検証する。マニフェストは元映像・追跡・必要時の報告SHA、世界座標系IDと測量出典SHA、フレームごとの生BGR画素SHA/PTS/カメラ区間、別々のfit用アンカーと検算用ランドマーク、メートル単位の対応点、独立時計の参照時刻を持つ。正確な構造は`tests/test_boat_video_calibration.py`の明記された架空fixtureで確認できる。架空fixtureを実測校正へ流用しない。

入力ランドマークは`RAW_DECODED_FRAME_PX`。追跡点の`REFERENCE_IMAGE_PX`はカメラ補正後の座標なので、保存されたカメラ変換の累積とリセットを再生してから対応させる。画面上の注釈を補正後座標と同じと仮定しない。fitと同じ点を名前だけ変えて検算に使うこと、欠けたカメラ変換・画素参照・時刻を単位変換で埋めることは拒否する。

`measure_calibrated_tracks(tracking, manifest, *, phase_windows, start_gate, max_gap_seconds)`は艇ごとに異なる時間の展示区間をメートル系で処理する。進入/スタート用の基準は`WATER_PLANE_METRES`と明記する。時計の参照差と映像PTSの差が一致することを検査し、fit残差と独立検算を区別する。既知の位置誤差が変位や旋回角を隠す場合は欠測とする。

これらは条件付きの投影で、艇の矩形中心が実際の水面接地点であること、参照点・時計の真実性、現場での強さや速度を認証しない。`physical_velocity=NOT_ESTABLISHED`、`UNVALIDATED`、`production_eligible=false`を保持する。

## 物理座標の実験文脈を既存2モデルへ渡す

`prepare_physical_video_context(report, identity_evidence, calibration_manifest, *, race_id, cutoff_at, roster, as_of, phase_windows=None, start_gate=None, max_gap_seconds=.3)`が、保存済み元報告から校正を再計算し、`RACE_AI_BOAT_VIDEO_PHYSICAL_MODEL_CONTEXT_V2`を作る。校正マニフェストには対象の`report_sha256`を必須として結び付ける。4特徴IDと既存2モデルのfamily IDは維持する。

同じ世界座標系・時計・校正の参照があれば、艇ごとの実観測区間を使える。独立した艇番読取がない艇は欠測のまま。数値比較には同じ特徴の比較可能な艇が2艇以上必要で、各区間に使った全フレーム・PTS・区間IDを参照と一致させる。途中の高誤差点を抜いて誤差を小さくできない。旋回半径の誤差は位置・経路長・方位角の誤差から伝播し、旋回が消える可能性があるときは半径を確定しない。

既存V1のピクセル文脈は従来の同一フレーム比較を維持する。V2を使う新しい実験学習は入力座標系・単位の宣言と、レース内の無次元対比を保存する。古いpx限定の凍結学習へm単位の文脈を黙って入れない。方向係数、強弱の正解、校正済み確率や改善実績を初期値で作らない。

`connect_report`は、凍結V2文脈の`measurement_parameters`と`model_inputs.calibration_manifest`から再構築し、一致を確認してから既存モデルを呼ぶ。元の予想・報告を置換しない。独立受領証の認証は別の必須条件であり、JSONの自己申告だけでは学習・予想へ採用しない。

## 既存cycleで動画文脈の保存原本を独立に読み戻す

`VideoContextArchiveReader`は既存認証済みGitHub読取経路で、許可された既存workflowのartifact/runメタデータ、ZIP実バイトとdigest、`video-contexts.json`中の文脈SHAを照合する。リポジトリ・branch・workflow・producer run/head、レース・締切・登録番号・文脈の利用可能時刻を結び付ける。ZIP取得前にメタデータのサイズを検査し、取得後も実バイト・メンバー・JSONの整合を検証する。

既存`github_existing_cycle.py`の`restore`/`forecast`/`audit`には任意の`--video-context-artifact ID`を追加した。認証器は予想・fit・保存済み再演・復元まで伝える。より新しい文脈を過去snapshotへ混入せず、各時点で利用可能だった文脈を選ぶ。無指定の既定動作と通常予想の出力は保つ。任意動画の失敗は理由を記録して隔離し、必須の予想原本や動画以外の整合性エラーは引き続き拒否する。

当日動画の常時取得、実測校正参照、実文脈の独立保存、動画特徴を用いた実学習・締切前ペア予想・未来公式結果での改善実証は、実データの記録が必要な受入条件である。読取器や架空データのE2E試験だけで完成としない。最新の実測件数・完成区分は`RACE_AI_LATEST_STATUS.md`と対応する証拠に記録する。

## カメラ補正失敗時の識別継続

実験CRNN経路は、背景不足とカメラfit失敗だけについて、数字の継続と計測用カメラ区間を別に扱える。補正がない各フレームで新しい一致した数字を読むことを必須とし、未読・曖昧・重複・遮蔽・時間欠落・画面切替で継続を中断する。追跡結果の`scene`は実際の計測用区間を保持し、別の`identity_continuity_scene`を位置校正へ流用しない。数字が続いたことを理由にカメラ変換や有効な物理位置を作らない。既存Tesseractの既定経路は変更しない。

## 暗号化した文脈の発行と自動取込の接続

`race_ai.boat_video_publication`は、保護された元映像・元報告・艇番証拠・凍結文脈を再照合してから、既存の`RACE_AI_STATE_KEY`を使うAES-256-GCMで文脈を暗号化する。鍵は引数やGit、ログへ出さない。暗号文も実際のrepository/workflow/branch/HEADへ結び付け、上限を超えるdispatch本文は送らない。既存Viewer workflowに追加したdispatch専用jobだけが`video-context.enc`を保存する。publicリポジトリのartifactへ平文特徴や映像は保存しない。

既存`boat_video_intake.main(...)`の信頼するPython呼出元は、既存の証拠/モデル入力/受領証検証callbacksと任意の`context_publisher`を渡せる。`make_context_publisher(...)`の送信関数・platform readiness・非秘密の設定revisionを明示しない場合はHOLDで、勝手にGitHubへ送らない。CLIやキューJSONから検証関数や発行権限を設定できない。

発行試行は私有`video-publications/`へ呼出前にSTARTEDを追記する。受付済み・通信結果不明・例外・中断したSTARTEDは文脈単位で重複送信を抑止する。送信前と確認できる特定HOLDだけが、設定revision変更後かつ締切前に再確認できる。dispatch受付は独立受領証の確認ではなく、`receipt_verified=false`のまま。archive readerが実APIのrun/HEAD/保存時刻・ZIP実digest・暗号文を検証して初めて、既存cycleへ渡す。

この経路のコードと架空データ試験が成功しても、プラットフォーム上のdispatch可否、実鍵の接続、実映像文脈の保存、現行workerでの利用を認定しない。稼働中プロセスは自動再起動していない。公式映像の視聴拒否は迂回せず、実入力のない状態で本番採用を有効化しない。

並行作業のPDCA用公開受信鍵は別のSQLite転送プロトコルで、この動画の対称鍵や文脈として直接利用できない。公開鍵を`key`へ代入しない。Actions内のroot鍵を取り出す方法を前提にせず、各経路の認証・秘密保持・受領確認を個別に満たす。
