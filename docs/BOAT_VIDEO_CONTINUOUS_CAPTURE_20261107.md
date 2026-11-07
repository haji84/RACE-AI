# 許可済み連続映像の私有保存と艇番抽出

既存Draft PR71のPython処理。`scripts/boat_video_capture.py` がHLSを区間原本として保存し、閉じた解析区間をローカルMP4へ出力する。既存の自動予想・動画intakeの停止や本番モデル切替は行わない。

## 入力と実行

利用許可・正規の取得URLを確認したsourceだけを指定する。source宣言や証拠SHAだけで許諾・レース同一性を認証したことにはならない。403となった映像を別ホスト、認証情報、接続元等で取り直す機能はない。

Git管理外に所有者専用directory（0700）を作り、source JSONを0600で保存する。以下は書式例であり取得先ではない。

```json
{
  "schema": "RACE_AI_AUTHORIZED_HLS_SOURCE_V1",
  "source_id": "owner-authorized-feed",
  "playlist_url": "https://media.example.invalid/authorized/live.m3u8",
  "allowed_origins": ["https://media.example.invalid"],
  "source_role": "OWNER_AUTHORIZED",
  "source_evidence_sha256": "<確認した権限・取得経路の証拠ファイルのSHA256>"
}
```

```bash
python scripts/boat_video_capture.py \
  --private-root /private/capture \
  --manifest /private/source.json \
  --follow
```

`--follow`は利用者が停止するまで巡回する。取得数、総GET数、区間数、総稼働時間で打ち切らない。既定の30秒の解析窓、1ファイルの解析条件、DB読取ページは全体の取得上限ではない。SIGINT/SIGTERM後は処理中のローカル区間を確定し、未処理区間は再開時に読む。`--follow`なしは1回の取得と1ページ分のローカル出力を行う。

playlistは1応答2MiB、媒体は1応答1GiBの資源保護を持つ。解析用の1窓は120秒/256MiB以内とし、解析条件外の保存区間は明示して飛ばし、後続区間の取得・出力を続ける。総取得数・全保存量の停止上限を設定するものではない。

source roleは `OWNER_AUTHORIZED` / `LICENSED_DEVELOPMENT` / `SYNTHETIC_TEST`。外部通信はHTTPSの正規proxy/CA/TLSを使う。数値loopbackへのHTTPは `SYNTHETIC_TEST` のローカル検証だけに許可する。

## 保存・待機・再開

原本segment/map、私有SQLite台帳、出力MP4、capture receiptを保存する。GET前の意図と確認できた応答を分け、途中終了で不明になった試行も残す。再起動後に保存済みsegmentを二重取得しない。元bytesや同一sequenceの宣言が変われば要確認とする。

401/403は永続的な権限待ちとし、自動再要求・別variantへの切替は行わない。429、Retry-After、一時障害、未掲載は既存の待機方針に従う。待機中GETは0。暗号鍵/DRM、未対応LL-HLS、許可originからの逸脱は取得前に拒否する。欠損、不連続、map変更を跨いで1本の連続映像として結合しない。

MP4出力はhash確認済みのローカルbytesだけをFFmpegへ渡す。上流PDT、実取得・出力完了のUTC時計、媒体PTSはそれぞれ別の情報として記録する。媒体の日付やテンプレート指定で取得時刻を前倒ししない。

## 既存解析への接続

既定はcapture-only。真正なrace_id・締切・6艇の登録番号を確認できた場合だけ、既存JOB_V1のテンプレートを `--job-template`、既存intake用の私有directoryを `--intake-root` に指定する。sourceは `OWNER_LOCAL/OWNER_DECLARED` を明記し、media SHA・captured_at・source_metadata_sha256は検証済みexportから補う。これらをテンプレートに指定する場合はexportと完全一致が必要。

`LICENSED_DEVELOPMENT` の過去映像はrace intakeへ昇格させない。HTTP保存を `OFFICIAL_BROWSER_CAPTURE` と表示しない。接続後も既存のUNVALIDATED・モデル適用条件を維持する。保存済みexportとreceipt・原本の照合に失敗したらenqueueしない。export後の中断は再開時に同じ区間を検証して再投入し、既存のjob SHAで重複を避ける。

## 艇番と完成判定

艇番候補抽出の「艇画像の下側40%にしか数字がない」という固定条件を除去する。既存CRNNの語彙・未校正likelihood・UNKNOWN・複数時刻での一致条件は維持する。色だけで艇番を確定せず、同一フレームの複数加工を独立した連続観測に数えない。

ローカルHLSでの保存成功と、現在の公式LIVE取得、実映像での6艇継続識別は別に判定する。実際の観測結果と未達条件は `docs/RACE_AI_LATEST_STATUS.md` および対応するevidenceへ記録する。静止画の反復や過去映像で現在のレースの識別成功・予想改善を主張しない。
