# 宮島3R 2026-11-03 A/B未来予想の締切前外部保存証明

**対象**: `20261103-17-03`、公式締切11:19:00 JST。原本予想は11:09:50.181 JSTに生成され、GitHub Actionsのサーバー側artifact `created_at=2026-11-03T02:09:50Z`。締切9分10秒前に存在が確認される。

- [GitHub Actions run 41564362916](https://github.com/haji84/RACE-AI/actions/runs/41564362916)
- [Artifact 13198428110](https://github.com/haji84/RACE-AI/actions/runs/41564362916/artifacts/13198428110)
- ZIP SHA256 `3b943dd4ee9a2d8309b8abb7cdd888f3b8107e4cf0b6658eac8c183f6120f317`（GitHub APIとZIPの再ダウンロードで実一致）
- 元`pair.json` SHA256 `5d58f23261513f44c31808f1d2d4ebbec65437f1012d9a94f295acaf1c3e11be`
- 公式出走表SHA `ba4de7f0769c0b39a99a3860dabc6dd7d2e924eb87c1a9b8f11fc9e071a77df3`、公式展示SHA `c02b5bbdad3ff6935046fceff1d700e19662dd82fd26c0b686dfc95cedaa8152`
- 同じ公式入力6艇、同じ捕捉時点 `2026-11-03T02:09:50.168429Z`。モデル補正値は2R以前に決めており、3Rの着順結果を予想入力に含めない。
- 共通A/B bundle SHA `6c73217a740d10b6e288390c9edec992be3087909acb02c24c59d4d19dbfaf7c`。

| 順位 | A:全国勝率+展示 | B:コース+モーター固定補正 |
|---|---|---|
| 1 | 6-2-3 | 2-3-6 |
| 2 | 2-6-3 | 2-6-3 |
| 3 | 6-3-2 | 3-2-6 |
| 4 | 2-3-6 | 6-2-3 |
| 5 | 3-6-2 | 2-3-4 |
| 6 | 3-2-6 | 2-4-3 |
| 7 | 6-2-4 | 2-6-4 |
| 8 | 2-6-4 | 3-2-4 |

- A: `boat-display-rating-PL-reference-v1-UNVALIDATED`、full120のモデルSHA `9627f6c5030477827743d7e0be72c65110b1d0f8df434ff3d50d922a594e2f6d`、Top8モデル合計質量 `0.14786041267459898`。
- B: `boat-course-motor-shadow-v0.1-UNTRAINED`、full120のモデルSHA `661086a769d86a9137a4b81c9088b718f2bfe738650e9279994b7ce99eb5b7fd`、Top8モデル合計質量 `0.13510308961487047`。

**注記**: スコアは未校正で、真の的中確率と同一視しない。結果照合時に原本を変更しない。GitHub Actions artifactには7日間の保持期限があるため、この文書だけで全120通りの永久読戻しを保証できない。Vercel使用なし、実購入なし、一般公開なし、Cloudflare本番D1運転なし。結果判定は別runのみ。
