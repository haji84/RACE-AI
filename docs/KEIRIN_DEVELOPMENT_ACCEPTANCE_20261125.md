# 選手詳細分析指示書との照合・引継ぎ（2026-11-25）

[2026年11月28日の予想精度・信頼度統合仕様](KEIRIN_PREDICTION_ACCURACY_CONFIDENCE_SPEC_20261128.md)を競輪の着順学習・可変点数・確率校正の受入に適用する。ここで記録する既存のデータ、研究と真正性の条件を引き継ぐ。

**引継ぎ済み。全体完成は未達。** [開発基準](KEIRIN_DETAILED_DEVELOPMENT_SPEC_20261125.md)を今後の要求として採用する。下表はコードの存在と実データ・本番受入を分けたものであり、既存の研究結果を再実施済みとするものではない。

**実装継続の最新記録：** [着順確率・比較・独立復号](KEIRIN_JOINT_FORECAST_CONTINUATION_20261125.md)。PR #330/#331をmainへ統合し、既存GitHub Pagesに選手詳細を反映。確認対象75レース516出走の確率を配信し、締切前10件と事後参考65件を分離。別ランナーで実原本10組を既存鍵から独立に復号した。既知期間3,201件の再現では三連単Top4が28.99%→29.58%だが、A3・L・9車等は改善せず、独立した未来での精度向上や全国完成とは判定しない。

**11月26日00時04分 JSTの追加実装：** PR #333/#334もmainへ統合。公開結果更新から固定原本の採点を起動し、10件すべてで三連単Top4は保存3→比較4、二車単Top2は両方3。少数例のため改善実証とはしない。現在登録2,416人の基礎カルテを生成し、2,393人・211,212着順を読戻した。11月25日の75件516人には46,028着順の期間別・直近履歴を、出走表SHAと公式番号を照合する別の締切後資料として追加。GitHub Pagesの14資産と暗号化配信を確認した。約14か月の確認範囲であり、全能力・全国自動更新の完成とは区別する。[実集計](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/basic-dossiers.json)・[履歴配信](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/rider-history-publication.json)・[実HTTP](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/rider-history-pages-live-readback.json)

PR #335のmain実行で、既存の所有者鍵を使う全国カルテ・名簿の独立実復元にも成功。将来の環境で参照できる暗号文・出典・検査CLIを保存した。過去時点の真正性や精度向上の判定とは分ける。[実復元の証拠](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/rider-dossier-independent-readback.json)

## 確認した基準点

