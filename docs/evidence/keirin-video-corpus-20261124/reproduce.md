# 競輪の映像台帳を作成・更新する

日別一覧に掲載されたレースを起点にする。過去の着順が欠けたレースも登録する。出走者は当日の車番と登録番号で結ぶ。以下はリポジトリのルートで Python 3.12、beautifulsoup4、lxml、numpy、Playwright、Chromium、ffmpeg、ffprobe が使える環境で実行する。連続再生の画面収録には Playwright の ffmpeg も使う。Pillow は確認用の画像一覧の作成に使う。作業先には映像・選手別記録を置くため、非公開のディレクトリを指定する。

## 日別の母集団と出走者

```bash
umask 077
VIDEO_WORK="${XDG_STATE_HOME:-$HOME/.local/state}/race-ai/keirin-video-study"
mkdir -p "$VIDEO_WORK/calendars" "$VIDEO_WORK/rosters"
python -m scripts.keirin_video_census \
  --first 2023-11-24 --last 2026-11-23 \
  --calendar "$VIDEO_WORK/calendars" --fetch-missing-calendars \
  --public-cache "$VIDEO_WORK/rosters" --public-races 10 \
  --output "$VIDEO_WORK/census-001.jsonl" --summary "$VIDEO_WORK/census-001.json"
python -m scripts.keirin_video_corpus --db "$VIDEO_WORK/corpus.sqlite" ingest \
  --census "$VIDEO_WORK/census-001.jsonl"
```

10 はこの実行で新たに照合する出走表の数。日別一覧の取得範囲は全期間。保管した日別一覧と2媒体の資料を引き継ぎ、出力名を新しくして再開する。`--public-races -1` は残りの全件を対象とする。過去研究の登録番号・出走表・確定着順を保全してある環境では同じコマンドに原本のパスと SHA-256 を渡して統合できる。オプションの一覧は `python -m scripts.keirin_video_census --help` で確認できる。

## 映像の収集と検証

手元にある、研究利用が認められた映像は `--manifest` から検証・取り込みできる。

```bash
python -m scripts.keirin_video_media inventory --manifest "$VIDEO_WORK/owner-films.jsonl" \
  --db "$VIDEO_WORK/media.sqlite" --out "$VIDEO_WORK/verified.jsonl"
python -m scripts.keirin_video_corpus --db "$VIDEO_WORK/corpus.sqlite" ingest \
  --media "$VIDEO_WORK/verified.jsonl"
```

Kドリームスはサイト掲載コンテンツの無断複製に関する条件を設けている。映像を通常視聴できることと、機械取得・録画・研究利用の許諾は個別に確認する。提供元の許諾原本を確認し、対象のレースと用途を確認者が記録した場合に限って、次のコマンドで対象範囲を収集する。[サイトの利用条件](https://keirin.kdreams.jp/info/sitepolicy/)

```bash
python -m scripts.keirin_video_corpus --db "$VIDEO_WORK/corpus.sqlite" queue \
  --stage continuous --out "$VIDEO_WORK/to-capture.jsonl"
python -m scripts.keirin_video_sources --queue "$VIDEO_WORK/to-capture.jsonl" \
  --source-approval "$VIDEO_WORK/reviewed-source-approval.json" \
  --continuous --out "$VIDEO_WORK/digests" --limit 2
python -m scripts.keirin_video_media inventory --root "$VIDEO_WORK/digests" \
  --db "$VIDEO_WORK/media.sqlite" --out "$VIDEO_WORK/verified.jsonl"
```

`--source-approval` は確認者が許諾の範囲をまとめた非公開の JSON ファイル。`source_host` は `keirin.kdreams.jp`、`reviewer` は確認者、`rights_ref` は実際に確認した許諾原本のローカルパス、`rights_sha256` はその SHA-256 とする。発行元の許諾書式は変更せず、照合に使う原本を参照する。対象は `race_ids` または両端を含む `first_race_date`・`last_race_date` で指定する。両方を指定した場合は両方に該当するレースに適用する。利用期限が定められている場合は `valid_until` にタイムゾーン付きの期限を記録する。

`allowed_uses` には許諾を確認した用途を記載する。この収集で必要な用途は `automated_fetch`（自動取得）、`private_retention`（非公開での保存）、`history_analysis`（選手別の研究・学習）、および `video_recording`（録画）または `frame_capture`（静止画）となる。静止画の場合は `--continuous` を外し、別の保存先を指定する。新規に取得した資料には許諾確認記録と原本のハッシュを添える。取得・再生できなかった理由も台帳に残す。`inventory` に複数の保存先や許諾済み既存ファイルをまとめて渡し、復号・検証した資料を前述の `ingest` で取り込む。

## 選手別の動きを確認する

```bash
python -m scripts.keirin_video_review --db "$VIDEO_WORK/corpus.sqlite" \
  --media-db "$VIDEO_WORK/media.sqlite" --next sheet --output "$VIDEO_WORK/next.jpg"
```

候補画像で調べる時刻を決め、元の映像で車番、前の選手、進路を確かめる。`record` にはレース、対象車、追走相手の車番、開始・終了時刻、区間、判断とその根拠を入力する。`--asset` で選択した動画に対応する時刻を使う。仕掛けは対象区間での最初の動き出しを扱う。打鐘の前後、最終ホーム、バック、4角、直線を区別する。追走は相手の後輪を追えたか、離れたか、再び付いたか、自分がその相手を抜いたかを記録する。別線が外から通過した場合も追走相手を確認する。

視界外・カメラの切り替わり・車番の重なりは `unknown` と理由を残す。「仕掛けなし」「追走相手なし」には該当区間の連続映像が必要になる。静止画に写った短い区間、連続して確認した区間、最終周の全体、レース全体は区別して学ぶ。全編という資料種別は提供元による申告で、各選手の動きは個別に確認する。全周・全編を判読できた場合は、同じ映像で当該車の最終ホームまたはスタート、および決勝線の通過時刻を別に記録する。確認画面の `bounds` が境界ファイルを作る。全員の登録番号、仕掛けと追走の両方が確認できた場合に、該当する区間の全選手確認を数える。

## 再開・学習・検証

```bash
python -m scripts.keirin_video_corpus --db "$VIDEO_WORK/corpus.sqlite" ingest \
  --bounds "$VIDEO_WORK/crossings.jsonl" --review "$VIDEO_WORK/reviewed.jsonl"
python -m scripts.keirin_video_corpus --db "$VIDEO_WORK/corpus.sqlite" study \
  --profiles "$VIDEO_WORK/rider-profiles.jsonl" --report "$VIDEO_WORK/scores.json"
python -m scripts.keirin_video_corpus --db "$VIDEO_WORK/corpus.sqlite" status
```

`ingest` は複数の名簿・映像・観察ファイルを取り込み、1回分をまとめて確定する。同じ入力を再度渡しても出走数や観察数は増えない。過去の判読不能記録は履歴に保管する。対象車・追走相手・映像時刻・画像または動画のハッシュと対応した観察を学習に渡す。学習は日付順で、ある日を採点する際に使う記録はその前日まで。`study --before YYYY-MM-DD` で指定日より前だけを利用できる。全登録選手を保存し、未観測の選手には観測数を付け足さない。出力する確率は選手の動きの推定用で、三連単の的中率は別の締切前予想と結果で採点する。

境界を記録する必要のない短い観察だけを取り込む回は、コマンドの `--bounds` を省略できる。研究の映像・原票・個人別ファイルは非公開の作業先で扱う。既存ドラフトにはコード、テスト、集計を保存する。[今回の実測](analysis.md)
