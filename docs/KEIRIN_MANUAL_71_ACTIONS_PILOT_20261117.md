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
