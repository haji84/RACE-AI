# 初回調査・開発報告 — 2026年10月15日（日本時間）

これは確認時点の記録です。完成報告ではありません。GitHub mainだけを統合済み正本とし、作業ブランチ・合成試験・実通信・実データ・実機の証拠を区別します。

## GitHub

- main commit: `8bb7d69f9c8fb302055bc9e2609903d1e8f73e4b`
- main tree: `293e81c2f88b6a0544dfea474b27a4b541b56414`
- mainはREADMEのみ。取得済みブランチの履歴も検索し、既存AGENTS.md／PROJECT_STATE.md／ROADMAP.mdは確認できませんでした。今回のPR #61で提案します。
- 調査開始時のopen PRは50件。UI保存後は53件、API PR #63追加後は54件。新しいPRによって変化するため固定値として扱いません。
- PR #46〜#59は全件Draft・未統合。各head、base、CI runは [監査JSON](evidence/20261015/GITHUB_AUDIT.json) に保存しています。#59→#58→…→#46→それ以前のブランチという積み重ねで、現在のmainに直接すべてを適用できる状態ではありません。
- #46〜#59の最新headのunit CI・metadata smokeは成功。ただしmetadata smokeは実データ取得成功の証拠ではありません。
- 未統合の主要機能はUI、当日API、24会場台帳、日別保存、履歴保存、Worker、Blob SDK、検証Function、Actions、OIDCです。今回の追加PRもDraftで、統合していません。

## Vercel・認証・Blob

最終再確認でPR #59のheadが610b90cd9667de60d75729e3137e4e1919d4cb1aへ進み、最新E2E38611712685が成功していました。以前のHTTP302／設定API404を現在の通信障害として扱わず、実行ログを確認して以下を補正しました。最新CI38611720204も成功しています。

プロジェクトrace-ai-preview、team `team_YGrZkBR7MyYxkq3K9XkTBhqu`、project `prj_B6XEB1mdFUCmOlip8eUMeBvod5FR` を確認しました。SSO保護は全デプロイで有効です。

| 検証対象 | 確認結果 |
|---|---|
| 修復済み認証Preview | `dpl_2PszR3s1rTDayutTPr8GodGk1TFP` READY、head `cab804e72f314885166cf8e801814026ea38cfa6` |
| 新UI Preview | `dpl_Rt63JqgTcDDmagbHityzT3Qc91i5` READY、head `a6bc73d97d56e0f6626450e1883000763feb0643` |
| UI配信（認証済み取得） | `/` 200、`/ui-model.js` 200 |
| `/api/today` | 503 `FEED_NOT_APPROVED`。実データ配信未完成 |
| `/api/blob-probe` | 修復後GET 405／Allow POST。旧Previewの500／github_oidc import失敗は修復 |
| Actions実通信 | 最新run `38611712685`、job `116016956898`：OIDC発行、POST、private put/get、SHA一致、削除まで成功。61bytes、SHA `23a9b6603b16b27a2bda95b0fbf677c31065c6113da22fd40238575ab733fd72` |
| 保護層 | 旧runの302はvercel.comの認証画面。後続の識別子修正を経て最新通信は成功。SSOは全デプロイで有効。過去runの403の厳密な履歴原因までは未確定 |
| 接続設定 | 以前の狭いTrusted Sources設定APIは404。最新通信は成功したため再設定しない。実際のGitHub subjectは `repo:haji84@173585154/RACE-AI@1416489937:environment:blob-e2e-preview` に固定 |
| Blob | private store `store_K4bSVFm5Bub7EdQf`、Previewの適用先を確認。検証用キーの実put/get/SHA/delete成功。公式当日データの日別キー保存は未実証 |
| Production | `dpl_5P4r39De9UGb1ZR5UXmDBzmop3Wb` READY、commit `d8c9ca88b5d20b58bdc9dcdeefba17718d43ca79`。本作業では変更なし |

Productionの旧RACE_AI_PROBE_SECRETは設定名・適用先を監査しました。値の取得、削除、公開はしていません。Production影響を調べる前に削除しません。新有料リソースも追加していません。

実通信のログと限界は [Blob実通信証拠](evidence/20261015/LIVE_BLOB_PROOF.json) に保存しました。内部生成の検証JSONであり、公式実レースの保存成功とは区別します。未承認・日付違いの実配信E2E拒否は残っています。

## 当日データ

徳山の公式2026-10-14 HTMLを1回取得した監査では、レース一覧12Rを解析しました。これは過去日のレース一覧で、2026-10-15の72艇・出走表・開催節・モーター照合成功ではありません。

