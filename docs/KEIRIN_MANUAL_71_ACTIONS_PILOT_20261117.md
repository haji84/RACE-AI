# 競輪71R：既存GitHub Actionsへの実レース1件・結果照合接続（2026-11-17）

## 判定
**実装・合成CIは前進。本番無人完走の実証はNO-GO / HOLD。**
11月17日の松山7Rはユーザーがこの会話で締切前に公開した予想原本に基づき、外部公開結果との参考照合が可能だったが、GitHub Actions自身が認可済みV3結果を取込み、AES暗号保存、別runner復元、閲覧用HTML反映まで実際に完走した事実はない。手動照合をActions実績に流用しない。

## 今日の現物・参考照合
- manual V3予想元ファイル SHA-256: `4cd7e88d9ab7880702180bcbab248ebda2a8078a721fab5a08fe47323de21d68`（ChatGPT会話内の添付、Public repoには平文を載せない）
- 比較元V2 SHA-256: `3bdb6930812cd00035f5591cc4a349aa171d49a1f1a709c44a2f2b990c233c59`
- 会場別HTML SHA-256: `2c0ec7ed2f8b77b81e026ae162ba4b185abcc4d1983e624d08eef7e61c1cf11c`
- manual V3記録生成: 2026-11-17 09:06:03 JST。松山7R発走予定10:55、公開締切予定10:50。締切の独立認証は未了。
- 松山7Rの元予想8点の第7候補 `7-2-1` と第三者公開結果 `7-2-1` / 3連単100円払戻390円が一致（参考Hit@8=1、Hit@1=0）。主催者発表原本や取得API権利の独立証明は未取得。
- 第三者公開結果参照: https://keirin.netkeiba.com/race/result/?race_id=202611177507&rf=courselist および https://keirin.kdreams.jp/matsuyama/racedetail/7520261117010007/?pageType=result

## 既存実装との接続
- 残す：`race_ai/keirin_manual_result_sync.py`（71R原本SHA検証、V2/V3版・候補順位、同着/返還/未観測、Hit@1/全候補/仮想払戻、非公式な参考比較、プライベートHTML作成）。
- 追加：`race_ai/keirin_manual_71_actions_bridge.py`。**既存のlicensed V3 source stage** の `licensed_result_rows` のみ読む。最初はレースID `202611177507` (= `75-07`) だけ。シナリオ予測や無許可の別GETはしない。
- `scripts/keirin_cloud_pr71_state.py::cycle` が、既存のsource/grants確認後かつ所有者の非公開予想資料が明示的にある場合に研究用参考結果を照合。予想原本や欠測した会場・レース・結果は、推測で補完しない。
- `keirin_owner_manual_71_audits` テーブルに日付/レース/結果改訂SHA、予想原本SHA、監査JSON SHA、閲覧HTML SHAとprivate blobを保存。INSERT ONLY、同一結果改訂の二重保存なし、異なる内容に置換できない。**従来のPR71モデル予想テーブルは変更しない**。
- 追加したtableは**既存PR71のAES-256-GCM暗号化SQLite Git履歴**に含ませる設計。別runnerの既存 `verify` がprivate blob SHAとレースID/本数/非認証フラグを独立読戻しチェックする。公開Actions logに予想車番・払戻やprivate HTMLを載せない。
- 既存 `.github/workflows/keirin-pr71-owner-autonomous.yml` のsynthetic-ciに本研究サイドカーのsource-freeテストを追加。新しいworkflow/secret/課金/公開サーバを作らず、mainの保護を維持。
- Public site/Pagesに予想平文HTMLを自動投稿しない。保管したHTMLは**private AES blob**のみ。一般公開HTMLへの反映は別の所有者承認・表示権限設計が必要。

