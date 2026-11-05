# 艇愛DB履歴接続（2026-11-05 UTC、研究境界）

**全体未完成。** 実APIの限定取得・形式解析・公式K照合を実施し、既存モデル用アダプターを追加した。本番予想への自動供給、正式バックテスト、未来レース検証、学習、本番運用の成功を意味しない。

データ提供：**[艇愛ボートレースDB](https://boatrace-db.jp/)**。源流はBOAT RACEオフィシャルの配布ファイル。API原文、個々の選手・レースの全データ、予想原本は本変更に含めない。

## 調査したブランチと既存機能

調査開始時PR71 HEAD: `0b400636041f435754d8d6c0c2c48ef7faaf6ab4`。baseは `codex/actions-four-sport-e2e` (PR69、HEAD `bca59ebc5c7174e79d2dba027a97890f5d0d3d1f`) でありmainではない。mainとの差分は既存760ファイル、79,130追加/6,559削除。今回これらをmainへ一括統合しない。関連PR64 `761247bee0209e37b1af6b8885e92cad3e9260a5`、PR72 `7a432e5acc4d3495a0e82bd79726929e2f8085fe` は既存CI同様に固定参照する。作業開始時の別ブランチ `work` の未統合変更は持ち込まない。作業元AGENTS.mdのCloudflare/Vercel禁止・GitHub限定・暗号化・原本保全の制約は引き続き適用。

|既存ファイル|既存処理と今回の扱い|
|---|---|
|`boat_racer_tendencies.py`|厳格な6艇通常結果からコース、枠→実進入、勝者決まり手、内側敗戦代理指標、10/30走を集計。意図・直接被まくりは断定しない。変更しない。|
|`boat_tactical_scenarios.py`|全6人の公式履歴receipt・場別資料を要求。艇愛だけで公式receiptを捏造しない。|
|`boat_feature_adapter.py`|用途別承認、5〜30走、モーター、展示、気象の全特徴量を要求。欠測を埋めて接続しない。|
|`boat_entry_source_collection.py`|前日公式B/Kペア取得とREADY/WAITING_PUBLICATIONキャッシュ。新API用と混同しない。|
|`boat_historical_result_roster.py`|締切前C-lite原本6人と後日公式結果の一致検証。既存原本経路維持。|
|`boat_multi_feature_models.py`|全特徴量を必須とする既存2モデル。入力不足は保留、係数不変。|
|`boat_observed_pairwise_models.py`|欠測理由・出走母数・history window・用途承認を保持する既存2モデル。今回の直接接続先。|
|`boat_k_day_methods.py`|公式Kの決まり手を解析。照合器で再利用。|
|`existing_model_dispatch.py`|既存A/B、C-lite、tactical、full、observed、4競技共通モデルを契約別にdispatch。新モデル追加なし。|
|`observed_result_history.py`|既存の実測履歴平均、F/L/欠測母数、window識別子の算出を再利用。|
|PR64 `core.py`, `official_lzh_extract.py`|公式K固定幅データ・LZH安全展開・内部日付検証を再利用。|
|`permissioned_source_delivery.py`|独立署名された用途別PermissionPolicyとリダイレクト拒否。許可の自己申告を実権利と扱わない。|
|`source_retry_policy.py`|429/Retry-After、403、通信失敗の待機判定を再利用。|

既存の結果照合・PDCAは `boat_ab_result_audit.py`、`boat_shadow_result_audit.py`、`frozen_day_cycle.py`、`github_existing_cycle.py` の原本・receipt読戻し経路を維持する。艇愛履歴から結果や予想の原本を上書きしない。

## 提供元一次資料と用途判断

2026-11-05 16:47〜16:49 UTCにHTTPSで直接確認した。

- [データ・API仕様](https://boatrace-db.jp/about/data/#api): 「認証やAPIキーは不要です。個人利用・研究用途はご自由にどうぞ。」
- [利用条件](https://boatrace-db.jp/about/rules/): 「機械的にデータを使いたい場合はJSON APIをお使いください。」短時間の大量ページ取得は避ける。
- API資料: 「取得は1日数回まで」「取得したものを保存して表示」「APIの内容をそのまま第三者に再配布することはご遠慮ください」「項目は予告なく変わることがあります」「数字は主催者発表と照合」。表示には提供元名とリンクを近接表示。
- 集計値は出典名・URLとともに記事/SNS/個人研究で利用可能。商用一般、モデル学習、長期保管の包括的許諾は確認できない。今回それらを実行しない。
- 個人研究の限定取得・短期非公開キャッシュ・照合・記述統計を対象とする。研究目的の既存モデル入力契約を検証するが、取得許可を全用途の許可に拡張しない。
- 全文転載を避け、確認した文言・URL・SHAのみ保存。ページ全体のSHAは動的な最終取込時刻等でも変わる。SHAは保存した内容の識別子であって独立公表時刻証明ではない。

|確認資料|HTML SHA-256|
|---|---|
|`/about/data/`|`7503068a00719468ce38d8e806fb635c806a66b8ab28653eee1014c1d7dbd886`|
|`/about/rules/`|`27466ada50cdc9b7ac01068f093cfb41f4ffbcff6e9b37d74795004e8e8775f3`|
|公式download.html|`56dc43cc2775fac6ff036216d134700b78c5c742108c18dd3324bbe4b4851f0c`|

## API一覧（末尾 `/` が必要）

|API|形式・指定|今回の実取得|
|---|---|---|
|`/api/meta/`|JSON、収録初日・最終日・レース数・更新時刻|資料調査のみ|
|`/api/highpayoff/YYYYMMDD/?limit=5`|JSON、limit 1〜50|資料調査のみ|
|`/api/today/?date=YYYYMMDD`|JSON、開催場・前月末まで12か月のコース成績|資料調査のみ。過去日付指定が当時値を保証するとは解釈しない|
|`/api/stadium/NN/course/`|JSON、場コード01〜24|資料調査のみ|
|`/api/race/YYYYMMDD/NN/R/`|JSON、source/race/day/entries/payouts|20261101/13/10 1件|
|`/api/racer/NNNN/`|JSON、source/racer/stats|4444 1件|
|`/api/racer/NNNN/results/`|UTF-8 BOM CSV、全出走|4444 1件、4,470行|
|`/api/rank/next/`|CSV、来期適用勝率|資料調査のみ|

収録範囲の資料表示: 1997-05-01〜2026-11-05。結果速報は終了後概ね5〜10分、8〜23時JSTに5分おき確認。夜22:30〜翌04時過ぎに直近3日を公式Kで上書き、通常06時JSTまで完了。これらは提供元の更新説明でありRACE-AIで実測した遅延値ではない。公表時刻や訂正版をAPIレスポンスで独立に復元できる保証は確認できない。

## 実際の項目と欠測

履歴CSVの正確なヘッダー:

`日付,場,R,レース,開催,グレード(推定),艇番,コース,ST,ST記号,着,結果記号,決まり手,展示,モーター,ボート,タイム`

CSVには登録番号が無い。要求URLに結び付けた登録番号は暫定値であり、選手JSONと公式Kの同日・場・R・艇番の登録番号照合を経る。CSVには場名のみのため、公式24場の固定対応でコードを正規化。レースIDは `YYYYMMDD-JJ-RR`。日付/R/範囲/重複を検査。

選手JSONで登録番号、氏名、カナ、支部、級別、生年月日、登録期等を確認。レースJSONでは年齢、全国/当地勝率・2連率、モーター/ボート番号・2連率、展示、実進入、ST、結果記号、着順、払戻等を確認。氏名等はJSONとして読めるが既存モデルへ自動追加しない。現在の選手通算statsを過去の予想へ渡さない。全国/当地3連率は取得したレース項目に無く、推測補完しない。

異常結果: `F,L0,L1,K0,K1,S0,S1,S2`、空欄と`00`を区別して保持。実データのFは負のST値だったため `raw_st` に保持し、通常ST平均から除外する。空欄は0ではない。未知の記号は形式エラー。内容の異なる重複レースは隔離し、その選手のモデル入力を停止する（窓から消して古い走で補わない）。1着同着はJSONの同順位を保持し特殊結果扱いとする。転覆・返還などの原因をS記号だけから詳細断定しない。CSVの決まり手は本人勝利時だけで、敗戦時の勝者決まり手は埋めない。未知の決まり手原文（実データには「つけまい」）は保持し、既知分類へ勝手に変換しない。

## 実データの照合結果

[機械可読の件数・SHA証拠](evidence/2026-11-05/teiai-history-counts.json)。ローカル実データを使い、`python -m scripts.teiai_history_probe` で生成。原文は公開していない。

- 実取得: CSV 542,561 bytes、4,470行、重複0、競合重複0。2007-05-17〜2026-11-05。
- 選手JSONの登録番号4444一致。CSVの全4,470行の登録番号を公式確認済みという意味ではない。
- 公式[配布入口](https://www.boatrace.jp/owpc/pc/extra/data/download.html)から案内された `www1.mbrace.or.jp/od2/K/202611/k261101.lzh` とB同日ファイルを限定取得。Kの1,008行を既存解析器で解析。
- レースJSON: 1レース6艇、日付・場・R・登録番号・艇番・コース・ST・確定着順・勝者決まり手を照合。49非欠測フィールド比較、6行一致、不一致0、欠測0。
- CSV: 選手4444の同日2走、17フィールド比較、2行一致、不一致0、欠測0。
- 合わせて **2レース・延べ8行・重複を除く7出走**。レースJSONとCSVの共通1走を二重に独立標本と数えない。
- 払戻: 単勝/複勝/2連単/2連複/拡連複/3連単/3連複の10組番すべて一致、欠測0・不一致0。途中実装の2項目のみ照合から全10項目へ拡張し再実行済み。
- 当該照合標本の不一致率0%。全データ精度100%の主張はしない。履歴の残り4,468行は当該公式日ファイルの対象外で未照合。
- 全CSV中の数値着順は4,351行、異常/未確定/欠測119行、OK ST 4,394件。これは**未全件照合の探索用**集計である。数値着順のみを率の分母とし、提供元の「出走数」定義とは区別。
- 公式の訂正前後の原本、訂正履歴、公表時刻、取得→反映実測遅延は未確認 (`null`)。単一取得から改訂追跡を実証しない。

取得のローカル保存完了時刻（UTC、ファイルmtime、独立receiptではない）: CSV 16:48:41、レースJSON 16:49:18、選手JSON 16:49:19、K 16:49:19、B 16:49:22。JSTでは翌11月6日。API3件を当該JST日の上限として扱い追加呼出しを停止した。提供元の「1日」の時差定義は不明なので、ローカル運用にJSTを採用した。

## モデル入力と時点境界

`enrich_observed_snapshot(snapshot, histories, official_archives, verified_at=..., allow_source=..., authenticate_official=...)` は既存native snapshotのコピーを返す。CSV、または取得済み1レースJSONを6人で共有して履歴として再利用できる。公式LZHは実bytesを再展開しhash・内部日付・登録番号を照合する。独立公式ソース認証callbackと用途別承認なしでは停止。

追加可能なnative特徴量は `recent_mean_finish`, `recent_mean_st` (提供履歴の最大直近10機会)、`course_mean_finish`, `course_mean_st` (現在の枠番と同じ**過去実進入**の提供履歴の条件一致最大直近30機会)。実走母数・window・出典・変換を維持する。全履歴が照合できないときは提供履歴の範囲のみであり、全出走と呼ばない。未照合/不一致の走は隔離し件数を報告するが、窓の機会数から除外して古い正常走で埋めない。F/L/同着・未照合を含む窓では通常着順平均を出さず、STはOK値のみとF/L/欠測母数を維持する。

既存2 observedモデルへ**同一snapshot**を渡す合成6人統合テストに成功。今回の実データでは過去レースの現在取得データしかないため、そのレースの締切前入力としてnativeモデルへ通す検証は実施していない。実6人の過去1レースデータ作成・照合は成功、未来レースの入力一式/モデル実行成功は未実証。

`descriptive_summary` はコース別1/2/3着内率、ST平均/母標準偏差/コース別ST、10/30走、場別・**推定**グレード別集計、期間・母数・定義・出典を返す。探索用集計であり公式照合フラグを付けない。既存の `boat_racer_tendencies` / `boat_entry_observations` で前付け代理指標等を扱う処理は変更しない。CSVだけから受けた進入変更、内側敗戦の勝者決まり手、意図、直接まくられた相手を作らない。

A/Bは出走表・展示・モーター、C-liteは当日当地勝率/平均ST、fullモデルは展示/気象等の追加必須入力がある。4競技共通モデルには全共通8特徴とボート用3特徴、環境の独立証拠が必要。艇愛の欠測項目を補って全モデル比較成功と称さない。今回はdispatch/係数/モデルID/学習処理を変更しない。母数不足でも年齢ボーナスを付けず、モデル既存の欠測方針を維持する。平滑化変更は未実施。

可用時刻は `published_at` (不明ならnull)、`captured_at`、`stored_at`、`verified_at` を区別し、取得≤保存≤照合≤予想基準<発売締切を必須とする。履歴対象日は対象レースより前日以前に限定。レース開催日は公表時刻の代用にしない。過去時点の独立可用性確認が無いので正式バックテストeligibleは常にfalse。現時点取得した選手通算/grade/年齢を過去時点値として復元しない。

## キャッシュ・実行と権限

`HistoryCache.initialize(path, owner_key)` は明示的初回作成のみ。`path` はgit checkout外。32byteの所有者設定キーでAES-256-GCM暗号化した原bytesと取得/書込み開始時刻をSQLiteへ保存する。返却するstored_atはcommit後、または認証済み復元読出し後に観測した保守的な可用時刻である。書込み開始時刻を保存完了と扱わない。通常再開は `HistoryCache(path, owner_key)` とし、欠落・破損・復号不一致を新規空DBへresetしない。合成テスト以外の公開キー/ランダム即席キーを本番に使わない。

`fetch(url, allow_source=...)` のcallbackは既存 `PermissionPolicy` の用途判定と接続できる。collection/private_storage/analysisの全許可が必要。exact allowlist、redirect拒否、8MB上限、Content-Type、TLSを検査。既取得は無通信再利用。`refresh=True` の明示時だけ差分候補を取得し、旧原本を上書きせずSHA付き版を追記する。取得台帳・保管期限・全暗号化版はキーに結び付いたHMACで認証し、違うキーでの未取得URLへのGETや台帳削除も停止する。認証済み旧DB全体への巻戻しはローカルHMACでは検出できず、独立したrunner間handoff証拠が必要。同じSHAは内容同一の再観測として識別可能。

API全体で3 GET/JST日をGET前にSQLite transactionで予約。エラーも消費。通信中の中断は自動再実行せず確認待ち。429/Retry-After/403/5xx/通信失敗は既存待機方針で永続化し、inline retryしない。未明示のエンドポイント・スクレイピングへの代替なし。複数runnerで同じキャッシュを共有しなければ全体quotaを保証できないため、未設定の定期runnerへ接続しない。初回手動pilotの3GETも本日の消費済みとして扱う。

キャッシュは初回から7日で利用停止し保管見直しを要求する。これは長期保存許可ではない。原本の削除/保管延長/暗号化アーカイブを所有者の保管方針に従って判断する。原本DBの自動削除や予想保存領域への書込みは行わない。実APIpilotは一時private作業領域にあり、所有者キーを使う実データ暗号化復元は未実施。GitHub secret一覧取得は403であり、キー未設定と断定していない。

## GitHub Actionsと検証方法

既存 `.github/workflows/forecast-audit-ui.yml` のviewer_contractに、固定crypto依存導入と `test_teiai*.py` 検査を追加。新workflow・schedule・権限追加なし。CIは全て合成fixturesで、provider通信・実raw upload・実学習は行わない。既存の全国締切順ワークフローは現在動作中だったため変更・再起動していない。main保護APIは403、保護を迂回しない。

```
python -m pip install -r requirements-history.txt
python -m unittest discover -s tests -p 'test_teiai*.py' -v
python -m unittest discover -s tests -q
PYTHONPATH=. python tests/boat_historical_route_harness.py
python -m scripts.teiai_history_probe --history /private/4444.csv --racer /private/racer.json \
  --registration 4444 --race /private/race.json --race-id 20261101-13-10 \
  --official-k /private/k261101.lzh
```

公式解析器は既存CIの固定PR64 checkout `pr64-reference/race_ai` が必要。CIの固定PR72参照も全件回帰テストに必要。原APIや非公開モデル入力をテストfixtureへコピーしない。

## 完成条件と最小の次工程

|条件|現在地|
|---|---|
|API・利用条件確認|個人研究の限定範囲は確認。学習・長期保管等は保留|
|既存コード差分調査|完了、モデル変更なし|
|1選手の実履歴|4,470行の限定取得・解析成功|
|公式一致検証|2レース7unique出走・払戻10項目の小標本のみ|
|特徴量|探索集計実行、照合/時点付き変換と合成native統合テスト。全履歴の正確性未確定|
|6人1レース|実6人の過去データ正規化・照合成功。6人全履歴/未来入力一式は未完|
|既存モデル接続|同一6人snapshot→既存observed2モデルの合成契約成功。実未来入力は未実証|
|単体・統合テスト|実行結果は最終報告とActions exact HEADを参照|
|GitHub Actions|既存CIのみで検証、URLは最終報告を参照|
|未来1レース予想・照合|未実施。締切前に今回データを取得できた未来対象を確定していない|
|原本復元/再実行|暗号化キャッシュ・quota・改変停止の合成テスト。実原本の所有者キー復元は未実証|
|PDCA全モデル比較|既存処理維持。今回追加データでの同条件実比較は未実証|

次の最小工程: 所有者キー/期限付き用途承認/暗号化キャッシュのrunner間復元を確認し、取得済み6人データを再利用できる未来レース1件を選ぶ。必要な不足履歴を日次上限の範囲で段階取得し、公式照合後の同一入力を締切前に既存モデルへ渡す。GitHubの独立保存時刻receiptを得た原本だけを、後日の公式確定結果と既存PDCAへ結合する。研究入力の不足・許諾不明・証明欠落を埋めて先へ進まない。

## 独立レビュー修正

同着の通常着順扱い、異常/未照合の直近機会から古い正常走への補充、勝者決まり手欠測の見落とし、別キーでの新URL取得、quota/期限台帳の未認証、commit前の保存完了時刻、の6点を再現テストでRED→GREEN修正。追加で同時リクエスト予約の停止と期限改変停止を検証。未供給の選手については既存snapshotの検証済み特徴量を保持する部分補完であり、全選手履歴の一括置換ではない。

## 2026-11-06 JST: 全選手の一括投入

ユーザーの「全選手のデータを入れて」を受け、艇愛APIの登録番号総当たりではなく、公式公開の全選手期別ファイルを使う経路を追加した。艇愛APIの前回3GET/JST日を増やしていない。

- 公式公開入口: https://www.boatrace.jp/owpc/pc/extra/data/download.html
- 仕様: https://www.boatrace.jp/owpc/pc/extra/data/layout.html （確認HTML SHA `c8ab62784eaed687ac439afe5dd9a7ffe480fdd32633117eccb7e46f41a4869a`）
- 対象: `fan2604.lzh`、2026年後期、算出期間2025-11-01〜2026-04-30。最新の公開配布ファイルとして確認した範囲であり、当日の全現役登録名簿、全引退選手、全生涯レース履歴の完全性を意味しない。
- 元archive183,497bytes、固定416byte/CP932の**全1,643選手・全9,858コース行**。UTF-8文字幅や可変CSVとして扱わない。登録番号重複・誤った期間・不足列・不正数値・コース母数矛盾を拒否する。
- 全1,643人を `RacerDatabase` のprivateメモリSQLiteへ実投入し、全件登録番号lookupとSQLite serialize/restoreの件数一致を実行した。全国出走0の43人、コース母数0の579行は勝率/STを架空の0で埋めずNoneと欠測理由にする。
- 既取得の公式K261101も**全1,008出走・621選手**を投入。期別ファイル外の2登録番号も保持し、確認済みIDの和集合は1,645人。基本情報のない2人を他人の記録で補わない。
- 期別の級別・年齢は当該資料記録値。現在値や過去の予想時点値へ読み替えない。全国/当地3連率、当地勝率等の未提供項目は未提供のまま。コース別数値着順からの1/2/3着内率と公式複勝率は定義を別に保持する。
- [実投入件数・hashの公開可能な証拠](evidence/2026-11-06/all-boat-racers-counts.json)。原文・個人別の全データ・SQLite plaintextはcommitしない。これはprivateメモリ上の投入・復元成功であり、所有者キーによる永続保存の証拠と混同しない。

追加実装:

- `race_ai/boat_racer_term.py`: 公式レイアウトの厳格な全行解析。LZH展開は固定PR64の `_extract_portable` を再利用、lhafile0.3.1を固定。
- `race_ai/boat_racer_database.py`: 全選手の索引、原archive/hash、版別名簿、コース成績、公式日別履歴。原本をUPDATE/DELETEしない。取得/メモリ投入完了/復元観測後だけlookup可能。JST日付で判定し、訂正版から外れた人を旧版から黙って復活させない。A→B→Aの内容巻戻りは自動選択せず訂正確認待ち。
- `scripts/boat_all_racers.py`: 全件投入/readback、count-only報告、所有者キーの非表示preflight、原本SHA固定の1GET、暗号化、復号・全件lookup。
- `scripts/keirin_github_checkpoint.mjs`: 既存main `0e45c02` の汎用SQLite AES-256-GCM処理を**無変更で再利用**（ファイルSHA `07cb14b8b996a119513754901a54bbf1825bc054da425294b0f5d9b8ff2e3e47`）。競輪の状態DBを読んだり変更したりしない。

既存 `forecast-audit-ui.yml` に、owner-key確認→暗号化一括投入と別jobのartifact復元を追加した。PR71・同一repositoryのPRだけに限定。新workflow/cron/外部クラウド/有料サービス/モデル追加なし。

- `RACE_AI_STATE_KEY` がない場合、**HOLD_OWNER_STATE_KEY_MISSING、provider GET=0** を件数のみのsummaryに記録し、復号jobをskipする。合成キーやGITHUB_TOKENから代替鍵を作らない。
- キーが設定済みなら、公開済み公式1ファイルの既確認SHAだけを取得し、SQLiteを既存AES-GCMで暗号化する。rawとplaintext SQLiteはprivate runner temp内のみで、uploadは`racers.checkpoint`とcount-only`summary.json`の2ファイルだけ。
- 取得済みの暗号化snapshotはGitHub Actions cacheで再利用し、復号/hash/全件lookupの検証に失敗したcacheから空DBへresetしない。7日経過は保管見直し待ち、暗黙の延長/再取得なし。ownerキー更新で既存snapshotを復号できない場合もGETへ切替えない。
- 別jobは同一runの正確なartifact IDをdownloadし、AES認証・SQLite hash/integrity・公式archive SHA・取得時刻・全選手lookupを再検査。artifactは7日限りで永久バックアップではない。
- この一括経路は当該期の再構築可能な研究資料専用で、予想原本や継続PDCAのDBを初期化しない。現行モデルへの学習/切替、当日能力値の置換はない。

独立レビューで、全国母数0の扱い、名簿改訂時の集合、内容巻戻りを指摘され、各再現テストで修正した。JST境界と暗号化cacheの無通信再利用もテストした。固定checkpoint上限8MiBのため初回1期分に限定し、次期・大量訂正版を無制限に追加できると主張しない。上限到達時は停止し、圧縮/分割/版管理設計が別途必要。

再現コマンド（raw出力なし）:

```
python -m unittest tests.test_boat_racer_term tests.test_boat_racer_database tests.test_boat_all_racers -v
python -m scripts.boat_all_racers inspect --term-archive /private/fan2604.lzh \
  --k-archive /private/k261101.lzh --k-day 2026-11-01
python -m scripts.boat_all_racers capture --out-dir /private/cipher-output --reuse-dir /private/cipher-cache
python -m scripts.boat_all_racers restore --folder /private/cipher-output
```

未来レース1件の締切前保存/確定結果照合は、この一括投入とは別ゲートのまま。全選手の「期別成績」を、全選手の「直近10/30実走履歴」として渡さない。

## 全会場・全期間の追加

[全期間・全会場・全選手の履歴集計](BOAT_ALL_PERIOD_VENUE_HISTORY.md)に、公式公開月263か月の対象、実データ7日分・全24場の集計、月別暗号化checkpointと残る未取得範囲を記録した。全期間取得完了ではない。
