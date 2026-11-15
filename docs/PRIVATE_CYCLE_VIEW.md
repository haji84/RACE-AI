# 保存済みBOAT巡回JSONを本人の画面で読む

既存Draft PR71の読取経路。原本の取得・復元・表示だけを行い、予想再生成、学習の再実行、結果の再採点、providerへのGET、workflow起動、公開は行わない。Linux/POSIXのディレクトリ参照とリンク拒否を使用する。

## 取得するもの

既存GitHub Actionsの予想artifactには、P0の`forecasts.json`、巡回ごとの展示後P1の`national.json`がある。結果artifactには`official-result-observations.json`がある。`continuity.json`の参照だけを元原本の取得成功とは数えない。最終回が空の`national.json`の場合もあり、最後のartifact一つから全日分を復元できるとは限らない。

通常のGitHub API認証と通信許可がある場合、選択済みartifactを新規の非Git私有ディレクトリへ保存できる。

```bash
RACE_AI_PRIVATE_DIR=$(mktemp -d /var/tmp/race-ai-owner.XXXXXX)
python -m race_ai.private_cycle_capture \
  --day 2026-11-04 \
  --artifact-id 13280270767 \
  --artifact-id 13311386530 \
  --artifact-id 13311232967 \
  --out "$RACE_AI_PRIVATE_DIR/selected-originals" \
  --export-view
```

上記IDは保存済みチェックポイントの具体例であり、最新巡回・全日網羅を宣言するものではない。既存の`gh`認証をそのまま使う。通信/TLS設定の迂回、秘密値の出力、失敗時の無限再試行はしない。ネットワークが拒否した場合は`PRIVATE_CYCLE_CAPTURE_BLOCKED`で終了し、取得成功と表示しない。実行中環境の`api.github.com`許可が未適用の間は、この段階を完了できない。

JSON/ZIPは元バイトのまま保存し、API metadata、ZIP、主要JSONメンバーのSHAを`manifest.json`へ記録する。新規ディレクトリは0700、ファイルは0600、既存ファイルへは上書きしない。親ディレクトリ差し替え・シンボリックリンク・Git配下を拒否する。上の一時領域は恒久保存先ではなく、GitHubの7日artifactも期限なし保管ではない。

## ローカル原本を復元・投影するAPI

既に認可されたZIP/metadataがある場合は、ネットワークを使わず読める。

```python
state = restore_manifest(manifest, private_root)
view = project_state(state, dataset_status="REAL_REPORTED")
```

関数はそれぞれ`race_ai.private_cycle_restore`、`race_ai.private_cycle_projection`にある。manifestは`RACE_AI_PRIVATE_ARTIFACT_MANIFEST_V1`。`repo`、`repository_id`、`day_jst`、`artifacts`が必要。各artifactには`kind`（p0/p1/result）、`artifact_id`、`run_id`、`metadata_file`、`zip_file`、`metadata_sha256`、`zip_sha256`を指定する。任意の`member_sha256`と`created_at`も一致を検査する。相対ファイルは私有root直下から読み、リンク・ハードリンク・経路逸脱・読取中変化を拒否する。

復元は選択したartifactのみ。`complete=false`、`coverage_scope=EXPLICIT_ARTIFACTS_ONLY`を保持する。旧`RACE_AI_RECOVERED_FIRST_RECEIPTS_V1`も投影できるが、状態のSHA一致を独立認証へ格上げしない。

## 画面に出るものと未確認のもの

`--export-view`が作る`cycle-view.json`を、起動済みの画面で「保存原本を読み込む」から選ぶ。原本と別の派生ファイルであり、元のTop8・全順位・P0/P1・モデル/SHA・保存時刻の申告を保持する。保存済み学習版は基準版と分け、元モデルとの結び付きが確認できないものは理由付きで未解決に残す。

未保存のモデル版・生成時刻・入力SHA・出典SHAは未取得のまま。本文のハッシュから時刻や個別入力SHAを捏造しない。結果の`captured_at`は取得観測時刻であり、公式確定時刻や公式改訂番号ではない。観測原文を履歴として保持し、公式改訂配列は作らない。

`REAL_REPORTED`も研究閲覧として読み込み、独立receipt/公式結果検証を未完了に固定する。正式Hit@8・回収率・校正済み確率には加算しない。学習版の表示成功を精度改善と扱わない。予想・購入候補はブラウザのlocalStorageへ保存せず、外部へ送信しない。

初回の合成結合試験は[evidence/2026-11-04/private-cycle-view](evidence/2026-11-04/private-cycle-view)を参照。環境設定適用後の[実読戻し証拠](evidence/2026-11-04/real-original-readback/EVIDENCE.md)ではBOAT144レース・基準570予想・学習版70予想・505結果観測を接続した。最終回の空P1だけで全日分を代用せず、過去の原本を結合した。空のP0取得試行も0予想の原本として保全する。

原本同士の締切が異なる場合、単一の締切へ補正せず、選択した予想の元時刻と保存された一覧を表示する。構造・SHAが正しい観測でもレース/締切/出走者/着順が対応しない場合は理由付きで照合不可とし、原文を履歴に残す。最新観測が照合不可なら古い観測へ黙って戻さない。全文の表示を4000文字で打ち切らず、学習版の学習物SHA・artifact ID・ZIP digest・基準原本SHAを保持する。

画面のファイル選択は最大16ファイル、1ファイル5MiB、合計20MiB。大きい派生viewはレース単位を変えずに複数ファイルへ分割し、同時選択する。実予想・結果・スクリーンショットはGitやpublic assetsへ置かない。4競技/全モデルの全レース継続運転と実機Safari受入は引き続き未達。
