# Codexへの貼り付け用・RACE-AI 3レーン並列完遂指示（2026-10-25）

以下「Codexに送る指示文」全文をコピーして、GitHub haji84/RACE-AI を操作可能なCodex/Workセッションに投入すること。この文書は実際のCodexジョブ起動の証拠ではない。指示を受け取るCodexはGitHubをread-onlyで照合してから変更を開始する。

---

# Codexに送る指示文（全文）

あなたはRACE-AI（ https://github.com/haji84/RACE-AI ）のプロダクト完成責任者・並列開発統括・品質保証統括として行動してください。これは調査報告だけの依頼ではありません。**ユーザーが採用したGoalを実際のコード/CI/許可済み実データ/外部不変保存/公式結果/iPhone実機受入まで完了させるため、権限と時点・規約の範囲内で、独立レビューと依存解決を繰り返し進める指示**です。ただし本セッションが終了した後まで実際の常駐実行が保証されると偽らないでください。

**あなたが最初に、必ず全文を読むGitHub正本：**
1. https://github.com/haji84/RACE-AI/blob/feat/p0-offline-discovery-gate-20261022/docs/CODEX_RACE_AI_THREE_STREAM_MASTER_HANDOFF_20261025.md
2. https://github.com/haji84/RACE-AI/blob/feat/p0-offline-discovery-gate-20261022/docs/CODEX_RACE_AI_PARALLEL_RUNBOOK_20261025.md
3. このファイル https://github.com/haji84/RACE-AI/blob/feat/p0-offline-discovery-gate-20261022/docs/CODEX_RACE_AI_START_PROMPT_20261025.md
4. 目標 https://github.com/haji84/RACE-AI/issues/67 と作業管理 https://github.com/haji84/RACE-AI/issues/68
5. PR #61、#64、#65、#69、#71、#72 の **現在の** head/base/差分、CI、既存資産。既存Cloudflare private D1/Access/Workerはread-onlyから再確認。過去の保存SHAは動く可能性があるので再確認。
6. 最新GitHub照合と排他担当表 https://github.com/haji84/RACE-AI/blob/feat/p0-offline-discovery-gate-20261022/docs/CODEX_RACE_AI_GITHUB_VERIFIED_STATUS_20261025.md （初回時点の記録であり現在HEADは毎回再取得）

**変えてはならない製品Goal**：4競技（ボート/競輪/オート/競馬JRA・地方）の全開催・全レースを、公式販売締切の早い順に管理する。オッズを予測/学習/Top8選定に一切使わず、能力・近走・ライン・ハンデ・展示・試走・当日馬体重・気象・馬場など合法で本当に締切前に存在したデータで全有効3連単組番から各モデル最大8点を予想し、外部時刻付きで締切前不変保存。公式結果/払戻/訂正照合からモデル別PDCAを反復。未予想を母数から消さない。主KPI Hit@8_all 実測98%以上は未達の極めて高い研究挑戦目標であり、保証や改ざんをしない。自動投票/決済しない。

**3つのチャットからの最新版を統合する：**

**A. 公式データ・掲載検知：PR #72主担当**。10分以内ではない。ボート展示、AUTORACE試走、競輪選手紹介/脚見せ、競馬パドック・別イベントのJRA当日馬体重が、公式の該当レースで公開されたと**本当に観測されたら**入力充足判定を開始する。過去HTMLの汎用説明欄を実レースの発表と混同せず、race_id/出走者・取得時刻・元公開時刻・source SHA・権利用途・欠測を厳密確認。ボートB/K/展示・風波の真データは一部接続済みだがPR71の全部の実入力は未成立。AUTORACE伊勢崎11Rで旧「開催中止」判定は誤りとして撤回済み、実試走数値/掲載差分は未証明。JRA京都12RはCP932 HTML読取成功だが馬ID別当日馬体重公開差分未証明。KEIRIN日程と実選手紹介は別で、実映像/並びの合法取得・掲載差分未証明。まず各1Rの実ソース形式・公開前後2観測・許容された取得頻度を実証。権利不明なら当該ソース/用途はHOLD。

**B. オッズ/Cloudflare/iPhone：PR #71主担当**。既存公式BOAT3連単120値→Cloudflare私設D1保存とSHA読戻しの実レース成功を必ず再利用。芦屋6R/7R・宮島3R・平和島3Rの2026-10-24実証と、Browser Run側429とtimeoutの事実を読む。D1 race-ai-odds-private-preview / Worker owner-only / Access制限の状態は本番の現実をread-onlyで再検証し、秘密情報を公開しない。**まだ未達なのは所有者のiPhone Safari認証/全120表示/60秒×3周期の実機受入、未来レースの正当な60秒自動源流GET、全競技への安全な展開**。既存PR71のodds_refresh_plan.pyはT-60分既定、ユーザーはT-15分/T-10分に短縮する案を検討しているが正式な最終採択は未確認。SPEC_CONFLICTSに保留として記録して、合法な取得方法/無料枠の実測後に最小案を提案。展示の公開トリガーとオッズ毎分開始時刻は別。

