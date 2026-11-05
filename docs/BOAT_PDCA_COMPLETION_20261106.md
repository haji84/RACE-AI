# 選手情報統合とPDCAの完成確認（2026-11-06 JST）

ユーザー指定1〜4の実装・実データ確認。**実データのGitHub暗号化復元は所有者鍵の確認待ち。全実運用完了とはしない。** 精度改善・本番への自動切替・全キャリア/全登録選手の網羅・期限なし保存も未実証。

|項目|確認できた範囲|残る実証|
|---|---|---|
|1. 選手データ|既存の公式期別DBと90日履歴を登録番号で結合。1,653名、当日583名全員のプロフィールを保持|当日4名は両資料に実績がなく欠測表示。直接被まくりや交換周期は未確認|
|2. 集計・締切|不明な機会を保持、比較版へ同じ改訂を適用、元/改訂締切・実保存完了・JST日付を検査|稼働workerへ未適用。原本は不変|
|3. 履歴入力|艇愛と公式履歴が同じ`observed_result_history._features`を使用。比較版は直近着順/STを一度だけ置換|期別・映像・モーターをこの比較へ加点していない|
|4. 状態の引継ぎ|私的SQLite、AES-256-GCM、別プロセス復元、原本/訂正結果保持、重複防止を実装|GitHub別runnerは合成CIで確認。実データの暗号化引継ぎは鍵待ち|

## データと期間

- 公式B/Kは2026-08-07〜11-04の90日・180原本。通常13,090R、例外/未確認1,046R。
- 予定84,816機会を出走確認84,104・欠場142・未確認570に区別。未確認を実出走・通常不的中に変えず、直近の窓からも消さない。
- 同じDBに解析V1/V2/V3の270解釈を追記。源流180原本は不変。同じ捕捉時刻で源流bytesが異なる場合は競合として停止する。
- 既存`boat_racer_database`/`boat_racer_term`で公式2026-2期1,643名・9,858コース行を扱う。対象期間は2025-11-01〜2026-04-30。記録上の年齢・級別を現在値へ変換しない。
- 90日履歴1,609名と期別の和集合1,649名に、情報不足の当日4名を追加して1,653プロフィール。当日583名のプロフィール未作成は0名。情報不足4名の氏名・成績・戦法を推測しない。
- 期別の氏名/カナ/支部/登録期、日付付きBの年齢/級別/体重/全国・当地成績、実進入別・直近10/30機会・ST/F/L・進入変化・決まり手を出典と母数付きで保持する。意図や直接被まくりを因果ラベルへ変換しない。
- モーターは会場×実番号×観測期間で集計。番号の再使用を同一機体の通算実績へ結合せず、交換周期未確認の入力を予想へ自動投入しない。

全原本・DB・プロフィール・買い目はGit外の0700/0600領域。公開は件数・定義・SHAのみ。BOATERS一括収集や艇愛APIパイロットの再取得はない。統合時に公式期別ファイルを1回だけ私的に取得し、既存実装の固定SHAで照合した。

## 採点と比較原本

11/5の認証済みcontinuity ZIPから698モデル別原本を再照合。行SHA `26b7a6be6bb2f3ebc88985d3d08745f8a8688e6ceb4f4e716bc0da70c1a83a33` は処理前後一致。締切改訂3R、通常確定133R、採点641モデル別行（HIT204/MISS437）、例外/結果待ち57行。698/641はレース数ではない。

結果だけでは締切を改訂しない。同じ出走者の締切前P1を根拠に、基準/学習版へ同じ改訂を適用。元締切で遅刻した予想を後の改訂で救済しない。同じ瞬間を示すUTC/JSTは同じ日本開催日として扱う。

V1の624研究予想は、未確認履歴の欠落と物理保存レシート不足により隔離し、原本は保全した。修正版V2は156R×既存2モデル×2版=624研究予想を同一情報時点・8点で別保存。情報基準07:19:44 JST、最後の実保存完了07:20:07 JST、最初の締切08:35 JST。直近着順468/936艇、ST897/936艇へ入力し、残りは欠測を維持。

