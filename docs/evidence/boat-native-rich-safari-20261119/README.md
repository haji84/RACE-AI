# 実Mac Safari・既存合成入力の保存画像

実行 [44439338949](https://github.com/haji84/RACE-AI/actions/runs/44439338949)、Safari 26.6/macOS、候補 f723。4幅×7画面の元PNG28枚をartifactと同一bytesで保管した。入力の日付・出走者・予想・結果はすべて架空で、各幅でBOAT6/競輪7/AUTO8/競馬12出走をDOM検査している。

目視判定は **参考8画面すべてPARTIAL**。390/1920幅の `detail` 名画像には一覧画面が残り、ほか26枚はページ種別が一致した。元の誤ったラベルも保全し、撮影同期の修正前証拠として扱う。詳細の2枚を詳細表示の成功証拠にしない。

| 対応確認 | 保存画像 |
| --- | --- |
| スマホ・ホーム | [390-home.png](390-home.png) |
| スマホ・一覧 | [390-races.png](390-races.png) |
| スマホ・詳細：一覧が残る不一致 | [390-detail.png](390-detail.png) |
| スマホ・買い目：配分summaryは未受入 | [390-picks.png](390-picks.png) |
| PC・ホーム | [1440-home.png](1440-home.png) |
| PC・一覧 | [1440-races.png](1440-races.png) |
| PC・詳細 | [1440-detail.png](1440-detail.png) |
| PC・買い目：参考との状態差あり | [1440-picks.png](1440-picks.png) |

全ファイルのサイズ・SHA256・元ZIPのidentityは [manifest.json](manifest.json)、目視の件数は [visual-counts.json](visual-counts.json)。元artifactは9,151,195 bytes、SHA256 `d5ec34e7fc199ccf12762cb07c7d1f4b1a675bd459a7bd9251708a0a9457f082`。

実データの画面・原参考JPEG・予想原本・鍵・本人用URLは含めない。物理iPhone、本人login、直接GitHub feed配送、全8画面の最終受入は未確認。UI資産の配備・モデルや重みの変更は行っていない。
