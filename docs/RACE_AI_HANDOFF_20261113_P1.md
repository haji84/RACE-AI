# RACE-AI 引継ぎ正本：BOAT P1不足（2026-11-13 JST）

次のチャットでも、まず main・production の最新HEAD、Actions、保存済み原本、PRの差分とCIを取り直すこと。この記録だけで本番完了を認定しない。

## GOAL・不変条件
GitHub Actionsだけで、開催日全国の実対象レースについて既存モデル別のP0（展示前）/P1（展示後）を所定時刻に生成し、AES原本として不変保存、別runnerでSHAと保存時刻を独立検証、既存の公式結果照合・PDCAとGitHub Pagesへ結び付ける。全国の出走一覧・適格レース分母を認証し、足りないデータはNO_FORECAST/HOLD。既存の4競技の目標、既存ボートモデルと採点器、Publicリポジトリ、PC不要、Vercelなしを維持。過去レースへ後付け正式予想を生成しない。暗号鍵・秘密の選手情報・平文予想をPublic Gitに入れない。公式providerの既存取得上限、403/429停止、同一日内の継続計数、単一writerを厳守する。

## 2026-11-13 に実際に確認した正本
- repo: https://github.com/haji84/RACE-AI (Public)
- main HEAD: `bce9a04c53e988d9c7a0ea22a51837baac21760a`（この記録時点）
- production/boat-p0-p1-20261111 HEAD: `0da3f00b0f5c5115f956658d306ddcb9833ec7af`（この記録時点）
- owner実予想run: https://github.com/haji84/RACE-AI/actions/runs/43348227701
- 第3巡失敗job: https://github.com/haji84/RACE-AI/actions/runs/43348227701/job/131632650482
- 11/13暗号日付索引修復PR #271: https://github.com/haji84/RACE-AI/pull/271 （main統合済み）
- 11/13原本復旧・別runner読戻し: https://github.com/haji84/RACE-AI/actions/runs/43374720710 （両job成功）
- 新しい限定修正候補: https://github.com/haji84/RACE-AI/pull/272 （Draft、未本番適用）

## 実測：136レース、P1は9レース
11/13の署名・暗号原本を元に、AES履歴V5の欠落していた11/13索引を復旧した。generationは138→139、暗号SHA256は `052164cde0e24319bb96cdf25f7631047b85ac6a2f6fa0296d9120bf3ab1a117`。別runner読戻しのレース分母136件、P0存在136レース（モデル別保存レコード680）、P1存在9レース（モデル別保存レコード126）。元予想改変0、復旧中の新規予想生成0、公式provider GET 0。独立読戻しステータス `AES_DAY_AND_STAGE_COUNTS_VERIFIED_P1_COMPLETENESS_HOLD`。したがって136-9=127は「P1が存在すると確認できないレース数」であり、**適格な127件がすべてP1生成失敗**という意味ではない。公式の全開催プログラム・展示公開時刻・締切・中止・欠測を突き合わせて初めて適格分母を確定できる。

## 途中停止と原因の区別
run43348227701 はP0関連保存成功、P1巡回1・2成功、第3巡失敗、4〜24巡がskip。第3巡はRESULT artifact `14004326635` をGitHubにアップロードした後、`scripts.boat_private_original_vault capture` が `VAULT_GITHUB_READ_DENIED_OR_UNAVAILABLE` で終了。保全済みsource-controlは `completed_round=2,requests_used=88`。ログはGitHubのどのGET（artifact metadata/run metadata/zip）が失敗したか、HTTP何番かを示さず、再現原因は未確定。推測だけでデータ提供元の取得拒否や予想モデル不良と断定しない。
同ownerの `SAVED_MODEL_VIEW_NAME_SOURCE_KIND` は表示用保存処理の別のエラーであり、P1第3巡の直接原因と混同しない。PR #271のAES V5日別索引欠落は修正・独立読戻しを実証済み。

## 変更済み・未完成の修正PR
PR #272 のブランチ `fix/boat-p1-run-metadata-bounded-read-retry-20261113` はproduction `0da3f00b...` から分岐。GitHub artifact GETで既存の最大3回・間隔2秒/4秒となっていた読込再試行を、同一のGitHub run metadata `actions/runs/{id}` にだけ拡張した。既存SHA/実行元認証・容量検証・保存時刻・同一日source240件上限・公式提供元403/429停止は変更していない。4つの新しいfixture unittestを追加した。ただし「第3巡の原因がrun metadata GET」と確定したわけではなく、**CI合格・実レース再発防止は未実証**。Draftのまま。GitHub APIが返す403/429をこのwrapper自体が分類していない点は、より高信頼な修正を検討する際の制約。

## 本当の次の作業ゲート
1. PR #272 のソース取得なしのunittest/既存回帰CI、元原本の整合・独立読戻し・停止条件を確認する。mainが参照するproduction固定SHAを審査抜きで変更しない。旧runを再予想しない。
2. 既存の認証済み開催一覧・保存済み公式プログラムを用いて開催日ごとの全race IDを突合。各raceでP0有無、展示公開の事前証明、P1適格/非適格/不明、P1保存、有効な事前時刻、欠損理由を出力。公式開始・締切前に遡って後付けの予想はしない。
3. 次の実日で、同じ1日source取得枠と同一writerを保ったまま、異常停止→引継ぎ原本復元→次worker自動起動を実証。プロバイダ取得を増やして枠を迂回しない。P0/P1モデル別・race ID/SHA/時刻を固定。
4. 別runnerでAES保存原本を認証し、既存公式結果・PDCA・Pagesで同一race ID/モデルを照合。「生成」「保存」「独立読戻し」「画面」「照合」を別ゲートで報告する。
5. 未来の全開催日・全実対象レースで同じ本番ゲートを通し、足りないレース/モデルを分母から消さず、カバー率とエラー原因を日別に監査してGOALを確定する。

main上の既存日次Actionsが起動した事実は、全国P1完成の証明ではない。次のチャットでも**引継ぎ復唱だけで止まらず、未完成PRの実テストと全日公式適格分母の算定から進む**こと。
