# 自動予想経路の取得回数上限を撤廃

2026-11-05のオーナー指示「取得上限なしにして」に対応。以前の固定GET回数上限（累積240回、1収集45回）を、自動予想経路の反復session・provider・service・controller・P1pilotから外した。新しい上限値はPython `None`/JSON `null`。巨大数やInfinityで上限を隠す方式は使わない。画面は明示的なnullのときだけ「取得回数上限なし」と取得回数を表示する。

## 検証

- 全Python888件、Node179件、失敗/skip0。独立レビュー118件成功。
- 合成ブラウザ4幅、37操作グループ/58PNG、画面エラー0。390/1440の両幅で365→366回でも自動GET表示更新、編集中候補・選択原本・手動読込を保持。生成POST/公式取得0。
- providerは保存済み240回から246回へ継続し、再起動後もカウンターを保持。1収集50回の模擬GETも成功。
- 反復guardは258回を計数。240回超でprepare→complete→再起動、旧240 metadata・280カウンターから281回への継続が成功。
- pilotは60回の模擬GET、46回以後の日程取得/候補処理/既存オッズ取得を検証。HTTP429は引き続き停止し、追加GETしない。
- service/controllerは365回を受入れ、回数減少・bool/負数等を拒否。旧上限による保存済み停止は自動解除しない。

最初に旧実装で失敗することを確認し、修正後に成功させた。全試験は合成・ローカル入力であり、実レース予想を追加生成した証拠とはしない。[検証要約](verification-summary.json) / [合成画面](synthetic-browser-summary.json) / [現行コードSHA](source-sha256.json)。

## 保持した条件と範囲

180秒間隔、最大24巡/65分、JST日付境界、最大3新規レースの処理単位、締切210秒前、単一writer、HTTP4xx/429停止、出典照合、ファイル/応答サイズ・timeoutを維持。providerの真正性停止や既存の各race/venueの検証棄却を弱めていない。過去の独立one-shot診断の6GET等は、自動予想経路とは別のため変更しない。

既存カウンター、元Top8/SHA、保存時刻、原本ZIPは変更していない。ローカル既存DB SHA256 `c40bead05533ace426188ea8a111b1e4a4a639283f576972ba276e14a3e8ff1a` とsource回数3、STOPPEDを再確認した。既存stopを消して新しい回数を与える移行は行わない。

## 実行中処理への反映

公開PR HEAD897a31c、既存run41964059991は旧コードfea5b2a4で起動済み。承認前のローカル変更は未pushであり、その時点の既存実行の240回上限をその場で解除したとは扱わない。承認後の適用結果は下記に追記した。実行中処理の中断/再起動、追加run、環境再公開、main統合、実投票、本番モデル切替はしていない。ローカル自動処理も重複防止のSTOPPEDを保全する。

上限撤廃は全4競技/全適用モデル/全レースの完成や精度改善の認定ではない。入力不足、締切、巡回時間、アプリへのGitHub最新原本の自動同期等は別の未完成条件。

## 配布・並行作業の保全

新しい本人用ZIPは12,765,026バイト/319ファイル、SHA256 `a5adc98ca72f02c4501900593c13fb9a8313f82e72d1895eb3f351306c7a29cb`。276現行ソースと20seedを保持し、旧配布物/原本を上書きしない。CRC/全member SHA一致、cache/symlink0、isolated `--check` 保存288件/追加GET0/推論0。[配布物照合](package-delivery-summary.json)。

公開HEAD897a31cの監査記録/トリガーとworkflow契約修正をローカルへ取り込み、契約の両方のassertを保持して関連16件が成功。公開HEADの古い上限を新policyの実証に使わず、今回の未pushコードと区別する。

独立した配布物審査でもCRC/全格納SHA/276現行ソース/20seedが一致。旧検証済みZIPと新ZIPの私有原本38memberを直接比較して全バイト一致、4上限定数None/配布metadata null、cache/symlink0を確認。[独立配布物審査](independent-package-review.json)。

## オーナー承認後の実運転適用

717725cを既存PR71へfast-forward pushし、同一workflow/concurrencyで後続41967896991を1件のみ待機。先行41964059991の最終continuityをZIP/API SHA/CRC/session hashで認証し、旧240回上限による正常停止（第16巡完了）・HTTP等の停止なしを確認した。後続は先行のsuccess後13:38:36 JSTに開始し、第1巡step13:42:49 JST success。

新しい保存結果にsource_limit明示null、P1原本にもsource_request_cap明示nullを直接確認。実取得22（forecast18/result4）、halted_reasonnull。先行533原本の全SHA/Top8/時刻、初回P0ZIP不変。初回の新規予想/通常採点/学習版は0、結果観測+1版。未公開展示・結果表非対応3件を未確定/レビューとして保持。未対応結果を成功/外れに変換しない。実フォワード比較の精度改善や全モデル完成は認定しない。

[実policy](applied-runtime-policy.json) / [第1巡照合](applied-first-round-summary.json) / [第1巡step](applied-first-round-job.json) / [先行正常終了](applied-predecessor-handoff.json) / [source保留](applied-source-limitations.json) / [push・CI](applied-push-and-CI-summary.json) / [ローカルAPI](applied-local-api-summary.json)。10主要ファイルremote/local実バイト一致、main/初回P0索引不変、sourceHEAD717725cのviewer/autorace CI成功。

既存復元は異なるsessionのHTTP停止を自動的に継承する仕組みではないため、今後の継続起動も前sessionの終了理由を独立確認してから行う。今回の1回の切替は、その確認を完了している。新しいworkflow/自動無期限継続は作成していない。
