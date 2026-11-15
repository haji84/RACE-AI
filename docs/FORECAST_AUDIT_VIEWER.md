# RACE-AI 予想と確定結果の照合ビュー（4競技） v0.1
関連Issue: #67・#68。開発ブランチはPR #69の合成E2Eを土台にした分離Draft。PR #62既存のボート画面には変更を加えない。UI設計はPR #62の紺/白/青緑とスマホ対応を参考にした。

## 実装済み（この差分）
- `web/forecast-audit.html` を開くと、同一オリジンの `web/data/2026-10-22-forecast-audit.json` から**実際にGitHub監査保存された322レース枠の暫定台帳**を閲覧できる構成。内訳は以前保存した228枠と追加94枠。両者のrace_idは固有で重複ゼロ。この322件は**全開催を正式確定した実レース数ではない**。
- レース単位で競技、会場、R、締切時刻、予想の最大8点、保存時刻、モデル版、根拠、予想ハッシュ、3連単確定結果、的中マーク、未予想理由を表示。競技/状態/会場検索の絞り込みが可能。
- 集計は **全件台帳数と、3連単発売済みで正式結果が評価可能なレース数を分離**。後者の分母には未予想や保存証拠不足も含む。結果がない場合Hit@8は「未検証」（null）、0%とはしない。モデルバージョン別・場別成績などは将来の実資料を受けて拡張。
- 各競技の入力は厳密なJSONスキーマ。3連単上限8点・重複券/同一着順艇/選手不可・市場依存なし・生成/保存/締切時刻・SHA形式・外部レシート申告を検査し、不一致は的中へ加算しない。ブラウザ内では**真正性・署名自体は検証しない**。
- 4競技で表示の動作を試す `web/data/example-synthetic-forecast-audit.json` は2030年の架空データ。合成だけの切替ボタンを明示し、**実測精度には流用できない**。
- 既存予想元データの外部取得なし。利用許諾/保存/学習の権限を増やさない。CSPは同一オリジンに限定、外部送信・広告・自動投票・課金・一般公開/Production変更なし。

## JSON構造（記録用の読み取り専用Projection）
```json
{
  "schema": "RACE_AI_FORECAST_AUDIT_V1",
  "dataset_status": "REAL_REPORTED",
  "event_date_jst": "YYYY-MM-DD",
  "records": [{
    "race_id": "sport:date:venue:race",
    "sport": "boat",
    "venue": "venue",
    "race_no": 1,
    "cutoff_at": "YYYY-MM-DDTHH:MM:SS+09:00",
    "offering_status": "TRIFECTA_OFFERED",
    "race_status": "final",
    "prediction": {
      "ordered_top8": [[1,2,3]],
      "generated_at": "YYYY-MM-DDTHH:MM:SS+09:00",
      "persisted_at": "YYYY-MM-DDTHH:MM:SS+09:00",
      "cutoff_at": "YYYY-MM-DDTHH:MM:SS+09:00",
      "input_sha256": "(64 hex)",
      "prediction_sha256": "(64 hex)",
      "model_version": "version-id",
      "odds_independent": true,
      "external_receipt_verified": true,
      "rationale": "short grounded explanation",
      "evidence_url": "https://..."
    },
    "result": {
      "status": "final",
      "winning_combinations": [[1,2,3]],
      "confirmed_at": "YYYY-MM-DDTHH:MM:SS+09:00"
    },
    "no_forecast_reason": null
  }]
}
```
このJSONは**読み取り用投影**であって元のappend-only台帳ではない。読み取り用の値・外部検証フラグを捏造して精度を上げることは禁止。実データ投入は信頼済みのレース日程・公式結果・独立予想レシートから生成し、基礎イベントを不変保持する。

## 重大な未達・正式Doneまでの順番
1. **当日全開催・全レース発見**（前日夜から、締切昇順、公式との完全照合、未収録を報告）。現在322枠は部分台帳。
2. **適法な実データ取得と正本保存**：出走・過去成績・直前環境・締切を用途別許諾したソースのみ。PR #69は`SYNTHETIC_ONLY`で、実レースを拒否する。既存権利未確認ソースの制限を回避しない。
3. **実レースの予想を外部時刻付きで不変凍結**：モデルバージョン・入力ハッシュ・全候補/上位8点・`persisted_at < sales_cutoff_at`・再取得/署名・冪等性・誤取得時のNO_FORECAST。
4. **公式確定結果・同着・返還・取消・改訂のappend-only照合**：判定可能/不可を分け、旧予想を変更しない。
5. **このビューへの自動データ供給**：独立検証した保存/結果イベントを日付別・スポーツ別の静的またはAPI投影へ変換し、別途アクセス制御と権利検査を実施。UIのファイル選択だけで全自動とは主張しない。
6. **iPhone Safari実機**：画面・タップ・フィルター・日付切替と外部レシートリンクを検証。現在はソースとCIテストの段階。
7. **精度**：全発売/評価可能レース（未予想含む）Hit@8_allを未来の未使用レースで計測し、98%以上の再現を証明。98%未達なら製品最終GOAL未達。合成試験の的中数を実績に転用しない。

## 起動 / 検査
同じフォルダをHTTPの同一オリジンで配信し `web/forecast-audit.html` を開く。外部APIは呼ばない。同一オリジンの監査台帳を読み、JSON手動取込も可能。ファイルを直接開く場合、ブラウザのローカルfetch制約で自動読込に失敗し得るので明示的にJSON選択する。

Node 18以降: `node --test tests/forecast_audit.test.cjs`
CI: `.github/workflows/forecast-audit-ui.yml` は開発PR向けのみ。既存PR #69のPython36テストとは別。
独立コード/セキュリティ/データ監査、正確なhead CI、main統合、実データE2E、実機確認は完了確認までDraftを維持。

## 既存UIとの統合
PR #62はボート先行の現行モックUI。衝突を避け、予想照合のモデルを単体モジュールとして隔離。統合段階に `成績分析` と `全レース` のナビへリンクし、モデル/データ契約を一元化する。PR #62の古い手動購入成績と本照合のAI予測精度を混ぜない。
