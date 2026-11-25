# 2026-11-25 夜 JST｜競輪三連単95%に向けた学習と開催日別採点

18時58分時点で二元一致した45レースの掲載三連単は17/45。一律8点では23/45。対戦相手の強さを日ごとに学習する案と三者のライン構成を評価する案は過去12,234件の8点で52件・51件増えたが、現行の直近287件では同じ上限での改善が確認できていない。当日の新規4案は締切前に固定。映像から4角付近の3番手を12件で確認し、開催日をまたいで同じ点数を比較する累積採点を追加した。全対象・上限8点での95%到達は検証継続。[検証と前向き登録](evidence/keirin-95-goal-20261125/analysis.md)

# 2026-11-25 夕方 JST｜後から届いた並びで競輪の三連単を再計算

朝の公開後に完全な並びがそろったレースを同じ点数で既存モデルに渡す私用の改訂処理を実装。11月24日の通常決着14件は同じ合計60点で4→6件、全8点なら7→7件。11月25日は後から並びが届いた15件すべてを17時46分に別保存し、掲載時と同じ点数で比較する。18時00分の二元一致は41件で公開三連単14/41。同じ上位4点内の1点目を登録府県・同ラインの関係で選ぶ案は、直近287件の再現で32→35件、4点・8点の組は全件一致。本番採用は未確定。[検証結果・前向き比較・公開状況](evidence/keirin-accuracy-deeper-20261125/analysis.md)

# 2026-11-25 16時24分 JST｜競輪三連単の少点数予想を検証

当日の二元照合33レースで掲載三連単は12/33、同じ点数の予想Aは7/33、Bは6/33。外れ21件のうち13件は勝者を1着に置けず、そのうち9件で勝者を2・3着に置いていた。過去12,234件と直近287件で、同走歴による先頭・番手の勝者、番手が勝ったときの先頭の残り方、別線の2着選手、出走表の予想印などを比較した。11月21・23日は締切前の予定戦法と公式のH・B先頭、勝者の決まり手を119件で照合した。先行・押え先・カマシの予定選手が実際にB先頭だった102件でも掲載三連単は40件的中・62件不的中。現行の買い目で一貫して的中が増える補正は確定していない。午後は42レースに8通りの比較予想を締切前に固定し、元サイトの掲載予想も継続して採点している。[検証と前向き登録の記録](evidence/keirin-accuracy-forward-20261125/analysis.md)

# 2026-11-25 JST｜競輪の公開日をGitHub Actionsで自動登録

元サイトの公開を従来の競輪ブランチに記録すると、既存の公開照合Actionsが起動する。対象は公開記録の `publication.json`、`site-publication.json`、`site-all-publication.json`（`docs/evidence/keirin-*/` 配下）、または `docs/evidence/keirin-site-publications/` 配下の日別JSON。掲載元の実ページを確認して台帳を登録し、以後は既存の定期Actionsが2媒体の結果を照合して保存する。公開した予想が増えた日は旧台帳を保存し、以前に照合した結果を維持する。

