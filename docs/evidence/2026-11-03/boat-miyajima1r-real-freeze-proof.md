# 2026-11-03 宮島1R 実公式展示取得・予想・締切前クラウド保存証拠（Vercel不使用）

**実行概要：** GitHub Actions実run [41557112331](https://github.com/haji84/RACE-AI/actions/runs/41557112331) の「Real single venue/read-only bounded source」が、公式`racelist`1R → レース本人の`racelist` → 公式`beforeinfo` を最大3GETで取得し、PR64固定コミット`761247bee0209e37b1af6b8885e92cad3e9260a5`のPython HTML検査器で年月日・会場・1R・締切・6艇登録番号・展示タイムを照合した。

- レースID: `20261103-17-01`（宮島1R）
- 予定締切: `2026-11-03T10:18:00+09:00`
- 展示入力捕捉: `2026-11-03T01:03:08.819794+00:00`
- 予想生成: `2026-11-03T01:03:08.832952+00:00`
- GitHub Actions artifact ID: `13193749273`
- [artifactへのリンク](https://github.com/haji84/RACE-AI/actions/runs/41557112331/artifacts/13193749273)
- GitHub Actions artifact server-side created_at: `2026-11-03T01:03:09Z`、**予定締切891秒前**。
- ZIP SHA256: `dc7f5b43354ae80bbe677d2bc17c302e58bc8a9fb3ba6782a85f49d08a200442`（GitHub API値とダウンロード再計算一致）
- artifact内`pilot.json`のSHA256: `f353ce72e72daac9f4acf444b7a072d1474c90da4c8e2c40bf90342ac340046b`
- 元`beforeinfo`のソースSHA256: `86d4962f933028474739d5f303f3aff56144890ce16fb7a53d5654962a6145ba`
- 予想モデル: `PR64-style-rating-display-PL-uncalibrated-readonly`（PR64厳密同値・確率校正は未検証）
- 3連単上位8点（保存版から転記）:
  1. 2-1-5 (0.02589451287014028)
  2. 1-2-5 (0.02492600293087105)
  3. 2-5-1 (0.024433122601494037)
  4. 5-2-1 (0.02259938002993521)
  5. 1-5-2 (0.02235974328936074)
  6. 2-1-3 (0.02176961037683443)
  7. 5-1-2 (0.021485203321101133)
  8. 1-2-3 (0.020955380577273485)
- 上位8点score合計: `0.18442295599701036`。**未校正**なので実的中率と称さない。

**重要な区別:** 当該GitHubクラウドartifactは実レースに先立って作成・読戻し確認済みで、予想内容とserver-side外部時刻の事前保存証拠となる。ただし7日間のartifact保持なので長期の不可変監査・Cloudflare D1・アカウント別非公開ストアの代用品ではない。またGitHubのpublic repoに保存したのは研究用派生JSONのみで、公式HTML原文・映像・API認証情報は保存しない。

**未達:** Cloudflare Workers cron+D1は未配備。全国全レース・無人連続実行、レース別冪等的D1保存・UI配信・新しい未来レースへの本番自動反映の実証は0件。宮島1Rの公式結果照合・PDCAは、この記録時点では未実施。結論は「**単一レースの実展示取得→研究予想→締切前GitHub artifact保存→APIと実ZIPのSHA読戻し成功**」に限定する。PR #64のBlob保存機構はVercel依存なので使用していない。
