# 競輪：可変0～12点・期待値・回収率の検証（研究版）

## オーナー指定の正式な順番（2026-11-08）

1. 必要情報収集：締切前・出典・利用条件・全選手・ライン・環境
2. 選手能力評価：既存PR71研究モデルの根拠付き特徴量
3. 展開シミュレーション：既存モデルのシナリオ／ライン相互作用
4. 着順確率：全3連単をオッズ抜きで計算し、確率合計1・重複なしを検査
5. オッズ：別のスナップショットで出典・取得時刻・レースIDを検査
6. 期待値：モデル予測P×総払戻倍率 - 1。未校正なので仮説値と表示
7. 最適な買い目数：参考100円単位で仮説上の期待利益が正の券を選別

通常は最大8点。展開予測の確率分布が広い混戦は最大12点。
有利な買い目が少なければ1～3点にも絞り、候補がなければ0点・見送り。
点数を減らすだけで長期期待回収率が高まるとは言わない。

## 新規の独立検証コード

race_ai/keirin_variable_selection.py

- 現行PR71の検証済み研究スイートから、選択モデルの全3連単確率を受け取る。
- オッズはモデルに入力せず、モデル算出後にだけ適用する。市場オッズから
  逆算した確率を独立したモデルの勝率だと偽らない。
- 事前オッズとモデル予測のレースID・時間・順列・確率質量を照合する。
- 研究用の未学習ヒューリスティック：有効組合せ数 = 1 / Σp² が25超なら
  分散大で上限12、その他は上限8。閾値25は校正前の仮定であり、
  本物の荒れやすさとの対応を過去の凍結予想で検証する必要がある。
- 仮説的な期待倍率が1より大きい券だけを優先し、仮説利益の高い順で
  上限まで採用する。100円均等の参考投資では総期待円利益の最適化に
  相当し、期待回収率そのものの数学的な最大化とは区別する。
- すべての結果は「研究用・未校正・購入推奨不可」。買い目や原本を
  既存PR72の8点固定スキーマに書き戻さない。

研究用のローカル保存では、同名ファイルを上書きせず、
SHA256を照合してから読み戻す。出力先は所有者が管理する絶対パスに限る。
公開GitHubのブランチ、Actionsログ、artifact、cacheへ実レースの原本や
オッズ生データ、個人DB、秘密鍵を絶対に保存しない。

## 予想確定後の結果照合

evaluate_settled_result は別途入力した結果改訂番号・確定3連単・
100円当たり払戻金を照合し、仮想投資額・払戻額・損益・回収率を算出する。
欠測、結果待ち、返還は外れにしない。見送りは的中率の分母に含めない。
aggregate_latest_audits には同一レース・同一モデルの最新リビジョン
だけを渡す。古い予想は一切変更しない。正式的中率と実購入損益は未確認。

## 2026-11-08 既存の保存・結果照合への接続（PR #103内）

- `race_ai/keirin_private_spool.py` の既存個人用処理に、
  **任意の `odds/*.json` 段階**を追加。既存 `pre/` の8点予想保存が
  終わった後で実行する。オッズ未供給でも元の8点処理は継続する。
- `scripts/keirin_private_agent.py` に、本人保存の非楽天オッズ入力
  用ゲートを追加。既存サイトへ新規HTTPアクセスは行わない。
  本人による保存と、自動取得・転載・再利用の権利は同一ではない。
- `race_ai/keirin_variable_integration.py` で、**既存と同じ個人専用
  SQLite**に3つの追加テーブルを作る：
  `variable_odds_snapshots`、`variable_selections`、
  `variable_selection_audits`。
  事前オッズ全券（7車なら210組合せ）・当時の選定・結果リビジョン別
  の仮想収支を別々に保持する。予想原本と既存監査テーブルは変更しない。
- 同レース・同モデルの原本SHA256と予想Top8を、元のソースから
  再計算した研究モデルに照合。元予想とは別の可変買い目を
  create-onlyで確定し、保存した後にSQLiteを再読込してSHAを確認する。
- 結果は従来の `results/` → `result_revisions` に記録され、
  既存Top8監査に加えて可変選定の監査をリビジョン単位で追記する。
  結果訂正時も過去の予想は変更しない。
- `PrivateVariableLedger.compare_latest(race_id,model_id)` で、
  **8点固定×各100円**と**可変点数×各100円**を同一の確定結果で
  比較する。投資・払戻・収支・回収率は全て架空購入の参考値。
  `aggregate()` は最後の結果改訂のみを集計。最新改訂の監査が
  欠けていたら `latest_revision_reconciled=False` として隠さない。

### 接続済みのローカル処理順

