# KEIRIN: 楽天以外の情報源 + 競走得点の上限なし変換（2026-11-08）

## 優先対象と取得の可否

以下はサイトの**公開情報の存在**を確認した候補であり、**無許可の自動巡回・継続収集を許可する資料ではない**。現段階のモデル用取り込みは、本人が適法に保存・記録した資料、または利用条件を満たす提供データのみ受け付ける。サイトの規約・用途を超える機械取得はしない。

| 優先順位 | 情報源 | 公式確認した情報と使い方 | 自動機械取得 |
|---|---|---|---|
| 1 | KEIRIN.JP https://www.keirin.jp/pc/raceschedule | 開催日程。選手の級班、競走得点、脚質、決まり手等について公式ガイドを確認 | 継続自動取得の許可・専用データ配信は未確認 |
| 2 | WINTICKET https://www.winticket.jp/keirin | 競走得点、選手コメント、直近10走、当地成績、対戦成績。2026年7月の「競走得点の推移」機能も確認 | 規約・提供方式は個別確認必要 |
| 3 | オッズパーク https://www.oddspark.com/keirin/ | 出走表、直近4か月の競走得点、S/H/B、決まり手、ギア倍率、条件別成績 | 規約・提供方式は個別確認必要 |
| 4 | チャリロト https://www.chariloto.com/ | 出走表の競走得点、S回数、バック回数、直近10走の結果等 | 規約・提供方式は個別確認必要 |
| 5 | netkeirin https://keirin.netkeiba.com/ | 出走表等の補助照合。ただし規約には私的利用範囲外・営業準備に制限 | 商用準備には利用しない。機械取得可否未確認 |
| 天候 | 気象庁 https://www.data.jma.go.jp/risk/obsdl/ | CSVの過去気象・降水・風・気温。品質情報・観測地点・観測時刻を保存 | 過度な自動アクセス禁止の注意あり。利用条件を守る |

公式説明：
- https://keirin.jp/pc/dfw/portal/guest/policy/index.html
- https://www.keirin.jp/pc/static/beginner/basics/racecard.html
- https://www.winticket.jp/keirin/topics/9f4QV3dmkfQ8CZtLr1Fb52
- https://www.winticket.jp/keirin/topics/n8Gpk7zcYqHUJCYPfVzTv8
- https://sp.oddspark.com/keirin/service/racelist/mikata.html
- https://www.chariloto.com/articles/6184
- https://keirin.netkeiba.com/info/kiyaku/
- https://www.data.jma.go.jp/risk/obsdl/

**楽天・KDreamsは新規収集対象から除外**。keirin.kdreams.jp、*.kdreams.jp、*.rakuten.co.jp、*.rakuten.com等を `race_ai/keirin_non_rakuten_sources.py` で遮断。既存の楽天日程取得モジュール `keirin_discovery.get_single_day` のライブGETも無効化。過去のオフラインHTMLパーサーは合成テスト専用に残す。

## 実行済み・実行していないこと

- コード済み：非楽天ソースのホスト分類、楽天URLの各取り込み経路（個人手動、権利参照付き、提供API、既存モデル入力）からの除外。個人が保存した**非楽天**日程JSONの厳密な日付・race_id・競輪場/R検査。
- GitHub Actionsの旧楽天日程自動GETをDraft PRで削除。今後そのワークフローは、ユーザーが事前に保存した非楽天ロスターJSONを指定する **手動実行のみ**。実際のレース出走表の自動収集を示すものではない。
- コード未完了：上記候補サイトの許される自動取得方式、出走表のHTML/CSV/JSON実データの統一パーサー、全レースの事前データを実際に取得して継続投入すること。**候補URLを列挙しただけで自動収集完成と呼ばない**。
- 自動巡回・無断大量収集、課金、車券購入、本番main統合は未実施。

## 競走得点は上限なし。rawの実数値を保存

既存コードの「競走得点200点を超えると拒否する」問題を修正した。

- 対象：`race_ai/keirin_allowed_delivery.py` の `RIDER_MAP.ability`、`RIDER_MAP.recent_points`
- 旧版：`score200`（0～200の入力上限、200で1.0）
- **新版：`score_open_v2`**。有限で0以上の実数値を何点でも受け入れる（100、120、200、201、300、999など）。負数・NaN・無限大・数値でない文字列は拒否。
- モデル側は数値が0～1の範囲内である必要があるため、数学的に単調増加する `model_value = raw_score / (100 + raw_score)` を使用。**入力上限ではなく、モデル側の特徴量変換**。100=0.5、120≈0.54545、200≈0.66667、300=0.75。スコアを捨てず、別の得点にも同じ変換を適用する。
- raw元値、公開/取得時刻、出典およびSHAは元の非公開JSON資料に残り、モデルの入力には `keirin-audit-score_open_v2-v1` の変換識別子が残る。形式上の単調性が精度向上や勝率の実証を意味するわけではない。
- 未学習スケールであり、**勝率・確率ではない**。以前の事前予想原本を書き換えず、変換変更は別版として未来レースで比較する。
- 100超を含め任意の非負得点にハード上限はない。計算機の浮動小数点精度が限られるため、現実離れした天文学的桁数では結果が1.0に丸められる場合がある。選手得点の実用範囲では上限による排除はしない。

## 完成判定

347項目は公開データ347本ではなく、直接確認項目、派生計算、当日しか公開されない項目、展開仮説を含む。**全項目を取得済み**と表示するのは全ての観測が確かに取得できた時だけ。予想エンジンへの実入力、公式締切前保存、結果照合、PDCA、実測的中率はそれぞれ別に検証する。

この変更は PR #101 のDraftに留め、他競技・既存台帳・本番データを変更しない。
