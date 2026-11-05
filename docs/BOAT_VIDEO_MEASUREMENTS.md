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

## 計測の意味と未完成条件

ターンは標本の方向変化・経路長・相当半径、出足と行き足は標本間速度の傾向、伸びは画像上の平均移動速度と横ずれを記録する。単位はpxと動画PTSの秒。実速度m/s、瞬間加速度、選手能力、艇間の優劣ではない。別カメラ・別遠近条件のpx/sを順位付けに用いない。

背景のホモグラフィ推定と品質条件でカメラの動きを扱う。遮蔽、複数候補、色の重なり、画面切替、時刻欠落、位置誤差以下の動きは欠測にする。色候補の `COLOR_CANDIDATE` と数字/時系列の `NUMBER_TEMPORAL_CANDIDATE` は、どちらも艇の独立識別を認定しない。波や背景が実場で十分な補正基準になることも未検証。

全報告は `UNVALIDATED` / `model_eligible=false`。ハッシュは改変検知用で、映像の権利・艇番・取得時刻の真正性を認証しない。画面の任意JSON取込も形式と関連付けの照合であり、報告本文のSHA再計算や独立認証ではない。

2026-11-06 JSTの確認では、通常の公式導線で住之江・多摩川・徳山の対象展示の再生要求が403/「この動画の視聴は許可されていません。」となり、公式にリンクされた津YouTube経路はトンネル接続に失敗した。別認証・URL推測・別プロキシ等で拒否を回避していない。この結果を全場の映像が利用不可という意味には拡張しない。実映像の供給が成立した後、艇番・走行区間・カメラ動作を独立した正解と照合し、未使用の実映像で誤検出と欠測を測る必要がある。**公式映像の常時取得、実映像6艇の識別精度、実用上の強さの評価、映像を使った締切前実予想、精度改善の実証は未完成。実展示映像の検証は0件。** ソフトウェアの取込・候補追跡・モデル接続試験と混同しない。

## 検証

既存CIのViewer audit contract内で、別venvの固定NumPy/OpenCVを使い、合成動画を本当に復号するテストを実行する。システムPythonだけの試験でOpenCV試験がskipされた場合は、映像復号の成功とは扱わない。

```bash
python -m unittest tests.test_boat_video_measurements tests.test_boat_video_evaluation tests.test_boat_video_cli -v
/absolute/private/video-tools/bin/python -m unittest tests.test_boat_video_tracking -v
/absolute/private/video-tools/bin/python -m unittest tests.test_boat_video_identity tests.test_boat_video_identity_tracking tests.test_boat_video_intake tests.test_boat_video_connection -v
python -m unittest tests.test_boat_video_model_context tests.test_boat_video_learning tests.test_video_existing_hooks tests.test_video_shadow_projection -v
node --test tests/boat_video_ui.test.mjs
```

合成画像の正常な追跡は実レースの受入成功や予想精度の改善を意味しない。
