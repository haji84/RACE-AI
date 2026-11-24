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

```bash
python -m scripts.keirin_video_corpus --db "$VIDEO_WORK/corpus.sqlite" queue \
  --stage continuous --out "$VIDEO_WORK/to-capture.jsonl"
python -m scripts.keirin_video_sources --queue "$VIDEO_WORK/to-capture.jsonl" \
  --continuous --out "$VIDEO_WORK/digests" --limit 2
python -m scripts.keirin_video_media inventory --root "$VIDEO_WORK/digests" \
  --db "$VIDEO_WORK/media.sqlite" --out "$VIDEO_WORK/verified.jsonl"
python -m scripts.keirin_video_corpus --db "$VIDEO_WORK/corpus.sqlite" ingest \
  --media "$VIDEO_WORK/verified.jsonl"
```

収集は日別一覧からたどる通常の公開プレーヤーを使う。1回の処理件数を分けても、全件台帳から続行できる。画面の録画時間とプレーヤーの再生時間を確認し、取得・再生できなかった理由を記録する。通常アクセスで拒否や利用制限を受けた回は停止する。取得済み映像はハッシュを照合して再利用する。静止画を使う場合は `--continuous` を外し、別の収集ディレクトリを使う。`inventory` にすべての保存先を `--root` で渡す。手元の利用可能な全編は `--manifest` で取り込める。動画の復号に成功した範囲と、映像内で実際に選手が見えた範囲は個別に記録する。

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