**C. 高度予想モデル/結果PDCA：PR #61/#64/#71主担当**。旧3指標B-LITEを完成形にしない。PR64の実K/ST/同一コース、PR71の4競技総合・展開・条件付き着順・レース軌道モデルを最優先で再利用。既存係数を結果を見て過去予測に反映しない。ソースのライセンス、published_at≠first_observed_at、sample_n、合法as_of、真の風向・波・車番/枠/参加者一致を確認し、足りない値は0や平均で埋めずNO_FORECASTとする。既存PR71へ許可された実スナップショットを投入した未来1レースをまず予想し、総合/展開/他のモデル別最大8点を締切前に外部レシート/SHA読戻しで固定、その後公式結果改訂に照合。全レースへ拡大。オッズ予想への混入を絶対に禁止。

**D. 共有統合・独立品質**。PR69共通基盤、PR65 read-only Controller pilot、PR71 UI、PR72 source evidenceを再利用してRaceLedger全件・前時点特徴量・ModelFreeze・OfficialResultRevision・PDCA・Safari UI・Quotaを同じキー/時刻/権限に接続。AI09または真に独立したAI/環境で批判レビュー。**CodeRabbitは使わない**。モデル自身のレビューと正当なGitHub独立APPROVEDを区別。Human Gateを越えない。

**並列手順を守る**：
- 初回は必ず現在のmain/PR head/base/changed files/CIを取得してASSET_REUSE_MATRIXとSPEC_CONFLICTS、SRC_RIGHTS_STATUS、REQUIRED_EXIT_GATESを更新し、全体設計をBuilderと独立Reviewerで照合する。
- A、B、C、Dの4役割を依存関係に基づき動的に割当てる。最初に共有API・証拠schemaを固めた後、Aの公式入力検知、BのD1/Safariと実オッズ、Cの実モデル/凍結を**可能な部分で同時に進める**。レビューとQAは別担当。必要に応じ並列数を増減し、2本固定のために待たない。
- **PR #71はBとCが同じブランチ**なので、別worktreeで並列コード作成しても、GitHubの正本へpush/mergeするwriterは**必ず排他/expected-HEAD CAS**で直列化。PR #72はAが担当、PR69は横断依存。PRを増殖させず既存PRを最大限再利用。既存PRを他者の変更ごと上書き・force-push・全PRを一括Mergeしない。
- 1つの変更単位は implement→自動テスト→exact HEAD CI→独立AI09批判レビュー→指摘修正/再レビュー→依存統合→実レースE2EまたはSafari実機→証拠保存→最重要次工程選択。CI失敗は原因とAllowedPathsを特定し最小修正、同じ失敗方法を3回繰り返さず別案へreplan。仕様・根幹構成の変更は先に独立設計レビューと必要な所有者承認。実装のみで止めない。
- 保存場所はGitHubのIssue #68を統合台帳とし、担当・PR・head・SourceRights・CI run ID・独立レビュー結果・model_input SHA・発表時刻・取得時刻・外部凍結レシート・iPhone acceptance・次タスクを毎ステップ更新。プロセス中断した場合は保存点から安全に再開し、レースの重複処理/予想書き換え/D1重複更新を防ぐ。
- 追加費用0円、Publicへの第三者の元画像/映像/公式HTML/全120原数値公開禁止、所有者識別情報・秘密鍵/Token/AccessJWT露出禁止。Cloudflare Access権限緩和、DB破壊変更、定期高頻度収集/外部公開、有料変更、mainの保護解除・正式reviewer変更、主要Goal/構成変更は**個別の事前Human Gate**。今回の指示で包括承認済みと見なさない。
- 権利/別モデル環境/iPhone所有者実機などの外部ブロッカーがある場合、その作業だけBLOCKED。許可されたテスト・設計・実装・内部実証など他のクリティカルパスは進め、Ownerへ必要な操作を前倒しで1点ずつ明確に通知する。権利がないからと言って無断でスクレイピング/録画/高頻度ポーリングを始めない。
- **完成宣言**は1未来レースの合法実データ・事前モデル凍結・公式結果照合だけではできず、4競技全対象捕捉、D1/iPhone実機、予想不変/低コスト無人復旧、独立審査、main/適切な稼働環境での製品受入、前向きHit@8_allの98%達成検証まで分離したGoal Ledger上で判断。過剰な精度を保証しない。

**実行の最初のコマンド/ステップ**：GitHubの現在のmainとPR #61/#64/#65/#69/#71/#72を再fetchし、引継ぎドキュメントの差分を読んだら、①現状表（完了証拠と未達を別記）②衝突/権利/費用一覧③最短P0依存経路④A/B/C/D並列担当・作業ファイル/lock⑤最初に実装してCIを回す変更⑥人間が先に操作する必要のある事項をIssue #68に更新。**この最初の返答だけで作業終了せず、安全にできる実装・テスト・独立レビュー・復旧まで進める。**

Codexが実際のツール・権限・トークンを持たない場合、作業を成功と見せかけない。権限不足に対する迂回も禁止。実際に止まる時には保存されたGitHubの正確なhead、成功CI、BLOCKED理由、再開対象と次の人間操作を示す。終了後に勝手に働き続けると断言しない。

# ここまでがCodexに送る指示文
