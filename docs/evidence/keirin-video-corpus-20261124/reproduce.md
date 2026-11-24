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

## 公開プレーヤーで追加した32レースを再現する

2023年11月24日いわき平の7レース、2024年6月11日岸和田の12レース、2025年9月16日函館の8レース、2026年11月17日小松島の5レースが今回の追加分。各行の `public_page` を開き、ダイジェストの時計を `back_seconds` と `corner_seconds` に合わせ、前後の場面で進行方向・車番・車輪の前後を照合する。各秒は映像の再生位置で、レースの公式計時とは異なる。32レースのうち、先頭が両地点で判読できた29件は維持24・交代5。ほか3件は4角の先頭を確定できなかった。結果票のBは別欄に残している。[新32レースの時刻・車番・公開ページ](public-new32.json)・[過去分を含む観測点](public-race-observations.json)

### 3年分の台帳への取り込みと再開

リポジトリのルートから、上記で作った `VIDEO_WORK` のコーパスを使う。次の例は新32件をCLI用のJSONLに変換し、過去3年の全行を含む進捗表を書き出す。月別・年別の開催件数と映像を実際に確認した件数は別々に集計する。

```bash
EVIDENCE_DIR=docs/evidence/keirin-video-corpus-20261124
python - "$EVIDENCE_DIR/public-new32.json" "$VIDEO_WORK/watched-32.jsonl" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as src:
    races = json.load(src)["races"]
assert len({r["race_id"] for r in races}) == len(races) == 32
with open(sys.argv[2], "w", encoding="utf-8") as out:
    for race in races:
        row = {k: race[k] for k in (
            "race_id", "back_car", "back_second_car", "back_seconds",
            "corner_car", "corner_second_car", "corner_seconds", "observation",
        )}
        row["source_url"] = race["public_page"]
        out.write(json.dumps(row, ensure_ascii=False) + "\n")
PY

python -m scripts.keirin_public_replay_progress --help
python -m scripts.keirin_public_replay_progress \
  --corpus "$VIDEO_WORK/corpus.sqlite" \
  --state "$VIDEO_WORK/public-player-progress.sqlite" \
  --observations "$VIDEO_WORK/watched-32.jsonl" \
  --output "$VIDEO_WORK/public-player-progress.jsonl"
```

引き続き同じ `--state` を使い、`--observations` に追加の観察ファイルを渡すと、同一の観察原票を重複登録せずに再開できる。公開資料から作成済みの索引を反映する場合は `--archive-index` に `keirin_video_archive_index` のJSONLまたはJSONL.GZを渡す。旧コーパスの映像ハッシュと観測点を対応させたメディア目録がある場合は `--checkpoints` にその目録を渡す。再出力時にも同じ索引・目録を指定する。CLIはコーパスを読み取り専用で開く。通常プレーヤーを試して失敗した記録には `status=failed` と理由を残す。再生だけ確認した場合は `playback_only`、再生できても車番が読めなかった場合は `unreadable` とし、学習用の車番は空欄にする。

### 先頭維持の検証を再計算する

公開観測表には125レースがあり、3年台帳の最終日である2026年11月23日までが123件、翌日の比較用観測が2件。登録番号、最終Bの先頭、4角の先頭がそろった95件を使う。期間を固定した検証では11月20日までの78件を学習、11月21日以降の17件を採点に使った。78件の内訳は従来45件、新たに回収した旧映像4件、今回の29件。旧4件は特定選手の勝ち・負けを選んだ標本で、今回の開催抽出とは選び方が違う。後日17件は前回の13件、当時は予測を固定してから映像を確認した別の3件、旧映像1件。今回はすべて過去の再採点になる。[固定した比較の集計](public-aggregate.json)

別の検証では、95件を39の日本開催日ごとにまとめ、早い日から処理した。同じ日の全レースの確率を先に計算し、その日のすべてを採点してから履歴を更新する。最終Bで先頭だった選手を条件に、その選手が4角でも先頭なら1、交代なら0とする。集団の維持確率は `(維持回数 + 1) / (観測数 + 2)`。選手別は `(その選手の維持回数 + 4 × 集団の維持確率) / (その選手の観測数 + 4)`。下記は公開表だけで両方の比較を再現する例。

```bash
python - "$EVIDENCE_DIR/public-race-observations.json" <<'PY'
import json
import sys
from collections import defaultdict
from itertools import groupby
from statistics import mean

with open(sys.argv[1], encoding="utf-8") as source:
    observed = json.load(source)["races"]
rows = sorted((r for r in observed if r["readable_B_to_corner"]),
              key=lambda r: r["race_id"])

def held(row):
    return int(row["B_car"] == row["corner_car"])

def predict(earlier, rider):
    population = (1 + sum(map(held, earlier))) / (2 + len(earlier))
    individual = [r for r in earlier if r["B_leader_registration"] == rider]
    probability = (4 * population + sum(map(held, individual))) / (4 + len(individual))
    return population, probability

train = [r for r in rows if r["included_in_earlier_rider_fit"]]
test = [r for r in rows if r["race_id"][:8] > "20261120"]
previous = [r for r in train if "current_viewing" not in r["source_groups"]
            and not r["historical_purposive_win_loss_sample"]]
assert (len(previous), len(train), len(test)) == (45, 78, 17)
for history in (previous, train):
    errors = [(predict(history, r["B_leader_registration"])[1] - held(r)) ** 2
              for r in test]
    print(len(history), len(test), round(mean(errors), 6))

past, errors = [], defaultdict(list)
days = 0
for _, batch in groupby(rows, key=lambda r: r["race_id"][:8]):
    today = list(batch)
    predictions = [predict(past, r["B_leader_registration"]) for r in today]
    for r, probabilities in zip(today, predictions):
        for version, p in enumerate(probabilities):
            errors[version].append((p - held(r)) ** 2)
    past.extend(today)
    days += 1
assert (days, len(past)) == (39, 95)
print(days, len(past), round(mean(errors[0]), 6), round(mean(errors[1]), 6))
PY
```

