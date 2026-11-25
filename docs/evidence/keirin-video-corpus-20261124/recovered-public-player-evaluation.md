# 復旧した公開プレーヤー20レースの追加検証

公開プレーヤーで新たに20レースの最終向正面・最終カーブを確認し、映像の観察記録を先に固定して掲載結果のBと突き合わせた。Bと4角の両地点の先頭を使えるのは17件。そのうち先頭維持16件、交代1件だった。松戸1Rと小倉7Rは、画像中の先頭が掲載Bと一致せず、その局面をまたぐ学習から除いた。4角だけで確認できた情報は原票に残した。いわき平10Rは4角が不明だった。[20件の時刻・車番・出典と採点原票](recovered-public-player-evaluation.json)

| 開催 | 新たに位置を読めたレース | B→4角の先頭を学習できたレース |
|---|---:|---:|
| 2023年11月24日 いわき平 | 3 | 2 |
| 2023年11月24日 前橋 | 0 | 0 |
| 2025年6月3日 松戸 | 4 | 3 |
| 2026年11月17日 小松島 | 3 | 3 |
| 2026年11月18日 小松島 | 6 | 6 |
| 2026年11月19日 小倉 | 4 | 3 |

新規17件のうち、B・4角ともに前2車を識別できたのは12件。当時の締切前出走表・予想が揃った7件を、既存の三連単研究のB→4角推定に追加した。レースIDと区間を組み合わせて重複を除き、選手登録番号と車番を照合した。松戸7Rはダイジェストの確認中に放送内の着順表示が視界に入った。このレースも学習期間側に置いた。

### 後日の同一レースで比較

11月20日までの選手別先頭維持の学習例は88件から105件に増えた。同じ後日20件では15件が先頭維持。B先頭の選手が既知という条件で、維持確率の誤差（ブライアスコア、小さい方がよい）は次のとおり。

| 学習に使ったレース数 | 45 | 78 | 88 | 105 |
|---|---:|---:|---:|---:|
| 後日20件の誤差 | 0.169075 | 0.172962 | 0.173732 | 0.175564 |

別途、全125件を43の開催日に分け、それぞれ前日までの履歴だけでその日を採点した。集団の維持確率は0.153565、選手別の維持確率は0.152936。選手ごとの過去観測を使えたのは35件で、90件で初観測だった。これらと同じ後日20件の比較では、標本と学習日が異なる。

三連単は11月21〜23日の211件について、当時の締切前入力から全ての候補のB隊列と4角隊列を確率で平均して作成した。評価レースの実B・実4角・確定着順は入力に渡さず、順位を凍結してから払い戻しが確認できた207件を採点した。下表は的中レース数。

| B→4角に使った学習 | 1点 | 4点以内 | 8点以内 |
|---|---:|---:|---:|
| 前2車の区間学習20件 | 26 | 69 | 93 |
| 前2車の区間学習27件 | 26 | 69 | 93 |
| 仮想B先頭の選手別維持確率も使用、88件学習 | 25 | 69 | 92 |
| 同105件学習 | 25 | 69 | 92 |

追加後の区間学習だけでは的中数の改善は確認できなかった。今回新たに学習した展開のうち、先頭交代は17件中1件で、交代の予測に関する証拠は少ない。この公開資料は既知の過去レースの再採点である。4角の前2車がゴールまでに入れ替わる区間を合わせて学んだ評価は別に収録した。[直前版の方法](local-frame-coverage.md)・[4角→ゴールを含む検証](b-corner-finish.md)

### 公開原票から再計算する

以下をリポジトリのルートで実行する。旧125レースの観測、保存映像24件の再読、復旧した20件を日付・レースIDで突合し、直前の88件と今回の105件の条件付き誤差を独立に計算する。三連単は同じ確定組が凍結した上位8点の何番目にあるかをレースごとに照合する。原本から締切前の予測順位そのものを再生成するには、当時の出走表・凍結済み予想や特徴量が必要。公開原票で今回の順位ファイルのハッシュを確認できる。

```bash
python - <<'PY'
from pathlib import Path
from statistics import mean
from math import isclose
import json

base = Path("docs/evidence/keirin-video-corpus-20261124")
def load(name):
    return json.loads((base / name).read_text())

rows = {}
for r in load("public-race-observations.json")["races"]:
    if r["readable_B_to_corner"]:
        rows[r["race_id"].replace("-", "")] = (r["B_leader_registration"], r["B_car"] == r["corner_car"])
for r in load("local-frame-recovery.json")["reread_records"]:
    if r["accepted_for_back_to_corner"]:
        assert r["race"] not in rows
        a = r["accepted_phase"]
        rows[r["race"]] = (r["back_registration"], a["back"] == a["corner"])
report = load("recovered-public-player-evaluation.json")
prior = {k: v for k, v in rows.items() if k[:8] <= "20261120"}
for r in report["visual_new"]:
    if r["accepted_for_B_to_corner"]:
        assert r["race"] not in rows
        v = r["visual"]
        rows[r["race"]] = (r["accepted_back_registration"], v["back_car"] == v["corner_car"])
latest = {k: v for k, v in rows.items() if k[:8] <= "20261120"}
assert len(prior) == 88 and len(latest) == 105
for name, train in [("previous88", prior), ("all_eligible", latest)]:
    population = (1 + sum(y for _, y in train.values())) / (2 + len(train))
    errors = []
    for k in report["conditional"]["same_sample_races"]:
        assert k[:8] > "20261120"
        rider, outcome = rows[k]
        past = [y for reg, y in train.values() if reg == rider]
        probability = (4 * population + sum(past)) / (4 + len(past))
        errors.append((probability - outcome) ** 2)
    assert len(errors) == 20
    assert isclose(mean(errors), report["conditional"][name]["brier"], abs_tol=1e-12)
score = report["trifecta"]
cases = [r for r in score["first_hitting_rank_within_eight"].values() if r is not None]
assert len(cases) == 207
for mode in ("previous_pair_20", "new_pair", "previous_direct_88", "new_direct"):
    for cap in (1, 4, 8):
        assert sum(r[mode] is not None and r[mode] <= cap for r in cases) == score[mode][str(cap)]
print("20件の追加観測、105件の学習、後日20件、三連単207件の再計算が一致")
PY
```
