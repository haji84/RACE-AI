# DT-R1 再開証拠（2026-11-28 JST）

- 親HEAD 9a984288158c36dd7e6446f0eafb660cb5b375b4 / PR #408。main未変更。
- 修正版run [46049489264](https://github.com/haji84/RACE-AI/actions/runs/46049489264) の実ZIPを別環境へ取得し、外部固定ZIP SHA・manifest SHA、8暗号shard、3公開ファイル、CRC、ファイル集合を全照合。公開モデルはログ25断片を再結合し、ZIP中モデルと同一Git blobであることを確認して本ディレクトリに固定。暗号文そのもののGitHub恒久保存は未達。
- 保全CLIは実ZIPを一時的なローカルGit remoteへcreate-only保存し、別checkoutで12ファイル照合・2回目の冪等動作を確認。shard改変と余分なファイルを拒否。GitHub本番stateには未実行、別runnerやowner秘密鍵による復元も未実施。既存認証済みcheckoutから `python -m research.chatgpt_dt_r1.preserve_verified_bundle /path/to/downloaded.zip --publish-from-existing-checkout /path/to/RACE-AI` を使用。新規権限・鍵・cronなし。
- Artifact期限: 2026-12-05 03:45:24 JST。GitHubの既存アーカイブwrite jobはmainのsynthetic producer限定。研究CIのwrite権限拡張は行わない。現チャットのローカル実行環境はGitHub DNS解決不可。APIのGit blob writeはテキスト入力で実ZIPの全バイト転送経路がないため、全暗号文保存を完了扱いにしない。
- B展開 [run 46049762970](https://github.com/haji84/RACE-AI/actions/runs/46049762970) 完了。20,041教師、B先頭2211/3503、着順共通3480。直接→混合: 3連単1点415→415、2点677→697、4点996→1011、9点1484→1481、12点1672→1674、2車単1点837→841、2点1322→1332。Log Loss 4.1735144→4.1578177。3連単1点は改善なし。B重みは当該runのartifactに存在せず、集計のみ保全。再学習を繰り返さず、新独立期間の試験でモデルと校正の保存を必須とする。旧最終期間は候補選択に再利用しない。
- [Mac PR #409](https://github.com/haji84/RACE-AI/pull/409) 最新の実機報告は398フレーム、65観測の46正答/7誤り/12棄権、学習適格観測2→3、新規動画0、未来映像有無比較0。録画許可失効と既存映像解析許可を分離。DT-R1に認証済み速度・加速度等が追加されたとは扱わない。
- [#404](https://github.com/haji84/RACE-AI/pull/404) 現行A/B合計50%、研究50%（A/B各25%）。所有者指定のA/B各50%の統合とは異なる。[#405](https://github.com/haji84/RACE-AI/pull/405) は現行A/B合計25%学習配分。Codex独自候補[#406](https://github.com/haji84/RACE-AI/pull/406) と[#407](https://github.com/haji84/RACE-AI/pull/407) の比較は事後検証。正しい統合の実体を特定し、3者の同一締切前入力・model/policy/schema pin・独立読戻しが揃うまで勝敗保留。
- P0: ZIP独立取得・整合性と公開モデル保全。暗号文GitHub保存/owner復元/別runner待ち。P1: B実学習集計回収、モデル永続化/校正/未来試験待ち。P2-P8未完。今回のmain・本番pin・既存原本・権限・秘密・購入・スケジュールの変更なし。
