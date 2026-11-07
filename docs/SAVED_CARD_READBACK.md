# 保存された出走ページの観測を表示する

`race_ai.saved_card_projection.project_saved_cards()`は既存`RACE_AI_OWNER_REQUESTED_PUBLIC_CARDS_V1`の純粋な読取変換。元JSONの実バイトSHAとartifact IDを別途検証して渡す。取得・推論・学習・結果採点は行わない。

今回取得したartifact13283229052のcards.jsonは競輪75・オート20・競馬59の154ページ観測、予想0件。URLの開催日とページ内の日付、元URL/最終URL、取得時刻、元ページSHAを検査する。meeting開始日と開催日番号の組合せも照合する。

保存URLをそのまま識別子とし、未知の公式レースID・場名・R・締切・参加者・モデル入力を推定しない。`source_observation_view: true`、予想/結果/締切はnull、発売状態UNKNOWNで表示する。元ページの表や本文には過去成績・人気・オッズ等が混在するため、nativeモデルの特徴量へ直接渡さない。市場情報を含む表を都合よく除去して「同一入力」と認定することもしない。

画面では取得ページの出典と未接続理由を表示する。予想・結果・保存締切一覧との混在は拒否し、独立認証・締切前保存の検証フラグをfalseに固定する。154件の表示成功は154レースの予想成功や全開催網羅の証明ではない。

既存のnative入力・利用条件・締切前保存・結果照合を接続する条件は[全モデル実行契約](ALL_EXISTING_MODEL_DISPATCH.md)と[私有保存](PRIVATE_OPERATION_AND_COMPARISON.md)に従う。[最新状況](RACE_AI_LATEST_STATUS.md)に実予想の不足を残す。