## 初期化の明示的HOLD
1. 元ChatGPT会話の71R V2/V3/HTMLの平文は公開GitHubに入れない。現行Actionsには `RACE_AI_KEIRIN_MANUAL71_PRIVATE_DIR` にSHAが一致する `forecast_v3.json`, `baseline_v2.json`, `categories.html`, `template.html` を取り込む承認済み非公開経路がまだない。環境変数を設定するだけでは入力実体は現れない。
2. 本番の認可済みV3結果の取得・`licensed_result_rows`生成を松山7Rで確認できていない。公開webをブラウズできても「認可済みAPIと主催者公式結果を受信した」とは扱わない。403/429拒否を迂回しない。
3. mainの既存PR71アーカイブは、完全な真正事前入力で生まれた本物のAES production genesisが存在しない場合、`HOLD_NO_COMPLETE_PRE_CUTOFF_INPUT` で止まる。**手動71予想だけを理由に、既存のPR71正式4モデルの空の暗号履歴を創作することは禁止**。このため現在の追加コードは、PR71履歴が復旧/生成された上でのみ既存暗号コミットへ一緒に保存できる。
4. 現行PR #291はDraftでmainには未統合。CI SUCCESSは本番Actions稼働証明でなく、主催者結果認証・HTML実画面・71R全件収集の証明ではない。
5. 公式締切、同着、結果訂正、返還、発走取り消し等は元結果revisionから保存する。現状の参考比較の時刻ゲートは**予定発走前（公式締切前の独立証明ではない）**ので正式的中として認定しない。

## 合格ゲート
| Gate | 受入条件 | 現状 |
|---|---|---|
| G0 | 固定原本SHA・原子INSERT・SHA照合の合成テスト | コード実装/CI確認済み |
| G1 | 事前保存した実予想1件と実結果の独立照合 | チャットで参考一致、Actions実証なし |
| G2 | GitHub-hosted既存ジョブが認可済V3結果1件を自動取得 | HOLD |
| G3 | 71R私有予想をrunner内で正規復号・SHA確認 | HOLD |
| G4 | 同じIDの暗号SQL/AES世代を既存Git stateへ追記 | HOLD |
| G5 | 別Actions runnerが元原本・レース改訂・監査HTMLをSHA独立読戻し | HOLD |
| G6 | スマホから閲覧できる本人向けHTMLに結果が更新される | HOLD |
| G7 | 全71Rと全会場に漏れなく拡大し、正規/参考、Hit@1、Hit@全点、仮想ROIを確認 | NOT RUN |

## 次にやる工程（優先）
- **入力の確保**：公開しない71R予想原本の非公開・AES連携と、既存V3 sourceで実在する松山7Rの結果を取得できることを独立に証明。既存のprivate stateとSecrets以外の追加先・費用は勝手に導入しない。
- 最初の1実レースで`forecast SHA -> V3 source SHA -> result revision SHA -> private audit SHA -> Git AES commit -> fresh runner SHA -> private HTML`を同じレースIDで連続実証。その際のRun IDs/commit SHA/原本時刻・正式締切を報告。
- 現行PR71 genesisが無いなら、**ユーザー承認の範囲で**手動研究用の私有AES intakeを既存履歴に安全に共存させる設計を別途比較。架空モデル保存を捏造しない。
- 最初の1件の本番合格後、71件と毎日の新規レースへ拡大。結果なし・見送り・遅延・返還は「不的中」にしない。各バージョンが実締切前か確認する。公表順位を後から変更しない。

## CI
- Branch: `research/keirin-six-phase-score-20261114`
- 既存PR: https://github.com/haji84/RACE-AI/pull/291
- Synthetic-ci run: https://github.com/haji84/RACE-AI/actions/runs/44013678282 （SUCCESS、実結果アクセスではない）
- 既存業務に影響するcodeはDraft PR内。保護main・古い予想・4競技共通のモデル重み・Secrets・発注・自動投票を変更していない。

## 2026-11-17 午後：オーナー再確定の5工程と実行証拠ゲート

対象：**松山7R（202611177507 / manual 75-07）**。全71レースへ広げる前の受入条件は同一レースの **①実結果取得 → ②元予想との照合 → ③AES暗号保存 → ④別runnerで独立SHA読戻し → ⑤本人が閲覧できるHTML実画面反映**。5工程がすべて実Run ID・証拠SHA・実日時で揃うまでは **HOLD**。

