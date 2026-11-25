# 選手詳細分析指示書の引継ぎと展開独立採点 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. The owner requested continued implementation without routine approval stops.

**Goal:** 指示書の全項目を既存実装と照合し、着順的中と展開一致を分離する動く採点経路を既存研究採点へ接続する。

**Architecture:** PR #327 の既存研究モデル、凍結原本、`keirin_forward_score.score` を再利用する。展開観測は別ファイルとし、凍結予想のSHAへ結び、既存の着順集計を変更せず追加の集計を返す。欠測・ユーザー申告・正式に確認した観測を分ける。

**Tech Stack:** Python standard library / existing unittest / existing GitHub CI.

**Spec:** ユーザー提示「RACE-AI 選手詳細分析・戦術予測・着順確率・展開PDCA強化 開発指示書」全27節と末尾の追加6能力。リポジトリ内の保存先は `docs/KEIRIN_DETAILED_DEVELOPMENT_SPEC_20261125.md`。

## Global Constraints

- 正本 `haji84/RACE-AI`。GitHubのみ。Cloudflare/Vercel/新規課金/権限変更/投票は行わない。
- 旧A/B/C方針、私有原本、AES、SHA、別runner読戻し、保護されたmainとレビューを保全する。
- ユーザー観察は独立確認前に公式・映像確認済みへ昇格させない。
- 着順の的中だけで展開のA判定を作らない。未観測を一致として数えない。
- 今回は全国の未観測能力を推定値で埋めず、全体完成・精度改善を主張しない。

## Review Focus

- 元予想に展開が保存されていない場合、後付け展開は正式採点されない。
- 一部局面だけの一致やゴール一致が「全展開一致」を生まない。
- ユーザー観察とAI推定だけで正式B/D判定を確定しない。
- 車番の重複、別レース、SHA不一致、時刻不整合を拒否する。
- 複数シナリオから実結果に近いものを事後選択しない。

### Task 1: 独立採点を既存研究経路に接続

**Files:** Create `race_ai/keirin_flow_evaluation.py`, `tests/test_keirin_flow_evaluation.py`; modify `scripts/keirin_forward_score.py`, `tests/test_keirin_forward_score.py` and existing persistent-core CI test command.

**Interfaces:** `summarize_flow(predictions, observations, *, forecast_sha256, receipt, orders_by_race, starters_by_race)` consumes SHA-verified predictions, the original receipt, separate observations and already admitted result orders. Reuses `keirin_form_fall_blind_pdca.compare_race_development`; produces count-only research/reference A–E categories and denominators, no forecast orders.

- [x] Write tests for A/B/C/D/E, partial observations, missing original flow, source categories, invalid identity/hash/time, no result and unchanged legacy scoring.
- [x] Run `python -m unittest tests.test_keirin_flow_evaluation tests.test_keirin_forward_score -q`; confirm missing implementation fails.
- [x] Implement the evaluator and optional `flow_observations_raw` / `--flow-observations` input. Bind to original SHA; no edits to saved originals.
- [x] Run targeted and existing related regressions (147 passed before review). Commit with the related specification/evidence, so relative documentation links resolve in the commit.

### Task 2: 実レース検証と継続可能な引継ぎ

**Files:** Create the spec, `docs/KEIRIN_DEVELOPMENT_ACCEPTANCE_20261125.md`, safe source-check evidence and user-observation case. Link from existing handoff/latest-status docs.

**Interfaces:** Reuses Task 1 evaluator for a clearly retrospective/reference case; no fabricated pre-cutoff forecast receipt.

- [x] Read latest main/PR/CI/runtime logs and published site. Use ordinary approved source requests; retain raw bodies privately only.
- [x] Record user-observed initial order, initiative and attack order without unobserved positions/speeds/times. Preserve the conversation prediction as reference if no original is restored.
- [x] Run the real reference case; report formal count zero when original/independent evidence is missing.
- [x] Save all 27 requirement groups, additional six abilities, concrete existing paths, missing acceptance evidence and next executable work.
- [ ] Verify links, diff, regressions and source preservation. Update existing PR #327 through normal fast-forward only; no merge or model promotion.

## Progress

- Baseline `main`: `2d4a87c43795af5aaaa966603c9e5a634fb67759`.
- Inherited PR #327 HEAD: `c058c3cf5640661244c8cbef8c21c387c03eca02` (376 existing changed files; preserve all).
- Existing baseline: 23 forward-score/cohort-score/rider-context tests passed.
- Ruling: Work on the dedicated local branch from PR #327, preserving the clean `work` branch. No new worktree is necessary for this managed workspace.
- Ruling: A source category plus hash remains a producer attestation, not independent authentication. The scorer reports that boundary explicitly; formal production admission remains outside this component.
- Ruling: The public forecast is a different record from the conversation prediction (top-one differs; top-four includes the reported result). Preserve both identities and add zero formal performance races from the conversation case.
- Source check: secondary two-source 5-3-1 match, source bodies private; video not independently watched. Published 75-race asset SHA matches the inherited publication receipt.
- Task 1/2 interface check: observation facts bind to the unchanged original prediction SHA. The retrospective case uses canonical `compare_race_development` with conversation_reference scope, without manufacturing a pre-cutoff receipt.
- Ruling: During work PR #327 advanced to `345f0ac8`; integrate all 27 new paths and reuse its `compare_race_development`. Remove the duplicate classifier. Cost if wrong: the optional research adapter would duplicate or diverge from the canonical PDCA, so regression tests now exercise the shared function.
- Final review: independent reviewer reproduced post-cutoff normalization admission, initial-prefix inconsistency, and compatible-partial-source conflicts. The latter two are handled by the shared canonical comparator; the adapter separately refuses late normalized bytes. Regression tests cover all three.
- Review minor addressed by consolidation: a supplied conversation flow is never labeled a restored original; reference scope has no formal grade and contributes zero formal races.
- Broad keirin discovery before integration: 1,549 tests, 1 failure, 8 errors, 11 skipped. Seven errors require missing legacy pinned modules, one requires Playwright Chromium. The failure was a negative fixture created as 0700 under umask0077 instead of intended 0755; explicit chmod fixes the fixture, without changing runtime permissions or code.