今回のWorkerは取得権限を先に確認し、日付と各レース行の公式リンクを照合します。一覧のみならpartialで止まり、選手・締切・モーターの架空値を作りません。別セルやナビリンクを付けて古い表を当日扱いにできる不具合を独立レビューで再現し、回帰試験で修正しました。20件のWorker試験は合成です。

実際の当日取得会場数・完全な出走表レース数・選手登録番号／モーター番号／同一開催節照合・Blob保存・API配信は、成功と報告できる証拠がありません。取得と公開の条件が未確認であるため、承認フラグや定期取得を勝手に有効化していません。

## UI

添付8枚はローカルで存在を確認し、UI担当が個別に閲覧しました。スマートフォン4枚はホーム／一覧／詳細／買い目、PC4枚も同じ4画面です。画像内の選手・写真・確率・AI評価・オッズ・払戻例は実データに移していません。

実装済みはホーム、全レース、詳細、買い目、成績、研究、設定の7画面。白・淡い青・紺・青緑、PCサイドナビ＋補助パネル、スマートフォン下部ナビ、24会場選択を備えます。未取得会場を「開催なし」として表示しません。

Chromiumの1440px、390px、320pxで画面遷移、フィルタ、買い目点数制限、手入力記録、日付変更、更新競合、当日API自動更新を検証しました。日本語フォントを設定した [UIスクリーンショットと制約](https://github.com/haji84/RACE-AI/blob/feat/reference-responsive-ui/docs/evidence/20261015/UI_EVIDENCE.md) を保存しました。合成データの操作試験です。iPhone Safariの実機は未検証です。

参考画像との差分として、許諾済み写真とヘッダー写真、実データによる高密度分析、検証済みAI評価・推奨、永続利用者設定・履歴、公式結果の自動照合、研究グラフは残っています。完全なUI完成・参考画像どおりとは判定しません。

## 開発計画・外部条件

認証修復、データWorker、API、UI、独立レビューを担当分離して進めました。共通モデルを複数担当が同時編集しないようにし、UIのPreviewバンドルへのJS同梱漏れは親が修正しました。auth＋Worker＋UI統合状態でPython193 tests OK（既存OpenCV 1 skip）、ブラウザ操作試験成功を確認しました。APIレビューの未来公開時刻・登録番号／モーター重複・結果フラグ／集計件数の矛盾を修正し、APIも含めた206 tests OK（既存OpenCV 1 skip）を確認しました。API PR #63の最初のCIはSDK未導入の初期テスト段階で失敗しました。依存テストを明示的に第2段階で実行する構成に修正し、最新head eee30c0af9ec0c2532eaab82943d7dc251d2d77f のCI38612150125は両段階とも成功しました。未導入状態での206件中20件skipと、固定依存導入後の1件skipは区別します。

統合Previewは test/p0-integrated-preview、commiteb18b01e2e2149f99d47c3fb4260789a0759d9db、deployment dpl_Eqvs7BaMxSEbciGrPMwvZDHYAxKD（READY）です。認証済み取得で /200、/ui-model.js200、/api/today503 FEED_NOT_APPROVED、/api/blob-probe405を確認しました。最新のPR #59認証変更を統合して208 tests OK（既存OpenCV 1 skip）を確認しました。統合ブランチ自身のホストCI成功は報告しません。詳細は [統合検証記録](evidence/20261015/INTEGRATION_CHECKPOINT.json) に保存しています。

次の順序を維持します。

1. Preview限定の保護接続を設定し、正確なheadのPOST→private Blob put/get→SHA照合→削除を実行。
2. 取得・公開条件を根拠付きで確定し、徳山の自動詳細取得・12R/72艇照合・開催節照合を接続。
3. Worker→Blob→SDK API→UIを実データで検証し、全国24会場と実機Safariへ展開。
4. 発走前予想保存・共通計算・公式結果照合・校正・履歴・運用の完成条件へ進む。

現在の主な外部条件は、事実データの取得／公開条件、写真・映像の個別利用条件、実機検証です。認証接続と通常のBlob実通信は最新runで成功しています。一般公開や大幅な権限変更・新契約は最終承認が必要です。最新接続は成功しているため、以前の404を理由にしたブラウザ切替や保護解除は不要です。Production操作は代替にしません。

常駐自律開発や当日実データの定期取得が動作しているとは報告しません。保存済みの正本・PR・監査情報から次のセッションで再開できます。