### 今回追加した既存Actions内の検査機能
- `race_ai/keirin_manual71_live_evidence.py`：5段階の個別 PASS/HOLD と原因を記録する source-free ゲート。実結果ソースの真正性は別の信頼された認証関数の結果がなければ PASS にしない。単に第三者Webに結果が見えたこと、サマリーの `official=true`、SHAを入力したことでは認証しない。
- `race_ai/keirin_manual_71_actions_bridge.py`：元V3予想SHA、認可済み結果改訂SHA、監査レコード集合のSHA、閲覧HTMLのSHAを**暗号化SQLite内の同一レース証拠列**として結ぶ。さらに別runner側が復号後の監査行集合とHTML SHAを再計算し、一致しなければ PASS にしない。
- 既存 `.github/workflows/keirin-pr71-owner-autonomous.yml` の **新ジョブを作らず** 既存 producer ジョブの非機密メタデータを既存 independent-cloud-readback ジョブへ渡し、実読戻し後に5工程の PASS/HOLD を GITHUB_STEP_SUMMARY へ出す。原本の車番・購入額・払い戻し金額・HTML本文を公開出力しない。異なる job が実際に起動した事実と暗号世代・監査行集合SHAが一致する必要がある。
- `tests/test_keirin_manual71_live_evidence.py`：合成データで「出所未確認」「異なるジョブでない」「異なる保存世代」「別レース結果」「別改訂」「別runnerで異なる行集合SHA」「ブラウザを開いたと書いただけ」では合格しないことを検査する。**合成fixtureの全条件PASSは実レースの合格証拠ではない。**
- 本番ジョブは main 上でしか秘密鍵/実プロバイダー入力を使わない。PR #291 は Draftのまま。ブランチ上のCI成功は本番稼働を意味しない。

### 現在HOLDの理由
1. 私有V3/比較V2/分類HTML/元HTMLの4原本が Actions に**正当な非公開経路で入力された証拠なし**。手元ファイルSHAは既存本文記載のとおり。公開リポジトリへ平文をコミットしない。
2. 認可された実V3結果提供で松山7Rの公式結果・同着/返還/改訂を自動取得した Actions Run ID がない。公開ページとのチャット照合は参考のみ。403/429回避や未許可の第二取得元を追加しない。
3. 現行PR71 stateは真の4モデル事前予想を含むAES genesisがある前提。これが無い状態から手動71Rを理由にモデル原本を後付け作成しない。
4. private HTML byte blobは暗号保存されるが、**認証済み本人向けサイトで開いて画面内容を独立確認した証拠がない**。SHAが一致しても表示成功とは呼ばない。
5. `PILOT` ブランチ上の新コード・CIを main へ保護ルール無視で統合しない。新サービス/課金/Secrets/自動投票は追加しない。

### 本番合格レポートに必ず残す項目
同じレースID、当日の出走条件・締切原本、予想各版の作成/保存時刻、予想SHA、結果ソース/改訂SHAと取得Run ID、照合監査SHA、AES世代/commit/cipher SHA、**独立readerのjob IDと復号監査集合SHA**、実HTMLの認証閲覧記録/表示SHA/閲覧job ID、各工程のPASS/HOLD/FAILと理由。PASSは source とブラウザの独立照合含む全5条件一致時のみ。全71Rへの移行は合格後。

**現時点の完了評価：検査器・証拠連鎖の実装は進展。ただし実レース1件の5工程完走は0件確認。**

## 2026-11-17 追加：実予想原本の回収・本人公開鍵による封印

この段階でも **本番5工程は HOLD**。コード合格やブラウザでの結果閲覧だけで「Actionsが本番自動完走」とは言わない。

### 今回実際に確認できた原本
- 過去会話で作成された `keirin_2026-11-17_71r_12point_expanded_v3.json` の**実バイトSHA** が、本Docと既存codeのPIN `4cd7e88d9ab7880702180bcbab248ebda2a8078a721fab5a08fe47323de21d68` に一致した。実データ71件、松山7R `75-07` の第7候補は `7-2-1`。この予想原本の元記録は `2026-11-17T09:06:03+09:00`。元の時刻・公式締切は独立した第三者witnessで照会・証明されていないため、参考照合のまま。
- 実V2 JSON SHA `3bdb6930812cd00035f5591cc4a349aa171d49a1f1a709c44a2f2b990c233c59`、信頼度/波乱表示 HTML SHA `2c0ec7ed2f8b77b81e026ae162ba4b185abcc4d1983e624d08eef7e61c1cf11c`。4つのowner input roleは forecast_v3 / baseline_v2 / categories / template、最後2つは同一の元HTMLの実バイトを使う。
- GitHubに既に置かれた既存PR102 RSA公開鍵の**Git blob SHA** `7717a321a66243118e1864c2136c88c4713ab19c` を元ファイルから確認。公開鍵を変えず、ユーザー手元ファイルを zlib後、同一JSONにまとめ、既存 `RACE_AI_PRIVATE_KEIRIN_ENCRYPTED_JSON_V1` RSA-OAEP/AES-256-GCM形式で封印した。
- 作業用モデル実行環境で作成した暗号化パッケージ `RACE_AI_20261117_owner_71r_sealed.json` の**実バイトSHA-256** は `164bd98caf06deb2308626d0f6343c074db9e85b9517378ac60119af21b3375e`。暗号文SHA-256 `d04e070ef10e92a0276f3a3d1633ebf0fc4d075bf3c9d206c5f1fc9a76315a4f`。**この暗号ファイルは会話内の作業ファイルであり、GitHub main/state/Actionsには投入していない**。owner専用のRSA秘密鍵がこちらにあると主張しない。
- ユーザーには平文をGitHub公開リポジトリに置くよう求めない。上記暗号化ファイルの提出先/復号鍵のジョブ共有権限は既存公開暗号保存同意と用途を照らして確認する必要がある。既存動画用RSA秘密鍵を別のworkflowに黙って渡さない。

