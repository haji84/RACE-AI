# RACE-AI BOAT：上限撤廃後の自動P1・停止復旧 引継ぎ（2026-11-14 JST）

**正本はGitHub HEAD、GitHub Actionsの実run、Git暗号原本。ここに記載した値は記録時の状態であり、次のチャットは必ず最新版を照合する。引継ぎ文の復唱で終わらず、未完了の実装・実証から進める。**

## 最終GOALと禁止事項
全国の公式開催対象について、既存モデルのP0（展示前）／P1（展示後）を当日の正しい締切前に自動生成し、GitHub Actionsで暗号原本保存、別runner独立読戻し、結果照合・PDCA・公開ページ反映まで行う。保存失敗時は予想を作り直さず保存済みP1/RESULT/AES continuityを検証して引き継ぐ。展示**映像**を使う予想は、事前取得した合法・利用許諾済み映像の認証と時刻整合が必須で、展示タイム等のデータ版P1とは区別する。

Public GitはAES暗号文と安全な件数・SHAのみ。原本上書き、事後予想の後付け、途中GETカウンタのゼロ戻し、複数ownerの同時公式取得、403/429を無視した継続、異なるモデル・採点器へのすり替えは行わない。PC常時運転・Vercelは使用しない。

## 2026-11-14に接続・確認した実装

- production/boat-p0-p1-20261111：`5d1dabff0ab9bb83132cd7fbdd43f49fb4eef6c4`。PR #280で固定GET上限240/日、45/巡、24論理巡・65分の旧停止条件を解除。履歴の累計GETとその日開始時の基準値は保持。物理的にはActions 1jobに24巡の定義があり、作業後はWORKER_HANDOFFで次workerに切り替える。Actionsの物理的時間制限と公式のsource waitは解除していない。
- main：`c90b95ed64db8cdac2a8ad6e1ff53808b72d5832`。PR #281で固定GET残量を条件にしていた次owner起動・失敗復旧ゲートを修正。PR #283で既存 BOAT per-race results workflow の `workflow_run: completed` でも新しいproducerの自動起動判定を行うよう接続。定期scheduleは維持。
- workflow_runからの自動再開は、**main上のGitHubイベント本文＋独立したGitHub run履歴**の一致（実行ID、同日で最新、run名、event=workflow_dispatch、repository、production refと厳密SHA、success/failure）を要求する。さらに実際の暗号済みcontinuity/controlをproduction固定readerで取得検証し、source waitなし・整合カウンタ確認後のみ再開。failureの場合は従来のAES原本復旧を行ってから再判定する。認証できなければHOLD。新しい無制限再実行許可ではない。
- PR #283のsource-free CI：https://github.com/haji84/RACE-AI/actions/runs/43492155427 および https://github.com/haji84/RACE-AI/actions/runs/43492155753 （それぞれテスト成功）。実source生成jobはPR実行ではスキップ。本番の実P1発生はこのCIからは主張しない。
- PR #282で別の結果回収器に12/36固定枠から独立した認証済みdueキューを実装し、release/boat-result-uncapped-20261114に `bfcb3bf60d78e9be7d7a6c1a1ee34e1651eedd85` を統合。mainの結果欠損回復ゲートも`MAX_RECOVERY_GETS_PER_CYCLE=36`の固定上限を撤廃し、保管済みdue件数で許可する（mainに別コミット `d107000fd2f9a8fa2a84b60321cb2f33144c696a`）。通常の高速結果収集の小型12回処理など全経路の残余固定値は別途監査が必要で、**全競技・全ワークフローの全ての閾値撤廃は未認定**。
- 最新releaseに対応したsource-free原本監査はmainの `.github/workflows/boat-main-recovery-contract.yml` の `workflow_run` 成功/失敗両方で起動するよう固定SHAを更新。全国P0/P1件数・不足分類・認証済み動画予想レコード数は安全な件数だけ出力。監査が動くことは動画の自動入力成功ではない。

## 直近の実原本の事実と未証明事項
- 2026-11-13の公式開催資料は13場156レース。P0原本が確認できたのは136レース、P1原本を確認できたのは9レース。公式掲載156のうち147レースはP1未確認。P0の136レースの中だけを見るとP1未確認は127。両方混同しない。
- 11/13 producer run https://github.com/haji84/RACE-AI/actions/runs/43348227701 は第3巡RESULTアップロード後にGitHub読戻し障害で停止し、第4〜24巡が未実行。その後の暗号・継続記録は復旧検証に利用済み。当時のHTTPエラー種別はログ不足で確定できない。
- 2026-11-14の本番修正を用いた**生の未来レースでの失敗→AES復元→別workerで新規P1生成→独立読戻し**は、記録時点で未確認。後付けで11/13のP1を増やして達成扱いにしない。
- 11/13原本に展示映像解析予想が実際に使われたと認証できた件数は0（確認した原本の範囲）。展示データP1と展示映像AI P1は別。
- 公式 BOATCASTには展示リプレイの視聴経路がある（https://race.boatcast.jp/replay?jo=03）。ただし自動保存とAI利用がすべての会場で許されるとは確認できない。利用条件は会場によって異なる。福岡FAQ：https://boatrace-fukuoka.com/modules/other/?page=index_faq  宮島の2026年7月改定告知：https://www.boatrace-miyajima.com/pdf/20260611.pdf 。許諾が不明な映像に取得コードを勝手につながない。

## 次に実行・確認すべきゲート
1. 最新のmain/production SHA・owner scheduleの発火・production `workflow_dispatch` run、Actionsの結果とper-stepログを再取得。同日新実行が存在するかどうか先に確認する。存在しなければ実レース成功は0件のまま。
2. 実runを取得できたら、公式の全race IDリストとP0/P1のAES原本（別runner SHA・予想時刻）をrace ID別に突合。各レースに「締切前予想保存／展示未公開／取得拒否／未着手／中止／締切経過」を区分し、適格レースを勝手に分母から減らさない。
3. producerが失敗した場合、後続`workflow_run`でmain owner gateと復旧proofの起動・SOURCE_CONTROL履歴GETカウンタ保持・新しい現時点未来レースへのP1保存を確認。結果の見かけ上のsuccessだけではなく、新しい暗号原本のモデル別race ID/保存時刻が必要。
4. 公式結果公開に応じて、既存結果収集器→独立暗号読戻し→PDCA→Pagesを本物の新しいrunで検証。各ステージ分母を記録し、欠落をHOLDとして通知・記録する。
5. 展示映像は対象会場・提供元の利用許諾と事前映像ソースを確認し、暗号保管・実艇番の識別・同一画角/時刻補正・P1締切前処理・既存モデルへの特徴反映・別runner証拠・実レース比較を一段ずつ実証。未提供映像やカメラ指標は合成や想像で埋めない。
6. 残る固定GETや物理workerのタイムアウト条件が、目的の全対象レースを消していないか検査する。ソース403/429、サーバーRetry-After、サイズ・認証・単一writerの安全上限は維持。

**完成判定：現時点では「自動再開の接続＋source-free CI合格」。実レース中の次P1復旧成功、全国全対象P1、映像解析P1の3証明は未完。**
