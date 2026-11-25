# 選手詳細・着順確率・実データ比較の継続記録

27節の[開発指示書](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/KEIRIN_DETAILED_DEVELOPMENT_SPEC_20261125.md)を継続する。**全国の全仕様完成、未来レースでの統計的な精度向上は未達**。今回、比較モデルの固定、整合する確率の画面表示、実原本の独立復号を実装し、既存の採点へ接続した。

## main と実配信

- [PR #330](https://github.com/haji84/RACE-AI/pull/330)を検査・独立レビュー後にmainへ統合。選手名から詳細、選手切替、全着順確率、2/3着以内、期待着順、資料の時点を表示する。比較Bの資料と保存出走表を分け、未知の能力を架空のスコアで補完しない。
- [PR #334](https://github.com/haji84/RACE-AI/pull/334)で期間別・直近走別の着順履歴を追加。main `ebc22ed82a03edad6eec1f90e31b4c31906bcb76`、Pages `681edf78d15b6c33033bee6b9d129553ccc6f4fd`で14資産を実HTTP照合した。独立レビュー、関連Node65件、Chromium5件とPython note6件が成功。[配備](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/rider-history-pages-publication.json)・[HTTP照合](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/rider-history-pages-live-readback.json)
- 全確率は既存 `JointFinish` の一つの同時分布から導出。上位8候補を100％に再正規化しない。全員完走・同着なしの条件付き、未校正の研究予測と明示する。旧A/B・C方針や本番重みの変更は行っていない。
- 同一レース、全車、氏名、既知の登録番号、入力の実バイトSHA、資料SHA、生成・取得・締切の時点を照合する。不一致は保留。Pythonの `80.0` をブラウザで `80` に変換してハッシュを変えないよう、保存JSONの該当部分を構造に沿って取得する。
- [GitHub Pages](https://haji84.github.io/RACE-AI/)の既存app/styleへ組込み、公開元の14資産をHTTPで読戻した。既存暗号原本・BOAT表示・asset範囲を保全。所有者の既存閲覧用capabilityを使う。[配備](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/pages-publication.json)・[HTTP確認](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/pages-live-readback.json)。新たなCloudflare/Vercel・鍵・課金・バックエンドは導入していない。

## 過去比較

公開GitHubの固定版からSQLite2件を取得し、Git blob、SHA256、読み取り専用DB検査を行った。生データの再配布許諾は確認できないため、平文は私用領域だけに保持する。

- `sumidatadayoshi/keirin-data@2a1260fb0940ad11160b56a36f9c24cc4fb2f6d2` の `keirin.db` と `keirin_2026q4.db`。2025年10月1日〜2026年11月22日の30,713件を検査。3年分を取得したという意味ではない。
- 欠場、競り、完全着順不足、特殊結果、掲載並び不足等を保留し、26,656件を採用。既に分析した豊橋 `202611224506` は事前指定で除外。全員の競走得点が不足する19件も結果に依存せず保留した。[採用と欠損](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/archive-admission.json)
- 学習20,649件は2026年7月まで、候補の選択2,787件は8〜9月。そこで残差比較 `all_96` を固定し、その後は再選択・再学習せず10〜11月の3,201件を採点した。従来の保存順位モデルに既存の条件付き残差学習を追加した比較で、公開Siteの買い目原本そのものを再現した比較ではない。
- この10〜11月期間とモデル系列は先行研究でも既に調べられている。**未使用・独立の評価期間とは呼ばず、既知期間の時系列再現**とする。掲載当時の入力公開時刻の独立証明もない。

| 指標（3,201件、同一入力・同一点数） | 保存B順位モデル | 比較B |
| --- | ---: | ---: |
| 三連単Top1 | 401 / 12.53% | 428 / 13.37% |
| 三連単Top4 | 928 / 28.99% | 947 / 29.58% |
| 三連単Top8 | 1,298 / 40.55% | 1,323 / 41.33% |
| 二車単Top2 | 1,237 / 38.64% | 1,240 / 38.74% |
| 三連単Log Loss（小さいほど良い） | 4.13687 | 4.10483 |
| 三連単Brier（小さいほど良い） | 0.95868 | 0.95641 |

48日を単位とした対応付きbootstrapで、Top4差は+0.594ポイント、95％範囲は+0.062〜+1.142ポイント。二車単Top2差の範囲は−0.442〜+0.590ポイントでゼロをまたぐ。全体を独立した未来での改善と判定しない。[全実測値](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/retrospective-score.json)

| 区分 | 件数 | 三連単Top4 保存→比較 |
| --- | ---: | ---: |
| A級1・2班 | 1,382 | 27.42% → 28.58% |
| S級 | 887 | 24.92% → 25.48% |
| A級3班 | 657 | 36.38% → 36.23% |
| L級 | 275 | 32.36% → 32.00% |
| 9車 | 258 | 24.03% → 23.26% |

A級3班・L級・9車等は改善していない。区分を見て今回のモデルを選び直していない。本番へ一律採用しない。[全区分・欠損・不確実性](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/retrospective-subgroups.json)

## 未来の10レース

11月25日12:57 UTCに、未締切の10件をKdreamsの通常公開ページから取得。全70人の氏名・車番、掲載級班・印・率・並びを確認した。登録番号を推測で作らず、未取得はnullとした。現在の結果を予想入力へ追加していない。

12:59:58 UTCに旧版と比較版の完全な同時分布を同じ入力で生成し、既存の所有者P-256宛てに暗号化、既存の `state/keirin-note-view` に保存。13:00:10 UTCにGit読戻し、別Actionsランナーが13:03:07 UTCに暗号文SHAを確認した。最早掲載締切は13:04 UTC。元の暗号文は変更していない。

- 原本：`54f713d386b936f2c0f8a494fa12fc68d67d2a05:views/e12d24ead30bef9f228cf22e6c47f2765a1d043c2a6c12673c1ed87f01bc8b51.json`
- [事前固定](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/prospective-publication.json)・[締切前の別runner](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/independent-runner-readback.json)
- 完全な入力、モデル、取得資料とソースコードも暗号化原本内に保全。新しい評価で保存済みモデルが変わらないよう、モデルSHA、6ソース、13依存ファイル、3学習段階、期間、候補の定義、依存ライブラリ版を検証する別CLIを追加した。保存モデルの再検査で3,201件の全実測値・日別不確実性が元の結果と一致した。[固定版検証](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/frozen-runtime-verification.json)

[PR #331](https://github.com/haji84/RACE-AI/pull/331)で、同一原本を既存の所有者RSA鍵でも独立に読める復旧コピーと検査を接続した。新しいコピーの作成時刻は13:26 UTCであり、新たな締切前予想として加算しない。元P-256の暗号文・header・index・過去Actionsの成功時刻と実行時のreceiptを結び、同じ平文SHAであることを確認する。

[本番run 45626363042](https://github.com/haji84/RACE-AI/actions/runs/45626363042)の専用ランナーは、既存の所有者鍵での復号と検査に成功。これは合成テストの成功とは別の実原本の読戻しである。公式結果・実主催者締切の独立認証やPR71モデル採用とは区別する。復旧コピーは既存 `state/keirin-encrypted-history` の研究専用パスに保持し、公式結果の履歴へ混入させない。[復旧コピーの参照](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/joint-original-rsa-recovery.json)・[実鍵での独立読戻し](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/independent-plaintext-readback.json)

## 結果更新後の自動採点

[PR #333](https://github.com/haji84/RACE-AI/pull/333)をmainへ統合。既存の公開結果更新workflowが完了すると、同じ暗号原本を既存鍵で再検証し、同じGit commitの出走表・結果へ照合する。取得側が一部失敗しても保存済み確認部分を使い、未取得は保留する。新しい源泉取得や権限変更、重みの採用はない。自動対象は今回の固定10件で、全国全レースの新B自動生成まで完了したという意味ではない。自動実行は最終掲載締切から6時間までに限定し、後日の手動監査は維持する。

[main統合後run 45633700634](https://github.com/haji84/RACE-AI/actions/runs/45633700634)で復号から採点まで成功。さらに[結果更新による自動実行45634329984](https://github.com/haji84/RACE-AI/actions/runs/45634329984)でも完走した（`workflow_run`）。最終の[run 45636908765](https://github.com/haji84/RACE-AI/actions/runs/45636908765)では10件すべてを2媒体一致結果に照合し、三連単Top4は保存B3件→比較B4件、二車単Top2は両モデル3件だった。10件の1件増加は統計的な改善の証明としない。最初の取得確認は復号前に停止したが、同じ不変資料・同じ結果commitでの再読取りと再実行は成功。最初のHTTP応答と停止対象は当時のエラーに含まれず原因不明であり、推測で確定しない。[実行結果](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/automatic-forward-score.json)・[自動起動の証拠](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/automatic-trigger-proof.json)は件数・SHA・取得元commitだけを保存し、原本・氏名・買い目・確率・鍵を公開しない。展開原本不足、実主催者締切未認証、公式結果未認証を独立して明示する。

[PR #336](https://github.com/haji84/RACE-AI/pull/336)で停止工程・HTTP状態を記録し、指定した一時障害だけ一度再試行する既存修正を本番へ反映した。その後run `45642996407` はGitHubの `witness_jobs` 取得でHTTP403となり、1試行で鍵を使う前に停止。詳細な原因は不明のまま保全する。[PR #337](https://github.com/haji84/RACE-AI/pull/337)では新しい権限を追加せず、既存の `contents:read` 標準トークンを正本repoのGitHub APIだけに使用した。rawホストへトークンを送らず、403の再試行や匿名フォールバックもしない。PRの実API確認はHTTP200で成功し、main `31469b4cb289fbaa6cc2acfe0fb39d801be396d2` の[run 45644494222](https://github.com/haji84/RACE-AI/actions/runs/45644494222)でも同じ原本の実復号・10件の採点が成功した。

さらに既存の公開結果更新 `45645160915` を受けた[自動run 45645265780](https://github.com/haji84/RACE-AI/actions/runs/45645265780)も実復号から10件すべての採点まで成功。Top4は3→4、Top2は両方3のまま。新しい予想を作ったり結果で原本を書き換えた証拠ではなく、同じ原本を読む実行経路の確認である。[障害と認証確認](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/github-readback-auth-recovery.json)・[認証後の自動採点](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/authenticated-automatic-forward-score.json)

## 当日画面と採点

当日登録75件のうち、10件は上記の締切前原本、別の57件は締切後に作った参考解析として区別して配信した。不足していた8件52出走は、Kdreamsの掲載並びを締切後13:53 UTCに取得して参考表示だけを補った。確認対象75件516出走の全確率・入力SHAを既存の画面モデルで検証。締切前10件、事後再現57件、締切後取得資料による参考8件を分け、65件を締切前実績へ加算しない。[配信件数](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/day-display-publication.json)・[不足8件の補完](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/recovered-eight-display.json)・[実データの読込](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/display-readback.json)

`scripts/keirin_joint_forward_score.py` は新しいPDCA分類器ではない。実原本・外部SHA・同一入力・時刻・登録範囲を検査し、固定4点を既存 `keirin_forward_score.score` へ渡す。同じ同時分布で二車単2点と三連単1/4/8点を照合する。照合用への変換時刻は実際の現在時刻とし、事後変換ファイルを締切前原本と偽らない。

13:43 UTC取得の2媒体一致結果では、10件中4件を照合し、三連単4点・二車単2点はどちらのモデルも2件。他は結果待ち。保存済みの展開原本がないため展開の一致を加算しない。[途中の採点](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/forward-score-1350.json)・[同一原本の復号との接続](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/live-chain-progress.json)。少数の的中・不的中で重みを変更しない。

## 次の継続作業と未達

全国の現在登録名簿246ページ・10区分を通常取得し、2,416の公式登録番号を確認した。既存 `IdentityIndex` と `HistoryBook` を使い、2,416人の基礎カルテを生成・私用領域で読戻し。2,393人に211,212件の数値着順があり、23人は観測着順なし。取得範囲は約14か月で、完全な3年分ではない。4,421件の名寄せ不足、2,718件の事故等・非数値着順、178件の結果不足を分けて保持する。今回取得した登録級班と過去走の級班を分離し、登録名簿を過去時点の入力として認証しない。[名簿の検証](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/official-registry-verification.json)・[カルテの実集計](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/basic-dossiers.json)

全カルテ、登録名簿、通常取得資料・出典・生成コードの339ファイル（展開42,401,836バイト）を既存所有者宛ての暗号化履歴へ保全した。表示用3資料は75件516人を含み、締切前実績の増分は0。生資料・カルテの平文を公開Gitへ追加していない。[暗号化保管と表示配信](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/rider-history-publication.json)

[PR #335](https://github.com/haji84/RACE-AI/pull/335)を通常保護mergeし、[本番run 45641179956](https://github.com/haji84/RACE-AI/actions/runs/45641179956)で既存の所有者RSA鍵からカルテと名簿を別runnerへ実復元した。2ファイルの実SHA、全登録番号、取得時点、2,416人／履歴あり2,393人／211,212着順を確認。平文はrunner私用0700領域の0600ファイルで、公開artifactは件数とSHAだけ。新しい鍵・権限・保存先サービスは使っていない。これは実際の所有者鍵を使う復元であり、合成テストやローカルの復号代替とは区別する。[暗号文の参照](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/rider-dossier-recovery.json)・[独立実復元](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/rider-dossier-independent-readback.json)

当日75レース516人も、保存した出走表と新しい掲載資料の氏名・車番・期別・府県を照合して公式番号へ結んだ。元の出走表の実バイトSHAへ結ぶ別の履歴資料を作り、全期間・3年・1年・6/4/3/1か月と直近30/20/10/5走を既存集計から表示できる。516人・46,028着順で画面モデルと保存予想不変を検査した。すべて締切後の資料であり、締切前予想の入力や実績へ追加しない。観測走数と欠損・取得時点を示し、実績率を今回の予測確率や能力値として扱わない。[生成と欠損](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/rider-history-build.json)・[実データの表示検査](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/rider-history-display-readback.json)

1. 固定した未来10件と、先行作業で固定された11月26日の比較群を、同一入力と点数で継続採点する。新しい情報で元の予想を書き換えず、公開旧Bと今回の順位比較を混同しない。
2. 締切後に補った8件を次回は締切前に収集し、独立取得できない登録番号・履歴・コメントを項目別に補う。長期能力と直近の調子、全戦術の試行分母、映像の連続イベント、バンク・気象・連係への接続は全条件で完成していない。
3. 着順と展開の採点、履歴更新、改善候補の採否までの全国定期運転は未達。今回の未来原本に存在しない展開を事後追加しない。未知の原因は原因候補として扱う。
4. 独立した複数開催日でのTop4／Top2・校正・区分別有効性を確認してから採用を判断する。今回の全国基礎カルテの取得元は約14か月の2DBで、先行作業の3年履歴や333ファイル復元の記録とは別。全期間の完全性を今回の集計で証明しない。

再実行では平文・鍵を公開Gitへ入れない。保存済みモデルを読み込む入口は `scripts.keirin_frozen_accuracy_study` とする。モデルSHAは外部receiptに固定し、評価済み出力へ上書きしない。旧ドライバを直接呼ぶ低水準APIだけで固定版の真正性を主張しない。main保護、旧予想、暗号原本と別runner、Cloudflare/Vercel禁止を継承する。
