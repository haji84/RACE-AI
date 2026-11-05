# 艇愛履歴接続 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task.

**Goal:** 既存予想モデルに、許諾・照合・時点を確認した実履歴を渡す。
**Architecture:** 艇愛専用の厳格な形式境界→既存公式B/K解析器との照合→既存missing-awareモデル入力。HTTP待機と履歴平均の算出は既存処理を再利用する。
**Tech Stack:** Python standard library, SQLite, AES-256-GCM (cryptography), existing unittest/Actions.
**Spec:** User's 2026-11-05 development instructions; docs/TEIAI_HISTORY_INTEGRATION.md records implementation boundaries.

## Global Constraints

- Cloudflare/Vercel/new external services/Copilot/CodeRabbit禁止。
- PR71を使用。main非統合、モデル不変、予想原本・結果・SHA不変。
- 個人研究・短期非公開保存のみ。原API再配布、学習、自動切替はしない。
- 1日3 GETをAPI全体の保守的ローカル上限にする。明確な公式数値制限ではない。
- 現在取得した履歴を過去予想時点の可用データと偽らない。

## Review Focus

- CSVが登録番号を持たない: URL/profileだけで公式照合済みにしない。
- 決まり手CSVは本人勝利だけ: 敗者に勝者の手を推測しない。
- 同着/異常結果: 通常6着順モデルへ黙って変換しない。
- 再起動/同時実行/エラー: GET前に永続quotaを消費し、欠落状態をresetしない。
- キャッシュ改変・未来取得: 復号/hash/時点の検査失敗で停止。

### Task 1: Parse and reconcile
Files: race_ai/teiai_history.py, race_ai/teiai_official_reconciliation.py, tests/test_teiai_history.py.
- [x] Write synthetic format, identity, special result, dedup and mismatch tests; run RED.
- [x] Implement parse_history_csv(raw, racer_id, source_url), parse_race_json(raw, race_id), parse_racer_json(raw, racer_id).
- [x] Reuse pinned official parsers, method_of, _blocks; compare racer, frame, course, ST, finish, method, payouts with explicit missing denominators.
- [x] Run focused tests GREEN and actual local files. Retain only counts/hash evidence publicly.

### Task 2: Private bounded collection
Files: race_ai/teiai_collection.py, tests/test_teiai_collection.py, requirements-history.txt.
- [x] Write tests for restart quota, concurrency, failure, Retry-After, corrupt cache, rights denial, encryption, expiry; run RED.
- [x] Implement AES-GCM encrypted append-only version cache + durable request ledger. Reuse plan_http_wait/wait_active. No redirects, retries inline, plaintext artifacts, periodic tasks or automated permission flags.
- [x] Verify encrypted restore and identical cached readback without further HTTP.

### Task 3: Existing model adapter and CI
Files: race_ai/teiai_feature_adapter.py, tests/test_teiai_feature_adapter.py, existing .github/workflows/forecast-audit-ui.yml.
- [x] Write tests for capture/store/verification/as-of/cutoff order, insufficient samples, unverified rows, post-result backtest refusal and missing/model contracts; run RED.
- [x] Reuse observed_result_history._features and strict existing model validator. Add only admitted recent/course numeric history; retain denominators, windows and sources. No motor-cycle aggregation without independent cycle evidence.
- [x] Add isolated existing CI job for synthetic tests (no provider network, no key for real data). Full Python regression + existing model harness.
- [x] Review branch, push only PR71, verify Actions exact HEAD, document real evidence and outstanding gates.

## Execution ledger

Baseline: 61 relevant existing tests PASS at 0b400636041f435754d8d6c0c2c48ef7faaf6ab4.
Ruling: owner explicitly requests implementation through Actions, so proceed with specified scope without additional design approval. Use existing PR71 worktree; do not bring unrelated work branch changes into it.
Ruling: no production integration or live prediction until data rights and independent timing proof are established. A future race is a separate real-time acceptance gate, never simulated.

Task 1: implemented; synthetic format/official tests RED→GREEN; actual CSV 4470, 2 races/7 unique entries and payouts10 matched.
Task 2: implemented; synthetic quota/restart/crypto/failure tests RED→GREEN. Real owner-key handoff not verified.
Task 3: adapter/probe/CI implemented; synthetic native 6-racer two-model integration RED→GREEN. Full regression 1264 tests, 14 skips, zero failures before last payout/probe additions. Exact-head final CI pending.

Final review: independent reviewer identified 6 important issues. All fixed with reproductions RED→GREEN: special finishes, opportunity windows, missing winner methods, wrong-key new URLs, authenticated quota/retention, postcommit availability clocks. Focused suite 33 tests passed. Minor documentation of partial supplementation corrected. No model file changed.

Final focused suite: 34 tests PASS (synthetic); additional known-F opportunity, concurrent reservation, authenticated expiry and provider special-note retention verified.
