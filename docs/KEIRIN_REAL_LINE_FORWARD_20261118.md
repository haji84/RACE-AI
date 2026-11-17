# KEIRIN 実連係履歴と未来同一レース A/B/C 比較（2026-11-18 JST）

## 目的

A = 既存PR71の保存済み従来モデル、B = 6局面/勝ち上がり条件による段階別研究、C = B＋先頭と番手/3番手の実連係履歴。将来の同じrace_id・as_of・公式締切・事前登録母数で3方式を独立保存して評価する。PR #291はDraft維持、保護main・正式モデル重みは変更しない。

## 今回の実資料2レース（「想定ライン」であって実走の追走結果ではない）

| 過去レース | 公開の並び予想 | 先頭→番手の登録番号 |
| --- | --- | --- |
| 2026-11-09 武雄2R | 5-3-6 | 神尾敬冬 015709 → 三ッ井武 014525 |
| 2026-11-10 武雄4R | 7-4-3 | 神尾敬冬 015709 → 三ッ井武 014525 |

照合先： 
- 選手登録番号 https://www.keirin.jp/pc/racerprofile?snum=015709 と https://keirin.jp/pc/racerprofile?snum=014525
- 武雄11/09 https://keirin.tokyo-sports.co.jp/list/race/20261108_30916 と https://keirin.netkeiba.com/race/entry/?race_id=202611098402
- 武雄11/10 https://keirin.kdreams.jp/takeo/racedetail/8420261109020004/?pageType=yoso と https://keirin.tokyo-sports.co.jp/list/race/20261109_32344

2026-11-18に公開資料を確認して手作業転記。サイト公開時点の原本HTML SHA・実映像のSHA・独立確認された実際の追走位置は取得していない。予想ライン・出走と実走連係は別。着順・決まり手だけからHELD/GAPPED/SWITCHEDを作ることは禁止。

## 今回の差分

- docs/evidence/2026-11-18/keirin_takeo_public_planned_pairs_v1.json：2件の実資料に対応する予想ライン、選手登録番号、公開ソース、追走UNKNOWN
- race_ai/keirin_real_line_evidence.py：登録番号/役割/二つ以上の別ホストのソース/重複・将来混入・偽の追走結果を検査するオフライン研究アダプター
- tests/test_keirin_line_cohesion.py：SOURCE日付だけを確認した場合はJST翌日から有効、実ラベル0件を維持、改ざん・同一レース重複・架空成功を拒否する回帰

パケットのハッシュは転記内容のハッシュであって公開元サイトの真正な原本SHAではない。外部ソースの独立アーカイブ検証を通せるまでは自動学習に採用しない。独立ソース検証ができても「並び予想」を追走成功ラベルに格上げしない。

## 未完の本番ゲート

1. 既存の私的保存済み映像を原本SHAつきで再生し、先頭・番手・3番手の車番/登録ID・打鐘/ホーム/バック/4角・追走/離れ/切替を独立ラベル化する。色や着順を正解にしない。
2. 既存line_cohesion.pyの厳格なLABELスキーマに本物のラベルと原本の可用時刻を通し、C研究重みを結果を見ないで凍結する。履歴ゼロは「初連係」「必ず弱い」にはしない。
3. 同じ未来レースのA/B/Cを締切前に別々にAES保存し、別runnerでSHA照合する。事前登録された母数を後から入れ替えない。
4. 公式結果が公開されてから既存keirin_line_three_arm_audit.pyでHit@1、Hit@全点、100円均等条件の仮想ROI、HOLD率を一括比較する。1回的中で性能改善を断定しない。
5. PR #308でmainへ統合した松山7R前段検査とは別に、結果取得→照合→暗号保存→独立読戻し→サイト反映の本番5工程も未完として維持する。

現在の正確な評価：実在2レース分の「並び予想」は記録できた。実映像で認証された追走結果0件、実履歴で補正したCの本番予想0件、未来レースA/B/C正式比較0件。合成CIを本番成功には数えない。


## 2026-11-18 本番ソース再検査と歴史結果の結合（今回の作業）

### 実資料・結果の証拠を追加

