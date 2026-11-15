# 宮島4R A/B未来予想の締切前不変保存証明（2026-11-03 JST）
宮島4R 20261103-17-04。公式出走表の締切予定11:47 JST（2026-11-03T02:47:00Z）。結果・オッズを入力せず、未校正A/Bを同じ6艇の公式出走表・展示に適用した1回の前向き実証。予想後の結果採点ではない。

## 一次検証・再ダウンロード
- 公式出走表 https://www.boatrace.jp/owpc/pc/race/racelist?hd=20261103&jcd=17&rno=4
- 公式直前情報 https://www.boatrace.jp/owpc/pc/race/beforeinfo?hd=20261103&jcd=17&rno=4
- GitHub Actions run https://github.com/haji84/RACE-AI/actions/runs/41567387450 （push 1回、head/source commit 4bbc53980dc719f97c47045a20557aa9564926be）
- Artifact https://github.com/haji84/RACE-AI/actions/runs/41567387450/artifacts/13199222868 （name boat-future-ab-41567387450）
- GitHub API created_at 2026-11-03T02:38:47Z（JST 11:38:47、予定締切より8分13秒前）。
- GitHub APIのZIP digest SHA256 = 実ダウンロードZIP SHA256 61f67a3b58ccffa6f2b106c2443cf346ea29e20484e50f4f301b7b8bbdb43a6b。
- 実展開 pair.json SHA256 66e42619da9327d1233d6333849b091a1704f23677f72da4886c088cd729b1d3、バイト数14394。
- 予想生成時刻 2026-11-03T02:38:46.927338Z、入力捕捉 2026-11-03T02:38:46.919628Z。
- 公式出走表 HTML SHA256 4d65f9ebc2d7458272e8c86d5dc4f99e870c5a1c913dbeb52d7a8a4113bb148e、公式展示 HTML SHA256 b02563d07163248e5ae625e8060073d5f2ec2681ad96a466564f006501d723c4。
- 正規化入力 SHA256 00fb47f95f76f761e90256b0415213b19b0b7f48ba32eac244af8e5a082060de。共通A/B bundle SHA256 6dfa153cd25ba0b8cee4c1cf16277ef89e61cada92a608305aeca3cb46fadd27。
- 公式3 GET制限下で2026-11-03の日付、場17、4R、締切、選手登録番号6人の出走表・展示一致、6艇全展示タイム、モーター2連率を固定コードで点検した。結果入力は null、実購入なし。

## 未校正の上位8点（原本pair.jsonから転記、順序は固定）
|順位|A boat-display-rating-PL-reference-v1-UNVALIDATED|B boat-course-motor-shadow-v0.1-UNTRAINED|
|---:|---|---|
|1|2-4-1|2-1-4|
|2|2-1-4|1-2-4|
|3|4-2-1|2-4-1|
|4|1-2-4|1-4-2|
|5|4-1-2|4-2-1|
|6|1-4-2|4-1-2|
|7|2-4-6|2-1-6|
|8|2-1-6|1-2-6|

- Aはfull_120=120/120、model SHA256 c40d2e70d45f7535250dd7382d7c48349d2e98b0ecb81b27a580979620df8eea、上位8点スコア合計0.14761926230384012。
- Bはfull_120=120/120、model SHA256 a39e942b9f5023f0bc278909f0d288453407ea353cfd4972c794c157c94eda49、上位8点スコア合計0.18516261868463227。
- 各120通りは重複なし、score合計は丸め許容内で1。どちらもtrained=false, calibrated=false, odds_independent=true, purchase_decision=NO_BET。スコアは真の的中確率と主張できない。
- 原本JSONはGitHub artifactで7日保持。レース結果発表後に元原本を変更せず、別の結果版でのみ採点する。新PR作成なし、Vercel・main統合・公開・課金・自動投票なし。
