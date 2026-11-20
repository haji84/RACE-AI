# 競輪サイトを既存RACE-AIへ取り込む（2026-11-20 JST）

本人指示：『取り込んで、GitHubに取り込んで使える画面にして、入力元も同じようにして。』

この指示で、提供サイトと同じKドリームス・netkeirinの入力を本移行の対象に追加する。過去のWINTICKET/KEIRIN.JP限定の取得設定より本指示を優先する。Cloudflare/Vercel・新課金・投票・本番重み切替・新PRを追加する指示ではない。既存の取得拒否履歴や未完成表示を消さない。

## 取得済みの原本

- Source Site: `https://keirin-20261119-race-note.chankuma.chatgpt.site/`
- 公開第6版のsource commit: `25a829413d5f5940f0dcaed1cc7dda7e473105a0`。
- 11/20: 57レース・414選手。個別分析原本57件/543点と、可変点数の改訂594点を別に保持する。原分析8〜12点・改訂4〜18点を正式モデルの最大8点へ改変しない。
- 参考A/B各57件は既存RACE-AIの無改変の計算。Cは57件とも未生成。11/19の75原本と後日の照合も別データのまま保持する。
- 提供サイトの主表示の統計はKドリームス、Hと参考A/Bの統計はnetkeirin。媒体間の値を平均・混在させない。正式PR71全入力の認証や学習済み精度とは扱わない。

## 実装

- [x] 現main `afbf923b5522e19d479d0bf1244b22a880ac2186` を保全し、既存PR62の履歴をours mergeで残してUI82ファイルを取り込む。古い他分野のtreeを適用しない。
- [x] 所有者の保存JSONを読み、原本SHA/改訂/日付/出典を保持する独立のnote envelopeを作る。平文の予想・出走資料・結果原本をpublic Gitへ置かない。
- [x] 独立した表示用AES鍵で新しいnoteだけを暗号化する。`RACE_AI_STATE_KEY` の取得・local使用は0。既存BOATのviewer/key/予想/履歴を読み替えない。
- [x] 新しい画面は既存app.js/style.css/index.htmlの許可済み配信資産へまとめ、Shadow DOMで既存4競技の画面と分離する。日付・場/検索・2車単/3連単・点数・予算・原本/改訂・参考A/B/C・根拠・保存オッズ・コピーを実装する。
- [x] 同じ入力元の動的な日付/開催/締切の取得を既存パーサーで接続する。構造化された並びとレース固有のclass/stage/cutoffを使用する。取得総数の8件上限を外し、既存の時間/拒否/原本/締切の条件を保持する。
- [x] 元の57保存入力と無改変A/B出力の一致、合成回帰、暗号読取り、スマホ/PC操作、ファイル改変/予算/出典不整合の拒否を検証する。
- [ ] 既存PR62へ通常FFで保存し、現在のmainに対する差分を検証する。必要なCIとレビュー後に通常の保護付き統合を行う。
- [ ] 既存gh-pagesのcurrent parentでCASする画面更新。全既存viewとBOAT manifest identity、racer-daily V2、既存DOM hooksを保持し、新規のlive asset pathを増やさない。競合時は新headを読み直す。

## 固定境界

BOAT source `1dbb47b68d487fc6def0bd4b10b1423f0a2145f6` と稼働中workerを変更しない。再dispatch/retry/cancel/reset/hotswapをしない。新workflow/job/step/input/cron/runner/timeout/permission/trigger markerは作らず、必要な既存run本文だけを変更する。全モデル・全日/T15・実機iPhone・前向き改善は個別の実証が必要。


## 更新用の表示鍵と実取得（追加設計・実測）

日々の更新は新しい表示専用P-256受取人へECDH/HKDF-SHA256/AES-256-GCMで暗号化する。publicな受取人だけをconfigへ保存し、秘密鍵は本人用リンクのfragmentにのみ保持する。Actionsの元の保管鍵はこの表示処理へ渡さない。同じRACE-AI内の `state/keirin-note-view` にindexとimmutable ciphertextを通常FF/CASで追記する。原本122ファイルのGit archiveは独立した暗号化archive entryに保全し、スマホで毎回ダウンロードしない。UIの元データ・研究更新と別に保つ。

既存の相互排他的なPR71/AB Git writerのrun本文へ同じcollectorを接続した。job/step/input/if/cron/runner/timeout/permission等の定義は不変。全公開開催HREF・全適格レースを扱い、初回の未来レースを保存し、その後は掲載締切15〜10分前に一度改訂する。過去/近すぎ/時刻不明を明示し、拒否は日付をまたいで保存停止する。拒否後に包装が失敗しても停止ラッチだけを保管する。旧AB/BOATのstop/stateを消さない。

ローカル実取得では6会場57件を観測し、24件は取得開始時点ですでに掲載締切後。残る33件中31件を正規化し無改変の既存A/B参考計算を行い、原入力と共にGitHub暗号化branchでreadbackした。73 GETは拒否なし。2件はnetkeirinのcanonicalが結果routeを指したためHOLDし、取得拒否の迂回やURL照合の緩和は行わない。1件は掲載T15〜10で入力取得・計算できたが、Git保管まで同時間帯という認証はしていない。正式PR71/全4競技/T15全件/実機iPhone/校正・前向き改善は合格していない。

現在公開中のPages `57da5e4f2e01c91f1b33daa1aaccf92743d7f4b3` の全70許可済みassetを土台にした。旧PR62の古いwebだけで既存BOAT owner-formal表示を消さず、現行DOM/module/日次V2と保存view identityを保持する。新noteは同じapp/styleへbundleする。CLI/入力/暗号・local Git readback・交錯した読込取消・元モデルとの分離・source provenanceを検査した。