### GitHubに追加した再利用可能な取り込み処理
- `race_ai/keirin_manual71_owner_encrypted_intake.py`：既存 PR102 の**固定SHAの RSA-OAEP/AES-256-GCMヘルパー**を使用してowner本人原本4ファイルを封印／復号。元SHAが違う、原本4個不足、base64改変、AESタグ不一致、解凍上限超過、公共GitHub workspace内の平文書込み、既存ファイル上書き等は拒否する。復元後も `RACE_AI_KEIRIN_MANUAL71_PRIVATE_DIR` の実入力がまだ必要。復元専用コードはDraftに存在するがmain producerへの実行配線は未承認。
- `tests/test_keirin_manual71_owner_encrypted_intake.py`：**架空**originalと架空RSA 3072-bit keyで、本物のPR102 `keirin_private_sealed_payload.py` の seal/open を用いた8合成回帰を追加。
- 既存 `.github/workflows/keirin-pr71-owner-autonomous.yml` の合成CIに追加。GitHub Actions [Run 44018540637](https://github.com/haji84/RACE-AI/actions/runs/44018540637) `synthetic-ci` **SUCCESS**、上記8件の暗号関連テストもPass。main-only `config_readiness`／`github-hosted-pr71-cycle`／`independent-cloud-readback` は **SKIPPED**。本番5工程・実レース自動照合の証拠ではない。

### 結果確認の独立性
- Webから2026-11-17松山7Rの `7-2-1`・100円当り390円が [netkeirin](https://keirin.netkeiba.com/race/result/?race_id=202611177507) で確認できた。楽天Kドリームスの同レース画面でも `7-2-1` の着順が掲載された。
- ただし**両方とも主催者公式結果の独立した機械認証や取得権限・GitHub Actionsの実GETを保証しない**。前回のチャット・Web閲覧を自動取得Runの代替にしない。

### 追加で確認した真のブロッカー
- GitHub `state/keirin-encrypted-history` には `state/keirin/v1/latest.json`（mode=synthetic）が存在する一方、**`state/keirin/pr71-production/v1/latest.json`（本番genesis）は現時点で存在を確認できなかった**。実PR71 AES stateを「既に本番で作れた」と報告しない。
- 既存 PR71 state `check_owner_cipher_consent()` は `allowed_material == AES-256-GCM-encrypted production forecast SQLite snapshots only` を要求する。**手動研究71Rを偽のPR71 production genesisとして保存しない**。ownerによる暗号保存用途・復号鍵アクセス範囲の追加承認なしに main workflow の Secrets 権限を拡張しない。
- 残りの本番受入：Actionsが認可された松山7R公式結果をGETしたRun/ジョブ、private原本実復元、研究用AESの認可された正本と独立runner読戻し、owner向けの安全なHTML実表示。この4つのいずれも今回未達。

**現在判定:** 実予想原本4ファイル = byte SHA回収済、暗号封印 = ローカル実原本で実施、暗号ローダ = ソースフリー CI 合格。GitHub Actionsの実結果取得 → 同じ原本との本番照合 → 暗号保存 → 別runner読戻し → HTML実画面の一巡 = **0件、NO-GO**。71Rへの拡大は保留。