固定した17件の選手別ブライアスコアは45件学習で0.190405、78件学習で0.197273。39日逐次の95件では集団0.177873、選手別0.177254。値が小さいほど予測誤差が小さい。逐次検証では同じ選手の過去観測を利用できたのは28件で、67件は集団確率を使った。二つの検証は対象・学習日・比較基準が異なる。いずれも実際のB先頭が既知の条件付き予測で、締切前の三連単は別に評価する。

### 締切前の三連単との対応

11月21〜23日の同じ211レースで、通常の予想入力から全てのBの前2車の組に確率を割り当て、4角での各組の位置変化と、その先の1・2着を平均する。各レースの実B・実4角・最終着順を候補作成に渡さず、1・4・8点の順位を固定した。その後に確定結果を開き、照合できた207件を同じ点数で比較する。過去映像のうち、当時の締切前入力と両地点の前2車がそろう学習例は16件から18件に増えた。この更新の前後はいずれも26・69・93件的中。比較用に、各仮想B先頭が4角に残る確率を今回の選手別確率で置き換えると25・69・92件だった。維持する場合と交代する場合の各グループ内では既存の相対確率を保ち、既存の25%混合を使った。[旧方式と比較条件](../keirin-video-transitions-20261124/analysis.md)・[今回の同一レース比較](public-aggregate.json)

公開観測表からは映像ラベルと日付別の条件付き採点を再計算できる。三連単の順位をゼロから再構築するには、当時の締切前出走表・特徴量、既存方式の凍結モデルおよび入力原本が必要になる。集計にある `frozen_forecast_hashes` で研究時の保存物と照合できる。これらのレースは過去にも採点され、一部の映像は後日のB先頭選手や過去の勝敗を手がかりに選んでいる。将来の的中率は、その後の対象レースを締切前に固定し、結果判明後に採点して確かめる。

### 公開CSVから未確認レースを特定する

[3年分の開催日・場・レース番号](three-year-replay-calendar.csv) は、1行が日本開催日 `date_jst` と競輪場の2桁コード `venue_code` の組。番号の欄では空欄が0件、`1-3 5` は1・2・3・5Rを表す。レースIDは、開催日を8桁にし、場コード、2桁のレース番号の順にハイフンで結ぶ。例として2023年11月24日のいわき平8Rは `20231124-13-08`。

`all_races` は全掲載番号、`cancelled_races` は中止番号、`visually_checked_races` は実際に映像を確認した番号、`positions_or_rider_events_races` はそのうち選手の位置または動きを具体的に確認した番号。`all_races` から中止と映像確認済みを引くと、未確認の全番号が得られる。その中で過去資料に該当レースの映像ボタンが載っていた番号が `pending_with_replay_button_races`。ボタンの掲載は当時の記録で、現在再生できるかは各レースの確認時に記録する。

CSVを展開し、1,096日・8,289開催日場について、レースIDごとに全区分を照合した。掲載82,774件から中止7件を除いた対象は82,767件。映像を確認した143件すべてで、少なくとも1地点の選手の位置または動きが分かった。未確認82,624件のうち、12,791件は該当レースの映像ボタンが掲載された記録があり、69,833件は開催詳細までを確認している。

集計は次の順で更新した。

1. 公開プレーヤーで59レースを試し、32レースの観察を追加した。この時点の映像確認は123件、位置や動きまで具体的に読めたのは111件だった。CSVは Git のコミット `979e7d89722883d39b57bf51df0e15bfb885914a` に残っている。
2. 保存済みの映像資料24レースを読み直し、12レースで初めて選手の位置を確定した。これで123件すべてに具体的な観察が付いた。対象IDと当時のCSVのSHA-256は `current_after_local_reread`、CSVはコミット `442049c9a` で確認できる。
3. 初回に局面を読めなかった27レースを再試行し、初めて試す13レースを加えた。40レースのうち20件で今回初めて位置を確定できた。内訳は再試行17件、初試行3件。初回から通算すると、異なる72レースを試し、52件に観察が付いた。冒頭だけ再生できたレースは未確認に残した。

最後の40レースでは、古い索引にボタン記録のなかった未確認6件についても、該当レースの場内プレーヤーへのリンクを確認した。現在のCSVにはこの6件も含めた。差分のID・開催別の成否・未確認6件のリンク・最新CSVのSHA-256は `current_after_public_player_recovery` で確認できる。[初回の集計と2回の更新記録](all-watch-coverage.json)