- main：`2d4a87c43795af5aaaa966603c9e5a634fb67759`（PR #329 統合後）。
- 継承する [Draft PR #327](https://github.com/haji84/RACE-AI/pull/327)：`c058c3cf5640661244c8cbef8c21c387c03eca02`。既存376変更ファイルを保全し、今回の差分だけを積み増す。PR名は「docs」だが実際はコード・研究・証拠を含む。
- **監査中の更新を継承**：同PRが `345f0ac8af94237b03c281c4e288f3f0f3a4cc62` へ進み、[カルテ・確率・展開照合](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/KEIRIN_TACTICAL_DOSSIER_20261125.md)を追加した。今回の変更はそのHEAD上へ積み直した。重複した分類器は廃し、`keirin_form_fall_blind_pdca.compare_race_development` への件数集計アダプターに統一した。最終統合では `912947a3` の追加17変更（第34版の事後観測表示等）も保全した。以下の表はこの更新を含む。
- [既存引継ぎ](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/KEIRIN_RIDER_TRAITS_CODEX_HANDOFF_20261122.md)、`AGENTS.md`、最新状況、予想／結果スクリプト、画面コード、公開ファイルとCIの実行内容を確認。
- [定期run 45606639155](https://github.com/haji84/RACE-AI/actions/runs/45606639155) はsuccessだが、実logは `HOLD_OWNER_SOURCE_PARTIAL_NO_COMPLETE_PR71_INPUT`。当日一覧は8場75レース、詳細・選手確認・新予想は0、独立読戻しjobはskip。918応答HTTP200を全入力完了と解釈しない。
- 公開SiteとGitHub移植画面は異なる配信経路。公開Siteの当日ファイルは75レース、保存済み公開記録と現HTTPのSHAが一致。[今回の読戻し](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-spec-handoff-20261125/public-site-check.json)。これは全国のカルテ／全モデル／全着順確率の完成証明ではない。

## 指示書27節との対応

状態の「一部」は、該当部品・研究があることを表す。全国接続や精度改善まで検証済みという意味ではない。

| 節 | 現在あるもの／今回の実装 | 未達の受入証拠・次の作業 |
|---|---|---|
| 1 目的・正本 | RACE-AI、既存A/B・保存・結果・画面を継承 | 全体完成・全国自動運用は未達 |
| 2 西武園11R | 2媒体の5-3-1一致を今回確認。先行更新には公式・映像確認記録あり。会話参考を既存PDCAで再実行 | 会話の締切前原本、初周全体と正確な開始時刻の独立確認 |
| 3 詳細カルテ | 現在登録2,416人の基礎dossier、2,393人・211,212の数値着順、追加6能力の機会分母。現在級班と過去級班を分離 | 全国の戦術観測機会・成否の充足、自動更新。決まり手を戦術試行数にしない |
| 4 過去条件別 | 全収録・3年・1年・6/4/3/1か月、直近30/20/10/5走。会場・掲載ライン役割・級区分の交差集計を西武園と翌日分で確認 | 全指定条件の分布、小標本補正の検証・公開接続。全収録期間を生涯全履歴とみなさない |
| 5 直近内容 | `keirin_rider_form_evidence.py`、`HistoryBook.features`の長短期差 | 相手・展開・消耗を考慮した30/20/10/5走・開催別の内容評価 |
| 6 映像・イベント | `keirin_video_corpus.py`、`keirin_video_review.py`、checkpoint研究 | 全車連続の時系列イベント。全国映像の確認完了ではない |
| 7 反応 | H/B仮説、番手自力の局面経路 | 条件別反応の実観測、計測可能な反応時間と選択確率 |
| 8 多段階捲り | `keirin_rider_context.py`に複数段階分岐。先行更新は翌日68件を比較用に事前保存した記録 | 発生確率の校正、外回り消耗、全試行分母での前向き精度検証 |
| 9 単騎 | 既存のSOLO役割・基礎経路 | 戦術別自力・利用・切替・内外と相手条件を含む実履歴 |
| 10 番手・相性 | `keirin_rider_context.py`、連係／line-history／matchup研究 | 急加速・上捲り時の追走／千切れ／差し／自力を別々に予測・検証 |
| 11 コメント | 原文欄、自力方針の抽出、出典付き条件観測 | 発言時点管理と戦術選択の一致率、文脈による方針変更の接続 |
| 12 バンク | course/bank研究、役割×場の履歴 | 全場形状、位置別個人適性、左回り図・座標の実画面検査 |
| 13 気象 | 既存weather契約と研究試験 | 方位×風向×反時計回り×個人実績の接続。今回の風を未検証の耐性値へ変換しない |
| 14 評価分離 | 長期・直近・役割特徴の部品 | 指定の全分解評価、期間・標本・信頼度、当日評価との分離表示 |
| 15 六局面 | 既存`keirin_nationwide_auto_generator.py`と番手比較版 | 全車位置・条件付き多段階・イベントを含む動的分岐の全国接続 |
| 16 全着順確率 | `keirin_joint_finish.py`の同じ分布を保存・検査し、75件516出走の確率を既存閲覧権限の画面へ接続 | 締切後に補完した8件の次回の事前取得、全条件の校正、独立した未来の精度。整合性だけで改善としない |
| 17 戦術確率 | 研究用分岐支持、H/B/checkpointの学習部品 | 本物の戦術機会と失敗を含む分母、信頼区間、条件付き／無条件表示 |
| 18 カルテUI | 元Site第34版と既存原本を保持。PR #330でGitHub画面にも名前タップ・切替・全着順確率・出典を実装し、既存Pagesへ反映、14資産HTTP一致 | 条件別全詳細、全国の観測能力、iPhone実機。所有者ブラウザでの実鍵閲覧の今回の再確認は未実施 |
| 19 A/B/C | 旧版保存と比較CLI、C未生成を明示 | 新Bの全分析接続、旧A/Bを同時点で保存した公平な比較。研究版を自動昇格しない |
| 20 精度 | 既存研究を保持。今回の既知期間3,201件は固定B順位モデル928→947件、二車単Top2は1237→1240件。未来10件は原本固定後に既存採点へ接続 | 未来の複数開催日での独立比較、全区分の校正。過去期間の再利用とA3/L/9車等の非改善を明示 |
| 21 独立PDCA | **先行の既存PDCAを再利用し、今回forward-scoreへ任意の観測入力を接続**。締切後正規化の展開原本への流用を排除 | 凍結時点の展開入力と確認済み観測の定期供給、原因の検証。自動学習採用は未接続 |
| 22 カルテ更新 | 既存SQLite、日付付き履歴、映像review履歴 | 能力・全戦術・相性の差分と更新理由、時点復元、検証後の採用経路 |
| 23 真正性 | 同一入力の全確率10組を締切前にP-256/AES/Git保存し、別runnerが締切前SHA確認。PR #331で既存RSA鍵から元平文SHAを独立読戻し | 公式結果・実主催者締切の認証、全カルテ・展開を含む全国本番。事後作成の復旧コピーを新規事前予想にしない |
| 24 全国自動化 | discovery、GitHub定期処理、公開2媒体結果照合 | 全国対象／処理／未取得／保留の統一分母、全詳細カルテからPDCAまでの完走 |
| 25 開発順 | 現状確認後、既存採点へ最初の不足機能を実装 | 下記の次作業を順に実装・実データ比較する |
| 26 完成判定 | コード・研究・本番証拠を本表で分離 | 全国完成・前向き精度改善は未証明。CI合格を代用しない |
| 27 引継ぎ | 本書・要求整理・コード・テスト・実事例・出典SHAをGitHubへ保存 | 後続も実装／採点／採否／未達を更新する |

追加6能力（捲り抵抗、番手自力、並走持続、戦術切替、消耗後末脚、内外位置別）は[要求の第3節](KEIRIN_DETAILED_DEVELOPMENT_SPEC_20261125.md#追加必須能力)へ保存した。先行更新の`keirin_tactical_observations.py`は機会分母と未確認・矛盾を扱うが、全能力が全国で測定済みという意味ではない。UIに表示する未観測項目を架空のスコアで埋めない。

## 11月25日夜の再照合

- **確率の実データ採点**　既存の原本採点から、1〜3着・二車単・三連単のBrierと対数損失、三連単1・4・8点と二車単2点の確率帯別の実測頻度を本人用に計算できるようにした。11月25日23時27分時点の固定10件・照合済み9件で動作確認した。個別の確率が推測され得る件数の少ない区間もあるため、通常のActionsへの出力は従来の照合件数・的中数を使う。GitHub Pages移植版の本人用読戻しは75件で確認、元サイトの匿名表示と実機iPhoneの全確率表示は別に確認する。[実装・検証・取得時刻](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-joint-calibration-20261125/analysis.md)

- **締切前原本の独立復号・採点**　mainに統合された既存PR #331〜#333で、11月25日の研究比較Bの10レース・20予想について、別ランナーで復号し、元の入力・全着順分布・二車単・三連単を照合した。原本の暗号文と公開締切前に完了した最初のGitHub読戻しの証拠をそのまま参照する。23時12分の二元結果では7件を採点でき、三連単1・4・8点と二車単2点でいずれも両案2件が的中。23時27分の公開結果更新からは、同じ原本を復号して採点する既存GitHub Actionsが自動起動した。登録10件中9件を二元で採点し、結果待ちは1件。三連単1点は両案2件、4点・8点は両案3件、二車単2点は両案2件。公開結果の状態コミットと採点に使ったSHAも一致した。全国稼働、正式なPR71の本番予想、締切前の正式な展開原本および精度改善は要検証。[別ランナーの読戻し](https://github.com/haji84/RACE-AI/actions/runs/45627411872/job/139251409264)・[初回採点](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/verified-main-score-2312.json)・[自動再採点](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/verified-main-score-2327.json)・[実行ログ](https://github.com/haji84/RACE-AI/actions/runs/45634329984/job/139275865225)

- **戦術切り替えの実例**　2025年9月16日函館5Rの⑤市本隆司について、最終Hで④を追走し、HからBの間に外から動いて抜いたことを保存映像で照合した。選手登録番号と着順は別の掲載元で照合。確認時点より前の予想、対象レース自身、根拠のない入力には入らないことを検査した。観測できた1件の記録で、切り替えを試さなかった機会の網羅、加速値、成功確率は未確認。11月26日の84件に本人の出走はなく、当該資料を前向き精度へ加算しない。[映像の場面・採点境界](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-tactical-dossier-20261125/hakodate-5-tactical-switch.json)

- **カルテと追加6能力**　公開画面は既存第34版。選手名から75レース・延べ516出走のカルテを開ける。追加6能力は項目として表示し、西武園11Rの①・④・⑤には映像確認済みの動きを掲載した。捲り抵抗と内外の2項目は既存映像記録と公式着順を再照合した。内外の着順傾向は同じレースで複数回観測しても同じ側では1走として数え、着順が食い違うレースを集計から外す。番手自力、並走時の速度維持、戦術切替、消耗後の末脚の4項目は、この事例では数値を付けていない。全国のカルテへの観測追加と予想モデルへの接続は未達。[画面の確認](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-tactical-dossier-20261125/site-v34-verification.json)・[実データ再照合](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-tactical-dossier-20261125/seibuen-11-tactical-race-denominator.json)
- **全着順と精度**　同じ同時分布から1着から最下位までと二車単・三連単を算出し、選手画面の表示部品を既存PRへ追加した。元サイトの全着順確率の表示には未接続。保存済み資料で再構成した3,201件では三連単4点928→947件、8点1,298→1,323件、二車単2点1,237→1,240件。過去の再現から得た差であり、前向きの改善は未確認。[3,201件の採点](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-live-accuracy-closure-20261125/retrospective-score.json)
- **前向き成績**　22時12分の既存GitHub Actionsで25日の75件中64件を二元照合。24・25日合計で公開156件中143件を照合し、三連単1点12/143（8.4%）、4点37/143（25.9%）、8点58/143（40.6%）。8点のレース単位95%区間は32.9〜48.8%。日によって公開モデルが異なる。1・2着の組を補正した事前固定試験では11件中4件を照合し、4点・8点とも両案2件。比較Bの改善と全国95%は未達。[定期処理の既存ワークフローによる更新](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-rider-variation-20261125/native-result-2212.json)・[二日分の採点](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-rider-variation-20261125/two-day-2212.json)・[補正の採点](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-rider-variation-20261125/pair-study-live-2212.json)
- **GitHub移植画面**　PR #330 がmain `cc5009c6` に統合された。予想原本と車番、情報取得時刻、締切に結び付く比較用の着順確率を、GitHub移植版のカルテが表示できる。既存ドロップダウン、選手切替、戻るフォーカスをブラウザ検査で確認した。元サイトにおける実データ確率の表示とiPhone実機は未確認。[統合された変更](https://github.com/haji84/RACE-AI/pull/330)
- **本人用の結果照合**　既存GitHub Actionsの暗号化履歴から三連単を読み戻し、公式資料で出走車番・締切・着順を確認して、同じ1・4・8点で採点する経路を追加した。11月25日分は4パケット・2媒体一致53件の読み戻しと、西武園11Rの公式資料との照合を確認した。翌日の全84件は結果待ち。この比較の定期実行は未確認。[手順と実結果](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-note-cohort-20261125/analysis.md)
- **今後の実レース**　11月26日8場84件で、静的・掲載並び・6局面の比較版・1/2着の組の補正・選手の過去着順のばらつき補正の対象と締切を照合した。事前の掲載並びが2資料で一致した61件は、結果の二元確認後に同線・別線でも集計できる。84件はすべて前日固定で、締切15〜10分前に固定した比較は別途必要。結果はまだ採点していない。[84件の比較監査](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-rider-variation-20261125/nov26-five-arm-audit.json)
- **映像の追加観測**　別ラインが勝った旧レース5件を学習用に抽出し、通常再生と公式のB・着順を照合した。別ラインへの先頭交代は4角までが1件、4角出口からゴールまでが4件。結果を使って選んだ5件のため、交代の発生率と前向き精度の分母には加えない。[映像観測の集計](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-rider-variation-20261125/video-cross-line-enriched.json)

## 西武園11Rの実照合

- [結果チェック](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-spec-handoff-20261125/seibuen11-result-check.json)：既存parserでKドリームスとnetkeirinの5-3-1、三連単100円840円が一致。**主催者公式結果の認証ではない。** 公式時刻・映像による展開は未認証。
- [会話由来の参考事例](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-spec-handoff-20261125/seibuen11-conversation-reference.json)：ユーザーが記録した初周、打鐘前、④→①→⑤の捲り、⑥と③の追走を出典別に保持。実測していない距離・速度・時刻は追加していない。
- [実行結果](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-spec-handoff-20261125/seibuen11-reference-evaluation.json)：着順参照一致、ユーザー観察に基づく参考B。参考scopeなので正式gradeはnull、**正式な締切前成績への加算0件。** 公開原本の展開Eは[先行の別記録](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-tactical-dossier-20261125/seibuen-11-assessment.json)にある。初周の全順序と全仕掛けの事前原本は無く、不足を後付けしない。
- 当日の公開済みファイルは以前の公開記録のSHAと一致。公開データには六局面原本はなく、5-3-1は第1候補ではなく上位4候補内。[読戻し証拠](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-spec-handoff-20261125/public-site-check.json)。会話の「本命5-3-1」の原本と同一だと仮定しない。
- 最初のKdreams検索URLの `pageType=showResult` は既存の厳格URL validator対象外だったため、公開されたクエリなしの正規詳細URLで照合した。URL制約は変更していない。取得本文は私用一時領域だけに保持し、GitHubへ保存していない。
- 監査中に継承した別作業の記録には、主催者資料と映像で打鐘前②および④→①→⑤を確認したとある。[確認者の記録](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/KEIRIN_TACTICAL_DOSSIER_20261125.md#最初の実データ検証)を保持する。今回の監査者自身が映像を再視聴したとは報告せず、出典を混ぜない。

再実行（既存ファイルを書換えず標準出力へ参考判定のみ）：

```bash
python - <<'PY'
import json
from pathlib import Path
from race_ai.keirin_form_fall_blind_pdca import compare_race_development
p = Path('docs/evidence/keirin-spec-handoff-20261125')
c = json.loads((p/'seibuen11-conversation-reference.json').read_text())
r = json.loads((p/'seibuen11-result-check.json').read_text())
print(compare_race_development(race_id=c['race_id'], starters=c['starters'], forecast=c['forecast'],
    order=dict(race_id=c['race_id'], winning_triples=[r['winning_triple']]), observations=c['observations'],
    verify_forecast=lambda _:False, verify_order=lambda _:r['state']=='SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL',
    verify_observation=lambda _:False))
PY
```

## 今回追加した独立採点の契約

`race_ai/keirin_flow_evaluation.py` は**分類器ではなく、既存 `keirin_form_fall_blind_pdca.compare_race_development` を呼ぶ件数集計アダプター**とし、`scripts/keirin_forward_score.py` に接続した。旧引数での返り値は変えず、観測を指定した場合だけ `flow_evaluation` を追加する。今回の差分は予想配列、重み、原本、モデル採用、定期運用、公開Siteを変更しない。

```bash
python -m scripts.keirin_forward_score \
  --predictions /private/frozen-predictions.json --receipt /private/original-receipt.json \
  --roster /private/registered-roster.json --results /private/results.json \
  --flow-observations /private/flow-observations.json
```

観測envelopeのschemaは `KEIRIN_FLOW_OBSERVATIONS_V1`、`forecast_sha256` は予想ファイルの実バイトSHA、`recorded_at` は観測集合を保存した実日時、`races` は登録済みrace_idとobservationsの配列。観測集合へ未登録レースを足せない。

元予想に `flow: {published: {...}, trial: {...}}` が既に保存されている場合だけ比較する。各側は既存PDCAの `INITIAL/BELL/FINAL_HOME/FINAL_BACK/FOURTH_CORNER` の順序（前方の部分列も可）、`INITIATIVE`、`ATTACK_ORDER` の必要な範囲を保持する。前受け1車はINITIALの部分列として同じ照合領域に置く。主導権を車列先頭から自動推定せず、複数シナリオから事後に的中経路を選ばない。

各観測は既存PDCAの `race_id`, `aspect`, `observed`, `complete`, `source`, `receipt` を使う。sourceはvideo / official / article / user / estimate。アダプターのreceiptは `reference`, `recorded_at`, `sha256`。最初の3種は作成者の出典確認を前提とし、**この採点部品自身はURLを取得せず出典の真正性を独立認証しない**。SHAがあることだけで実映像や公式記録の正しさを証明しない。ユーザー観察は参考のみ、AI推定は実観測の採点に入れない。

- 着順は既存の登録・締切・SHA・結果チェックを通った対象だけ採点する。結果保留なら展開の比較件数は出すがA〜Eの分類へ加算しない。
- 全体一致A/Cは既存PDCAのゴール以外の5局面・主導権・完全な仕掛け列を全て確認できた場合のみ。部分一致はE。独立確認された一つの明確な不一致でB/Dは判定可能。
- 観測の無い局面は一致率分母に足さない。完全な仕掛け列とそれに整合する部分列は一つの照合にまとめ、相反する観測は保留する。別々の独立分類器を持たない。
- 出典・集合の時刻不整合、未出走車、車番重複、GOALを展開観測へ流用する入力、不正SHAを拒否する。
- `normalized_at` が締切後の予想ファイルは、元の買い目freeze時刻が古くても展開A〜Eの分母へ入れない。元バイトとの独立照合機能がないため、安全側に `origin_not_admitted` とする。旧来の着順採点は継続する。時計はreceiptの申告であり、別runnerやサーバ時刻の独立証拠をこの部品自身が作るわけではない。
- 返り値は件数と分類・分母のみ。元の買い目・選手順序・本文を出力しない。

この接続は**任意の観測ファイルを渡して動く採点機能**までであり、凍結時のflow自動作成、レース後の観測自動収集、カルテ更新、本番自動PDCAは未接続。

## 精度についての引継ぎ

今回の[検証記録](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-spec-handoff-20261125/validation.md)：最終の関連203検査は成功。広範囲1,549検査では既存pin不足7件・ブラウザ不足1件のエラーと、umaskに依存する合成fixtureの失敗があった。fixtureを修正して9件を再検証した。全体試験を合格と扱わない。

[既存20:08記録](https://github.com/haji84/RACE-AI/blob/6b30e6368216519cb55232f417462caffc6c57f6/docs/evidence/keirin-95-continue-20261125/checkpoint-2008.md)は2媒体一致51件で三連単上位4＝16/51、上位8＝26/51、掲載点数＝19/51。これらは継承した特定時点の記録であり、今回再採点した全国成績ではない。今回の変更により着順精度が上がったとは主張しない。複数の試験案を同じ結果で選ぶことと、未使用の未来期間で効果を確認することを分ける。95%等の旧研究目標も完成の代用品にしない。

## 次に実行する作業

1. 先行更新のカルテ・全着順同時分布・追加6能力・多段階分岐を再利用し、未観測条件と信頼区間を維持して全国のデータ充足を進める。別実装を作らない。
2. 11月26日分の比較展開・予想が保存された先行記録と、実際の原本・独立読戻し・結果・映像観測を照合する。既存原本へ追加flowを追記しない。
3. 正規化後の研究ファイルしかない場合、元のflow-bearing原本の別runner認証が未接続なので展開は保留とする。着順だけでも進める。
4. 実装・配備済みの全着順確率とGitHubカルテUIを土台に、欠測、コメント・バンク・気象接続、定期PDCAを進める。モデル採用と三連単・二車単の改善判定は未使用未来レースで行う。

先行資料にある私有333ファイル、複数年SQLite、映像、モデル重み一式は、この環境で全復元・再検証したとは主張しない。公開されたハッシュや集計だけから非公開の原本を作り直さない。Actions Secretを出力・移転したり、既存運用のモデルpinを変更したりしない。
