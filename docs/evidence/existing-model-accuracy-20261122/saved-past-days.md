# 保存した過去日の閲覧確認（2026-11-22 16:23 JST）

既存の本人用リンクを再読み込みし、競輪画面上部の日付を選ぶと、保存済みの日の予想・結果・改訂履歴を確認できる。「これからのレース」をオンにしている場合は、過去日を見る際にオフにする。

| 保存日 | 表示レース行 | 二次資料の結果一致が表示された行 |
| --- | ---: | ---: |
| 11/19 | 75 | 75 |
| 11/20 | 57 | 54 |
| 11/21 | 57 | 55 |
| 11/22 | 68 | 38 |

日付を切り替え、参考Aを表示し、「結果の改訂履歴・出典」と「参考予想の保存版・原本の照合」を展開する実操作を確認した。日付の選択範囲は保存済みの11/19〜11/22であり、任意の過去日の全データを取得済みという意味ではない。結果が未確認の行はそのまま未確認として表示する。この行数は固定33件の8点精度比較とは別の分母である。

## 見つかった不具合と対応

確認開始時、配信中のPages99832aの古い読み取り処理は、11/22の新しい全国一覧パケットで `KEIRIN_NOTE_INVALID` となり、保存データの読み込みを完了できなかった。同じ実暗号文を取得先通信0件で再生したところ、protected main8646afの読み取り処理は4日分を正常に開けた。データを削除したり、検証条件を緩めたりする必要はなかった。

関連Node141検査を通し、未公開の修正候補で4日分の日付切替・原予想/結果履歴の展開を実ブラウザーで確認した。その同じtreeであることをpush直前に検証し、既存の凍結publisherを使って、**既存のGitHub Pagesの配信資産をprotected mainへ同期**した。

- 配信元：protected main `8646af01e7931e5c0901f4e6dc3d1bd4544bbaa7`
- 配信commit：`f2e97da96672484d52e178c30134603fd286d4e0`
- 既存Pages deployment：[44997858989](https://github.com/haji84/RACE-AI/actions/runs/44997858989)、completed/success
- 全14対象資産の実HTTP/manifest/Git一致を確認。legacy BOAT reader・元cipher blob・保存予想identityは不変。
- 実公開画面390pxで4日分を読み取り、日付切替/結果履歴/予想保存版の展開が成功。JS例外0、鍵送信0、取得先サイトへのブラウザー要求0。

既存のURLとasset pathを保持し、新しいサイト・モデル・予想を作成していない。本番鍵のlocal取得/使用、本番重み切替、BOAT producer操作、原本/結果改訂の書換えは0。物理iPhone/Safariの受入確認ではない。

[旧reader/現mainの再生診断](saved-past-days-reader-diagnosis.json)・[未公開候補の実画面](saved-past-days-preview-browser.json)・[既存画面の更新と保全](saved-past-days-presentation-refresh.json)・[実HTTP一致](saved-past-days-live-http.json)・[配信後の実画面](saved-past-days-live-browser.json)。