元サイト第32版の公開記録で自動起動を確認。11月25日14時31分のサイト読み戻しでは当日22/75件、前日79/81件、前々日87/89件が照合済み。元サイト第32版では新しい予想公開時に前日・前々日の保存版を選択できる。公開記録をGitHubに残さず元サイトだけを更新した場合も新しい日付を探す定期処理は、保護されたmainへの取り込み待ち。[本番の自動実行](https://github.com/haji84/RACE-AI/actions/runs/45554054130)・[画面と保存値の照合](evidence/keirin-pair-diagnosis-20261125/daily-results-automation.json)

# 2026-11-25 JST｜競輪三連単の外れを公開と同じ点数で検証

11月21〜24日の再現は4点・8点で93/287件（32.4%）。外れ194件中159件は、買い目に正しい順の1・2着がなかった。11月24日に予定ラインを分類できた56件では、1・2着が同ラインなら13/25件、別ラインなら1/31件が的中した。295レースの結果詳報を照合し、切替の明記は21レースで4件的中。上がりを直近90日で補正しても同じ掲載点数では93/287件だった。過去3年分の結果詳報から実追走5,198組を名寄せし、その履歴を使った補正も93件のまま。11月25日は、まだ締切前だった73件で研究予想を別に固定した。締切前資料で競りが明記された過去3件では、番手を取る選手ごとに並びを分けると同じ4点で0→1件。静岡9Rと西武園3Rでこの比較予想を締切前に固定した。[比較の根拠・選手の動き・締切前の固定記録](evidence/keirin-pair-diagnosis-20261125/accuracy-gap.md)

# 2026-11-25 JST｜元の競輪サイトで掲載点数別の的中信頼度を表示

08時58分に11月25日の75レースすべてに、三連単・二車単それぞれの信頼度と同条件での過去的中数を掲載した。三連単287件、二車単637件を照合した。今回は激アツと高はどちらも0件。三連単は中21・低12・未評価42、二車単は中43・低4・未評価28。元の予想とのハッシュ一致、武雄1Rの締切後評価注記、本人接続なしの150券種表示を確認した。[表示方法と検証条件](evidence/keirin-pair-diagnosis-20261125/analysis.md#掲載点数別の的中信頼度)

# 2026-11-25 JST｜競輪75レースの予想を元サイトに掲載

同条件で採点した過去207件では、映像学習の更新版が全8点で93件、掲載用の4点・8点の使い分けで71件的中した。2・3着補正版は同じ配分で67件。11月25日は8場75件の順位を07時37分までに固定し、08時43分19秒に元サイトへ掲載した。三連単は4点60件・8点15件。個人戦8件は共通順位、並び未掲載15件は既存の出走表方式を使った。武雄1Rのオッズは締切4分51秒前にも取得。掲載360点中275点で三連単の数値オッズを確認できた。本人接続なしの配信を読み戻し、75件の結果照合台帳を既存Actions用に登録した。[公開予想と照合タブ](https://keirin-20261119-race-note.chankuma.chatgpt.site/)・[時刻と件数の記録](evidence/keirin-pair-diagnosis-20261125/publication.json)

# 2026-11-25 JST｜競輪で別ラインの番手を落とす理由を検証

三連単8点の同条件比較で、実際の1・2着が同ラインのときは74/106件、別ラインでは14/87件的中した。別ラインの番手が絡む41件では、正しい順の1・2着が8点に入ったのは4件。過去の別期間で1・2着の組を再学習すると、展開内で相手を特定する順位は改善したが、その展開に割り当てる確率が下がった。11月24日に締切前固定した別の研究予想66件では、相手と3着の補正で8点が21→24件だった。11月25日は出走一覧3社で一致した8場75件すべてで2・3着補正の比較予想を締切前に固定した。並び未掲載の15件は既存の共通出走表方式を使った。映像更新の比較は初回の60件。結果照合前。[母集団別の比較と採点方法](evidence/keirin-pair-diagnosis-20261125/analysis.md)

# 2026-11-25 JST｜競輪の映像を累計143件で判読し、三連単の1点・4点・8点を再採点

再生失敗だった27件を全て再試行し、初試行の13件も確認。20件で選手の位置を新たに判読できた。今回の新規判読は計52件。過去3年の82,767件のうち累計143件で1地点以上の選手の位置または動きを確認し、映像未確認は82,624件。いわき平・岸和田・函館の対象開催日は全レースを判読した。B先頭が4角も先頭にいるかの学習は105件。三連単のB→4角は27例、4角→確定1・2着は30例で学習し、同じ207レースで従来と比較した。1点26→27件、4点69→70件、8点93→93件。前向きの精度向上は未実証。[開催別の全件台帳・再生結果](evidence/keirin-video-corpus-20261124/all-watch-progress.md)・[三連単の比較](evidence/keirin-video-corpus-20261124/player-recovery-finish-study.json)

# 2026-11-25 JST｜競輪の保存映像24件を全件再読し、4角からゴールまでを予想に反映

過去3年の対象82,767件のうち、映像または保存資料で1地点以上の選手の位置・動きを確認したのは123件、映像未確認は82,644件。公開プレーヤーで新たに32件を判読した後、保存済み78件のうちBと4角の両方を確定できていなかった24件も全て再読した。13件を新たに採用し、選手別のB→4角の学習は88件、後日の検証は20件。三連単はB→4角と4角→確定1・2着の両区間を更新して同じ207件で比較した。1点26→26、4点69→70、8点93→93件。以前に固定した95件では、B先頭が4角も先頭だった75件のうち、確定1着まで残ったのは28件だった。[全件台帳・映像の判読と採点](evidence/keirin-video-corpus-20261124/all-watch-progress.md)・[4角とゴールの照合](evidence/keirin-video-corpus-20261124/b-corner-finish.md)

# 2026-11-25 JST｜競輪の映像32レースを追加判読し、選手別の予想を再検証

6開催日の既存確認を除く全58件と松戸1Rの計59レースで公開映像を確認。32件で位置を判読し、27件はページか映像を開けなかった。3年の対象82,767件のうち映像または保存資料の確認は累計123件、未確認82,644件。最終バックと4角の両方で先頭を判別できた新規29件のうち、5件で先頭が交代した。三連単207件の8点は93件のまま。過去の勝敗因を使った別検証の8点は63,487件で的中が64件増え、締切前に出走表を保存した516件では1件減った。[開催別の件数・観測秒数・学習結果](evidence/keirin-video-corpus-20261124/all-watch-progress.md)

# 2026-11-25 JST｜競輪の公開映像15レースを判読して追加学習

未判読の学習用10レースと独立評価用5レースをKドリームスで再生した。バックから4角への先頭交代を9レースで判定して選手別の既存学習例に追加。以前の13件では誤差が下がったが、新たに映像を開く前に予測を固定した5件では、判定できた3件の誤差が増えた。三連単の同条件比較207件は1点26件、4点69件、8点93件で、学習を加えた後も同数だった。[レース別の観測と学習の検証](evidence/keirin-video-corpus-20261124/analysis.md#公開プレーヤーでの追加学習)

# 2026-11-24 JST｜競輪の未確認映像82,689件の照合

未確認82,689件を1,096日分の掲載資料と照合し、12,818件で当該レースの映像ボタンを確認した。残り69,871件は開催詳細リンクまで。Kドリームスのサイト利用条件を確認して録画を停止し、今回の映像判読・追加学習は0件。研究用映像の提供範囲と利用条件を尋ねる照会文を用意した。記録時点で窓口への送信は未実施。[照合結果と再開条件](evidence/keirin-video-corpus-20261124/analysis.md)

# 2026-11-24 JST｜過去3年の競輪映像台帳と選手別の学習

1,096日分の全掲載82,774件を登録し、7件の中止を2媒体で確認した。登録番号で特定できたのは2,636人。映像を確認できた78レースのうち、仕掛けか追走を読めたのは15レース・29人。全員について最終周の両項目を確認できたレースは0件。各選手の区間を確認して順に学習を再開できる。三連単の改善は未実証。[映像の範囲と検証記録](evidence/keirin-video-corpus-20261124/analysis.md)

# 2026-11-24 JST｜競輪の別ラインと万車券を締切前に推定

別ラインの1・2着は低判定26.5%、高判定60.7%、三連単の万車券は低判定15.8%、高判定39.1%。16,325件の全レースで、調整期間で選んだ配分の8点は6,594→6,598件で改善差の95%区間にゼロを含む。買い目ごとの万車券見込みも学習した。万車券優先の8点は実際に万車券が出た4,240件のうち13→355件を当てたが、全体は6,594→910件。上位4点を守り高判定の残り4点だけ替える設定は万車券49件・全体6,347件。現状の配分による全レース精度の向上は未確認。[レースと組み合わせの採点](evidence/keirin-race-risk-20261124/analysis.md)

# 2026-11-24 JST｜競輪の決まり手、相手別成績、実走の位置と仕掛けを学習

出走表と結果を照合した26,994件、登録番号を照合した月別結果47,635件を使い、マークのある2着、同じ相手が出走した場合の決まり手、H・B先頭、公式レポートの仕掛け・追走を加えた。三連単16,325件で従来の1/4/8点は1,912/4,686/6,594件、着順確率の補正は1,896/4,679/6,596件、決定木の再学習は1,915/4,683/6,595件。8点の差の日単位95%区間はいずれもゼロを含む。締切前保存版557件では再学習版の8点が223→227件、4点が166→162件。全体の精度向上は未確認。全選手の通過順位と実際の仕掛けを記録できる範囲は限定的。[照合したデータと2方式の採点](evidence/keirin-method-matchup-20261124/analysis.md)

# 2026-11-24 JST｜競輪の直近の調子を対戦相手の強さで評価し、保存オッズも比較

三連単の過去16,325件で、相手ごとの得点差を考慮した過去走の先着実績を追加した。従来に比べ4点は4,672→4,686件、8点は6,559→6,594件（40.18→40.39%）。8点の全期間の95%区間は−0.006〜+0.441ポイント。10〜11月3,989件の8点は1,594→1,616件、締切前の保存出走表が残る557件の4点は158→166件。保存オッズ89件では50%混合で1点15→19件、8点48→47件。取得と提供元の更新が両方とも締切10〜15分前だった資料は0件。[採点と取得時刻](evidence/keirin-odds-opponent-form-20261124/analysis.md)

# 2026-11-24 JST｜競輪の別線と番手の着順を学習し、3方式を比較

前回の研究版と過去16,325件で三連単を比較した。過去走を足した1・2着の再学習は8点6,546件、同じ3人の着順補正は6,559件、上位4点を保持した配分は6,560件。従来6,559件との差は1件で日単位95%区間は−0.206〜+0.219ポイント。最後の配分は別線が1・2着となった場合の的中が65件増え、同ラインの的中が65件減った。番手以降の勝ち切りと全体精度の改善は未確認。締切前保存版557件の8点は前回と同じ220件。[学習と3方式の比較](evidence/keirin-targeted-positions-20261124/analysis.md)

# 2026-11-24 JST｜競輪の的中条件と着順を外す場面を調査

前回固定した過去13,275件を調査した。7車でラインを組むレースでは、予定の得点上位2人が同ラインの3連単8点は48.9%、別ラインは34.7%。結果を照合すると、実際の1・2着が別ラインの4,426件では11.9%に落ち、1着が合った3,044件のうち2,018件で正しい2着との組がなかった。三連単が一通りに確定した外れ7,872件のうち2,243件は、正しい3人を違う着順で挙げていた。締切前保存版557件の再集計とS・H・Bの照合も記録した。[的中条件と外れ方](evidence/keirin-hit-miss-context-20261124/analysis.md)

# 2026-11-24 JST｜過去13,275件で競輪の着順付けを比較

11月23日までの過去資料で、ラインと選手の強さの関係から着順ごとに候補順位を補正した。調整期間で選んだ方式の3連単は、前回B方式と比べて4点が28.45%から28.79%、8点が39.95%から40.26%。日単位の95%区間はそれぞれ+0.01〜+0.67ポイント、−0.06〜+0.69ポイント。締切前の出走表がある557件の8点は前回B214件、今回220件。今回の採点は過去データの再現。[3期間の採点と固定記録](evidence/keirin-nonlinear-ranking-20261124/analysis.md)

# 2026-11-24 JST｜締切前の並びを照合し、H・Bを使う競輪予想を比較

締切前の保存版393件と11月24日の取得し直した64件で、確認できた版の間の並び変更は0。公式結果のH・Bは新規240件を含む316件、公式記述から仕掛け・位置取り108件と追走継続13組・離れ4組を照合した。過去3,989件の3連単8点は保存方式1,579件、B方式1,588件、H→B方式1,592件で、改善差の95%区間はゼロを含む。11月24日の64件で締切前に比較予想を固定し、最初の1件は締切約13分38秒前に再固定した。[取得、版、固定と採点](evidence/keirin-home-back-phase-20261124/analysis.md)

# 2026-11-24 JST｜競輪の別線とS・Bの履歴を再検証

過去23,750件のS・Bと着順を照合し、実績を足した3連単8点を10〜11月の3,989件で検証した。保存方式、履歴追加ともに1,579件（39.58%）。1・2着が別線だった1,692件は288件（17.02%）だった。公式結果79件で登録番号付きのH・Bを確認した。確定人気を照合した3年分の81,967件で上位8点は45.39%。11月24日の66件で履歴追加版を締切前に固定し、結果待ち。[過去走・別線・市場の検証](evidence/keirin-line-events-20261124/analysis.md)

# 2026-11-24 JST｜競輪3連単の組み方を過去4,002件で再現

10月1日〜11月23日の公開出走表を4,002件揃え、照合できた3,989件を採点した。保存方式と2・3着のライン評価を変えた方式の3連単8点は36.98%と39.58%。同じ過去データで90%に達したのはそれぞれ上位96点と87点。締切前の元出走表が残る557件では、3着だけを変更した8点が206件から213件になり、改善幅の95%区間はゼロを含む。11月24日の66件で比較用予想を締切前に固定済みで、前向きの採点は結果待ち。[採点と固定時刻](evidence/keirin-ordered-ticket-20261124/analysis.md)

# 2026-11-22 17:34 JST｜保存履歴検索を検証し、PR1件による反映を承認

日付ボタンを増やし続ける方式を改善し、競輪ガイドに全期間検索、カレンダー、開始日〜終了日、会場・レース番号の絞り込み、20件ずつのページ分けを実装した。日付ショートカットは最大7件、件数の切捨ては0。検討リスト・予算・買い目選択と更新時の検索条件を保持する。

関連Node150/Python53/Chromium23は成功。独立レビューで見つかった空日付・会場条件・年跨ぎの3点も再現して修正した。実際の保存暗号文を使う非公開プレビューでは、320/390/1440pxの全幅で4日257レースを13ページにわたり重複・欠落なく確認。日付検索57件・2日間の範囲114件、予想原本・結果改訂履歴の展開も成功した。平文・本人用鍵・実データ画面は公開していない。[機能と検証](KEIRIN_HISTORY_SEARCH_20261122.md)・[集計証拠](evidence/keirin-history-search-20261122/validation.json)。

並行main ac444a33の変更と凍結した精度比較用worktreeを保全している。実装・検証結果を提示後、所有者の「進めて」により今回の新PR1件と通常検査後の既存画面への反映が承認された。関連既存PRはすべてmerge済みで、開いた別用途/凍結PRは流用しない。配備前の集計証拠と配備完了を区別し、最終CI・統合・HTTP・実ブラウザーの確認結果は[最新配備記録](https://github.com/haji84/RACE-AI/blob/feat/keirin-history-search-20261122/docs/evidence/keirin-history-search-20261122/delivery.json)で記録する。main保護・配備先・予想原本・本番重みは維持する。

この検索は読込済みの保存日が対象であり、暗号文全履歴の読込方式や無制限データ量の待ち時間を改善したという実証ではない。実機iPhone、4競技全件/T15、6艇識別・校正、前向き精度改善は別の未完了項目のまま。下段は過去時点の記録であり、WINTICKETを必須扱いする古い記述は、所有者の後続指示「WINticketにこだわらなくてもいいよ」より優先しない。

以下は以前の確認記録。

# 2026-11-21 JST｜実取得で判明した同一レース参照リンクの限定修正（実保存は統合後に確認）

PR312はmain12cf6b3a729f1eb3c3d67de06bd2c83464539115へ通常保護merge済み。後続の既存実行[44789444126](https://github.com/haji84/RACE-AI/actions/runs/44789444126)では新規参考予想0件、保有38/観測57を維持した。最新の原本監査で、残る区分1件は選択中リンクの同一host/path/race_idに付く `rf=courselist` だけが照合を阻んでいた。2件のcanonicalは結果routeを指して矛盾しており、現在も拒否する。

既存PR8を再利用し、この実在する参照パラメーターだけを選択リンクで検証する。canonical本体・競走ID・日付・R・出走者・級班根拠・締切・既存既定動作は維持する。取得原本と受領時刻を変えず、socketを停止した新旧原本再生で、旧57件は39正常/18未掲載HOLDのまま、新しい19保留分は1正常/16未掲載HOLD/2canonical矛盾HOLD。関連131テストと独立69テスト・追加35負例等が成功した。[再生証拠](evidence/keirin-selected-link-rf-20261121/offline-real-replay.json)・[独立review](evidence/keirin-selected-link-rf-20261121/review.json)。新しい実予想の生成・Git保存は統合後の実行で別途確認し、原本再生を実績へ混ぜない。

並行main243469の公式全国継続処理・4方式表示・既存暗号化資料を保全。PR8の元head3d7977d689ac34df117201aa642afab652f49ddaと14pathの履歴を残し、新PRは作らない。下段の公式実レース1件の照合完了、WINTICKET自体403、4競技全件/T15、6艇校正、実機、前向き改善の未達をそれぞれ維持する。

以下は以前の確認記録。

# 2026-11-21 JST｜競輪の実レース1件で公式結果・4方式採点・独立再検証を完了

11月20日の小倉5R（202611208105）は、締切前に固定したA/B・補正A/Bと公式着順・100円単位の配当を同一条件で比較し、暗号化保存と所有者用表示データの公開まで完了した。実行[44784648369](https://github.com/haji84/RACE-AI/actions/runs/44784648369)は `REAL_FUTURE_CANARY_FOUR_ARMS_COMPARISON_COMPLETE`、比較対象1レース、4方式・公式結果・原本の実行時刻証明を確認済み。新しい予想の事後生成は0件。

別実行[44786003895](https://github.com/haji84/RACE-AI/actions/runs/44786003895)でも保存資料だけから再照合し、`RESULT_WATCH_SAVED_COMPLETE` を確認した。取得先への通信0件、原本・結果は既存表示を再利用し、二重公開は0件。これにより「公式結果取得と本番採点が未完了」という固定レースについての状態は更新する。[安全な実証記録](evidence/keirin-official-continuation-20261121/README.md)。

全国用の継続処理は、この実証を毎回再検証し、既存の公式公開SP経路だけを利用する。原本の取得・独立読み戻し・公開を分離し、結果監視は予想収集と独立する。未対応・未掲載・締切超過を全件分母から削除せず、確認済みA/Bと補正/Cの保留を別表示する。新たな取得拒否は停止を永続化し、過去の停止記録も変更しない。[継続条件と範囲](KEIRIN_OFFICIAL_SOURCE_CONTINUATION_20261121.md)。

この1レースの合格は、全国全レースの取得・全モデルの完成・予想精度の改善を示すものではない。下段の二次資料による参考予想、他競技、全日/T15、前向き評価の未達を置き換えない。全国の実件数・保留理由・新たな実結果の採点は、次の本番実行の記録で確認する。

以下は並行作業と以前の確認記録。

# 2026-11-21 JST｜既存PR312の限定修正は原本再生39/57、残り18は未掲載

最新の確認済み運転は下段のmain88/run44781578013（38/57）。その19保留を暗号化原本から調べ、18件に並び未掲載の明記、1件に同一選択レースのnetkeirin見出しで明示された競走区分を確認した。

- 既存PR312では、Kdreamsの区分省略時だけ、そのnetkeirinの選択見出しを使う明示opt-inを追加。canonical/date/R/選択中リンク/出走者/競走名を結び、矛盾・曖昧さを拒否する。元Kdreamsの締切/並び・統計と元raw SHAは維持し、区分の出典だけnetkeirin PROGRAM receiptと別metadataへ記録する。新モデル・重み・正式admissionを変えない。
- socketを止めた実原本57組の再生は **39正常/18未掲載HOLD**、元38カードは同一byte、121取得原本/受領記録は不変。既存既定動作も57/57で同じ結果・エラー。根拠なしの級班推測・過去表の全体検索はしない。関連66検査＋独立6負例が成功、rootの関連suiteと最終CIを別記する。
- 原本再生は新しい実予想の保存実証ではない。通常保護merge後の既存Actions・独立読戻しが済むまで、現在の実績を39へ書き換えない。main3b975の並行四arm表示、main1591232のdaily coverageも全て保全。workflow graph/source/model pins/頻度/権限の変更0。

[原本監査](evidence/keirin-selected-class-source-20261121/actual-held-source-audit.json)・[オフライン再生](evidence/keirin-selected-class-source-20261121/offline-real-replay.json)・[独立review](evidence/keirin-selected-class-source-20261121/review.json)。WINTICKET自体403、4競技全件/T15、実機iPhone、独立6艇校正、前向き改善の未達は下段のまま保持する。実運転後の結果は既存PR312に追記する。

以下は確認済み運転と以前の記録。

# 2026-11-21 02:46 JST｜既存PR291を統合、実運転で翌日38件生成・結果129一致/3保留

既存PR291は **main88b5bfdad02d01c4a54815b7cdcbc6b73ebe2943** へ通常保護merge済み。レビューhead7900f3480とtree8feb05186e600a846fcb3acc81a92f4cdd7118f3が一致し、PR最終29checks＝13success/16skip/失敗0。配備後のmainもHTTP再照合を含め60checks＝11success/49skip/失敗0。旧失敗は保持し、未実行skipを実証へ加算しない。

- **既存Actionsの実運転**：run **44781578013/job136445426680** はcompleted/success。11/21の掲載元57候補を121要求で確認し、**38レースの参考A/B各38件** を生成・暗号化保存した。local別読取では38件すべてのfile/cipher binding、掲載締切前生成、および掲載締切前にGitHub読戻し済みであることを確認。T15〜10窓の全件保存、実際の主催者締切、正式PR71全モデルの認証ではない。
- **結果改訂を実確認**：過去132レースはlocal実二社取得時の128一致/4HOLDから、同Actionsの別結果取得31要求で **129二社一致/3HOLD** へ更新。前回の取得失敗1件が照合でき、旧観測も別cipherの改訂履歴として保持した。3件は特殊払戻等の公式確認待ち。参考A/Bの11/20共通分母は53→54レースで、学習改善・Hit@8・実購入の実績とはしない。
- **実配信**：既存Pages **718d4622c61769e2d5d63377cef45d1db2a1a947** の実HTTP14資産とmain88の一致を、GitHub job **136452750118/run44780867206 attempt2** でも確認。元forecast identity・全cipher・BOAT core/scorer/cryptoは不変。実公開Page/raw GitHub暗号文の390/1440pxで読戻し、JS例外0・鍵送信0・掲載元ブラウザー要求0。Actions改訂後も390pxで翌日38件/129一致3保留を確認した。本人用リンクの鍵は同じ。
- **残る入力の実原本監査**：19保留中 **18件は「並び予想がありません」と明記**され、並びの数値は0件。残り1件はKdreamsの選択競走見出しが競走区分を省略しているが、同一canonical/date/R/出走者のnetkeirin選択見出しには区分が明記されている。121/121原本/receiptと保存3fileを全byte照合し、推測補完を避けてこの1件だけの限定修正を既存PR312で続ける。新PRは作らない。
- **正式経路は別**：同runの旧PR71は **HOLD_OWNER_SOURCE_PARTIAL_NO_COMPLETE_PR71_INPUT**、source_state=OWNER_ATTESTED_PARTIAL_SOURCE_COLLECTED。生成/PDCA/結果の件数fieldはnullで、job successを全モデルの生成成功に変えない。Noteの参考出力とも別。
- **並行mainを保全**：後続PR318（main1591232）の初回日付観測/daily_coverage、およびPR317（main3b9758b）の既存四arm原本/結果表示を通常mergeで保全する。既存PR312の元379df9b5・34pathのmode/type/blob/metadataも親履歴に残し、旧treeの一括適用はしない。上記の実運転/画面の証拠は当時のmain88に対応する。

[実Actionsとsafe log](evidence/race-ai-goal-continuation-20261121/final-action-safe-log.json)・[38件の独立読戻し](evidence/race-ai-goal-continuation-20261121/final-action-independent-note-readback.json)・[配信画面](evidence/race-ai-goal-continuation-20261121/final-action-live-browser.json)・[main HTTP](evidence/race-ai-goal-continuation-20261121/final-github-http-proof.json)・[19件の原本監査](evidence/keirin-selected-class-source-20261121/actual-held-source-audit.json)。

**GOAL全体は未達**。WINTICKET自身の最初の403、BOAT SのSOURCE_AUTHORIZATION_REQUIRED/403、4競技全日×全既存適用モデル/T15実証、独立6艇識別・距離/時計/強さ校正、実機iPhoneの全受入、11/24終了の前向き精度改善は未完了。iPhone13Pro本人操作を改めて依頼中だが回答未確認。最後の有効study reportはmatched0、既存固定期間と100組/5日/10会場日を保全する。本番重み切替/投票/追加課金/BOAT直接再起動0、state keyのlocal取得・使用0、元offline未push2commitはUNRESTORED。

以下は各時点の記録。

# 2026-11-21 02:04 JST｜並行mainの公式結果更新を保全し、二次結果の照合と統合

検証中に独立作業のPR316が **main78b855e462ec57aef5cc0e265747847ca7bf3b22** へ統合されたため、通常mergeで全変更を保全した。既存PR291だけを継続し、公式 `result/result_revisions/result_updates.json` と、今回の二次研究 `results/result_checks/research_results.json` の両形式・別履歴を保持する。公式の着順/配当を研究HOLDで消さず、更新の重複防止・端末内cache・選択保持も維持した。

- 統合後rootは **Python214、Node87、Chromium12** を確認。独立reviewでもmixed62・公式71・Node87と両結果が混在する320/390/1440の追加実ブラウザーケースが成功、重大未解決0。実132件の既存暗号文を最終readerで再読取りし、原予想不変/128二社一致/4HOLD・参考A/B共通53件を確認した。まだ新しい結果indexはGitへ公開しておらず、最終CI→通常保護merge→実Git保存/Actionsの順で確認する。
- 既存Pagesの並行更新9d317はapp/styleだけが保護main78と同じ新byteになり、manifest/indexのversionは旧版だった。凍結publisherの厳密なHASH_MISMATCH拒否を保ち、直前の検証済みe787との差分がその2fileだけであることと正規main bytesを照合した。CASで2assetのmetadataを修正（b18a0bfe）、同じ凍結publisherでindex/資産を再生成（**5bf9757e**）。全暗号文・元forecast identityを保持し、配備後 **14資産の実HTTP一致** を確認した。BOAT producer/sourceS/counter/stop/weightsは不変。
- 最初のPR CIは、こちらがSafari検査runを複数行へ変えたことで172件中1件の既存契約検査が失敗し、元の単行形式へ戻して9関連検査を通した。次のCIは並行Pagesのmetadata不整合を正しくHOLDした。どちらも失敗記録を残し、上記修正後の新headで再検査する。

証拠は [統合検査](evidence/race-ai-goal-continuation-20261121/validation.json)、[実暗号化読戻し](evidence/race-ai-goal-continuation-20261121/combined-real-sealed-readback.json)、[既存Pages修正](evidence/race-ai-goal-continuation-20261121/concurrent-main-pages-publication.json)、[HTTP](evidence/race-ai-goal-continuation-20261121/concurrent-main-pages-http.json)。**WINTICKET自身403・4競技全件/T15・独立6艇校正・実機iPhone・前向き改善は下記のとおり未達**。正式結果の追加コード自体を完成・精度改善とは数えない。

以下は統合前の検証記録。

# 2026-11-21 01:48 JST｜競輪132件の結果を実照合、配信と前向き監査の不具合を修正（GOAL未達）

本人の「全部完了させて」を受け、実装・検査・実取得を継続する。以下が最新の検証時点で、下段は以前の記録として保持する。コード候補 **f2f9c82d2e9d9306b8e97824e58f7674c2257e6b**、基準main **28e726d463e761ec2102c191adb567cf4f469086**。統合後の実HEAD/CI/運転読戻しは[既存PR291](https://github.com/haji84/RACE-AI/pull/291)へ記録する。

- **実結果の照合**：所有ガイドの11/19 **75件**・11/20 **57件**、合計132レースを通常のKdreams/netkeirin取得で確認した。二社一致 **128件**、特殊払戻等の正式確認待ち3件・取得失敗1件の **4件はHOLD**。前半103要求で48件、後半184要求で84件を確認し、403/429は0。これは所有ガイド対象の過去二日であり、現在の全国全件・4競技・全モデルの完走ではない。[実取得](evidence/race-ai-goal-continuation-20261121/real-result-tail.json)。
- **暗号化して端末内照合**：別の表示専用P-256受取人へ結果2packetを暗号化し、実WebCryptoで132件のfile/cipher binding、元予想の不変、128一致/4保留を確認した。参考A/Bで比較できるのは53レース×2=106行。原本の全点数・各100円の研究比較で、Hit@8・公式認証・学習効果・実購入とはしない。これは記録時点ではlocal暗号文読戻しであり、Git保存/実Actionsの完了を先取りしない。[実暗号化読戻し](evidence/race-ai-goal-continuation-20261121/real-sealed-readback.json)。
- **継続処理の修正**：新しい締切前予想を先に保存し、その後で過去日結果を照合する。新規予想0件・日付跨ぎでも結果照合を続け、元予想と結果改訂を別保存する。独立reviewで見つかった「過去日発見だけで時間切れ」「入力collector例外時の拒否ラッチ消失」は実再現→修正→独立再検査で解消した。拒否後の追加GETは0。取得総数/日数の切捨て上限は設けず、既存budgetで日・会場を公平に巡回する。
- **Pages検証の修正**：承認済み競輪ガイド追加後に、旧f603の全app byteへ固定していたHTTP検証がrun **44738980224/job136297904822** で失敗した。元forecast identity/全cipher履歴/BOAT core・scorer・cryptoと資産pathを固定したまま、保護mainの現行JS/CSS全件とGit/manifest/HTTPを照合する方式へ修正。現在の旧main28eとPages e787を実HTTPで14資産一致確認し、異なる配備/改変manifest/未承認codeを拒否した。BOAT producerには変更しない。
- **前向きobserverの修正**：長時間producerの古いrun.updated_atだけで、新しい正規recordを落とすshortcutを削除した。実AESを使う回帰と独立検査が成功。各recordの時計/登録/締切・固定study・採点器・閾値は変えず、失われた新規原本や精度改善を作り出さない。
- **検査と保全**：rootのbackend66、Node23、Chromium11（320/390/1440）、Pages/既存guard23、新規observer回帰1が成功。独立backend59・client5browser/22uniqueNode・observer関連90も成功し、重大未解決0。実暗号化feedでも132件表示、JS例外0・鍵送信0・providerブラウザーGET0を確認。実機iPhoneではない。既存PR291の元head **f06b15aee0c6d615deed9dceda8cbdfe41042c98** と213変更pathをGit親/manifestへ保存し、古いtreeを再適用せず新PRを作らない。[review/検査](evidence/race-ai-goal-continuation-20261121/README.md)。

| 残るGOAL | 現在の実証と不足 |
| --- | --- |
| WINTICKET自身の403解除 | 最新確認run44728334291/job136261471157は11/20 20:32:53 JST、最初の通常 `/keirin/racecard/` GETで403、解析前。本人iPhone Safariでは表示するが、具体的原因と正規automation接続条件は未確定。別入力の200をWT解除とはしない。 |
| 4競技全件・T15生成保存・結果 | 最新BOAT owner44656378586は新巡回0/GET0/24skip、真正controlは AUTHORIZATION_WAIT/SOURCE_AUTHORIZATION_REQUIRED/403/attempts1。最新結果44766623468も当日分母null/SOURCE_WAIT。formal競輪は不足入力で予想0、AUTO/HORSE全国継続運転は未実証。Noteでは33件の締切前生成/保存、うち同一T15〜10窓1件を過去run44683039940で確認済みだが、正式全モデルと区別する。 |
| 6艇識別・校正・予想接続 | 実775frame/7選定frameのAI開発参照では6艇同時正解0/7、適格ID遷移0。独立した時間方向ラベル、距離/時計のcheck点、強さの正解targetがない。未校正の強さやAI参照を合格へ変換しない。 |
| 前向き精度改善 | 登録済み期間は11/19 12:15:30〜11/24 12:15:30 JST。最後の有効reportはmatched0、必要100組/5日/10会場日未達。終了を早めず、旧574組で埋めず、結果を見る前の新規原本を要する。 |
| iPhone13Pro実受入 | 接続実機はなくRACE-AI本人操作の返答は未確認。Chrome・Mac SafariやWT一覧の表示を実機合格へ置換しない。 |

[正確な実run/artifact/件数とnullの監査](evidence/race-ai-goal-continuation-20261121/actual-goal-audit.json)。BOAT **S=1dbb47b68d487fc6def0bd4b10b1423f0a2145f6**・counter・stop・source/model pinsを保全し、直接dispatch/rerun/cancel/reset/hotswapは0。本番重み切替・投票・追加課金・state keyのlocal取得/使用0。元offline未push **b7380fe6a377e6ccf2b96331f2126c52549bbe17 / daae4c10167224b7730006d8ada5ade398aaa64b はUNRESTORED**。別環境ファイルの自動移転は仮定しない。

以下は以前の記録。

# 2026-11-20 JST｜提供された競輪ガイドをGitHubへ取り込み、既存画面で実読取りを確認

本人の『取り込んで、GitHubに取り込んで使える画面にして、入力元も同じようにして。』に従い、同じRACE-AIに統合する。以下を最新として優先し、下段は当時の記録として保持する。

- 所有サイトの公開v6 source **25a829413d5f5940f0dcaed1cc7dda7e473105a0** を保全。11/19の75レース/539選手/680点、11/20の57レース/414選手/原分析543点・可変改訂594点、2車単、参考A/B、C未生成を区別する。原本122ファイルのGit archiveも暗号化して同じGitHubに保持した。別環境のファイル自動転送は仮定せず、元offline未push **b7380fe6a377e6ccf2b96331f2126c52549bbe17 / daae4c10167224b7730006d8ada5ade398aaa64b はUNRESTORED**。
- 既存PR **#62** の履歴を親に残し、現在のmain **4701697f5**（公式履歴canaryを含む）を保全してmain向けに整理した。新PR/モデル系統/課金/投票/本番重み切替は追加しない。旧PRの古い他分野のtreeを戻さない。
- 既存Pagesの現行70資産を土台に、日付/会場/検索、2車単・3連単、原分析/改訂/A/B/C、点数選択、予算配分、コピー、6局面、選手情報・出典、保存オッズと照合の画面を統合。実公開URL **https://haji84.github.io/RACE-AI/** はHTTP200。実ネットワークのChromium390/1440pxで57件/75件の切替・B/C・元BOAT表示を確認し、JS例外0・鍵の送信0・掲載元へのブラウザー要求0。**物理iPhone/Safariの合格ではない**。[実公開画面](evidence/keirin-site-import-20261120/live-pages-browser.json)。
- Pagesは既存の凍結publisherでCAS更新し、元の全cipher OIDとBOAT manifest identityを保持した。BOAT **S=1dbb47b68d487fc6def0bd4b10b1423f0a2145f6** と既存run **44656378586** は変更・dispatch/rerun/cancel/reset/hotswapをしていない。元の失敗run **43829249080** はcompleted/failureのままであり、後続の実行状態と区別する。[表示更新の保全](evidence/keirin-site-import-20261120/pages-publication.json)。
- 同じKdreams/netkeirin入力を許可済みの通常GETで接続した。ローカル実取得は **6会場57観測、24件締切後、33未来候補中31正規化・参考A/B計算、73GETで拒否0**。2件はnetkeirin canonicalが結果routeを指したためHOLDし、URL照合を緩和しない。1件は掲載T15〜10で取得・計算したが、Git保存まで同窓内の認証はしていない。原本と計算の暗号化Git readbackは **48ac1c6f39872d0ac95baf4123728694e1a1327b**。[取得・保管の実測](evidence/keirin-site-import-20261120/implementation.json)。
- 日々の更新は**独立した表示専用P-256公開受取人**に暗号化し、本人用の秘密鍵はURL fragmentにのみ置く。`RACE_AI_STATE_KEY` のlocal取得/使用は0、表示処理へも渡さない。取得総数の恣意的上限を設けず、全公開開催HREF/未来候補を扱い、掲載T15〜10を優先して一度更新する。取得と計算が両方T15〜10の場合だけpriority receiptに数える。拒否ラッチは日付をまたいで保全し、包装失敗時も制御ラッチだけを保管する。
- 既存の相互排他的なPR71/AB Git writerの**run本文だけ**へ接続し、旧source/configが許す既存実行経路を使う。workflow/job/step/input/if/cron/runner/timeout/permission等の定義追加0、元A/B generatorのblob一致を確認した。最新の運転件数・時刻は [暗号化表示index](https://raw.githubusercontent.com/haji84/RACE-AI/state/keirin-note-view/index.json) と既存完了Actionsを参照する。記録時点の31件はlocal実入力後のGit保管実証であり、統合後の定期全件T15運転を先取りしない。
- 関連Python **103検査**、Node **9契約**、Chromium **6合成ケースと実データ2幅**を検証。PR head8c378cc33のCIは成功11/失敗0、以後の時刻判定・互換性修正と記録は最終headのCIで再確認する。独立reviewは重大な未解決0。[review](evidence/keirin-site-import-20261120/review.json)。
- **WINTICKET側の403は未解消**。今回の別入力元のHTTP200と区別する。全4競技全件×全適用モデル/T15保存・結果照合、実機iPhone、6艇識別/校正/予想接続、前向き改善は未完了。部分入力・参考計算を正式PR71全入力の認証や精度向上と扱わない。

以下は以前の記録。

# 2026-11-20 JST｜全件取得の照合時間を短縮・WINTICKETの実403を再確認（実運転は未確認）

本人用の開発を継続し、既存の画面照合を一括読取りへ変更した。以下はこの変更の統合前検証であり、新しい実全件運転・予想保存の合格ではない。下段の旧記録を履歴として保持する。

- 前回の通常実運転は **6会場57レースID・55詳細/延べ398選手・全10,684応答HTTP200/未確認0**。既存240秒で残る2件が未取得だった。今回は同じ件数・順序・値・token・待機後scopeの検査を維持し、要素別の大量のブラウザー通信だけを一括化した。既存120/240秒と全workflow定義・本文、HTTP/本文/拒否処理、元モデル/weights/source pinsは不変。
- 73 calendar tableの合成ケースが修正前HOLD_OFFICIAL_SP_BUDGET、修正後は既存120秒で全6件/46選手・22応答すべて200へ進んだ。実Chromiumでもinput.valueだけの変更、重複/欠落/順序/入れ子/未審査shadow rootを拒否した。root関連 **147件、元モデル優先環境7+25件** が成功・skip0。独立124件+追加native28controlも成功・CLEAR。実日の57/57とT15保存は統合後の既存運転で確認する。[検証と独立review](evidence/keirin-coverage-winticket-20261120/implementation-and-validation.json)。
- **WINTICKET自身は未解消**。最新確認の定期run **44619210875/job135896120088** は **11月20日06:30:11 JST**、最初の通常公開一覧GETが実HTTP403で、解析/映像へ未到達。後続保管もSOURCE_ARCHIVE_NOT_ATTESTED。本人のiPhone13 Pro Safariでは**同じ /keirin/racecard/ の開催一覧が表示**された。接続元/時刻等が異なり、IP/地域/認証/bot対策などの具体的原因は未確定。新たなWT要求・拒否再試行・偽装・proxy・cookie持込は0。[独立した完了ログの確認](evidence/keirin-coverage-winticket-20261120/winticket-denial.json)。
- **全件取得と全モデル自動運転は別**。既存PR71入力はscore以外に履歴/ライン/環境等が不足し、全scoreが揃っても7/9車で86/108 numeric slotsが欠ける。現在の既存経路はnew_pre_race_inputs=0・grants=Noneで、全件取得後も予想0/HOLDを維持する。欠測の推測補完・自作の許可証・空の本番AES genesisは行わない。[既存入力の不足](evidence/keirin-coverage-winticket-20261120/model-input-gaps.json)。
- 新PRを作らず、古い既存PR10の11原pathをimmutable head **e3506dbc0980589fd6476615b793d25c7bdb2854** とGit親履歴に保全して利用する。古いtreeを再適用せず、BOAT source **1dbb47b68d487fc6def0bd4b10b1423f0a2145f6**・原暗号文・予想履歴・PR62 UIを変更しない。[保全記録](evidence/keirin-coverage-winticket-20261120/original-pr10-preservation.json)。
- 全4競技全件×全適用モデル/T15生成保存結果照合、WINTICKET403、物理iPhone受入、6艇識別/校正/予想接続、前向き改善は未達。元offline未push b7380fe6/daae4c10はUNRESTOREDを継承し、自動転送を仮定しない。UI新規公開・投票・本番重み切替・追加課金0。

以下は以前の確認記録。

# 2026-11-20 JST｜競輪の画面遷移と通信完了を修正中（GOAL未達）

本人用の開発を継続する。UI新規公開・投票・本番重み切替は実施していない。以下を最新の実測として優先し、下段を履歴として保持する。

- 検証元mainは **bfd8de04b8e6bb7fefc6a910f1d2aae2f536e40f**。実run **44560531226** は当日6会場・57レースIDまで検証した。attempt1は詳細0、正規のtransport再検査attempt2は **1レース・7選手** を実検証し、両方に未確認通信4件が残ってHOLD_TRANSPORT。確認済み応答は全HTTP200、403/429は0。job successを安定取得成功には数えない。[元の認証済み実測](https://github.com/haji84/RACE-AI/blob/86d832bdb8377055f9e84df15e62680396e2eebb/docs/evidence/keirin-403-official-actual-20261120/actual-main-source.json)。
- 同じPlaywright1.56/既定Chromium141のlocal実取得は14レース・延べ102選手まで確認した。約120秒のnavigation timeoutがreport上TRANSPORT/budget falseとなる分類の不足も確認した。これをGitHubで14件確認したとは扱わない。
- 外部providerを使わない同一ブラウザ版の再現テストで、読み込み中の画像/フォントを通常の画面遷移が中断し、`net::ERR_ABORTED` からcollector全体が止まることを確認した。旧page.close/hash変更では再現しない。GitHubの停止と整合する機序だが、元logだけで唯一の原因とは断定しない。
- 修正後は送信済み通信を既存budget内で完了確認し、本文/拒否を検査してから通常の遷移へ進む。待機後に今日のscope/tokenを再検証し、unknownを0に書き換えず、失敗callbackも維持する。再現ケースは旧処理0detailsから新処理3details/21選手へ進み、late403はPOST前停止、本文未到達は約1秒budgetでunknown1を保持してHOLDした。
- 関連 **165検査** と元モデル優先環境での **25検査** が成功。例外ログは固定categoryとlocal関数/行だけで、本文・URL・selector・例外messageを出さない。workflow全byte/既存時間上限/元モデル/weights/source pinsは維持し、新しいjob/step/input/cron/runner/permission等を増やさない。[再現と保全](evidence/keirin-request-settlement-20261120/README.md)。**新しい実Actions取得は記録時点で未確認。**
- 既存PR72の元head **7a432e5acc4d3495a0e82bd79726929e2f8085fe** と331変更pathのmode/type/blob/immutable URLを保全し、元treeは適用しない。既存PR62はUI/証拠Draftのまま、本人用82 web blobs/tree **5cbbfe05a2971485b5c32a84a8ddf7b2539604cc** はhead **86d832bdb8377055f9e84df15e62680396e2eebb** に不変で保持する。新PR0。
- source/model admissionはfalse、新予想0。WINTICKET自身/映像collectorの403解除、全4競技全日×全既存モデル・締切15〜10分前生成/保存/結果照合、物理iPhone13Pro、6艇連続識別/校正/予想接続、前向き精度改善は未達。元暗号文336候補/1,008fileの復旧、実Mac Safari172検査、元offline未push2commitのUNRESTOREDを継承する。
- BOAT source **1dbb47b68d487fc6def0bd4b10b1423f0a2145f6** の待機・counter・原本を変更しない。直接dispatch/retry/cancel/reset/hotswap、課金、投票、本番重み切替は行わない。

以下は以前の確認記録。

# 2026-11-20 JST｜競輪の公式入力を修正中（GOAL未達）

本人用の開発を継続する。一般公開の確認待ちは設けず、UI新規公開・投票・本番重み切替は行っていない。以下を最新の実測として優先し、以前の記録は下段に保持する。

- 今回の検証元mainは **6306a6fd59f9a7b2df46eb8640d9ad5966c6a59e**。BOAT source **1dbb47b68d487fc6def0bd4b10b1423f0a2145f6**、元モデルと映像sourceのpin、Secrets/flagsは変更していない。
- 認証済み完了log **44553849928/job135664465763** では公式経路102応答が全てHTTP200、403/429・block・unknownは0、カレンダー73開催まで解析した。一覧の未来日欄にも今日と同じ確定リンクを要求していたため、レース・選手の検証は0のHOLDだった。job successを取得成功に読み替えない。
- 今日だけの厳密なリンク検証に修正した通常のlocal実取得では、当日の全候補 **6会場・57レースID** を検証し、最初の詳細画面まで全796応答HTTP200。表示用画像の追加項目で停止した。画像alt/srcの明示的な組を読取り形式に追加し、値をモデルや校正済み強さへ変換しない。
- 次のlocal取得は **4レース・28選手** を検証。確認済み1,527応答は全てHTTP200、終了時unknown1を保持し、9車立ての枠番号項目で停止した。公式表示JSにある枠番号/表示CSSだけを追加で読み分け、全許可keyは掲載JSの21項目と一致する。修正後に保存済み **5レース・37選手** をofflineで再検証した。これを5件の新規予想や全日全モデルの完成に数えない。
- 未完了の通信本文にも既存budgetを適用した。loopback実ブラウザで、旧処理はbudget1秒でも本文待ち2.995秒、新処理は約1秒でHOLDする。上記Actionsの長時間stepは依存導入であり、この待ち問題が実原因だったとは断定しない。
- 関連 **155検査** と元モデル優先の環境で **25検査** が成功。source/model admissionはfalse、新予想0。workflowの全byteは検証元mainと同じで、job/step/input/cron/runner/timeout/permission等の定義を増やしていない。[実失敗・修正・保全](evidence/keirin-current-day-dom-20261120/README.md)。**修正一式の実Actions取得は、この記録時点では未確認。**
- 既存PR103の元head **9b875cf9c1d48f8bd31e95fd407a24cf3dcdb330** と132変更pathのmode/type/blob/immutable URLを保全する。元のEV/model変更treeを本番へ適用せず、新PRを作らない。
- WINTICKET自身と映像collectorの403は別件として未解除。今回の公式入力経路を、そのサーバ側の解除と同一視しない。拒否後retry、UA/headers偽装、cookie持込、proxyは行っていない。
- 4競技全日×全適用モデル・締切15〜10分前の生成/保存/結果照合、物理iPhone13Pro、6艇の連続識別/校正/予想接続、前向き精度改善は未達。原本/登録済み観測期間/本番重みを保全する。
- 保管復旧336候補/1,008file/375,640,877bytes・欠落0相違0、実Mac Safari172検査、未push **b7380fe6a377e6ccf2b96331f2126c52549bbe17** / **daae4c10167224b7730006d8ada5ade398aaa64b** の **UNRESTORED** は前記証拠を継承する。別環境のファイル自動移転や物理iPhone合格は仮定しない。

以下は以前の確認記録であり、当時の「現在」表現を含む。

# 2026-11-20 00:04 JST｜競輪403の継続修正（GOAL未達）

本人用開発を継続中。一般公開の承認待ちは設けない。UI新規公開・投票・本番重み切替は実施していない。以下を最新の確認とし、下段の以前の状況は履歴として保持する。

- 確認済みmainは **3c78b756960148f6bafd00a3dd243288430629ed**。既存PR101の通常保護mergeで、WINTICKETの拒否に依存しない公式KEIRIN.JPの通常画面経路を接続した。BOAT source **1dbb47b68d487fc6def0bd4b10b1423f0a2145f6** と既存モデルpinは変更していない。
- 実Actions **44547916659/job135643414848** は公式経路37応答が全てHTTP200、403/429は0。jobはsuccessでも、こちらの通信チェックで停止し開催一覧/レース/選手の解析は0だった。未取得を成功扱いにしない。
- 同じ停止を変更していないguardで再現した。公式画面の掲載scriptが送る `/sp/ana` の空body・同一origin XHR GETが最初の停止点。後続6通信は停止後のblockだった。この厳密な通常通信だけを許可する修正と、解析から既存owner-cycleまでの回帰検査を進めている。[診断と修正範囲](evidence/keirin-official-analytics-20261119/README.md)。**修正後の実取得は、この記録時点では未確認。**
- WINTICKET映像側の実run44491357722と44528962738は通常Chromiumでも `DAILY_INDEX_HTTP_403`。今回の公式入力経路の確認と、WINTICKET自身の403解除は分ける。UA偽装・cookie持込・proxy・拒否後retryは行わない。
- 既存PR102の元head **c52ff0216435b97a0209c43bbe5d0de589445736**、120変更pathのmode/type/blob/immutable URLを保全し、新PRは作らない。workflow/job/step/input/cron/runner/timeout/permissionの定義追加は0。
- 原暗号文の保管復旧は **336候補・1,008file・375,640,877bytes・欠落0・相違0** を別object databaseで全byte確認済み。state head **6c0a01ce55b1948b17610f694a15629df5ccdacf**。追加Actionsの候補AES再検査は初回限定guardでHOLDであり、全byte一致とは別に扱う。鍵のlocal取得は0。[既存PR62の保管証拠](https://github.com/haji84/RACE-AI/blob/6970228c7df74f4e93122facf9d3baff4733413f/docs/evidence/race-ai-final-handoff-20261119/ciphertext-recovery.json)。
- 実Mac Safari26.6の44470498836/job135378501491は172検査・private loopback/AES・合成28PNGを通過した。物理iPhone13ProのRACE-AI受入は未確認。本人SafariでWINTICKET一覧が開いたことを実機アプリ受入に置き換えない。[最新の他scope証拠](https://github.com/haji84/RACE-AI/blob/6970228c7df74f4e93122facf9d3baff4733413f/docs/RACE_AI_LATEST_STATUS.md)。
- 元offline未pushの **b7380fe6a377e6ccf2b96331f2126c52549bbe17** / **daae4c10167224b7730006d8ada5ade398aaa64b** は正規readでもlocal objectでも取得できず **UNRESTORED**。別環境ファイルの自動移転は仮定しない。
- 4競技全日全モデル・締切15〜10分前の生成/保存/照合、6艇の連続識別/校正/予想接続、前向き比較の精度改善は未達。登録済み観測期間/原本/重み/分母を変更しない。

以下は以前の確認記録。上記と矛盾する「現在」表現は当時の時点を示す。

# RACE-AI 最新状況 — 2026-11-19 15:03 JST

**GOALは未達。** 本人利用の開発・受入確認を継続し、一般公開の確認待ちは設けない。原本・既存変更・本番重みを保全する。前版は[同一blobの履歴](history/RACE_AI_STATUS_HISTORY_THROUGH_20261119_1332.md)と[相対リンクも有効なF4原文](https://github.com/haji84/RACE-AI/blob/f4a42cda749e6d52f90610b519df5cd7c896fac5/docs/RACE_AI_LATEST_STATUS.md)に保存した。

## 現在のHEAD・接続・保全

- 現mainは既存PR121の通常保護merge **147d0558dc8c8718af673310b324b63babc90d59**。tested head eeb3c5a4と同一tree `b0627bcfdf671fe49beb14b0610b04f2140aa52d`、26 checks＝12成功/14skip/失敗0。実CIは472件/343.745秒＋旧A74 raw7件/20.255秒。summary型の独立BLOCKERを閉じ、PRのSafari172件も成功した。[mergeと実CI](evidence/boat-main121-merge-and-actual-ci-20261119.json)。
- 並行PR311のmain8d67210c/12変更とPR309のmain9520104c/102変更をmode/type/blob一致で保全した。当方のworkflow変更は0。旧main M3 f4a42cda・M4 ed336daa・M5 a277a692の原study証拠を継承し、再登録は0。
- 稼働BOAT sourceは **1dbb47b68d487fc6def0bd4b10b1423f0a2145f6** のまま。既存Pagesは自動の暗号化data2file更新だけで `379531bb7e6d52157f5f5aa89751727cffcff2cf`へ進んだ。UI資産f603、本番重み、Secrets/flagsは変更0。UI新規公開・投票・新モデル系統・課金・新job/step/input/cron/runner/timeout/権限は追加0。OFF pilot/PR290/291/main308、legacy KEIRIN-AIも当方では変更しない。
- 13:09:32 JSTの実確認は、無認証の公開API HTTP200、正規CLI haji84認証/push権限true、既存branchへの通常FF push成功。匿名/認証のHEADは一致。state keyはActions内だけ。[接続の別判定](evidence/race-ai-public-auth-write-offline-recheck-20261119.json)。
- 元offline変更PR70 `b7380fe6a377e6ccf2b96331f2126c52549bbe17`、PR292 `daae4c10167224b7730006d8ada5ade398aaa64b` は正規APIで再び両方422、local objectもなく**未復元**。ZIPや別環境ファイルの自動移転を仮定しない。

## P0保管・実運転・現在の学習候補読戻し

元run43829249080のP0保管失敗/24巡skipは履歴に残す。修正後A74は24巡・73AES原本・23 ALL_MODEL ZIP・保存P1 513行一致/欠落0を別runnerで確認したが、ALL_MODEL r4/19の欠落HOLDや全日適格は別問題だった。

実Sのfirst worker **44426169530/job135231474660** は自然完了success。実control24巡・今回requests420・lifetime15950。producerは19contexts/新171forecast/既存baseline再利用95を報告し12readback verified。これはproducer集計で、全原本union/全4競技/T15〜10の証明ではない。[実完了](evidence/boat-source1dbb-natural-completion-actual-20261119.json)。

旧追加P0の660原本は別runnerでAES/全inventoryを認証し不変のまま復旧済み。Sのr0は再発行0、132contexts/660slots保持。閉prefix2ではrawAES7・ALL_MODEL ZIP2・新P1 9行一致/欠落0、baseline5行は加算しない。R1 ALL_MODELは件数null/HOLD。issued mapは保存viewからの再構成で、実runtime issued fileの独立読取ではない。[独立認証範囲](evidence/boat-current-s-closed2-actual-counts-20261119.json)。

別のprivate venue学習候補はr18/23/24でVAULT_GIT_PUSH_TIMEOUTを報告した。fallback retained_candidates0を実未保存0にしない。M3実監査 **44460053379/job135344355259** はjob successだが、候補読戻しは**PRIVATE_ARCHIVE/HOLD**で、remoteへ未到達・保存/欠落/相違件数は全てnull。原予想保管とは分ける。[実report](evidence/boat-main3-bound-registration-and-cold-hold-actual-20261119.json)、[artifactの実照合](evidence/boat-main3-actual-counts-artifact-receipt-20261119.json)。

検証器の同race observationのpartition重複集計とsummary primitive型比較を修正し、**M121実ActionsでPRIVATE_ARCHIVEを通過**した。次のremote読戻しでは**336候補中176一致・160欠落・相違0、認証して一致した原bytes194,960,367**。remoteは `1af9a3ad7dda6ef2068397e6f98fa00d1de45fa9`、statusはHOLD_PRIVATE_RESEARCH_RETENTION、reasonはREMOTE_CANDIDATES_MISSING_OR_CONFLICTING。160は一部file不足も含む候補数で、欠落file数/round別内訳は未確認。旧HOLDを保存済みと読み替えず、原ciphertextとActionsの認証済inventoryを照合してcreate-only復旧可能性を調べる。local owner-key取得/復号/復旧pushは0。[実report](evidence/boat-main121-actual-cold-retention-and-study-20261119.json)、[artifact照合](evidence/boat-main121-counts-artifact-receipt-20261119.json)。

後継 **44446167880/job135298730289** は04:38:02 UTCでround2が長時間実行中、artifact7。実control/生成数/source_wait値は未読null。通常next_checkは最大180秒だがAUTHORIZATION_WAIT/SOURCE_REVIEW_WAIT/長いRetry-Afterには正規の長時間待機経路がある。実causeは未確定で、停止・再実行・counter reset・hotswapはしない。[readonly診断](evidence/boat-sourceS-successor-long-wait-readonly-20261119.json)。

## 前向き比較の実登録

M121実Actionsでも **VERIFIED_ORIGINAL_SERVER_WITNESS** を確認した。元M4/run44449743664/artifact14495645723、nonce/spec/実candidate bindings/sourceSは不変。固定観測期間は **2026-11-19 12:15:30〜11-24 12:15:30 JST**。実適格matchedは二セルとも0、schedule分母はnull、評価はWINDOW_OPEN_HOLD。これは0開催/全件0の証明ではない。

100matched/5開催日/10会場日＋3指標の不確実性を満たす前の支持判定はNone。旧574 pairs/登録前予想を新分母へ流用しない。改善・98%・production昇格は未実証。原文代表照合は2/2一致を再確認したが、全records/公開時刻/実発売終了/G8は未証明。[登録と代表照合の実report](evidence/boat-main3-bound-registration-and-cold-hold-actual-20261119.json)。

## 画面・実Safari・実機

現本人用候補は **b55242230e93ec3975a5a49bf3dd5f46632ff794**、webtree `5cbbfe05a2971485b5c32a84a8ddf7b2539604cc`。mobile設定欄を69px短縮し320/390幅で完全表示券行を1行増やし、削除を含む44px target・320px間隔/最大金額表示・確認focus/scroll・短画面/更新保持を検証。CSSと既存geometryだけを変更し、元f723/f9e2を祖先に保つ。既存PR62証拠head8f916へ新Linux合成32PNGを同一byteで保管した。[合成証拠](https://github.com/haji84/RACE-AI/blob/8f916340f9287ae5d0379c15bf8791ff67313daf/docs/evidence/boat-ui-mobile-allocation-density-20261119/README.md)。

実Mac **44460086148/job135344475665** はSafari26.6で当日保存view/private loopback/AESを通過。feed revision477（予想件数ではない）・結果18・native P1 groups9・30cipher/239,433,121bytes・同一原本比較2を確認し、private session cleanupもtrue。plaintext endpoint0/外部browser要求0/実画面export0。[実private再生と失敗](evidence/boat-main3-actual-private-safari-and-synthetic-cleanup-hold-20261119.json)。

M3の合成capture終了失敗で元UI例外が隠れる問題は、主例外同一性と8固定cleanup項目を保持する修正をM121へ統合した。ただしM121実Mac **44467823700/job135369769829** は追加source-free fixtureの6subcase失敗でstep6停止し、private Safari/合成captureは全てSKIP・artifact0。実Mac修正成功は未確認。

実symlinkの一時rootで同6失敗を再現し、テスト出力先2箇所だけresolve()して意図したresize/open/capture境界へ入るよう修正した。通常172件と同alias下172件が成功、root関連210件/20.105秒も成功。原172methods/本番symlink guard/runtime/RPC/timeout/source/pinsは不変。元Macの実際のalias文字列は未記録なので断定しない。[再現と修正](evidence/boat-native-M121-temp-alias-test-fixture-fix-20261119.json)、[root最終検証](evidence/boat-native-M121-fixture-root-final-review-20261119.json)。

物理iPhone13Pro・本人login・直接GitHub feed配送・全8参考画面の最終受入は未確認。本人SafariでWINTICKET開催一覧が表示されたことをRACE-AI画面合格に置き換えない。接続された実機操作環境は無い。

## 4競技・競輪・映像の残件

| 完成条件 | 実確認と不足 |
| --- | --- |
| 全レース×適用可能な既存全モデル | sourceSのactive登録は既存15系統/30 sport-modelセル。4競技全日union・締切15〜10分前生成/保存/結果照合、AUTO実8試走値、JRA/NARの全5model適用は未実証。未提供sportを0件とするcurrent分母と空入力receiptのlocal修正はreview済みだがSへ未適用。 |
| 競輪403 | fe7実probe44437961180はHTTP403=1/429=0/UNKNOWN=0、新入力0。本人Safari/別client通常200とは別。公式SP calendarは73期間/42会場見出し/当日候補8、個race/締切/rosterはnull。既掲載JSの正規POST1回は500、本文未保存で原因不明。403解消・全347/437・当日全予想は未証明。 |
| 6艇識別・校正・予想接続 | 775frameを既存S/modelで実推論。6人物が同時に見える7frame/0.2秒のAI参照42を先に固定し、manualROIをモデルへ渡さず評価。幾何15/42・服色current正解2・6色同時0/7、ID遷移分母0。世界距離/速度/強さ/予想適格はfalse。 |
| 前向き精度改善 | 原サーバ証拠の実登録は成功。window open、適格matched0、所定期間/件数/不確実性未達。改善の証明はこれから。 |

競輪の新mainから除外済みKdreamsへ進めたsecondary入口は、既存4host/https/no-userinfo/443をRequest/open前に検証する修正で閉じた。381関連＋独立381＋禁止81/承認24 casesが成功。旧offline parser/NoRedirect/source flagsを保全し、実provider要求0。これを403解消とは扱わない。[独立review](evidence/keirin-approved-transport-guard-independent-review-20261119.json)、[SP正規navigationの実停止](evidence/keirin-calendar-normal-navigation-actual-stop-20261119.json)。並行PR309の17歴史結果/11月18日79cohortも当日の全国live intakeや新しい前向き改善へ加算しない。

映像ではgeneric PERSON候補が観客にも置かれ、元metadataもparent boat/identity/model eligibleをfalseにしていた。追加の同7frame観測は既定の戻り値を完全保持し26→25→16→15の対応を確認。global cap到達後の未訪問tailに9対象があるが、NMS拒否/uncapなら成功とは推定しない。source/閾値/cap/weights/GTは不変。短い選定後AI参照はhuman GT/全race連続ID/前向き精度ではない。[counts・hash・許諾](evidence/boat-six-rider-diagnostic-final-counts-hashes-license-20261119.json)。raw frame/journal/参照座標は非公開。

## 既存変更と次の検証

新PRを作らず、既存PR121の元metadataと11月10日28race A研究SHA receiptを保全して統合済み。次は既存PR106の元15filesをimmutable5b0f7ef/全Git ancestryで保持し、元32race SHA receipt1fileだけを現treeへ同一blobで採用する。raw JSON/予想/結果原本とUIはmainへ追加せず、元metadata/全mode/type/blob/URLを保存してfixture修正を載せる。元receiptはhuman heuristicでtrained modelではなく、元ZIP/予想原本は復元されていない。新しいmodel authorityや今の精度分母へ使わない。

[review済みlocal future patch](evidence/race-ai-reviewed-local-future-patches-20261119.json)は公式calendar partial parser・current分母None/0区別・空contextのAES receipt/不正path拒否。AUTO personal Bも完全8値・時計/SHA・未引退flag・締切前の既存B1入力へ接続するreview済みlocal修正を保管した。いずれも固定Sやstudyへ未適用で、実生成合格ではない。

次はfixture修正の最終CIと通常main統合、実Mac再確認、認証済cipher inventoryに基づく欠落160候補の安全な復旧可否を確認する。実確認できない残件は完成扱いにしない。
