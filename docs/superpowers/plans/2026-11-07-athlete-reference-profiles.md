# Athlete Reference Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement task-by-task. Steps use checkbox syntax.

**Goal:** 空の選手カルテを、公式の基本情報・期別成績・6コース成績と、出走コースに応じた根拠付きの参考シナリオで埋める。

**Architecture:** 既存の公式期別資料パーサーを使い、公開された選手資料のみの静的カタログを作る。レース側に名前と登録番号しかなくても、既存イラストと同じ厳密な照合で資料を読めるようにする。期別資料と現在のレースの取得値は分け、保存予想を書き換えない。

**Tech Stack:** existing Python official term parser, static JSON/JavaScript, native browser UI, Node/Playwright tests, existing GitHub Pages refresh.

**Spec:** 前回承認された `docs/superpowers/specs/2026-11-07-race-navigation-profile-design.md` の選手情報を実データへ接続する修正。ユーザーは追加で「得意コース」「出走コース時の展開予想」を依頼。既存の実装・公開承認の範囲で進める。

## Global Constraints

- GitHubのみ。Cloudflare/Vercel/新たなサービスや課金・権限を追加しない。
- 予想原本・鍵・SQLite・結果原文を公開しない。暗号化された既存ビューと所有者リンクを保持する。
- 選手名・登録番号の照合、合成データの隔離、イラスト1,669名の対応を保持する。
- 公式資料の集計期間・取得時点・出走数を明示。0と未収録を区別する。
- 期別成績を古いレースの当時の入力へコピーしない。成績集計後のレースに対する参考シナリオだけを示す。
- 検証用の出走例は架空レース。実際の予想精度や全レース取得の証明にしない。

## Review Focus

- レースに登録番号と名前しかなくても本物の公式資料が表示されること。
- 新人・未収録の選手は基本情報を示し、実績を創作しないこと。
- コース成績の分母はコース出走数。失格等を除いた着順件数の合計へ置き換えないこと。
- 枠番を確定した進入コースと呼ばず、展示進入と仮定を区別すること。
- 過去レースに後日を含む期別集計で予想を付けないこと。相手比較は矛盾のない進入対応と同じ期別・十分な件数の時だけ行うこと。

## Task 1: 公式資料カタログ

**Files:** `race_ai/racer_profiles.py`, `scripts/build_racer_profiles.py`, `web/data/racer-profiles.json`, `web/racer-profiles-data.js`, `tests/test_racer_profiles.py`.

**Interfaces:** `parse_basic_profile(raw, registration, expected_name)` validates official HTML identity. `build_catalogue(term_rows, portraits, basic_profiles, current_grades, source)` produces all 1,669 portrait identities, public basic metadata and nullable period stats with six explicit course records. `FILES` lists the three static profile assets.

- [x] Add failing tests for no race-side statistics, counts/denominators, zero samples, rookies and rejected basic-profile identities.
- [x] Implement extraction with existing `boat_racer_term` and bounded official HTML parsing; record source hashes. Official fan2604 data matches the current official season/course page sampled on 2026-11-07; fan2610 is not yet available.
- [x] Build deterministic JSON/data module and verify 1,669 entries, 1,643 term rows and remaining 26 basic profiles. Run Python tests and commit.

## Task 2: コース成績・参考シナリオ API

**Files:** `web/racer-profiles.js`, `tests/racer_profiles.test.cjs`.

**Interfaces:** `get(race, person)` uses existing portrait identity gates. `preferredCourses(profile)` ranks courses with 10+ starts by two-place rate minus the same-term whole-catalogue course baseline; falls back to explicitly labeled within-racer ranking. `scenario(race, person, course, {entryMap})` returns conditional course paths, own measured values and eligible adjacent-racer comparisons. No win probabilities or new saved tickets.

- [x] Add failing tests for all 6 courses, sparse/zero records, synthetic/mismatched identities, historical-data cutoff, entry conflicts and real-source sampled values.
- [x] Implement exact course counts and cautious conditional descriptions. A selected alternate course is hypothetical unless a complete, identity-bound exhibition map establishes positions; do not invent opponents' positions.
- [x] Run Node tests and commit.

## Task 3: カルテへの接続と配布

**Files:** `web/app.js`, `web/index.html`, `web/style.css`, `race_ai/saved_pages.py`, `race_ai/saved_pdca_view.py`, `race_ai/local_forecast_server.py`, relevant browser/packaging tests.

- [x] Reproduce the original bug using name/ID-only participants and assert populated real basic/period/course data in the browser before implementing.
- [x] Show official references before empty race-specific groups; retain nonempty saved values in separate sections. Add course cards, preferred-course basis and an explicit course selector with reference scenarios.
- [x] Load the new modules in ordinary, local and offline views. Allow a validated old Pages manifest to gain the new profile assets while retaining all cipher bytes and required original files.
- [x] Run browser cases at 320/390/1440px, profile/portrait/identity tests, saved-view packaging and WebCrypto/browser regressions. Update the existing UI workflow; commit.

## Task 4: 確認・公開

- [x] Request one fresh read-only whole-change review; reproduce and fix material findings with tests.
- [x] Preserve concurrent source changes, update the existing PR and publish through the existing Pages refresh. Verify all ciphertext and portrait assets unchanged and deployed sparse-participant cards populated.
- [x] Record source coverage, public-data dates and deployed verification. Complete the plan and report the actual available information and reference-scenario limits.
