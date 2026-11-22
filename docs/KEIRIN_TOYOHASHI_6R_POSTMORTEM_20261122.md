# 豊橋6R「激アツ」不的中の構造監査（2026-11-22）

## 結論

今回の不的中は、買い目を少なくした際に的中候補を落とした事例ではない。元から生成した3連単10候補、2車単8候補に、実際の `2-3-1` と `2-3` が存在しなかった。全候補の1・2着には必ず6番または7番が入る一方、実結果では6番が6着、7番が7着だった。

その候補集合の中で支持値が1番・7番へ集中し、候補内集中度の暫定ルールを満たして「激アツ」になった。確認できた問題は、**到達できる展開の不足と、その不足を評価に反映しない信頼度判定** である。現実のレースで7番が大敗した具体的な原因は、映像を検証していないため断定しない。

3連単の集中度を上位6候補から上位4候補へ変更するだけでは、今回のA・3連単は94.6457506074%で基準90%を超え、「激アツ」のままである。この変更は買い目の4点制限ではなく、今回の失敗を防ぐ十分条件でもない。

## 1. 対象と時刻

- 対象：2026年11月22日、豊橋6R、race_id `202611224506`。
- 凍結分析の作成時刻：2026年11月22日17:36:34.828193 JST。
- 掲載締切：同日12:52 JST。作成は締切後。
- 元データの取得記録は同日11:03～11:05 JSTだが、出走表統計の更新時刻は未確認。締切前の原本が認証された正式な事前検証にはしない。
- 原分析は「結果欄未参照」の参考分析。今回の監査は結果確認後の事後検証。
- 凍結分析のモデル参照コミット：`b2e878d18cd2117ac234eeafdbf93d29e15d864d`。
- 監査時チェックアウト：`4711b9b1d841906c3d0cb1d67c8ba3497c5da58f`。
- 生成器SHA-256：`b30b7940cb054fc3225f109f1f35e70cab034c704e0d701937ded8309b8f5b47`。凍結記録と一致。
- 当該レース分析ハッシュ：`60de4cb47c43acea478f42379503ed20a506665bf351350e1eb13242300a907f`。

凍結した正規化入力を同一生成器に再投入し、A/Bそれぞれの採用買い目、全候補、14シナリオ、選別情報がすべて一致した。生成器の編集、原予測の上書き、重みの学習はしていない。以下の反実仮想はメモリ上の診断だけである。

この文書には公開画面で扱う予測要約・集計値・コード上の分析だけを記載し、私有原本、取得ページ本文、全入力レコードは含めない。

## 2. 確認した実結果と原分析