- `docs/evidence/2026-11-18/keirin_takeo_public_pair_finishes_v1.json` に、実際の事後結果を公開ソースから転記。11/09 武雄2R 5-3-1（神尾5番1着、三ッ井3番2着・マーク）、11/10 武雄4R 6-2-4（神尾7番6着、三ッ井4番3着）。2つの公開サイトで同じ結果を確認したが、主催者原本の独立認証は未完。
- `race_ai/keirin_real_pair_finish_outcome.py` を実装。前回の「想定ライン」2レースに、今回は「事後の着順」のみを厳格なrace_id/車番で結合する。元のソース確認日時が日付しかなければ、未来予測に採用できるのは翌JST日から。出走前の予想ライン、事後の確定着順、レース中の追走/離れを明示的に分離。
- 結合例は「先頭→番手が1-2着」1件、「別着順」1件。これは実際の途中の追走維持1/2という測定ではない。追走ラベルHELD/GAPPED/SWITCHEDは**0件、全てUNKNOWN**。結果だけを使った自動学習・Cモデルの正式補正は禁止したまま。
- 転記元: [武雄11/09結果](https://www.keirin-mobile.jp/top/result.php?date=20261109&jcode=84&race=02)、[同日別ソース](https://keirinhex.jp/races/20261109/028420261109/)、[武雄11/10結果](https://www.keirin-mobile.jp/top/result.php?date=20261110&jcode=84&race=04)、[同日別ソース](https://www.chariloto.com/keirin/results/84/2026-11-10/)。

### 所有者非公開レビュー資料の実バイト検証

- Library内の武雄2026-11-09 2RのA/B別HTML（各46フレーム）を読み、A側バイトSHA `4bfab49ce7c1beba6840fab40856aaaf9843afdff9077acd2fa723831ccc6469`、B側 `95d6bd402dbce180486952da643584860c76f7ca1669ab459409b39e7ac845eb` が2026-11-15の過去記録と一致した。
- 別々のペイロードであること、同じ46個の宣言されたフレームID順・動画内秒数、各フレームに埋め込まれた表示PNGのバイト内容がA/Bで46/46一致した。
- **元動画のWebMバイト自体は今回再取得・再復号していない。** HTML内のフレームSHA宣言が元の動画と一致することも今回新規証明したわけではない。A/Bは`reviewer_A_pending`/`reviewer_B_pending`、未提出のレビュー材料であり、人間2者による署名済み判定ではない。
- 赤字秘密情報・PNG・座標を保存せず安全な結果を `docs/evidence/2026-11-18/keirin_takeo2r_real_review_packet_readback_redacted.json` に作成。再利用可能な読取専用検証は `scripts/keirin_private_review_pair_readiness.py`。非公開PNGなどをPRに含めない。
- 実際のレビュー独立正解2件・実選手追跡正解・実追走ラベルは依然**0**。これを偽装しない。

### CIとmain本番停止状態

- 研究Draft PR #291の変更を既存`keirin-pr71-owner-autonomous.yml`のsynthetic-ciに登録し、[Run 44128837320](https://github.com/haji84/RACE-AI/actions/runs/44128837320)（HEAD `63814a050fac09b3580d95d4af261f2820b7df84`）でsynthetic-ci **SUCCESS**。新追加の6件のレビュー資料テスト＋8件の結果結合テストを含む研究サブセット95件PASS。これは本番A/B/C予測成功ではない。
- 既存保護mainの[PR71実行44070303901](https://github.com/haji84/RACE-AI/actions/runs/44070303901)ログではstate=`HOLD_OWNER_SOURCE_PARTIAL_NO_COMPLETE_PR71_INPUT`、`new_pre_race_inputs=0`、`actual_four_model_forecast_saved=false`。Actionsジョブsuccessは本物の4モデル予想成功を表さない。
- mainの[映像独立読戻しRun 44091948744](https://github.com/haji84/RACE-AI/actions/runs/44091948744)は`SOURCE_ARCHIVE_NOT_ATTESTED`。既存のLive本番ソースの証明も別途未合格。
- **現在の正式な未来A/B/C前向き比較件数0**。PRはDraftのまま、main・正式モデル・課金・Secrets・投票には変更なし。

### 次の未完、順序を固定

1. 既存の非公開A/Bレビュー材料から真の実映像ラベルを独立に取得し、選手登録ID/車番・先頭/番手/3番手・仕掛け・HELD/GAPPED/SWITCHEDをフレームと動画SHAに結び付ける。レビューの独立性と出典証明が無ければUNKNOWN。
2. 同一実レースの本物のPR71締切前入力とB/Cの6局面条件を揃え、Cを事前凍結。現時点の公開の「並び予想＋結果」のみではC正式補正をしない。
3. 未来の未使用レースでA/B/C原本を事前登録→AES保存→別runner SHA→公式結果独立取得→`keirin_line_three_arm_audit.py`で同一母数のHit@1/全候補/仮想ROI/HOLD評価。
4. mainでソース拒否・映像保存認証が続くと予想母数0のため、既存ワークフローの回復証拠を優先。エラー回避のための無許可大量アクセスは行わない。


## 2026-11-18 JST 追加本番ゲート：動画全体からの再復号・未来レース母数凍結

### 1. 実録画データのSHA連鎖を本物のWebMまでたどった

所有者Libraryの既存RSA/AES-GCM暗号アーカイブから `202611098402` の実WebM 10,657,421 bytesを一時復号した。暗号アーカイブSHA `f9cb22db33145b85337df5c3dc0e66489d7d1e1d0fec6b99cb9250d3215860e9`、暗号ファイルSHA `2b12476f944331099e6ca2a392fbeec3542d18f30921348f8b859c175998d905`、認証復号WebM SHA `4e389a46c223b7cb2eaa7c5c5bdc34ade229deedea8a3c795c8be987b57aa810` が元マニフェストと一致。

OpenCVで実WebMを再デコードし、0/2/4/.../90秒の46フレームを固定の画面プレイヤー領域（y=30.3〜70.9%、x=29.9〜70.1%）で再クロップ。**実WebM→46フレームBGR画素のSHAが全46件で当初のレビューA/BのフレームSHAに一致。0不一致。** 同じフレームID/画素を持つこともA/B 46/46で確認。これは暗号原本と画素系譜の証拠であり、競輪場主催者の映像権限、正式な車番/ライン・仕掛け・追走の認識精度は証明しない。

- 赤字や元映像を含まない新証拠：`docs/evidence/2026-11-18/keirin_takeo2r_real_webm_redecrypt_frame_sha_v1.json`
- 既存レビュー用PNGからデコードしたBGR source SHA 46×2の検証処理を `scripts/keirin_private_review_pair_readiness.py` に追加。別系統ソースの現実映像はCIへ含まず、合成PNGで判定を回帰。
- 6か所の実フレームについて5番黄色と3番赤の見かけの前後を単一観察として記録：`docs/evidence/2026-11-18/keirin_takeo2r_single_visual_color_order_candidates_v1.json`。**観測者はAI単独。実追走のHELD/GAPPED/SWITCHEDラベルとして認証されていない。** 「映像フレーム一致」と「本人追走認証」を混同しない。

### 2. Cを本当の連係履歴につなぐ受け口・B/C別Freeze処理

`race_ai/keirin_real_three_arm_prospective_bridge.py` を追加。既存の `keirin_line_cohesion.forecast_with_pair_evidence` にしか入れない。既存PR71元原本・今回本人登録ID・過去真の映像ラベルの外部認証がある場合だけBとCを作る。想定並びの転記を渡すと拒否、履歴ゼロならBのみ研究表示、CはHOLD。証拠数が不足しCの重みが変わらなければ正式な三方式比較完走とは数えない。

元のAを書き換えず、B/Cを別々の0600ファイルとして0700非公開ディレクトリへcreate-once保存・同ジョブのSHA読戻しするソースフリー処理を追加。**本物のAES跨ぎ保存・別runner読戻しではない**。この本番接続は引き続き未合格。

### 3. 実際の未来レースを、発走前に選定して母数を固定

**2026-11-18 西武園1R（race_id `202611182601`）**を前向き比較対象として登録。楽天Kドリームスと東スポ競輪の出走表上、発走10:50、掲載締切10:45 JST、A級予選7車。主催者の改訂/実際の発売終了時刻は独立認証待ち。

- 初期登録コミット `56a2628affed56a5411edfb2240f153c513fb730` のGitHubコミット時刻：2026-11-17 17:09:31 UTC（JST 11/18 02:09:31）、出走表記載締切より前。
- `docs/evidence/2026-11-18/keirin_seibuen1r_future_three_arm_pre_register_v1.json` を元登録とする。
- 既存 `keirin_round_paired_audit.make_cohort` 形式のSHA凍結レース母数1件も `docs/evidence/2026-11-18/keirin_seibuen1r_3arm_cohort_frozen_v1.json` に記録。cohort SHA=`8cd2699a2c57431416f9dd97ebf930f98f19388acf34cf8d87747c2d7116dcf2`。
- 出走前資料 https://keirin.kdreams.jp/seibuen/racedetail/2620261118010001/ と https://keirin.tokyo-sports.co.jp/list/race/20261117_30979 。締切変更や公式主催者裏付けが得られなければHOLD。GitHubコミット時刻は事前登録の証拠であって、**A/B/C予想を締切前に作成した証拠ではない**。

### 4. 現在の前向き比較成績は未確定

`keirin_line_three_arm_audit.summarize` の実選定1Rを、まだレポート0件で実行したときの正しい状態は planned_races=1、three_arm_paired_races=0、unpaired_holds={UNREPORTED:1}。不的中0件・的中0件として加算しない。将来の正規結果とA/B/C暗号原本が全部揃ったときだけ同一1レース母数を採点する。

現在の**4工程状態**：

| 工程 | 今回の進捗 | 本番正式合格 |
| --- | --- | --- |
| 映像から連係追走を認証 | RSA/AES WebM→46 BGR原本SHA 46/46、単一観察候補を記録 | NO（本人/追走の独立確定ラベル0） |
| Cへ実履歴接続 | 真正ラベルだけ受ける新bridge、偽並び/無証拠をHOLD | NO（学習対象の真正追走ラベル0） |
| 未来A/B/C同時保存 | 西武園1Rを事前登録、A原本保持とB/C私的Freezeの研究テスト | NO（本番AES+別runner未合格） |
| 公式結果による3方式比較 | 同一1Rの分母SHA固定・未報告HOLDテスト | NO（未来結果と3方式の事前原本なし） |

PR #291はDraftのままでmain/正式重み/自動投票は変更せず、AI独立性・原本暗号・可用時刻を偽装しない。次の具体的な障害は**既存PR71の本番モデル入力が取れないこと（旧RunではHOLD_OWNER_SOURCE_PARTIAL_NO_COMPLETE_PR71_INPUT）と、実追走の確定ラベルがないこと**。


## 2026-11-18 実際の障害2件の再調査とC履歴直接接続

### 障害1：認証済み追走履歴がない

2026-11-09武雄2Rで、RSA/AES-GCMの保存済み元WebMのバイトSHAとフレーム画素SHA46/46の系譜は再現できた。しかし黄色5・赤3の見かけ上の前後関係、着順5-3-1やマーク決まり手、AIによる単一目視だけでは、正式なHELD/GAPPED/SWITCHEDの局面ラベルを新規認証したとは扱えない。**独立認証済み追走ラベルは0件。**

今回は完成済みのレビュー結果をシステムに通せる入口を実装した：
- `race_ai/keirin_observed_follow_admission.py`：少なくとも3つのフレーム、時間順と動画SHA、車番・登録ID・局面・先行戦術、実際の追走/離れ/切替が見えるフレーム、**別々に独立検証された2レビュー署名**がそろった時だけ既存`keirin_line_cohesion.make_label`の履歴に変換。出走前の予定ライン、着順、同色の画素、署名の自称は拒否。外部検証コールバックを実装していない環境ではHOLD。
- `race_ai/keirin_real_three_arm_prospective_bridge.py::prepare_from_signed_tactical_packets`：上記をA元原本のSHAが一致する既存B/C研究計算へ直接つなぐ。元予想/履歴を上書きせず、履歴が不足する場合はHOLD。**実際の署名済みレビューはまだ存在せず、テストの架空人物/鍵を正解として数えない**。
- `tests/test_keirin_observed_follow_admission.py`＋`tests/test_keirin_real_three_arm_prospective_bridge.py`：独立認証なし・同一署名・着順からの偽HELD・無効フレーム・参照元違い・履歴不足の拒否を合成検証。

### 障害2：本番PR71の入力は予想処理より前の**当日一覧ページ**で停止

既存の保護main実行ログの独立読み取り：
- [main Run 44050344058](https://github.com/haji84/RACE-AI/actions/runs/44050344058)
- [main Run 44063985261](https://github.com/haji84/RACE-AI/actions/runs/44063985261)
- [main Run 44070303901](https://github.com/haji84/RACE-AI/actions/runs/44070303901)

3件とも安全な出力に`HOLD_OWNER_SOURCE_PARTIAL_NO_COMPLETE_PR71_INPUT`、`public_page_requests=1`、`provider_denial_stopped_requests=true`、`new_pre_race_inputs=0`、`actual_four_model_forecast_saved=false`が含まれていた。初回の取得URLは固定済みPR71ソース`scripts/keirin_github_owner_future_intake.py`の`https://www.winticket.jp/keirin/odds/YYYYMMDD`。

**重要**：取得元の内部実レスポンスのHTTP 403/429は、この公開安全ログからは識別不能。既存`keirin_owner_public_page_fetch.py`では403と429を同じ`PUBLIC_PAGE_BLOCKED_OR_RATE_LIMITED_NO_RETRY`として通知する。従って「確実に403」とは断定しない。ログが示すのは「初回1GETから拒否扱いになり追加GETを停止」まで。原本の記録：[3 Run診断JSON](https://github.com/haji84/RACE-AI/blob/research/keirin-six-phase-score-20261114/docs/evidence/2026-11-18/keirin_main_3runs_source_denial_verified_v1.json)。

対処優先順位：
1. **独立に利用可能なデータ供給元を正規に確保**するか、既存の公開ページが通常アクセスできる状態に回復したことを本番Runで証明する。403/429後のUA偽装・隠しAPI・アクセス制御回避や繰返しリトライはしない。
2. 取得に成功しただけでは4モデル完走ではない。実出走表、選手登録番号、直近実績、ライン、観測利用可能時刻、各モデルの必須入力が充足し、同一締切前に原本SHAと予想4モデルすべてを保存できたか照合する。
3. 既存の`RACE_AI_KEIRIN_FEED_*`正規JSON提供ルートはコード上すでに存在するが、今回の3 Runにはその完全データ受信・正式保存の証拠はない。別API用Secretを適当に捏造して設定しない。
4. 公開資料では`keirin.yomisuji.jp`が二次利用・監査向けJSONを案内している一方、確認できた公開ページの最終生成は2026-11-08で、説明上9車中心。2026-11-18の全国7/9車の全必須入力を埋めた実例として扱わない。KEIRIN.JPの内部JSON APIを紹介する非公式第三者調査もあるが、公式の正式利用契約や当該レースでの入力網羅を証明しないため、**自動的な本番移行をしない**。

### 現時点の判定

- 映像原本SHAと保存フレーム：確認済み
- 真正な追走・離れイベントラベル：0件、HOLD
- 実ラベル→C研究モデルへの橋渡しコード：追加済み、独立ラベルの本番通過は0
- PR71本番ソースの初回1GETアクセス停止：実行ログ3件で確認
- 本物の新規4モデル正式予想、A/B/Cの未来同時暗号保存・別runner、公式結果比較：0件確認、HOLD
- Draft PR #291にのみ追記。保護main・秘密鍵・新課金・自動投票・モデル重みは変更しない。

**次の唯一の正式な前進条件**は、別経路認証つきの実走追走ラベルを受付へ通すこと、およびアクセス可能で必要項目を網羅する正規出走前データを1レース分取得し、同じ未来レースでA/B/C原本の独立保存を実証すること。
