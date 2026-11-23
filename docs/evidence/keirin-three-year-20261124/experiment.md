# 競輪の3年分の資料とライン別履歴の精度検証

対象は2023年11月24日〜2026年11月23日 JST。月別CSV、Kドリームス由来のSQLite、出走表の版が残る公開データを日付・場・Rで照合した。収録を確認したレースは82,731件、1,096日。月別CSVの並び欄は区切りを復元できる形式の裏づけがない。ラインと出走車の一致を確認したSQLiteは2025年10月〜2026年11月の29,159件。旧い23か月は、各月の7車レースの時系列上の中央1件をKドリームスの元ページで確認した。23件で並びとB、21件でSが得られた。元ページの確認時刻はレース後。[月別CSV](https://github.com/Kenseimk/keirin-data/tree/8ba8316329c145aea55b5ada529b0af7b0d94c48/keirin_data) · [SQLiteと公開欄の抽出方法](https://github.com/sumidatadayoshi/keirin-data/blob/2a1260fb0940ad11160b56a36f9c24cc4fb2f6d2/keirin_scraper.py)

過去のS・Bは結果欄のマークを使う。Sは発走後に先頭誘導選手の後ろを取った記録。HとBは最終ホーム・バックの先頭通過を示し、全選手の位置や仕掛けの開始時点とは別の情報。SQLiteではS・Bと勝者の決まり手を確認できた。Hの通過順や仕掛け時点を公式レポートで確認できる個別例がある。全件に使えるH・通過順・仕掛けの時点は未収録。[KEIRIN.JPのマーク定義](https://keirin.jp/pc/dfw/portal/guest/news/2007khn/12/news20071213_01.html) · [京王閣の公式レポート](https://keirin.jp/pc/dfw/portal/guest/report/GIII/27keiokaku/2024/report_4.html) · [松阪の公式レポート](https://keirin.jp/pc/dfw/portal/guest/report/GIII/47matsusaka/2025/report_3.html)

選手の履歴は、同じレースの両アーカイブで車番と氏名が一致し、出走表側の登録番号と公式出走表由来の登録マスター上の氏名が一致し、両方の予定ライン内の役割が一致したときに採用する。予定されていた先頭・番手・後方・単騎ごとに、その後結果欄に記録されたS・Bと、勝者が逃げ・捲りだったかを集計する。各項目の観測数も残し、3走未満は評価に使わない。役割は公表された予定であり、レース中の後続選手全員の通過位置は計測していない。欠測は欠測として扱う。[登録マスターの保存版](https://github.com/mitiki0720-oss/keirin-datalavo/blob/c2dd29784525ec357906eea8962c73174bb69260/public/data/analytics/kurari-ex/exact/rider-master.generated.json) · [出走表保存版](https://github.com/kurinaka12-afk/keirin-app-data/tree/a8c7851a062e36da1e10101dcbbe1aad278fe168)

9月3日〜10月20日を学習、10月21日〜31日を設定選び、11月1日〜23日を評価に使う。学習時の履歴は対象の前日まで、評価時の履歴は10月31日までに固定する。比較するのは、既存の着順別の評価方式、並びを追加する版、並びに過去の同じ役割でのS・Bと決まり手の実績も追加する版。3着の評価係数と算出方法は3版で共通とし、2車単は1・2着から独立採点する。選定は調整期間の2車単2点、2車単4点、3連単8点の順。既存A/Bも同じ出走表で再現する。上限1・2・4点の2車単、上限4・8点の3連単を測り、既存A/Bを含む全版で実際の点数をそろえた集計も保存する。

評価用の出走表は、当時の生成時刻とコミット時刻がいずれも締切前だった保存版を優先する。後日取得した出走表を使う再現検証は別に採点する。2026年11月23日は既存の公開結果台帳の締切後の照合済み記録を使う。評価用の着順と払戻を読み込む前に、予想・係数の照合用ハッシュを固定する。直前オッズは両元資料で時点を確認できる揃った標本がなく、この比較の入力は出走表と過去走まで。

## 学習プログラム

Python 3.12、NumPy、SciPyで実行できる。学習と調整のgzip圧縮JSONは、各行が `input` と `outcomes` を持つ配列。 `input` には対象日から始まる`race_id`、全車の`riders`、車番を並べた`line_groups`が必要。登録番号が確認できた選手の`history`には過去の同じ役割での`s`、`b`、`front_win`の各項目を置き、観測件数を`n`、該当件数を`yes`で渡す。`outcomes`には確定した2車単・3連単を`2t`と`3t`に渡す。

```sh
python -m scripts.keirin_line_history_study \
  --fit fit.json.gz --tune tune.json.gz --output line-history-weights.json
```
