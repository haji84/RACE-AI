# 継続映像保存と自動艇番識別の実装設計

対象は既存Draft PR71。ユーザーの「完成まで進める」「連続映像の取得と自動艇番識別をできるようにして完成させる」という実行指示に従う。以下の技術選択は実装担当の判断であり、新たな本番切替の承認とはしない。

## 方針

既存Python/OpenCVと既存YOLOX/NanoDet・37文字CRNNを使う。既存intakeはローカル動画専用なので、取得を独立componentにし、完成したローカル区間だけを既存intakeへ渡す。取得数・巡回数・全体稼働時間の停止上限は追加しない。既存の120秒/256MiB等は1つの解析用ファイルの条件として扱い、保存全体の停止条件にしない。

公式プレーヤーの403を別ホスト・認証情報・接続元・UAで回避する案、新しい有料映像/AI API案は採用しない。許可された公開HLSの正規取得・私有保存と、実画像で判明した位置抽出の誤りを修正する。許可された入力がない状態をコードで許諾済みに変えない。

## 取得契約

- Source schemaは `RACE_AI_AUTHORIZED_HLS_SOURCE_V1`。`source_id`、`playlist_url`、`allowed_origins`、`source_role`、`source_evidence_sha256` を必須とする。roleは `LICENSED_DEVELOPMENT` / `OWNER_AUTHORIZED` / `SYNTHETIC_TEST`。証拠SHAやowner宣言自体は、権利・race同一性の独立認証ではない。
- `Collector(root, manifest, fetch=None, clock=None)` の `tick()` が正規取得、原本segment/mapのatomic保存、GET試行/応答/未確定試行の単調記録、待機と次回取得時刻の要約を返す。既定の総GET・segment数・稼働時間上限は持たない。
- `fetch(url, headers)` は `HTTPResult(status, headers, body)` を返す。bodyはread可能なbinary stream。既定HTTP実装は継承proxy/CA/TLSを維持し、自動redirectをせずCollectorが許可originを検査する。資格情報やsigned queryをログへ出さない。
- メタデータはprivate SQLite等で扱い、長期取得で全segment一覧を毎回メモリへ展開しない。私有directory0700、file0600、symlink/別source混入/原本改変を拒否する。
- HLS masterは最初に固定したvariantを使い、拒否後の別variant切替はしない。media sequence・discontinuity・map・byte-range・上流PDTを保持。暗号化/DRMと未対応のLL-HLS等は取得前に明示拒否する。
- 401/403後は同じsourceを再要求せず権限待ちを保存する。429/5xx/未掲載は既存 `plan_http_wait` / `wait_active` を保存して待機中GET0。sourceの拒否を解除するescape optionは作らない。
- 保存済みsegment/mapをrestartで二重GETしない。同じsequenceの内容差、欠損・encoder再開等は別区間/要確認として残し、連続していたと捏造しない。
- `export_window(window_id)` は同じ連続区間のmap/segmentをhash検査し、local-only FFmpegでMP4とcapture receiptを作る。URLや未検証の元playlistをFFmpegへ渡さない。欠損、不連続、初期化変更を跨がない。
- 未終了のliveは複数の解析可能区間へ区切って保存し続ける。ENDLIST/ユーザー停止/正当なsource待機を区別する。PDTは上流の主張、PTSは媒体timeline、captured_atは実bytes取得・remux完了後の実clockとして分離する。

## 既存intakeへの接続

完成したMP4とcapture receiptを読むbridgeを用意する。race_id/cutoff_at/rosterは真正性を確認済みのcaller入力を使い、未確認ならcapture-only。sourceは既存の `OWNER_LOCAL/OWNER_DECLARED` 等の契約を維持し、HTTP取得を `OFFICIAL_BROWSER_CAPTURE` と偽称しない。capture SHAで予想の根拠が認証されたことにはしない。既存予想・採点・係数の書換え、本番モデルの切替、既存運転の停止/再起動は行わない。

## 識別の最小修正

新しい実写真で、正しいMSER/Otsu候補が固定の「画像の下側」条件だけで落とされることを確認した。この位置仮定を除き、同じ印字を上下に平行移動しても候補が消えない試験を先に作る。37文字の語彙、raw likelihoodの未校正性、UNKNOWN、多桁機材タグ、同じフレームを複数の独立観測にしない条件を維持する。

正規化やconfidence/temporal gateの変更はこの原因修正へ混ぜない。私有の固定一変数検証では自動の直接可読参照一致0→2だったが、6艇追跡や本番精度とはしない。修正後に封印済み写真・実動画で再計算する。

## 合格条件

1. 20を超えるsegment、sliding live、restart、rate/auth待機、欠損とdiscontinuity、原本改変、暗号化、origin逸脱をテストする。
2. 実際の許諾済み連続動画を使い、HTTP取得→local export→decodeのframe/PTS/原本SHAを保存する。localhostのtransport fixtureを公式LIVE成功へ読み替えない。
3. 数字の位置抽出はRED→GREEN、実写真と実動画の出力を封印参照へ照合し、誤りと未識別を残す。静止画反復で6艇の連続識別を作らない。
4. 既存の全体テストと新component/CLI試験を実行し、exact source/HEADを記録する。
5. 現在の日本競艇LIVEと6艇継続識別の実測がない限り、全体完成とは報告しない。外部許可・入力不足は実装済み部分と分けて最新statusへ記録する。