各原本の実bytes・履歴窓・出典・モデル再計算・保存開始/完了を検査。締切後の保存は遅刻原本として残し、比較へ採用しない。**ローカル時刻と自己ハッシュは独立した外部時刻証明ではない。** 正式な外部証明フラグはfalse。[V2 SHA一覧](../audit/freezes/2026-11-06/official-history-research-pairs-v2-sha-only.json)。旧予想の編集や事後補充はない。

## 私的状態とGitHub受入

`boat_pdca_state.py`は履歴DB・選手DB・源流・比較原本/レシート・結果改訂・採点を保持。同じ結果の再処理を二重計上せず、訂正版を別行で保持し、古い観測へ戻らない。実データjournalは156ペア/674ファイル版、実結果/実採点は現在0件。

暗号化は既存艇愛キャッシュと同じ`cryptography`のAES-256-GCM。既存Node codecの8MiB上限は変更せず、大きい履歴には別の有界圧縮envelopeを使用する。repository/mode/generation/前世代cipher SHAを認証し、復元では受入側が別途固定したcipher SHAと期待scopeを要求。鍵違い・改変・scope違い・サイズ超過・既存DB上書き・状態欠落を停止条件とし、空DBへresetしない。

`production`は所有者設定`RACE_AI_STATE_KEY`なしに暗号文を作らず、公開fixture鍵で実データを扱わない。11/3のmain検査は`production_key_ready=false`、今回のローカルbindingも無し。GitHubの現在のsecret有無を直接読めたとはしない。

既存`forecast-audit-ui.yml`に架空選手のみのproducer/consumerを追加。別runnerで期別/履歴/元bytesを復元し、結果→再実行→訂正版→次予想→次世代暗号化を検査する。2jobに実データsecretを渡さず、artifactは架空暗号文と件数証拠だけ。3日artifactを永久保全と呼ばない。既存の実全選手intake/readbackも鍵無しならHOLDを維持する。

```sh
python scripts/boat_racer_profiles.py --history-db /private/history.sqlite --racer-db /private/racers.sqlite --racer-db-sha256 EXPECTED_SHA --registrations /private/requested.json --output /private/profiles
python scripts/boat_pdca_state.py init --state /private/pdca.sqlite --mode production
python scripts/boat_pdca_state.py ingest --state /private/pdca.sqlite --history-db /private/history.sqlite --captures /private/captures --racer-db /private/racers.sqlite --pairs-dir /private/pairs-v2
python scripts/boat_pdca_state.py checkpoint --state /private/pdca.sqlite --generation 1 --output /private/sealed
python scripts/boat_pdca_state.py restore --state /private/restored.sqlite --cipher /private/sealed/state.enc --expected-sha256 EXPECTED_CIPHER_SHA --expected-scope /private/expected-scope.json
python scripts/boat_pdca_state.py score --state /private/restored.sqlite --pair-sha256 PAIR_SHA --observations /private/official-results.json
```

`expected-scope.json`は`proof.json`の`scope`と同じ5項目を持つ受入側固定値。鍵を引数/ログ/公開ファイルへ書かない。実データのGitHub暗号化引継ぎが終わるまで、1〜4の全実運用完了とは報告しない。

## 検証と運用境界

独立レビューでUTC朝締切の重要指摘1件を再現しRED→GREEN修正。前回3指摘にも回帰テストを追加し、関連46件成功、Node202件成功。最終Python全体とGitHub exact HEAD結果は追記で記録する。任意映像依存がないPython44件のskipは区別する。

稼働worker・アプリ・自動予想トリガー・係数・main保護を変更せず、既存Draft PR71へコードと件数/SHAのみ反映する。main統合・実投票・Cloudflare/Vercel・新たな有料サービスは実施しない。
