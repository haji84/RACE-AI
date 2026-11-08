# KEIRIN: 許諾済み情報の自動取り込み→347項目監査→既存PR71モデル接続

更新：2026-11-08。設計・テスト正本は PR #101（Issue #67）。

## 1. 今回実装した入出力

- `race_ai/keirin_preflight.py`：レース32項目＋選手1人45項目。7車は347件、9車は437件。**項目の確認状態を全件記録**。
- `race_ai/keirin_allowed_delivery.py`：**既に提供された許諾済みデータ**を照合し、全項目の監査を作り、信頼できる値だけ既存PR71モデルの必要な数値形式に正規化する。
- `race_ai/keirin_permissioned_owner.py`：非公開の許諾根拠ファイルのSHA-256・権限用途・期間・正確なURL範囲を検査し、許諾元から事前に供給された生データを非公開フォルダーへ**作成専用でステージング**する。HTTPアクセスなし。
- `scripts/keirin_permissioned_owner_agent.py`：許諾済みデータが `inbox/raw/*.json` に到着すると、同じ監査・正規化コードを使って `inbox/pre/` に投入する。従来の `KeirinPrivateSpool` と**既存の `PR71` モデル**・SQLite予想原本・結果照合を利用。2分間隔のローカル監視を構成可能。
- `tests/test_keirin_allowed_delivery.py` と `tests/test_keirin_permissioned_owner.py`：架空データでモデル実行、権限否認、欠測、締切、変更版の衝突をテスト。架空の情報源は実際のライセンスの証拠ではない。

**注意：すべての347項目がモデルの数値特徴量になるわけではない。** 競輪の全ての前提を監査し、計算できる値だけを既存PR71の必須/任意特徴量に写像する。ライン、欠場歴、コメント等の定性的情報は情報源検証に利用し、モデルがまだ数値化していないものは監査のみ。未実装を「使った」と偽らない。

## 2. 実データ自動取得を開始しない理由

### 2026-11-08に確認した情報源のサイトポリシー

| 情報源 | 確認したこと | 今回の自動取得判定 |
|---|---|---|
| KEIRIN.JP | 公式サイトの複製・転用は私的使用等の法定例外に制限 | 自動取り込みの利用許諾は別途確認が必要 |
| 楽天グループ/楽天Kドリームス | 明示許可のないクローラー、抽出・データマイニング等を禁止 | 無許可のサイト巡回を追加しない |
| netkeirin | 私的利用の範囲外の複製・利用、営利準備等に制限 | 自動大量取得の権限は未確認 |
| 気象庁 | 原則PDL 1.0。CSV等を提供するが過度の機械アクセスを控えるよう案内 | 規約と取得方式・出典・観測時刻・バンクへの代表性を確認した提供データに限る |
| 独自・直接契約フィード | 提供元、対象用途、保存/解析、商用範囲、量、期間が契約で決まる | 契約の範囲が検証できたものだけ投入 |

参照：
- https://keirin.jp/pc/dfw/portal/guest/policy/index.html
- https://corp.rakuten.co.jp/copyright/
- https://keirin.netkeiba.com/info/kiyaku/
- https://www.jma.go.jp/jma/kishou/info/coment.html
- https://www.data.jma.go.jp/risk/obsdl/

**公開されている=自動収集・学習・再配信が許可されている、ではない。**
機械処理自体の権限、二次利用、個人利用/将来販売向け範囲、権利者、アクセス方式は別に検証する。

## 3. 必須の非公開情報源設定

**GitHubの公開ブランチ・PR・Issueに生データ、認証情報、個人の予想原本、契約書原本をアップロードしない。**

オーナーが内容・発行者・許諾範囲・有効期限を実際に確認した契約書等を、非公開ディスク上に保管する。設定マニフェストは以下の構造。

```json
{
  "schema": "RACE_AI_KEIRIN_OPERATOR_LICENSE_MANIFEST_V1",
  "bundle_id": "OWNER-APPROVED-SOURCE-BUNDLE-ID",
  "grants": [{
    "source_url_prefix": "https://licensed.example.invalid/approved-path/",
    "rights_ref": "LICENSE-REFERENCE-FROM-ACTUAL-PROVIDER",
    "purposes": ["schedule", "pre_race", "analysis", "model_inference", "private_retention"],
    "valid_from": "2030-01-01T00:00:00+09:00",
    "valid_until": "2030-01-31T23:59:59+09:00",
    "license_document_path": "/private/licenses/provider-agreement.txt",
    "license_document_sha256": "SHA256_OF_ACTUAL_OWNER_HELD_DOCUMENT"
  }]
}
```

上記は説明用の架空のURL/参照IDであり、実在の許諾ではない。**SHA一致は文書の改変チェックであり、文書内容の法的有効性や提供元の真正性まで自動証明するものではない。** 確認前に設定を有効にしない。

提供元から承認済みの `RACE_AI_KEIRIN_PERMISSIONED_DELIVERY_V1` JSONパケットが `inbox/raw` に到着すると、オーナー側の常時実行環境で取り込み可能。必ず今後のレースの締切前に公開・取得されたデータを使う。実データフィーダーがまだ存在しないので、現時点では自動着信はゼロ。

ローカルで実行する場合（ライセンスの実確認、非公開の永続環境が前提）：

```bash
python3 -m scripts.keirin_permissioned_owner_agent \
  --db /private/race-ai/owner.sqlite3 \
  --inbox /private/race-ai/inbox \
  --grant-manifest /private/licenses/manifest.json \
  --operator-reviewed-licenses \
  --loop --interval-seconds 120
```

GitHub Actions の一時ディスクで実行する場合は、**既存の暗号化永続状態を正当に復旧できること**が必要。プライベート永続ボリュームの確認がない状態では停止。現在のコードをGitHubへコミットするだけで上記プロセスが24時間動作するわけではない。

## 4. 対応済みゲートと検証待ち

- 対応：全項目（347/437）の状態自動作成、欠損/権限不明の明示、提供済み情報から対応する既存モデル特徴量への変換、締切後情報の拒否、本人・車番・ライン・改訂・締切の基本整合検証、入力スナップショットのSHA連結、最大8点・過去予想不変の既存ルートへの接続。
- 未接続：権利者の**実在する適法なリアルタイム配信**、未正規化または定性の全項目をモデルの予測精度に寄与させる実証済み変換、現実の勝ち上がり規則の全開催自動照合、当日選手の公表されない体調、実際の外部時刻証明。
- 未実証：実開催の全レースで入力→凍結→公式結果→PDCAの無人完走、先行するA/B両モデルの未来成績と参考損益、主KPIの実測98％。
- 予想成功を主張できるのは、合法なフィードを含む**実データの条件が全て充足したレースのみ**。欠測を0扱い、結果後の予想、正規化の事後学習によるリーク、オッズ混入は禁止。

## 5. 完成判定

「347項目を全部**確認した**」は、全347項目の状態・理由が記録された時点。
「347項目の**実測値が全部収集済み**」は、そのレースで実際に全347項目が確認可能で、許諾・時点が満たされた場合だけ。
「モデル入力に**反映済み**」は、それぞれの項目とモデル特徴量の入力対応、変換式、出力SHA、実推論使用、未来評価の証拠がある場合だけ。監査だけの項目をモデル使用済みとは数えない。

この区別を、今後の差分報告・UI・学習記録でも保持する。