`daily/`（任意）→ `results/`（結果受信と旧／新監査）
→ `pre/`（事前入力から8点原本を非公開保存）
→ `odds/`（事前オッズから0～12点を別保存）。

既存CLI：
```bash
python3 -m scripts.keirin_private_agent \
  --db "$HOME/.race-ai/private/owner.sqlite3" \
  --inbox "$HOME/.race-ai/private" \
  --personal-only
```

`odds/*.json` は
`RACE_AI_KEIRIN_TRIFECTA_ODDS_SNAPSHOT_V1` スキーマで
`race_id`, `captured_at`（タイムゾーン付き）,
`source_ref`, `source_rights_ref`, `prices`（全3連単の
`triple` と `decimal_odds`）を含める。8点原本保存後で、
締切より60秒以上前に全券を入力する必要がある。
ファイル監視は既存ループ `--loop` のオプションで実行できるが、
GitHub Actions上での私有DBの持続性は未解決なので、
短命runnerを永続保存先と誤認しない。

### 自動回帰テスト

```bash
python3 -m unittest -v \
  tests.test_keirin_variable_selection \
  tests.test_keirin_variable_integration \
  tests.test_keirin_private_spool \
  tests.test_keirin_private_agent
```

架空7車・架空オッズに限定。0／1／2／8／12点、締切後拒否、
重複・NaN・不足券、SHA取り違え、事前原本を維持したままの
SQLite読み戻し、架空払い戻し、見送り・返還、改訂後収支、
8点固定との比較、原本保護、旧パイプラインの回帰を検証。

### まだ未完成の本番GOAL

- 非楽天の実出走表・オッズの条件適合な**自動供給元と入手経路**。
- 実際の締切前に保存した全レースのオッズと、外部独立時刻の証明。
- 既存の未学習・未校正モデルを十分な実レースで検証・校正すること。
- 公式結果の真正性確認と、全保存期間に対する自動再照合の実証。
- GitHub上での秘密鍵保護・暗号化状態の安全な継続保存と読み戻し。
- UI反映と、現実の的中率・参考回収率の測定。

**このPR内では、既存の個人用ローカル保存／結果監査にコードを接続済み。**
ただし正式本番・無人実データ自動取得・収益性が完成したという意味ではない。
データ権利、実購入、公開・課金、外部サービスへの送信は追加していない。

## 2026-11-08 過去の参考成績・全保存履歴の検証（追加）

- `race_ai/keirin_reference_history_recheck.py` は、オーナーが手元で保存
  した**3つの派生研究レポート**を全レースID・8点原本・掲載着順・掲載配当
  の順で照合する。1レースでも不一致なら参考合計を報告せず失敗する。
  3ファイルは同じ元資料から派生しているので、**独立した3データ提供元による
  確認ではない**。公式結果の認証・締切前の第三者証明も不可能。
- `scripts/keirin_reference_history_audit.py` では、持ち主だけが保存
  している3つのJSONのファイル名を引数として渡す。通信なし・
  原本更新なし・原本データの出力なしで、件数・的中率・参考投資額・
  掲載配当による参考回収率・買い目の欠落分類だけを表示する。
- `race_ai/keirin_variable_integration.py` の
  `PrivateVariableLedger.reconcile_saved_history()` は同じ個人用
  SQLiteの既存可変予想**全レース・全保存結果リビジョン**を再照合する。
  重複せず何度でも再実行でき、オッズなしや予想未保存の欠落数を
  隠さない。結果の改訂を過去の予想に上書きしない。
- `scripts/keirin_variable_reconcile_private.py` は存在する非公開SQLite
  に対して、この再照合を実行する。空のDBを新規作成せず、GitHub
  Actionsの一時ディスク上の私有永続保存を仮定しない。

```bash
python3 -m scripts.keirin_reference_history_audit \
  --owner-reference-a /private/research/history_a.json \
  --owner-reference-b /private/research/history_b.json \
  --owner-reference-c /private/research/history_c.json

python3 -m scripts.keirin_variable_reconcile_private \
  --db /private/race-ai/owner.sqlite3 --owner-private-research
```

**合成試験が通っただけで「実レース正式的中率・回収率」にはしない。**
実際の保存済み研究レポートを再計算しても、独立した予想時刻の原本・
主催者の公式確定結果（返還・同着・取消・全訂正）の確定検証・
既存モデルの独立確率校正・合法なデータフィードが欠けている限り
`formal_hit_rate` / `formal_return_rate` はnullのままにする。

加えて、歴史的な8点参照予想に事後のオッズを投入して0〜12点を
後付けで再選択してはならない。可変方式の比較は**同じ未来レースの
締切前に両方の選定を別々に凍結できた実績**だけで評価する。
