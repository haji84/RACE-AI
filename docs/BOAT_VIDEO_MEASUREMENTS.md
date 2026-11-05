# 展示映像の実験計測

既存PR #71で、ローカルに保存された映像の復号、色による艇番候補の追跡、カメラ補正、4区間の計測、私有保存と閲覧を実装する。**実艇の強さを判定する完成済み機能ではない。** 実映像の供給、白・黒を含む艇の識別、独立した正解との照合は別の受入条件である。

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

入出力フラグは対で指定し、出力には未作成のファイル名を使う。元の予想・結果・SHA・時刻は変更しない。レース、締切、6艇すべての登録番号が一致する報告だけを補足する。合成報告は実予想へ接続しない。出力JSONを既存画面の原本読込から開くと、レース詳細→直前情報→「映像の実験計測」で各区間、欠測理由、時刻、SHA、標本フレーム番号を確認できる。映像を保存するだけで既存workerが自動収集する機能はまだない。

## 計測の意味と未完成条件

ターンは標本の方向変化・経路長・相当半径、出足と行き足は標本間速度の傾向、伸びは画像上の平均移動速度と横ずれを記録する。単位はpxと動画PTSの秒。実速度m/s、瞬間加速度、選手能力、艇間の優劣ではない。別カメラ・別遠近条件のpx/sを順位付けに用いない。

背景のホモグラフィ推定と品質条件でカメラの動きを扱う。遮蔽、複数の同色候補、色の重なり、画面切替、時刻欠落、位置誤差以下の動きは欠測にする。色は艇の独立識別ではなく `COLOR_CANDIDATE`。白・黒の候補は未解決。波や背景が実場で十分な補正基準になることも未検証。

全報告は `UNVALIDATED` / `model_eligible=false`。ハッシュは改変検知用で、映像の権利・艇番・取得時刻の真正性を認証しない。画面の任意JSON取込も形式と関連付けの照合であり、報告本文のSHA再計算や独立認証ではない。

2026-11-06 JSTの確認では、通常の公式BOATCAST導線で対象展示の再生要求が403となり、公式にリンクされた津YouTube経路はトンネル接続に失敗した。前者を別の認証やURL推測で回避していない。この結果を全場の映像が利用不可という意味には拡張しない。実映像の供給が成立した後、艇番・走行区間・カメラ動作を人の正解と照合し、未使用の実映像で誤検出と欠測を測る必要がある。映像入力の自動収集、6艇の自動識別、実用上の強さの評価、締切前予想への採用、精度改善の実証は未完成。

## 検証

既存CIのViewer audit contract内で、別venvの固定NumPy/OpenCVを使い、合成動画を本当に復号するテストを実行する。システムPythonだけの試験でOpenCV試験がskipされた場合は、映像復号の成功とは扱わない。

```bash
python -m unittest tests.test_boat_video_measurements tests.test_boat_video_evaluation tests.test_boat_video_cli -v
/absolute/private/video-tools/bin/python -m unittest tests.test_boat_video_tracking -v
node --test tests/boat_video_ui.test.mjs
```

合成画像の正常な追跡は実レースの受入成功や予想精度の改善を意味しない。