[Kdreams/Gamboo結果](https://keirin.kdreams.jp/gamboo/keirin-kaisai/race-card/result/4520261121/45202611210200/06/)と[netkeirin結果](https://keirin.netkeiba.com/race/result/?race_id=202611224506&rf=dbprofile)で着順・払戻が一致。

| 項目 | 確認値 |
| --- | --- |
| 全着順 | 2 → 3 → 1 → 5 → 4 → 6 → 7 |
| 3連単 | 2-3-1、15,550円 |
| 2車単 | 2-3、3,360円 |
| 結果表の記録 | 2番・3番は「差」、6番はB、5番はS、7番の着差は「大差」 |
| 天候・風速 | 晴、1.8m/s。確認した結果表に風向の記載はない |

BやSは結果表の記録で、打鐘からゴールまでの全隊列・進路・失速原因を直接示すものではない。風速だけから向かい風・追い風・横風や、特定選手の敗因を決めることもしない。

| 原分析 | 採用買い目 | 原評価 | 照合 |
| --- | --- | --- | --- |
| A・3連単 | 7-1-3、1-7-3、7-3-1、7-2-1 | 激アツ | 不的中 |
| B・3連単 | 7-1-3、1-7-3、7-3-1 | 中 | 不的中 |
| A・2車単 | 7-1、1-7、7-3、7-2 | 激アツ | 不的中 |
| B・2車単 | 7-1、1-7、7-2、7-3 | 激アツ | 不的中 |

2車単の集合はA/Bで同一、順位だけ異なる。A/Bは同じ入力と展開集合を使うため、一致を独立した二重の裏付けとは扱えない。

## 3. コード上の原因

### 掲載ライン先頭だけを仕掛け役にする

入力の掲載並びは `[7,1,3] / [6,2,5,4]`。`_evidence_scenarios` は `leaders = [g[0] for g in groups]` と置き、掲載ライン先頭の7番・6番だけを仕掛け役候補にする。

2番の脚質・H/B・決まり手を読み `explicit_attack=True` と評価していても、2番は掲載ラインの番手なので、自力に切り替えて動く独立した仕掛け役にしない。番手の差し分岐はあるが、2番が前の6番を見切って動く経路はない。

現在確認できるKdreamsのレース評は、6番を使う2番自身の仕掛けも想定している。ただし、その文面が凍結収集時にも同一だったことは証明していない。その文章を展開分岐へ変換する処理がないことと、当時の収集時点でその記述を見落としたかどうかは別問題である。

### 片方の先頭が崩れても、もう片方の先頭が残る形に限定される

14シナリオは8戦術分岐から作られる。

| 分岐 | 生成できる到達形 | 構造上の制限 |
| --- | --- | --- |
| 7番ライン維持・6番から7番の反撃 | 7-1-3、7-3-1 | 7番が1着に残る |
| 7番に対する番手差し | 1-7-3 | 7番が2着に残る |
| 7番の失速 | 6-1-7、6-1-2 | 6番を1着に置く |
| 6番ライン維持・7番から6番の反撃 | 6-2-5、6-5-2 | 6番が1着に残る |
| 6番に対する番手差し | 2-6-5 | 6番が2着に残る |
| 6番の失速 | 7-2-6、7-2-1 | 7番を1着に置く |

`FOLLOWER_PASS` では番手が先頭を交わした後、さらに元の先頭が2着から落ちる局所遷移を禁止している。その場合を別の `ATTACKER_FADE` に分けているが、そちらも片方の仕掛け役が減速し、隣接2車が交わす一本の経路に限定する。終盤の追加追い抜きも一回までで、別々の2着・3着争いを自由に連結しない。

その結果、**両ラインの先頭がともに後退し、番手・三番手の選手が別線をまたいで上位を占める経路** を、今回の並びから生成できなかった。これは実際の6局面を復元した主張ではない。実際の上位2車がどちらも掲載ライン先頭ではなく、全生成候補の不変条件に反していた、という確認である。

### 2番の勝ち筋を6番の2着残りに縛る

生成された2番1着候補は `2-6-5` だけ。能力スコアは、2番の1着用が0.583、6番の2着用が0.0852。支持値は次の非線形積で計算する。

`1着能力^2 × 2着能力^1.3 × 分岐係数`

Aの分岐係数は分岐支持値の平方根、Bは分岐支持値と局所追い抜き適合度。3連単では、さらに許可された3着候補の能力^0.8による比率で分配する。

2番本人が一定の能力を持ち、番手差し分岐の支持が0.8でも、6番の低い2着用能力を必ず掛ける。2番が勝ちながら6番が着外へ落ちる形には、そもそも支持値を割り当てない。

| 全候補内の勝者別支持比率 | A | B |
| --- | ---: | ---: |
| 1番 | 29.1803% | 30.3081% |
| 2番 | 1.2183% | 1.3863% |
| 6番 | 1.0592% | 1.1931% |
| 7番 | 68.5422% | 67.1125% |
| 3・4・5番 | 0% | 0% |

この比率は候補内の研究支持値であり、現実の勝率ではない。0%は、その選手が勝てないという事実ではなく、生成集合に勝つ経路を置かなかったことを意味する。

## 4. なぜ「激アツ」が止まらないのか

各候補は、同じ着順に至る複数シナリオの支持値の最大を採り、全候補内で合計1へ正規化する。重複による水増しは避けられるが、生成しなかった着順の残余リスクを持たない。

| 原指標 | A・3連単 | B・3連単 | A・2車単 | B・2車単 |
| --- | ---: | ---: | ---: | ---: |
| 勝者上位2車 | 97.7225% | 97.4206% | 97.7225% | 97.4206% |
| 1・2着上位4組 | 97.7225% | 97.4206% | 97.7225% | 97.4206% |
| 3連単上位6組 | 98.9408% | 98.8069% | 対象外 | 対象外 |
| 採用買い目に残る支持比率 | 94.6458% | 78.5936% | 97.7225% | 97.4206% |
| 主要分岐の未採用 | なし | あり | なし | なし |
| 原評価 | 激アツ | 中 | 激アツ | 激アツ |

「激アツ」は軸85%、1・2着85%、3連単集中90%、採用比率90%以上と、主要分岐に未採用がない条件による設計上の判定で、実績から校正した数値ではない。展開集合が欠けていても、内部集中度だけ高くなり得る。

`_forward_metrics` は支持比率10%以上の候補に加え、各対抗分岐の種類ごとに最強シナリオ一つを主要分岐にする。今回の代表は次のとおり。

| 分岐の種類 | 主要代表 | 主要代表から外れた反対側 |
| --- | --- | --- |
| 番手差し | 1-7-3 | 2-6-5 |
| 先頭失速 | 7-2-1 | 6-1-7 / 6-1-2 |
| 別線反撃 | 7-1-3 | 6-2-5 / 6-5-2 |

種類を一つずつカバーしても、両側のラインが有利になる展開をカバーしたことにはならない。Aでは7番側に寄った代表をすべて採用して「主要分岐の未採用なし」になる。

また必須欠測判定は主に `riders.*` と `published_line_groups`。`race_time_weather`、`bank_specific_rider_performance`、`verified_recent_form_trend` などが未接続でも、それ自体では「激アツ」を遮断しない。したがって現行表示は、これらも加味した総合信頼度を表していない。

## 5. 選手特性・位置別バンク適性・みなし直線・風への耐性

| 要素 | 今回の実処理 |
| --- | --- |
| 競走得点・掲載勝率・連対率・3連対率 | 使用。着順別能力の主成分 |
| 掲載印 | 使用。1着能力10%、2着・3着能力各5% |
| H/B・S・逃げ/捲り/差し/マーク・脚質 | 仕掛け資格、分岐支持、初周仮説、局所追い抜き条件に使用 |
| 出典付き本人コメント | 狭い自力表明パターンを使用。文章の総合解釈ではない |
| 直近の調子の上昇・下降 | 未接続。掲載4ヶ月成績をその代用にしていない |
| 選手ごとの位置別バンク適性 | 未接続。番手という位置を使うことと、その位置での実績を学ぶことは別 |
| バンク形状・みなし直線 | 未接続 |
| 当日の風速・風向と走行方向 | 未接続 |
| 選手ごとの風への耐性 | 未接続 |
| ギヤ比 | 記録のみ。採点しない |
| 落車・休養・復帰後の時系列履歴 | 未接続 |

| 能力 | 得点 | 対応する着内率 | 掲載印 |
| --- | ---: | ---: | ---: |
| 1着用 | 60% | 勝率30% | 10% |
| 2着用 | 60% | 2連対率35% | 5% |
| 3着用 | 55% | 3連対率40% | 5% |

得点は場内差を `max(10点, 最高最低差)` で割る変換後の値であり、確率ではない。

別ファイル `comprehensive_four_sport_models.py` には `bank_fit` や `crosswind_resilience` の係数が存在する。しかし今回の実行経路は `keirin_generate_result_unread_analysis.py → keirin_nationwide_auto_generator.generate_evidence_analysis` で、別モデルは呼ばれていない。リポジトリ内に名称があるだけで使用済みとはしない。

## 6. オフライン感度検証（反実仮想）

結果確認後に行った原因分離の診断。事前に有効性を検証した改善案、実測された選手能力、的中保証として扱わない。全候補・支持値・買い目を固定して集中度だけ変えた結果は以下。

| 区分 | 3連単上位4集中度 | 置換後評価 |
| --- | ---: | --- |
| A・3連単 | 0.946457506074 | 激アツのまま |
| B・3連単 | 0.943887433537 | 中のまま |
| A・2車単 | 対象外 | 激アツのまま |
| B・2車単 | 対象外 | 激アツのまま |

B・3連単は採用比率78.5936%と主要分岐未採用が残り、高以上にならない。

主要代表だけを「分岐種類」から `(分岐種類, 仕掛け役)` ごとに一つへ変える診断では、A・3連単と両2車単にも未採用の反対側分岐が現れ、4区分すべて「中」になる。ただし的中候補は追加されない。実装・採用はしていない。

候補・分岐・入力を固定し、支持値の `2着能力^1.3` の項だけを除いた診断では、2番1着の候補内支持比率が次のように変わる。

| 診断 | A | B |
| --- | ---: | ---: |
| 原計算 | 1.2183% | 1.3863% |
| 2着能力の乗数だけ除去 | 15.1747% | 17.1458% |
| 1着能力の指数だけ2から1へ変更 | 1.3807% | 1.5570% |

6番が実際には高能力だったという主張ではない。2番の評価が、6番を2着に残す唯一の経路に強く縛られていたことを切り分ける診断である。どの変更でも `2-3` は全候補に現れず、単に能力の重みを緩めても経路欠落は解消しない。

## 7. 判断と限界

改善を検討するなら、番手の自力への切替、追走の切れ、両先頭の後退、別線の追込みが交差する到達形を、根拠付きで扱えるかが先になる。分岐種類の網羅と、どちらのライン・仕掛け役の成否を網羅したかも分ける必要がある。位置別バンク実績、みなし直線と差し・残り、風向・風速と走行方向、選手別の風対応については、入力接続と事前固定データ群での検証が別途必要である。

これは今すぐ特定の係数を変更すべきという結論ではない。候補を無制限に増やすことも解決にはならない。低根拠の全順列列挙は実際の経路を説明しない。未モデル化の残余リスクと、強い表示を付ける条件を併せて検証する必要がある。

現時点で断定しない事項：実際の打鐘・最終ホーム・最終バック・4角の全隊列、7番後退の理由、2番の仕掛け位置、3番の進路、風の着順への影響、バンク適性を入れた場合の的中可否。映像を未検証のため、この監査に実走の6局面記録はない。過去のバンク解説の季節風記述も、2026年11月22日当日の風向や敗因へ転用しない。

## 8. 再現手順

私有原本は添付しない。所有者の環境で凍結パケットを指定する。出力は一致判定と集計だけで、元の出走表・予測本文は出力しない。

```bash
python - /absolute/path/to/frozen-analysis.json <<'PY'
import copy
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from race_ai import keirin_nationwide_auto_generator as generator

packet = json.loads(Path(sys.argv[1]).read_text())
race = next(row for row in packet['races']
            if row['race_id'] == '202611224506')
assert hashlib.sha256(Path(generator.__file__).read_bytes()).hexdigest() == race['model_source_sha256']
snapshot = dict(race_id=race['race_id'], riders=race['normalized_riders'],
                line_groups=race['analysis_lines'], line_warnings=race['line_warnings'],
                round_rule=None, condition_evidence=race['condition_evidence'],
                competition='OTHER')
replay = generator.generate_evidence_analysis(snapshot)
profiles = {p['car']: p for p in race['feature_audit']['riders']}

for arm in ('A', 'B'):
    for field in ('ranked_tickets', 'ranked_2ren_tan', 'candidate_tickets',
                  'six_phase_scenarios', 'selection'):
        assert replay[arm][field] == race[arm][field], (arm, field)
    for places in (3, 2):
        exact = {}
        support_key = ('support_' if places == 3 else 'pair_support_') + arm
        for scenario in race[arm]['six_phase_scenarios']:
            ticket = tuple(scenario['projected_3ren_tan'][:places])
            exact[ticket] = max(exact.get(ticket, 0), scenario[support_key])
        total = sum(exact.values())
        dist = {ticket: value / total for ticket, value in exact.items()}
        assert tuple((2, 3, 1)[:places]) not in dist
        assert all(set(ticket[:2]) & {6, 7} for ticket in dist)
        winner = defaultdict(float)
        for ticket, weight in dist.items():
            winner[ticket[0]] += weight
        print(arm, places, 'candidate_count', len(dist),
              'top4_share', sum(sorted(dist.values(), reverse=True)[:4]),
              'winner_2_share', winner[2])
    altered = copy.deepcopy(race[arm]['six_phase_scenarios'])
    for scenario in altered:
        second = scenario['projected_3ren_tan'][1]
        factor = max(.001, profiles[second]['second_strength']) ** -1.3
        scenario['support_' + arm] *= factor
        scenario['pair_support_' + arm] *= factor
    pair = {}
    for scenario in altered:
        key = tuple(scenario['projected_3ren_tan'][:2])
        pair[key] = max(pair.get(key, 0), scenario['pair_support_' + arm])
    share = sum(v for t, v in pair.items() if t[0] == 2) / sum(pair.values())
    print(arm, 'remove_second_strength_multiplier', share)
print('Exact frozen replay and structural checks passed.')
PY
```

## 9. コードと公開資料

- [生成器](../race_ai/keirin_nationwide_auto_generator.py)：`_evidence_profiles`、`_evidence_scenarios`、`_scenario_prefix`、`_local_finish_paths`、`select_scenario_markets`、`generate_evidence_analysis`。
- [研究信頼度](../race_ai/keirin_research_stability.py)：`_distribution`、`_forward_metrics`、`assess_research_analysis`。原評価は変更前の凍結指標に基づく。
- [共通評価](../race_ai/keirin_confidence.py)：`THRESHOLDS`、`grade_coherence_metrics`。上位4変更は別作業。
- [実行入口](../scripts/keirin_generate_result_unread_analysis.py)：`analyze` と固定生成器ハッシュ。
- [別モデル](../race_ai/comprehensive_four_sport_models.py)：今回呼ばれていないバンク適性・横風耐性項目との区別。
- [Kdreams/Gamboo結果・レース評](https://keirin.kdreams.jp/gamboo/keirin-kaisai/race-card/result/4520261121/45202611210200/06/)。
- [netkeirin結果](https://keirin.netkeiba.com/race/result/?race_id=202611224506&rf=dbprofile)。
- [Kdreams当日出走表](https://keirin.kdreams.jp/toyohashi/racecard/45202611210200/)。
